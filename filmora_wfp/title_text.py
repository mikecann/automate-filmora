"""Narrow same-serialization-length replacement for an existing Filmora title."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple, Union

from .archive import TIMELINE_SUFFIX, WfpError
from .diffing import diff_projects
from .evals import evaluate_project
from .title_cards import _compact_json, _load_decimal_json


Pathish = Union[os.PathLike[str], str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _title_clips(document: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
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
            if not isinstance(track, dict) or not isinstance(track.get("clipList"), list):
                continue
            for clip in track["clipList"]:
                if (
                    isinstance(clip, dict)
                    and clip.get("type") == 4
                    and isinstance(clip.get("scriptBuf"), str)
                ):
                    found.append(clip)
    return found


def _replace_clip_text(
    clip: MutableMapping[str, Any],
    clip_uid: str,
    old_text: str,
    new_text: str,
) -> bool:
    if clip.get("thisUId") != clip_uid:
        return False
    raw_script = clip.get("scriptBuf")
    if not isinstance(raw_script, str):
        raise WfpError("Selected title clip has no scriptBuf")
    try:
        script = json.loads(raw_script)
    except json.JSONDecodeError as exc:
        raise WfpError("Selected title clip has invalid scriptBuf JSON") from exc
    if not isinstance(script, dict):
        raise WfpError("Selected title clip scriptBuf is not an object")
    text_data = script.get("TextData")
    if (
        not isinstance(text_data, list)
        or not text_data
        or not isinstance(text_data[0], dict)
    ):
        raise WfpError("Selected title clip has no TextData mirror")
    if script.get("Text") != old_text or text_data[0].get("CharData") != old_text:
        raise WfpError("Selected title text does not match both serialized mirrors")

    script["Text"] = new_text
    text_data[0]["CharData"] = new_text
    serialized = _compact_json(script)
    if len(serialized.encode("utf-8")) != len(raw_script.encode("utf-8")):
        raise WfpError(
            "Replacement changes serialized script length; auto-sizing is not proven safe"
        )
    clip["scriptBuf"] = serialized
    declared_size = clip.get("scriptBufSize")
    if declared_size is not None and declared_size != len(serialized.encode("utf-8")) + 1:
        raise WfpError("Selected title clip has an inconsistent scriptBufSize")
    return True


def audit_title_text_copy(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_text: str,
    new_text: str,
) -> Dict[str, Any]:
    """Confirm that a copy changed only the two mirrored title-text fields."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    errors: List[str] = []
    try:
        result = diff_projects(source_path, output_path, max_changes=10_000)
    except WfpError as exc:
        return {"valid": False, "errors": [str(exc)], "details": {}}

    if result.get("added_members"):
        errors.append("Title-text copy added archive members")
    if result.get("removed_members"):
        errors.append("Title-text copy removed archive members")
    changed_members = result.get("changed_members") or []
    if not changed_members:
        errors.append("Title-text copy changed no archive members")
    if any(not member.endswith(TIMELINE_SUFFIX) for member in changed_members):
        errors.append("Title-text copy changed a non-timeline archive member")
    if result.get("parse_errors"):
        errors.append("Title-text copy contains JSON parse errors")
    if result.get("truncated"):
        errors.append("Title-text copy diff was unexpectedly truncated")

    text_change_count = 0
    mirror_change_count = 0
    for change in result.get("json_changes") or []:
        path = str(change.get("path"))
        expected_values = change.get("before") == old_text and change.get("after") == new_text
        if path.endswith(".scriptBuf.$embedded_json.Text") and expected_values:
            text_change_count += 1
        elif path.endswith(".scriptBuf.$embedded_json.TextData[0].CharData") and expected_values:
            mirror_change_count += 1
        else:
            errors.append("Unexpected semantic change: {0}".format(path))

    if text_change_count < 1 or text_change_count != mirror_change_count:
        errors.append(
            "Title-text mirrors changed inconsistently: {0}/{1}".format(
                text_change_count, mirror_change_count
            )
        )

    evaluation = evaluate_project(output_path)
    if not evaluation.get("valid"):
        errors.append("Generated title-text copy failed format evaluation")

    matching_titles = [
        title
        for title in _titles_for_uid(output_path, clip_uid)
        if title == new_text
    ]
    if len(matching_titles) != 1:
        errors.append("Generated title-text copy does not expose exactly one updated title")

    return {
        "valid": not errors,
        "errors": errors,
        "details": {
            "changed_members": changed_members,
            "title_occurrences_changed": text_change_count,
            "format_eval_valid": bool(evaluation.get("valid")),
        },
    }


