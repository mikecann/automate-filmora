"""Narrow timeline move for one already-linked visual/audio clip pair."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import PROJECT_INFO_MEMBER, TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ticks(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WfpError("{0} must be a non-negative integer tick count".format(label))
    return value


def _pair_occurrences(
    document: MutableMapping[str, Any],
    video_clip_uid: str,
    audio_clip_uid: str,
) -> List[
    Tuple[
        MutableMapping[str, Any],
        MutableMapping[str, Any],
        List[MutableMapping[str, Any]],
        List[MutableMapping[str, Any]],
    ]
]:
    pairs = []
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
            clips = [clip for clip in track["clipList"] if isinstance(clip, dict)]
            for clip in clips:
                if clip.get("thisUId") == video_clip_uid:
                    if track.get("trackType") != 1 or clip.get("type") != 1:
                        raise WfpError("Selected visual move target is not a type-1 visual clip")
                    videos.append((clip, clips))
                if clip.get("thisUId") == audio_clip_uid:
                    if track.get("trackType") != 2 or clip.get("type") != 2:
                        raise WfpError("Selected audio move target is not a type-2 audio clip")
                    audios.append((clip, clips))
        if videos or audios:
            if len(videos) != 1 or len(audios) != 1:
                raise WfpError("Linked A/V move selectors must resolve together exactly once")
            pairs.append((videos[0][0], audios[0][0], videos[0][1], audios[0][1]))
    return pairs


def _validate_pair(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    video_track: List[MutableMapping[str, Any]],
    audio_track: List[MutableMapping[str, Any]],
    *,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> int:
    if video.get("sourceUuid") != audio.get("sourceUuid") or not video.get("sourceUuid"):
        raise WfpError("Selected visual and audio clips do not share one sourceUuid")
    if any(key in clip for clip in (video, audio) for key in ("preTransition", "postTransition")):
        raise WfpError("Moving clips with transitions is not supported")
    for clip in (video, audio):
        if clip.get("tlBegin") != old_start_ticks or clip.get("tlEnd") != old_end_ticks:
            raise WfpError("Selected linked clip bounds do not match the requested old range")
    if old_end_ticks <= old_start_ticks:
        raise WfpError("Selected linked clip range must have positive duration")
    new_end_ticks = new_start_ticks + (old_end_ticks - old_start_ticks)
    if new_start_ticks == old_start_ticks:
        raise WfpError("new_start_ticks must differ from old_start_ticks")

    for selected, clips in ((video, video_track), (audio, audio_track)):
        for other in clips:
            if other is selected:
                continue
            begin = other.get("tlBegin")
            end = other.get("tlEnd")
            if not isinstance(begin, int) or not isinstance(end, int):
                continue
            if new_start_ticks < end and begin < new_end_ticks:
                raise WfpError("Requested linked A/V move overlaps another clip on its track")
    return new_end_ticks


def preflight_linked_av_move(
    source: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> Dict[str, Any]:
    """Resolve one transition-free linked A/V move without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Linked A/V moves require an existing .wfp source")
    if not isinstance(video_clip_uid, str) or not video_clip_uid:
        raise WfpError("video_clip_uid must be non-empty text")
    if not isinstance(audio_clip_uid, str) or not audio_clip_uid:
        raise WfpError("audio_clip_uid must be non-empty text")
    old_start = _ticks(old_start_ticks, "old_start_ticks")
    old_end = _ticks(old_end_ticks, "old_end_ticks")
    new_start = _ticks(new_start_ticks, "new_start_ticks")
    matches = 0
    new_end: Optional[int] = None
    with zipfile.ZipFile(source_path, "r") as archive:
        project_info = _load_decimal_json(archive.read(PROJECT_INFO_MEMBER))
        declared_duration = project_info.get("project_timeline_duration")
        if not isinstance(declared_duration, int) or declared_duration <= 0:
            raise WfpError("Source project does not declare a positive timeline duration")
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio, video_track, audio_track in _pair_occurrences(
                document, video_clip_uid, audio_clip_uid
            ):
                candidate_end = _validate_pair(
                    video,
                    audio,
                    video_track,
                    audio_track,
                    old_start_ticks=old_start,
                    old_end_ticks=old_end,
                    new_start_ticks=new_start,
                )
                if new_end is not None and candidate_end != new_end:
                    raise WfpError("Cached linked A/V copies have conflicting durations")
                new_end = candidate_end
                matches += 1
    if matches < 1 or new_end is None:
        raise WfpError("Linked A/V move selectors did not match the source project")
    if new_end > declared_duration:
        raise WfpError("Requested move would extend the declared project duration")
    return {
        "matching_archive_occurrences": matches,
        "old_start_ticks": old_start,
        "old_end_ticks": old_end,
        "new_start_ticks": new_start,
        "new_end_ticks": new_end,
        "declared_project_duration": declared_duration,
    }


