"""Guarded Filmora project writer for one-source rough-cut plans.

The writer is intentionally narrower than a generic timeline exporter. It only
accepts a Filmora-created seed containing one linked video/audio pair and
replaces that pair with contiguous linked clones for reviewed source ranges.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import zipfile
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from .archive import MEDIAS_INFO_MEMBER, PROJECT_INFO_MEMBER, TIMELINE_SUFFIX, WfpError
from .evals import evaluate_project
from .linked_av_split import (
    _instance_ids,
    _linked_userdata_id,
    _pair_uuid,
    _replace_instance_ids,
    _set_linked_userdata_id,
)
from .title_cards import (
    JsonPairs,
    _compact_json,
    _load_decimal_json,
    _load_pairs_json,
    _pairs_get,
    _pairs_set,
)


Pathish = Union[os.PathLike[str], str]
TICKS_PER_SECOND = 10_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_number(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise WfpError("{0} must be a finite number".format(label))
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise WfpError("{0} must be a finite number".format(label)) from exc
    if not number.is_finite():
        raise WfpError("{0} must be a finite number".format(label))
    return number


def _filename_from_clip(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise WfpError("Rough-cut seed clips require a source filename")
    # Filmora has emitted both file:///Users/... and file://Users/... forms.
    without_scheme = value[7:] if value.startswith("file://") else value
    return Path(without_scheme).name


def _find_seed_pair(
    timeline_document: MutableMapping[str, Any],
) -> Tuple[MutableMapping[str, Any], MutableMapping[str, Any], List[Any], List[Any], int]:
    timelines = timeline_document.get("timelineInfos")
    if not isinstance(timelines, list) or len(timelines) != 1:
        raise WfpError("Rough-cut seed must contain exactly one timeline")
    timeline = timelines[0]
    if not isinstance(timeline, dict) or not isinstance(timeline.get("trackInfos"), list):
        raise WfpError("Rough-cut seed timeline has no track list")
    videos: List[Tuple[MutableMapping[str, Any], List[Any]]] = []
    audios: List[Tuple[MutableMapping[str, Any], List[Any]]] = []
    total_clips = 0
    for track in timeline["trackInfos"]:
        if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
            continue
        clips = track["clipList"]
        total_clips += sum(isinstance(clip, dict) for clip in clips)
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            if track.get("trackType") == 1 and clip.get("type") == 1:
                videos.append((clip, clips))
            elif track.get("trackType") == 2 and clip.get("type") == 2:
                audios.append((clip, clips))
    if total_clips != 2 or len(videos) != 1 or len(audios) != 1:
        raise WfpError("Rough-cut seed must contain only one linked video/audio pair")
    video, video_track = videos[0]
    audio, audio_track = audios[0]
    return video, audio, video_track, audio_track, int(timeline.get("timelineId", -1))


def _validate_seed_pair(
    video: Mapping[str, Any],
    audio: Mapping[str, Any],
    *,
    declared_duration: int,
) -> Dict[str, Any]:
    if video.get("sourceUuid") != audio.get("sourceUuid") or not video.get("sourceUuid"):
        raise WfpError("Rough-cut seed clips do not share one sourceUuid")
    for label, clip in (("video", video), ("audio", audio)):
        if any(key in clip for key in ("preTransition", "postTransition")):
            raise WfpError("Rough-cut seed {0} clip must not have transitions".format(label))
        if clip.get("tlBegin") != 0 or clip.get("inPoint") != 0:
            raise WfpError("Rough-cut seed pair must begin at timeline and source tick zero")
        if clip.get("tlEnd") != declared_duration or clip.get("outPoint") != declared_duration:
            raise WfpError("Rough-cut seed pair must fill the declared project duration")
        speed = clip.get("speed")
        if not isinstance(speed, Mapping) or speed.get("reverse") is not False:
            raise WfpError("Rough-cut seed only supports forward clips with a speed object")
        if _plain_number(speed.get("offset"), "seed speed offset") != 0:
            raise WfpError("Rough-cut seed speed must start at source zero")
        expected_end = Decimal(declared_duration) / TICKS_PER_SECOND
        actual_end = _plain_number(speed.get("offsetEnd"), "seed speed offsetEnd")
        # Filmora 15.7.3 writes the visual offsetEnd to millisecond precision
        # while the linked audio value retains seven decimals. The timeline and
        # source ticks remain exact, so accept only that tiny native mismatch.
        if abs(actual_end - expected_end) > Decimal("0.001"):
            raise WfpError("Rough-cut seed speed does not cover the source duration")
    if video.get("speed", {}).get("speedParam") != audio.get("speed", {}).get("speedParam"):
        raise WfpError("Rough-cut seed clips do not share identical speed parameters")
    video_link, video_link_size = _linked_userdata_id(video)
    audio_link, audio_link_size = _linked_userdata_id(audio)
    if video_link != audio_link or {video_link_size, audio_link_size} != {47, 64}:
        raise WfpError("Rough-cut seed clips do not share the supported link identifier")
    if _filename_from_clip(video.get("filename")) != _filename_from_clip(audio.get("filename")):
        raise WfpError("Rough-cut seed clips do not reference the same media filename")
    return {
        "source_uuid": video["sourceUuid"],
        "source_filename": _filename_from_clip(video.get("filename")),
        "duration_ticks": declared_duration,
    }


def _load_seed(source: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise WfpError("Rough-cut seed archive contains duplicate member names")
        timeline_names = [name for name in names if name.endswith(TIMELINE_SUFFIX)]
        if len(timeline_names) != 1:
            raise WfpError("Rough-cut seed must contain exactly one timeline document")
        if PROJECT_INFO_MEMBER not in names or MEDIAS_INFO_MEMBER not in names:
            raise WfpError("Rough-cut seed is missing required project metadata")
        project_info = _load_decimal_json(archive.read(PROJECT_INFO_MEMBER))
        timeline = _load_decimal_json(archive.read(timeline_names[0]))
        media_info = _load_pairs_json(archive.read(MEDIAS_INFO_MEMBER))
    declared_duration = project_info.get("project_timeline_duration")
    if not isinstance(declared_duration, int) or declared_duration <= 0:
        raise WfpError("Rough-cut seed has no positive declared duration")
    video, audio, video_track, audio_track, timeline_id = _find_seed_pair(timeline)
    pair = _validate_seed_pair(video, audio, declared_duration=declared_duration)
    frame_rate = project_info.get("project_timeline_framerate")
    if (
        not isinstance(frame_rate, list)
        or len(frame_rate) != 2
        or not all(isinstance(item, int) and item > 0 for item in frame_rate)
    ):
        raise WfpError("Rough-cut seed has an unsupported frame rate")
    timeline_media_id = project_info.get("timeline_mediaId")
    if not isinstance(timeline_media_id, str) or not timeline_media_id:
        raise WfpError("Rough-cut seed has no timeline media identifier")
    media_items = _pairs_get(media_info, "media_items")
    if not isinstance(media_items, JsonPairs):
        raise WfpError("Rough-cut seed media_items is not an object")
    timeline_media = _pairs_get(media_items, timeline_media_id)
    if not isinstance(timeline_media, JsonPairs):
        raise WfpError("Rough-cut seed timeline media entry is not an object")
    if _pairs_get(timeline_media, "duration") != declared_duration:
        raise WfpError("Rough-cut seed duration metadata is inconsistent")
    return {
        "project_info": project_info,
        "timeline": timeline,
        "media_info": media_info,
        "timeline_member": timeline_names[0],
        "video": video,
        "audio": audio,
        "video_track": video_track,
        "audio_track": audio_track,
        "timeline_id": timeline_id,
        "timeline_media": timeline_media,
        "timeline_media_id": timeline_media_id,
        "frame_rate": (frame_rate[0], frame_rate[1]),
        **pair,
    }


def inspect_rough_cut_seed_shape(project: Pathish) -> Dict[str, Any]:
    """Return the accepted single-pair seed shape without writing anything."""

    source = Path(project).expanduser().resolve()
    issues: List[str] = []
    model: Optional[Dict[str, Any]] = None
    if source.suffix.lower() != ".wfp" or not source.is_file():
        issues.append("Rough-cut seeds require an existing .wfp project")
    else:
        try:
            model = _load_seed(source)
        except (OSError, zipfile.BadZipFile, WfpError) as exc:
            issues.append(str(exc))
    return {
        "valid_seed_shape": not issues,
        "issues": issues,
        "source": (
            {
                "filename": source.name,
                "sha256": _sha256(source),
                "filmora_version": model["project_info"].get("project_editor_modify_version"),
                "os": model["project_info"].get("project_os_name"),
            }
            if model is not None
            else None
        ),
        "seed": (
            {
                "source_uuid": model["source_uuid"],
                "source_filename": model["source_filename"],
                "duration_ticks": model["duration_ticks"],
                "frame_rate": list(model["frame_rate"]),
                "timeline_id": model["timeline_id"],
            }
            if model is not None
            else None
        ),
        "filmora_writer_available": not issues,
        "remaining_gate": None if not issues else "Create a clean Filmora single-pair seed",
    }


def _load_plan(plan: Union[Pathish, Mapping[str, Any]]) -> Dict[str, Any]:
    if isinstance(plan, Mapping):
        payload = dict(plan)
    else:
        path = Path(plan).expanduser().resolve()
        if not path.is_file():
            raise WfpError("Rough-cut plan does not exist: {0}".format(path))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WfpError("Invalid rough-cut plan JSON: {0}".format(exc)) from exc
    if payload.get("schema_version") != 1:
        raise WfpError("Rough-cut project writer requires plan schema version 1")
    source = payload.get("source")
    if not isinstance(source, Mapping) or not isinstance(source.get("filename"), str):
        raise WfpError("Rough-cut plan has no source filename")
    if not isinstance(payload.get("keep_ranges"), list):
        raise WfpError("Rough-cut plan keep_ranges must be an array")
    return payload


def _frame_tick(frame: int, numerator: int, denominator: int) -> int:
    value = Decimal(frame * TICKS_PER_SECOND * denominator) / Decimal(numerator)
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _quantized_ranges(
    rows: Sequence[Any],
    *,
    duration_ticks: int,
    frame_rate: Tuple[int, int],
) -> List[Tuple[int, int]]:
    numerator, denominator = frame_rate
    duration_seconds = Decimal(duration_ticks) / TICKS_PER_SECOND
    ranges: List[Tuple[int, int]] = []
    previous_unquantized_end: Optional[Decimal] = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise WfpError("Rough-cut keep_ranges contains a non-object range")
        start = _plain_number(row.get("start"), "keep range start")
        end = _plain_number(row.get("end"), "keep range end")
        if start < 0 or end <= start or end > duration_seconds + Decimal("0.01"):
            raise WfpError("Rough-cut keep range is outside the seed source duration")
        if previous_unquantized_end is not None and start < previous_unquantized_end:
            raise WfpError("Rough-cut keep ranges must be sorted and non-overlapping")
        previous_unquantized_end = end
        start_frame = int(
            (start * numerator / denominator).to_integral_value(rounding=ROUND_FLOOR)
        )
        end_frame = int(
            (end * numerator / denominator).to_integral_value(rounding=ROUND_CEILING)
        )
        start_tick = max(0, min(duration_ticks, _frame_tick(start_frame, numerator, denominator)))
        end_tick = max(0, min(duration_ticks, _frame_tick(end_frame, numerator, denominator)))
        if end_tick <= start_tick:
            continue
        if ranges and start_tick <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end_tick))
        else:
            ranges.append((start_tick, end_tick))
    if not ranges:
        raise WfpError("Rough-cut plan does not retain any frame-aligned source range")
    return ranges


def preflight_rough_cut_project(
    seed: Pathish,
    plan: Union[Pathish, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Resolve the exact frame-aligned linked pairs without writing a WFP."""

    source = Path(seed).expanduser().resolve()
    if source.suffix.lower() != ".wfp" or not source.is_file():
        raise WfpError("Rough-cut project writer requires an existing .wfp seed")
    model = _load_seed(source)
    payload = _load_plan(plan)
    if payload["source"]["filename"] != model["source_filename"]:
        raise WfpError(
            "Rough-cut plan source does not match the seed media: {0} != {1}".format(
                payload["source"]["filename"], model["source_filename"]
            )
        )
    planned_duration = _plain_number(
        payload["source"].get("duration_seconds"), "plan source duration_seconds"
    )
    seed_duration = Decimal(model["duration_ticks"]) / TICKS_PER_SECOND
    if abs(planned_duration - seed_duration) > Decimal("0.01"):
        raise WfpError("Rough-cut plan duration does not match the seed source")
    source_ranges = _quantized_ranges(
        payload["keep_ranges"],
        duration_ticks=model["duration_ticks"],
        frame_rate=model["frame_rate"],
    )
    pairs: List[Dict[str, int]] = []
    timeline_tick = 0
    for source_start, source_end in source_ranges:
        duration = source_end - source_start
        pairs.append(
            {
                "source_start_ticks": source_start,
                "source_end_ticks": source_end,
                "timeline_start_ticks": timeline_tick,
                "timeline_end_ticks": timeline_tick + duration,
            }
        )
        timeline_tick += duration
    return {
        "seed": str(source),
        "seed_sha256": _sha256(source),
        "source_uuid": model["source_uuid"],
        "source_filename": model["source_filename"],
        "frame_rate": list(model["frame_rate"]),
        "input_keep_range_count": len(payload["keep_ranges"]),
        "output_pair_count": len(pairs),
        "output_duration_ticks": timeline_tick,
        "output_duration_seconds": timeline_tick / TICKS_PER_SECOND,
        "pairs": pairs,
    }