def _titles_for_uid(path: Path, clip_uid: str) -> List[str]:
    found: List[str] = []
    seen: set[Tuple[Any, str]] = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _title_clips(document):
                if clip.get("thisUId") != clip_uid:
                    continue
                script = json.loads(clip["scriptBuf"])
                key = (clip.get("thisUId"), script.get("Text"))
                if key not in seen:
                    seen.add(key)
                    found.append(script.get("Text"))
    return found


def preflight_title_text_replacement(
    source: Pathish,
    *,
    clip_uid: str,
    old_text: str,
    new_text: str,
) -> Dict[str, Any]:
    """Prove a selected replacement preserves the actual serialized script length."""

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".wfp" or not source_path.is_file():
        raise WfpError("Title-text replacement requires an existing .wfp source")
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    if not isinstance(old_text, str) or not old_text:
        raise WfpError("old_text must be non-empty text")
    if not isinstance(new_text, str) or not new_text or new_text == old_text:
        raise WfpError("new_text must be different non-empty text")
    matches = 0
    with zipfile.ZipFile(source_path, "r") as archive:
        for info in archive.infolist():
            if not info.filename.endswith(TIMELINE_SUFFIX):
                continue
            document = _load_decimal_json(archive.read(info))
            for clip in _title_clips(document):
                candidate = copy.deepcopy(clip)
                if _replace_clip_text(candidate, clip_uid, old_text, new_text):
                    matches += 1
    if matches < 1:
        raise WfpError("Title selector did not match the source project")
    return {
        "matching_occurrences": matches,
        "serialized_length_preserved": True,
    }


def replace_title_text(
    source: Pathish,
    output: Pathish,
    *,
    clip_uid: str,
    old_text: str,
    new_text: str,
    expected_source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Replace one existing title without changing its serialized script length."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise WfpError("Input and output project paths must differ")
    if source_path.suffix.lower() != ".wfp" or output_path.suffix.lower() != ".wfp":
        raise WfpError("Title-text replacement requires .wfp input and output paths")
    if not source_path.is_file():
        raise WfpError("Project does not exist: {0}".format(source_path))
    if output_path.exists():
        raise WfpError("Refusing to overwrite existing output: {0}".format(output_path))
    if not isinstance(clip_uid, str) or not clip_uid:
        raise WfpError("clip_uid must be non-empty text")
    if not isinstance(old_text, str) or not old_text:
        raise WfpError("old_text must be non-empty text")
    if not isinstance(new_text, str) or not new_text or new_text == old_text:
        raise WfpError("new_text must be different non-empty text")

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
                        member_matches = 0
                        for clip in _title_clips(document):
                            if _replace_clip_text(clip, clip_uid, old_text, new_text):
                                member_matches += 1
                        if member_matches:
                            data = _compact_json(document).encode("utf-8")
                            changed_members.append(info.filename)
                            matches += member_matches
                    destination.writestr(copy.copy(info), data)
        if matches < 1:
            raise WfpError("Title selector did not match the source project")
        if _sha256(source_path) != starting_hash:
            raise WfpError("Source project changed while the copy was being written")
        if output_path.exists():
            raise WfpError("Output appeared while the copy was being written: {0}".format(output_path))
        os.chmod(temporary_path, source_path.stat().st_mode & 0o7777)
        os.replace(temporary_path, output_path)
    except (OSError, zipfile.BadZipFile) as exc:
        temporary_path.unlink(missing_ok=True)
        raise WfpError("Cannot write title-text project copy: {0}".format(exc)) from exc
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    audit = audit_title_text_copy(
        source_path,
        output_path,
        clip_uid=clip_uid,
        old_text=old_text,
        new_text=new_text,
    )
    if _sha256(source_path) != starting_hash:
        output_path.unlink(missing_ok=True)
        raise WfpError("Source project changed before the generated-copy audit completed")
    if not audit.get("valid"):
        output_path.unlink(missing_ok=True)
        raise WfpError(
            "Generated title-text copy failed its source-aware audit: {0}".format(
                "; ".join(audit.get("errors") or ["unknown error"])
            )
        )
    return {
        "source": str(source_path),
        "output": str(output_path),
        "source_sha256": starting_hash,
        "clip_uid": clip_uid,
        "old_text": old_text,
        "new_text": new_text,
        "changed_members": changed_members,
        "audit": audit,
    }
