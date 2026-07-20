"""Guarded replacement of existing Filmora Background Blur settings."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
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


def _replace(clip: MutableMapping[str, Any], uid: str, old: int, new: int,
             old_enabled: Optional[bool], enabled: Optional[bool]) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected background target is not a type-1 video clip")
    if "backgroundFillBluredness" not in clip:
        raise WfpError("Selected clip does not expose existing Background Blur strength")
    current = clip["backgroundFillBluredness"]
    if not isinstance(current, int) or isinstance(current, bool) or current != old:
        raise WfpError("Selected Background Blur strength does not match the expected value")
    if new < 0 or new > 100:
        raise WfpError("Background Blur strength must be between 0 and 100")
    clip["backgroundFillBluredness"] = new
    if enabled is not None:
        current_enabled = clip.get("backgroundFillEnable") is True
        if current_enabled != old_enabled:
            raise WfpError("Selected Background Blur enable state does not match the expected value")
        if current_enabled == enabled:
            raise WfpError("New Background Blur enable state must differ from current state")
        if enabled:
            clip["backgroundFillEnable"] = True
        else:
            clip.pop("backgroundFillEnable", None)
    return True


def preflight_clip_background_blur(source: Pathish, *, clip_uid: str, old_strength: int,
                                   new_strength: int, old_enabled: Optional[bool] = None,
                                   new_enabled: Optional[bool] = None) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Background Blur replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    if isinstance(old_strength, bool) or isinstance(new_strength, bool):
        raise WfpError("Background Blur strength must be an integer")
    if old_strength == new_strength and old_enabled is None:
        raise WfpError("New Background Blur state must differ from current state")
    if (old_enabled is None) != (new_enabled is None):
        raise WfpError("Both old_enabled and new_enabled are required for an enable toggle")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(__import__("copy").deepcopy(clip), clip_uid, old_strength, new_strength, old_enabled, new_enabled):
                        matches += 1
    if matches != 1:
        raise WfpError("Background Blur selector must match exactly one archive occurrence")
    return {"matching_archive_occurrences": matches, "old_strength": old_strength, "new_strength": new_strength,
            "old_enabled": old_enabled, "new_enabled": new_enabled}


def replace_clip_background_blur(source: Pathish, output: Pathish, *, clip_uid: str,
                                 old_strength: int, new_strength: int,
                                 old_enabled: Optional[bool] = None, new_enabled: Optional[bool] = None,
                                 expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight_clip_background_blur(source_path, clip_uid=clip_uid, old_strength=old_strength,
                                   new_strength=new_strength, old_enabled=old_enabled, new_enabled=new_enabled)
    if expected_source_sha256 and _sha256(source_path).lower() != expected_source_sha256.lower():
        raise WfpError("Source fingerprint changed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent, delete=False)
    tmp_path = Path(tmp.name); tmp.close()
    try:
        with zipfile.ZipFile(source_path) as source_zip, zipfile.ZipFile(tmp_path, "w") as dest:
            infos = source_zip.infolist()
            if len({i.filename for i in infos}) != len(infos):
                raise WfpError("Refusing to mutate an archive with duplicate member names")
            matches = 0
            for info in infos:
                data = source_zip.read(info)
                if info.filename.endswith(TIMELINE_SUFFIX):
                    document = _load_decimal_json(data)
                    for clip in _clips(document):
                        if _replace(clip, clip_uid, old_strength, new_strength, old_enabled, new_enabled):
                            matches += 1
                    if matches:
                        data = _compact_json(document).encode("utf-8")
                dest.writestr(info, data)
        if matches != 1:
            raise WfpError("Background Blur selector did not match exactly one archive occurrence")
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    result = evaluate_project(output_path)
    if not result.get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated Background Blur copy failed format evaluation")
    return {"output": str(output_path), "format_eval_valid": True, "matching_archive_occurrences": matches}


def audit_clip_background_blur_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                                    old_strength: int, new_strength: int,
                                    old_enabled: Optional[bool] = None, new_enabled: Optional[bool] = None) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors = []
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    if any(not x.endswith(TIMELINE_SUFFIX) for x in result.get("changed_members", [])):
        errors.append("non-timeline member changed")
    allowed = {"backgroundFillBluredness", "backgroundFillEnable"}
    for change in result.get("json_changes", []):
        path = str(change.get("path"))
        if not any(path.endswith("." + key) for key in allowed):
            errors.append("unexpected semantic change: " + path)
    if not result.get("changed_members") or not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed validation")
    return {"valid": not errors, "errors": errors, "details": result}
