from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from filmora_wfp import (
    WfpError,
    audit_rough_cut_project,
    inspect_rough_cut_seed_shape,
    preflight_rough_cut_project,
    project_sha256,
    write_rough_cut_project,
)
from filmora_wfp.cli import main as cli_main
from tests.helpers import write_rough_cut_seed


def _plan() -> dict:
    return {
        "schema_version": 1,
        "source": {"filename": "camera.mp4", "duration_seconds": 5.0},
        "keep_ranges": [
            {"start": 0.0, "end": 1.01},
            {"start": 2.01, "end": 3.0},
            {"start": 4.0, "end": 5.0},
        ],
    }


def _timeline(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as archive:
        return json.loads(archive.read("ProjectFolder/Medias/MAIN/timeline.wesproj"))


class RoughCutWfpTest(unittest.TestCase):
    def test_seed_inspection_accepts_current_filmora_rounding_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            seed = write_rough_cut_seed(Path(temporary) / "seed.wfp")

            result = inspect_rough_cut_seed_shape(seed)

            self.assertTrue(result["valid_seed_shape"], result)
            self.assertTrue(result["filmora_writer_available"])
            self.assertEqual(result["seed"]["source_filename"], "camera.mp4")
            self.assertEqual(result["source"]["filmora_version"], "15.7.3.12221")

    def test_preflight_quantizes_outward_and_builds_gapless_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            seed = write_rough_cut_seed(Path(temporary) / "seed.wfp")

            result = preflight_rough_cut_project(seed, _plan())

            self.assertEqual(result["output_pair_count"], 3)
            self.assertEqual(
                result["pairs"],
                [
                    {
                        "source_start_ticks": 0,
                        "source_end_ticks": 10_333_333,
                        "timeline_start_ticks": 0,
                        "timeline_end_ticks": 10_333_333,
                    },
                    {
                        "source_start_ticks": 20_000_000,
                        "source_end_ticks": 30_000_000,
                        "timeline_start_ticks": 10_333_333,
                        "timeline_end_ticks": 20_333_333,
                    },
                    {
                        "source_start_ticks": 40_000_000,
                        "source_end_ticks": 50_000_000,
                        "timeline_start_ticks": 20_333_333,
                        "timeline_end_ticks": 30_333_333,
                    },
                ],
            )

    def test_writer_creates_audited_linked_pairs_and_preserves_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = write_rough_cut_seed(root / "seed.wfp")
            before = seed.read_bytes()
            output = root / "generated.wfp"

            result = write_rough_cut_project(
                seed,
                output,
                _plan(),
                expected_source_sha256=project_sha256(seed),
            )

            self.assertEqual(seed.read_bytes(), before)
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["output_pair_count"], 3)
            self.assertEqual(result["output_duration_ticks"], 30_333_333)
            document = _timeline(output)
            tracks = document["timelineInfos"][0]["trackInfos"]
            audio = tracks[1]["clipList"]
            video = tracks[2]["clipList"]
            self.assertEqual(len(audio), 3)
            self.assertEqual(len(video), 3)
            self.assertEqual(
                [(clip["tlBegin"], clip["tlEnd"]) for clip in video],
                [(0, 10_333_333), (10_333_333, 20_333_333), (20_333_333, 30_333_333)],
            )
            self.assertEqual(
                [(clip["inPoint"], clip["outPoint"]) for clip in video],
                [(0, 10_333_333), (20_000_000, 30_000_000), (40_000_000, 50_000_000)],
            )
            self.assertTrue(audit_rough_cut_project(seed, output, _plan())["valid"])
            with zipfile.ZipFile(output, "r") as archive:
                self.assertEqual(
                    json.loads(archive.read("ProjectFolder/Medias/MAIN/extra.json")),
                    {"unchanged": True},
                )
                project_info = json.loads(archive.read("ProjectFolder/project_info.json"))
            self.assertEqual(project_info["project_file_name"], "generated")
            self.assertEqual(project_info["project_timeline_duration"], 30_333_333)
            self.assertEqual(project_info["project_source"], "opaque-source-token")
            self.assertEqual(project_info["project_date_modify"], 123456789)

    def test_writer_rejects_mismatched_source_stale_hash_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = write_rough_cut_seed(root / "seed.wfp")
            wrong = _plan()
            wrong["source"] = dict(wrong["source"])
            wrong["source"]["filename"] = "other.mp4"
            with self.assertRaisesRegex(WfpError, "does not match the seed media"):
                preflight_rough_cut_project(seed, wrong)
            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                write_rough_cut_project(
                    seed,
                    root / "stale.wfp",
                    _plan(),
                    expected_source_sha256="0" * 64,
                )
            existing = root / "existing.wfp"
            existing.write_bytes(b"do not replace")
            with self.assertRaisesRegex(WfpError, "Refusing to overwrite"):
                write_rough_cut_project(seed, existing, _plan())
            self.assertEqual(existing.read_bytes(), b"do not replace")

    def test_cli_writes_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = write_rough_cut_seed(root / "seed.wfp")
            plan = root / "plan.json"
            plan.write_text(json.dumps(_plan()), encoding="utf-8")
            output = root / "cli-output.wfp"
            stdout = StringIO()

            with redirect_stdout(stdout):
                status = cli_main(
                    ["rough-cut-project", str(seed), str(plan), str(output)]
                )

            self.assertEqual(status, 0)
            self.assertTrue(output.is_file())
            self.assertIn("Linked A/V pairs: 3", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
