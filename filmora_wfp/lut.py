"""Guarded replacement of an existing Filmora 3D LUT strength value."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, MutableMapping, Optional, Union

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


def _param(effect: MutableMapping[str, Any], name: str) -> Optional[MutableMapping[str, Any]]:
    params = effect.get("paramList")
    if not isinstance(params, list):
        return None
    matches = [item for item in params if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        return None
    return matches[0]


def _find_adjust_color(clip: MutableMapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    chains = clip.get("effectChainList")
    if not isinstance(chains, list):
        return None
    matches = []
    for chain in chains:
        if not isinstance(chain, dict) or not isinstance(chain.get("effectList"), list):
            continue
        for effect in chain["effectList"]:
            if isinstance(effect, dict) and effect.get("display") == "AdjustColor":
                matches.append(effect)
    return matches[0] if len(matches) == 1 else None


def _replace(clip: MutableMapping[str, Any], uid: str, old: float, new: float) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected LUT target is not a type-1 video clip")
    effect = _find_adjust_color(clip)
    if effect is None or effect.get("id") != "662E16ED-4524-4D13-AAE9-11DBA0C63E17":
        raise WfpError("Selected clip does not expose one AdjustColor effect")
    enabled = _param(effect, "bEnableLUT")
    path = _param(effect, "lut3dPath")
    alpha = _param(effect, "alpha")
    if not enabled or not path or not alpha:
        raise WfpError("Selected clip does not expose an existing LUT strength")
    if enabled.get("fxParam", {}).get("paramType") != 5 or enabled.get("fxParam", {}).get("unValue") != 1:
        raise WfpError("Selected LUT is not enabled")
    if path.get("fxParam", {}).get("paramType") != 6 or not isinstance(path.get("fxParam", {}).get("unValue"), str):
        raise WfpError("Selected LUT path has an unfamiliar shape")
    fx = alpha.get("fxParam")
    if not isinstance(fx, dict) or fx.get("paramType") != 5:
        raise WfpError("Selected LUT strength has an unfamiliar shape")
    current = fx.get("unValue")
    if isinstance(current, bool) or not isinstance(current, (int, float, Decimal)) or float(current) != old:
        raise WfpError("Selected LUT strength does not match the expected value")
    if isinstance(new, bool) or not isinstance(new, (int, float, Decimal)) or not 0 <= new <= 100:
        raise WfpError("LUT strength must be between 0 and 100")
    if new == old:
        raise WfpError("New LUT strength must differ from the current value")
    fx["unValue"] = float(new)
    return True


def preflight_clip_lut(source: Pathish, *, clip_uid: str, old_strength: float,
                       new_strength: float) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("LUT replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(copy.deepcopy(clip), clip_uid, old_strength, new_strength):
                        matches += 1
    if matches != 1:
        raise WfpError("LUT selector must match exactly one archive occurrence")
    return {"matching_archive_occurrences": matches, "old_strength": old_strength,
            "new_strength": new_strength}


def replace_clip_lut(source: Pathish, output: Pathish, *, clip_uid: str,
                     old_strength: float, new_strength: float,
                     expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Write a copy changing one existing enabled LUT strength value."""
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight_clip_lut(source_path, clip_uid=clip_uid, old_strength=old_strength,
                       new_strength=new_strength)
    if expected_source_sha256 and _sha256(source_path).lower() != expected_source_sha256.lower():
        raise WfpError("Source fingerprint changed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix=output_path.name + ".", suffix=".tmp",
                                             dir=output_path.parent, delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(source_path, "r") as source_zip, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            infos = source_zip.infolist()
            if len({info.filename for info in infos}) != len(infos):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            matches = 0
            for info in infos:
                data = source_zip.read(info)
                if info.filename.endswith(TIMELINE_SUFFIX):
                    document = _load_decimal_json(data)
                    for clip in _clips(document):
                        if _replace(clip, clip_uid, old_strength, new_strength):
                            matches += 1
                    if matches:
                        data = _compact_json(document).encode("utf-8")
                destination.writestr(info, data)
        if matches != 1:
            raise WfpError("LUT selector did not match exactly one archive occurrence")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated LUT copy failed format evaluation")
    audit = audit_clip_lut_copy(source_path, output_path, clip_uid=clip_uid,
                                old_strength=old_strength, new_strength=new_strength)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated LUT copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_lut_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                        old_strength: float, new_strength: float) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors = []
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    if any(not item.endswith(TIMELINE_SUFFIX) for item in result.get("changed_members", [])):
        errors.append("non-timeline member changed")
    allowed = False
    for change in result.get("json_changes", []):
        path = str(change.get("path"))
        if path.startswith("$.timelineInfos[0].trackInfos[") and ".effectChainList[" in path and ".paramList[" in path and path.endswith(".fxParam.unValue"):
            allowed = True
            continue
        if path.startswith("$.timelineInfos[0].userData[") or path.startswith("$.media_items."):
            continue
        if path.startswith("$.proj_") or path.startswith("$.project_"):
            continue
        errors.append("unexpected semantic change: " + path)
    if not allowed or not result.get("changed_members") or not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed validation or did not change LUT strength")
    return {"valid": not errors, "errors": errors,
            "details": {"old_strength": old_strength, "new_strength": new_strength,
                        "semantic_changes": len(result.get("json_changes") or [])}}