def _set_pair_ranges(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    row: Mapping[str, int],
) -> None:
    source_start = row["source_start_ticks"]
    source_end = row["source_end_ticks"]
    timeline_start = row["timeline_start_ticks"]
    timeline_end = row["timeline_end_ticks"]
    offset = Decimal(source_start) / TICKS_PER_SECOND
    offset_end = Decimal(source_end) / TICKS_PER_SECOND
    for clip in (video, audio):
        clip["tlBegin"] = timeline_start
        clip["tlEnd"] = timeline_end
        clip["inPoint"] = source_start
        clip["outPoint"] = source_end
        clip["speed"]["offset"] = offset
        clip["speed"]["offsetEnd"] = offset_end


def _build_pairs(
    video_template: MutableMapping[str, Any],
    audio_template: MutableMapping[str, Any],
    rows: Sequence[Mapping[str, int]],
) -> Tuple[List[MutableMapping[str, Any]], List[MutableMapping[str, Any]]]:
    videos: List[MutableMapping[str, Any]] = []
    audios: List[MutableMapping[str, Any]] = []
    for index, row in enumerate(rows):
        video = copy.deepcopy(video_template)
        audio = copy.deepcopy(audio_template)
        if index > 0:
            replacements: Dict[str, str] = {}
            _replace_instance_ids(video, replacements)
            _replace_instance_ids(audio, replacements)
            link_id = _pair_uuid()
            _set_linked_userdata_id(video, link_id)
            _set_linked_userdata_id(audio, link_id)
        _set_pair_ranges(video, audio, row)
        videos.append(video)
        audios.append(audio)
    return videos, audios


