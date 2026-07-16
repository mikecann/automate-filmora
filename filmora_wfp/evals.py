"""Repeatable compatibility probes for observed Filmora project files."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Union

from .analysis import validate_project
from .archive import WfpArchive
from .mapping import map_project


Pathish = Union[os.PathLike[str], str]


def _probe(name: str, passed: bool, detail: str, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "passed": passed, "required": required, "detail": detail}


def evaluate_project(path: Pathish) -> Dict[str, Any]:
    """Run content-independent format probes against a real WFP project."""

    validation = validate_project(path)
    mapped = map_project(path)
    probes: List[Dict[str, Any]] = []

    with WfpArchive(path) as archive:
        bad_crc = archive.zip_file.testzip()
        probes.append(
            _probe(
                "archive_crc",
                bad_crc is None,
                "all archive members passed CRC" if bad_crc is None else "bad CRC: {0}".format(bad_crc),
            )
        )

    probes.append(
        _probe(
            "structural_validation",
            bool(validation.get("valid")),
            "; ".join(validation.get("errors") or []) or "main timeline and archive routing resolve",
        )
    )
    documents = mapped.get("documents") or {}
    for kind in ("project_info", "medias_info", "timeline"):
        count = (documents.get(kind) or {}).get("document_count", 0)
        probes.append(
            _probe(
                "required_document_{0}".format(kind),
                count >= 1,
                "observed {0} document(s)".format(count),
            )
        )

    parse_errors = [
        error
        for document in documents.values()
        for error in document.get("parse_errors") or []
    ]
    probes.append(
        _probe(
            "all_json_documents_parse",
            not parse_errors,
            "; ".join(parse_errors) if parse_errors else "all JSON and WESPROJ documents parsed",
        )
    )

    archive = mapped.get("archive") or {}
    duplicate_members = archive.get("duplicate_member_names") or []
    probes.append(
        _probe(
            "unique_archive_member_names",
            not duplicate_members,
            ", ".join(duplicate_members) if duplicate_members else "no duplicate ZIP member names",
        )
    )

    cache = (mapped.get("timeline") or {}).get("standalone_cache") or {}
    conflicts = cache.get("conflicting_copy_count", 0)
    probes.append(
        _probe(
            "timeline_cache_consistency",
            conflicts == 0,
            "{0} standalone timeline copy conflict(s)".format(conflicts),
        )
    )
    duplicate_timeline_ids = cache.get("duplicate_ids_in_main") or {}
    probes.append(
        _probe(
            "unique_main_timeline_ids",
            not duplicate_timeline_ids,
            "duplicates: {0}".format(duplicate_timeline_ids)
            if duplicate_timeline_ids
            else "all routed-main timeline IDs are unique",
        )
    )

    identifiers = mapped.get("identifiers") or {}
    timeline_ids = identifiers.get("timeline_ids") or {}
    unresolved_timelines = timeline_ids.get("unresolved_references") or []
    probes.append(
        _probe(
            "timeline_references_resolve",
            not unresolved_timelines,
            "unresolved: {0}".format(unresolved_timelines)
            if unresolved_timelines
            else "all timeline references resolve",
        )
    )

    source_uuids = identifiers.get("source_uuids") or {}
    unresolved_sources = source_uuids.get("unresolved_reference_count", 0)
    probes.append(
        _probe(
            "source_uuid_references_resolve",
            unresolved_sources == 0,
            "{0} unresolved sourceUuid value(s)".format(unresolved_sources),
        )
    )
    this_uid = (identifiers.get("identifier_fields") or {}).get("thisUId") or {}
    this_uid_occurrences = this_uid.get("occurrences", 0)
    this_uid_unique = this_uid.get("unique", 0)
    probes.append(
        _probe(
            "instance_identifiers_unique",
            this_uid_occurrences == this_uid_unique,
            "{0}/{1} thisUId values are unique".format(this_uid_unique, this_uid_occurrences),
        )
    )

    transition_count = 0
    transitions_in_valid_groups = 0
    invalid_transition_groups: List[str] = []
    for transition in mapped.get("transitions") or []:
        count = transition.get("count", 0)
        if not isinstance(count, int):
            count = 0
        transition_count += count
        duration = transition.get("duration_ticks") or {}
        duration_count = duration.get("count", 0)
        numeric_range = duration.get("numeric_range")
        minimum = numeric_range[0] if isinstance(numeric_range, list) and numeric_range else None
        complete_positive_range = (
            duration_count == count
            and isinstance(minimum, (int, float))
            and not isinstance(minimum, bool)
            and minimum > 0
        )
        if complete_positive_range:
            transitions_in_valid_groups += count
        else:
            invalid_transition_groups.append(
                "{0}:{1}".format(transition.get("position"), transition.get("id"))
            )
    probes.append(
        _probe(
            "transition_ranges_valid",
            not invalid_transition_groups,
            "{0}/{1} transitions are in groups with complete positive ranges{2}".format(
                transitions_in_valid_groups,
                transition_count,
                "; invalid groups: {0}".format(", ".join(invalid_transition_groups))
                if invalid_transition_groups
                else "",
            ),
        )
    )

    titles = mapped.get("titles") or {}
    invalid_titles = titles.get("invalid_json_count", 0)
    probes.append(
        _probe(
            "title_script_buffers_parse",
            invalid_titles == 0,
            "{0} valid, {1} invalid".format(titles.get("valid_json_count", 0), invalid_titles),
        )
    )
    declared_sizes = titles.get("declared_scriptBufSize_count", 0)
    matching_sizes = titles.get("declared_size_matches_utf8_plus_one", 0)
    probes.append(
        _probe(
            "title_script_sizes_match",
            declared_sizes == matching_sizes,
            "{0}/{1} declared sizes equal UTF-8 bytes plus one".format(matching_sizes, declared_sizes),
        )
    )
    text_mirrors = titles.get("text_mirror_count", 0)
    matching_text_mirrors = titles.get("text_mirror_matches", 0)
    probes.append(
        _probe(
            "title_text_mirrors_match",
            text_mirrors == matching_text_mirrors,
            "{0}/{1} script Text values equal TextData[0].CharData".format(
                matching_text_mirrors, text_mirrors
            ),
        )
    )

    media_folders = identifiers.get("media_folders") or {}
    probes.append(
        _probe(
            "main_media_folder_resolves",
            bool(media_folders.get("timeline_media_id_resolves")),
            "timeline_mediaId resolves to an archive media folder",
        )
    )

    duplicate_json_keys = [
        {"document_kind": kind, **duplicate}
        for kind, document in documents.items()
        for duplicate in document.get("duplicate_keys") or []
    ]
    required_failures = [probe for probe in probes if probe["required"] and not probe["passed"]]
    return {
        "valid": not required_failures,
        "source": mapped.get("source"),
        "probes": probes,
        "observations": {
            "duplicate_json_keys": duplicate_json_keys,
            "standalone_only_timelines": cache.get("standalone_only_count", 0),
            "format_map_version": mapped.get("format_map_version"),
        },
    }
