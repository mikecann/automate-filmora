"""Read-only, privacy-preserving surveys across a corpus of Filmora projects."""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from .archive import WfpError
from .evals import evaluate_project
from .mapping import map_project


Pathish = Union[os.PathLike[str], str]
PROJECT_SUFFIXES = {".wfp", ".wfpbundle"}
VERSION_MAJOR_RE = re.compile(r"^(\d+)")


def discover_projects(inputs: Iterable[Pathish]) -> List[Path]:
    """Return project files below ``inputs`` without following directory symlinks."""

    discovered: Set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() in PROJECT_SUFFIXES:
                discovered.add(path)
            continue
        if not path.is_dir():
            continue
        for root, directories, filenames in os.walk(path, followlinks=False):
            # A package can itself end in .wfpbundle. Filmora bundles observed so
            # far are files, but do not descend into an unknown directory bundle.
            directories[:] = [
                name
                for name in directories
                if not name.lower().endswith(".wfpbundle")
                and not Path(root, name).is_symlink()
            ]
            for filename in filenames:
                candidate = Path(root, filename)
                if candidate.suffix.lower() in PROJECT_SUFFIXES and candidate.is_file():
                    discovered.add(candidate.resolve())
    return sorted(discovered, key=lambda path: str(path).lower())


def _stream_sha256(source: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _project_fingerprint(path: Path) -> str:
    """Hash project decisions, not multi-gigabyte media carried by a bundle."""

    if path.suffix.lower() != ".wfpbundle":
        with path.open("rb") as source:
            return _stream_sha256(source)
    try:
        with zipfile.ZipFile(path, "r") as bundle:
            embedded = [
                info
                for info in bundle.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".wfp")
            ]
            if len(embedded) != 1:
                raise WfpError(
                    "Bundle contains {0} embedded WFP files: {1}".format(len(embedded), path)
                )
            with bundle.open(embedded[0], "r") as source:
                return _stream_sha256(source)
    except zipfile.BadZipFile as exc:
        raise WfpError("Not a readable WFP bundle: {0}".format(path)) from exc


def _major(version: Any) -> Optional[int]:
    if not isinstance(version, str):
        return None
    match = VERSION_MAJOR_RE.match(version)
    return int(match.group(1)) if match else None


def _relevance(version: Any, reference_version: Optional[str]) -> str:
    if not isinstance(version, str) or not version:
        return "unknown"
    if not reference_version:
        return "unclassified"
    if version == reference_version:
        return "exact"
    project_major = _major(version)
    reference_major = _major(reference_version)
    if project_major is None or reference_major is None:
        return "unknown"
    if project_major == reference_major:
        return "same_major"
    return "legacy" if project_major < reference_major else "future"


def _redact_error(error: Exception, path: Path, reveal_paths: bool) -> str:
    message = str(error)
    if not reveal_paths:
        message = message.replace(str(path), "<project>")
    return "{0}: {1}".format(type(error).__name__, message)