def _observed_pairs(path: Path) -> Dict[str, Any]:
    model = _load_seed_like_output(path)
    videos = model["videos"]
    audios = model["audios"]
    rows: List[Dict[str, Any]] = []
    for video, audio in zip(videos, audios):
        video_link, _ = _linked_userdata_id(video)
        audio_link, _ = _linked_userdata_id(audio)
        rows.append(
            {
                "video": video,
                "audio": audio,
                "video_link": video_link,
                "audio_link": audio_link,
            }
        )
    return {**model, "pairs": rows}


def _load_seed_like_output(path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        timeline_names = [name for name in names if name.endswith(TIMELINE_SUFFIX)]
        if len(timeline_names) != 1:
            raise WfpError("Generated rough cut has an unexpected timeline member set")
        timeline = _load_decimal_json(archive.read(timeline_names[0]))
        project_info = _load_decimal_json(archive.read(PROJECT_INFO_MEMBER))
        media_info = _load_pairs_json(archive.read(MEDIAS_INFO_MEMBER))
    timelines = timeline.get("timelineInfos")
    if not isinstance(timelines, list) or len(timelines) != 1:
        raise WfpError("Generated rough cut has an unexpected timeline shape")
    videos: List[MutableMapping[str, Any]] = []
    audios: List[MutableMapping[str, Any]] = []
    total = 0
    for track in timelines[0].get("trackInfos") or []:
        if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
            continue
        total += len(track["clipList"])
        if track.get("trackType") == 1:
            videos.extend(
                clip for clip in track["clipList"]
                if isinstance(clip, dict) and clip.get("type") == 1
            )
        elif track.get("trackType") == 2:
            audios.extend(
                clip for clip in track["clipList"]
                if isinstance(clip, dict) and clip.get("type") == 2
            )
    if total != len(videos) + len(audios) or len(videos) != len(audios):
        raise WfpError("Generated rough cut contains clips outside the linked pair tracks")
    return {
        "timeline": timeline,
        "project_info": project_info,
        "media_info": media_info,
        "videos": videos,
        "audios": audios,
        "timeline_member": timeline_names[0],
    }


def audit_rough_cut_project(
    seed: Pathish,
    output: Pathish,
    plan: Union[Pathish, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Confirm a generated project contains exactly the planned linked pairs."""

    source = Path(seed).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    errors: List[str] = []
    try:
        preflight = preflight_rough_cut_project(source, plan)
        source_model = _load_seed(source)
        output_model = _observed_pairs(destination)
        with zipfile.ZipFile(source, "r") as before, zipfile.ZipFile(destination, "r") as after:
            before_names = before.namelist()
            after_names = after.namelist()
            if before_names != after_names or len(after_names) != len(set(after_names)):
                errors.append("Generated rough cut changed or duplicated the archive member set")
            allowed = {
                PROJECT_INFO_MEMBER,
                MEDIAS_INFO_MEMBER,
                source_model["timeline_member"],
            }
            for name in before_names:
                if name not in allowed and before.read(name) != after.read(name):
                    errors.append("Generated rough cut changed unrelated member: {0}".format(name))
        if len(output_model["pairs"]) != preflight["output_pair_count"]:
            errors.append("Generated rough cut has the wrong linked pair count")
        expected_timeline_start = 0
        links = set()
        instance_ids: List[str] = []
        for expected, observed in zip(preflight["pairs"], output_model["pairs"]):
            video = observed["video"]
            audio = observed["audio"]
            for clip in (video, audio):
                if clip.get("sourceUuid") != preflight["source_uuid"]:
                    errors.append("Generated pair changed sourceUuid")
                actual = {
                    "source_start_ticks": clip.get("inPoint"),
                    "source_end_ticks": clip.get("outPoint"),
                    "timeline_start_ticks": clip.get("tlBegin"),
                    "timeline_end_ticks": clip.get("tlEnd"),
                }
                if actual != expected:
                    errors.append("Generated pair range does not match the frame-aligned plan")
                speed = clip.get("speed") or {}
                if _plain_number(speed.get("offset"), "output speed offset") != (
                    Decimal(expected["source_start_ticks"]) / TICKS_PER_SECOND
                ) or _plain_number(speed.get("offsetEnd"), "output speed offsetEnd") != (
                    Decimal(expected["source_end_ticks"]) / TICKS_PER_SECOND
                ):
                    errors.append("Generated pair speed offsets do not match its source range")
            if observed["video_link"] != observed["audio_link"]:
                errors.append("Generated video/audio pair link identifiers differ")
            if observed["video_link"] in links:
                errors.append("Generated linked pairs reuse a link identifier")
            links.add(observed["video_link"])
            instance_ids.extend(_instance_ids(video))
            instance_ids.extend(_instance_ids(audio))
            if expected["timeline_start_ticks"] != expected_timeline_start:
                errors.append("Generated rough cut contains a timeline gap")
            expected_timeline_start = expected["timeline_end_ticks"]
        if len(instance_ids) != len(set(instance_ids)):
            errors.append("Generated rough cut reuses clip or effect instance identifiers")
        output_info = output_model["project_info"]
        for opaque_field in ("project_date_modify", "project_source", "project_guid"):
            if output_info.get(opaque_field) != source_model["project_info"].get(opaque_field):
                errors.append("Generated rough cut changed opaque project field {0}".format(opaque_field))
        if output_info.get("project_timeline_duration") != preflight["output_duration_ticks"]:
            errors.append("Generated rough cut project duration is wrong")
        media_items = _pairs_get(output_model["media_info"], "media_items")
        timeline_media = _pairs_get(media_items, source_model["timeline_media_id"])
        if _pairs_get(timeline_media, "duration") != preflight["output_duration_ticks"]:
            errors.append("Generated rough cut media timeline duration is wrong")
        evaluation = evaluate_project(destination)
        if not evaluation.get("valid"):
            errors.append("Generated rough cut failed format evaluation")
    except (OSError, zipfile.BadZipFile, WfpError) as exc:
        errors.append(str(exc))
        preflight = {}
        evaluation = {"valid": False}
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "output_pair_count": preflight.get("output_pair_count"),
            "output_duration_ticks": preflight.get("output_duration_ticks"),
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def write_rough_cut_project(
    seed: Pathish,
    output: Pathish,
    plan: Union[Pathish, Mapping[str, Any]],
    *,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one new Filmora rough-cut project from an accepted seed and plan."""

    source = Path(seed).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if source == destination:
        raise WfpError("Rough-cut seed and output paths must differ")
    if source.suffix.lower() != ".wfp" or destination.suffix.lower() != ".wfp":
        raise WfpError("Rough-cut project writer requires .wfp input and output paths")
    if destination.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(destination))
    preflight = preflight_rough_cut_project(source, plan)
    starting_hash = _sha256(source)
    if expected_source_sha256 and starting_hash.lower() != expected_source_sha256.lower():
        raise WfpError(
            "Source fingerprint changed: expected {0}, found {1}".format(
                expected_source_sha256, starting_hash
            )
        )
    model = _load_seed(source)
    videos, audios = _build_pairs(model["video"], model["audio"], preflight["pairs"])
    model["video_track"][:] = videos
    model["audio_track"][:] = audios
    new_duration = preflight["output_duration_ticks"]
    project_info = model["project_info"]
    project_info["project_timeline_duration"] = new_duration
    project_info["project_file_name"] = destination.stem
    if "proj_zip_save_path" in project_info:
        project_info["proj_zip_save_path"] = str(destination)
    position = project_info.get("project_current_position")
    if isinstance(position, int):
        project_info["project_current_position"] = min(position, new_duration)
    _pairs_set(model["timeline_media"], "duration", new_duration)
    replacements = {
        model["timeline_member"]: _compact_json(model["timeline"]).encode("utf-8"),
        PROJECT_INFO_MEMBER: _compact_json(project_info).encode("utf-8"),
        MEDIAS_INFO_MEMBER: _compact_json(model["media_info"]).encode("utf-8"),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(source, "r") as before, zipfile.ZipFile(temporary_path, "w") as after:
            infos = before.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            for info in infos:
                after.writestr(copy.copy(info), replacements.get(info.filename, before.read(info)))
        if _sha256(source) != starting_hash:
            raise WfpError("Rough-cut seed changed while the copy was being written")
        if destination.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(destination))
        temporary_path.replace(destination)
        audit = audit_rough_cut_project(source, destination, plan)
        if not audit.get("valid"):
            destination.unlink(missing_ok=True)
            raise WfpError(
                "Generated rough cut failed source-aware audit: {0}".format(
                    "; ".join(audit.get("errors") or ["unknown audit failure"])
                )
            )
        return {
            "source": str(source),
            "source_sha256": starting_hash,
            "output": str(destination),
            "source_uuid": preflight["source_uuid"],
            "input_keep_range_count": preflight["input_keep_range_count"],
            "output_pair_count": preflight["output_pair_count"],
            "output_duration_ticks": new_duration,
            "output_duration_seconds": preflight["output_duration_seconds"],
            "frame_rate": preflight["frame_rate"],
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
