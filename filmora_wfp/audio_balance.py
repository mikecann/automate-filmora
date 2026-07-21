"""Guarded replacement of an existing Filmora audio balance parameter."""

from __future__ import annotations

import copy
import hashlib
import os
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ui_balance(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise WfpError(label + " must be a finite balance number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WfpError(label + " must be a finite balance number")
    if not result.is_finite() or result < -100 or result > 100:
        raise WfpError(label + " must be between -100 and 100")
    return result


def _stored_balance(value: Decimal) -> Decimal:
    return (value + Decimal("100")) / Decimal("200")


def _balance_params(clip: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    found: List[MutableMapping[str, Any]] = []
    for chain in clip.get("effectChainList") or []:
        for effect in (chain.get("effectList") or []) if isinstance(chain, dict) else []:
            if not isinstance(effect, dict) or effect.get("id") != "audio/effect/volume":
                continue
            for parameter in effect.get("paramList") or []:
                fx = parameter.get("fxParam") if isinstance(parameter, dict) else None
                if parameter.get("name") == "Balance" and isinstance(fx, dict) and fx.get("paramType") == 2 and "unValue" in fx:
                    found.append(parameter)
    return found


def _replace(clip: MutableMapping[str, Any], uid: str, old: Decimal, new: Decimal) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 2:
        raise WfpError("Selected balance target is not a type-2 audio clip")
    params = _balance_params(clip)
    if len(params) != 1:
        raise WfpError("Selected clip does not expose exactly one existing Balance parameter")
    current = Decimal(str(params[0]["fxParam"]["unValue"]))
    if current != _stored_balance(old):
        raise WfpError("Selected clip balance does not match the expected value")
    params[0]["fxParam"]["unValue"] = float(_stored_balance(new))
    return True


def preflight_clip_audio_balance(source: Pathish, *, clip_uid: str, old_balance: Any,
                                 new_balance: Any) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Audio balance replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old, new = _ui_balance(old_balance, "old_balance"), _ui_balance(new_balance, "new_balance")
    if old == new:
        raise WfpError("New balance must differ from the current balance")
    matches = 0
    with zipfile.ZipFile(source_path) as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(copy.deepcopy(clip), clip_uid, old, new):
                        matches += 1
    if matches != 1:
        raise WfpError("Audio balance selector must match exactly one existing clip")
    return {"matching_archive_occurrences": matches, "old_balance": str(old), "new_balance": str(new),
            "old_stored_balance": str(_stored_balance(old)), "new_stored_balance": str(_stored_balance(new))}


def replace_clip_audio_balance(source: Pathish, output: Pathish, *, clip_uid: str,
                               old_balance: Any, new_balance: Any,
                               expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight = preflight_clip_audio_balance(source_path, clip_uid=clip_uid,
                                             old_balance=old_balance, new_balance=new_balance)
    old, new = Decimal(preflight["old_balance"]), Decimal(preflight["new_balance"])
    if expected_source_sha256 and _sha256(source_path).lower() != expected_source_sha256.lower():
        raise WfpError("Source fingerprint changed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent, delete=False)
    temporary_path = Path(temporary.name); temporary.close()
    try:
        with zipfile.ZipFile(source_path) as source_zip, zipfile.ZipFile(temporary_path, "w") as destination:
            infos = source_zip.infolist()
            if len({info.filename for info in infos}) != len(infos):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            matches = 0
            for info in infos:
                data = source_zip.read(info)
                if info.filename.endswith(TIMELINE_SUFFIX):
                    document = _load_decimal_json(data)
                    changed = 0
                    for clip in _clips(document):
                        if _replace(clip, clip_uid, old, new):
                            changed += 1
                    if changed:
                        data = _compact_json(document).encode("utf-8")
                        matches += changed
                destination.writestr(info, data)
        if matches != 1:
            raise WfpError("Audio balance selector did not match exactly one existing clip")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated audio balance copy failed format evaluation")
    audit = audit_clip_audio_balance_copy(source_path, output_path, clip_uid=clip_uid,
                                          old_balance=old, new_balance=new)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated audio balance copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_audio_balance_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                                  old_balance: Any, new_balance: Any) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors = []
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    changed = result.get("changed_members") or []
    if not changed or any(not item.endswith(TIMELINE_SUFFIX) for item in changed):
        errors.append("unexpected archive membership change")
    old, new = _ui_balance(old_balance, "old_balance"), _ui_balance(new_balance, "new_balance")
    expected = {_stored_balance(old), _stored_balance(new)}
    seen = set()
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        if path.endswith(".name") and change.get("after") == "Balance":
            continue
        if path.endswith(".fxParam.unValue"):
            before, after = Decimal(str(change.get("before"))), Decimal(str(change.get("after")))
            if {before, after} != expected:
                errors.append("balance diff does not match requested values")
            seen.update((before, after))
        else:
            errors.append("unexpected semantic change: " + path)
    if seen != expected:
        errors.append("expected Balance scalar change was not observed")
    if not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed format evaluation")
    return {"valid": not errors, "errors": errors, "details": result}
