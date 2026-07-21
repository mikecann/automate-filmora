"""Guarded replacement of an existing Filmora Stabilization smoothness value."""

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


def _replace(clip: MutableMapping[str, Any], uid: str, old: float, new: float) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected Stabilization target is not a type-1 video clip")
    state = clip.get("stabilization")
    if not isinstance(state, dict):
        raise WfpError("Selected clip does not expose an existing Stabilization object")
    if set(state) != {"cache_mode", "smooth", "status", "version"}:
        raise WfpError("Selected Stabilization object has an unfamiliar shape")
    if state.get("status") != 1 or state.get("version") != 1.0 or state.get("cache_mode") != 0:
        raise WfpError("Selected Stabilization object is not an enabled normalized state")
    current = state.get("smooth")
    if isinstance(current, bool) or not isinstance(current, (int, float, Decimal)) or float(current) != old:
        raise WfpError("Selected Stabilization smoothness does not match the expected value")
    if isinstance(new, bool) or not isinstance(new, (int, float)) or not 0 <= new <= 10:
        raise WfpError("Stabilization smoothness must be between 0 and 10")
    if new == old:
        raise WfpError("New Stabilization smoothness must differ from the current value")
    state["smooth"] = float(new)
    return True


def preflight_clip_stabilization(source: Pathish, *, clip_uid: str, old_smooth: float,
                                 new_smooth: float) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Stabilization replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(copy.deepcopy(clip), clip_uid, old_smooth, new_smooth):
                        matches += 1
    if matches != 1:
        raise WfpError("Stabilization selector must match exactly one archive occurrence")
    return {"matching_archive_occurrences": matches, "old_smooth": old_smooth,
            "new_smooth": new_smooth}


def replace_clip_stabilization(source: Pathish, output: Pathish, *, clip_uid: str,
                               old_smooth: float, new_smooth: float,
                               expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Write a copy changing one existing enabled Stabilization smoothness value."""
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight_clip_stabilization(source_path, clip_uid=clip_uid, old_smooth=old_smooth,
                                 new_smooth=new_smooth)
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
                        if _replace(clip, clip_uid, old_smooth, new_smooth):
                            matches += 1
                    if matches:
                        data = _compact_json(document).encode("utf-8")
                destination.writestr(info, data)
        if matches != 1:
            raise WfpError("Stabilization selector did not match exactly one archive occurrence")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated Stabilization copy failed format evaluation")
    audit = audit_clip_stabilization_copy(source_path, output_path, clip_uid=clip_uid,
                                          old_smooth=old_smooth, new_smooth=new_smooth)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated Stabilization copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_stabilization_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                                  old_smooth: float, new_smooth: float) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors = []
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    if any(not item.endswith(TIMELINE_SUFFIX) for item in result.get("changed_members", [])):
        errors.append("non-timeline member changed")
    for change in result.get("json_changes", []):
        path = str(change.get("path"))
        if path.endswith(".stabilization.smooth"):
            continue
        if path.startswith("$.timelineInfos[0].userData[") or path.startswith("$.media_items."):
            continue
        if path.startswith("$.proj_") or path.startswith("$.project_"):
            continue
        errors.append("unexpected semantic change: " + path)
    if not result.get("changed_members") or not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed validation")
    return {"valid": not errors, "errors": errors,
            "details": {"old_smooth": old_smooth, "new_smooth": new_smooth,
                        "semantic_changes": len(result.get("json_changes") or [])}}
