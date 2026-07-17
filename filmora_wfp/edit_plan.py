"""Versioned, declarative edit plans for proven Filmora project mutations."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, TypedDict, Union

from .analysis import WFP_TICKS_PER_SECOND, list_titles
from .archive import WfpArchive, WfpError
from .evals import evaluate_project
from .title_cards import clone_title_cards
from .title_text import preflight_title_text_replacement, replace_title_text


EDIT_PLAN_SCHEMA_VERSION = 2
EDIT_PLAN_API_VERSION = 2
SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS = (1, 2)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PLAIN_DECIMAL_RE = re.compile(r"^(?:0|[0-9]+(?:\.[0-9]+)?|0?\.[0-9]+)$")

Pathish = Union[os.PathLike[str], str]
PlanInput = Union["EditPlan", Mapping[str, Any], Pathish]


class EditPlanSource(TypedDict):
    filename: str
    sha256: str
    filmora_version: Optional[str]
    os: Optional[str]


class EditTargetsResult(TypedDict):
    api_version: int
    source: EditPlanSource
    supported_operations: List[str]
    title_card_templates: List[Dict[str, Any]]
    title_text_targets: List[Dict[str, Any]]


class EditPlanExplanation(TypedDict):
    api_version: int
    plan_schema_version: int
    status: str
    writes_performed: bool
    description: Optional[str]
    source: EditPlanSource
    preflight: Dict[str, bool]
    operations: List[Dict[str, Any]]
    filmora_round_trip: Dict[str, bool]


class EditPlanApplicationResult(TypedDict):
    api_version: int
    plan_schema_version: int
    status: str
    writes_performed: bool
    source: EditPlanSource
    output: str
    operations: List[Dict[str, Any]]
    created_cards: List[Dict[str, Any]]
    verification: Dict[str, bool]


@dataclass(frozen=True)
class TitleCardTemplateSelector:
    """Resolve a title-card template from the current source project."""

    timeline_id: Optional[int] = None
    heading: Optional[str] = None
    subheading: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        if self.timeline_id is not None:
            return {"timeline_id": self.timeline_id}
        return {"heading": self.heading, "subheading": self.subheading}


@dataclass(frozen=True)
class TitleCardSpec:
    """One title card normalized to the exact values accepted by the writer."""

    start_ticks: int
    position_unit: str
    position_value: Union[int, str]
    heading: str
    subheading: str
    heading_font_size: Decimal
    heading_scale_x: Decimal
    subheading_font_size: Decimal
    subheading_scale_x: Decimal

    def writer_spec(self) -> Dict[str, Any]:
        return {
            "start_ticks": self.start_ticks,
            "heading": self.heading,
            "subheading": self.subheading,
            "heading_font_size": self.heading_font_size,
            "heading_scale_x": self.heading_scale_x,
            "subheading_font_size": self.subheading_font_size,
            "subheading_scale_x": self.subheading_scale_x,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "at": {self.position_unit: self.position_value},
            "resolved_start_ticks": self.start_ticks,
            "heading": self.heading,
            "subheading": self.subheading,
            "heading_font_size": str(self.heading_font_size),
            "heading_scale_x": str(self.heading_scale_x),
            "subheading_font_size": str(self.subheading_font_size),
            "subheading_scale_x": str(self.subheading_scale_x),
        }


@dataclass(frozen=True)
class CloneTitleCardsOperation:
    """Clone one verified compound title-card template one or more times."""

    operation_id: str
    template: TitleCardTemplateSelector
    cards: Tuple[TitleCardSpec, ...]


@dataclass(frozen=True)
class ReplaceTitleTextOperation:
    """Replace one existing title while preserving its serialized byte length."""

    operation_id: str
    clip_uid: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class EditPlan:
    """A parsed edit plan whose fields have already passed strict validation."""

    schema_version: int
    source_sha256: str
    operations: Tuple[Union[CloneTitleCardsOperation, ReplaceTitleTextOperation], ...]
    description: Optional[str] = None


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WfpError("{0} must be a JSON object".format(label))
    return value


def _only_keys(value: Mapping[str, Any], allowed: Sequence[str], label: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise WfpError("{0} has unknown field(s): {1}".format(label, ", ".join(unknown)))


def _non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WfpError("{0} must be non-empty text".format(label))
    return value


def _positive_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise WfpError("{0} must be a positive decimal number".format(label))
    if isinstance(value, str) and not _PLAIN_DECIMAL_RE.fullmatch(value):
        raise WfpError("{0} must be a positive decimal number".format(label))
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise WfpError("{0} must be a positive decimal number".format(label)) from exc
    if not result.is_finite() or result <= 0:
        raise WfpError("{0} must be a positive decimal number".format(label))
    return result


def _parse_position(value: Any, label: str) -> Tuple[int, str, Union[int, str]]:
    position = _object(value, label)
    _only_keys(position, ("ticks", "seconds"), label)
    if len(position) != 1:
        raise WfpError("{0} must contain exactly one of ticks or seconds".format(label))
    if "ticks" in position:
        ticks = position["ticks"]
        if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
            raise WfpError("{0}.ticks must be a non-negative integer".format(label))
        return ticks, "ticks", ticks

    raw_seconds = position["seconds"]
    if isinstance(raw_seconds, bool) or not isinstance(raw_seconds, (int, float, str, Decimal)):
        raise WfpError("{0}.seconds must be a non-negative decimal number".format(label))
    if isinstance(raw_seconds, str) and not _PLAIN_DECIMAL_RE.fullmatch(raw_seconds):
        raise WfpError("{0}.seconds must be a non-negative decimal number".format(label))
    try:
        seconds = Decimal(str(raw_seconds))
    except InvalidOperation as exc:
        raise WfpError("{0}.seconds must be a non-negative decimal number".format(label)) from exc
    if not seconds.is_finite() or seconds < 0:
        raise WfpError("{0}.seconds must be a non-negative decimal number".format(label))
    ticks_decimal = seconds * WFP_TICKS_PER_SECOND
    if ticks_decimal != ticks_decimal.to_integral_value():
        raise WfpError("{0}.seconds exceeds Filmora's 100 ns tick precision".format(label))
    return int(ticks_decimal), "seconds", str(seconds)


def _parse_selector(value: Any, label: str) -> TitleCardTemplateSelector:
    selector = _object(value, label)
    _only_keys(selector, ("timeline_id", "heading", "subheading"), label)
    if "timeline_id" in selector:
        if set(selector) != {"timeline_id"}:
            raise WfpError("{0} must use timeline_id or heading/subheading, not both".format(label))
        timeline_id = selector["timeline_id"]
        if isinstance(timeline_id, bool) or not isinstance(timeline_id, int) or timeline_id < 0:
            raise WfpError("{0}.timeline_id must be a non-negative integer".format(label))
        return TitleCardTemplateSelector(timeline_id=timeline_id)
    if set(selector) != {"heading", "subheading"}:
        raise WfpError("{0} must contain heading and subheading".format(label))
    return TitleCardTemplateSelector(
        heading=_non_empty_text(selector["heading"], "{0}.heading".format(label)),
        subheading=_non_empty_text(selector["subheading"], "{0}.subheading".format(label)),
    )


def _parse_card(value: Any, index: int) -> TitleCardSpec:
    label = "operations[0].cards[{0}]".format(index)
    card = _object(value, label)
    fields = (
        "at",
        "heading",
        "subheading",
        "heading_font_size",
        "heading_scale_x",
        "subheading_font_size",
        "subheading_scale_x",
    )
    _only_keys(card, fields, label)
    missing = [field for field in fields if field not in card]
    if missing:
        raise WfpError("{0} is missing field(s): {1}".format(label, ", ".join(missing)))
    start_ticks, position_unit, position_value = _parse_position(card["at"], "{0}.at".format(label))
    return TitleCardSpec(
        start_ticks=start_ticks,
        position_unit=position_unit,
        position_value=position_value,
        heading=_non_empty_text(card["heading"], "{0}.heading".format(label)),
        subheading=_non_empty_text(card["subheading"], "{0}.subheading".format(label)),
        heading_font_size=_positive_decimal(
            card["heading_font_size"], "{0}.heading_font_size".format(label)
        ),
        heading_scale_x=_positive_decimal(
            card["heading_scale_x"], "{0}.heading_scale_x".format(label)
        ),
        subheading_font_size=_positive_decimal(
            card["subheading_font_size"], "{0}.subheading_font_size".format(label)
        ),
        subheading_scale_x=_positive_decimal(
            card["subheading_scale_x"], "{0}.subheading_scale_x".format(label)
        ),
    )


def _parse_plan(value: Any) -> EditPlan:
    document = _object(value, "edit plan")
    _only_keys(document, ("schema_version", "description", "source", "operations"), "edit plan")
    schema_version = document.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS
    ):
        raise WfpError(
            "Unsupported edit-plan schema_version: {0}; expected one of {1}".format(
                schema_version,
                ", ".join(str(version) for version in SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS),
            )
        )
    description = document.get("description")
    if description is not None:
        description = _non_empty_text(description, "edit plan.description")

    source = _object(document.get("source"), "edit plan.source")
    _only_keys(source, ("sha256",), "edit plan.source")
    source_sha256 = source.get("sha256")
    if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256):
        raise WfpError("edit plan.source.sha256 must be a 64-character SHA-256 digest")

    raw_operations = document.get("operations")
    if not isinstance(raw_operations, list) or len(raw_operations) != 1:
        raise WfpError(
            "Edit plans require exactly one operation"
        )
    raw_operation = _object(raw_operations[0], "operations[0]")
    operation_name = raw_operation.get("op")
    operation_id = raw_operation.get("id", "operation-1")
    operation_id = _non_empty_text(operation_id, "operations[0].id")
    if operation_name == "clone_title_cards":
        _only_keys(raw_operation, ("id", "op", "template", "cards"), "operations[0]")
        raw_cards = raw_operation.get("cards")
        if not isinstance(raw_cards, list) or not raw_cards:
            raise WfpError("operations[0].cards must be a non-empty array")
        cards = tuple(_parse_card(card, index) for index, card in enumerate(raw_cards))
        operation: Union[CloneTitleCardsOperation, ReplaceTitleTextOperation]
        operation = CloneTitleCardsOperation(
            operation_id=operation_id,
            template=_parse_selector(raw_operation.get("template"), "operations[0].template"),
            cards=cards,
        )
    elif operation_name == "replace_title_text" and schema_version == 2:
        _only_keys(raw_operation, ("id", "op", "target", "new_text"), "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(target, ("clip_uid", "text"), "operations[0].target")
        operation = ReplaceTitleTextOperation(
            operation_id=operation_id,
            clip_uid=_non_empty_text(
                target.get("clip_uid"), "operations[0].target.clip_uid"
            ),
            old_text=_non_empty_text(target.get("text"), "operations[0].target.text"),
            new_text=_non_empty_text(raw_operation.get("new_text"), "operations[0].new_text"),
        )
        if operation.new_text == operation.old_text:
            raise WfpError("operations[0].new_text must differ from the current text")
    else:
        raise WfpError("Unsupported edit operation: {0}".format(operation_name))
    return EditPlan(
        schema_version=schema_version,
        source_sha256=source_sha256.lower(),
        operations=(operation,),
        description=description,
    )


def _validate_typed_plan(plan: EditPlan) -> EditPlan:
    """Keep manually constructed public dataclasses behind the same safety gate."""

    if (
        isinstance(plan.schema_version, bool)
        or plan.schema_version not in SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS
    ):
        raise WfpError(
            "Unsupported edit-plan schema_version: {0}; expected one of {1}".format(
                plan.schema_version,
                ", ".join(str(version) for version in SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS),
            )
        )
    if not isinstance(plan.source_sha256, str) or not _SHA256_RE.fullmatch(plan.source_sha256):
        raise WfpError("edit plan.source.sha256 must be a 64-character SHA-256 digest")
    if plan.description is not None:
        _non_empty_text(plan.description, "edit plan.description")
    if not isinstance(plan.operations, tuple) or len(plan.operations) != 1:
        raise WfpError("Edit plans require exactly one operation")
    operation = plan.operations[0]
    if not isinstance(operation, (CloneTitleCardsOperation, ReplaceTitleTextOperation)):
        raise WfpError("Unsupported typed edit operation")
    _non_empty_text(operation.operation_id, "operations[0].id")
    if isinstance(operation, ReplaceTitleTextOperation):
        if plan.schema_version != 2:
            raise WfpError("replace_title_text requires edit-plan schema version 2")
        _non_empty_text(operation.clip_uid, "operations[0].target.clip_uid")
        _non_empty_text(operation.old_text, "operations[0].target.text")
        _non_empty_text(operation.new_text, "operations[0].new_text")
        if operation.new_text == operation.old_text:
            raise WfpError("operations[0].new_text must differ from the current text")
        return plan
    if not isinstance(operation, CloneTitleCardsOperation):
        raise WfpError("Unsupported typed edit operation")
    selector = operation.template
    if not isinstance(selector, TitleCardTemplateSelector):
        raise WfpError("operations[0].template must be a TitleCardTemplateSelector")
    if selector.timeline_id is not None:
        if (
            isinstance(selector.timeline_id, bool)
            or not isinstance(selector.timeline_id, int)
            or selector.timeline_id < 0
            or selector.heading is not None
            or selector.subheading is not None
        ):
            raise WfpError("Typed template selector must use timeline_id or heading/subheading")
    elif (
        not isinstance(selector.heading, str)
        or not selector.heading.strip()
        or not isinstance(selector.subheading, str)
        or not selector.subheading.strip()
    ):
        raise WfpError("Typed template selector must contain heading and subheading")
    if not isinstance(operation.cards, tuple) or not operation.cards:
        raise WfpError("operations[0].cards must be non-empty")
    for index, card in enumerate(operation.cards):
        label = "operations[0].cards[{0}]".format(index)
        if not isinstance(card, TitleCardSpec):
            raise WfpError("{0} must be a TitleCardSpec".format(label))
        if isinstance(card.start_ticks, bool) or not isinstance(card.start_ticks, int) or card.start_ticks < 0:
            raise WfpError("{0}.start_ticks must be a non-negative integer".format(label))
        _non_empty_text(card.heading, "{0}.heading".format(label))
        _non_empty_text(card.subheading, "{0}.subheading".format(label))
        _positive_decimal(card.heading_font_size, "{0}.heading_font_size".format(label))
        _positive_decimal(card.heading_scale_x, "{0}.heading_scale_x".format(label))
        _positive_decimal(card.subheading_font_size, "{0}.subheading_font_size".format(label))
        _positive_decimal(card.subheading_scale_x, "{0}.subheading_scale_x".format(label))
        if card.position_unit == "ticks":
            if card.position_value != card.start_ticks:
                raise WfpError("{0}.at does not match resolved start_ticks".format(label))
        elif card.position_unit == "seconds":
            ticks, _unit, _value = _parse_position(
                {"seconds": card.position_value}, "{0}.at".format(label)
            )
            if ticks != card.start_ticks:
                raise WfpError("{0}.at does not match resolved start_ticks".format(label))
        else:
            raise WfpError("{0}.position_unit must be ticks or seconds".format(label))
    return plan


def load_edit_plan(value: PlanInput) -> EditPlan:
    """Load and strictly validate a supported edit plan from a path or mapping."""

    if isinstance(value, EditPlan):
        return _validate_typed_plan(value)
    if isinstance(value, Mapping):
        return _parse_plan(value)
    if not isinstance(value, (str, os.PathLike)):
        raise WfpError("Edit plan must be an EditPlan, JSON object, or filesystem path")
    path = Path(value).expanduser().resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, json.JSONDecodeError) as exc:
        raise WfpError("Cannot read edit plan: {0}".format(exc)) from exc
    return _parse_plan(document)


def edit_plan_schema(version: int = EDIT_PLAN_SCHEMA_VERSION) -> Dict[str, Any]:
    """Return a new dictionary containing one bundled immutable JSON Schema."""

    if version not in SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS:
        raise WfpError("Unsupported edit-plan schema version: {0}".format(version))

    raw = (
        resources.files("filmora_wfp.schemas")
        .joinpath("edit-plan-v{0}.schema.json".format(version))
        .read_text(encoding="utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise WfpError("Bundled edit-plan schema is not a JSON object")
    return value


def project_sha256(path: Pathish) -> str:
    """Return the byte-level SHA-256 used as an edit-plan precondition."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise WfpError("Cannot fingerprint project: {0}".format(exc)) from exc
    return digest.hexdigest()


