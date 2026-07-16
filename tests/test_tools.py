from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from filmora_wfp import (
    WfpArchive,
    WfpError,
    audit_title_card_copy,
    clone_title_cards,
    diff_projects,
    evaluate_project,
    inspect_project,
    list_titles,
    map_project,
    validate_project,
)

from tests.helpers import write_cloneable_title_project, write_project


class FilmoraProjectToolsTest(unittest.TestCase):
    def test_format_eval_checks_graph_cache_and_title_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = write_cloneable_title_project(Path(temporary) / "fixture.wfp")

            result = evaluate_project(project)

            self.assertTrue(result["valid"], result)
            self.assertTrue(all(probe["passed"] for probe in result["probes"]), result)
            self.assertEqual(result["observations"]["standalone_only_timelines"], 0)

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
