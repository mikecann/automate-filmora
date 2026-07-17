"""Narrow writers for an existing linked Dissolve and audio-fade pair."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
_VIDEO_TRANSITION_ID = "2981D185-D52E-44f4-ABD5-3CE83890E32E"
_AUDIO_TRANSITION_ID = "audio/blender/transition-fade"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_ticks(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WfpError("{0} must be a positive integer tick count".format(label))
    return value


def _linked_pairs(
    document: MutableMapping[str, Any],
    video_clip_uid: str,
    audio_clip_uid: str,
) -> List[Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]]:
    pairs: List[Tuple[MutableMapping[str, Any], MutableMapping[str, Any]]] = []
    timelines = document.get("timelineInfos")
    if not isinstance(timelines, list):
        return pairs
    for timeline in timelines:
        if not isinstance(timeline, dict):
            continue
        videos: List[MutableMapping[str, Any]] = []
        audios: List[MutableMapping[str, Any]] = []
        tracks = timeline.get("trackInfos")
        if not isinstance(tracks, list):
            continue
        for track in tracks:
            if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
                continue
            for clip in track["clipList"]:
                if not isinstance(clip, dict):
                    continue
                if clip.get("thisUId") == video_clip_uid:
                    if track.get("trackType") != 1 or clip.get("type") != 1:
                        raise WfpError("Selected video transition owner is not a type-1 visual clip")
                    videos.append(clip)
                if clip.get("thisUId") == audio_clip_uid:
                    if track.get("trackType") != 2 or clip.get("type") != 2:
                        raise WfpError("Selected audio transition owner is not a type-2 audio clip")
                    audios.append(clip)
        if videos or audios:
            if len(videos) != 1 or len(audios) != 1:
                raise WfpError("Linked transition selectors must resolve together exactly once")
            pairs.append((videos[0], audios[0]))
    return pairs


def _transition_bounds(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    expected_duration_ticks: int,
) -> Tuple[int, int, int]:
    video_transition = video.get("postTransition")
    audio_transition = audio.get("postTransition")
    if not isinstance(video_transition, dict) or not isinstance(audio_transition, dict):
        raise WfpError("Selected linked clips do not both have a postTransition")
    if video_transition.get("id") != _VIDEO_TRANSITION_ID:
        raise WfpError("Selected visual transition is not the observed Dissolve")
    if audio_transition.get("id") != _AUDIO_TRANSITION_ID:
        raise WfpError("Selected audio transition is not the observed linked audio fade")
    video_begin = video_transition.get("tlBegin")
    video_end = video_transition.get("tlEnd")
    audio_begin = audio_transition.get("tlBegin")
    audio_end = audio_transition.get("tlEnd")
    if not all(isinstance(value, int) for value in (video_begin, video_end, audio_begin, audio_end)):
        raise WfpError("Selected linked transitions do not have integer timeline bounds")
    if video_begin != audio_begin or video_end != audio_end:
        raise WfpError("Selected visual and audio transition ranges do not match")
    video_clip_begin = video.get("tlBegin")
    video_clip_end = video.get("tlEnd")
    audio_clip_begin = audio.get("tlBegin")
    audio_clip_end = audio.get("tlEnd")
    if not all(
        isinstance(value, int)
        for value in (video_clip_begin, video_clip_end, audio_clip_begin, audio_clip_end)
    ):
        raise WfpError("Selected linked clips do not have integer timeline bounds")
    if video_clip_begin != audio_clip_begin or video_clip_end != audio_clip_end:
        raise WfpError("Selected visual and audio clip ranges do not match")
    if video_end != video_clip_end or video_begin < video_clip_begin:
        raise WfpError("Selected transition is not contained at the end of its linked clips")
    if video_end - video_begin != expected_duration_ticks:
        raise WfpError(
            "Selected transition duration does not match: expected {0}, found {1}".format(
                expected_duration_ticks, video_end - video_begin
            )
        )
    return video_begin, video_end, video_clip_begin


def preflight_linked_transition(
    source: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    expected_duration_ticks: int,
) -> Dict[str, Any]:
    """Resolve one observed linked transition pair without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Linked-transition edits require an existing .wfp source")
    if not isinstance(video_clip_uid, str) or not video_clip_uid:
        raise WfpError("video_clip_uid must be non-empty text")
    if not isinstance(audio_clip_uid, str) or not audio_clip_uid:
        raise WfpError("audio_clip_uid must be non-empty text")
    duration = _positive_ticks(expected_duration_ticks, "expected_duration_ticks")
    matches = 0
    bounds: Optional[Tuple[int, int, int]] = None
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio in _linked_pairs(document, video_clip_uid, audio_clip_uid):
                current_bounds = _transition_bounds(video, audio, duration)
                if bounds is not None and current_bounds != bounds:
                    raise WfpError("Cached linked transition copies have conflicting ranges")
                bounds = current_bounds
                matches += 1
    if matches < 1 or bounds is None:
        raise WfpError("Linked transition selectors did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "tl_begin": bounds[0],
        "tl_end": bounds[1],
        "owner_tl_begin": bounds[2],
        "duration_ticks": duration,
    }


def _pair_state(
    path: Path,
    video_clip_uid: str,
    audio_clip_uid: str,
) -> List[Tuple[Optional[Tuple[str, int, int]], Optional[Tuple[str, int, int]]]]:
    states: List[Tuple[Optional[Tuple[str, int, int]], Optional[Tuple[str, int, int]]]] = []
    seen = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio in _linked_pairs(document, video_clip_uid, audio_clip_uid):
                values: List[Optional[Tuple[str, int, int]]] = []
                for clip in (video, audio):
                    transition = clip.get("postTransition")
                    if isinstance(transition, dict):
                        values.append(
                            (
                                str(transition.get("id")),
                                transition.get("tlBegin"),
                                transition.get("tlEnd"),
                            )
                        )
                    else:
                        values.append(None)
                state = (values[0], values[1])
                if state not in seen:
                    seen.add(state)
                    states.append(state)
    return states


