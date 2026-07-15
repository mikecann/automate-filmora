"""Copy-only cloning of an observed Filmora compound title-card template."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import os
import re
import struct
import tempfile
import time
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from .archive import MEDIAS_INFO_MEMBER, PROJECT_INFO_MEMBER, TIMELINE_SUFFIX, WfpError
from .audit import audit_title_card_copy


_PAIR_UUID_RE = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}-){15}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
_CANONICAL_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
_INSTANCE_UUID_FIELDS = {"busUid", "thisUId"}


class JsonPairs(list):
    """A JSON object represented as ordered pairs, including duplicate keys."""


JsonScalar = Union[None, bool, int, float, Decimal, str]
JsonValue = Union[JsonScalar, List[Any], Dict[str, Any], JsonPairs]


def _load_decimal_json(raw: bytes) -> Dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WfpError("Invalid JSON: {0}".format(exc)) from exc
    if not isinstance(value, dict):
        raise WfpError("Expected a JSON object")
    return value


def _load_pairs_json(raw: bytes) -> JsonPairs:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=JsonPairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WfpError("Invalid duplicate-preserving JSON: {0}".format(exc)) from exc
    if not isinstance(value, JsonPairs):
        raise WfpError("Expected a JSON object")
    return value


def _compact_json(value: JsonValue) -> str:
    """Serialize without changing the lexical form of Decimal-backed numbers."""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise WfpError("Non-finite numbers are not valid project JSON")
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise WfpError("Non-finite numbers are not valid project JSON")
        return json.dumps(value, allow_nan=False)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, JsonPairs):
        return "{" + ",".join(_compact_json(key) + ":" + _compact_json(item) for key, item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(_compact_json(key) + ":" + _compact_json(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_compact_json(item) for item in value) + "]"
    raise WfpError("Unsupported JSON value: {0}".format(type(value).__name__))


def _pairs_get(value: JsonPairs, key: str) -> Any:
    for candidate, item in reversed(value):
        if candidate == key:
            return item
    raise WfpError("Missing JSON key: {0}".format(key))


def _pairs_set(value: JsonPairs, key: str, replacement: Any) -> None:
    for index in range(len(value) - 1, -1, -1):
        if value[index][0] == key:
            value[index] = (key, replacement)
            return
    raise WfpError("Missing JSON key: {0}".format(key))


def _pair_uuid() -> str:
    return "-".join(uuid.uuid4().hex[index : index + 2] for index in range(0, 32, 2)).upper()


class _IdRemapper:
    def __init__(self) -> None:
        self._values: Dict[str, str] = {}

    def register(self, old: str, new: str) -> None:
        self._values[old] = new

    def direct_uuid(self, value: str) -> str:
        return self._replacement(value)

    def replace_tokens(self, value: str) -> str:
        value = _PAIR_UUID_RE.sub(lambda match: self._replacement(match.group(0)), value)
        return _CANONICAL_UUID_RE.sub(lambda match: self._replacement(match.group(0)), value)

    def _replacement(self, value: str) -> str:
        if value in self._values:
            return self._values[value]
        if _PAIR_UUID_RE.fullmatch(value):
            replacement = _pair_uuid()
        elif _CANONICAL_UUID_RE.fullmatch(value):
            replacement = str(uuid.uuid4())
            if value.upper() == value:
                replacement = replacement.upper()
        else:
            raise WfpError("Not a recognized UUID: {0}".format(value))
        self._values[value] = replacement
        return replacement


def _replace_userdata(
    entries: Sequence[MutableMapping[str, Any]],
    remapper: _IdRemapper,
    old_timeline_id: Optional[int],
    new_timeline_id: Optional[int],
) -> None:
    for entry in entries:
        encoded = entry.get("data")
        if not isinstance(encoded, str):
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            continue

        if (
            entry.get("key") == 6
            and old_timeline_id is not None
            and new_timeline_id is not None
            and len(raw) == 4
            and struct.unpack("<I", raw)[0] == old_timeline_id
        ):
            entry["data"] = base64.b64encode(struct.pack("<I", new_timeline_id)).decode("ascii")
            continue

        try:
            decoded = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        replaced = remapper.replace_tokens(decoded)
        if replaced != decoded:
            entry["data"] = base64.b64encode(replaced.encode("ascii")).decode("ascii")


def _transform_clone(
    value: Any,
    remapper: _IdRemapper,
    timeline_ids: Mapping[int, int],
    old_timeline_id: Optional[int],
    new_timeline_id: Optional[int],
) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if key == "timelineId" and isinstance(item, int) and item in timeline_ids:
                result[key] = timeline_ids[item]
            elif key in _INSTANCE_UUID_FIELDS and isinstance(item, str):
                result[key] = remapper.direct_uuid(item)
            elif key == "busUuids" and isinstance(item, list):
                result[key] = [remapper.direct_uuid(uuid_value) for uuid_value in item]
            else:
                result[key] = _transform_clone(
                    item,
                    remapper,
                    timeline_ids,
                    old_timeline_id,
                    new_timeline_id,
                )
        user_data = result.get("userData")
        if isinstance(user_data, list):
            _replace_userdata(user_data, remapper, old_timeline_id, new_timeline_id)
        return result
    if isinstance(value, list):
        return [
            _transform_clone(item, remapper, timeline_ids, old_timeline_id, new_timeline_id)
            for item in value
        ]
    return copy.deepcopy(value)


def _replace_structure_tokens(value: Any, remapper: _IdRemapper) -> Any:
    if isinstance(value, dict):
        return {
            remapper.replace_tokens(key): _replace_structure_tokens(item, remapper)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_structure_tokens(item, remapper) for item in value]
    if isinstance(value, str):
        return remapper.replace_tokens(value)
    return copy.deepcopy(value)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise WfpError("Invalid decimal for {0}: {1!r}".format(field, value)) from exc
    if not result.is_finite():
        raise WfpError("Invalid decimal for {0}: {1!r}".format(field, value))
    return result


def _float32_decimal(value: Decimal) -> Decimal:
    packed = struct.pack("<f", float(value))
    return Decimal(str(struct.unpack("<f", packed)[0]))


def _set_transform_value(clip: MutableMapping[str, Any], name: str, value: Decimal) -> None:
    for chain in clip.get("effectChainList") or []:
        for effect in chain.get("effectList") or []:
            effect_id = str(effect.get("id") or "")
            is_transform = effect.get("display") == "transform" or effect_id == "transform"
            if not is_transform and not effect_id.endswith("/transform"):
                continue
            for parameter in effect.get("paramList") or []:
                if parameter.get("name") == name:
                    parameter["fxParam"]["unValue"] = value
                    return
    raise WfpError("Title clip does not contain transform parameter {0}".format(name))


def _update_title_clip(clip: MutableMapping[str, Any], text: str, font_size: Decimal, scale_x: Decimal) -> None:
    script_raw = clip.get("scriptBuf")
    if not isinstance(script_raw, str):
        raise WfpError("Title clip does not contain scriptBuf")
    try:
        script = json.loads(script_raw, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise WfpError("Title scriptBuf is not valid JSON") from exc

    text_data = script.get("TextData") or []
    if len(text_data) != 1 or not isinstance(text_data[0], dict):
        raise WfpError("Expected one TextData entry in title scriptBuf")
    basic = text_data[0].get("Basic")
    if not isinstance(basic, dict):
        raise WfpError("Title scriptBuf is missing TextData.Basic")

    scale_x = _float32_decimal(scale_x)
    scale_y = _float32_decimal(font_size / Decimal(360))
    script["Text"] = text
    text_data[0]["CharData"] = text
    for field in ("FontHSize", "FontSize", "FontVSize"):
        basic[field] = font_size
    script["ScaleX"] = scale_x
    script["ScaleY"] = scale_y

    _set_transform_value(clip, "Scale_x", _float32_decimal(scale_x * Decimal(100)))
    _set_transform_value(clip, "Scale_y", _float32_decimal(scale_y * Decimal(100)))

    serialized = _compact_json(script)
    clip["scriptBuf"] = serialized
    clip["scriptBufSize"] = len(serialized.encode("utf-8")) + 1


def _card_value(card: Mapping[str, Any], key: str) -> Any:
    if key not in card:
        raise WfpError("Title-card specification is missing {0}".format(key))
    return card[key]


def load_title_card_spec(path: Union[os.PathLike[str], str]) -> List[Dict[str, Any]]:
    spec_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(spec_path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, json.JSONDecodeError) as exc:
        raise WfpError("Cannot read title-card specification: {0}".format(exc)) from exc
    if not isinstance(value, list) or not value:
        raise WfpError("Title-card specification must be a non-empty JSON array")
    if not all(isinstance(card, dict) for card in value):
        raise WfpError("Every title-card specification entry must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clone_zip_info(template: zipfile.ZipInfo, filename: str) -> zipfile.ZipInfo:
    result = copy.copy(template)
    result.filename = filename
    result.orig_filename = filename
    return result


def clone_title_cards(
    source: Union[os.PathLike[str], str],
    output: Union[os.PathLike[str], str],
    template_timeline_id: int,
    cards: Sequence[Mapping[str, Any]],
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Clone one observed compound card graph into a new project copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    if not cards:
        raise WfpError("At least one title card is required")

    starting_hash = _sha256(source_path)
    if expected_source_sha256 and starting_hash.lower() != expected_source_sha256.lower():
        raise WfpError(
            "Source fingerprint changed: expected {0}, found {1}".format(expected_source_sha256, starting_hash)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    replacements: Dict[str, bytes] = {}
    additions: List[Tuple[zipfile.ZipInfo, bytes]] = []
    created_cards: List[Dict[str, Any]] = []

    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise WfpError("Refusing to mutate an archive with duplicate member names")

            try:
                project_info = json.loads(archive.read(PROJECT_INFO_MEMBER).decode("utf-8"))
                media_id = project_info["timeline_mediaId"]
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WfpError("Cannot resolve the main timeline") from exc
            main_member = "ProjectFolder/Medias/{0}/timeline.wesproj".format(media_id)
            if main_member not in names:
                raise WfpError("Main timeline is missing: {0}".format(main_member))
            main = _load_decimal_json(archive.read(main_member))

            standalone_member: Optional[str] = None
            standalone: Optional[Dict[str, Any]] = None
            for member in names:
                if member == main_member or not member.endswith(TIMELINE_SUFFIX):
                    continue
                document = _load_decimal_json(archive.read(member))
                if document.get("currentTimelineId") == template_timeline_id:
                    if standalone_member is not None:
                        raise WfpError("Template timeline resolves to more than one media member")
                    standalone_member = member
                    standalone = document
            if standalone_member is None or standalone is None:
                raise WfpError(
                    "No standalone media member found for template timeline {0}".format(template_timeline_id)
                )

            parts = standalone_member.split("/")
            if len(parts) < 4:
                raise WfpError("Unexpected standalone timeline member path")
            template_media_id = parts[-2]
            template_extra_member = "ProjectFolder/Medias/{0}/extra.json".format(template_media_id)
            if template_extra_member not in names:
                raise WfpError("Template media member is missing extra.json")
            template_extra = _load_decimal_json(archive.read(template_extra_member))

            media_info = _load_pairs_json(archive.read(MEDIAS_INFO_MEMBER))
            media_structure = _pairs_get(media_info, "media_structure")
            media_folder = _pairs_get(media_structure, "Folder")
            media_items = _pairs_get(media_info, "media_items")
            template_media_item = _pairs_get(media_items, template_media_id)
            template_timeline_uuid = _pairs_get(template_media_item, "timeline_uuid")

            template_timelines = standalone.get("timelineInfos")
            if not isinstance(template_timelines, list) or not template_timelines:
                raise WfpError("Template standalone member has no timelines")
            template_ids = [timeline.get("timelineId") for timeline in template_timelines]
            if template_timeline_id not in template_ids or not all(isinstance(value, int) for value in template_ids):
                raise WfpError("Template timeline graph is invalid")

            main_timelines = main.get("timelineInfos")
            if not isinstance(main_timelines, list):
                raise WfpError("Main project has no timelineInfos")
            existing_ids = {timeline.get("timelineId") for timeline in main_timelines if isinstance(timeline, dict)}
            if not all(template_id in existing_ids for template_id in template_ids):
                raise WfpError("Main project does not contain the complete template timeline graph")

            current_id = main.get("currentTimelineId")
            current_timeline = next(
                (timeline for timeline in main_timelines if timeline.get("timelineId") == current_id),
                None,
            )
            if current_timeline is None:
                raise WfpError("Cannot find the current main timeline")
            template_placements: List[Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]] = []
            for track in current_timeline.get("trackInfos") or []:
                for clip in track.get("clipList") or []:
                    if clip.get("timelineId") == template_timeline_id:
                        template_placements.append((track, clip))
            if len(template_placements) < 2:
                raise WfpError("Expected paired main-timeline placements for the template card")

            duration_ticks = template_placements[0][1].get("outPoint")
            if not isinstance(duration_ticks, int) or duration_ticks <= 0:
                raise WfpError("Template card has an invalid duration")
            if any(clip.get("outPoint") != duration_ticks for _, clip in template_placements):
                raise WfpError("Template placement durations do not match")

            next_timeline_id = max(value for value in existing_ids if isinstance(value, int)) + 1
            for card in cards:
                start_ticks = _card_value(card, "start_ticks")
                if not isinstance(start_ticks, int) or start_ticks < 0:
                    raise WfpError("start_ticks must be a non-negative integer")
                heading = _card_value(card, "heading")
                subheading = _card_value(card, "subheading")
                if not isinstance(heading, str) or not heading.strip():
                    raise WfpError("heading must be non-empty text")
                if not isinstance(subheading, str) or not subheading.strip():
                    raise WfpError("subheading must be non-empty text")

                timeline_id_map = {
                    old_id: next_timeline_id + index for index, old_id in enumerate(template_ids)
                }
                next_timeline_id += len(template_ids)
                new_template_id = timeline_id_map[template_timeline_id]
                new_media_id = _pair_uuid()
                new_timeline_uuid = _pair_uuid()
                remapper = _IdRemapper()
                remapper.register(template_media_id, new_media_id)
                remapper.register(template_timeline_uuid, new_timeline_uuid)

                cloned_timelines: List[Dict[str, Any]] = []
                for template in template_timelines:
                    old_id = template["timelineId"]
                    cloned_timelines.append(
                        _transform_clone(
                            template,
                            remapper,
                            timeline_id_map,
                            old_id,
                            timeline_id_map[old_id],
                        )
                    )

                title_clips: List[MutableMapping[str, Any]] = []
                for timeline in cloned_timelines:
                    for track in timeline.get("trackInfos") or []:
                        for clip in track.get("clipList") or []:
                            if clip.get("type") != 4 or not isinstance(clip.get("scriptBuf"), str):
                                continue
                            try:
                                script = json.loads(clip["scriptBuf"])
                            except json.JSONDecodeError:
                                continue
                            if script.get("Text"):
                                title_clips.append(clip)
                if len(title_clips) != 2:
                    raise WfpError("Expected exactly two non-empty title layers in the template graph")
                title_clips.sort(key=lambda clip: json.loads(clip["scriptBuf"]).get("PosY", 0))

                _update_title_clip(
                    title_clips[0],
                    heading,
                    _decimal(_card_value(card, "heading_font_size"), "heading_font_size"),
                    _decimal(_card_value(card, "heading_scale_x"), "heading_scale_x"),
                )
                _update_title_clip(
                    title_clips[1],
                    subheading,
                    _decimal(_card_value(card, "subheading_font_size"), "subheading_font_size"),
                    _decimal(_card_value(card, "subheading_scale_x"), "subheading_scale_x"),
                )

                main_timelines.extend(copy.deepcopy(cloned_timelines))

                for track, placement in template_placements:
                    cloned_placement = _transform_clone(
                        placement,
                        remapper,
                        timeline_id_map,
                        current_id,
                        current_id,
                    )
                    cloned_placement["tlBegin"] = start_ticks
                    cloned_placement["tlEnd"] = start_ticks + duration_ticks
                    track["clipList"].append(cloned_placement)
                    track["clipList"].sort(key=lambda clip: (clip.get("tlBegin", 0), clip.get("tlEnd", 0)))

                cloned_standalone = copy.deepcopy(standalone)
                cloned_standalone["currentTimelineId"] = new_template_id
                cloned_standalone["serialNumber"] = max(timeline_id_map.values()) + 1
                cloned_standalone["timelineInfos"] = copy.deepcopy(cloned_timelines)

                cloned_extra = _replace_structure_tokens(template_extra, remapper)
                new_timeline_member = "ProjectFolder/Medias/{0}/timeline.wesproj".format(new_media_id)
                new_extra_member = "ProjectFolder/Medias/{0}/extra.json".format(new_media_id)
                timeline_info = archive.getinfo(standalone_member)
                extra_info = archive.getinfo(template_extra_member)
                additions.append(
                    (
                        _clone_zip_info(timeline_info, new_timeline_member),
                        _compact_json(cloned_standalone).encode("utf-8"),
                    )
                )
                additions.append(
                    (
                        _clone_zip_info(extra_info, new_extra_member),
                        _compact_json(cloned_extra).encode("utf-8"),
                    )
                )

                new_media_item = copy.deepcopy(template_media_item)
                _pairs_set(new_media_item, "id", new_media_id)
                _pairs_set(new_media_item, "timeline_uuid", new_timeline_uuid)
                _pairs_set(new_media_item, "create_time", int(time.time()))
                media_items.append((new_media_id, new_media_item))
                media_folder.append(("media_item", new_media_id))

                created_cards.append(
                    {
                        "heading": heading,
                        "subheading": subheading,
                        "start_ticks": start_ticks,
                        "end_ticks": start_ticks + duration_ticks,
                        "timeline_id": new_template_id,
                        "media_id": new_media_id,
                    }
                )

            main["serialNumber"] = next_timeline_id
            project_info["project_file_name"] = output_path.stem
            project_info["proj_zip_save_path"] = str(output_path)

            replacements[main_member] = _compact_json(main).encode("utf-8")
            replacements[MEDIAS_INFO_MEMBER] = _compact_json(media_info).encode("utf-8")
            replacements[PROJECT_INFO_MEMBER] = json.dumps(
                project_info,
                indent=4,
                ensure_ascii=False,
            ).encode("utf-8")

            temporary = tempfile.NamedTemporaryFile(
                prefix=output_path.name + ".",
                suffix=".tmp",
                dir=str(output_path.parent),
                delete=False,
            )
            temporary_path = Path(temporary.name)
            temporary.close()
            try:
                with zipfile.ZipFile(temporary_path, "w") as destination:
                    for info in infos:
                        data = replacements.get(info.filename, archive.read(info))
                        destination.writestr(copy.copy(info), data)
                    for info, data in additions:
                        destination.writestr(info, data)
                if _sha256(source_path) != starting_hash:
                    raise WfpError("Source project changed while the copy was being written")
                if output_path.exists():
                    raise WfpError("Output appeared while the copy was being written: {0}".format(output_path))
                os.chmod(temporary_path, source_path.stat().st_mode & 0o7777)
                os.replace(temporary_path, output_path)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
    except zipfile.BadZipFile as exc:
        raise WfpError("Not a readable WFP ZIP: {0}".format(source_path)) from exc

    copy_audit = audit_title_card_copy(source_path, output_path)
    if _sha256(source_path) != starting_hash:
        output_path.unlink(missing_ok=True)
        raise WfpError("Source project changed before the generated-copy audit completed")
    if not copy_audit.get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError(
            "Generated title-card copy failed its source-aware audit: {0}".format(
                "; ".join(copy_audit.get("errors") or ["unknown error"])
            )
        )

    return {
        "source": str(source_path),
        "output": str(output_path),
        "source_sha256": starting_hash,
        "template_timeline_id": template_timeline_id,
        "created_cards": created_cards,
        "copy_audit": copy_audit,
    }
