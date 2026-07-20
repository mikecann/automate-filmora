"""Guarded replacement of an existing uniform Filmora corner radius."""

from __future__ import annotations

import copy
import os
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .scale import DecimalInput, _clips, _finite_decimal, _sha256
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]
_EFFECT_ID = "video/effect/transform"
_PARAMETER_NAMES = ("LeftTop", "RightTop", "LeftBottom", "RightBottom")


def _stored_radius(value: DecimalInput, label: str) -> Decimal:
    result = _finite_decimal(value, label)
    if result <= 0 or result > 100:
        raise WfpError("{0} must be greater than zero and at most 100".format(label))
    return result.quantize(Decimal("0.0")) if result == result.to_integral_value() else result


def _radius_params(
    clip: MutableMapping[str, Any],
) -> Dict[str, List[MutableMapping[str, Any]]]:
    params: Dict[str, List[MutableMapping[str, Any]]] = {
        name: [] for name in _PARAMETER_NAMES
    }
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return params
    for chain in chains:
        effects = chain.get("effectList") if isinstance(chain, dict) else None
        if not isinstance(effects, list):
            continue
        for effect in effects:
            if (
                not isinstance(effect, dict)
                or effect.get("id") != _EFFECT_ID
                or not isinstance(effect.get("paramList"), list)
            ):
                continue
            for parameter in effect["paramList"]:
                if not isinstance(parameter, dict) or parameter.get("name") not in params:
                    continue
                fx_param = parameter.get("fxParam")
                if (
                    isinstance(fx_param, dict)
                    and fx_param.get("paramType") == 3
                    and "unValue" in fx_param
                ):
                    params[parameter["name"]].append(parameter)
    return params


def _uniform_radius(clip: MutableMapping[str, Any]) -> Decimal:
    params = _radius_params(clip)
    if any(len(params[name]) != 1 for name in _PARAMETER_NAMES):
        raise WfpError(
            "Selected clip does not expose exactly one complete corner-radius quartet"
        )
    values = [
        _stored_radius(params[name][0]["fxParam"]["unValue"], "current " + name)
        for name in _PARAMETER_NAMES
    ]
    if len(set(values)) != 1:
        raise WfpError("Only uniform corner-radius replacement has been verified")
    return values[0]


def _replace_radius(
    clip: MutableMapping[str, Any], clip_uid: str, old: Decimal, new: Decimal
) -> bool:
    if clip.get("thisUId") != clip_uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected corner-radius target is not a type-1 video clip")
    current = _uniform_radius(clip)
    if current != old:
        raise WfpError(
            "Selected clip corner radius does not match: expected {0}, found {1}".format(
                old, current
            )
        )
    params = _radius_params(clip)
    for name in _PARAMETER_NAMES:
        params[name][0]["fxParam"]["unValue"] = new
    return True


def preflight_clip_corner_radius(
    source: Pathish,
    *,
    clip_uid: str,
    old_radius: DecimalInput,
    new_radius: DecimalInput,
) -> Dict[str, Any]:
    """Resolve one existing uniform corner-radius quartet without writing."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Corner-radius replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old = _stored_radius(old_radius, "old_radius")
    new = _stored_radius(new_radius, "new_radius")
    if old == new:
        raise WfpError("New corner radius must differ from the current radius")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if _replace_radius(copy.deepcopy(clip), clip_uid, old, new):
                    matches += 1
    if matches < 1:
        raise WfpError("Corner-radius selector did not match the source project")
    return {
        "matching_archive_occurrences": matches,
        "old_radius": str(old),
        "new_radius": str(new),
    }


def _radii_for_uid(path: Path, clip_uid: str) -> List[Decimal]:
    found: List[Decimal] = []
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if clip.get("thisUId") == clip_uid:
                    value = _uniform_radius(clip)
                    if value not in found:
                        found.append(value)
    return found


def audit_clip_corner_radius_copy(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_radius: DecimalInput,
    new_radius: DecimalInput,
) -> Dict[str, Any]:
    """Confirm that only one existing uniform radius quartet changed."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    old = _stored_radius(old_radius, "old_radius")
    new = _stored_radius(new_radius, "new_radius")
    errors: List[str] = []
    try:
        preflight = preflight_clip_corner_radius(
            source_path,
            clip_uid=clip_uid,
            old_radius=old,
            new_radius=new,
        )
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}
    if result.get("added_members") or result.get("removed_members"):
        errors.append("Corner-radius copy changed archive membership")
    changed_members = result.get("changed_members") or []
    if not changed_members or any(
        not member.endswith(TIMELINE_SUFFIX) for member in changed_members
    ):
        errors.append("Corner-radius copy changed unexpected archive members")
    if result.get("parse_errors") or result.get("truncated"):
        errors.append("Corner-radius copy diff was incomplete")
    changes = result.get("json_changes") or []
    expected_count = 4 * preflight["matching_archive_occurrences"]
    valid_changes = 0
    for change in changes:
        try:
            before = _stored_radius(change.get("before"), "diff before")
            after = _stored_radius(change.get("after"), "diff after")
        except WfpError:
            before = after = Decimal("NaN")
        if (
            str(change.get("path")).endswith(".fxParam.unValue")
            and before == old
            and after == new
        ):
            valid_changes += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(change.get("path")))
    if valid_changes != expected_count or len(changes) != expected_count:
        errors.append("Corner-radius copy did not change exactly four values per target")
    try:
        if _radii_for_uid(output_path, clip_uid) != [new]:
            errors.append("Generated copy does not expose one updated uniform radius")
    except WfpError as exc:
        errors.append(str(exc))
    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated corner-radius copy failed format evaluation")
    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "radius_values_changed": valid_changes,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def replace_clip_corner_radius(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_radius: DecimalInput,
    new_radius: DecimalInput,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Change one existing positive uniform radius in a new audited WFP copy."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Corner-radius replacement requires .wfp input and output paths")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    preflight = preflight_clip_corner_radius(
        source_path,
        clip_uid=clip_uid,
        old_radius=old_radius,
        new_radius=new_radius,
    )
    old = Decimal(preflight["old_radius"])
    new = Decimal(preflight["new_radius"])
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
                        member_matches = sum(
                            1
                            for clip in _clips(document)
                            if _replace_radius(clip, clip_uid, old, new)
                        )
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches != preflight["matching_archive_occurrences"]:
            raise WfpError("Corner-radius target count changed while writing")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
        temporary_path.replace(output_path)
        audit = audit_clip_corner_radius_copy(
            source_path,
            output_path,
            clip_uid=clip_uid,
            old_radius=old,
            new_radius=new,
        )
        if not audit.get("valid"):
            output_path.unlink(missing_ok=True)
            raise WfpError(
                "Generated corner-radius copy failed source-aware audit: {0}".format(
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
