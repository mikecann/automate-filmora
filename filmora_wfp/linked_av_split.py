"""Guarded split for one transition-free, forward 1x linked A/V pair."""

from __future__ import annotations

import base64
import binascii
import copy
import os
import re
import tempfile
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .evals import evaluate_project
from .linked_av import _normal_speed_state, _sha256, _ticks
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
TICKS_PER_SECOND = 10_000_000
_PAIR_UUID_RE = re.compile(r"^(?:[0-9A-F]{2}-){15}[0-9A-F]{2}$")
_CANONICAL_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


PairOccurrence = Tuple[
    MutableMapping[str, Any],
    MutableMapping[str, Any],
    List[Any],
    List[Any],
]


def _pair_occurrences(
    document: MutableMapping[str, Any],
    video_clip_uid: str,
    audio_clip_uid: str,
) -> List[PairOccurrence]:
    pairs: List[PairOccurrence] = []
    timelines = document.get("timelineInfos")
    if not isinstance(timelines, list):
        return pairs
    for timeline in timelines:
        if not isinstance(timeline, dict) or not isinstance(timeline.get("trackInfos"), list):
            continue
        videos = []
        audios = []
        for track in timeline["trackInfos"]:
            if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
                continue
            for clip in track["clipList"]:
                if not isinstance(clip, dict):
                    continue
                if clip.get("thisUId") == video_clip_uid:
                    if track.get("trackType") != 1 or clip.get("type") != 1:
                        raise WfpError("Selected visual split target is not a type-1 visual clip")
                    videos.append((clip, track["clipList"]))
                if clip.get("thisUId") == audio_clip_uid:
                    if track.get("trackType") != 2 or clip.get("type") != 2:
                        raise WfpError("Selected audio split target is not a type-2 audio clip")
                    audios.append((clip, track["clipList"]))
        if videos or audios:
            if len(videos) != 1 or len(audios) != 1:
                raise WfpError("Linked A/V split selectors must resolve together exactly once")
            pairs.append((videos[0][0], audios[0][0], videos[0][1], audios[0][1]))
    return pairs


def _linked_userdata_id(clip: Mapping[str, Any]) -> Tuple[str, int]:
    entries = clip.get("userData")
    if not isinstance(entries, list):
        raise WfpError("Linked A/V split requires clip userData")
    matches = [entry for entry in entries if isinstance(entry, Mapping) and entry.get("key") == 3]
    if len(matches) != 1 or not isinstance(matches[0].get("data"), str):
        raise WfpError("Linked A/V split requires exactly one key-3 link identifier")
    try:
        raw = base64.b64decode(matches[0]["data"], validate=True)
        text = raw.rstrip(b"\0").decode("ascii")
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise WfpError("Linked A/V key-3 identifier is not supported base64 text") from exc
    if not _PAIR_UUID_RE.fullmatch(text) or len(raw) not in (47, 64):
        raise WfpError("Linked A/V key-3 identifier has an unsupported shape")
    return text, len(raw)


def _set_linked_userdata_id(clip: MutableMapping[str, Any], value: str) -> None:
    old_value, raw_length = _linked_userdata_id(clip)
    if value == old_value or not _PAIR_UUID_RE.fullmatch(value):
        raise WfpError("Generated linked A/V key-3 identifier is invalid")
    raw = value.encode("ascii") + b"\0" * (raw_length - len(value))
    for entry in clip["userData"]:
        if isinstance(entry, dict) and entry.get("key") == 3:
            entry["data"] = base64.b64encode(raw).decode("ascii")
            return
    raise WfpError("Linked A/V key-3 identifier disappeared while cloning")


def _pair_uuid() -> str:
    return "-".join(uuid.uuid4().hex[index : index + 2] for index in range(0, 32, 2)).upper()


