"""Narrow replacement of an existing Filmora audio-clip fade-in value."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .analysis import WFP_TICKS_PER_SECOND
from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
FadeTimeInput = Union[Decimal, float, int, str]
_FADE_EFFECT_ID = "audio/effect/fade"
_FADE_IN_PARAM = "FadeInTime"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_fade_time(value: FadeTimeInput, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, float, int, str)):
        raise WfpError("{0} must be a positive finite decimal number".format(label))
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise WfpError("{0} must be a positive finite decimal number".format(label)) from exc
    if not result.is_finite() or result <= 0:
        raise WfpError("{0} must be a positive finite decimal number".format(label))
    return result


def _clips(document: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    found: List[MutableMapping[str, Any]] = []
    timelines = document.get("timelineInfos")
    if not isinstance(timelines, list):
        return found
    for timeline in timelines:
        if not isinstance(timeline, dict):
            continue
        tracks = timeline.get("trackInfos")
        if not isinstance(tracks, list):
            continue
        for track in tracks:
            if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
                continue
            found.extend(clip for clip in track["clipList"] if isinstance(clip, dict))
    return found


def _fade_in_params(clip: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    params: List[MutableMapping[str, Any]] = []
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return params
    for chain in chains:
        if not isinstance(chain, dict) or not isinstance(chain.get("effectList"), list):
            continue
        for effect in chain["effectList"]:
            if (
                not isinstance(effect, dict)
                or effect.get("id") != _FADE_EFFECT_ID
                or not isinstance(effect.get("paramList"), list)
            ):
                continue
            for param in effect["paramList"]:
                if (
                    isinstance(param, dict)
                    and param.get("name") == _FADE_IN_PARAM
                    and isinstance(param.get("fxParam"), dict)
                    and "unValue" in param["fxParam"]
                ):
                    params.append(param)
    return params


def _clip_duration_seconds(clip: MutableMapping[str, Any]) -> Decimal:
    begin = clip.get("tlBegin")
    end = clip.get("tlEnd")
    if not isinstance(begin, int) or not isinstance(end, int) or end <= begin:
        raise WfpError("Selected fade-in target has an invalid timeline range")
    return Decimal(end - begin) / WFP_TICKS_PER_SECOND


def _replace_fade_in(
    clip: MutableMapping[str, Any],
    clip_uid: str,
    old_fade_in: Decimal,
    new_fade_in: Decimal,
) -> bool:
    if clip.get("thisUId") != clip_uid:
        return False
    if clip.get("type") != 2:
        raise WfpError("Selected fade-in target is not a type-2 audio clip")
    duration = _clip_duration_seconds(clip)
    if old_fade_in > duration or new_fade_in > duration:
        raise WfpError(
            "Fade-in time must not exceed the selected clip duration of {0} seconds".format(
                duration
            )
        )
    params = _fade_in_params(clip)
    if len(params) != 1:
        raise WfpError("Selected clip does not expose exactly one existing FadeInTime parameter")
    current = _positive_fade_time(params[0]["fxParam"]["unValue"], "current FadeInTime")
    if current != old_fade_in:
        raise WfpError(
            "Selected clip FadeInTime does not match: expected {0}, found {1}".format(
                old_fade_in, current
            )
        )
    params[0]["fxParam"]["unValue"] = new_fade_in
    return True


def preflight_clip_fade_in(
    source: Pathish,
    *,
    clip_uid: str,
    old_fade_in: FadeTimeInput,
    new_fade_in: FadeTimeInput,
) -> Dict[str, Any]:
    """Resolve one existing clip fade-in target without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Fade-in replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old_value = _positive_fade_time(old_fade_in, "old_fade_in")
    new_value = _positive_fade_time(new_fade_in, "new_fade_in")
    if old_value == new_value:
        raise WfpError("new_fade_in must differ from old_fade_in")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                candidate = copy.deepcopy(clip)
                if _replace_fade_in(candidate, clip_uid, old_value, new_value):
                    matches += 1
    if matches < 1:
        raise WfpError("FadeInTime selector did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_fade_in": str(old_value),
        "new_fade_in": str(new_value),
    }


def _fade_ins_for_uid(path: Path, clip_uid: str) -> List[Decimal]:
    found: List[Decimal] = []
    seen: set[Tuple[str, Decimal]] = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if clip.get("thisUId") != clip_uid:
                    continue
                for param in _fade_in_params(clip):
                    value = _positive_fade_time(param["fxParam"]["unValue"], "FadeInTime")
                    key = (str(clip.get("thisUId")), value)
                    if key not in seen:
                        seen.add(key)
                        found.append(value)
    return found


def audit_clip_fade_in_copy(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_fade_in: FadeTimeInput,
    new_fade_in: FadeTimeInput,
) -> Dict[str, Any]:
    """Confirm that a generated copy changed only the selected FadeInTime value."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    old_value = _positive_fade_time(old_fade_in, "old_fade_in")
    new_value = _positive_fade_time(new_fade_in, "new_fade_in")
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}

    if result.get("added_members"):
        errors.append("Fade-in copy added archive members")
    if result.get("removed_members"):
        errors.append("Fade-in copy removed archive members")
    changed_members = result.get("changed_members") or []
    if not changed_members:
        errors.append("Fade-in copy changed no archive members")
    if any(not member.endswith(TIMELINE_SUFFIX) for member in changed_members):
        errors.append("Fade-in copy changed a non-timeline archive member")
    if result.get("parse_errors"):
        errors.append("Fade-in copy contains JSON parse errors")
    if result.get("truncated"):
        errors.append("Fade-in copy diff was unexpectedly truncated")

    fade_in_changes = 0
    for change in result.get("json_changes") or []:
        try:
            before = _positive_fade_time(change.get("before"), "diff before")
            after = _positive_fade_time(change.get("after"), "diff after")
        except WfpError:
            before = after = Decimal("NaN")
        if (
            str(change.get("path")).endswith(".fxParam.unValue")
            and before == old_value
            and after == new_value
        ):
            fade_in_changes += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    if fade_in_changes < 1:
        errors.append("Fade-in copy did not expose the expected semantic change")

    output_fade_ins = _fade_ins_for_uid(output_path, clip_uid)
    if output_fade_ins != [new_value]:
        errors.append("Generated copy does not expose exactly one updated FadeInTime value")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated fade-in copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "fade_in_occurrences_changed": fade_in_changes,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def replace_clip_fade_in(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_fade_in: FadeTimeInput,
    new_fade_in: FadeTimeInput,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Change one already-present audio FadeInTime value in a new WFP copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Fade-in replacement requires .wfp input and output paths")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))

    preflight = preflight_clip_fade_in(
        source_path,
        clip_uid=clip_uid,
        old_fade_in=old_fade_in,
        new_fade_in=new_fade_in,
    )
    old_value = Decimal(preflight["old_fade_in"])
    new_value = Decimal(preflight["new_fade_in"])
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
                        for clip in _clips(document):
                            if _replace_fade_in(clip, clip_uid, old_value, new_value):
                                member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("FadeInTime target count changed while the copy was being written")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_clip_fade_in_copy(
            source_path,
            output_path,
            clip_uid=clip_uid,
            old_fade_in=old_value,
            new_fade_in=new_value,
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated fade-in copy failed source-aware audit: {0}".format(
                    "; ".join(audit.get("errors") or ["unknown audit failure"])
                )
            )
        return {
            "source": str(source_path),
            "output": str(output_path),
            "clip_uid": clip_uid,
            "old_fade_in": str(old_value),
            "new_fade_in": str(new_value),
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
