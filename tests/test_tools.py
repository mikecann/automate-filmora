from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from filmora_wfp import (
    WfpArchive,
    WfpError,
    clone_title_cards,
    diff_projects,
    inspect_project,
    list_titles,
    validate_project,
)

from tests.helpers import write_cloneable_title_project, write_project


class FilmoraProjectToolsTest(unittest.TestCase):
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
            self.assertEqual(json.loads(project_info)["proj_zip_save_path"], str(output.resolve()))

            output_before = output.read_bytes()
            with self.assertRaises(WfpError):
                clone_title_cards(source, output, template_timeline_id=10, cards=cards)
            self.assertEqual(output.read_bytes(), output_before)


if __name__ == "__main__":
    unittest.main()
