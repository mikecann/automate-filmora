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
from .audio_fade import preflight_clip_fade_in, replace_clip_fade_in
from .archive import WfpArchive, WfpError
from .evals import evaluate_project
from .linked_av import (
    _normal_speed_state,
    move_linked_av_pair,
    preflight_linked_av_end_trim,
    preflight_linked_av_move,
    trim_linked_av_pair_end,
)
from .linked_av_start_trim import (
    preflight_linked_av_start_trim,
    trim_linked_av_pair_start,
)
from .linked_av_split import (
    _linked_userdata_id,
    preflight_linked_av_split,
    split_linked_av_pair,
)
from .rotation import preflight_clip_rotation, replace_clip_rotation
from .title_cards import clone_title_cards
from .title_text import preflight_title_text_replacement, replace_title_text
from .transitions import (
    preflight_linked_transition,
    remove_linked_transition,
    replace_linked_transition_duration,
)
from .volume import preflight_clip_volume_gain, replace_clip_volume_gain


EDIT_PLAN_SCHEMA_VERSION = 7
EDIT_PLAN_API_VERSION = 7
SUPPORTED_EDIT_PLAN_SCHEMA_VERSIONS = (1, 2, 3, 4, 5, 6, 7)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PLAIN_DECIMAL_RE = re.compile(r"^(?:0|[0-9]+(?:\.[0-9]+)?|0?\.[0-9]+)$")
_SIGNED_DECIMAL_RE = re.compile(r"^-?(?:0|[0-9]+(?:\.[0-9]+)?|0?\.[0-9]+)$")
_VIDEO_TRANSITION_ID = "2981D185-D52E-44f4-ABD5-3CE83890E32E"
_AUDIO_TRANSITION_ID = "audio/blender/transition-fade"

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
    rotation_targets: List[Dict[str, Any]]
    volume_gain_targets: List[Dict[str, Any]]
    fade_in_targets: List[Dict[str, Any]]
    linked_transition_targets: List[Dict[str, Any]]
    linked_av_targets: List[Dict[str, Any]]


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
class ReplaceClipRotationOperation:
    """Replace one existing visual clip Rotation parameter."""

    operation_id: str
    clip_uid: str
    old_rotation: Decimal
    new_rotation: Decimal


@dataclass(frozen=True)
class ReplaceClipVolumeGainOperation:
    """Replace one existing audio clip VolumeGain parameter."""

    operation_id: str
    clip_uid: str
    old_volume_gain: Decimal
    new_volume_gain: Decimal


@dataclass(frozen=True)
class ReplaceClipFadeInOperation:
    """Replace one existing audio clip FadeInTime parameter."""

    operation_id: str
    clip_uid: str
    old_fade_in: Decimal
    new_fade_in: Decimal


@dataclass(frozen=True)
class ReplaceLinkedTransitionDurationOperation:
    """Replace the duration of one observed linked transition pair."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    old_duration_ticks: int
    new_duration_ticks: int


@dataclass(frozen=True)
class RemoveLinkedTransitionOperation:
    """Remove one observed linked transition pair."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    expected_duration_ticks: int


@dataclass(frozen=True)
class MoveLinkedAvPairOperation:
    """Move one transition-free linked A/V pair within declared duration."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    old_start_ticks: int
    old_end_ticks: int
    new_start_ticks: int


@dataclass(frozen=True)
class TrimLinkedAvPairStartOperation:
    """Shorten the start of one forward 1x linked A/V pair."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    old_start_ticks: int
    old_end_ticks: int
    new_start_ticks: int


