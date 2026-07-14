from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from filmora_wfp import WfpArchive, WfpError, diff_projects, inspect_project, list_titles, validate_project

from tests.helpers import write_project


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


if __name__ == "__main__":
    unittest.main()
