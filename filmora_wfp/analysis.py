"""High-level observations extracted from Filmora project JSON."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple, Union
from urllib.parse import unquote, urlparse

from .archive import PROJECT_INFO_MEMBER, WfpArchive, WfpError


WFP_TICKS_PER_SECOND = 10_000_000
Pathish = Union[os.PathLike[str], str]


def ticks_to_seconds(value: Any) -> Optional[float]:
    try:
        return int(value) / WFP_TICKS_PER_SECOND
    except (TypeError, ValueError):
        return None


def _display_path(value: Any, reveal_paths: bool) -> Any:
    if not isinstance(value, str) or not value:
        return value
    normalized = value.replace("\\", "/")
    if reveal_paths:
        home = str(Path.home()).replace("\\", "/")
        return normalized.replace(home, "~", 1) if normalized.startswith(home) else normalized
    return PurePosixPath(normalized.rstrip("/")).name


def _path_from_file_uri(value: str) -> Path:
    if not value.startswith("file:"):
        return Path(value).expanduser()
    parsed = urlparse(value)
    if parsed.netloc and parsed.netloc != "localhost":
        path = "/{0}{1}".format(parsed.netloc, parsed.path)
    else:
        path = parsed.path
    return Path(unquote(path))


def _timeline_infos(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = document.get("timelineInfos")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _clips(timeline: Dict[str, Any]) -> Iterator[Tuple[int, Dict[str, Any], int, Dict[str, Any]]]:
    tracks = timeline.get("trackInfos")
    if not isinstance(tracks, list):
        return
    for track_index, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        clip_list = track.get("clipList")
        if not isinstance(clip_list, list):
            continue
        for clip_index, clip in enumerate(clip_list):
            if isinstance(clip, dict):
                yield track_index, track, clip_index, clip


def _effect_names(clip: Dict[str, Any]) -> Iterable[str]:
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return []
    names: List[str] = []
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        effects = chain.get("effectList")
        if not isinstance(effects, list):
            continue
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            name = effect.get("display") or effect.get("id")
            if name:
                names.append(str(name))
    return names


def _transition_names(clip: Dict[str, Any]) -> Iterable[str]:
    names: List[str] = []
    for key in ("preTransition", "postTransition"):
        transition = clip.get(key)
        if isinstance(transition, dict):
            name = transition.get("display") or transition.get("id")
            if name:
                names.append(str(name))
    return names


def _title_from_clip(
    member: str,
    timeline_id: Any,
    track_index: int,
    clip_index: int,
    clip: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    script_buffer = clip.get("scriptBuf")
    if not isinstance(script_buffer, str):
        return None
    try:
        script = json.loads(script_buffer)
    except json.JSONDecodeError:
        return {
            "member": member,
            "timeline_id": timeline_id,
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_uid": clip.get("thisUId"),
            "error": "invalid scriptBuf JSON",
        }
    if not isinstance(script, dict):
        return None

    text_data = script.get("TextData")
    basic: Dict[str, Any] = {}
    char_data: Dict[str, Any] = {}
    if isinstance(text_data, list) and text_data and isinstance(text_data[0], dict):
        first = text_data[0]
        if isinstance(first.get("Basic"), dict):
            basic = first["Basic"]
        char_data = first

    animation = script.get("Animation")
    animation_id = animation.get("ID") if isinstance(animation, dict) else None
    text_colors = basic.get("TextColor")
    color = None
    if isinstance(text_colors, list) and text_colors and isinstance(text_colors[0], dict):
        color = text_colors[0].get("Color")

    return {
        "member": member,
        "timeline_id": timeline_id,
        "track_index": track_index,
        "clip_index": clip_index,
        "clip_uid": clip.get("thisUId"),
        "text": script.get("Text"),
        "start_seconds": ticks_to_seconds(clip.get("tlBegin")),
        "end_seconds": ticks_to_seconds(clip.get("tlEnd")),
        "font": basic.get("FontName"),
        "font_size": basic.get("FontSize"),
        "color": color,
        "character_spacing": char_data.get("CharSpace"),
        "position": {"x": script.get("PosX"), "y": script.get("PosY")},
        "scale": {"x": script.get("ScaleX"), "y": script.get("ScaleY")},
        "animation_id": animation_id,
    }


def list_titles(path: Pathish, include_empty: bool = False) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, Any, Any]] = set()
    with WfpArchive(path) as archive:
        for member, document in archive.timeline_documents():
            for timeline in _timeline_infos(document):
                timeline_id = timeline.get("timelineId")
                for track_index, _track, clip_index, clip in _clips(timeline):
                    title = _title_from_clip(member, timeline_id, track_index, clip_index, clip)
                    if title is None:
                        continue
                    if not include_empty and not title.get("text") and not title.get("error"):
                        continue
                    key = (title.get("timeline_id"), title.get("clip_uid"), title.get("text"))
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(title)
    return found


def _summarize_track(track_index: int, track: Dict[str, Any]) -> Dict[str, Any]:
    clip_list = track.get("clipList") if isinstance(track.get("clipList"), list) else []
    clip_types = Counter(str(clip.get("type")) for clip in clip_list if isinstance(clip, dict))
    timeline_refs = sorted(
        {
            clip.get("timelineId")
            for clip in clip_list
            if isinstance(clip, dict) and clip.get("timelineId") is not None
        },
        key=str,
    )
    starts = [
        clip.get("tlBegin")
        for clip in clip_list
        if isinstance(clip, dict) and clip.get("tlBegin") is not None
    ]
    ends = [
        clip.get("tlEnd")
        for clip in clip_list
        if isinstance(clip, dict) and clip.get("tlEnd") is not None
    ]
    return {
        "index": track_index,
        "track_type": track.get("trackType"),
        "track_tag": track.get("trackTag"),
        "uuid": track.get("uuid"),
        "clip_count": len(clip_list),
        "clip_types": dict(sorted(clip_types.items())),
        "nested_timeline_ids": timeline_refs,
        "start_seconds": ticks_to_seconds(min(starts)) if starts else None,
        "end_seconds": ticks_to_seconds(max(ends)) if ends else None,
    }


def inspect_project(path: Pathish, reveal_paths: bool = False) -> Dict[str, Any]:
    with WfpArchive(path) as archive:
        project = archive.project_info()
        main_member = archive.main_timeline_member()
        main = archive.read_json(main_member)
        timelines = _timeline_infos(main)
        current_id = main.get("currentTimelineId")
        current = next((item for item in timelines if item.get("timelineId") == current_id), None)
        if current is None and timelines:
            current = timelines[0]

        tracks: List[Dict[str, Any]] = []
        placements: List[Dict[str, Any]] = []
        effect_counts: Counter[str] = Counter()
        transition_counts: Counter[str] = Counter()
        if current is not None:
            raw_tracks = current.get("trackInfos") if isinstance(current.get("trackInfos"), list) else []
            tracks = [
                _summarize_track(index, track)
                for index, track in enumerate(raw_tracks)
                if isinstance(track, dict)
            ]
            for track_index, track, clip_index, clip in _clips(current):
                effect_counts.update(_effect_names(clip))
                transition_counts.update(_transition_names(clip))
                if clip.get("timelineId") is not None:
                    placements.append(
                        {
                            "timeline_id": clip.get("timelineId"),
                            "track_index": track_index,
                            "track_type": track.get("trackType"),
                            "track_tag": track.get("trackTag"),
                            "clip_index": clip_index,
                            "clip_type": clip.get("type"),
                            "start_seconds": ticks_to_seconds(clip.get("tlBegin")),
                            "end_seconds": ticks_to_seconds(clip.get("tlEnd")),
                        }
                    )

        resources: List[Dict[str, Any]] = []
        raw_resources = main.get("resources")
        if not isinstance(raw_resources, list):
            raw_resources = []
        for resource in raw_resources:
            if not isinstance(resource, dict):
                continue
            resources.append(
                {
                    "source_uuid": resource.get("sourceUuid"),
                    "filename": _display_path(resource.get("filename"), reveal_paths),
                    "stream_type": resource.get("streamType"),
                    "duration_seconds": ticks_to_seconds(resource.get("mediaLength")),
                    "video_stream_count": resource.get("videoStreamCount"),
                    "audio_stream_count": resource.get("audioStreamCount"),
                }
            )

        frame_rate = project.get("project_timeline_framerate") or [None, None]
        resolution = project.get("project_timeline_resolution") or [None, None]
        return {
            "archive": {
                "path": _display_path(str(archive.path), reveal_paths),
                "size_bytes": archive.path.stat().st_size,
                "member_count": len(archive.members()),
                "uncompressed_bytes": sum(info.file_size for info in archive.members()),
                "timeline_member_count": len(archive.timeline_members()),
                "duplicate_members": archive.duplicate_names(),
            },
            "project": {
                "name": project.get("project_file_name"),
                "filmora_version": project.get("project_editor_modify_version"),
                "created_with": project.get("project_editor_create_version"),
                "os": project.get("project_os_name"),
                "duration_seconds": ticks_to_seconds(project.get("project_timeline_duration")),
                "frame_rate": {"numerator": frame_rate[0], "denominator": frame_rate[1]},
                "resolution": {"width": resolution[0], "height": resolution[1]},
                "main_timeline_member": main_member,
                "current_timeline_id": current_id,
            },
            "main_timeline": {
                "project_version": main.get("projectVersion"),
                "serialization_version": main.get("serializationVersion"),
                "timeline_count": len(timelines),
                "timeline_ids": [item.get("timelineId") for item in timelines],
                "tracks": tracks,
                "nested_placements": placements,
                "effects": dict(effect_counts.most_common()),
                "transitions": dict(transition_counts.most_common()),
            },
            "resources": resources,
            "titles": list_titles(path),
        }


def validate_project(path: Pathish, check_media: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    try:
        with WfpArchive(path) as archive:
            duplicates = archive.duplicate_names()
            if duplicates:
                errors.append("Archive has duplicate member names: {0}".format(", ".join(duplicates)))

            archive.project_info()
            main_member = archive.main_timeline_member()
            main = archive.read_json(main_member)
            timelines = _timeline_infos(main)
            ids = {timeline.get("timelineId") for timeline in timelines}
            current_id = main.get("currentTimelineId")

            if not timelines:
                errors.append("Main timeline has no timelineInfos")
            if current_id not in ids:
                errors.append("currentTimelineId does not resolve: {0}".format(current_id))

            unresolved: Set[Any] = set()
            malformed_tracks = 0
            invalid_script_buffers = 0
            for timeline in timelines:
                if not isinstance(timeline.get("trackInfos"), list):
                    malformed_tracks += 1
                for _track_index, _track, _clip_index, clip in _clips(timeline):
                    target = clip.get("timelineId")
                    if target is not None and target not in ids:
                        unresolved.add(target)
                    script = clip.get("scriptBuf")
                    if isinstance(script, str):
                        try:
                            json.loads(script)
                        except json.JSONDecodeError:
                            invalid_script_buffers += 1

            if unresolved:
                warnings.append(
                    "Nested timeline IDs are unresolved in the main document: {0}".format(
                        ", ".join(str(value) for value in sorted(unresolved, key=str))
                    )
                )
            if malformed_tracks:
                errors.append("{0} timeline(s) have no trackInfos array".format(malformed_tracks))
            if invalid_script_buffers:
                warnings.append("{0} title scriptBuf value(s) are not valid JSON".format(invalid_script_buffers))

            missing_media: List[str] = []
            if check_media:
                raw_resources = main.get("resources")
                if not isinstance(raw_resources, list):
                    raw_resources = []
                for resource in raw_resources:
                    if not isinstance(resource, dict):
                        continue
                    filename = resource.get("filename")
                    if isinstance(filename, str) and filename and not _path_from_file_uri(filename).exists():
                        missing_media.append(str(_display_path(filename, False)))
                if missing_media:
                    errors.append("Missing external media: {0}".format(", ".join(sorted(set(missing_media)))))

            details = {
                "project_info_member": PROJECT_INFO_MEMBER,
                "main_timeline_member": main_member,
                "timeline_count": len(timelines),
                "timeline_ids": sorted(ids, key=str),
                "title_count": len(list_titles(path)),
                "checked_external_media": check_media,
                "external_media_valid": not missing_media if check_media else None,
                "missing_external_media_count": len(set(missing_media)),
            }
    except WfpError as exc:
        errors.append(str(exc))

    return {"valid": not errors, "errors": errors, "warnings": warnings, "details": details}