@dataclass(frozen=True)
class TrimLinkedAvPairEndOperation:
    """Shorten the end of one forward 1x linked A/V pair."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    old_start_ticks: int
    old_end_ticks: int
    new_end_ticks: int


@dataclass(frozen=True)
class SplitLinkedAvPairOperation:
    """Split one forward 1x linked A/V pair at an interior timeline tick."""

    operation_id: str
    video_clip_uid: str
    audio_clip_uid: str
    old_start_ticks: int
    old_end_ticks: int
    split_ticks: int


EditOperation = Union[
    CloneTitleCardsOperation,
    ReplaceTitleTextOperation,
    ReplaceClipRotationOperation,
    ReplaceClipVolumeGainOperation,
    ReplaceClipFadeInOperation,
    ReplaceLinkedTransitionDurationOperation,
    RemoveLinkedTransitionOperation,
    MoveLinkedAvPairOperation,
    TrimLinkedAvPairStartOperation,
    TrimLinkedAvPairEndOperation,
    SplitLinkedAvPairOperation,
]


@dataclass(frozen=True)
class EditPlan:
    """A parsed edit plan whose fields have already passed strict validation."""

    schema_version: int
    source_sha256: str
    operations: Tuple[EditOperation, ...]
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


def _finite_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise WfpError("{0} must be a finite decimal number".format(label))
    if isinstance(value, str) and not _SIGNED_DECIMAL_RE.fullmatch(value):
        raise WfpError("{0} must be a finite decimal number".format(label))
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise WfpError("{0} must be a finite decimal number".format(label)) from exc
    if not result.is_finite():
        raise WfpError("{0} must be a finite decimal number".format(label))
    return result


def _positive_ticks(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WfpError("{0} must be a positive integer tick count".format(label))
    return value


def _non_negative_ticks(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WfpError("{0} must be a non-negative integer tick count".format(label))
    return value


def _json_safe_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Preserve exact decimals as strings in public API results."""

    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in values.items()
    }


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
        operation: EditOperation = CloneTitleCardsOperation(
            operation_id=operation_id,
            template=_parse_selector(raw_operation.get("template"), "operations[0].template"),
            cards=cards,
        )
    elif operation_name == "replace_title_text" and schema_version in (2, 3, 4, 5, 6, 7):
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
    elif operation_name == "replace_clip_rotation" and schema_version in (3, 4, 5, 6, 7):
        _only_keys(raw_operation, ("id", "op", "target", "new_rotation"), "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(target, ("clip_uid", "rotation"), "operations[0].target")
        operation = ReplaceClipRotationOperation(
            operation_id=operation_id,
            clip_uid=_non_empty_text(
                target.get("clip_uid"), "operations[0].target.clip_uid"
            ),
            old_rotation=_finite_decimal(
                target.get("rotation"), "operations[0].target.rotation"
            ),
            new_rotation=_finite_decimal(
                raw_operation.get("new_rotation"), "operations[0].new_rotation"
            ),
        )
        if operation.new_rotation == operation.old_rotation:
            raise WfpError("operations[0].new_rotation must differ from the current rotation")
    elif operation_name == "replace_clip_volume_gain" and schema_version in (6, 7):
        _only_keys(raw_operation, ("id", "op", "target", "new_volume_gain"), "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(target, ("clip_uid", "volume_gain"), "operations[0].target")
        operation = ReplaceClipVolumeGainOperation(
            operation_id=operation_id,
            clip_uid=_non_empty_text(
                target.get("clip_uid"), "operations[0].target.clip_uid"
            ),
            old_volume_gain=_finite_decimal(
                target.get("volume_gain"), "operations[0].target.volume_gain"
            ),
            new_volume_gain=_finite_decimal(
                raw_operation.get("new_volume_gain"), "operations[0].new_volume_gain"
            ),
        )
        if operation.new_volume_gain == operation.old_volume_gain:
            raise WfpError(
                "operations[0].new_volume_gain must differ from the current volume gain"
            )
    elif operation_name == "replace_clip_fade_in" and schema_version == 7:
        _only_keys(raw_operation, ("id", "op", "target", "new_fade_in"), "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(target, ("clip_uid", "fade_in"), "operations[0].target")
        operation = ReplaceClipFadeInOperation(
            operation_id=operation_id,
            clip_uid=_non_empty_text(
                target.get("clip_uid"), "operations[0].target.clip_uid"
            ),
            old_fade_in=_positive_decimal(
                target.get("fade_in"), "operations[0].target.fade_in"
            ),
            new_fade_in=_positive_decimal(
                raw_operation.get("new_fade_in"), "operations[0].new_fade_in"
            ),
        )
        if operation.new_fade_in == operation.old_fade_in:
            raise WfpError(
                "operations[0].new_fade_in must differ from the current fade-in time"
            )
    elif operation_name in (
        "replace_linked_transition_duration",
        "remove_linked_transition",
    ) and schema_version in (3, 4, 5, 6, 7):
        allowed = (
            ("id", "op", "target", "new_duration_ticks")
            if operation_name == "replace_linked_transition_duration"
            else ("id", "op", "target")
        )
        _only_keys(raw_operation, allowed, "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(
            target,
            ("video_clip_uid", "audio_clip_uid", "duration_ticks"),
            "operations[0].target",
        )
        video_clip_uid = _non_empty_text(
            target.get("video_clip_uid"), "operations[0].target.video_clip_uid"
        )
        audio_clip_uid = _non_empty_text(
            target.get("audio_clip_uid"), "operations[0].target.audio_clip_uid"
        )
        duration_ticks = _positive_ticks(
            target.get("duration_ticks"), "operations[0].target.duration_ticks"
        )
        if operation_name == "replace_linked_transition_duration":
            new_duration_ticks = _positive_ticks(
                raw_operation.get("new_duration_ticks"),
                "operations[0].new_duration_ticks",
            )
            if new_duration_ticks == duration_ticks:
                raise WfpError(
                    "operations[0].new_duration_ticks must differ from the current duration"
                )
            operation = ReplaceLinkedTransitionDurationOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_duration_ticks=duration_ticks,
                new_duration_ticks=new_duration_ticks,
            )
        else:
            operation = RemoveLinkedTransitionOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                expected_duration_ticks=duration_ticks,
            )
    elif operation_name in (
        "move_linked_av_pair",
        "trim_linked_av_pair_start",
        "trim_linked_av_pair_end",
        "split_linked_av_pair",
    ) and schema_version in (4, 5, 6, 7):
        replacement_field = (
            "new_end_ticks"
            if operation_name == "trim_linked_av_pair_end"
            else "split_ticks"
            if operation_name == "split_linked_av_pair"
            else "new_start_ticks"
        )
        _only_keys(raw_operation, ("id", "op", "target", replacement_field), "operations[0]")
        target = _object(raw_operation.get("target"), "operations[0].target")
        _only_keys(
            target,
            ("video_clip_uid", "audio_clip_uid", "start_ticks", "end_ticks"),
            "operations[0].target",
        )
        video_clip_uid = _non_empty_text(
            target.get("video_clip_uid"), "operations[0].target.video_clip_uid"
        )
        audio_clip_uid = _non_empty_text(
            target.get("audio_clip_uid"), "operations[0].target.audio_clip_uid"
        )
        start_ticks = _non_negative_ticks(
            target.get("start_ticks"), "operations[0].target.start_ticks"
        )
        end_ticks = _positive_ticks(
            target.get("end_ticks"), "operations[0].target.end_ticks"
        )
        if end_ticks <= start_ticks:
            raise WfpError("operations[0].target must have a positive timeline range")
        replacement_ticks = _non_negative_ticks(
            raw_operation.get(replacement_field),
            "operations[0].{0}".format(replacement_field),
        )
        if operation_name == "move_linked_av_pair":
            if replacement_ticks == start_ticks:
                raise WfpError("operations[0].new_start_ticks must move the current range")
            operation = MoveLinkedAvPairOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_start_ticks=start_ticks,
                old_end_ticks=end_ticks,
                new_start_ticks=replacement_ticks,
            )
        elif operation_name == "trim_linked_av_pair_start":
            if not start_ticks < replacement_ticks < end_ticks:
                raise WfpError("operations[0].new_start_ticks must shorten the current range")
            operation = TrimLinkedAvPairStartOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_start_ticks=start_ticks,
                old_end_ticks=end_ticks,
                new_start_ticks=replacement_ticks,
            )
        elif operation_name == "trim_linked_av_pair_end":
            if not start_ticks < replacement_ticks < end_ticks:
                raise WfpError("operations[0].new_end_ticks must shorten the current range")
            operation = TrimLinkedAvPairEndOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_start_ticks=start_ticks,
                old_end_ticks=end_ticks,
                new_end_ticks=replacement_ticks,
            )
        else:
            if schema_version not in (5, 6, 7):
                raise WfpError("split_linked_av_pair requires edit-plan schema version 5 through 7")
            if not start_ticks < replacement_ticks < end_ticks:
                raise WfpError("operations[0].split_ticks must be inside the current range")
            operation = SplitLinkedAvPairOperation(
                operation_id=operation_id,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_start_ticks=start_ticks,
                old_end_ticks=end_ticks,
                split_ticks=replacement_ticks,
            )
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
    if not isinstance(
        operation,
        (
            CloneTitleCardsOperation,
            ReplaceTitleTextOperation,
            ReplaceClipRotationOperation,
            ReplaceClipVolumeGainOperation,
            ReplaceClipFadeInOperation,
            ReplaceLinkedTransitionDurationOperation,
            RemoveLinkedTransitionOperation,
            MoveLinkedAvPairOperation,
            TrimLinkedAvPairStartOperation,
            TrimLinkedAvPairEndOperation,
            SplitLinkedAvPairOperation,
        ),
    ):
        raise WfpError("Unsupported typed edit operation")
    _non_empty_text(operation.operation_id, "operations[0].id")
    if isinstance(operation, ReplaceTitleTextOperation):
        if plan.schema_version not in (2, 3, 4, 5, 6, 7):
            raise WfpError("replace_title_text requires edit-plan schema version 2 through 7")
        _non_empty_text(operation.clip_uid, "operations[0].target.clip_uid")
        _non_empty_text(operation.old_text, "operations[0].target.text")
        _non_empty_text(operation.new_text, "operations[0].new_text")
        if operation.new_text == operation.old_text:
            raise WfpError("operations[0].new_text must differ from the current text")
        return plan
    if isinstance(operation, ReplaceClipRotationOperation):
        if plan.schema_version not in (3, 4, 5, 6, 7):
            raise WfpError("replace_clip_rotation requires edit-plan schema version 3 through 7")
        _non_empty_text(operation.clip_uid, "operations[0].target.clip_uid")
        old_rotation = _finite_decimal(
            operation.old_rotation, "operations[0].target.rotation"
        )
        new_rotation = _finite_decimal(operation.new_rotation, "operations[0].new_rotation")
        if old_rotation == new_rotation:
            raise WfpError("operations[0].new_rotation must differ from the current rotation")
        return plan
    if isinstance(operation, ReplaceClipVolumeGainOperation):
        if plan.schema_version not in (6, 7):
            raise WfpError("replace_clip_volume_gain requires edit-plan schema version 6 or 7")
        _non_empty_text(operation.clip_uid, "operations[0].target.clip_uid")
        old_volume_gain = _finite_decimal(
            operation.old_volume_gain, "operations[0].target.volume_gain"
        )
        new_volume_gain = _finite_decimal(
            operation.new_volume_gain, "operations[0].new_volume_gain"
        )
        if old_volume_gain == new_volume_gain:
            raise WfpError(
                "operations[0].new_volume_gain must differ from the current volume gain"
            )
        return plan
    if isinstance(operation, ReplaceClipFadeInOperation):
        if plan.schema_version != 7:
            raise WfpError("replace_clip_fade_in requires edit-plan schema version 7")
        _non_empty_text(operation.clip_uid, "operations[0].target.clip_uid")
        old_fade_in = _positive_decimal(
            operation.old_fade_in, "operations[0].target.fade_in"
        )
        new_fade_in = _positive_decimal(
            operation.new_fade_in, "operations[0].new_fade_in"
        )
        if old_fade_in == new_fade_in:
            raise WfpError(
                "operations[0].new_fade_in must differ from the current fade-in time"
            )
        return plan
    if isinstance(
        operation,
        (ReplaceLinkedTransitionDurationOperation, RemoveLinkedTransitionOperation),
    ):
        if plan.schema_version not in (3, 4, 5, 6, 7):
            raise WfpError("Linked transition operations require edit-plan schema version 3 through 7")
        _non_empty_text(operation.video_clip_uid, "operations[0].target.video_clip_uid")
        _non_empty_text(operation.audio_clip_uid, "operations[0].target.audio_clip_uid")
        if isinstance(operation, ReplaceLinkedTransitionDurationOperation):
            old_duration = _positive_ticks(
                operation.old_duration_ticks, "operations[0].target.duration_ticks"
            )
            new_duration = _positive_ticks(
                operation.new_duration_ticks, "operations[0].new_duration_ticks"
            )
            if old_duration == new_duration:
                raise WfpError(
                    "operations[0].new_duration_ticks must differ from the current duration"
                )
        else:
            _positive_ticks(
                operation.expected_duration_ticks, "operations[0].target.duration_ticks"
            )
        return plan
    if isinstance(
        operation,
        (
            MoveLinkedAvPairOperation,
            TrimLinkedAvPairStartOperation,
            TrimLinkedAvPairEndOperation,
            SplitLinkedAvPairOperation,
        ),
    ):
        if isinstance(operation, SplitLinkedAvPairOperation):
            if plan.schema_version not in (5, 6, 7):
                raise WfpError("split_linked_av_pair requires edit-plan schema version 5 through 7")
        elif plan.schema_version not in (4, 5, 6, 7):
            raise WfpError("Linked A/V operations require edit-plan schema version 4 through 7")
        _non_empty_text(operation.video_clip_uid, "operations[0].target.video_clip_uid")
        _non_empty_text(operation.audio_clip_uid, "operations[0].target.audio_clip_uid")
        start_ticks = _non_negative_ticks(
            operation.old_start_ticks, "operations[0].target.start_ticks"
        )
        end_ticks = _positive_ticks(operation.old_end_ticks, "operations[0].target.end_ticks")
        if end_ticks <= start_ticks:
            raise WfpError("operations[0].target must have a positive timeline range")
        if isinstance(operation, MoveLinkedAvPairOperation):
            new_start = _non_negative_ticks(
                operation.new_start_ticks, "operations[0].new_start_ticks"
            )
            if new_start == start_ticks:
                raise WfpError("operations[0].new_start_ticks must move the current range")
        elif isinstance(operation, TrimLinkedAvPairStartOperation):
            new_start = _non_negative_ticks(
                operation.new_start_ticks, "operations[0].new_start_ticks"
            )
            if not start_ticks < new_start < end_ticks:
                raise WfpError("operations[0].new_start_ticks must shorten the current range")
        elif isinstance(operation, TrimLinkedAvPairEndOperation):
            new_end = _non_negative_ticks(
                operation.new_end_ticks, "operations[0].new_end_ticks"
            )
            if not start_ticks < new_end < end_ticks:
                raise WfpError("operations[0].new_end_ticks must shorten the current range")
        else:
            split_ticks = _non_negative_ticks(
                operation.split_ticks, "operations[0].split_ticks"
            )
            if not start_ticks < split_ticks < end_ticks:
                raise WfpError("operations[0].split_ticks must be inside the current range")
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


