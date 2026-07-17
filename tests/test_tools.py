from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from filmora_wfp import (
    EditPlan,
    WfpArchive,
    WfpError,
    apply_edit_plan,
    audit_title_text_copy,
    audit_title_card_copy,
    clone_title_cards,
    discover_projects,
    diff_projects,
    edit_plan_schema,
    evaluate_project,
    explain_edit_plan,
    inspect_project,
    list_edit_targets,
    list_titles,
    load_edit_plan,
    map_project,
    project_sha256,
    replace_title_text,
    survey_projects,
    validate_project,
)
from filmora_wfp.cli import main as cli_main

from tests.helpers import write_cloneable_title_project, write_project


def _rewrite_main_timeline(source: Path, destination: Path, mutate) -> Path:
    """Copy a fixture while applying one test-only change to the routed main timeline."""

    with zipfile.ZipFile(source, "r") as before, zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED
    ) as after:
        for info in before.infolist():
            data = before.read(info)
            if info.filename == "ProjectFolder/Medias/MAIN/timeline.wesproj":
                timeline = json.loads(data)
                mutate(timeline)
                data = json.dumps(timeline, separators=(",", ":")).encode("utf-8")
            after.writestr(info, data)
    return destination


def _edit_plan(source: Path, *, seconds: str = "5") -> dict:
    return {
        "schema_version": 1,
        "description": "Synthetic declarative title-card edit",
        "source": {"sha256": project_sha256(source)},
        "operations": [
            {
                "id": "add-next-tip",
                "op": "clone_title_cards",
                "template": {
                    "heading": "1. Template",
                    "subheading": "Template subtitle",
                },
                "cards": [
                    {
                        "at": {"seconds": seconds},
                        "heading": "2. Next Tip",
                        "subheading": "A useful subtitle",
                        "heading_font_size": "72",
                        "heading_scale_x": "0.7",
                        "subheading_font_size": "32",
                        "subheading_scale_x": "0.45",
                    }
                ],
            }
        ],
    }


def _replace_text_plan(source: Path) -> dict:
    return {
        "schema_version": 2,
        "description": "Replace one existing title without changing its serialized length",
        "source": {"sha256": project_sha256(source)},
        "operations": [
            {
                "id": "rename-template",
                "op": "replace_title_text",
                "target": {
                    "clip_uid": "12000000-0000-4000-8000-000000000002",
                    "text": "1. Template",
                },
                "new_text": "1. Templatf",
            }
        ],
    }


