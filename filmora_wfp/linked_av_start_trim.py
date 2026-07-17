"""Narrow start trim for one forward 1x linked visual/audio pair."""

from __future__ import annotations

import copy
import os
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .linked_av import (
    TICKS_PER_SECOND,
    _normal_speed_state,
    _pair_occurrences,
    _sha256,
    _ticks,
)
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]


def _validate_start_trim_pair(
    video: MutableMapping[str, Any],
    audio: MutableMapping[str, Any],
    *,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> Tuple[int, Decimal]:
    if video.get("sourceUuid") != audio.get("sourceUuid") or not video.get("sourceUuid"):
        raise WfpError("Selected visual and audio clips do not share one sourceUuid")
    if any(key in clip for clip in (video, audio) for key in ("preTransition", "postTransition")):
        raise WfpError("Trimming clips with transitions is not supported")
    for clip in (video, audio):
        if clip.get("tlBegin") != old_start_ticks or clip.get("tlEnd") != old_end_ticks:
            raise WfpError("Selected linked clip bounds do not match the requested old range")
    if not old_start_ticks < new_start_ticks < old_end_ticks:
        raise WfpError("new_start_ticks must shorten the selected positive clip range")
    video_speed = _normal_speed_state(video)
    audio_speed = _normal_speed_state(audio)
    if video_speed != audio_speed or video.get("speed", {}).get("speedParam") != audio.get(
        "speed", {}
    ).get("speedParam"):
        raise WfpError("Selected linked clips do not share one normal-speed source range")
    old_in_point, out_point, _offset, _offset_end = video_speed
    if out_point - old_in_point != old_end_ticks - old_start_ticks:
        raise WfpError("Selected source and timeline durations are not a 1x mapping")
    new_in_point = old_in_point + (new_start_ticks - old_start_ticks)
    if new_in_point >= out_point:
        raise WfpError("Requested trim would remove the entire selected source range")
    raw_offset = Decimal(new_in_point) / TICKS_PER_SECOND
    new_offset = (
        raw_offset.quantize(Decimal("0.0")) if raw_offset.as_tuple().exponent >= -1 else raw_offset
    )
    return new_in_point, new_offset


def preflight_linked_av_start_trim(
    source: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> Dict[str, Any]:
    """Resolve one transition-free, normal-speed linked A/V start trim."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Linked A/V start trims require an existing .wfp source")
    if not isinstance(video_clip_uid, str) or not video_clip_uid:
        raise WfpError("video_clip_uid must be non-empty text")
    if not isinstance(audio_clip_uid, str) or not audio_clip_uid:
        raise WfpError("audio_clip_uid must be non-empty text")
    old_start = _ticks(old_start_ticks, "old_start_ticks")
    old_end = _ticks(old_end_ticks, "old_end_ticks")
    new_start = _ticks(new_start_ticks, "new_start_ticks")
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
                candidate_in, candidate_offset = _validate_start_trim_pair(
                    video,
                    audio,
                    old_start_ticks=old_start,
                    old_end_ticks=old_end,
                    new_start_ticks=new_start,
                )
                if new_in_point is not None and (
                    candidate_in != new_in_point or candidate_offset != new_offset
                ):
                    raise WfpError("Cached linked A/V copies have conflicting trim state")
                new_in_point = candidate_in
                new_offset = candidate_offset
                matches += 1
    if matches < 1 or new_in_point is None or new_offset is None:
        raise WfpError("Linked A/V start trim selectors did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_start_ticks": old_start,
        "old_end_ticks": old_end,
        "new_start_ticks": new_start,
        "new_in_point": new_in_point,
        "new_offset": new_offset,
    }


def _pair_start_states(path: Path, video_clip_uid: str, audio_clip_uid: str) -> List[Tuple[Any, ...]]:
    states = []
    seen = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for video, audio, _video_track, _audio_track in _pair_occurrences(
                document, video_clip_uid, audio_clip_uid
            ):
                state = tuple(
                    clip.get(field)
                    for clip in (video, audio)
                    for field in ("tlBegin", "tlEnd", "inPoint", "outPoint")
                ) + tuple(clip.get("speed", {}).get("offset") for clip in (video, audio))
                if state not in seen:
                    seen.add(state)
                    states.append(state)
    return states


def audit_linked_av_start_trim_copy(
    source: Pathish,
    output: Pathish,
    *,
    video_clip_uid: str,
    audio_clip_uid: str,
    old_start_ticks: int,
    old_end_ticks: int,
    new_start_ticks: int,
) -> Dict[str, Any]:
    """Confirm a copy changed only both linked clips' three start fields."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    preflight = preflight_linked_av_start_trim(
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
        errors.append("Linked A/V start trim changed the archive member set")
    changed_members = result.get("changed_members") or []
    if not changed_members or any(
        not member.endswith(TIMELINE_SUFFIX) for member in changed_members
    ):
        errors.append("Linked A/V start trim changed members outside timeline documents")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Linked A/V start trim diff was incomplete")
    expected_values = {
        "tlBegin": (preflight["old_start_ticks"], preflight["new_start_ticks"]),
        "inPoint": (None, preflight["new_in_point"]),
        "offset": (None, preflight["new_offset"]),
    }
    semantic_changes = 0
    for change in result.get("json_changes") or []:
        field = str(change.get("path")).rsplit(".", 1)[-1]
        expected = expected_values.get(field)
        after_matches = bool(expected and change.get("after") == expected[1])
        if field == "offset" and expected:
            try:
                after_matches = Decimal(str(change.get("after"))) == expected[1]
            except Exception:
                after_matches = False
        matches = bool(
            change.get("kind") == "changed"
            and expected
            and after_matches
            and (expected[0] is None or change.get("before") == expected[0])
        )
        if matches:
            semantic_changes += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    expected_change_count = preflight["matching_archive_occurrences"] * 6
    if semantic_changes != expected_change_count:
        errors.append(
            "Linked A/V start trim changed {0} fields; expected {1}".format(
                semantic_changes, expected_change_count
            )
        )
    output_states = _pair_start_states(output_path, video_clip_uid, audio_clip_uid)
    if len(output_states) != 1:
        errors.append("Generated copy does not expose exactly one linked trim state")
    elif not (
        output_states[0][0] == preflight["new_start_ticks"]
        and output_states[0][1] == preflight["old_end_ticks"]
        and output_states[0][2] == preflight["new_in_point"]
        and output_states[0][4] == preflight["new_start_ticks"]
        and output_states[0][5] == preflight["old_end_ticks"]
        and output_states[0][6] == preflight["new_in_point"]
        and output_states[0][8:] == (preflight["new_offset"], preflight["new_offset"])
    ):
        errors.append("Generated copy does not retain the requested linked trim values")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated linked A/V start trim copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "semantic_changes": semantic_changes,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def trim_linked_av_pair_start(
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
    """Shorten the start of one normal-speed linked A/V pair into a new copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Linked A/V start trims require .wfp input and output paths")
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_linked_av_start_trim(
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
                        for video, audio, _video_track, _audio_track in _pair_occurrences(
                            document, video_clip_uid, audio_clip_uid
                        ):
                            _validate_start_trim_pair(
                                video,
                                audio,
                                old_start_ticks=preflight["old_start_ticks"],
                                old_end_ticks=preflight["old_end_ticks"],
                                new_start_ticks=preflight["new_start_ticks"],
                            )
                            for clip in (video, audio):
                                clip["tlBegin"] = preflight["new_start_ticks"]
                                clip["inPoint"] = preflight["new_in_point"]
                                clip["speed"]["offset"] = preflight["new_offset"]
                            member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Linked A/V start trim target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_linked_av_start_trim_copy(
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
                "Generated linked A/V start trim copy failed source-aware audit: {0}".format(
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
            "new_in_point": preflight["new_in_point"],
            "new_offset": preflight["new_offset"],
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