def _replace_instance_ids(value: Any, replacements: MutableMapping[str, str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "thisUId" and isinstance(item, str):
                replacement = replacements.get(item)
                if replacement is None:
                    replacement = str(uuid.uuid4())
                    replacements[item] = replacement
                value[key] = replacement
            else:
                _replace_instance_ids(item, replacements)
    elif isinstance(value, list):
        for item in value:
            _replace_instance_ids(item, replacements)


def _validate_pair(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    *,
    old_start_ticks: int,
    old_end_ticks: int,
    split_ticks: int,
) -> Tuple[int, Decimal]:
    if video.get("sourceUuid") != audio.get("sourceUuid") or not video.get("sourceUuid"):
        raise WfpError("Selected visual and audio split clips do not share one sourceUuid")
    if any(key in clip for clip in (video, audio) for key in ("preTransition", "postTransition")):
        raise WfpError("Splitting clips with transitions is not supported")
    for clip in (video, audio):
        if clip.get("tlBegin") != old_start_ticks or clip.get("tlEnd") != old_end_ticks:
            raise WfpError("Selected linked split bounds do not match the requested old range")
    if not old_start_ticks < split_ticks < old_end_ticks:
        raise WfpError("split_ticks must be strictly inside the selected positive range")
    video_speed = _normal_speed_state(video)
    audio_speed = _normal_speed_state(audio)
    if video_speed != audio_speed:
        raise WfpError("Linked A/V split requires matching source ranges and speed offsets")
    video_speed_object = video.get("speed")
    audio_speed_object = audio.get("speed")
    if (
        not isinstance(video_speed_object, dict)
        or not isinstance(audio_speed_object, dict)
        or video_speed_object.get("speedParam") != audio_speed_object.get("speedParam")
    ):
        raise WfpError("Linked A/V split requires identical speed parameters")
    in_point, out_point, offset, _offset_end = video_speed
    if out_point - in_point != old_end_ticks - old_start_ticks:
        raise WfpError("Linked A/V split only supports forward 1x source duration")
    video_link, _video_length = _linked_userdata_id(video)
    audio_link, _audio_length = _linked_userdata_id(audio)
    if video_link != audio_link:
        raise WfpError("Selected visual and audio clips do not share one key-3 link identifier")
    delta = split_ticks - old_start_ticks
    return in_point + delta, offset + Decimal(delta) / TICKS_PER_SECOND


def preflight_linked_av_split(
    source: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    split_ticks: int,
) -> Dict[str, Any]:
    """Resolve one supported linked A/V split without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Linked A/V splits require an existing .wfp source")
    if not isinstance(video_clip_uid, str) or not video_clip_uid:
        raise WfpError("video_clip_uid must be non-empty text")
    if not isinstance(audio_clip_uid, str) or not audio_clip_uid:
        raise WfpError("audio_clip_uid must be non-empty text")
    old_start = _ticks(old_start_ticks, "old_start_ticks")
    old_end = _ticks(old_end_ticks, "old_end_ticks")
    split = _ticks(split_ticks, "split_ticks")
    matches = 0
    new_in_point: Optional[int] = None
    new_offset: Optional[Decimal] = None
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio, _video_track, _audio_track in _pair_occurrences(
                document, video_clip_uid, audio_clip_uid
            ):
                candidate_in_point, candidate_offset = _validate_pair(
                    video,
                    audio,
                    old_start_ticks=old_start,
                    old_end_ticks=old_end,
                    split_ticks=split,
                )
                if new_in_point is not None and (
                    candidate_in_point != new_in_point or candidate_offset != new_offset
                ):
                    raise WfpError("Cached linked A/V split copies have conflicting source ranges")
                new_in_point = candidate_in_point
                new_offset = candidate_offset
                matches += 1
    if matches < 1 or new_in_point is None or new_offset is None:
        raise WfpError("Linked A/V split selectors did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_start_ticks": old_start,
        "old_end_ticks": old_end,
        "split_ticks": split,
        "new_in_point": new_in_point,
        "new_offset": new_offset,
    }


def _normalize_new_clone(value: Any) -> Any:
    result = copy.deepcopy(value)

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key == "thisUId" and isinstance(child, str):
                    item[key] = "<new-instance-id>"
                else:
                    walk(child)
            entries = item.get("userData")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("key") == 3:
                        entry["data"] = "<new-link-id>"
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(result)
    return result


def _instance_ids(value: Any) -> List[str]:
    found: List[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "thisUId" and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_instance_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_instance_ids(item))
    return found


def _apply_split_to_pair(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    video_track: List[Any],
    audio_track: List[Any],
    *,
    split_ticks: int,
    new_in_point: int,
    new_offset: Decimal,
    link_id: str,
    instance_ids: MutableMapping[str, str],
) -> Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]:
    video_second = copy.deepcopy(video)
    audio_second = copy.deepcopy(audio)
    for first in (video, audio):
        first["tlEnd"] = split_ticks
        first["outPoint"] = new_in_point
        first["speed"]["offsetEnd"] = new_offset
    for second in (video_second, audio_second):
        second["tlBegin"] = split_ticks
        second["inPoint"] = new_in_point
        second["speed"]["offset"] = new_offset
        _replace_instance_ids(second, instance_ids)
        _set_linked_userdata_id(second, link_id)
    video_track.insert(video_track.index(video) + 1, video_second)
    audio_track.insert(audio_track.index(audio) + 1, audio_second)
    return video_second, audio_second


def audit_linked_av_split_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    split_ticks: int,
) -> Dict[str, Any]:
    """Confirm a copy contains exactly the two expected linked split halves."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    preflight = preflight_linked_av_split(
        source_path,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_start_ticks=old_start_ticks,
        old_end_ticks=old_end_ticks,
        split_ticks=split_ticks,
    )
    errors: List[str] = []
    changed_members: List[str] = []
    observed_matches = 0
    try:
        with zipfile.ZipFile(source_path, "r") as before, zipfile.ZipFile(output_path, "r") as after:
            before_names = before.namelist()
            after_names = after.namelist()
            if before_names != after_names or len(before_names) != len(set(before_names)):
                errors.append("Linked A/V split changed or duplicated the archive member set")
            for name in before_names:
                before_data = before.read(name)
                after_data = after.read(name)
                if before_data == after_data:
                    continue
                changed_members.append(name)
                if not name.endswith(TIMELINE_SUFFIX):
                    errors.append("Linked A/V split changed a member outside timeline documents")
                    continue
                expected = _load_decimal_json(before_data)
                actual = _load_decimal_json(after_data)
                expected_pairs = _pair_occurrences(expected, video_clip_uid, audio_clip_uid)
                actual_pairs = _pair_occurrences(actual, video_clip_uid, audio_clip_uid)
                if len(expected_pairs) != len(actual_pairs):
                    errors.append("Linked A/V split changed original selector occurrences")
                    continue
                for expected_pair, actual_pair in zip(expected_pairs, actual_pairs):
                    ev, ea, evt, eat = expected_pair
                    av, aa, avt, aat = actual_pair
                    _validate_pair(
                        ev,
                        ea,
                        old_start_ticks=preflight["old_start_ticks"],
                        old_end_ticks=preflight["old_end_ticks"],
                        split_ticks=preflight["split_ticks"],
                    )
                    video_candidates = [
                        clip for clip in avt
                        if isinstance(clip, dict)
                        and clip is not av
                        and clip.get("type") == 1
                        and clip.get("sourceUuid") == av.get("sourceUuid")
                        and clip.get("tlBegin") == preflight["split_ticks"]
                        and clip.get("tlEnd") == preflight["old_end_ticks"]
                    ]
                    audio_candidates = [
                        clip for clip in aat
                        if isinstance(clip, dict)
                        and clip is not aa
                        and clip.get("type") == 2
                        and clip.get("sourceUuid") == aa.get("sourceUuid")
                        and clip.get("tlBegin") == preflight["split_ticks"]
                        and clip.get("tlEnd") == preflight["old_end_ticks"]
                    ]
                    if len(video_candidates) != 1 or len(audio_candidates) != 1:
                        errors.append("Generated copy does not contain one second linked half")
                        continue
                    expected_ids: Dict[str, str] = {}
                    expected_link = _pair_uuid()
                    expected_video_second, expected_audio_second = _apply_split_to_pair(
                        ev,
                        ea,
                        evt,
                        eat,
                        split_ticks=preflight["split_ticks"],
                        new_in_point=preflight["new_in_point"],
                        new_offset=preflight["new_offset"],
                        link_id=expected_link,
                        instance_ids=expected_ids,
                    )
                    actual_video_second = video_candidates[0]
                    actual_audio_second = audio_candidates[0]
                    actual_video_link, _ = _linked_userdata_id(actual_video_second)
                    actual_audio_link, _ = _linked_userdata_id(actual_audio_second)
                    source_link, _ = _linked_userdata_id(ev)
                    if actual_video_link != actual_audio_link or actual_video_link == source_link:
                        errors.append("Generated second halves do not share one fresh link identifier")
                    new_ids = _instance_ids(actual_video_second) + _instance_ids(actual_audio_second)
                    source_ids = set(_instance_ids(expected))
                    if (
                        len(new_ids) != len(set(new_ids))
                        or any(not _CANONICAL_UUID_RE.fullmatch(identifier) for identifier in new_ids)
                        or any(identifier in source_ids for identifier in new_ids)
                    ):
                        errors.append("Generated second halves have invalid or reused instance identifiers")
                    if _normalize_new_clone(expected_video_second) != _normalize_new_clone(
                        actual_video_second
                    ) or _normalize_new_clone(expected_audio_second) != _normalize_new_clone(
                        actual_audio_second
                    ):
                        errors.append("Generated second halves differ outside proven split fields")
                    # The expected document now has normalized-ID clones in the same slots.
                    for clone in (expected_video_second, expected_audio_second):
                        normalized = _normalize_new_clone(clone)
                        clone.clear()
                        clone.update(normalized)
                    for clone in (actual_video_second, actual_audio_second):
                        normalized = _normalize_new_clone(clone)
                        clone.clear()
                        clone.update(normalized)
                    if expected != actual:
                        errors.append("Generated split timeline changed unrelated values")
                    observed_matches += 1
    except (OSError, zipfile.BadZipFile, WfpError) as exc:
        errors.append(str(exc))
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated linked A/V split copy failed format evaluation")
    if observed_matches != preflight["matching_archive_occurrences"]:
        errors.append("Generated linked A/V split occurrence count is wrong")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "matching_archive_occurrences": observed_matches,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def split_linked_av_pair(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    split_ticks: int,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Split one supported linked pair and write only a new WFP copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Linked A/V splits require .wfp input and output paths")
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_linked_av_split(
        source_path,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_start_ticks=old_start_ticks,
        old_end_ticks=old_end_ticks,
        split_ticks=split_ticks,
    )
    starting_hash = _sha256(source_path)
    if expected_source_sha256 and starting_hash.lower() != expected_source_sha256.lower():
        raise WfpError(
            "Source fingerprint changed: expected {0}, found {1}".format(
                expected_source_sha256, starting_hash
            )
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    changed_members: List[str] = []
    matches = 0
    link_id = _pair_uuid()
    instance_ids: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            with zipfile.ZipFile(temporary_path, "w") as destination:
                for info in infos:
                    data = archive.read(info)
                    if info.filename.endswith(TIMELINE_SUFFIX):
                        document = _load_decimal_json(data)
                        member_matches = 0
                        for video, audio, video_track, audio_track in _pair_occurrences(
                            document, video_clip_uid, audio_clip_uid
                        ):
                            new_in_point, new_offset = _validate_pair(
                                video,
                                audio,
                                old_start_ticks=preflight["old_start_ticks"],
                                old_end_ticks=preflight["old_end_ticks"],
                                split_ticks=preflight["split_ticks"],
                            )
                            _apply_split_to_pair(
                                video,
                                audio,
                                video_track,
                                audio_track,
                                split_ticks=preflight["split_ticks"],
                                new_in_point=new_in_point,
                                new_offset=new_offset,
                                link_id=link_id,
                                instance_ids=instance_ids,
                            )
                            member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Linked A/V split target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while linked A/V split copy was being written")
        temporary_path.replace(output_path)
        audit = audit_linked_av_split_copy(
            source_path,
            output_path,
            video_clip_uid=video_clip_uid,
            audio_clip_uid=audio_clip_uid,
            old_start_ticks=preflight["old_start_ticks"],
            old_end_ticks=preflight["old_end_ticks"],
            split_ticks=preflight["split_ticks"],
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError("Generated linked A/V split copy failed audit: {0}".format("; ".join(audit["errors"])))
        return {
            "output": str(output_path),
            "source_sha256": starting_hash,
            "split_ticks": preflight["split_ticks"],
            "new_in_point": preflight["new_in_point"],
            "new_offset": preflight["new_offset"],
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
