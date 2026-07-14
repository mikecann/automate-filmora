"""Inspect, validate, diff, and narrowly copy Filmora WFP project files."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .diffing import diff_projects
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
    except WfpError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
