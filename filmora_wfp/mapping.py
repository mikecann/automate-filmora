"""Build an evidence inventory for an observed Filmora WFP project.

The mapper is deliberately read-only.  It reports shapes, enum-like values,
references, and opaque payload classifications without claiming undocumented
fields have stable meanings.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, DefaultDict, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union

from .analysis import WFP_TICKS_PER_SECOND
from .archive import MEDIAS_INFO_MEMBER, PROJECT_INFO_MEMBER, TIMELINE_SUFFIX, WfpArchive, WfpError


Pathish = Union[os.PathLike[str], str]
JSON_SUFFIXES = (".json", ".wesproj")
MEDIA_ID_RE = re.compile(r"^[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){15}$")
UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
HEX_ID_RE = re.compile(r"^[0-9A-Fa-f]{24,64}$")
WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


class JSONObject(list):
    """JSON object represented as ordered pairs so duplicate keys survive."""


def _pairs_object(pairs: List[Tuple[str, Any]]) -> JSONObject:
    return JSONObject(pairs)


def _value_type(value: Any) -> str:
    if isinstance(value, JSONObject) or isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _normalize_key(key: str) -> str:
    if MEDIA_ID_RE.match(key):
        return "{media_id}"
    if UUID_RE.match(key) or HEX_ID_RE.match(key):
        return "{id}"
    return key


def _normalize_member(member: str) -> str:
    return "/".join(_normalize_key(part) for part in PurePosixPath(member).parts)


def _looks_base64(value: str) -> Optional[int]:
    if len(value) < 8 or len(value) % 4:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if base64.b64encode(raw).decode("ascii").rstrip("=") != value.rstrip("="):
        return None
    return len(raw)


def _string_is_path(value: str) -> bool:
    return (
        value.startswith(("file:/", "/Users/", "/Volumes/", "/private/", "~/"))
        or WINDOWS_PATH_RE.match(value) is not None
    )


def _display_path(value: str, reveal_paths: bool) -> str:
    normalized = value.replace("\\", "/")
    if reveal_paths:
        home = str(Path.home()).replace("\\", "/")
        return normalized.replace(home, "~", 1) if normalized.startswith(home) else normalized
    return "<path>/{0}".format(PurePosixPath(normalized.rstrip("/")).name)


def _sanitize_scalar(value: Any, path: str, reveal_paths: bool) -> Any:
    if not isinstance(value, str):
        return value
    if _string_is_path(value):
        return _display_path(value, reveal_paths)
    leaf = path.rsplit(".", 1)[-1].lower()
    if leaf in {"text", "chardata", "caption", "sentence", "projectname"}:
        return "<text:{0} chars>".format(len(value))
    if MEDIA_ID_RE.match(value):
        return "<media-id>"
    if UUID_RE.match(value) or HEX_ID_RE.match(value):
        return "<opaque-id>"
    decoded_length = _looks_base64(value)
    if decoded_length is not None:
        return "<base64:{0} bytes>".format(decoded_length)
    if len(value) > 160:
        try:
            json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return "<string:{0} chars>".format(len(value))
        return "<embedded-json:{0} chars>".format(len(value))
    return value


class SchemaProfiler:
    """Aggregate normalized JSON paths without retaining private content."""

    def __init__(self, reveal_paths: bool = False, max_examples: int = 5) -> None:
        self.reveal_paths = reveal_paths
        self.max_examples = max_examples
        self.fields: Dict[str, Dict[str, Any]] = {}
        self.duplicate_keys: Dict[Tuple[str, str], Dict[str, int]] = {}

    def observe(self, value: Any, path: str = "$") -> None:
        self._record(path, value)
        if isinstance(value, JSONObject):
            counts = Counter(key for key, _item in value)
            for key, count in counts.items():
                if count > 1:
                    identity = (path, _normalize_key(key))
                    duplicate = self.duplicate_keys.setdefault(
                        identity,
                        {"objects": 0, "extra_occurrences": 0, "max_per_object": 0},
                    )
                    duplicate["objects"] += 1
                    duplicate["extra_occurrences"] += count - 1
                    duplicate["max_per_object"] = max(duplicate["max_per_object"], count)
            for key, item in value:
                self.observe(item, "{0}.{1}".format(path, _normalize_key(key)))
            return
        if isinstance(value, dict):
            for key, item in value.items():
                self.observe(item, "{0}.{1}".format(path, _normalize_key(str(key))))
            return
        if isinstance(value, list):
            for item in value:
                self.observe(item, "{0}[]".format(path))

    def _record(self, path: str, value: Any) -> None:
        field = self.fields.setdefault(
            path,
            {
                "count": 0,
                "types": Counter(),
                "examples": [],
                "_example_keys": set(),
                "numeric_min": None,
                "numeric_max": None,
            },
        )
        field["count"] += 1
        field["types"][_value_type(value)] += 1
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            field["numeric_min"] = value if field["numeric_min"] is None else min(field["numeric_min"], value)
            field["numeric_max"] = value if field["numeric_max"] is None else max(field["numeric_max"], value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            example = _sanitize_scalar(value, path, self.reveal_paths)
            key = json.dumps(example, sort_keys=True, ensure_ascii=False)
            if key not in field["_example_keys"] and len(field["examples"]) < self.max_examples:
                field["_example_keys"].add(key)
                field["examples"].append(example)

    def result(self) -> Dict[str, Any]:
        fields: List[Dict[str, Any]] = []
        for path, raw in sorted(self.fields.items()):
            item: Dict[str, Any] = {
                "path": path,
                "count": raw["count"],
                "types": dict(sorted(raw["types"].items())),
            }
            if raw["examples"]:
                item["examples"] = raw["examples"]
            if raw["numeric_min"] is not None:
                item["numeric_range"] = [raw["numeric_min"], raw["numeric_max"]]
            fields.append(item)
        duplicates = []
        for (path, key), values in sorted(self.duplicate_keys.items()):
            duplicates.append({"path": path, "key": key, **values})
        return {"field_count": len(fields), "fields": fields, "duplicate_keys": duplicates}


def _member_kind(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.is_dir():
        return "directory"
    if name == PROJECT_INFO_MEMBER:
        return "project_info"
    if name == MEDIAS_INFO_MEMBER:
        return "medias_info"
    if name.endswith(TIMELINE_SUFFIX):
        return "timeline"
    if name.endswith("/extra.json"):
        return "timeline_extra"
    if name.endswith("/media.json"):
        return "media_metadata"
    if name.endswith("/functionExtraData.json"):
        return "function_extra"
    if name.endswith("/thumbnail.png"):
        return "media_thumbnail"
    if name.endswith(".fsthumb"):
        return "cover_thumbnail"
    if name.endswith(".png"):
        return "png"
    if name.endswith(JSON_SUFFIXES):
        return "other_json"
    return "other_binary"


def _profile_documents(archive: WfpArchive, reveal_paths: bool) -> Dict[str, Any]:
    profilers: Dict[str, SchemaProfiler] = {}
    document_counts: Counter[str] = Counter()
    parse_errors: DefaultDict[str, List[str]] = defaultdict(list)
    root_keys: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    for info in archive.members():
        if not info.filename.endswith(JSON_SUFFIXES):
            continue
        kind = _member_kind(info)
        raw = archive.zip_file.read(info)
        try:
            text = raw.decode("utf-8")
            normal = json.loads(text)
            paired = json.loads(text, object_pairs_hook=_pairs_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_errors[kind].append("{0}: {1}".format(_normalize_member(info.filename), exc))
            continue
        document_counts[kind] += 1
        profiler = profilers.setdefault(kind, SchemaProfiler(reveal_paths=reveal_paths))
        profiler.observe(paired)
        if isinstance(normal, dict):
            root_keys[kind].update(normal.keys())

    result: Dict[str, Any] = {}
    kinds = sorted(set(document_counts) | set(parse_errors))
    for kind in kinds:
        profile = (
            profilers[kind].result()
            if kind in profilers
            else {"field_count": 0, "fields": [], "duplicate_keys": []}
        )
        result[kind] = {
            "document_count": document_counts[kind],
            "root_key_presence": dict(sorted(root_keys[kind].items())),
            "parse_errors": parse_errors[kind],
            **profile,
        }
    return result


def _iter_clips(timeline: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
    tracks = timeline.get("trackInfos")
    if not isinstance(tracks, list):
        return
    for track in tracks:
        if not isinstance(track, dict):
            continue
        clips = track.get("clipList")
        if not isinstance(clips, list):
            continue
        for clip in clips:
            if isinstance(clip, dict):
                yield track, clip


def _canonical_timelines(
    archive: WfpArchive,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, Any], List[Dict[str, Any]]]:
    main_member = archive.main_timeline_member()
    main = archive.read_json(main_member)
    canonical: List[Tuple[str, Dict[str, Any]]] = []
    by_id: Dict[Any, Dict[str, Any]] = {}
    duplicate_ids: Counter[str] = Counter()
    for timeline in main.get("timelineInfos", []):
        if not isinstance(timeline, dict):
            continue
        timeline_id = timeline.get("timelineId")
        if timeline_id in by_id:
            duplicate_ids[str(timeline_id)] += 1
            continue
        by_id[timeline_id] = timeline
        canonical.append((main_member, timeline))

    cache_rows: List[Dict[str, Any]] = []
    standalone_only = 0
    equal_copies = 0
    conflicting_copies = 0
    for member, document in archive.timeline_documents():
        if member == main_member:
            continue
        for timeline in document.get("timelineInfos", []):
            if not isinstance(timeline, dict):
                continue
            timeline_id = timeline.get("timelineId")
            if timeline_id not in by_id:
                by_id[timeline_id] = timeline
                canonical.append((member, timeline))
                standalone_only += 1
                status = "standalone_only"
            elif timeline == by_id[timeline_id]:
                equal_copies += 1
                status = "exact_copy"
            else:
                conflicting_copies += 1
                status = "conflicts_with_main"
            cache_rows.append(
                {
                    "member": _normalize_member(member),
                    "timeline_id": timeline_id,
                    "status": status,
                }
            )

    cache_summary = {
        "main_member": _normalize_member(main_member),
        "main_definition_count": len(by_id) - standalone_only,
        "standalone_copy_count": len(cache_rows),
        "exact_copy_count": equal_copies,
        "standalone_only_count": standalone_only,
        "conflicting_copy_count": conflicting_copies,
        "duplicate_ids_in_main": dict(sorted(duplicate_ids.items())),
    }
    return canonical, cache_summary, cache_rows


def _counter_rows(counter: Counter[Any], key_name: str = "value") -> List[Dict[str, Any]]:
    return [
        {key_name: key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def _field_presence(objects: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    presence: Counter[str] = Counter()
    for item in objects:
        presence.update(item.keys())
    return dict(sorted(presence.items()))


def _scalar_profile(values: Iterable[Any], path: str = "$.value") -> Dict[str, Any]:
    profiler = SchemaProfiler()
    for value in values:
        profiler.observe(value, path)
    result = profiler.result()
    if not result["fields"]:
        return {"count": 0, "types": {}}
    field = next(item for item in result["fields"] if item["path"] == path)
    return {key: value for key, value in field.items() if key != "path"}


def _leaf_values(value: Any, path: str = "$") -> Iterator[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaf_values(item, "{0}.{1}".format(path, key))
        return
    if isinstance(value, list):
        for item in value:
            yield from _leaf_values(item, "{0}[]".format(path))
        return
    yield path, value


def _effect_and_transition_map(
    canonical: Sequence[Tuple[str, Dict[str, Any]]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    effects: Dict[Tuple[str, str], Dict[str, Any]] = {}
    transitions: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for _member, timeline in canonical:
        for track, clip in _iter_clips(timeline):
            clip_type = str(clip.get("type"))
            chains = clip.get("effectChainList")
            if isinstance(chains, list):
                for chain in chains:
                    if not isinstance(chain, dict) or not isinstance(chain.get("effectList"), list):
                        continue
                    for effect in chain["effectList"]:
                        if not isinstance(effect, dict):
                            continue
                        identity = (str(effect.get("id")), str(effect.get("display")))
                        row = effects.setdefault(
                            identity,
                            {
                                "id": effect.get("id"),
                                "display": effect.get("display"),
                                "count": 0,
                                "clip_types": Counter(),
                                "field_presence": Counter(),
                                "parameters": defaultdict(list),
                            },
                        )
                        row["count"] += 1
                        row["clip_types"][clip_type] += 1
                        row["field_presence"].update(effect.keys())
                        params = effect.get("paramList")
                        if isinstance(params, list):
                            for param in params:
                                if not isinstance(param, dict):
                                    continue
                                name = str(param.get("name"))
                                payload = param.get("fxParam")
                                if isinstance(payload, (dict, list)):
                                    for leaf, value in _leaf_values(payload, "fxParam"):
                                        row["parameters"][(name, leaf)].append(value)
                                else:
                                    row["parameters"][(name, "fxParam")].append(payload)

            for position in ("preTransition", "postTransition"):
                transition = clip.get(position)
                if not isinstance(transition, dict):
                    continue
                identity = (position, str(transition.get("id")), str(transition.get("display")))
                row = transitions.setdefault(
                    identity,
                    {
                        "position": position,
                        "id": transition.get("id"),
                        "display": transition.get("display"),
                        "count": 0,
                        "clip_types": Counter(),
                        "field_presence": Counter(),
                        "duration_ticks": [],
                        "parameters": defaultdict(list),
                    },
                )
                row["count"] += 1
                row["clip_types"][clip_type] += 1
                row["field_presence"].update(transition.keys())
                for start_key, end_key in (("tlBegin", "tlEnd"), ("inPoint", "outPoint")):
                    start = transition.get(start_key)
                    end = transition.get(end_key)
                    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                        row["duration_ticks"].append(end - start)
                        break
                params = transition.get("paramList")
                if isinstance(params, list):
                    for param in params:
                        if not isinstance(param, dict):
                            continue
                        name = str(param.get("name"))
                        for leaf, value in _leaf_values(param.get("fxParam"), "fxParam"):
                            row["parameters"][(name, leaf)].append(value)

    def finalize(rows: Dict[Any, Dict[str, Any]], transition: bool = False) -> List[Dict[str, Any]]:
        output = []
        for raw in sorted(rows.values(), key=lambda item: (-item["count"], str(item.get("id")))):
            item = {
                "id": raw["id"],
                "display": raw["display"],
                "count": raw["count"],
                "clip_types": dict(sorted(raw["clip_types"].items())),
                "field_presence": dict(sorted(raw["field_presence"].items())),
                "parameters": [
                    {"name": name, "value_path": path, **_scalar_profile(values)}
                    for (name, path), values in sorted(raw["parameters"].items())
                ],
            }
            if transition:
                item["position"] = raw["position"]
                if raw["duration_ticks"]:
                    item["duration_ticks"] = _scalar_profile(raw["duration_ticks"])
            output.append(item)
        return output

    return finalize(effects), finalize(transitions, transition=True)


def _decode_user_data(value: Any) -> Dict[str, Any]:
    if not isinstance(value, str):
        return {"format": "non_string", "encoded_type": _value_type(value)}
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return {"format": "invalid_base64", "encoded_length": len(value)}
    result: Dict[str, Any] = {"decoded_bytes": len(raw)}
    if not raw:
        result["format"] = "empty"
        return result
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text and all(character.isprintable() for character in text):
        if MEDIA_ID_RE.match(text):
            result.update({"format": "ascii_media_id", "value": text})
        elif UUID_RE.match(text):
            result.update({"format": "ascii_uuid", "value": text})
        else:
            result.update({"format": "utf8_text", "value": text})
        return result
    if len(raw) == 4:
        result.update({"format": "uint32_le", "value": int.from_bytes(raw, "little")})
        return result
    result["format"] = "binary"
    return result


def _user_data_map(
    canonical: Sequence[Tuple[str, Dict[str, Any]]], media_ids: Set[str]
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def walk(value: Any, context: Dict[str, Any]) -> None:
        if isinstance(value, dict):
            next_context = dict(context)
            if "timelineId" in value and isinstance(value.get("trackInfos"), list):
                next_context.update({"scope": "timeline", "timeline_id": value.get("timelineId")})
            elif "trackType" in value and isinstance(value.get("clipList"), list):
                next_context.update({"scope": "track", "track_type": value.get("trackType")})
            elif "type" in value and any(key in value for key in ("tlBegin", "scriptBuf", "sourceUuid", "timelineId")):
                next_context.update({"scope": "clip", "clip_type": value.get("type")})
            elif (
                next_context.get("scope") != "transition"
                and "id" in value
                and isinstance(value.get("paramList"), list)
            ):
                next_context.update({"scope": "effect", "effect_id": value.get("id")})

            entries = value.get("userData")
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    key = str(entry.get("key"))
                    scope = str(next_context.get("scope", "object"))
                    row = groups.setdefault(
                        (scope, key),
                        {
                            "scope": scope,
                            "key": entry.get("key"),
                            "count": 0,
                            "formats": Counter(),
                            "decoded_lengths": [],
                            "values": Counter(),
                            "clip_types": Counter(),
                            "matches_containing_timeline": 0,
                            "matches_media_folder": 0,
                        },
                    )
                    decoded = _decode_user_data(entry.get("data"))
                    row["count"] += 1
                    row["formats"][decoded["format"]] += 1
                    if "decoded_bytes" in decoded:
                        row["decoded_lengths"].append(decoded["decoded_bytes"])
                    if "clip_type" in next_context:
                        row["clip_types"][str(next_context["clip_type"])] += 1
                    decoded_value = decoded.get("value")
                    if decoded["format"] == "uint32_le":
                        row["values"][decoded_value] += 1
                        if decoded_value == next_context.get("timeline_id"):
                            row["matches_containing_timeline"] += 1
                    elif decoded["format"] in {"ascii_media_id", "ascii_uuid"}:
                        sanitized = "<media-id>" if decoded["format"] == "ascii_media_id" else "<uuid>"
                        row["values"][sanitized] += 1
                        if decoded_value in media_ids:
                            row["matches_media_folder"] += 1
                    elif decoded["format"] == "utf8_text":
                        row["values"]["<text:{0} chars>".format(len(str(decoded_value)))] += 1
            for key, item in value.items():
                if key != "userData":
                    child_context = next_context
                    if key in {"preTransition", "postTransition"} and isinstance(item, dict):
                        child_context = {
                            **next_context,
                            "scope": "transition",
                            "transition_position": key,
                        }
                    walk(item, child_context)
        elif isinstance(value, list):
            for item in value:
                walk(item, context)

    for _member, timeline in canonical:
        walk(timeline, {"scope": "timeline", "timeline_id": timeline.get("timelineId")})

    output = []
    for row in sorted(groups.values(), key=lambda item: (item["scope"], str(item["key"]))):
        item: Dict[str, Any] = {
            "scope": row["scope"],
            "key": row["key"],
            "count": row["count"],
            "formats": dict(sorted(row["formats"].items())),
            "clip_types": dict(sorted(row["clip_types"].items())),
            "decoded_length_bytes": _scalar_profile(row["decoded_lengths"]),
            "decoded_value_examples": [
                {"value": value, "count": count}
                for value, count in row["values"].most_common(5)
            ],
        }
        if row["matches_containing_timeline"]:
            item["matches_containing_timeline"] = row["matches_containing_timeline"]
        if row["matches_media_folder"]:
            item["matches_media_folder"] = row["matches_media_folder"]
        output.append(item)
    return output


def _identifier_map(
    archive: WfpArchive,
    canonical: Sequence[Tuple[str, Dict[str, Any]]],
    media_ids: Set[str],
) -> Dict[str, Any]:
    timeline_definitions: Counter[Any] = Counter()
    timeline_references: Counter[Any] = Counter()
    source_definitions: Set[str] = set()
    source_references: Counter[str] = Counter()
    identifier_fields: DefaultDict[str, List[Any]] = defaultdict(list)

    # Standalone-only timelines can carry resources in their own document root.
    # Filmora 15.6.4 creates this shape when it normalizes a conflicting cache
    # copy during Save As, so definitions cannot be scoped to the routed main
    # timeline document alone.
    for _member, document in archive.timeline_documents():
        resources = document.get("resources")
        if not isinstance(resources, list):
            continue
        for resource in resources:
            if isinstance(resource, dict) and isinstance(resource.get("sourceUuid"), str):
                source_definitions.add(resource["sourceUuid"])

    def collect_fields(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"thisUId", "uuid", "busUid", "sourceUuid", "timelineId", "streamId"}:
                    if isinstance(item, (str, int)):
                        identifier_fields[key].append(item)
                elif key == "busUuids" and isinstance(item, list):
                    identifier_fields[key].extend(part for part in item if isinstance(part, str))
                collect_fields(item)
        elif isinstance(value, list):
            for item in value:
                collect_fields(item)

    for _member, timeline in canonical:
        timeline_id = timeline.get("timelineId")
        timeline_definitions[timeline_id] += 1
        collect_fields(timeline)
        for _track, clip in _iter_clips(timeline):
            target = clip.get("timelineId")
            if target is not None:
                timeline_references[target] += 1
            source_uuid = clip.get("sourceUuid")
            if isinstance(source_uuid, str):
                source_references[source_uuid] += 1

    identifier_summary = {}
    for field, values in sorted(identifier_fields.items()):
        counts = Counter(values)
        identifier_summary[field] = {
            "occurrences": len(values),
            "unique": len(counts),
            "reused_values": sum(1 for count in counts.values() if count > 1),
            "maximum_reuse": max(counts.values()) if counts else 0,
        }

    definition_ids = set(timeline_definitions)
    referenced_ids = set(timeline_references)
    unresolved_source = set(source_references) - source_definitions
    project_info = archive.project_info()
    routed_media_id = project_info.get("timeline_mediaId")
    return {
        "timeline_ids": {
            "definitions": len(definition_ids),
            "references": sum(timeline_references.values()),
            "referenced_unique": len(referenced_ids),
            "unreferenced_definitions": sorted(definition_ids - referenced_ids, key=str),
            "unresolved_references": sorted(referenced_ids - definition_ids, key=str),
            "multiply_defined": {
                str(value): count for value, count in timeline_definitions.items() if count > 1
            },
        },
        "source_uuids": {
            "definitions": len(source_definitions),
            "references": sum(source_references.values()),
            "referenced_unique": len(source_references),
            "unresolved_reference_count": len(unresolved_source),
        },
        "media_folders": {
            "count": len(media_ids),
            "timeline_media_id_resolves": routed_media_id in media_ids,
        },
        "identifier_fields": identifier_summary,
    }


def _title_map(canonical: Sequence[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    profiler = SchemaProfiler()
    valid = 0
    invalid = 0
    script_sizes: List[int] = []
    declared_size_matches = 0
    clips_with_declared_size = 0
    text_mirror_count = 0
    text_mirror_matches = 0
    title_clip_types: Counter[str] = Counter()
    for _member, timeline in canonical:
        for _track, clip in _iter_clips(timeline):
            script = clip.get("scriptBuf")
            if not isinstance(script, str):
                continue
            title_clip_types[str(clip.get("type"))] += 1
            script_sizes.append(len(script.encode("utf-8")))
            if isinstance(clip.get("scriptBufSize"), int):
                clips_with_declared_size += 1
                if clip["scriptBufSize"] == len(script.encode("utf-8")) + 1:
                    declared_size_matches += 1
            try:
                parsed = json.loads(script)
                paired = json.loads(script, object_pairs_hook=_pairs_object)
            except json.JSONDecodeError:
                invalid += 1
                continue
            valid += 1
            profiler.observe(paired)
            text_data = parsed.get("TextData") if isinstance(parsed, dict) else None
            text = parsed.get("Text") if isinstance(parsed, dict) else None
            char_data = (
                text_data[0].get("CharData")
                if isinstance(text_data, list) and text_data and isinstance(text_data[0], dict)
                else None
            )
            if isinstance(text, str):
                text_mirror_count += 1
                if isinstance(char_data, str) and text == char_data:
                    text_mirror_matches += 1
    return {
        "script_buffer_count": valid + invalid,
        "valid_json_count": valid,
        "invalid_json_count": invalid,
        "clip_types": dict(sorted(title_clip_types.items())),
        "utf8_size_bytes": _scalar_profile(script_sizes),
        "declared_scriptBufSize_count": clips_with_declared_size,
        "declared_size_matches_utf8_plus_one": declared_size_matches,
        "text_mirror_count": text_mirror_count,
        "text_mirror_matches": text_mirror_matches,
        "schema": profiler.result(),
    }


def _timeline_map(
    canonical: Sequence[Tuple[str, Dict[str, Any]]], cache_summary: Dict[str, Any], cache_rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    timelines = [timeline for _member, timeline in canonical]
    timeline_types: Counter[str] = Counter()
    track_types: Counter[str] = Counter()
    track_tags: Counter[str] = Counter()
    track_signatures: Counter[str] = Counter()
    clip_groups: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    clip_signatures: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    clip_durations: DefaultDict[str, List[Any]] = defaultdict(list)
    timeline_refs: Counter[Tuple[Any, Any, str]] = Counter()
    for _member, timeline in canonical:
        timeline_types[str(timeline.get("type"))] += 1
        containing_id = timeline.get("timelineId")
        tracks = timeline.get("trackInfos")
        if not isinstance(tracks, list):
            continue
        for track in tracks:
            if not isinstance(track, dict):
                continue
            track_type = str(track.get("trackType"))
            track_types[track_type] += 1
            track_tags[str(track.get("trackTag"))] += 1
            track_signatures[", ".join(sorted(track))] += 1
            clips = track.get("clipList")
            if not isinstance(clips, list):
                continue
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                clip_type = str(clip.get("type"))
                clip_groups[clip_type].append(clip)
                clip_signatures[clip_type][", ".join(sorted(clip))] += 1
                start, end = clip.get("tlBegin"), clip.get("tlEnd")
                if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                    clip_durations[clip_type].append(end - start)
                if clip.get("timelineId") is not None:
                    timeline_refs[(containing_id, clip.get("timelineId"), clip_type)] += 1

    clip_types = []
    for clip_type, clips in sorted(clip_groups.items(), key=lambda item: (-len(item[1]), item[0])):
        clip_types.append(
            {
                "type": clip_type,
                "count": len(clips),
                "field_presence": _field_presence(clips),
                "duration_ticks": _scalar_profile(clip_durations[clip_type]),
                "signatures": [
                    {"fields": fields.split(", ") if fields else [], "count": count}
                    for fields, count in clip_signatures[clip_type].most_common()
                ],
            }
        )
    return {
        "canonical_timeline_count": len(timelines),
        "timeline_ids": [timeline.get("timelineId") for timeline in timelines],
        "field_presence": _field_presence(timelines),
        "timeline_types": _counter_rows(timeline_types, "type"),
        "track_types": _counter_rows(track_types, "track_type"),
        "track_tags": _counter_rows(track_tags, "track_tag"),
        "track_signatures": [
            {"fields": fields.split(", ") if fields else [], "count": count}
            for fields, count in track_signatures.most_common()
        ],
        "clip_types": clip_types,
        "nested_references": [
            {"containing_timeline_id": source, "target_timeline_id": target, "clip_type": clip_type, "count": count}
            for (source, target, clip_type), count in sorted(
                timeline_refs.items(), key=lambda item: (str(item[0][0]), str(item[0][1]), item[0][2])
            )
        ],
        "standalone_cache": {**cache_summary, "entries": cache_rows},
    }


def _media_library_map(archive: WfpArchive) -> Dict[str, Any]:
    versions: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    stream_shapes: Counter[Tuple[int, int]] = Counter()
    parse_errors: List[str] = []
    count = 0
    for info in archive.members():
        if not info.filename.endswith("/media.json"):
            continue
        count += 1
        try:
            document = archive.read_json(info.filename)
        except WfpError as exc:
            parse_errors.append(str(exc))
            continue
        versions[str(document.get("version"))] += 1
        filename = document.get("file_name")
        if isinstance(filename, str):
            extensions[Path(filename).suffix.lower() or "<none>"] += 1
        source_info = document.get("sourceInfo")
        if isinstance(source_info, dict):
            audio_streams = source_info.get("audStreamInfos")
            video_streams = source_info.get("vidStreamInfos")
            audio_count = len(audio_streams) if isinstance(audio_streams, list) else 0
            video_count = len(video_streams) if isinstance(video_streams, list) else 0
            stream_shapes[(audio_count, video_count)] += 1
    return {
        "media_metadata_count": count,
        "metadata_versions": dict(sorted(versions.items())),
        "file_extensions": dict(sorted(extensions.items())),
        "stream_shapes": [
            {"audio_streams": audio, "video_streams": video, "count": amount}
            for (audio, video), amount in sorted(stream_shapes.items())
        ],
        "parse_errors": parse_errors,
    }


def map_project(path: Pathish, reveal_paths: bool = False) -> Dict[str, Any]:
    """Return a redacted, machine-readable structural inventory of ``path``."""

    with WfpArchive(path) as archive:
        project_info = archive.project_info()
        main = archive.main_timeline()
        canonical, cache_summary, cache_rows = _canonical_timelines(archive)
        media_ids = {
            parts[2]
            for info in archive.members()
            for parts in [PurePosixPath(info.filename).parts]
            if len(parts) >= 4 and parts[:2] == ("ProjectFolder", "Medias") and parts[2] != "medias_info.json"
        }
        member_kinds: Counter[str] = Counter()
        compression: Counter[str] = Counter()
        for info in archive.members():
            member_kinds[_member_kind(info)] += 1
            compression[str(info.compress_type)] += 1
        largest = sorted(archive.members(), key=lambda info: info.file_size, reverse=True)[:10]
        effects, transitions = _effect_and_transition_map(canonical)
        return {
            "format_map_version": 1,
            "source": {
                "path": _display_path(str(archive.path), reveal_paths),
                "size_bytes": archive.path.stat().st_size,
                "filmora_version": project_info.get("project_editor_modify_version"),
                "created_with": project_info.get("project_editor_create_version"),
                "os": project_info.get("project_os_name"),
                "project_duration_ticks": project_info.get("project_timeline_duration"),
                "ticks_per_second_observed": WFP_TICKS_PER_SECOND,
            },
            "archive": {
                "member_count": len(archive.members()),
                "uncompressed_bytes": sum(info.file_size for info in archive.members()),
                "member_kinds": dict(sorted(member_kinds.items())),
                "compression_methods": dict(sorted(compression.items())),
                "duplicate_member_names": archive.duplicate_names(),
                "largest_members": [
                    {
                        "member": _normalize_member(info.filename),
                        "kind": _member_kind(info),
                        "size_bytes": info.file_size,
                    }
                    for info in largest
                ],
            },
            "documents": _profile_documents(archive, reveal_paths=reveal_paths),
            "media_library": _media_library_map(archive),
            "timeline": _timeline_map(canonical, cache_summary, cache_rows),
            "titles": _title_map(canonical),
            "effects": effects,
            "transitions": transitions,
            "user_data": _user_data_map(canonical, media_ids),
            "identifiers": _identifier_map(archive, canonical, media_ids),
        }
