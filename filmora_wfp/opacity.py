"""Guarded replacement of an existing static overlay opacity value."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
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


def _opacity(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise WfpError(label + " must be a finite opacity number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WfpError(label + " must be a finite opacity number")
    if not result.is_finite() or result < 0 or result > 100:
        raise WfpError(label + " must be between 0 and 100")
    return result


def _pip(clip: MutableMapping[str, Any]) -> Dict[str, Any]:
    raw = clip.get("pipBuf")
    if not isinstance(raw, str):
        raise WfpError("Selected clip does not expose a serialized pipBuf")
    try:
        value = json.loads(raw.rstrip("\x00"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WfpError("Selected clip pipBuf is not parseable JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("Opacity"), (int, float)):
        raise WfpError("Selected clip does not expose a static pipBuf Opacity")
    if isinstance(value["Opacity"], bool) or "OpacityKeyFrame" in value:
        raise WfpError("Only static pipBuf Opacity is supported")
    return value


def _replace(clip: MutableMapping[str, Any], uid: str, old: Decimal, new: Decimal) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 1:
        raise WfpError("Selected opacity target is not a type-1 video clip")
    pip = _pip(clip)
    current = _opacity(pip["Opacity"], "current opacity")
    if current != old:
        raise WfpError("Selected clip opacity does not match the expected value")
    pip["Opacity"] = float(new)
    encoded = json.dumps(pip, separators=(",", ":"), ensure_ascii=False)
    clip["pipBuf"] = encoded
    clip["pipBufSize"] = len(encoded.encode("utf-8")) + 1
    return True


def preflight_clip_opacity(source: Pathish, *, clip_uid: str, old_opacity: Any,
                           new_opacity: Any) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Opacity replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old, new = _opacity(old_opacity, "old_opacity"), _opacity(new_opacity, "new_opacity")
    if old == new:
        raise WfpError("New opacity must differ from the current opacity")
    matches = 0
    with zipfile.ZipFile(source_path) as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(copy.deepcopy(clip), clip_uid, old, new):
                        matches += 1
    if matches != 1:
        raise WfpError("Opacity selector must match exactly one existing overlay")
    return {"matching_archive_occurrences": matches, "old_opacity": str(old), "new_opacity": str(new)}


def replace_clip_opacity(source: Pathish, output: Pathish, *, clip_uid: str,
                         old_opacity: Any, new_opacity: Any,
                         expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight = preflight_clip_opacity(source_path, clip_uid=clip_uid,
                                       old_opacity=old_opacity, new_opacity=new_opacity)
    old, new = Decimal(preflight["old_opacity"]), Decimal(preflight["new_opacity"])
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
            raise WfpError("Opacity selector did not match exactly one existing overlay")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated opacity copy failed format evaluation")
    audit = audit_clip_opacity_copy(source_path, output_path, clip_uid=clip_uid,
                                    old_opacity=old, new_opacity=new)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated opacity copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_opacity_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                            old_opacity: Any, new_opacity: Any) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors = []
    if result.get("added_members") or result.get("removed_members"):
        errors.append("archive membership changed")
    changed = result.get("changed_members") or []
    allowed_members = (TIMELINE_SUFFIX, "ProjectFolder/project_info.json", "ProjectFolder/Medias/medias_info.json")
    if not changed or any(not (item.endswith(allowed_members)) for item in changed):
        errors.append("unexpected archive membership change")
    old, new = _opacity(old_opacity, "old_opacity"), _opacity(new_opacity, "new_opacity")
    seen = set()
    allowed_suffixes = (".pipBuf.$embedded_json.Opacity", ".pipBufSize")
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        if path.endswith(".pipBuf.$embedded_json.Opacity"):
            if _opacity(change.get("before"), "diff before") != old or _opacity(change.get("after"), "diff after") != new:
                errors.append("opacity diff does not match requested values")
            seen.add("opacity")
        elif path.endswith(".pipBufSize"):
            seen.add("size")
        elif path.startswith("$.timelineInfos[0].userData[") or path.startswith("$.media_items.") or path.startswith("$.proj_") or path.startswith("$.project_"):
            continue
        elif not any(path.endswith(suffix) for suffix in allowed_suffixes):
            errors.append("unexpected semantic change: " + path)
    if "opacity" not in seen:
        errors.append("expected opacity change was not observed")
    if not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed format evaluation")
    return {"valid": not errors, "errors": errors, "details": result}
