"""Narrow replacement of an existing Filmora horizontal-flip effect state."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
_EFFECT_ID = "video/effect/horizontal_filp"
_STATE_KEY = 101
_ON_DATA = "AQAAAA=="
_OFF_DATA = "AAAAAA=="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            if isinstance(track, dict) and isinstance(track.get("clipList"), list):
                found.extend(clip for clip in track["clipList"] if isinstance(clip, dict))
    return found


def _effects(clip: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    found: List[MutableMapping[str, Any]] = []
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return found
    for chain in chains:
        if not isinstance(chain, dict) or not isinstance(chain.get("effectList"), list):
            continue
        found.extend(
            effect
            for effect in chain["effectList"]
            if isinstance(effect, dict) and effect.get("id") == _EFFECT_ID
        )
    return found


def _state_entry(effect: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    user_data = effect.get("userData")
    if not isinstance(user_data, list):
        raise WfpError("Horizontal flip effect does not expose userData")
    matches = [
        entry
        for entry in user_data
        if isinstance(entry, dict)
        and entry.get("key") == _STATE_KEY
        and entry.get("size") == 4
        and isinstance(entry.get("data"), str)
    ]
    if len(matches) != 1:
        raise WfpError("Horizontal flip effect does not expose exactly one key-101 state")
    return matches[0]


def _effect_state(effect: MutableMapping[str, Any]) -> bool:
    data = _state_entry(effect)["data"]
    if data == _ON_DATA and "enable" not in effect:
        return True
    if data == _OFF_DATA and effect.get("enable") is False:
        return False
    raise WfpError("Horizontal flip effect has an unverified state shape")


def _replace_state(clip: MutableMapping[str, Any], clip_uid: str, old: bool, new: bool) -> bool:
    if clip.get("thisUId") != clip_uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected horizontal flip target is not a type-1 video clip")
    effects = _effects(clip)
    if len(effects) != 1:
        raise WfpError("Selected clip does not expose exactly one existing horizontal flip effect")
    effect = effects[0]
    current = _effect_state(effect)
    if current is not old:
        raise WfpError(
            "Selected clip horizontal flip does not match: expected {0}, found {1}".format(
                old, current
            )
        )
    if new:
        effect.pop("enable", None)
        _state_entry(effect)["data"] = _ON_DATA
    else:
        effect["enable"] = False
        _state_entry(effect)["data"] = _OFF_DATA
    return True


def preflight_clip_horizontal_flip(
    source: Pathish,
    *,
    clip_uid: str,
    old_enabled: bool,
    new_enabled: bool,
) -> Dict[str, Any]:
    """Resolve one existing horizontal flip effect without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Horizontal flip replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    if not isinstance(old_enabled, bool) or not isinstance(new_enabled, bool):
        raise WfpError("Horizontal flip states must be booleans")
    if old_enabled is new_enabled:
        raise WfpError("New horizontal flip state must differ from the current state")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                candidate = copy.deepcopy(clip)
                if _replace_state(candidate, clip_uid, old_enabled, new_enabled):
                    matches += 1
    if matches < 1:
        raise WfpError("Horizontal flip selector did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_enabled": old_enabled,
        "new_enabled": new_enabled,
    }


def _states_for_uid(path: Path, clip_uid: str) -> List[bool]:
    found: List[bool] = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if clip.get("thisUId") != clip_uid:
                    continue
                effects = _effects(clip)
                if len(effects) == 1:
                    state = _effect_state(effects[0])
                    if state not in found:
                        found.append(state)
    return found


def audit_clip_horizontal_flip_copy(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_enabled: bool,
    new_enabled: bool,
) -> Dict[str, Any]:
    """Confirm only the verified two-part flip state changed."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}
    if result.get("added_members") or result.get("removed_members"):
        errors.append("Horizontal flip copy changed archive membership")
    changed_members = result.get("changed_members") or []
    if not changed_members or any(
        not member.endswith(TIMELINE_SUFFIX) for member in changed_members
    ):
        errors.append("Horizontal flip copy changed unexpected archive members")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Horizontal flip copy diff was incomplete")
    expected_data = (_ON_DATA, _OFF_DATA) if not new_enabled else (_OFF_DATA, _ON_DATA)
    saw_enable = False
    saw_data = False
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        if path.endswith(".enable"):
            expected_kind = "removed" if new_enabled else "added"
            expected_value = change.get("before") if new_enabled else change.get("after")
            if change.get("kind") == expected_kind and expected_value is False:
                saw_enable = True
                continue
        # Filmora currently stores key 101 at index 1, but array order is not
        # part of the state contract. The output-state check below proves the
        # changed data belongs to the one verified key-101 entry.
        if ".userData[" in path and path.endswith("].data") and (
            change.get("before"), change.get("after")
        ) == expected_data:
            saw_data = True
            continue
        errors.append("Unexpected semantic change: {0}".format(path))
    if not saw_enable or not saw_data:
        errors.append("Horizontal flip copy did not expose both expected state changes")
    if _states_for_uid(output_path, clip_uid) != [new_enabled]:
        errors.append("Generated copy does not expose exactly one updated flip state")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated horizontal flip copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "enable_changed": saw_enable,
            "key_101_changed": saw_data,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def replace_clip_horizontal_flip(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_enabled: bool,
    new_enabled: bool,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Change one existing horizontal-flip state in a new WFP copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Horizontal flip replacement requires .wfp input and output paths")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_clip_horizontal_flip(
        source_path,
        clip_uid=clip_uid,
        old_enabled=old_enabled,
        new_enabled=new_enabled,
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
        prefix=output_path.name + ".", suffix=".tmp", dir=str(output_path.parent), delete=False
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
                            if _replace_state(clip, clip_uid, old_enabled, new_enabled):
                                member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Horizontal flip target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_clip_horizontal_flip_copy(
            source_path,
            output_path,
            clip_uid=clip_uid,
            old_enabled=old_enabled,
            new_enabled=new_enabled,
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated horizontal flip copy failed source-aware audit: {0}".format(
                    "; ".join(audit.get("errors") or ["unknown audit failure"])
                )
            )
        return {
            "source": str(source_path),
            "output": str(output_path),
            "clip_uid": clip_uid,
            **preflight,
            "changed_members": changed_members,
            "audit": audit,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
