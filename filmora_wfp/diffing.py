"""Structural diffs for controlled before/after Filmora saves."""

from __future__ import annotations

import json
import os
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Union

from .archive import WfpArchive, WfpError


JSON_SUFFIXES = (".json", ".wesproj")
EMBEDDED_JSON_KEYS = {"scriptBuf", "pipBuf", "speedParam"}
Pathish = Union[os.PathLike[str], str]


def _redact(value: Any, reveal_paths: bool) -> Any:
    if reveal_paths or not isinstance(value, str):
        return value
    normalized = value.replace("\\", "/")
    if value.startswith("file:") or normalized.startswith("/") or ":/" in normalized:
        return PurePosixPath(normalized.rstrip("/")).name
    return value


def _expand_embedded(value: Any, key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        return {child_key: _expand_embedded(child, child_key) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_expand_embedded(child) for child in value]
    if isinstance(value, str) and (
        key in EMBEDDED_JSON_KEYS or value.lstrip().startswith(("{", "["))
    ):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        # Filmora also nests JSON below generic keys such as fxParam.unValue
        # and ICurveColor::* entries. Expanding any valid JSON object/array
        # keeps controlled diffs useful without assigning semantics to it.
        if key not in EMBEDDED_JSON_KEYS and not isinstance(decoded, (dict, list)):
            return value
        return {"$embedded_json": _expand_embedded(decoded)}
    return value


def _json_changes(
    before: Any,
    after: Any,
    path: str,
    changes: List[Dict[str, Any]],
    max_changes: int,
    reveal_paths: bool,
) -> None:
    if len(changes) >= max_changes:
        return
    if type(before) is not type(after):
        changes.append(
            {"path": path, "kind": "type", "before": type(before).__name__, "after": type(after).__name__}
        )
        return
    if isinstance(before, dict):
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys):
            if len(changes) >= max_changes:
                return
            changes.append(
                {"path": "{0}.{1}".format(path, key), "kind": "removed", "before": _redact(before[key], reveal_paths)}
            )
        for key in sorted(after_keys - before_keys):
            if len(changes) >= max_changes:
                return
            changes.append(
                {"path": "{0}.{1}".format(path, key), "kind": "added", "after": _redact(after[key], reveal_paths)}
            )
        for key in sorted(before_keys & after_keys):
            _json_changes(
                before[key],
                after[key],
                "{0}.{1}".format(path, key),
                changes,
                max_changes,
                reveal_paths,
            )
        return
    if isinstance(before, list):
        common = min(len(before), len(after))
        for index in range(common):
            _json_changes(
                before[index],
                after[index],
                "{0}[{1}]".format(path, index),
                changes,
                max_changes,
                reveal_paths,
            )
            if len(changes) >= max_changes:
                return
        for index in range(common, len(before)):
            if len(changes) >= max_changes:
                return
            changes.append(
                {"path": "{0}[{1}]".format(path, index), "kind": "removed", "before": _redact(before[index], reveal_paths)}
            )
        for index in range(common, len(after)):
            if len(changes) >= max_changes:
                return
            changes.append(
                {"path": "{0}[{1}]".format(path, index), "kind": "added", "after": _redact(after[index], reveal_paths)}
            )
        return
    if before != after:
        changes.append(
            {
                "path": path,
                "kind": "changed",
                "before": _redact(before, reveal_paths),
                "after": _redact(after, reveal_paths),
            }
        )


def diff_projects(
    before_path: Pathish,
    after_path: Pathish,
    member_filter: Optional[str] = None,
    max_changes: int = 200,
    reveal_paths: bool = False,
) -> Dict[str, Any]:
    if max_changes < 1:
        raise WfpError("max_changes must be positive")
    with WfpArchive(before_path) as before_archive, WfpArchive(after_path) as after_archive:
        before_infos = {info.filename: info for info in before_archive.members()}
        after_infos = {info.filename: info for info in after_archive.members()}
        before_names = set(before_infos)
        after_names = set(after_infos)
        added = sorted(after_names - before_names)
        removed = sorted(before_names - after_names)
        changed = sorted(
            name
            for name in before_names & after_names
            if before_infos[name].CRC != after_infos[name].CRC
            or before_infos[name].file_size != after_infos[name].file_size
        )
        if member_filter:
            added = [name for name in added if member_filter in name]
            removed = [name for name in removed if member_filter in name]
            changed = [name for name in changed if member_filter in name]

        json_changes: List[Dict[str, Any]] = []
        parse_errors: List[str] = []
        for member in changed:
            if not member.endswith(JSON_SUFFIXES):
                continue
            if len(json_changes) >= max_changes:
                break
            try:
                before = _expand_embedded(before_archive.read_json(member))
                after = _expand_embedded(after_archive.read_json(member))
            except WfpError as exc:
                parse_errors.append(str(exc))
                continue
            member_changes: List[Dict[str, Any]] = []
            _json_changes(
                before,
                after,
                "$",
                member_changes,
                max_changes - len(json_changes),
                reveal_paths,
            )
            for change in member_changes:
                change["member"] = member
            json_changes.extend(member_changes)

        return {
            "before": _redact(str(before_archive.path), reveal_paths),
            "after": _redact(str(after_archive.path), reveal_paths),
            "added_members": added,
            "removed_members": removed,
            "changed_members": changed,
            "json_changes": json_changes,
            "parse_errors": parse_errors,
            "truncated": len(json_changes) >= max_changes,
        }