def _pair_ranges(path: Path, video_clip_uid: str, audio_clip_uid: str) -> List[Tuple[int, int]]:
    ranges = []
    seen = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio, _video_track, _audio_track in _pair_occurrences(
                document, video_clip_uid, audio_clip_uid
            ):
                values = (
                    video.get("tlBegin"),
                    video.get("tlEnd"),
                    audio.get("tlBegin"),
                    audio.get("tlEnd"),
                )
                if values[0] != values[2] or values[1] != values[3]:
                    continue
                pair_range = (values[0], values[1])
                if pair_range not in seen:
                    seen.add(pair_range)
                    ranges.append(pair_range)
    return ranges


def audit_linked_av_move_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> Dict[str, Any]:
    """Confirm a copy changed only both linked clips' timeline bounds."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    preflight = preflight_linked_av_move(
        source_path,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_start_ticks=old_start_ticks,
        old_end_ticks=old_end_ticks,
        new_start_ticks=new_start_ticks,
    )
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}
    if result.get("added_members") or result.get("removed_members"):
        errors.append("Linked A/V move changed the archive member set")
    changed_members = result.get("changed_members") or []
    if not changed_members or any(
        not member.endswith(TIMELINE_SUFFIX) for member in changed_members
    ):
        errors.append("Linked A/V move changed members outside timeline documents")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Linked A/V move diff was incomplete")
    expected_values = {
        "tlBegin": (preflight["old_start_ticks"], preflight["new_start_ticks"]),
        "tlEnd": (preflight["old_end_ticks"], preflight["new_end_ticks"]),
    }
    semantic_changes = 0
    for change in result.get("json_changes") or []:
        field = str(change.get("path")).rsplit(".", 1)[-1]
        expected = expected_values.get(field)
        if change.get("kind") == "changed" and expected == (
            change.get("before"),
            change.get("after"),
        ):
            semantic_changes += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    expected_change_count = preflight["matching_archive_occurrences"] * 4
    if semantic_changes != expected_change_count:
        errors.append(
            "Linked A/V move changed {0} bounds; expected {1}".format(
                semantic_changes, expected_change_count
            )
        )
    if _pair_ranges(output_path, video_clip_uid, audio_clip_uid) != [
        (preflight["new_start_ticks"], preflight["new_end_ticks"])
    ]:
        errors.append("Generated copy does not expose exactly one requested linked range")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated linked A/V move copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "semantic_changes": semantic_changes,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def move_linked_av_pair(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Move one transition-free linked A/V pair without extending project duration."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Linked A/V moves require .wfp input and output paths")
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_linked_av_move(
        source_path,
        video_clip_uid=video_clip_uid,
        audio_clip_uid=audio_clip_uid,
        old_start_ticks=old_start_ticks,
        old_end_ticks=old_end_ticks,
        new_start_ticks=new_start_ticks,
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
                            _validate_pair(
                                video,
                                audio,
                                video_track,
                                audio_track,
                                old_start_ticks=preflight["old_start_ticks"],
                                old_end_ticks=preflight["old_end_ticks"],
                                new_start_ticks=preflight["new_start_ticks"],
                            )
                            for clip in (video, audio):
                                clip["tlBegin"] = preflight["new_start_ticks"]
                                clip["tlEnd"] = preflight["new_end_ticks"]
                            member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Linked A/V move target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_linked_av_move_copy(
            source_path,
            output_path,
            video_clip_uid=video_clip_uid,
            audio_clip_uid=audio_clip_uid,
            old_start_ticks=preflight["old_start_ticks"],
            old_end_ticks=preflight["old_end_ticks"],
            new_start_ticks=preflight["new_start_ticks"],
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated linked A/V move copy failed source-aware audit: {0}".format(
                    "; ".join(audit.get("errors") or ["unknown audit failure"])
                )
            )
        return {
            "source": str(source_path),
            "output": str(output_path),
            "video_clip_uid": video_clip_uid,
            "audio_clip_uid": audio_clip_uid,
            "old_start_ticks": preflight["old_start_ticks"],
            "old_end_ticks": preflight["old_end_ticks"],
            "new_start_ticks": preflight["new_start_ticks"],
            "new_end_ticks": preflight["new_end_ticks"],
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