def _audit_transition_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_duration_ticks: int,
    new_duration_ticks: Optional[int],
) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}
    if result.get("added_members"):
        errors.append("Linked-transition copy added archive members")
    if result.get("removed_members"):
        errors.append("Linked-transition copy removed archive members")
    changed_members = result.get("changed_members") or []
    if not changed_members:
        errors.append("Linked-transition copy changed no archive members")
    if any(not member.endswith(TIMELINE_SUFFIX) for member in changed_members):
        errors.append("Linked-transition copy changed a non-timeline archive member")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Linked-transition copy diff was incomplete")

    expected_suffix = ".postTransition" if new_duration_ticks is None else ".postTransition.tlBegin"
    expected_kind = "removed" if new_duration_ticks is None else "changed"
    semantic_changes = 0
    for change in result.get("json_changes") or []:
        if str(change.get("path")).endswith(expected_suffix) and change.get("kind") == expected_kind:
            semantic_changes += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    if semantic_changes < 2 or semantic_changes % 2:
        errors.append("Linked-transition copy did not change a complete visual/audio pair")

    states = _pair_state(output_path, video_clip_uid, audio_clip_uid)
    if new_duration_ticks is None:
        if states != [(None, None)]:
            errors.append("Generated copy still exposes the selected linked transitions")
    else:
        expected_end = preflight_linked_transition(
            source_path,
            video_clip_uid=video_clip_uid,
            audio_clip_uid=audio_clip_uid,
            expected_duration_ticks=old_duration_ticks,
        )["tl_end"]
        expected_begin = expected_end - new_duration_ticks
        expected_state = (
            (_VIDEO_TRANSITION_ID, expected_begin, expected_end),
            (_AUDIO_TRANSITION_ID, expected_begin, expected_end),
        )
        if states != [expected_state]:
            errors.append("Generated copy does not expose the requested linked duration")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated linked-transition copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "semantic_changes": semantic_changes,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def audit_linked_transition_duration_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_duration_ticks: int,
    new_duration_ticks: int,
) -> Dict[str, Any]:
    """Audit a linked transition duration replacement."""

    return _audit_transition_copy(
        source,
        output,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_duration_ticks=old_duration_ticks,
        new_duration_ticks=new_duration_ticks,
    )


def audit_linked_transition_removal_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    expected_duration_ticks: int,
) -> Dict[str, Any]:
    """Audit removal of one linked transition pair."""

    return _audit_transition_copy(
        source,
        output,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_duration_ticks=expected_duration_ticks,
        new_duration_ticks=None,
    )


def _write_linked_transition(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_duration_ticks: int,
    new_duration_ticks: Optional[int],
    expected_source_sha256: Optional[str],
) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Linked-transition edits require .wfp input and output paths")
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    old_duration = _positive_ticks(old_duration_ticks, "old_duration_ticks")
    new_duration = (
        _positive_ticks(new_duration_ticks, "new_duration_ticks")
        if new_duration_ticks is not None
        else None
    )
    if new_duration == old_duration:
        raise WfpError("new_duration_ticks must differ from old_duration_ticks")
    preflight = preflight_linked_transition(
        source_path,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        expected_duration_ticks=old_duration,
    )
    if new_duration is not None:
        new_begin = preflight["tl_end"] - new_duration
        if new_begin < preflight["owner_tl_begin"]:
            raise WfpError("Requested transition duration begins before its linked clips")

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
                        for video, audio in _linked_pairs(
                            document, video_clip_uid, audio_clip_uid
                        ):
                            _transition_bounds(video, audio, old_duration)
                            if new_duration is None:
                                video.pop("postTransition")
                                audio.pop("postTransition")
                            else:
                                begin = preflight["tl_end"] - new_duration
                                video["postTransition"]["tlBegin"] = begin
                                audio["postTransition"]["tlBegin"] = begin
                            member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Linked transition target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        if new_duration is None:
            audit = audit_linked_transition_removal_copy(
                source_path,
                output_path,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                expected_duration_ticks=old_duration,
            )
        else:
            audit = audit_linked_transition_duration_copy(
                source_path,
                output_path,
                video_clip_uid=video_clip_uid,
                audio_clip_uid=audio_clip_uid,
                old_duration_ticks=old_duration,
                new_duration_ticks=new_duration,
            )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated linked-transition copy failed source-aware audit: {0}".format(
                    "; ".join(audit.get("errors") or ["unknown audit failure"])
                )
            )
        return {
            "source": str(source_path),
            "output": str(output_path),
            "video_clip_uid": video_clip_uid,
            "audio_clip_uid": audio_clip_uid,
            "old_duration_ticks": old_duration,
            "new_duration_ticks": new_duration,
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def replace_linked_transition_duration(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_duration_ticks: int,
    new_duration_ticks: int,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Change the duration of one existing linked Dissolve and audio-fade pair."""

    return _write_linked_transition(
        source,
        output,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_duration_ticks=old_duration_ticks,
        new_duration_ticks=new_duration_ticks,
        expected_source_sha256=expected_source_sha256,
    )


def remove_linked_transition(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    expected_duration_ticks: int,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Remove one existing linked Dissolve and audio-fade pair."""

    return _write_linked_transition(
        source,
        output,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_duration_ticks=expected_duration_ticks,
        new_duration_ticks=None,
        expected_source_sha256=expected_source_sha256,
    )