def _counter_rows(
    counter: Counter[Any], key: str, count_key: str = "projects"
) -> List[Dict[str, Any]]:
    return [
        {key: value, count_key: count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    ]


class _CorpusFeatures:
    """Aggregate only structural observations, never project text or media paths."""

    def __init__(self) -> None:
        self.document_kinds: Counter[str] = Counter()
        self.document_fields: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.member_kinds: Counter[str] = Counter()
        self.track_types: Counter[str] = Counter()
        self.track_tags: Counter[str] = Counter()
        self.clip_types: Dict[str, Dict[str, Any]] = {}
        self.effects: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.transitions: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.title_fields: Dict[str, Dict[str, Any]] = {}
        self.user_data: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.serialized_payloads: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.serialized_payload_errors: Dict[Tuple[str, str], Dict[str, Any]] = {}

    @staticmethod
    def _base_row() -> Dict[str, Any]:
        return {"projects": 0, "occurrences": 0, "versions": Counter()}

    def add(self, mapped: Dict[str, Any]) -> None:
        version = str((mapped.get("source") or {}).get("filmora_version") or "<unknown>")
        archive = mapped.get("archive") or {}
        for kind, count in (archive.get("member_kinds") or {}).items():
            self.member_kinds[str(kind)] += int(count)

        documents = mapped.get("documents") or {}
        for kind, document in documents.items():
            self.document_kinds[str(kind)] += 1
            for field in document.get("fields") or []:
                path = str(field.get("path"))
                row = self.document_fields.setdefault(
                    (str(kind), path),
                    {**self._base_row(), "types": Counter()},
                )
                row["projects"] += 1
                row["occurrences"] += int(field.get("count") or 0)
                row["versions"][version] += 1
                row["types"].update(field.get("types") or {})

        timeline = mapped.get("timeline") or {}
        for item in timeline.get("track_types") or []:
            self.track_types[str(item.get("track_type"))] += int(item.get("count") or 0)
        for item in timeline.get("track_tags") or []:
            self.track_tags[str(item.get("track_tag"))] += int(item.get("count") or 0)
        for clip in timeline.get("clip_types") or []:
            clip_type = str(clip.get("type"))
            row = self.clip_types.setdefault(
                clip_type,
                {**self._base_row(), "fields": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(clip.get("count") or 0)
            row["versions"][version] += 1
            row["fields"].update(clip.get("field_presence") or {})

        for effect in mapped.get("effects") or []:
            identity = (str(effect.get("id")), str(effect.get("display")))
            row = self.effects.setdefault(
                identity,
                {**self._base_row(), "clip_types": Counter(), "parameters": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(effect.get("count") or 0)
            row["versions"][version] += 1
            row["clip_types"].update(effect.get("clip_types") or {})
            row["parameters"].update(
                "{0}:{1}".format(parameter.get("name"), parameter.get("value_path"))
                for parameter in effect.get("parameters") or []
            )

        for transition in mapped.get("transitions") or []:
            identity = (
                str(transition.get("position")),
                str(transition.get("id")),
                str(transition.get("display")),
            )
            row = self.transitions.setdefault(
                identity,
                {**self._base_row(), "clip_types": Counter(), "parameters": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(transition.get("count") or 0)
            row["versions"][version] += 1
            row["clip_types"].update(transition.get("clip_types") or {})
            row["parameters"].update(
                "{0}:{1}".format(parameter.get("name"), parameter.get("value_path"))
                for parameter in transition.get("parameters") or []
            )

        for field in ((mapped.get("titles") or {}).get("schema") or {}).get("fields") or []:
            path = str(field.get("path"))
            row = self.title_fields.setdefault(
                path,
                {**self._base_row(), "types": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(field.get("count") or 0)
            row["versions"][version] += 1
            row["types"].update(field.get("types") or {})

        for item in mapped.get("user_data") or []:
            identity = (str(item.get("scope")), str(item.get("key")))
            row = self.user_data.setdefault(
                identity,
                {**self._base_row(), "formats": Counter(), "clip_types": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(item.get("count") or 0)
            row["versions"][version] += 1
            row["formats"].update(item.get("formats") or {})
            row["clip_types"].update(item.get("clip_types") or {})

        for item in mapped.get("serialized_payloads") or []:
            identity = (str(item.get("field")), str(item.get("format")))
            row = self.serialized_payloads.setdefault(
                identity,
                {
                    **self._base_row(),
                    "clip_types": Counter(),
                    "schema_fields": Counter(),
                    "tags": Counter(),
                    "attributes": Counter(),
                    "null_terminated_occurrences": 0,
                },
            )
            row["projects"] += 1
            row["occurrences"] += int(item.get("count") or 0)
            row["versions"][version] += 1
            row["clip_types"].update(item.get("clip_types") or {})
            row["schema_fields"].update(
                field.get("path")
                for field in (item.get("schema") or {}).get("fields") or []
            )
            row["tags"].update(item.get("tags") or {})
            row["attributes"].update(item.get("attributes") or {})
            row["null_terminated_occurrences"] += int(
                item.get("null_terminated_count") or 0
            )

        for item in mapped.get("serialized_payload_errors") or []:
            identity = (str(item.get("field")), str(item.get("format")))
            row = self.serialized_payload_errors.setdefault(
                identity,
                {**self._base_row(), "clip_types": Counter()},
            )
            row["projects"] += 1
            row["occurrences"] += int(item.get("count") or 0)
            row["versions"][version] += 1
            row["clip_types"].update(item.get("clip_types") or {})

    @staticmethod
    def _finish_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: dict(sorted(value.items())) if isinstance(value, Counter) else value
            for key, value in row.items()
        }

    def result(self) -> Dict[str, Any]:
        def ranked(rows: Iterator[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return sorted(
                rows,
                key=lambda row: (-int(row.get("projects") or 0), str(row)),
            )

        return {
            "archive_member_kinds": dict(sorted(self.member_kinds.items())),
            "document_kinds": _counter_rows(self.document_kinds, "kind"),
            "document_fields": ranked(
                {
                    "kind": kind,
                    "path": path,
                    **self._finish_row(row),
                }
                for (kind, path), row in self.document_fields.items()
            ),
            "track_types": _counter_rows(self.track_types, "track_type", "occurrences"),
            "track_tags": _counter_rows(self.track_tags, "track_tag", "occurrences"),
            "clip_types": ranked(
                {"type": clip_type, **self._finish_row(row)}
                for clip_type, row in self.clip_types.items()
            ),
            "effects": ranked(
                {"id": identity[0], "display": identity[1], **self._finish_row(row)}
                for identity, row in self.effects.items()
            ),
            "transitions": ranked(
                {
                    "position": identity[0],
                    "id": identity[1],
                    "display": identity[2],
                    **self._finish_row(row),
                }
                for identity, row in self.transitions.items()
            ),
            "title_fields": ranked(
                {"path": path, **self._finish_row(row)}
                for path, row in self.title_fields.items()
            ),
            "user_data": ranked(
                {"scope": identity[0], "key": identity[1], **self._finish_row(row)}
                for identity, row in self.user_data.items()
            ),
            "serialized_payloads": ranked(
                {
                    "field": identity[0],
                    "format": identity[1],
                    **self._finish_row(row),
                }
                for identity, row in self.serialized_payloads.items()
            ),
            "serialized_payload_errors": ranked(
                {
                    "field": identity[0],
                    "format": identity[1],
                    **self._finish_row(row),
                }
                for identity, row in self.serialized_payload_errors.items()
            ),
        }


def survey_projects(
    inputs: Iterable[Pathish],
    reference_version: Optional[str] = None,
    reveal_paths: bool = False,
) -> Dict[str, Any]:
    """Map a de-duplicated project corpus and return redacted aggregate evidence."""

    paths = discover_projects(inputs)
    by_digest: DefaultDict[str, List[Path]] = defaultdict(list)
    hash_failures: List[Dict[str, Any]] = []
    for path in paths:
        try:
            by_digest[_project_fingerprint(path)].append(path)
        except (OSError, WfpError) as exc:
            hash_failures.append(
                {
                    "sample_id": "unreadable",
                    "error": _redact_error(exc, path, reveal_paths),
                    **({"path": str(path)} if reveal_paths else {}),
                }
            )

    features = _CorpusFeatures()
    samples: List[Dict[str, Any]] = []
    failures = list(hash_failures)
    versions: Dict[str, Dict[str, Any]] = {}
    eval_probe_failures: Counter[str] = Counter()
    for digest, copies in sorted(by_digest.items()):
        path = copies[0]
        sample_id = digest[:12]
        try:
            mapped = map_project(path, reveal_paths=False)
            evaluation = evaluate_project(path, mapped=mapped)
        except (OSError, WfpError, ValueError) as exc:
            failures.append(
                {
                    "sample_id": sample_id,
                    "copies": len(copies),
                    "error": _redact_error(exc, path, reveal_paths),
                    **({"paths": [str(item) for item in copies]} if reveal_paths else {}),
                }
            )
            continue

        features.add(mapped)
        source = mapped.get("source") or {}
        modified = str(source.get("filmora_version") or "<unknown>")
        created = str(source.get("created_with") or "<unknown>")
        os_name = str(source.get("os") or "<unknown>")
        relevance = _relevance(source.get("filmora_version"), reference_version)
        failed_probes = [
            str(probe.get("name"))
            for probe in evaluation.get("probes") or []
            if probe.get("required") and not probe.get("passed")
        ]
        eval_probe_failures.update(failed_probes)
        samples.append(
            {
                "sample_id": sample_id,
                "project_sha256": digest,
                "copies": len(copies),
                "container_size_bytes": path.stat().st_size,
                "copy_size_bytes": sum(item.stat().st_size for item in copies),
                "filmora_version": source.get("filmora_version"),
                "created_with": source.get("created_with"),
                "os": source.get("os"),
                "relevance": relevance,
                "eval_valid": bool(evaluation.get("valid")),
                "failed_probes": failed_probes,
                **({"paths": [str(item) for item in copies]} if reveal_paths else {}),
            }
        )
        version = versions.setdefault(
            modified,
            {
                "modified_version": modified,
                "projects": 0,
                "copies": 0,
                "created_with": Counter(),
                "operating_systems": Counter(),
                "relevance": relevance,
            },
        )
        version["projects"] += 1
        version["copies"] += len(copies)
        version["created_with"][created] += 1
        version["operating_systems"][os_name] += 1

    version_rows = [
        {
            **row,
            "created_with": dict(sorted(row["created_with"].items())),
            "operating_systems": dict(sorted(row["operating_systems"].items())),
        }
        for row in versions.values()
    ]
    version_rows.sort(key=lambda row: (-int(row["projects"]), row["modified_version"]))
    samples.sort(key=lambda row: (str(row.get("filmora_version")), row["sample_id"]))
    hashed_files = sum(len(copies) for copies in by_digest.values())
    return {
        "corpus_survey_version": 2,
        "reference_version": reference_version,
        "inventory": {
            "discovered_files": len(paths),
            "wfp_files": sum(path.suffix.lower() == ".wfp" for path in paths),
            "bundle_files": sum(path.suffix.lower() == ".wfpbundle" for path in paths),
            "hashed_files": hashed_files,
            "unique_file_hashes": len(by_digest),
            "duplicate_files": hashed_files - len(by_digest),
            "mapped_projects": len(samples),
            "failed_projects": len(failures),
            "total_size_bytes": sum(path.stat().st_size for path in paths if path.is_file()),
        },
        "versions": version_rows,
        "eval_probe_failures": _counter_rows(eval_probe_failures, "probe"),
        "samples": samples,
        "failures": failures,
        "features": features.result(),
    }