class FilmoraProjectToolsTest(unittest.TestCase):
    def test_replace_title_text_changes_only_equal_length_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            output = root / "output.wfp"
            source_before = source.read_bytes()

            result = replace_title_text(
                source,
                output,
                clip_uid="12000000-0000-4000-8000-000000000002",
                old_text="1. Template",
                new_text="1. Templatf",
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(output.is_file())
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["audit"]["details"]["title_occurrences_changed"], 2)
            self.assertIn("1. Templatf", [title["text"] for title in list_titles(output)])
            self.assertNotIn("1. Template", [title["text"] for title in list_titles(output)])
            audit = audit_title_text_copy(
                source,
                output,
                clip_uid="12000000-0000-4000-8000-000000000002",
                old_text="1. Template",
                new_text="1. Templatf",
            )
            self.assertTrue(audit["valid"], audit)

            with self.assertRaisesRegex(WfpError, "Refusing to overwrite"):
                replace_title_text(
                    source,
                    output,
                    clip_uid="12000000-0000-4000-8000-000000000002",
                    old_text="1. Template",
                    new_text="1. Templatf",
                )

    def test_replace_title_text_rejects_unsafe_length_and_removes_failed_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            unequal = root / "unequal.wfp"
            with self.assertRaisesRegex(WfpError, "serialized script length"):
                replace_title_text(
                    source,
                    unequal,
                    clip_uid="12000000-0000-4000-8000-000000000002",
                    old_text="1. Template",
                    new_text="A much longer title",
                )
            self.assertFalse(unequal.exists())

            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.title_text.audit_title_text_copy",
                return_value={"valid": False, "errors": ["controlled audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled audit failure"):
                    replace_title_text(
                        source,
                        rejected,
                        clip_uid="12000000-0000-4000-8000-000000000002",
                        old_text="1. Template",
                        new_text="1. Templatf",
                    )
            self.assertFalse(rejected.exists())

    def test_edit_targets_and_explain_plan_resolve_current_title_texts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            targets = list_edit_targets(source)
            self.assertEqual(targets["api_version"], 2)
            self.assertEqual(targets["source"]["sha256"], project_sha256(source))
            self.assertEqual(
                targets["title_card_templates"],
                [
                    {
                        "target_type": "compound_title_card_template",
                        "selector": {
                            "heading": "1. Template",
                            "subheading": "Template subtitle",
                        },
                        "template_metrics": {
                            "heading": {
                                "font": "Bebas Neue",
                                "font_size": 80.0,
                                "scale_x": 0.7,
                                "scale_y": 0.2,
                            },
                            "subheading": {
                                "font": "Bebas Neue",
                                "font_size": 80.0,
                                "scale_x": 0.7,
                                "scale_y": 0.2,
                            },
                        },
                        "resolved_timeline_id": 10,
                        "duration_ticks": 20_000_000,
                        "current_start_ticks": [10_000_000],
                    }
                ],
            )
            self.assertEqual(len(targets["title_text_targets"]), 2)
            self.assertEqual(
                targets["title_text_targets"][0]["selector"],
                {
                    "clip_uid": "12000000-0000-4000-8000-000000000002",
                    "text": "1. Template",
                },
            )

            result = explain_edit_plan(source, _edit_plan(source))
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["writes_performed"])
            self.assertTrue(result["preflight"]["source_sha256_matches"])
            self.assertTrue(result["preflight"]["format_eval_valid"])
            operation = result["operations"][0]
            self.assertEqual(operation["resolved_template"]["resolved_timeline_id"], 10)
            self.assertEqual(operation["cards"][0]["resolved_start_ticks"], 50_000_000)
            self.assertTrue(result["filmora_round_trip"]["required"])
            self.assertFalse(result["filmora_round_trip"]["performed"])

            schema = edit_plan_schema(1)
            self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
            self.assertEqual(
                schema["$defs"]["cloneTitleCardsOperation"]["properties"]["op"]["const"],
                "clone_title_cards",
            )
            schema_v2 = edit_plan_schema()
            self.assertEqual(schema_v2["properties"]["schema_version"]["const"], 2)
            self.assertEqual(
                schema_v2["$defs"]["replaceTitleTextOperation"]["properties"]["op"]["const"],
                "replace_title_text",
            )

    def test_v2_replace_title_text_plan_explains_and_applies_audited_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            source_before = source.read_bytes()
            output = root / "output.wfp"
            plan = _replace_text_plan(source)

            explanation = explain_edit_plan(source, plan)
            self.assertEqual(explanation["api_version"], 2)
            self.assertEqual(explanation["plan_schema_version"], 2)
            self.assertFalse(explanation["writes_performed"])
            operation = explanation["operations"][0]
            self.assertEqual(operation["op"], "replace_title_text")
            self.assertEqual(operation["new_text"], "1. Templatf")
            self.assertTrue(operation["serialized_length_preserved"])

            result = apply_edit_plan(source, output, plan)
            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["verification"]["source_aware_audit_valid"])
            self.assertFalse(result["verification"]["filmora_round_trip_performed"])
            self.assertIn("1. Templatf", [title["text"] for title in list_titles(output)])

            unequal = _replace_text_plan(source)
            unequal["operations"][0]["new_text"] = "A much longer title"
            with self.assertRaisesRegex(WfpError, "serialized script length"):
                explain_edit_plan(source, unequal)

            escaped = _replace_text_plan(source)
            escaped["operations"][0]["new_text"] = '1. Templat"'
            with self.assertRaisesRegex(WfpError, "serialized script length"):
                explain_edit_plan(source, escaped)

    def test_apply_edit_plan_uses_audited_writer_and_keeps_ui_gate_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            source_before = source.read_bytes()
            output = root / "output.wfp"

            result = apply_edit_plan(source, output, _edit_plan(source))

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(output.is_file())
            self.assertEqual(result["status"], "applied")
            self.assertTrue(result["writes_performed"])
            self.assertTrue(result["verification"]["source_aware_audit_valid"])
            self.assertTrue(result["verification"]["filmora_round_trip_required"])
            self.assertFalse(result["verification"]["filmora_round_trip_performed"])
            self.assertIn("2. Next Tip", [title["text"] for title in list_titles(output)])

    def test_edit_plan_rejects_stale_unsupported_and_lossy_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = write_cloneable_title_project(Path(temporary) / "source.wfp")

            stale = _edit_plan(source)
            stale["source"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                explain_edit_plan(source, stale)

            unsupported = _edit_plan(source)
            unsupported["operations"][0]["op"] = "trim_clip"
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(unsupported)

            boolean_version = _edit_plan(source)
            boolean_version["schema_version"] = True
            with self.assertRaisesRegex(WfpError, "Unsupported edit-plan schema_version"):
                load_edit_plan(boolean_version)

            lossy = _edit_plan(source, seconds="1.00000001")
            with self.assertRaisesRegex(WfpError, "100 ns tick precision"):
                load_edit_plan(lossy)

            exponent = _edit_plan(source, seconds="1e-3")
            with self.assertRaisesRegex(WfpError, "non-negative decimal"):
                load_edit_plan(exponent)

            bypass = EditPlan(
                schema_version=1,
                source_sha256=project_sha256(source),
                operations=(),
            )
            with self.assertRaisesRegex(WfpError, "exactly one"):
                load_edit_plan(bypass)

            with self.assertRaisesRegex(WfpError, "filesystem path"):
                load_edit_plan(None)  # type: ignore[arg-type]

            overlapping = _edit_plan(source)
            second = dict(overlapping["operations"][0]["cards"][0])
            second["at"] = {"seconds": "6"}
            overlapping["operations"][0]["cards"].append(second)
            with self.assertRaisesRegex(WfpError, "Planned title cards overlap"):
                explain_edit_plan(source, overlapping)

            with self.assertRaisesRegex(WfpError, "must use the .wfp extension"):
                apply_edit_plan(source, Path(temporary) / "output.zip", _edit_plan(source))

    def test_edit_plan_cli_json_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            source_before = source.read_bytes()
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(_edit_plan(source)), encoding="utf-8")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = cli_main(
                    ["explain-plan", str(source), str(plan_path), "--json"]
                )

            self.assertEqual(exit_code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["writes_performed"])
            self.assertEqual(source.read_bytes(), source_before)

            output = root / "cli-output.wfp"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "apply-plan",
                        str(source),
                        str(output),
                        str(plan_path),
                        "--json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "applied")
            self.assertTrue(result["verification"]["source_aware_audit_valid"])
            self.assertTrue(output.is_file())

            stale_plan = _edit_plan(source)
            stale_plan["source"]["sha256"] = "0" * 64
            stale_path = root / "stale-plan.json"
            stale_path.write_text(json.dumps(stale_plan), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = cli_main(
                    ["explain-plan", str(source), str(stale_path), "--json"]
                )
            self.assertEqual(exit_code, 2)
            error = json.loads(stderr.getvalue())
            self.assertEqual(error["api_version"], 2)
            self.assertEqual(error["error"]["code"], "wfp_error")
            self.assertIn("Source fingerprint changed", error["error"]["message"])

    def test_corpus_survey_deduplicates_and_aggregates_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_project(root / "first.wfp")
            shutil.copyfile(first, root / "duplicate.wfp")
            write_cloneable_title_project(root / "compound.wfp")
            (root / "ignore.txt").write_text("not a project", encoding="utf-8")

            self.assertEqual(len(discover_projects([root])), 3)
            result = survey_projects([root], reference_version="15.6.4.11894")

            self.assertEqual(result["inventory"]["discovered_files"], 3)
            self.assertEqual(result["inventory"]["wfp_files"], 3)
            self.assertEqual(result["inventory"]["bundle_files"], 0)
            self.assertEqual(result["inventory"]["hashed_files"], 3)
            self.assertEqual(result["inventory"]["unique_file_hashes"], 2)
            self.assertEqual(result["inventory"]["duplicate_files"], 1)
            self.assertEqual(result["inventory"]["mapped_projects"], 2)
            self.assertEqual(result["inventory"]["failed_projects"], 0)
            self.assertFalse(any("paths" in sample for sample in result["samples"]))
            clip_types = {row["type"]: row for row in result["features"]["clip_types"]}
            self.assertEqual(clip_types["4"]["projects"], 2)
            self.assertEqual(clip_types["6"]["occurrences"], 1)
            track_types = {
                row["track_type"]: row for row in result["features"]["track_types"]
            }
            self.assertIn("occurrences", track_types["1"])
            self.assertNotIn("projects", track_types["1"])
            version = result["versions"][0]
            self.assertEqual(version["modified_version"], "15.6.4.11894")
            self.assertEqual(version["relevance"], "exact")
            self.assertEqual(version["projects"], 2)
            self.assertEqual(version["copies"], 3)

    def test_bundle_maps_embedded_project_without_reading_bundled_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = write_project(root / "inside.wfp")
            bundle = root / "package.wfpbundle"
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("Medias/large-video.mp4", b"x" * 1024 * 1024)
                archive.writestr("inside.wfp", project.read_bytes())

            mapped = map_project(bundle)
            self.assertEqual(mapped["source"]["filmora_version"], "15.6.4.11894")

            result = survey_projects([project, bundle], reference_version="15.6.4.11894")
            self.assertEqual(result["inventory"]["discovered_files"], 2)
            self.assertEqual(result["inventory"]["wfp_files"], 1)
            self.assertEqual(result["inventory"]["bundle_files"], 1)
            self.assertEqual(result["inventory"]["hashed_files"], 2)
            self.assertEqual(result["inventory"]["unique_file_hashes"], 1)
            self.assertEqual(result["inventory"]["duplicate_files"], 1)
            self.assertEqual(result["samples"][0]["copies"], 2)
            with self.assertRaisesRegex(WfpError, "require a .wfp source"):
                list_edit_targets(bundle)

    def test_format_eval_checks_graph_cache_and_title_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_cloneable_title_project(Path(temporary) / "fixture.wfp")

            result = evaluate_project(project)

            self.assertTrue(result["valid"], result)
            self.assertTrue(all(probe["passed"] for probe in result["probes"]), result)
            self.assertEqual(result["observations"]["standalone_only_timelines"], 0)

    def test_format_eval_resolves_resources_from_standalone_timeline_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_cloneable_title_project(Path(temporary) / "fixture.wfp")
            standalone = {
                "currentTimelineId": 99,
                "resources": [
                    {
                        "filename": "file:///private/example/standalone.mp4",
                        "sourceUuid": "standalone-source",
                    }
                ],
                "timelineInfos": [
                    {
                        "timelineId": 99,
                        "trackInfos": [
                            {
                                "trackType": 1,
                                "uuid": "standalone-track",
                                "clipList": [
                                    {
                                        "type": 1,
                                        "sourceUuid": "standalone-source",
                                        "thisUId": "standalone-clip",
                                        "tlBegin": 0,
                                        "tlEnd": 10_000_000,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            with zipfile.ZipFile(project, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "ProjectFolder/Medias/STANDALONE/timeline.wesproj",
                    json.dumps(standalone, separators=(",", ":")),
                )

            result = evaluate_project(project)

            source_probe = next(
                probe
                for probe in result["probes"]
                if probe["name"] == "source_uuid_references_resolve"
            )
            self.assertTrue(source_probe["passed"], result)
            self.assertEqual(result["observations"]["standalone_only_timelines"], 1)

    def test_map_profiles_canonical_graph_and_opaque_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_cloneable_title_project(Path(temporary) / "fixture.wfp")

            result = map_project(project)

            self.assertEqual(result["source"]["path"], "<path>/fixture.wfp")
            self.assertEqual(result["timeline"]["canonical_timeline_count"], 3)
            self.assertEqual(result["timeline"]["standalone_cache"]["exact_copy_count"], 2)
            clip_counts = {
                row["type"]: row["count"] for row in result["timeline"]["clip_types"]
            }
            self.assertEqual(clip_counts, {"4": 2, "6": 1, "7": 1, "16": 1})
            self.assertEqual(result["titles"]["script_buffer_count"], 2)
            self.assertEqual(result["titles"]["declared_size_matches_utf8_plus_one"], 2)
            self.assertEqual(result["titles"]["text_mirror_matches"], 2)
            self.assertEqual(result["effects"][0]["id"], "transform")
            self.assertEqual(result["effects"][0]["count"], 2)
            key_six = next(row for row in result["user_data"] if row["key"] == 6)
            self.assertEqual(key_six["formats"], {"uint32_le": 5})
            self.assertEqual(key_six["matches_containing_timeline"], 5)
            self.assertTrue(result["identifiers"]["media_folders"]["timeline_media_id_resolves"])

            title_text_field = next(
                field
                for field in result["titles"]["schema"]["fields"]
                if field["path"] == "$.Text"
            )
            self.assertEqual(title_text_field["examples"], ["<text:11 chars>", "<text:17 chars>"])

    def test_map_preserves_duplicate_json_keys_for_schema_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_project(root / "source.wfp")
            project = root / "duplicates.wfp"
            with zipfile.ZipFile(source, "r") as before, zipfile.ZipFile(
                project, "w", compression=zipfile.ZIP_DEFLATED
            ) as after:
                for info in before.infolist():
                    after.writestr(info, before.read(info))
                after.writestr(
                    "ProjectFolder/Medias/medias_info.json",
                    '{"media_structure":{"media_item":"one","media_item":"two"}}',
                )

            result = map_project(project)

            duplicates = result["documents"]["medias_info"]["duplicate_keys"]
            self.assertEqual(
                duplicates,
                [
                    {
                        "path": "$.media_structure",
                        "key": "media_item",
                        "objects": 1,
                        "extra_occurrences": 1,
                        "max_per_object": 2,
                    }
                ],
            )

    def test_map_normalizes_braced_uuid_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_project(Path(temporary) / "markers.wfp")
            opaque = "{FA6C57DC-8387-4d6e-BB02-3D1391FF78C6}"
            with zipfile.ZipFile(project, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "ProjectFolder/Medias/MAIN/extra.json",
                    json.dumps(
                        {"allMarkersInfo": {opaque: [{"position": 10, "color": 2}]}},
                        separators=(",", ":"),
                    ),
                )

            result = map_project(project)
            fields = [field["path"] for field in result["documents"]["timeline_extra"]["fields"]]

            self.assertIn("$.allMarkersInfo.{id}[].position", fields)
            self.assertFalse(any(opaque in field for field in fields))

    def test_map_profiles_embedded_json_and_xml_without_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_payloads(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][0]
                clip["intelligenceSegmentSmartRemoveSerializeToJson"] = json.dumps(
                    {"enable": True, "fr": {"num": 30, "den": 1}},
                    separators=(",", ":"),
                )
                clip["animation"] = {
                    "charXml": '<AnimationParam MotionID="private-value"><AnimationConfig Property="x"/></AnimationParam>'
                }
                clip["hdr_color"] = '{"primaryColorAdjust":{"temperature":0.0}}\x00'

            project = _rewrite_main_timeline(source, root / "payloads.wfp", add_payloads)
            result = map_project(project)
            payloads = {
                (row["field"], row["format"]): row for row in result["serialized_payloads"]
            }

            embedded = payloads[("intelligenceSegmentSmartRemoveSerializeToJson", "json")]
            self.assertEqual(embedded["count"], 1)
            fields = [field["path"] for field in embedded["schema"]["fields"]]
            self.assertIn("$.fr.num", fields)
            self.assertFalse(any("examples" in field for field in embedded["schema"]["fields"]))
            xml = payloads[("animation.charXml", "xml")]
            self.assertEqual(xml["tags"], {"AnimationConfig": 1, "AnimationParam": 1})
            self.assertEqual(xml["attributes"], {"MotionID": 1, "Property": 1})
            self.assertNotIn("private-value", json.dumps(result["serialized_payloads"]))
            null_json = payloads[("hdr_color", "json")]
            self.assertEqual(null_json["count"], 1)
            self.assertEqual(null_json["null_terminated_count"], 1)

            def break_payload(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][0]
                clip["badPayload"] = "{broken"

            broken = _rewrite_main_timeline(project, root / "broken.wfp", break_payload)
            broken_map = map_project(broken)
            self.assertEqual(
                broken_map["serialized_payload_errors"],
                [
                    {
                        "field": "badPayload",
                        "format": "json",
                        "count": 1,
                        "clip_types": {"16": 1},
                    }
                ],
            )
            evaluation = evaluate_project(broken)
            probe = next(
                item
                for item in evaluation["probes"]
                if item["name"] == "serialized_payload_candidates_parse"
            )
            self.assertFalse(probe["passed"])
            self.assertFalse(probe["required"])
            self.assertTrue(evaluation["valid"])

    def test_map_profiles_rotation_and_linked_transition_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_effect_and_transitions(timeline):
                current = next(
                    item for item in timeline["timelineInfos"] if item["timelineId"] == 1
                )
                clips = [clip for track in current["trackInfos"] for clip in track["clipList"]]
                visual = next(clip for clip in clips if clip["type"] == 6)
                audio = next(clip for clip in clips if clip["type"] == 16)
                visual["effectChainList"] = [
                    {
                        "name": "Basic",
                        "effectList": [
                            {
                                "display": "transform",
                                "id": "video/effect/transform",
                                "thisUId": "effect-rotation",
                                "paramList": [
                                    {
                                        "name": "EnableTransform",
                                        "fxParam": {"paramType": 5, "unValue": 1},
                                    },
                                    {
                                        "name": "Rotation",
                                        "fxParam": {"paramType": 3, "unValue": 10.0},
                                    },
                                ],
                            }
                        ],
                    }
                ]
                visual["postTransition"] = {
                    "display": "Dissolve",
                    "id": "2981D185-D52E-44f4-ABD5-3CE83890E32E",
                    "thisUId": "visual-transition",
                    "tlBegin": 20_000_000,
                    "tlEnd": 30_000_000,
                    "type": 5,
                }
                audio["postTransition"] = {
                    "display": "audio fade",
                    "id": "audio/blender/transition-fade",
                    "includeTrimFrames": False,
                    "thisUId": "audio-transition",
                    "tlBegin": 20_000_000,
                    "tlEnd": 30_000_000,
                    "type": 5,
                }

            project = _rewrite_main_timeline(
                source,
                root / "effect-transition.wfp",
                add_effect_and_transitions,
            )

            result = map_project(project)

            transform = next(
                effect for effect in result["effects"] if effect["id"] == "video/effect/transform"
            )
            rotation_value = next(
                parameter
                for parameter in transform["parameters"]
                if parameter["name"] == "Rotation"
                and parameter["value_path"] == "fxParam.unValue"
            )
            self.assertEqual(rotation_value["numeric_range"], [10.0, 10.0])
            transitions = {transition["display"]: transition for transition in result["transitions"]}
            self.assertEqual(
                transitions["Dissolve"]["duration_ticks"]["numeric_range"],
                [10_000_000, 10_000_000],
            )
            self.assertEqual(
                transitions["audio fade"]["duration_ticks"]["numeric_range"],
                [10_000_000, 10_000_000],
            )
            evaluation = evaluate_project(project)
            transition_probe = next(
                probe for probe in evaluation["probes"] if probe["name"] == "transition_ranges_valid"
            )
            self.assertTrue(transition_probe["passed"], evaluation)

    def test_format_eval_rejects_non_positive_transition_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_zero_length_transition(timeline):
                current = next(
                    item for item in timeline["timelineInfos"] if item["timelineId"] == 1
                )
                visual = next(
                    clip
                    for track in current["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                visual["postTransition"] = {
                    "display": "Dissolve",
                    "id": "2981D185-D52E-44f4-ABD5-3CE83890E32E",
                    "thisUId": "zero-length-transition",
                    "tlBegin": 30_000_000,
                    "tlEnd": 30_000_000,
                    "type": 5,
                }

            project = _rewrite_main_timeline(
                source,
                root / "invalid-transition.wfp",
                add_zero_length_transition,
            )

            result = evaluate_project(project)

            self.assertFalse(result["valid"], result)
            transition_probe = next(
                probe for probe in result["probes"] if probe["name"] == "transition_ranges_valid"
            )
            self.assertFalse(transition_probe["passed"])

    def test_format_eval_rejects_mismatched_title_text_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_project(root / "source.wfp")
            project = root / "mismatched-title.wfp"
            with zipfile.ZipFile(source, "r") as before, zipfile.ZipFile(
                project, "w", compression=zipfile.ZIP_DEFLATED
            ) as after:
                for info in before.infolist():
                    data = before.read(info)
                    if info.filename.endswith("/timeline.wesproj"):
                        timeline = json.loads(data)
                        title_clip = next(
                            clip
                            for timeline_info in timeline["timelineInfos"]
                            for track in timeline_info["trackInfos"]
                            for clip in track["clipList"]
                            if "scriptBuf" in clip
                        )
                        script = json.loads(title_clip["scriptBuf"])
                        script["TextData"][0]["CharData"] = "Different mirrored text"
                        title_clip["scriptBuf"] = json.dumps(script)
                        title_clip["scriptBufSize"] = len(title_clip["scriptBuf"].encode("utf-8")) + 1
                        data = json.dumps(timeline).encode("utf-8")
                    after.writestr(info, data)

            result = evaluate_project(project)

            self.assertFalse(result["valid"], result)
            text_probe = next(
                probe for probe in result["probes"] if probe["name"] == "title_text_mirrors_match"
            )
            self.assertFalse(text_probe["passed"])

    def test_inspect_and_titles_decode_nested_script_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_project(Path(temporary) / "fixture.wfp")
            inspection = inspect_project(project)
            titles = list_titles(project)

            self.assertEqual(inspection["project"]["name"], "Fixture")
            self.assertEqual(inspection["project"]["duration_seconds"], 3.0)
            self.assertEqual(inspection["resources"][0]["filename"], "source.mp4")
            self.assertEqual(inspection["main_timeline"]["nested_placements"][0]["timeline_id"], 2)
            self.assertEqual(titles[0]["text"], "Hello")
            self.assertEqual(titles[0]["font"], "Bebas Neue")
            self.assertEqual(titles[0]["animation_id"], 274)

    def test_validate_accepts_synthetic_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_project(Path(temporary) / "fixture.wfp")
            result = validate_project(project)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["details"]["title_count"], 1)

    def test_diff_expands_script_buffer_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = write_project(root / "before.wfp", title="Before")
            after = write_project(root / "after.wfp", title="After")
            result = diff_projects(before, after, member_filter="timeline.wesproj")
            text_changes = [
                change
                for change in result["json_changes"]
                if change["path"].endswith("scriptBuf.$embedded_json.Text")
            ]
            self.assertEqual(len(text_changes), 1)
            self.assertEqual(text_changes[0]["before"], "Before")
            self.assertEqual(text_changes[0]["after"], "After")

    def test_unpack_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "unsafe.wfp"
            with zipfile.ZipFile(project, "w") as archive:
                archive.writestr("../escape.txt", "nope")
            with WfpArchive(project) as archive:
                with self.assertRaises(WfpError):
                    archive.safe_extract(root / "output")
            self.assertFalse((root / "escape.txt").exists())

    def test_clone_title_cards_writes_a_new_graph_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            output = root / "completed.wfp"
            source_before = source.read_bytes()
            cards = [
                {
                    "start_ticks": 50_000_000,
                    "heading": "2. Next Tip",
                    "subheading": "A useful subtitle",
                    "heading_font_size": 72,
                    "heading_scale_x": 0.7,
                    "subheading_font_size": 32,
                    "subheading_scale_x": 0.45,
                }
            ]

            result = clone_title_cards(
                source,
                output,
                template_timeline_id=10,
                cards=cards,
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(output.is_file())
            self.assertEqual(result["created_cards"][0]["timeline_id"], 13)

            titles = list_titles(output)
            self.assertIn("2. Next Tip", [title["text"] for title in titles])
            with WfpArchive(output) as archive:
                main = archive.main_timeline()
                created_title_clips = [
                    clip
                    for timeline in main["timelineInfos"]
                    for track in timeline["trackInfos"]
                    for clip in track["clipList"]
                    if clip.get("type") == 4
                    and json.loads(clip["scriptBuf"]).get("Text") == "2. Next Tip"
                ]
                self.assertEqual(len(created_title_clips), 1)
                created_script = json.loads(created_title_clips[0]["scriptBuf"])
                self.assertEqual(created_script["TextData"][0]["CharData"], "2. Next Tip")
                self.assertEqual(
                    created_title_clips[0]["scriptBufSize"],
                    len(created_title_clips[0]["scriptBuf"].encode("utf-8")) + 1,
                )
                current = next(
                    timeline
                    for timeline in main["timelineInfos"]
                    if timeline["timelineId"] == main["currentTimelineId"]
                )
                placements = [
                    clip
                    for track in current["trackInfos"]
                    for clip in track["clipList"]
                    if clip.get("timelineId") == 13
                ]
                self.assertEqual(len(placements), 2)
                self.assertEqual({clip["tlBegin"] for clip in placements}, {50_000_000})
                self.assertEqual(len(archive.timeline_members()), 3)

            with zipfile.ZipFile(output) as archive:
                project_info = archive.read("ProjectFolder/project_info.json")
            decoded_project_info = json.loads(project_info)
            self.assertEqual(decoded_project_info["project_file_name"], "completed")
            self.assertEqual(decoded_project_info["proj_zip_save_path"], str(output.resolve()))
            self.assertEqual(decoded_project_info["project_date_modify"], 1)
            self.assertEqual(decoded_project_info["project_source"], "fixture-integrity-token")

            audit = audit_title_card_copy(source, output)
            self.assertTrue(audit["valid"], audit)
            self.assertEqual(audit["details"]["new_card_count"], 1)

            output_before = output.read_bytes()
            with self.assertRaises(WfpError):
                clone_title_cards(source, output, template_timeline_id=10, cards=cards)
            self.assertEqual(output.read_bytes(), output_before)

            broken = root / "broken-date.wfp"
            with zipfile.ZipFile(output, "r") as source_archive, zipfile.ZipFile(broken, "w") as destination:
                for info in source_archive.infolist():
                    data = source_archive.read(info)
                    if info.filename == "ProjectFolder/project_info.json":
                        project_info = json.loads(data)
                        project_info["project_date_modify"] += 1
                        data = json.dumps(project_info, indent=4).encode("utf-8")
                    destination.writestr(info, data)

            broken_audit = audit_title_card_copy(source, broken)
            self.assertFalse(broken_audit["valid"], broken_audit)
            self.assertTrue(
                any("project_date_modify" in error for error in broken_audit["errors"]),
                broken_audit,
            )

    def test_clone_title_cards_removes_output_when_source_aware_audit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            output = root / "rejected.wfp"
            cards = [
                {
                    "start_ticks": 50_000_000,
                    "heading": "2. Next Tip",
                    "subheading": "A useful subtitle",
                    "heading_font_size": 72,
                    "heading_scale_x": 0.7,
                    "subheading_font_size": 32,
                    "subheading_scale_x": 0.45,
                }
            ]

            with patch(
                "filmora_wfp.title_cards.audit_title_card_copy",
                return_value={"valid": False, "errors": ["controlled audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled audit failure"):
                    clone_title_cards(source, output, template_timeline_id=10, cards=cards)

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
