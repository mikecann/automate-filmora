"""Guarded replacement of the two observed Filmora equalizer presets."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .scale import _clips
from .title_cards import _compact_json, _load_decimal_json

Pathish = Union[os.PathLike[str], str]
_EQUALIZER_ID = "audio/effect/equalizer"
_PRESETS: Dict[str, Tuple[Tuple[str, float], ...]] = {
    "Rock": (("31Hz", -1.08), ("63Hz", 2.88), ("125Hz", 2.16), ("250Hz", 2.88),
             ("500Hz", -1.08), ("1kHz", -1.08), ("4kHz", 2.16), ("8kHz", 2.16), ("16kHz", 3.96)),
    "Pop": (("31Hz", -1.08), ("63Hz", -2.16), ("125Hz", 3.96), ("250Hz", 5.76),
            ("500Hz", 5.76), ("1kHz", 3.96), ("2kHz", -1.08), ("4kHz", -2.16),
            ("8kHz", -2.16), ("16kHz", -2.16)),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preset(value: Any, label: str) -> str:
    if not isinstance(value, str) or value not in _PRESETS:
        raise WfpError(label + " must be one of the observed Rock or Pop presets")
    return value


def _effects(clip: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    found: List[MutableMapping[str, Any]] = []
    for chain in clip.get("effectChainList") or []:
        if not isinstance(chain, dict):
            continue
        for effect in chain.get("effectList") or []:
            if isinstance(effect, dict) and effect.get("id") == _EQUALIZER_ID:
                found.append(effect)
    return found


def _values(effect: MutableMapping[str, Any]) -> Tuple[Tuple[str, float], ...]:
    result: List[Tuple[str, float]] = []
    for parameter in effect.get("paramList") or []:
        fx = parameter.get("fxParam") if isinstance(parameter, dict) else None
        if not isinstance(parameter, dict) or not isinstance(fx, dict) or fx.get("paramType") != 2:
            raise WfpError("Selected equalizer contains an unsupported parameter")
        result.append((str(parameter.get("name")), float(fx.get("unValue"))))
    return tuple(result)


def _replace(clip: MutableMapping[str, Any], uid: str, old: str, new: str) -> bool:
    if clip.get("thisUId") != uid:
        return False
    if clip.get("type") != 2:
        raise WfpError("Selected equalizer target is not a type-2 audio clip")
    effects = _effects(clip)
    if len(effects) != 1:
        raise WfpError("Selected clip does not expose exactly one existing equalizer")
    if _values(effects[0]) != _PRESETS[old]:
        raise WfpError("Selected equalizer does not match the expected preset")
    effects[0]["paramList"] = [
        {"name": name, "fxParam": {"paramType": 2, "unValue": value}}
        for name, value in _PRESETS[new]
    ]
    return True


def preflight_clip_equalizer(source: Pathish, *, clip_uid: str, old_preset: Any,
                             new_preset: Any) -> Dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Equalizer replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    old, new = _preset(old_preset, "old_preset"), _preset(new_preset, "new_preset")
    if old == new:
        raise WfpError("new_preset must differ from old_preset")
    matches = 0
    with zipfile.ZipFile(source_path) as archive:
        for info in archive.infolist():
            if info.filename.endswith(TIMELINE_SUFFIX):
                document = _load_decimal_json(archive.read(info))
                for clip in _clips(document):
                    if _replace(copy.deepcopy(clip), clip_uid, old, new):
                        matches += 1
    if matches != 1:
        raise WfpError("Equalizer selector must match exactly one existing preset")
    return {"matching_archive_occurrences": matches, "old_preset": old, "new_preset": new}


def replace_clip_equalizer(source: Pathish, output: Pathish, *, clip_uid: str,
                           old_preset: Any, new_preset: Any,
                           expected_source_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Write a copy changing an existing Rock or Pop equalizer preset."""
    source_path, output_path = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source_path == output_path or output_path.exists():
        raise WfpError("Refusing to overwrite the source or an existing output")
    preflight = preflight_clip_equalizer(source_path, clip_uid=clip_uid,
                                         old_preset=old_preset, new_preset=new_preset)
    old, new = preflight["old_preset"], preflight["new_preset"]
    if expected_source_sha256 and _sha256(source_path).lower() != expected_source_sha256.lower():
        raise WfpError("Source fingerprint changed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix=output_path.name + ".", suffix=".tmp",
                                             dir=output_path.parent, delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
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
                    changed = sum(_replace(clip, clip_uid, old, new) for clip in _clips(document))
                    if changed:
                        data = _compact_json(document).encode("utf-8")
                        matches += changed
                destination.writestr(info, data)
        if matches != 1:
            raise WfpError("Equalizer selector did not match exactly one existing preset")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if not evaluate_project(output_path).get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated equalizer copy failed format evaluation")
    audit = audit_clip_equalizer_copy(source_path, output_path, clip_uid=clip_uid,
                                      old_preset=old, new_preset=new)
    if not audit["valid"]:
        output_path.unlink(missing_ok=True)
        raise WfpError("Generated equalizer copy failed semantic audit")
    return {"output": str(output_path), "format_eval_valid": True, "audit": audit,
            "matching_archive_occurrences": matches}


def audit_clip_equalizer_copy(source: Pathish, output: Pathish, *, clip_uid: str,
                              old_preset: Any, new_preset: Any) -> Dict[str, Any]:
    try:
        result = diff_projects(Path(source), Path(output), max_changes=10000)
        old, new = _preset(old_preset, "old_preset"), _preset(new_preset, "new_preset")
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)]}
    errors: List[str] = []
    changed = result.get("changed_members") or []
    if result.get("added_members") or result.get("removed_members") or not changed:
        errors.append("archive membership changed unexpectedly")
    if any(not item.endswith(TIMELINE_SUFFIX) for item in changed):
        errors.append("equalizer copy changed a non-timeline member")
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        if ".effectList[" in path and ".paramList" in path:
            continue
        if path.startswith("$.timelineInfos[0].userData[") or path.startswith("$.media_items.") or path.startswith("$.proj_") or path.startswith("$.project_"):
            continue
        errors.append("unexpected semantic change: " + path)
    if not evaluate_project(Path(output)).get("valid"):
        errors.append("output failed format evaluation")
    return {"valid": not errors, "errors": errors,
            "details": {"old_preset": old, "new_preset": new,
                        "semantic_changes": len(result.get("json_changes") or [])}}
