"""Inspect, validate, diff, and narrowly copy Filmora WFP project files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .audit import audit_title_card_copy
from .corpus import survey_projects
from .diffing import diff_projects
from .edit_plan import (
    EDIT_PLAN_API_VERSION,
    apply_edit_plan,
    explain_edit_plan,
    list_edit_targets,
)
from .evals import evaluate_project
from .feature_coverage import feature_coverage
from .mapping import map_project
from .rough_cut import (
    build_rough_cut_plan,
    detect_silence,
    evaluate_rough_cut_plan,
    inspect_rough_cut_seed,
    load_transcript,
    speech_regions_from_silences,
    transcribe_media_ranges,
    write_rough_cut_outputs,
)
from .rough_cut_wfp import write_rough_cut_project
from .title_cards import clone_title_cards, load_title_card_spec


def _dump_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _format_seconds(value: Any) -> str:
    if value is None:
        return "?"
    seconds = float(value)
    minutes, remainder = divmod(seconds, 60)
    return "{0:02.0f}:{1:06.3f}".format(minutes, remainder)


def _print_inspection(result: Dict[str, Any]) -> None:
    project = result["project"]
    archive = result["archive"]
    timeline = result["main_timeline"]
    fps = project["frame_rate"]
    resolution = project["resolution"]
    print("Project: {0}".format(project.get("name") or "(unnamed)"))
    print("Filmora: {0} on {1}".format(project.get("filmora_version") or "?", project.get("os") or "?"))
    print(
        "Timeline: {0}  {1}x{2}  {3}/{4} fps".format(
            _format_seconds(project.get("duration_seconds")),
            resolution.get("width"),
            resolution.get("height"),
            fps.get("numerator"),
            fps.get("denominator"),
        )
    )
    print(
        "Archive: {0} members, {1} timeline documents, {2} resources".format(
            archive.get("member_count"), archive.get("timeline_member_count"), len(result.get("resources") or [])
        )
    )
    print("Current timeline: {0}".format(project.get("current_timeline_id")))
    print("Tracks:")
    for track in timeline.get("tracks") or []:
        print(
            "  #{index} type={track_type} tag={track_tag} clips={clip_count} refs={nested_timeline_ids}".format(
                **track
            )
        )
    placements = timeline.get("nested_placements") or []
    if placements:
        print("Nested placements:")
        for placement in placements:
            print(
                "  timeline {0}: {1}-{2} on track {3}".format(
                    placement.get("timeline_id"),
                    _format_seconds(placement.get("start_seconds")),
                    _format_seconds(placement.get("end_seconds")),
                    placement.get("track_index"),
                )
            )
    titles = result.get("titles") or []
    if titles:
        print("Titles:")
        for title in titles:
            print(
                '  timeline {0}: "{1}" ({2} {3})'.format(
                    title.get("timeline_id"),
                    title.get("text"),
                    title.get("font") or "unknown font",
                    title.get("font_size") or "?",
                )
            )


def _print_titles(titles: List[Dict[str, Any]]) -> None:
    if not titles:
        print("No non-empty title text found.")
        return
    for title in titles:
        if title.get("error"):
            print("timeline {0}: {1}".format(title.get("timeline_id"), title["error"]))
            continue
        print(
            'timeline {0}  {1}-{2}  "{3}"  {4} {5}'.format(
                title.get("timeline_id"),
                _format_seconds(title.get("start_seconds")),
                _format_seconds(title.get("end_seconds")),
                title.get("text"),
                title.get("font") or "unknown font",
                title.get("font_size") or "?",
            )
        )


def _print_validation(result: Dict[str, Any]) -> None:
    print("VALID" if result.get("valid") else "INVALID")
    for error in result.get("errors") or []:
        print("ERROR: {0}".format(error))
    for warning in result.get("warnings") or []:
        print("WARNING: {0}".format(warning))
    details = result.get("details") or {}
    if details:
        print(
            "timelines={0} titles={1} main={2}".format(
                details.get("timeline_count"),
                details.get("title_count"),
                details.get("main_timeline_member"),
            )
        )


def _print_copy_audit(result: Dict[str, Any]) -> None:
    print("VALID TITLE-CARD COPY" if result.get("valid") else "INVALID TITLE-CARD COPY")
    for error in result.get("errors") or []:
        print("ERROR: {0}".format(error))
    for warning in result.get("warnings") or []:
        print("WARNING: {0}".format(warning))
    details = result.get("details") or {}
    if details:
        print(
            "new_cards={0} changed_members={1} added_members={2}".format(
                details.get("new_card_count"),
                len(details.get("changed_members") or []),
                len(details.get("added_members") or []),
            )
        )


def _print_diff(result: Dict[str, Any]) -> None:
    print("Changed members: {0}".format(len(result.get("changed_members") or [])))
    for member in result.get("changed_members") or []:
        print("  M {0}".format(member))
    for member in result.get("added_members") or []:
        print("  A {0}".format(member))
    for member in result.get("removed_members") or []:
        print("  D {0}".format(member))
    changes = result.get("json_changes") or []
    if changes:
        print("JSON changes:")
    for change in changes:
        print(
            "  {0} {1} {2}: {3!r} -> {4!r}".format(
                change.get("member"),
                change.get("kind"),
                change.get("path"),
                change.get("before"),
                change.get("after"),
            )
        )
    if result.get("truncated"):
        print("Output truncated. Increase --max-changes or narrow --member.")


def _print_map(result: Dict[str, Any]) -> None:
    source = result["source"]
    archive = result["archive"]
    timeline = result["timeline"]
    titles = result["titles"]
    identifiers = result["identifiers"]
    print("Filmora: {0} on {1}".format(source.get("filmora_version") or "?", source.get("os") or "?"))
    print(
        "Archive: {0} members, {1} JSON document kinds".format(
            archive.get("member_count"), len(result.get("documents") or {})
        )
    )
    print(
        "Canonical edit graph: {0} timelines, {1} title scripts, {2} effects, {3} transitions".format(
            timeline.get("canonical_timeline_count"),
            titles.get("script_buffer_count"),
            sum(effect.get("count", 0) for effect in result.get("effects") or []),
            sum(transition.get("count", 0) for transition in result.get("transitions") or []),
        )
    )
    print(
        "Serialized payloads: {0} parsed groups, {1} unparsed candidate groups".format(
            len(result.get("serialized_payloads") or []),
            len(result.get("serialized_payload_errors") or []),
        )
    )
    print("Clip types:")
    for clip_type in timeline.get("clip_types") or []:
        print("  type={0} count={1}".format(clip_type.get("type"), clip_type.get("count")))
    cache = timeline.get("standalone_cache") or {}
    print(
        "Standalone timeline copies: {0} exact, {1} standalone-only, {2} conflicting".format(
            cache.get("exact_copy_count", 0),
            cache.get("standalone_only_count", 0),
            cache.get("conflicting_copy_count", 0),
        )
    )
    timeline_ids = identifiers.get("timeline_ids") or {}
    print(
        "Timeline references: {0} total, {1} unresolved".format(
            timeline_ids.get("references", 0), len(timeline_ids.get("unresolved_references") or [])
        )
    )
    duplicate_documents = [
        (kind, len(document.get("duplicate_keys") or []))
        for kind, document in (result.get("documents") or {}).items()
        if document.get("duplicate_keys")
    ]
    if duplicate_documents:
        print("Duplicate JSON keys:")
        for kind, count in duplicate_documents:
            print("  {0}: {1} repeated path/key pair(s)".format(kind, count))
    print("Use --json for the full normalized field, enum, effect, transition, and userData map.")


def _print_evaluation(result: Dict[str, Any]) -> None:
    print("FORMAT EVAL PASSED" if result.get("valid") else "FORMAT EVAL FAILED")
    for probe in result.get("probes") or []:
        status = "PASS" if probe.get("passed") else "FAIL"
        print("{0} {1}: {2}".format(status, probe.get("name"), probe.get("detail")))
    observations = result.get("observations") or {}
    duplicate_keys = observations.get("duplicate_json_keys") or []
    if duplicate_keys:
        print("OBSERVED duplicate JSON key patterns: {0}".format(len(duplicate_keys)))


def _print_survey(result: Dict[str, Any]) -> None:
    inventory = result.get("inventory") or {}
    print(
        "Corpus: {0} files, {1} unique, {2} mapped, {3} failed".format(
            inventory.get("discovered_files", 0),
            inventory.get("unique_file_hashes", 0),
            inventory.get("mapped_projects", 0),
            inventory.get("failed_projects", 0),
        )
    )
    print("Versions:")
    for version in result.get("versions") or []:
        print(
            "  {0}: {1} projects, {2} copies, {3}".format(
                version.get("modified_version"),
                version.get("projects"),
                version.get("copies"),
                version.get("relevance"),
            )
        )
    features = result.get("features") or {}
    feature_summary = (
        len(features.get("clip_types") or []),
        len(features.get("effects") or []),
        len(features.get("transitions") or []),
        len(features.get("title_fields") or []),
        len(features.get("serialized_payloads") or []),
    )
    summary = (
        "Features: {0} clip types, {1} effects, {2} transitions, "
        "{3} title fields, {4} serialized payloads"
    )
    print(summary.format(*feature_summary))
    failures = result.get("eval_probe_failures") or []
    if failures:
        print("Compatibility probe failures:")
        for failure in failures:
            print("  {0}: {1} projects".format(failure.get("probe"), failure.get("projects")))


def _print_feature_coverage(result: Dict[str, Any]) -> None:
    summary = result["summary"]
    print(
        "Filmora feature coverage: {0} features across {1} areas".format(
            summary["total"], summary["areas"]
        )
    )
    print(
        "  "
        + ", ".join(
            "{0}={1}".format(status, count)
            for status, count in summary["by_status"].items()
        )
    )
    current_area = None
    for feature in result["features"]:
        if feature["area"] != current_area:
            current_area = feature["area"]
            print("{0}:".format(current_area))
        print(
            "  [{0}] {1} ({2})".format(
                feature["status"], feature["feature"], feature["evidence"]
            )
        )


def _print_edit_targets(result: Dict[str, Any]) -> None:
    source = result.get("source") or {}
    print(
        "Project: {0}  Filmora {1} on {2}".format(
            source.get("filename"),
            source.get("filmora_version") or "?",
            source.get("os") or "?",
        )
    )
    print("SHA-256: {0}".format(source.get("sha256")))
    templates = result.get("title_card_templates") or []
    print("Compatible title-card templates: {0}".format(len(templates)))
    for target in templates:
        selector = target.get("selector") or {}
        print(
            '  timeline {0}: "{1}" / "{2}"'.format(
                target.get("resolved_timeline_id"),
                selector.get("heading"),
                selector.get("subheading"),
            )
        )
    title_targets = result.get("title_text_targets") or []
    print("Replaceable existing titles: {0}".format(len(title_targets)))
    for target in title_targets:
        selector = target.get("selector") or {}
        print(
            '  {0}: "{1}"'.format(
                selector.get("clip_uid"),
                selector.get("text"),
            )
        )
    rotation_targets = result.get("rotation_targets") or []
    print("Replaceable clip rotations: {0}".format(len(rotation_targets)))
    for target in rotation_targets:
        selector = target.get("selector") or {}
        print(
            "  {0}: {1} degrees".format(
                selector.get("clip_uid"), selector.get("rotation")
            )
        )
    transition_targets = result.get("linked_transition_targets") or []
    print("Replaceable linked Dissolves: {0}".format(len(transition_targets)))
    for target in transition_targets:
        selector = target.get("selector") or {}
        print(
            "  {0} + {1}: {2} ticks".format(
                selector.get("video_clip_uid"),
                selector.get("audio_clip_uid"),
                selector.get("duration_ticks"),
            )
        )
    linked_av_targets = result.get("linked_av_targets") or []
    print("Editable linked A/V pairs: {0}".format(len(linked_av_targets)))
    for target in linked_av_targets:
        selector = target.get("selector") or {}
        print(
            "  {0} + {1}: {2}-{3} ticks ({4})".format(
                selector.get("video_clip_uid"),
                selector.get("audio_clip_uid"),
                selector.get("start_ticks"),
                selector.get("end_ticks"),
                ", ".join(target.get("capabilities") or []),
            )
        )


def _print_plan_explanation(result: Dict[str, Any]) -> None:
    print("EDIT PLAN READY" if result.get("status") == "ready" else "EDIT PLAN NOT READY")
    print("Writes performed: {0}".format(str(bool(result.get("writes_performed"))).lower()))
    for operation in result.get("operations") or []:
        if operation.get("op") == "replace_title_text":
            target = operation.get("resolved_target") or {}
            selector = target.get("selector") or {}
            print(
                '{0}: "{1}" -> "{2}"'.format(
                    operation.get("op"),
                    selector.get("text"),
                    operation.get("new_text"),
                )
            )
            continue
        if operation.get("op") == "replace_clip_rotation":
            selector = operation.get("requested_target") or {}
            print(
                "replace_clip_rotation: {0} -> {1}".format(
                    selector.get("rotation"), operation.get("new_rotation")
                )
            )
            continue
        if operation.get("op") in (
            "replace_linked_transition_duration",
            "remove_linked_transition",
        ):
            selector = operation.get("requested_target") or {}
            suffix = (
                " -> {0} ticks".format(operation.get("new_duration_ticks"))
                if operation.get("op") == "replace_linked_transition_duration"
                else " -> removed"
            )
            print(
                "{0}: {1} ticks{2}".format(
                    operation.get("op"), selector.get("duration_ticks"), suffix
                )
            )
            continue
        target = operation.get("resolved_template") or {}
        print(
            "{0}: {1} card(s) from current timeline {2}".format(
                operation.get("op"),
                len(operation.get("cards") or []),
                target.get("resolved_timeline_id"),
            )
        )
        for card in operation.get("cards") or []:
            print(
                '  {0} ticks: "{1}" / "{2}"'.format(
                    card.get("resolved_start_ticks"),
                    card.get("heading"),
                    card.get("subheading"),
                )
            )
    print("Filmora round trip required: yes")


def _print_plan_application(result: Dict[str, Any]) -> None:
    print("EDIT PLAN APPLIED")
    print(result.get("output"))
    operations = result.get("operations") or []
    if operations and operations[0].get("op") != "clone_title_cards":
        print("Applied operation: {0}".format(operations[0].get("op")))
    else:
        print("Created title cards: {0}".format(len(result.get("created_cards") or [])))
    verification = result.get("verification") or {}
    print(
        "Source-aware audit: {0}".format(
            "passed" if verification.get("source_aware_audit_valid") else "failed"
        )
    )
    print("Filmora round trip still required: yes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="filmora-project", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Summarize a WFP project")
    inspect_parser.add_argument("project")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.add_argument("--reveal-paths", action="store_true")

    titles_parser = subparsers.add_parser("titles", help="List decoded title text and styling")
    titles_parser.add_argument("project")
    titles_parser.add_argument("--include-empty", action="store_true")
    titles_parser.add_argument("--json", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Check archive and reference integrity")
    validate_parser.add_argument("project")
    validate_parser.add_argument("--check-media", action="store_true")
    validate_parser.add_argument("--json", action="store_true")

    unpack_parser = subparsers.add_parser("unpack", help="Safely extract a WFP to a new directory")
    unpack_parser.add_argument("project")
    unpack_parser.add_argument("destination")

    diff_parser = subparsers.add_parser("diff", help="Compare controlled before/after WFP saves")
    diff_parser.add_argument("before")
    diff_parser.add_argument("after")
    diff_parser.add_argument("--member", help="Only report archive members containing this text")
    diff_parser.add_argument("--max-changes", type=int, default=200)
    diff_parser.add_argument("--reveal-paths", action="store_true")
    diff_parser.add_argument("--json", action="store_true")

    map_parser = subparsers.add_parser(
        "map",
        help="Inventory normalized JSON paths, enums, references, effects, and opaque payloads",
    )
    map_parser.add_argument("project")
    map_parser.add_argument("--reveal-paths", action="store_true")
    map_parser.add_argument("--json", action="store_true")

    eval_parser = subparsers.add_parser(
        "eval-format",
        help="Run repeatable archive, reference, cache, title, and routing compatibility probes",
    )
    eval_parser.add_argument("project")
    eval_parser.add_argument("--json", action="store_true")

    survey_parser = subparsers.add_parser(
        "survey",
        help="Recursively map and de-duplicate a read-only corpus of WFP projects",
    )
    survey_parser.add_argument("inputs", nargs="+")
    survey_parser.add_argument("--reference-version")
    survey_parser.add_argument("--reveal-paths", action="store_true")
    survey_parser.add_argument("--json", action="store_true")
    survey_parser.add_argument("--output", help="Write the JSON survey to a new file")

    coverage_parser = subparsers.add_parser(
        "feature-coverage",
        help="Report which Filmora surfaces are writable, mapped, partial, or open",
    )
    coverage_parser.add_argument(
        "--status",
        choices=("writable", "mapped", "partial", "open", "external_dependency"),
    )
    coverage_parser.add_argument("--json", action="store_true")

    clone_parser = subparsers.add_parser(
        "clone-title-cards",
        help="Clone an observed compound title-card template into a new project copy",
    )
    clone_parser.add_argument("project")
    clone_parser.add_argument("output")
    clone_parser.add_argument("--template-timeline", required=True, type=int)
    clone_parser.add_argument(
        "--spec",
        required=True,
        help="JSON array of title cards and exact timeline ticks",
    )
    clone_parser.add_argument("--expect-sha256", help="Refuse if the source fingerprint has changed")
    clone_parser.add_argument("--json", action="store_true")

    audit_parser = subparsers.add_parser(
        "audit-title-card-copy",
        help="Check a generated title-card copy against its source project",
    )
    audit_parser.add_argument("source")
    audit_parser.add_argument("output")
    audit_parser.add_argument("--check-media", action="store_true")
    audit_parser.add_argument("--json", action="store_true")

    targets_parser = subparsers.add_parser(
        "edit-targets",
        help="List source-hash-bound targets supported by edit plans",
    )
    targets_parser.add_argument("project")
    targets_parser.add_argument("--json", action="store_true")

    explain_plan_parser = subparsers.add_parser(
        "explain-plan",
        help="Resolve and validate an edit plan without writing a project",
    )
    explain_plan_parser.add_argument("project")
    explain_plan_parser.add_argument("plan")
    explain_plan_parser.add_argument("--json", action="store_true")

    apply_plan_parser = subparsers.add_parser(
        "apply-plan",
        help="Apply a verified edit plan to a new project copy",
    )
    apply_plan_parser.add_argument("project")
    apply_plan_parser.add_argument("output")
    apply_plan_parser.add_argument("plan")
    apply_plan_parser.add_argument("--json", action="store_true")

    rough_cut_parser = subparsers.add_parser(
        "rough-cut-plan",
        help="Transcribe media and write a reviewable silence/duplicate-take cut plan",
    )
    rough_cut_parser.add_argument("media")
    rough_cut_parser.add_argument("output_directory")
    rough_cut_parser.add_argument(
        "--transcript",
        help="Reuse an existing SRT or rough-cut transcript JSON instead of transcribing",
    )
    rough_cut_parser.add_argument("--model", default="small.en")
    rough_cut_parser.add_argument("--device", default="cpu")
    rough_cut_parser.add_argument("--compute-type", default="int8")
    rough_cut_parser.add_argument("--ffmpeg", default="ffmpeg")
    rough_cut_parser.add_argument("--threshold-db", type=float, default=-35.0)
    rough_cut_parser.add_argument("--minimum-silence", type=float, default=0.5)
    rough_cut_parser.add_argument("--softening-buffer", type=float, default=0.4)
    rough_cut_parser.add_argument("--duplicate-window", type=float, default=90.0)
    rough_cut_parser.add_argument("--auto-drop-confidence", type=float, default=0.90)
    rough_cut_parser.add_argument("--minimum-duplicate-words", type=int, default=5)
    rough_cut_parser.add_argument(
        "--short-clip-suspicion",
        type=float,
        default=5.0,
        help="Mark retained clips shorter than this many seconds for review (0 disables)",
    )
    rough_cut_parser.add_argument(
        "--keep-untranscribed-audio",
        action="store_true",
        help="Keep audible regions with no transcript-word overlap for manual review",
    )
    rough_cut_parser.add_argument("--json", action="store_true")

    rough_cut_eval_parser = subparsers.add_parser(
        "rough-cut-eval",
        help="Compare a rough-cut plan with linked source ranges in a manual WFP edit",
    )
    rough_cut_eval_parser.add_argument("plan")
    rough_cut_eval_parser.add_argument("reference_project")
    rough_cut_eval_parser.add_argument("--source-uuid")
    rough_cut_eval_parser.add_argument("--json", action="store_true")

    rough_cut_seed_parser = subparsers.add_parser(
        "rough-cut-seed",
        help="Read-only check for the single linked-pair WFP seed shape",
    )
    rough_cut_seed_parser.add_argument("project")
    rough_cut_seed_parser.add_argument("--json", action="store_true")

    rough_cut_project_parser = subparsers.add_parser(
        "rough-cut-project",
        help="Create a new Filmora WFP rough cut from a seed and reviewed plan",
    )
    rough_cut_project_parser.add_argument("seed")
    rough_cut_project_parser.add_argument("plan")
    rough_cut_project_parser.add_argument("output")
    rough_cut_project_parser.add_argument("--expect-sha256")
    rough_cut_project_parser.add_argument("--json", action="store_true")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_project(args.project, reveal_paths=args.reveal_paths)
            _dump_json(result) if args.json else _print_inspection(result)
            return 0
        if args.command == "titles":
            result = list_titles(args.project, include_empty=args.include_empty)
            _dump_json(result) if args.json else _print_titles(result)
            return 0
        if args.command == "validate":
            result = validate_project(args.project, check_media=args.check_media)
            _dump_json(result) if args.json else _print_validation(result)
            return 0 if result.get("valid") else 1
        if args.command == "unpack":
            with WfpArchive(args.project) as archive:
                destination = archive.safe_extract(args.destination)
            print(destination)
            return 0
        if args.command == "diff":
            result = diff_projects(
                args.before,
                args.after,
                member_filter=args.member,
                max_changes=args.max_changes,
                reveal_paths=args.reveal_paths,
            )
            _dump_json(result) if args.json else _print_diff(result)
            return 0
        if args.command == "map":
            result = map_project(args.project, reveal_paths=args.reveal_paths)
            _dump_json(result) if args.json else _print_map(result)
            return 0
        if args.command == "eval-format":
            result = evaluate_project(args.project)
            _dump_json(result) if args.json else _print_evaluation(result)
            return 0 if result.get("valid") else 1
        if args.command == "survey":
            result = survey_projects(
                args.inputs,
                reference_version=args.reference_version,
                reveal_paths=args.reveal_paths,
            )
            if args.output:
                output = Path(args.output).expanduser().resolve()
                if output.exists():
                    raise WfpError("Refusing to overwrite survey output: {0}".format(output))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(output)
            else:
                _dump_json(result) if args.json else _print_survey(result)
            return 0 if not (result.get("failures") or []) else 1
        if args.command == "feature-coverage":
            result = feature_coverage(args.status)
            _dump_json(result) if args.json else _print_feature_coverage(result)
            return 0
        if args.command == "clone-title-cards":
            result = clone_title_cards(
                args.project,
                args.output,
                template_timeline_id=args.template_timeline,
                cards=load_title_card_spec(args.spec),
                expected_source_sha256=args.expect_sha256,
            )
            if args.json:
                _dump_json(result)
            else:
                print(result["output"])
                print("Created title cards: {0}".format(len(result["created_cards"])))
            return 0
        if args.command == "audit-title-card-copy":
            result = audit_title_card_copy(args.source, args.output, check_media=args.check_media)
            _dump_json(result) if args.json else _print_copy_audit(result)
            return 0 if result.get("valid") else 1
        if args.command == "edit-targets":
            result = list_edit_targets(args.project)
            _dump_json(result) if args.json else _print_edit_targets(result)
            return 0
        if args.command == "explain-plan":
            result = explain_edit_plan(args.project, args.plan)
            _dump_json(result) if args.json else _print_plan_explanation(result)
            return 0
        if args.command == "apply-plan":
            result = apply_edit_plan(args.project, args.output, args.plan)
            _dump_json(result) if args.json else _print_plan_application(result)
            return 0
        if args.command == "rough-cut-plan":
            print("Detecting silence...", file=sys.stderr)
            duration, silences = detect_silence(
                args.media,
                ffmpeg=args.ffmpeg,
                threshold_db=args.threshold_db,
                minimum_duration=args.minimum_silence,
            )
            if args.transcript:
                print("Loading transcript...", file=sys.stderr)
                transcript = load_transcript(args.transcript)
                transcription_mode = "provided_transcript"
            else:
                print("Transcribing silence-cut regions...", file=sys.stderr)
                transcript = transcribe_media_ranges(
                    args.media,
                    speech_regions_from_silences(
                        duration,
                        silences,
                        softening_buffer=args.softening_buffer,
                    ),
                    model_name=args.model,
                    device=args.device,
                    compute_type=args.compute_type,
                )
                transcription_mode = "independent_silence_regions"
            media_path = Path(args.media).expanduser().resolve()
            plan = build_rough_cut_plan(
                source_name=media_path.name,
                duration_seconds=duration,
                silences=silences,
                transcript=transcript,
                softening_buffer=args.softening_buffer,
                threshold_db=args.threshold_db,
                minimum_silence=args.minimum_silence,
                duplicate_window=args.duplicate_window,
                auto_drop_confidence=args.auto_drop_confidence,
                minimum_duplicate_words=args.minimum_duplicate_words,
                short_clip_suspicion_seconds=args.short_clip_suspicion,
                drop_untranscribed_audio=not args.keep_untranscribed_audio,
            )
            plan["settings"]["transcription_mode"] = transcription_mode
            outputs = write_rough_cut_outputs(
                args.output_directory,
                plan=plan,
                transcript=transcript,
            )
            summary = {
                "outputs": outputs,
                "regions": len(plan.get("regions") or []),
                "duplicate_drops": len(plan.get("duplicate_drop_ranges") or []),
                "non_speech_drops": len(plan.get("non_speech_drop_ranges") or []),
                "review_regions": sum(
                    item.get("decision") == "review"
                    for item in plan.get("regions") or []
                ),
                "filmora_handoff": plan.get("filmora_handoff"),
            }
            if args.json:
                _dump_json(summary)
            else:
                print(outputs["plan"])
                print("Speech regions: {0}".format(summary["regions"]))
                print("High-confidence duplicate drops: {0}".format(summary["duplicate_drops"]))
                print("Untranscribed audio drops: {0}".format(summary["non_speech_drops"]))
                print("Review regions: {0}".format(summary["review_regions"]))
                print("Filmora writer: available after rough-cut-seed check")
            return 0
        if args.command == "rough-cut-eval":
            result = evaluate_rough_cut_plan(
                args.plan,
                args.reference_project,
                source_uuid=args.source_uuid,
            )
            if args.json:
                _dump_json(result)
            else:
                print("Keep precision: {0:.1%}".format(result["keep_precision"]))
                print("Keep recall: {0:.1%}".format(result["keep_recall"]))
                print("Keep IoU: {0:.1%}".format(result["keep_iou"]))
                print(
                    "Duplicate drops: {0:.3f}s correct, {1:.3f}s overlapping manual keeps".format(
                        result["duplicate_correct_drop_seconds"],
                        result["duplicate_false_drop_seconds"],
                    )
                )
            return 0
        if args.command == "rough-cut-seed":
            result = inspect_rough_cut_seed(args.project)
            if args.json:
                _dump_json(result)
            else:
                print("VALID SEED SHAPE" if result["valid_seed_shape"] else "INVALID SEED SHAPE")
                for issue in result.get("issues") or []:
                    print("ERROR: {0}".format(issue))
                print(
                    "Filmora writer available: {0}".format(
                        "yes" if result.get("filmora_writer_available") else "no"
                    )
                )
            return 0 if result["valid_seed_shape"] else 1
        if args.command == "rough-cut-project":
            result = write_rough_cut_project(
                args.seed,
                args.output,
                args.plan,
                expected_source_sha256=args.expect_sha256,
            )
            if args.json:
                _dump_json(result)
            else:
                print(result["output"])
                print("Linked A/V pairs: {0}".format(result["output_pair_count"]))
                print("Timeline duration: {0:.3f}s".format(result["output_duration_seconds"]))
                print("Source-aware audit: valid")
            return 0
    except WfpError as exc:
        if getattr(args, "json", False):
            error_result: Dict[str, Any] = {
                "error": {
                    "code": "wfp_error",
                    "message": str(exc),
                }
            }
            if args.command in {"edit-targets", "explain-plan", "apply-plan"}:
                error_result["api_version"] = EDIT_PLAN_API_VERSION
            print(
                json.dumps(error_result, sort_keys=True),
                file=sys.stderr,
            )
        else:
            print("error: {0}".format(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