def _iter_clips(timeline: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    clips: List[Mapping[str, Any]] = []
    tracks = timeline.get("trackInfos")
    if not isinstance(tracks, list):
        return clips
    for track in tracks:
        if not isinstance(track, Mapping) or not isinstance(track.get("clipList"), list):
            continue
        clips.extend(clip for clip in track["clipList"] if isinstance(clip, Mapping))
    return clips


def _title_rows(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timelines = document.get("timelineInfos")
    if not isinstance(timelines, list):
        return rows
    for timeline in timelines:
        if not isinstance(timeline, Mapping):
            continue
        for clip in _iter_clips(timeline):
            script_buffer = clip.get("scriptBuf")
            if clip.get("type") != 4 or not isinstance(script_buffer, str):
                continue
            try:
                script = json.loads(script_buffer)
            except json.JSONDecodeError:
                continue
            text = script.get("Text") if isinstance(script, dict) else None
            if isinstance(text, str) and text.strip():
                position_y = script.get("PosY")
                text_data = script.get("TextData")
                basic: Mapping[str, Any] = {}
                if (
                    isinstance(text_data, list)
                    and text_data
                    and isinstance(text_data[0], Mapping)
                    and isinstance(text_data[0].get("Basic"), Mapping)
                ):
                    basic = text_data[0]["Basic"]
                rows.append(
                    {
                        "text": text,
                        "position_y": position_y if isinstance(position_y, (int, float)) else None,
                        "font": basic.get("FontName"),
                        "font_size": basic.get("FontSize"),
                        "scale_x": script.get("ScaleX"),
                        "scale_y": script.get("ScaleY"),
                    }
                )
    rows.sort(
        key=lambda row: (
            row["position_y"] is None,
            row["position_y"] if row["position_y"] is not None else 0,
            row["text"],
        )
    )
    return rows


def _title_card_targets(path: Pathish) -> Tuple[EditPlanSource, List[Dict[str, Any]]]:
    source_path = Path(path).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp":
        raise WfpError("Edit targets currently require a .wfp source, not a bundle")
    with WfpArchive(source_path) as archive:
        project = archive.project_info()
        main_member = archive.main_timeline_member()
        main = archive.read_json(main_member)
        current_id = main.get("currentTimelineId")
        timelines = main.get("timelineInfos")
        if not isinstance(timelines, list):
            raise WfpError("Main project has no timelineInfos")
        current = next(
            (
                timeline
                for timeline in timelines
                if isinstance(timeline, Mapping) and timeline.get("timelineId") == current_id
            ),
            None,
        )
        if current is None:
            raise WfpError("Cannot find the current main timeline")

        placements: Dict[Any, List[Dict[str, Any]]] = {}
        current_tracks = current.get("trackInfos")
        if not isinstance(current_tracks, list):
            current_tracks = []
        for track in current_tracks:
            if not isinstance(track, Mapping) or not isinstance(track.get("clipList"), list):
                continue
            for clip in track["clipList"]:
                if not isinstance(clip, Mapping) or clip.get("timelineId") is None:
                    continue
                placements.setdefault(clip["timelineId"], []).append(
                    {"track_type": track.get("trackType"), "clip": clip}
                )

        targets: List[Dict[str, Any]] = []
        for member, document in archive.timeline_documents():
            if member == main_member:
                continue
            timeline_id = document.get("currentTimelineId")
            if not isinstance(timeline_id, int):
                continue
            titles = _title_rows(document)
            paired_entries = placements.get(timeline_id, [])
            paired = [entry["clip"] for entry in paired_entries]
            track_types = {entry["track_type"] for entry in paired_entries}
            durations = {
                clip.get("outPoint")
                for clip in paired
                if isinstance(clip.get("outPoint"), int) and clip.get("outPoint") > 0
            }
            if (
                len(titles) != 2
                or len(paired) != 2
                or track_types != {1, 2}
                or len(durations) != 1
            ):
                continue
            starts = sorted(
                {
                    clip.get("tlBegin")
                    for clip in paired
                    if isinstance(clip.get("tlBegin"), int)
                }
            )
            targets.append(
                {
                    "target_type": "compound_title_card_template",
                    "selector": {
                        "heading": titles[0]["text"],
                        "subheading": titles[1]["text"],
                    },
                    "template_metrics": {
                        "heading": {
                            key: titles[0].get(key)
                            for key in ("font", "font_size", "scale_x", "scale_y")
                        },
                        "subheading": {
                            key: titles[1].get(key)
                            for key in ("font", "font_size", "scale_x", "scale_y")
                        },
                    },
                    "resolved_timeline_id": timeline_id,
                    "duration_ticks": next(iter(durations)),
                    "current_start_ticks": starts,
                }
            )
        targets.sort(
            key=lambda target: (
                target["current_start_ticks"][0] if target["current_start_ticks"] else 0,
                target["resolved_timeline_id"],
            )
        )
        source = {
            "filename": archive.path.name,
            "sha256": project_sha256(archive.path),
            "filmora_version": project.get("project_editor_modify_version"),
            "os": project.get("project_os_name"),
        }
        return source, targets


def list_edit_targets(path: Pathish) -> EditTargetsResult:
    """List targets currently supported by the declarative edit-plan API."""

    source, targets = _title_card_targets(path)
    title_targets: List[Dict[str, Any]] = []
    seen_title_targets = set()
    for title in list_titles(path):
        clip_uid = title.get("clip_uid")
        current_text = title.get("text")
        if not isinstance(clip_uid, str) or not isinstance(current_text, str) or not current_text:
            continue
        key = (clip_uid, current_text)
        if key in seen_title_targets:
            continue
        seen_title_targets.add(key)
        title_targets.append(
            {
                "target_type": "existing_title_text",
                "selector": {"clip_uid": clip_uid, "text": current_text},
                "timeline_id": title.get("timeline_id"),
                "track_index": title.get("track_index"),
                "clip_index": title.get("clip_index"),
                "font": title.get("font"),
                "font_size": title.get("font_size"),
                "scale_x": (title.get("scale") or {}).get("x"),
                "serialized_length_constraint": "replacement must preserve scriptBuf UTF-8 bytes",
            }
        )
    title_targets.sort(
        key=lambda target: (
            target.get("timeline_id") if isinstance(target.get("timeline_id"), int) else -1,
            target.get("track_index") if isinstance(target.get("track_index"), int) else -1,
            target.get("clip_index") if isinstance(target.get("clip_index"), int) else -1,
            target["selector"]["text"],
        )
    )
    return {
        "api_version": EDIT_PLAN_API_VERSION,
        "source": source,
        "supported_operations": ["clone_title_cards", "replace_title_text"],
        "title_card_templates": targets,
        "title_text_targets": title_targets,
    }


def _resolve_template(
    selector: TitleCardTemplateSelector,
    targets: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if selector.timeline_id is not None:
        matches = [
            target
            for target in targets
            if target.get("resolved_timeline_id") == selector.timeline_id
        ]
    else:
        matches = [
            target
            for target in targets
            if target.get("selector")
            == {"heading": selector.heading, "subheading": selector.subheading}
        ]
    if not matches:
        raise WfpError("Title-card template selector did not match the current source project")
    if len(matches) > 1:
        raise WfpError(
            "Title-card template selector is ambiguous; use the current timeline_id selector"
        )
    return matches[0]


def _resolve_title_text(
    operation: ReplaceTitleTextOperation,
    targets: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    selector = {"clip_uid": operation.clip_uid, "text": operation.old_text}
    matches = [target for target in targets if target.get("selector") == selector]
    if not matches:
        raise WfpError("Title-text selector did not match the current source project")
    if len(matches) > 1:
        raise WfpError("Title-text selector is ambiguous in the current source project")
    return matches[0]


def explain_edit_plan(source: Pathish, plan: PlanInput) -> EditPlanExplanation:
    """Resolve and validate an edit plan without writing a project."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp":
        raise WfpError("Edit plans currently require a .wfp source, not a bundle")
    parsed = load_edit_plan(plan)
    actual_sha256 = project_sha256(source_path)
    if actual_sha256 != parsed.source_sha256.lower():
        raise WfpError(
            "Source fingerprint changed: expected {0}, found {1}".format(
                parsed.source_sha256, actual_sha256
            )
        )

    evaluation = evaluate_project(source_path)
    if not evaluation.get("valid"):
        failed = [
            probe.get("name")
            for probe in evaluation.get("probes") or []
            if probe.get("required") and not probe.get("passed")
        ]
        raise WfpError(
            "Source project failed required format probes: {0}".format(
                ", ".join(str(name) for name in failed) or "unknown probe"
            )
        )

    targets_result = list_edit_targets(source_path)
    if targets_result["source"]["sha256"] != actual_sha256:
        raise WfpError("Source project changed while the edit plan was being explained")
    operation = parsed.operations[0]
    if isinstance(operation, ReplaceTitleTextOperation):
        target = _resolve_title_text(operation, targets_result["title_text_targets"])
        text_preflight = preflight_title_text_replacement(
            source_path,
            clip_uid=operation.clip_uid,
            old_text=operation.old_text,
            new_text=operation.new_text,
        )
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {
                "source_sha256_matches": True,
                "format_eval_valid": True,
            },
            "operations": [
                {
                    "id": operation.operation_id,
                    "op": "replace_title_text",
                    "requested_target": {
                        "clip_uid": operation.clip_uid,
                        "text": operation.old_text,
                    },
                    "resolved_target": dict(target),
                    "new_text": operation.new_text,
                    "serialized_length_preserved": text_preflight[
                        "serialized_length_preserved"
                    ],
                    "matching_archive_occurrences": text_preflight[
                        "matching_occurrences"
                    ],
                }
            ],
            "filmora_round_trip": {
                "required": True,
                "performed": False,
            },
        }

    if not isinstance(operation, CloneTitleCardsOperation):
        raise WfpError("Unsupported typed edit operation")
    target = _resolve_template(operation.template, targets_result["title_card_templates"])
    duration_ticks = target.get("duration_ticks")
    if not isinstance(duration_ticks, int) or duration_ticks <= 0:
        raise WfpError("Resolved title-card template has an invalid duration")
    planned_ranges = sorted(
        (card.start_ticks, card.start_ticks + duration_ticks) for card in operation.cards
    )
    for previous, current in zip(planned_ranges, planned_ranges[1:]):
        if current[0] < previous[1]:
            raise WfpError(
                "Planned title cards overlap: {0}-{1} and {2}-{3}".format(
                    previous[0], previous[1], current[0], current[1]
                )
            )
    explained_cards: List[Dict[str, Any]] = []
    for card in operation.cards:
        explained = card.to_dict()
        explained["resolved_end_ticks"] = card.start_ticks + duration_ticks
        explained_cards.append(explained)
    return {
        "api_version": EDIT_PLAN_API_VERSION,
        "plan_schema_version": parsed.schema_version,
        "status": "ready",
        "writes_performed": False,
        "description": parsed.description,
        "source": targets_result["source"],
        "preflight": {
            "source_sha256_matches": True,
            "format_eval_valid": True,
        },
        "operations": [
            {
                "id": operation.operation_id,
                "op": "clone_title_cards",
                "requested_template": operation.template.to_dict(),
                "resolved_template": dict(target),
                "cards": explained_cards,
            }
        ],
        "filmora_round_trip": {
            "required": True,
            "performed": False,
        },
    }


def apply_edit_plan(
    source: Pathish,
    output: Pathish,
    plan: PlanInput,
) -> EditPlanApplicationResult:
    """Apply the currently proven operation to a new project copy."""

    output_path = Path(output).expanduser().resolve()
    if output_path.suffix.lower() != ".wfp":
        raise WfpError("Edit-plan output must use the .wfp extension")
    parsed = load_edit_plan(plan)
    explanation = explain_edit_plan(source, parsed)
    operation = parsed.operations[0]
    if isinstance(operation, ReplaceTitleTextOperation):
        writer_result = replace_title_text(
            source,
            output,
            clip_uid=operation.clip_uid,
            old_text=operation.old_text,
            new_text=operation.new_text,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards: List[Dict[str, Any]] = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, CloneTitleCardsOperation):
        resolved = explanation["operations"][0]["resolved_template"]
        writer_result = clone_title_cards(
            source,
            output,
            template_timeline_id=resolved["resolved_timeline_id"],
            cards=[card.writer_spec() for card in operation.cards],
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = writer_result["created_cards"]
        audit_valid = bool((writer_result.get("copy_audit") or {}).get("valid"))
    else:
        raise WfpError("Unsupported typed edit operation")
    return {
        "api_version": EDIT_PLAN_API_VERSION,
        "plan_schema_version": parsed.schema_version,
        "status": "applied",
        "writes_performed": True,
        "source": explanation["source"],
        "output": str(output_path),
        "operations": explanation["operations"],
        "created_cards": created_cards,
        "verification": {
            "source_aware_audit_valid": audit_valid,
            "filmora_round_trip_required": True,
            "filmora_round_trip_performed": False,
        },
    }
