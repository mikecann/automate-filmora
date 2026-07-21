"""Guarded replacement of one existing static Filmora HSL scalar."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .scale import _clips
from .title_cards import _compact_json, _load_decimal_json

Pathish = Union[os.PathLike[str], str]
HslInput = Union[Decimal, float, int, str]
_ADJUST_COLOR_ID = "662E16ED-4524-4D13-AAE9-11DBA0C63E17"
_HSL_NAME = re.compile(r"^(Red|Orange|Yellow|Green|Aqua|Blue|Purple|Magenta)_(hueVal|satVal|brightnessVal)$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise WfpError(label + " must be a finite HSL number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WfpError(label + " must be a finite HSL number")
    if not result.is_finite() or result < -100 or result > 100:
        raise WfpError(label + " must be between -100 and 100")
    return result


def _name(value: Any) -> str:
    if not isinstance(value, str) or not _HSL_NAME.fullmatch(value):
        raise WfpError("parameter_name must be a supported static HSL scalar")
    return value


def _params(clip: MutableMapping[str, Any], parameter_name: str) -> List[MutableMapping[str, Any]]:
    found: List[MutableMapping[str, Any]] = []
    for chain in clip.get("effectChainList") or []:
        if not isinstance(chain, dict):
            continue
        for effect in chain.get("effectList") or []:
            if not isinstance(effect, dict) or effect.get("id") != _ADJUST_COLOR_ID:
                continue
            for parameter in effect.get("paramList") or []:
                fx = parameter.get("fxParam") if isinstance(parameter, dict) else None
                if (
                    isinstance(parameter, dict)
                    and parameter.get("name") == parameter_name
                    and isinstance(fx, dict)
                    and fx.get("paramType") == 3
                    and "unValue" in fx
                ):
                    found.append(parameter)
    return found


def _replace(clip: MutableMapping[str, Any], uid: str, parameter_name: str,
             old: Decimal, new: Decimal) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected HSL target is not a type-1 video clip")
    params = _params(clip, parameter_name)
    if len(params) != 1:
        raise WfpError("Selected clip does not expose exactly one existing HSL parameter")
    current = _number(params[0]["fxParam"]["unValue"], "current HSL value")
    if current != old:
        raise WfpError("Selected HSL value does not match the expected value")
    params[0]["fxParam"]["unValue"] = float(new)
    return True


def preflight_clip_hsl(source: Pathish, *, clip_uid: str, parameter_name: str,
                       old_value: HslInput, new_value: HslInput) -> Dict[str, Any]:
    """Resolve one existing static HSL parameter without writing a project."""
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("HSL replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    parameter = _name(parameter_name)
    old, new = _number(old_value, "old_value"), _number(new_value, "new_value")
    if old == new:
        raise WfpError("new_value must differ from old_value")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _clips(document):
                if _replace(copy.deepcopy(clip), clip_uid, parameter, old, new):
                    matches += 1
    if matches != 1:
        raise WfpError("HSL selector must match exactly one existing parameter")
    return {"matching_archive_occurrences": matches, "parameter_name": parameter,
            "old_value": str(old), "new_value": str(new)}


def replace_clip_hsl(source: Pathish, output: Pathish, *, clip_uid: str,
                     parameter_name: str, old_value: HslInput, new_value: HslInput,
                     expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Write a copy changing only one existing static HSL scalar."""
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight = preflight_clip_hsl(source_path, clip_uid=clip_uid, parameter_name=parameter_name,
                                   old_value=old_value, new_value=new_value)
    old, new = Decimal(preflight["old_value"]), Decimal(preflight["new_value"])
    if expected_source_sha256 and _sha256(source_path).lower() != expected_source_sha256.lower():
        raise WfpError("Source fingerprint changed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix=output_path.name + ".", suffix=".tmp",
                                             dir=output_path.parent, delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(source_path, "r") as source_zip, zipfile.ZipFile(temporary_path, "w") as destination:
            infos = source_zip.infolist()
            if len({info.filename for info in infos}) != len(infos):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            matches = 0
            for info in infos:
                data = source_zip.read(info)
                if info.filename.endswith(TIMELINE_SUFFIX):
                    document = _load_decimal_json(data)
                    changed = sum(
                        _replace(clip, clip_uid, parameter_name, old, new)
                        for clip in _clips(document)
                    )
                    if changed:
                        data = _compact_json(document).encode("utf-8")
                        matches += changed
                destination.writestr(info, data)
        if matches != 1:
            raise WfpError("HSL selector did not match exactly one existing parameter")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated HSL copy failed format evaluation")
    audit = audit_clip_hsl_copy(source_path, output_path, clip_uid=clip_uid,
                                parameter_name=parameter_name, old_value=old, new_value=new)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated HSL copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_hsl_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                        parameter_name: str, old_value: HslInput,
                        new_value: HslInput) -> Dict[str, Any]:
    """Verify one HSL scalar change and no other semantic JSON changes."""
    errors: List[str] = []
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
        old, new = _number(old_value, "old_value"), _number(new_value, "new_value")
        parameter = _name(parameter_name)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    changed = result.get("changed_members") or []
    if not changed or any(not item.endswith(TIMELINE_SUFFIX) for item in changed):
        errors.append("unexpected archive membership change")
    scalar_changes = 0
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        if path.endswith(".fxParam.unValue") and change.get("before") == float(old) and change.get("after") == float(new):
            scalar_changes += 1
        else:
            errors.append("unexpected semantic change: " + path)
    if scalar_changes != 1:
        errors.append("expected exactly one HSL scalar change")
    if not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed format evaluation")
    return {"valid": not errors, "errors": errors,
            "details": {"parameter_name": parameter, "scalar_changes": scalar_changes}}
