"""Narrow replacement of an existing Filmora video-clip scale pair."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
DecimalInput = Union[Decimal, float, int, str]
_TRANSFORM_EFFECT_ID = "video/effect/transform"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_decimal(value: DecimalInput, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, float, int, str)):
        raise WfpError("{0} must be a finite decimal number".format(label))
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise WfpError("{0} must be a finite decimal number".format(label)) from exc
    if not result.is_finite():
        raise WfpError("{0} must be a finite decimal number".format(label))
    return result


def _positive_scale(value: DecimalInput, label: str) -> Decimal:
    result = _finite_decimal(value, label)
    if result <= 0:
        raise WfpError("{0} must be greater than zero".format(label))
    return result


def _stored_scale(value: DecimalInput, label: str) -> Decimal:
    """Keep integral percentages serialized as Filmora-style JSON floats."""

    result = _positive_scale(value, label)
    return result.quantize(Decimal("0.0")) if result == result.to_integral_value() else result


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


def _scale_params(clip: MutableMapping[str, Any]) -> Dict[str, List[MutableMapping[str, Any]]]:
    params: Dict[str, List[MutableMapping[str, Any]]] = {"Scale_x": [], "Scale_y": []}
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return params
    for chain in chains:
        if not isinstance(chain, dict) or not isinstance(chain.get("effectList"), list):
            continue
        for effect in chain["effectList"]:
            if (
                not isinstance(effect, dict)
                or effect.get("id") != _TRANSFORM_EFFECT_ID
                or not isinstance(effect.get("paramList"), list)
            ):
                continue
            for parameter in effect["paramList"]:
                if not isinstance(parameter, dict) or parameter.get("name") not in params:
                    continue
                fx_param = parameter.get("fxParam")
                if isinstance(fx_param, dict) and "unValue" in fx_param:
                    params[parameter["name"]].append(parameter)
    return params


def _replace_scale(
    clip: MutableMapping[str, Any],
    clip_uid: str,
    old_x: Decimal,
    old_y: Decimal,
    new_x: Decimal,
    new_y: Decimal,
) -> bool:
    if clip.get("thisUId") != clip_uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected scale target is not a type-1 video clip")
    params = _scale_params(clip)
    if len(params["Scale_x"]) != 1 or len(params["Scale_y"]) != 1:
        raise WfpError("Selected clip does not expose exactly one existing Scale_x and Scale_y parameter")
    current_x = _positive_scale(params["Scale_x"][0]["fxParam"]["unValue"], "current Scale_x")
    current_y = _positive_scale(params["Scale_y"][0]["fxParam"]["unValue"], "current Scale_y")
    if current_x != old_x or current_y != old_y:
        raise WfpError(
            "Selected clip scale does not match: expected ({0}, {1}), found ({2}, {3})".format(
                old_x, old_y, current_x, current_y
            )
        )
    params["Scale_x"][0]["fxParam"]["unValue"] = new_x
    params["Scale_y"][0]["fxParam"]["unValue"] = new_y
    return True


def preflight_clip_scale(
    source: Pathish,
    *,
    clip_uid: str,
    old_scale_x: DecimalInput,
    old_scale_y: DecimalInput,
    new_scale_x: DecimalInput,
    new_scale_y: DecimalInput,
) -> Dict[str, Any]:
    """Resolve one existing scale target without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Scale replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old_x = _positive_scale(old_scale_x, "old_scale_x")
    old_y = _positive_scale(old_scale_y, "old_scale_y")
    new_x = _stored_scale(new_scale_x, "new_scale_x")
    new_y = _stored_scale(new_scale_y, "new_scale_y")
    if old_x != old_y or new_x != new_y:
        raise WfpError("Only linked uniform scale replacement has been verified")
    if old_x == new_x and old_y == new_y:
        raise WfpError("New scale must differ from the current scale")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                candidate = copy.deepcopy(clip)
                if _replace_scale(candidate, clip_uid, old_x, old_y, new_x, new_y):
                    matches += 1
    if matches < 1:
        raise WfpError("Scale selector did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_scale_x": str(old_x),
        "old_scale_y": str(old_y),
        "new_scale_x": str(new_x),
        "new_scale_y": str(new_y),
    }