def _existing_effect_targets(
    path: Pathish,
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Discover only exact structures accepted by proven effect writers."""

    rotation_targets: List[Dict[str, Any]] = []
    volume_gain_targets: List[Dict[str, Any]] = []
    fade_in_targets: List[Dict[str, Any]] = []
    transition_targets: List[Dict[str, Any]] = []
    seen_rotations = set()
    seen_volume_gains = set()
    seen_fade_ins = set()
    seen_transitions = set()
    with WfpArchive(path) as archive:
        for _member, document in archive.timeline_documents():
            timelines = document.get("timelineInfos")
            if not isinstance(timelines, list):
                continue
            for timeline_index, timeline in enumerate(timelines):
                if not isinstance(timeline, Mapping):
                    continue
                timeline_id = timeline.get("timelineId")
                tracks = timeline.get("trackInfos")
                if not isinstance(tracks, list):
                    continue
                videos: Dict[Tuple[Any, ...], List[Tuple[int, int, Mapping[str, Any]]]] = {}
                audios: Dict[Tuple[Any, ...], List[Tuple[int, int, Mapping[str, Any]]]] = {}
                for track_index, track in enumerate(tracks):
                    if not isinstance(track, Mapping) or not isinstance(track.get("clipList"), list):
                        continue
                    track_type = track.get("trackType")
                    for clip_index, clip in enumerate(track["clipList"]):
                        if not isinstance(clip, Mapping):
                            continue
                        clip_uid = clip.get("thisUId")
                        if track_type == 1 and clip.get("type") == 1 and isinstance(clip_uid, str):
                            values: List[Decimal] = []
                            chains = clip.get("effectChainList")
                            if isinstance(chains, list):
                                for chain in chains:
                                    if not isinstance(chain, Mapping) or not isinstance(
                                        chain.get("effectList"), list
                                    ):
                                        continue
                                    for effect in chain["effectList"]:
                                        if (
                                            not isinstance(effect, Mapping)
                                            or effect.get("id") != "video/effect/transform"
                                            or not isinstance(effect.get("paramList"), list)
                                        ):
                                            continue
                                        for parameter in effect["paramList"]:
                                            fx_param = (
                                                parameter.get("fxParam")
                                                if isinstance(parameter, Mapping)
                                                else None
                                            )
                                            if (
                                                isinstance(parameter, Mapping)
                                                and parameter.get("name") == "Rotation"
                                                and isinstance(fx_param, Mapping)
                                                and "unValue" in fx_param
                                            ):
                                                try:
                                                    values.append(
                                                        _finite_decimal(
                                                            fx_param["unValue"], "Rotation"
                                                        )
                                                    )
                                                except WfpError:
                                                    pass
                            if len(values) == 1:
                                key = (clip_uid, values[0])
                                if key not in seen_rotations:
                                    seen_rotations.add(key)
                                    rotation_targets.append(
                                        {
                                            "target_type": "existing_clip_rotation",
                                            "selector": {
                                                "clip_uid": clip_uid,
                                                "rotation": str(values[0]),
                                            },
                                            "timeline_id": timeline_id,
                                            "timeline_index": timeline_index,
                                            "track_index": track_index,
                                            "clip_index": clip_index,
                                        }
                                    )

                        if track_type == 2 and clip.get("type") == 2 and isinstance(clip_uid, str):
                            values = []
                            chains = clip.get("effectChainList")
                            if isinstance(chains, list):
                                for chain in chains:
                                    if not isinstance(chain, Mapping) or not isinstance(
                                        chain.get("effectList"), list
                                    ):
                                        continue
                                    for effect in chain["effectList"]:
                                        if (
                                            not isinstance(effect, Mapping)
                                            or effect.get("id") != "audio/effect/volume"
                                            or not isinstance(effect.get("paramList"), list)
                                        ):
                                            continue
                                        for parameter in effect["paramList"]:
                                            fx_param = (
                                                parameter.get("fxParam")
                                                if isinstance(parameter, Mapping)
                                                else None
                                            )
                                            if (
                                                isinstance(parameter, Mapping)
                                                and parameter.get("name") == "VolumeGain"
                                                and isinstance(fx_param, Mapping)
                                                and "unValue" in fx_param
                                            ):
                                                try:
                                                    values.append(
                                                        _finite_decimal(
                                                            fx_param["unValue"], "VolumeGain"
                                                        )
                                                    )
                                                except WfpError:
                                                    pass
                            if len(values) == 1:
                                key = (clip_uid, values[0])
                                if key not in seen_volume_gains:
                                    seen_volume_gains.add(key)
                                    volume_gain_targets.append(
                                        {
                                            "target_type": "existing_clip_volume_gain",
                                            "selector": {
                                                "clip_uid": clip_uid,
                                                "volume_gain": str(values[0]),
                                            },
                                            "timeline_id": timeline_id,
                                            "timeline_index": timeline_index,
                                            "track_index": track_index,
                                            "clip_index": clip_index,
                                        }
                                    )

                            fade_values: List[Decimal] = []
                            if isinstance(chains, list):
                                for chain in chains:
                                    if not isinstance(chain, Mapping) or not isinstance(
                                        chain.get("effectList"), list
                                    ):
                                        continue
                                    for effect in chain["effectList"]:
                                        if (
                                            not isinstance(effect, Mapping)
                                            or effect.get("id") != "audio/effect/fade"
                                            or not isinstance(effect.get("paramList"), list)
                                        ):
                                            continue
                                        for parameter in effect["paramList"]:
                                            fx_param = (
                                                parameter.get("fxParam")
                                                if isinstance(parameter, Mapping)
                                                else None
                                            )
                                            if (
                                                isinstance(parameter, Mapping)
                                                and parameter.get("name") == "FadeInTime"
                                                and isinstance(fx_param, Mapping)
                                                and "unValue" in fx_param
                                            ):
                                                try:
                                                    fade_values.append(
                                                        _positive_decimal(
                                                            fx_param["unValue"], "FadeInTime"
                                                        )
                                                    )
                                                except WfpError:
                                                    pass
                            begin = clip.get("tlBegin")
                            end = clip.get("tlEnd")
                            if (
                                len(fade_values) == 1
                                and isinstance(begin, int)
                                and isinstance(end, int)
                                and end > begin
                            ):
                                duration = Decimal(end - begin) / WFP_TICKS_PER_SECOND
                                if fade_values[0] <= duration:
                                    key = (clip_uid, fade_values[0])
                                    if key not in seen_fade_ins:
                                        seen_fade_ins.add(key)
                                        fade_in_targets.append(
                                            {
                                                "target_type": "existing_clip_fade_in",
                                                "selector": {
                                                    "clip_uid": clip_uid,
                                                    "fade_in": str(fade_values[0]),
                                                },
                                                "max_fade_in": str(duration),
                                                "timeline_id": timeline_id,
                                                "timeline_index": timeline_index,
                                                "track_index": track_index,
                                                "clip_index": clip_index,
                                            }
                                        )

                        transition = clip.get("postTransition")
                        if not isinstance(transition, Mapping):
                            continue
                        transition_id = transition.get("id")
                        if transition_id not in (_VIDEO_TRANSITION_ID, _AUDIO_TRANSITION_ID):
                            continue
                        bounds = (
                            transition.get("tlBegin"),
                            transition.get("tlEnd"),
                            clip.get("tlBegin"),
                            clip.get("tlEnd"),
                        )
                        if not all(isinstance(value, int) for value in bounds):
                            continue
                        if bounds[1] <= bounds[0] or bounds[1] != bounds[3] or bounds[0] < bounds[2]:
                            continue
                        entry = (track_index, clip_index, clip)
                        if (
                            track_type == 1
                            and clip.get("type") == 1
                            and transition_id == _VIDEO_TRANSITION_ID
                        ):
                            videos.setdefault(bounds, []).append(entry)
                        elif (
                            track_type == 2
                            and clip.get("type") == 2
                            and transition_id == _AUDIO_TRANSITION_ID
                        ):
                            audios.setdefault(bounds, []).append(entry)

                for bounds in sorted(set(videos) & set(audios)):
                    if len(videos[bounds]) != 1 or len(audios[bounds]) != 1:
                        continue
                    video_track, video_index, video = videos[bounds][0]
                    audio_track, audio_index, audio = audios[bounds][0]
                    video_uid = video.get("thisUId")
                    audio_uid = audio.get("thisUId")
                    if not isinstance(video_uid, str) or not isinstance(audio_uid, str):
                        continue
                    duration = bounds[1] - bounds[0]
                    key = (video_uid, audio_uid, duration)
                    if key in seen_transitions:
                        continue
                    seen_transitions.add(key)
                    transition_targets.append(
                        {
                            "target_type": "existing_linked_dissolve_audio_fade",
                            "selector": {
                                "video_clip_uid": video_uid,
                                "audio_clip_uid": audio_uid,
                                "duration_ticks": duration,
                            },
                            "timeline_id": timeline_id,
                            "timeline_index": timeline_index,
                            "video_track_index": video_track,
                            "video_clip_index": video_index,
                            "audio_track_index": audio_track,
                            "audio_clip_index": audio_index,
                            "tl_begin": bounds[0],
                            "tl_end": bounds[1],
                        }
                    )
    rotation_targets.sort(key=lambda target: tuple(str(value) for value in target["selector"].values()))
    volume_gain_targets.sort(
        key=lambda target: tuple(str(value) for value in target["selector"].values())
    )
    fade_in_targets.sort(
        key=lambda target: tuple(str(value) for value in target["selector"].values())
    )
    transition_targets.sort(
        key=lambda target: tuple(str(value) for value in target["selector"].values())
    )
    return rotation_targets, volume_gain_targets, fade_in_targets, transition_targets


def _linked_av_targets(path: Pathish) -> List[Dict[str, Any]]:
    """Discover unambiguous linked source pairs accepted by the narrow writers."""

    targets: List[Dict[str, Any]] = []
    seen = set()
    with WfpArchive(path) as archive:
        for _member, document in archive.timeline_documents():
            timelines = document.get("timelineInfos")
            if not isinstance(timelines, list):
                continue
            for timeline_index, timeline in enumerate(timelines):
                if not isinstance(timeline, Mapping):
                    continue
                tracks = timeline.get("trackInfos")
                if not isinstance(tracks, list):
                    continue
                videos: Dict[Tuple[Any, ...], List[Tuple[int, int, Mapping[str, Any]]]] = {}
                audios: Dict[Tuple[Any, ...], List[Tuple[int, int, Mapping[str, Any]]]] = {}
                for track_index, track in enumerate(tracks):
                    if not isinstance(track, Mapping) or not isinstance(track.get("clipList"), list):
                        continue
                    track_type = track.get("trackType")
                    for clip_index, clip in enumerate(track["clipList"]):
                        if not isinstance(clip, Mapping):
                            continue
                        clip_type = clip.get("type")
                        if (track_type, clip_type) not in ((1, 1), (2, 2)):
                            continue
                        uid = clip.get("thisUId")
                        source_uuid = clip.get("sourceUuid")
                        values = (
                            clip.get("tlBegin"),
                            clip.get("tlEnd"),
                            clip.get("inPoint"),
                            clip.get("outPoint"),
                        )
                        if (
                            not isinstance(uid, str)
                            or not isinstance(source_uuid, str)
                            or not source_uuid
                            or not all(isinstance(value, int) for value in values)
                            or values[1] <= values[0]
                            or any(key in clip for key in ("preTransition", "postTransition"))
                        ):
                            continue
                        key = (source_uuid,) + values
                        entry = (track_index, clip_index, clip)
                        (videos if track_type == 1 else audios).setdefault(key, []).append(entry)
                for key in sorted(set(videos) & set(audios), key=lambda item: tuple(map(str, item))):
                    if len(videos[key]) != 1 or len(audios[key]) != 1:
                        continue
                    video_track, video_index, video = videos[key][0]
                    audio_track, audio_index, audio = audios[key][0]
                    video_uid = video.get("thisUId")
                    audio_uid = audio.get("thisUId")
                    selector = {
                        "video_clip_uid": video_uid,
                        "audio_clip_uid": audio_uid,
                        "start_ticks": key[1],
                        "end_ticks": key[2],
                    }
                    selector_key = tuple(selector.values())
                    if selector_key in seen:
                        continue
                    capabilities = ["move_linked_av_pair"]
                    try:
                        # WfpArchive intentionally exposes ordinary JSON floats, while the
                        # audited trim writers parse decimals losslessly. Normalize only the
                        # two observed offsets before reusing their exact safety predicate.
                        normalized_clips = []
                        for clip in (video, audio):
                            normalized_clip = dict(clip)
                            speed_object = clip.get("speed")
                            if not isinstance(speed_object, Mapping):
                                raise WfpError("Linked clip has no speed object")
                            normalized_speed = dict(speed_object)
                            for field in ("offset", "offsetEnd"):
                                value = normalized_speed.get(field)
                                if isinstance(value, bool) or not isinstance(value, (int, float)):
                                    raise WfpError("Linked clip has a non-numeric speed offset")
                                normalized_speed[field] = Decimal(str(value))
                            normalized_clip["speed"] = normalized_speed
                            normalized_clips.append(normalized_clip)
                        video_speed = _normal_speed_state(normalized_clips[0])
                        audio_speed = _normal_speed_state(normalized_clips[1])
                        video_speed_object = video.get("speed")
                        audio_speed_object = audio.get("speed")
                        if (
                            video_speed == audio_speed
                            and isinstance(video_speed_object, Mapping)
                            and isinstance(audio_speed_object, Mapping)
                            and video_speed_object.get("speedParam")
                            == audio_speed_object.get("speedParam")
                            and video_speed[1] - video_speed[0] == key[2] - key[1]
                            and key[2] - key[1] > 1
                        ):
                            capabilities.extend(
                                [
                                    "trim_linked_av_pair_start",
                                    "trim_linked_av_pair_end",
                                ]
                            )
                            video_link, _video_link_size = _linked_userdata_id(video)
                            audio_link, _audio_link_size = _linked_userdata_id(audio)
                            if video_link == audio_link:
                                capabilities.append("split_linked_av_pair")
                    except (AttributeError, TypeError, WfpError):
                        pass
                    seen.add(selector_key)
                    targets.append(
                        {
                            "target_type": "existing_linked_av_pair",
                            "selector": selector,
                            "capabilities": capabilities,
                            "timeline_id": timeline.get("timelineId"),
                            "timeline_index": timeline_index,
                            "video_track_index": video_track,
                            "video_clip_index": video_index,
                            "audio_track_index": audio_track,
                            "audio_clip_index": audio_index,
                            "source_uuid": key[0],
                            "in_point": key[3],
                            "out_point": key[4],
                        }
                    )
    targets.sort(key=lambda target: tuple(str(value) for value in target["selector"].values()))
    return targets


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
    rotation_targets, volume_gain_targets, fade_in_targets, transition_targets = (
        _existing_effect_targets(path)
    )
    linked_av_targets = _linked_av_targets(path)
    if project_sha256(path) != source["sha256"]:
        raise WfpError("Source project changed while edit targets were being discovered")
    return {
        "api_version": EDIT_PLAN_API_VERSION,
        "source": source,
        "supported_operations": [
            "clone_title_cards",
            "replace_title_text",
            "replace_clip_rotation",
            "replace_clip_volume_gain",
            "replace_clip_fade_in",
            "replace_linked_transition_duration",
            "remove_linked_transition",
            "move_linked_av_pair",
            "trim_linked_av_pair_start",
            "trim_linked_av_pair_end",
            "split_linked_av_pair",
        ],
        "title_card_templates": targets,
        "title_text_targets": title_targets,
        "rotation_targets": rotation_targets,
        "volume_gain_targets": volume_gain_targets,
        "fade_in_targets": fade_in_targets,
        "linked_transition_targets": transition_targets,
        "linked_av_targets": linked_av_targets,
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


def _resolve_exact_selector(
    selector: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    matches = [target for target in targets if target.get("selector") == selector]
    if not matches:
        raise WfpError("{0} selector did not match the current source project".format(label))
    if len(matches) > 1:
        raise WfpError("{0} selector is ambiguous in the current source project".format(label))
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

    if isinstance(operation, ReplaceClipRotationOperation):
        selector = {
            "clip_uid": operation.clip_uid,
            "rotation": str(operation.old_rotation),
        }
        target = _resolve_exact_selector(
            selector, targets_result["rotation_targets"], "Rotation"
        )
        rotation_preflight = preflight_clip_rotation(
            source_path,
            clip_uid=operation.clip_uid,
            old_rotation=operation.old_rotation,
            new_rotation=operation.new_rotation,
        )
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {"source_sha256_matches": True, "format_eval_valid": True},
            "operations": [
                {
                    "id": operation.operation_id,
                    "op": "replace_clip_rotation",
                    "requested_target": selector,
                    "resolved_target": dict(target),
                    "new_rotation": str(operation.new_rotation),
                    "matching_archive_occurrences": rotation_preflight[
                        "matching_archive_occurrences"
                    ],
                }
            ],
            "filmora_round_trip": {"required": True, "performed": False},
        }

    if isinstance(operation, ReplaceClipFadeInOperation):
        selector = {
            "clip_uid": operation.clip_uid,
            "fade_in": str(operation.old_fade_in),
        }
        target = _resolve_exact_selector(
            selector, targets_result["fade_in_targets"], "Clip fade-in"
        )
        fade_preflight = preflight_clip_fade_in(
            source_path,
            clip_uid=operation.clip_uid,
            old_fade_in=operation.old_fade_in,
            new_fade_in=operation.new_fade_in,
        )
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {"source_sha256_matches": True, "format_eval_valid": True},
            "operations": [
                {
                    "id": operation.operation_id,
                    "op": "replace_clip_fade_in",
                    "requested_target": selector,
                    "resolved_target": dict(target),
                    "new_fade_in": str(operation.new_fade_in),
                    "matching_archive_occurrences": fade_preflight[
                        "matching_archive_occurrences"
                    ],
                }
            ],
            "filmora_round_trip": {"required": True, "performed": False},
        }

    if isinstance(operation, ReplaceClipVolumeGainOperation):
        selector = {
            "clip_uid": operation.clip_uid,
            "volume_gain": str(operation.old_volume_gain),
        }
        target = _resolve_exact_selector(
            selector, targets_result["volume_gain_targets"], "Clip volume gain"
        )
        volume_preflight = preflight_clip_volume_gain(
            source_path,
            clip_uid=operation.clip_uid,
            old_volume_gain=operation.old_volume_gain,
            new_volume_gain=operation.new_volume_gain,
        )
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {"source_sha256_matches": True, "format_eval_valid": True},
            "operations": [
                {
                    "id": operation.operation_id,
                    "op": "replace_clip_volume_gain",
                    "requested_target": selector,
                    "resolved_target": dict(target),
                    "new_volume_gain": str(operation.new_volume_gain),
                    "matching_archive_occurrences": volume_preflight[
                        "matching_archive_occurrences"
                    ],
                }
            ],
            "filmora_round_trip": {"required": True, "performed": False},
        }

    if isinstance(
        operation,
        (ReplaceLinkedTransitionDurationOperation, RemoveLinkedTransitionOperation),
    ):
        old_duration = (
            operation.old_duration_ticks
            if isinstance(operation, ReplaceLinkedTransitionDurationOperation)
            else operation.expected_duration_ticks
        )
        selector = {
            "video_clip_uid": operation.video_clip_uid,
            "audio_clip_uid": operation.audio_clip_uid,
            "duration_ticks": old_duration,
        }
        target = _resolve_exact_selector(
            selector,
            targets_result["linked_transition_targets"],
            "Linked transition",
        )
        transition_preflight = preflight_linked_transition(
            source_path,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            expected_duration_ticks=old_duration,
        )
        operation_result: Dict[str, Any] = {
            "id": operation.operation_id,
            "op": (
                "replace_linked_transition_duration"
                if isinstance(operation, ReplaceLinkedTransitionDurationOperation)
                else "remove_linked_transition"
            ),
            "requested_target": selector,
            "resolved_target": dict(target),
            "matching_archive_occurrences": transition_preflight[
                "matching_archive_occurrences"
            ],
        }
        if isinstance(operation, ReplaceLinkedTransitionDurationOperation):
            resolved_begin = transition_preflight["tl_end"] - operation.new_duration_ticks
            if resolved_begin < transition_preflight["owner_tl_begin"]:
                raise WfpError("Requested transition duration begins before its linked clips")
            operation_result["new_duration_ticks"] = operation.new_duration_ticks
            operation_result["resolved_new_tl_begin"] = resolved_begin
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {"source_sha256_matches": True, "format_eval_valid": True},
            "operations": [operation_result],
            "filmora_round_trip": {"required": True, "performed": False},
        }

    if isinstance(
        operation,
        (
            MoveLinkedAvPairOperation,
            TrimLinkedAvPairStartOperation,
            TrimLinkedAvPairEndOperation,
            SplitLinkedAvPairOperation,
        ),
    ):
        selector = {
            "video_clip_uid": operation.video_clip_uid,
            "audio_clip_uid": operation.audio_clip_uid,
            "start_ticks": operation.old_start_ticks,
            "end_ticks": operation.old_end_ticks,
        }
        target = _resolve_exact_selector(
            selector, targets_result["linked_av_targets"], "Linked A/V pair"
        )
        operation_name = (
            "move_linked_av_pair"
            if isinstance(operation, MoveLinkedAvPairOperation)
            else "trim_linked_av_pair_start"
            if isinstance(operation, TrimLinkedAvPairStartOperation)
            else "trim_linked_av_pair_end"
            if isinstance(operation, TrimLinkedAvPairEndOperation)
            else "split_linked_av_pair"
        )
        if operation_name not in target.get("capabilities", []):
            raise WfpError(
                "Linked A/V pair does not support {0} in the current source".format(
                    operation_name
                )
            )
        if isinstance(operation, MoveLinkedAvPairOperation):
            linked_preflight = preflight_linked_av_move(
                source_path,
                video_clip_uid=operation.video_clip_uid,
                audio_clip_uid=operation.audio_clip_uid,
                old_start_ticks=operation.old_start_ticks,
                old_end_ticks=operation.old_end_ticks,
                new_start_ticks=operation.new_start_ticks,
            )
            requested_value = {"new_start_ticks": operation.new_start_ticks}
        elif isinstance(operation, TrimLinkedAvPairStartOperation):
            linked_preflight = preflight_linked_av_start_trim(
                source_path,
                video_clip_uid=operation.video_clip_uid,
                audio_clip_uid=operation.audio_clip_uid,
                old_start_ticks=operation.old_start_ticks,
                old_end_ticks=operation.old_end_ticks,
                new_start_ticks=operation.new_start_ticks,
            )
            requested_value = {"new_start_ticks": operation.new_start_ticks}
        elif isinstance(operation, TrimLinkedAvPairEndOperation):
            linked_preflight = preflight_linked_av_end_trim(
                source_path,
                video_clip_uid=operation.video_clip_uid,
                audio_clip_uid=operation.audio_clip_uid,
                old_start_ticks=operation.old_start_ticks,
                old_end_ticks=operation.old_end_ticks,
                new_end_ticks=operation.new_end_ticks,
            )
            requested_value = {"new_end_ticks": operation.new_end_ticks}
        else:
            linked_preflight = preflight_linked_av_split(
                source_path,
                video_clip_uid=operation.video_clip_uid,
                audio_clip_uid=operation.audio_clip_uid,
                old_start_ticks=operation.old_start_ticks,
                old_end_ticks=operation.old_end_ticks,
                split_ticks=operation.split_ticks,
            )
            requested_value = {"split_ticks": operation.split_ticks}
        return {
            "api_version": EDIT_PLAN_API_VERSION,
            "plan_schema_version": parsed.schema_version,
            "status": "ready",
            "writes_performed": False,
            "description": parsed.description,
            "source": targets_result["source"],
            "preflight": {"source_sha256_matches": True, "format_eval_valid": True},
            "operations": [
                {
                    "id": operation.operation_id,
                    "op": operation_name,
                    "requested_target": selector,
                    "resolved_target": dict(target),
                    **requested_value,
                    "resolved_values": _json_safe_values(linked_preflight),
                }
            ],
            "filmora_round_trip": {"required": True, "performed": False},
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
    elif isinstance(operation, ReplaceClipRotationOperation):
        writer_result = replace_clip_rotation(
            source,
            output,
            clip_uid=operation.clip_uid,
            old_rotation=operation.old_rotation,
            new_rotation=operation.new_rotation,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, ReplaceClipVolumeGainOperation):
        writer_result = replace_clip_volume_gain(
            source,
            output,
            clip_uid=operation.clip_uid,
            old_volume_gain=operation.old_volume_gain,
            new_volume_gain=operation.new_volume_gain,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, ReplaceClipFadeInOperation):
        writer_result = replace_clip_fade_in(
            source,
            output,
            clip_uid=operation.clip_uid,
            old_fade_in=operation.old_fade_in,
            new_fade_in=operation.new_fade_in,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, ReplaceLinkedTransitionDurationOperation):
        writer_result = replace_linked_transition_duration(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            old_duration_ticks=operation.old_duration_ticks,
            new_duration_ticks=operation.new_duration_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, RemoveLinkedTransitionOperation):
        writer_result = remove_linked_transition(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            expected_duration_ticks=operation.expected_duration_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, MoveLinkedAvPairOperation):
        writer_result = move_linked_av_pair(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            old_start_ticks=operation.old_start_ticks,
            old_end_ticks=operation.old_end_ticks,
            new_start_ticks=operation.new_start_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, TrimLinkedAvPairStartOperation):
        writer_result = trim_linked_av_pair_start(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            old_start_ticks=operation.old_start_ticks,
            old_end_ticks=operation.old_end_ticks,
            new_start_ticks=operation.new_start_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, TrimLinkedAvPairEndOperation):
        writer_result = trim_linked_av_pair_end(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            old_start_ticks=operation.old_start_ticks,
            old_end_ticks=operation.old_end_ticks,
            new_end_ticks=operation.new_end_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
        audit_valid = bool((writer_result.get("audit") or {}).get("valid"))
    elif isinstance(operation, SplitLinkedAvPairOperation):
        writer_result = split_linked_av_pair(
            source,
            output,
            video_clip_uid=operation.video_clip_uid,
            audio_clip_uid=operation.audio_clip_uid,
            old_start_ticks=operation.old_start_ticks,
            old_end_ticks=operation.old_end_ticks,
            split_ticks=operation.split_ticks,
            expected_source_sha256=parsed.source_sha256,
        )
        created_cards = []
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