def _scales_for_uid(path: Path, clip_uid: str) -> List[Tuple[Decimal, Decimal]]:
    found: List[Tuple[Decimal, Decimal]] = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if clip.get("thisUId") != clip_uid:
                    continue
                params = _scale_params(clip)
                if len(params["Scale_x"]) == 1 and len(params["Scale_y"]) == 1:
                    value = (
                        _positive_scale(params["Scale_x"][0]["fxParam"]["unValue"], "Scale_x"),
                        _positive_scale(params["Scale_y"][0]["fxParam"]["unValue"], "Scale_y"),
                    )
                    if value not in found:
                        found.append(value)
    return found


def audit_clip_scale_copy(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_scale_x: DecimalInput,
    old_scale_y: DecimalInput,
    new_scale_x: DecimalInput,
    new_scale_y: DecimalInput,
) -> Dict[str, Any]:
    """Confirm that a generated copy changed only the selected scale values."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    old_x = _positive_scale(old_scale_x, "old_scale_x")
    old_y = _positive_scale(old_scale_y, "old_scale_y")
    new_x = _positive_scale(new_scale_x, "new_scale_x")
    new_y = _positive_scale(new_scale_y, "new_scale_y")
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}
    if result.get("added_members") or result.get("removed_members"):
        errors.append("Scale copy changed archive membership")
    changed_members = result.get("changed_members") or []
    if not changed_members:
        errors.append("Scale copy changed no archive members")
    if any(not member.endswith(TIMELINE_SUFFIX) for member in changed_members):
        errors.append("Scale copy changed a non-timeline archive member")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Scale copy diff was incomplete")
    expected_pairs = set()
    if old_x != new_x:
        expected_pairs.add((old_x, new_x))
    if old_y != new_y:
        expected_pairs.add((old_y, new_y))
    observed_pairs = set()
    for change in result.get("json_changes") or []:
        try:
            pair = (
                _positive_scale(change.get("before"), "diff before"),
                _positive_scale(change.get("after"), "diff after"),
            )
        except WfpError:
            pair = (Decimal("NaN"), Decimal("NaN"))
        if str(change.get("path")).endswith(".fxParam.unValue") and pair in expected_pairs:
            observed_pairs.add(pair)
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    if observed_pairs != expected_pairs:
        errors.append("Scale copy did not expose exactly the expected semantic changes")
    if _scales_for_uid(output_path, clip_uid) != [(new_x, new_y)]:
        errors.append("Generated copy does not expose exactly one updated scale pair")
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated scale copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "scale_values_changed": len(observed_pairs),
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def replace_clip_scale(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_scale_x: DecimalInput,
    old_scale_y: DecimalInput,
    new_scale_x: DecimalInput,
    new_scale_y: DecimalInput,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Change existing video transform scale values in a new WFP copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Scale replacement requires .wfp input and output paths")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_clip_scale(
        source_path,
        clip_uid=clip_uid,
        old_scale_x=old_scale_x,
        old_scale_y=old_scale_y,
        new_scale_x=new_scale_x,
        new_scale_y=new_scale_y,
    )
    old_x = Decimal(preflight["old_scale_x"])
    old_y = Decimal(preflight["old_scale_y"])
    new_x = Decimal(preflight["new_scale_x"])
    new_y = Decimal(preflight["new_scale_y"])
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
                            if _replace_scale(clip, clip_uid, old_x, old_y, new_x, new_y):
                                member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Scale target count changed while the copy was being written")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_clip_scale_copy(
            source_path,
            output_path,
            clip_uid=clip_uid,
            old_scale_x=old_x,
            old_scale_y=old_y,
            new_scale_x=new_x,
            new_scale_y=new_y,
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated scale copy failed source-aware audit: {0}".format(
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
