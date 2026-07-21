from __future__ import annotations

import base64
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
    SplitLinkedAvPairOperation,
    WfpArchive,
    WfpError,
    apply_edit_plan,
    audit_clip_fade_in_copy,
    audit_clip_anchor_copy,
    audit_clip_corner_radius_copy,
    audit_clip_fade_out_copy,
    audit_clip_position_copy,
    audit_clip_scale_copy,
    audit_clip_horizontal_flip_copy,
    audit_clip_vertical_flip_copy,
    audit_linked_av_split_copy,
    audit_clip_volume_gain_copy,
    audit_clip_lut_copy,
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
    move_linked_av_pair,
    normalized_position,
    normalized_anchor,
    preflight_linked_av_end_trim,
    preflight_linked_av_move,
    preflight_linked_av_start_trim,
    preflight_clip_fade_in,
    preflight_clip_anchor,
    preflight_clip_corner_radius,
    preflight_clip_fade_out,
    preflight_clip_position,
    preflight_clip_opacity,
    preflight_clip_audio_balance,
    preflight_clip_blend_mode,
    preflight_clip_hsl,
    preflight_clip_equalizer,
    preflight_clip_stabilization,
    preflight_clip_video_denoise,
    preflight_clip_lut,
    preflight_clip_scale,
    preflight_clip_horizontal_flip,
    preflight_clip_vertical_flip,
    preflight_clip_volume_gain,
    project_sha256,
    replace_clip_rotation,
    replace_clip_anchor,
    replace_clip_corner_radius,
    replace_clip_fade_in,
    replace_clip_fade_out,
    replace_clip_position,
    replace_clip_scale,
    replace_clip_horizontal_flip,
    replace_clip_vertical_flip,
    replace_clip_volume_gain,
    replace_clip_hsl,
    replace_clip_equalizer,
    replace_clip_stabilization,
    replace_clip_video_denoise,
    replace_clip_lut,
    replace_clip_blend_mode,
    replace_linked_transition_duration,
    replace_title_text,
    remove_linked_transition,
    survey_projects,
    split_linked_av_pair,
    trim_linked_av_pair_end,
    trim_linked_av_pair_start,
    validate_project,
)
from filmora_wfp.cli import main as cli_main
from filmora_wfp.feature_coverage import feature_coverage

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
    def test_feature_coverage_has_unique_curated_rows_and_status_totals(self) -> None:
        result = feature_coverage()
        features = result["features"]
        identities = [(item["area"], item["feature"]) for item in features]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(result["summary"]["total"], len(features))
        self.assertEqual(
            sum(result["summary"]["by_status"].values()), len(features)
        )
        self.assertIn("writable", result["summary"]["by_status"])
        self.assertIn("open", result["summary"]["by_status"])
        track_row = next(
            item for item in features
            if item["area"] == "project" and item["feature"] == "track creation and reorder"
        )
        self.assertEqual(track_row["status"], "partial")
        self.assertIn("Track Manager insertion", track_row["evidence"])
        lut_row = next(
            item for item in features
            if item["area"] == "color" and item["feature"] == "LUT selection and intensity"
        )
        self.assertEqual(lut_row["status"], "partial")
        self.assertIn("alpha", lut_row["evidence"])
        wb_row = next(
            item for item in features
            if item["area"] == "color" and item["feature"] == "Auto Color and white balance picker"
        )
        self.assertEqual(wb_row["status"], "partial")
        self.assertIn("Auto White Balance", wb_row["evidence"])
        unlink_row = next(
            item for item in features
            if item["area"] == "timeline" and item["feature"] == "unlink and relink clips"
        )
        self.assertEqual(unlink_row["status"], "partial")
        self.assertIn("opaque", unlink_row["evidence"])

    def test_feature_coverage_cli_filters_json_without_changing_totals(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["feature-coverage", "--status", "open", "--json"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["filter"], "open")
        self.assertTrue(result["features"])
        self.assertTrue(all(item["status"] == "open" for item in result["features"]))
        self.assertGreater(result["summary"]["total"], len(result["features"]))

    def test_v3_edit_plan_discovers_and_applies_rotation_and_transition_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_targets(timeline):
                audio = {
                    "type": 2,
                    "thisUId": "audio-source-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 70_000_000,
                    "inPoint": 0,
                    "outPoint": 30_000_000,
                    "postTransition": {
                        "id": "audio/blender/transition-fade",
                        "display": "audio fade",
                        "thisUId": "audio-transition",
                        "type": 5,
                        "tlBegin": 50_000_000,
                        "tlEnd": 70_000_000,
                    },
                }
                video = {
                    "type": 1,
                    "thisUId": "video-source-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 70_000_000,
                    "inPoint": 0,
                    "outPoint": 30_000_000,
                    "effectChainList": [
                        {
                            "effectList": [
                                {
                                    "id": "video/effect/transform",
                                    "paramList": [
                                        {"name": "Rotation", "fxParam": {"unValue": 10.0}}
                                    ],
                                }
                            ]
                        }
                    ],
                    "postTransition": {
                        "id": "2981D185-D52E-44f4-ABD5-3CE83890E32E",
                        "display": "Dissolve",
                        "thisUId": "video-transition",
                        "type": 5,
                        "tlBegin": 50_000_000,
                        "tlEnd": 70_000_000,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(audio)
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(video)

            source = _rewrite_main_timeline(base, root / "source.wfp", add_targets)
            digest = project_sha256(source)
            targets = list_edit_targets(source)
            self.assertEqual(targets["api_version"], 10)
            self.assertEqual(
                targets["rotation_targets"][0]["selector"],
                {"clip_uid": "video-source-clip", "rotation": "10.0"},
            )
            transition_selector = {
                "video_clip_uid": "video-source-clip",
                "audio_clip_uid": "audio-source-clip",
                "duration_ticks": 20_000_000,
            }
            self.assertEqual(
                targets["linked_transition_targets"][0]["selector"],
                transition_selector,
            )

            rotation_plan = {
                "schema_version": 3,
                "source": {"sha256": digest},
                "operations": [
                    {
                        "op": "replace_clip_rotation",
                        "target": {"clip_uid": "video-source-clip", "rotation": "10.0"},
                        "new_rotation": "20.0",
                    }
                ],
            }
            rotation_explanation = explain_edit_plan(source, rotation_plan)
            self.assertFalse(rotation_explanation["writes_performed"])
            self.assertEqual(rotation_explanation["operations"][0]["new_rotation"], "20.0")
            rotation_result = apply_edit_plan(
                source, root / "rotation-output.wfp", rotation_plan
            )
            self.assertTrue(rotation_result["verification"]["source_aware_audit_valid"])

            duration_plan = {
                "schema_version": 3,
                "source": {"sha256": digest},
                "operations": [
                    {
                        "op": "replace_linked_transition_duration",
                        "target": transition_selector,
                        "new_duration_ticks": 10_000_000,
                    }
                ],
            }
            duration_explanation = explain_edit_plan(source, duration_plan)
            self.assertEqual(
                duration_explanation["operations"][0]["resolved_new_tl_begin"],
                60_000_000,
            )
            duration_result = apply_edit_plan(
                source, root / "duration-output.wfp", duration_plan
            )
            self.assertTrue(duration_result["verification"]["source_aware_audit_valid"])
            too_long_plan = dict(duration_plan)
            too_long_plan["operations"] = [dict(duration_plan["operations"][0])]
            too_long_plan["operations"][0]["new_duration_ticks"] = 40_000_000
            with self.assertRaisesRegex(WfpError, "begins before its linked clips"):
                explain_edit_plan(source, too_long_plan)

            removal_plan = {
                "schema_version": 3,
                "source": {"sha256": digest},
                "operations": [{"op": "remove_linked_transition", "target": transition_selector}],
            }
            removal_result = apply_edit_plan(
                source, root / "removal-output.wfp", removal_plan
            )
            self.assertTrue(removal_result["verification"]["source_aware_audit_valid"])

            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(
                    {
                        "schema_version": 2,
                        "source": {"sha256": digest},
                        "operations": rotation_plan["operations"],
                    }
                )

    def test_linked_transition_duration_and_removal_change_only_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_linked_transition(timeline):
                audio = {
                    "type": 2,
                    "thisUId": "audio-source-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 70_000_000,
                    "inPoint": 0,
                    "outPoint": 30_000_000,
                    "postTransition": {
                        "id": "audio/blender/transition-fade",
                        "display": "audio fade",
                        "thisUId": "audio-transition",
                        "type": 5,
                        "tlBegin": 50_000_000,
                        "tlEnd": 70_000_000,
                    },
                }
                video = {
                    "type": 1,
                    "thisUId": "video-source-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 70_000_000,
                    "inPoint": 0,
                    "outPoint": 30_000_000,
                    "postTransition": {
                        "id": "2981D185-D52E-44f4-ABD5-3CE83890E32E",
                        "display": "Dissolve",
                        "thisUId": "video-transition",
                        "type": 5,
                        "tlBegin": 50_000_000,
                        "tlEnd": 70_000_000,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(audio)
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(video)

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_transition)
            source_before = source.read_bytes()
            duration_output = root / "duration.wfp"
            duration_result = replace_linked_transition_duration(
                source,
                duration_output,
                video_clip_uid="video-source-clip",
                audio_clip_uid="audio-source-clip",
                old_duration_ticks=20_000_000,
                new_duration_ticks=10_000_000,
                expected_source_sha256=project_sha256(source),
            )
            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(duration_result["audit"]["valid"], duration_result)
            duration_changes = diff_projects(source, duration_output)["json_changes"]
            self.assertEqual(len(duration_changes), 2)
            self.assertTrue(
                all(change["path"].endswith(".postTransition.tlBegin") for change in duration_changes)
            )
            self.assertEqual({change["after"] for change in duration_changes}, {60_000_000})

            removal_output = root / "removed.wfp"
            removal_result = remove_linked_transition(
                source,
                removal_output,
                video_clip_uid="video-source-clip",
                audio_clip_uid="audio-source-clip",
                expected_duration_ticks=20_000_000,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(removal_result["audit"]["valid"], removal_result)
            removal_changes = diff_projects(source, removal_output)["json_changes"]
            self.assertEqual(len(removal_changes), 2)
            self.assertTrue(
                all(
                    change["kind"] == "removed"
                    and change["path"].endswith(".postTransition")
                    for change in removal_changes
                )
            )
            with self.assertRaisesRegex(WfpError, "begins before its linked clips"):
                replace_linked_transition_duration(
                    source,
                    root / "too-long.wfp",
                    video_clip_uid="video-source-clip",
                    audio_clip_uid="audio-source-clip",
                    old_duration_ticks=20_000_000,
                    new_duration_ticks=40_000_000,
                )

    def test_linked_transition_writer_rejects_partial_or_stale_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_partial_pair(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "video-source-clip",
                        "postTransition": {
                            "id": "2981D185-D52E-44f4-ABD5-3CE83890E32E",
                            "tlBegin": 50_000_000,
                            "tlEnd": 70_000_000,
                        },
                    }
                )

            partial = _rewrite_main_timeline(base, root / "partial.wfp", add_partial_pair)
            with self.assertRaisesRegex(WfpError, "resolve together"):
                remove_linked_transition(
                    partial,
                    root / "output.wfp",
                    video_clip_uid="video-source-clip",
                    audio_clip_uid="missing-audio",
                    expected_duration_ticks=20_000_000,
                )

    def test_linked_av_move_changes_only_four_timeline_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "linked-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "linked-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            with self.assertRaisesRegex(WfpError, "overlaps another clip"):
                preflight_linked_av_move(
                    source,
                    video_clip_uid="linked-video",
                    audio_clip_uid="linked-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    new_start_ticks=20_000_000,
                )
            with self.assertRaisesRegex(WfpError, "extend the declared project duration"):
                preflight_linked_av_move(
                    source,
                    video_clip_uid="linked-video",
                    audio_clip_uid="linked-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    new_start_ticks=90_000_000,
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "linked-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "linked-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            source_before = source.read_bytes()
            output = root / "moved.wfp"
            preflight = preflight_linked_av_move(
                source,
                video_clip_uid="linked-video",
                audio_clip_uid="linked-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                new_start_ticks=70_000_000,
            )
            self.assertEqual(preflight["new_end_ticks"], 90_000_000)

            result = move_linked_av_pair(
                source,
                output,
                video_clip_uid="linked-video",
                audio_clip_uid="linked-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                new_start_ticks=70_000_000,
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["audit"]["valid"], result)
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 4)
            self.assertEqual(
                {change["path"].rsplit(".", 1)[-1] for change in changes},
                {"tlBegin", "tlEnd"},
            )
            self.assertEqual(
                sorted(change["after"] for change in changes),
                [70_000_000, 70_000_000, 90_000_000, 90_000_000],
            )

    def test_linked_av_move_rejects_overlap_and_duration_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )

    def test_linked_av_end_trim_changes_only_six_end_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            speed_param = json.dumps(
                {
                    "Version": 3,
                    "ParameterType": 0,
                    "keyframeSets": [
                        {"_time": 0.0, "_value": 1.0},
                        {"_time": 2.0, "_value": 1.0},
                    ],
                    "_totalTime": 2.0,
                },
                separators=(",", ":"),
            )

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                    "speed": {
                        "offset": 0.0,
                        "offsetEnd": 2.0,
                        "reverse": False,
                        "speedParam": speed_param,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "trim-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "trim-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            output = root / "trimmed.wfp"
            result = trim_linked_av_pair_end(
                source,
                output,
                video_clip_uid="trim-video",
                audio_clip_uid="trim-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                new_end_ticks=50_000_000,
                expected_source_sha256=project_sha256(source),
            )

            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["new_out_point"], 10_000_000)
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 6)
            self.assertEqual(
                {change["path"].rsplit(".", 1)[-1] for change in changes},
                {"tlEnd", "outPoint", "offsetEnd"},
            )

    def test_linked_av_end_trim_rejects_non_1x_or_complete_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            variable_speed = json.dumps(
                {
                    "ParameterType": 0,
                    "keyframeSets": [{"_time": 0.0, "_value": 2.0}],
                },
                separators=(",", ":"),
            )

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                    "speed": {
                        "offset": 0.0,
                        "offsetEnd": 2.0,
                        "reverse": False,
                        "speedParam": variable_speed,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "trim-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "trim-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            with self.assertRaisesRegex(WfpError, "1x speed keyframes"):
                preflight_linked_av_end_trim(
                    source,
                    video_clip_uid="trim-video",
                    audio_clip_uid="trim-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    new_end_ticks=50_000_000,
                )
            with self.assertRaisesRegex(WfpError, "shorten the selected positive clip range"):
                preflight_linked_av_end_trim(
                    source,
                    video_clip_uid="trim-video",
                    audio_clip_uid="trim-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    new_end_ticks=40_000_000,
                )
    def test_linked_av_start_trim_changes_only_six_start_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            speed_param = json.dumps(
                {
                    "Version": 3,
                    "ParameterType": 0,
                    "keyframeSets": [
                        {"_time": 0.0, "_value": 1.0},
                        {"_time": 5.0, "_value": 1.0},
                    ],
                    "_totalTime": 5.0,
                },
                separators=(",", ":"),
            )

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 20_000_000,
                    "outPoint": 40_000_000,
                    "speed": {
                        "offset": 2.0,
                        "offsetEnd": 4.0,
                        "reverse": False,
                        "speedParam": speed_param,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "trim-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "trim-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            output = root / "trimmed.wfp"
            result = trim_linked_av_pair_start(
                source,
                output,
                video_clip_uid="trim-video",
                audio_clip_uid="trim-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                new_start_ticks=50_000_000,
                expected_source_sha256=project_sha256(source),
            )

            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["new_in_point"], 30_000_000)
            self.assertEqual(str(result["new_offset"]), "3.0")
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 6)
            self.assertEqual(
                {change["path"].rsplit(".", 1)[-1] for change in changes},
                {"tlBegin", "inPoint", "offset"},
            )
            with self.assertRaisesRegex(WfpError, "shorten the selected positive clip range"):
                preflight_linked_av_start_trim(
                    source,
                    video_clip_uid="trim-video",
                    audio_clip_uid="trim-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    new_start_ticks=60_000_000,
                )

    def test_v4_edit_plan_discovers_explains_and_applies_linked_av_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            speed_param = json.dumps(
                {
                    "Version": 3,
                    "ParameterType": 0,
                    "keyframeSets": [
                        {"_time": 0.0, "_value": 1.0},
                        {"_time": 2.0, "_value": 1.0},
                    ],
                    "_totalTime": 2.0,
                },
                separators=(",", ":"),
            )

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "linked-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "linked-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                    "speed": {
                        "offset": 0.0,
                        "offsetEnd": 2.0,
                        "reverse": False,
                        "speedParam": speed_param,
                    },
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {**common, "type": 2, "thisUId": "linked-audio"}
                )
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {**common, "type": 1, "thisUId": "linked-video"}
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            source_before = source.read_bytes()
            selector = {
                "video_clip_uid": "linked-video",
                "audio_clip_uid": "linked-audio",
                "start_ticks": 40_000_000,
                "end_ticks": 60_000_000,
            }
            targets = list_edit_targets(source)
            self.assertEqual(targets["api_version"], 10)
            self.assertEqual(len(targets["linked_av_targets"]), 1)
            self.assertEqual(targets["linked_av_targets"][0]["selector"], selector)
            self.assertEqual(
                targets["linked_av_targets"][0]["capabilities"],
                [
                    "move_linked_av_pair",
                    "trim_linked_av_pair_start",
                    "trim_linked_av_pair_end",
                ],
            )

            cases = [
                ("move_linked_av_pair", "new_start_ticks", 70_000_000, 4),
                ("trim_linked_av_pair_start", "new_start_ticks", 50_000_000, 6),
                ("trim_linked_av_pair_end", "new_end_ticks", 50_000_000, 6),
            ]
            for operation_name, replacement_field, replacement, change_count in cases:
                plan = {
                    "schema_version": 4,
                    "source": {"sha256": project_sha256(source)},
                    "operations": [
                        {
                            "op": operation_name,
                            "target": selector,
                            replacement_field: replacement,
                        }
                    ],
                }
                explanation = explain_edit_plan(source, plan)
                self.assertEqual(explanation["status"], "ready")
                self.assertFalse(explanation["writes_performed"])
                self.assertEqual(explanation["operations"][0]["op"], operation_name)
                json.dumps(explanation)

                output = root / (operation_name + ".wfp")
                result = apply_edit_plan(source, output, plan)
                self.assertTrue(result["verification"]["source_aware_audit_valid"])
                json.dumps(result)
                self.assertEqual(len(diff_projects(source, output)["json_changes"]), change_count)

            self.assertEqual(source.read_bytes(), source_before)
            rejected = {
                "schema_version": 3,
                "source": {"sha256": project_sha256(source)},
                "operations": [
                    {
                        "op": "move_linked_av_pair",
                        "target": selector,
                        "new_start_ticks": 70_000_000,
                    }
                ],
            }
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(rejected)

    def test_linked_av_split_clones_second_halves_with_fresh_linked_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            speed_param = json.dumps(
                {
                    "Version": 3,
                    "ParameterType": 0,
                    "keyframeSets": [
                        {"_time": 0.0, "_value": 1.0},
                        {"_time": 5.0, "_value": 1.0},
                    ],
                    "_totalTime": 5.0,
                },
                separators=(",", ":"),
            )
            link_text = "11-22-33-44-55-66-47-88-99-AA-BB-CC-DD-EE-FF-00"

            def link_data(length):
                raw = link_text.encode("ascii") + b"\0" * (length - len(link_text))
                return [{"key": 3, "size": length, "data": base64.b64encode(raw).decode("ascii")}]

            def add_linked_pair(timeline):
                timeline["resources"].append(
                    {"sourceUuid": "split-source", "filename": "file:///fixture.mov"}
                )
                common = {
                    "sourceUuid": "split-source",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 20_000_000,
                    "outPoint": 40_000_000,
                    "speed": {
                        "offset": 2.0,
                        "offsetEnd": 4.0,
                        "reverse": False,
                        "speedParam": speed_param,
                    },
                }
                audio = {
                    **common,
                    "type": 2,
                    "thisUId": "split-audio",
                    "effectChainList": [
                        {"effectList": [{"id": "audio/effect/volume", "thisUId": "audio-effect"}]}
                    ],
                    "userData": link_data(47),
                }
                video = {
                    **common,
                    "type": 1,
                    "thisUId": "split-video",
                    "effectChainList": [
                        {"effectList": [{"id": "video/effect/transform", "thisUId": "video-effect"}]}
                    ],
                    "userData": link_data(64),
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(audio)
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(video)

            source = _rewrite_main_timeline(base, root / "source.wfp", add_linked_pair)
            source_before = source.read_bytes()
            output = root / "split.wfp"
            result = split_linked_av_pair(
                source,
                output,
                video_clip_uid="split-video",
                audio_clip_uid="split-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                split_ticks=50_000_000,
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["new_in_point"], 30_000_000)
            self.assertEqual(str(result["new_offset"]), "3.0")
            with WfpArchive(output) as archive:
                timeline = archive.main_timeline()["timelineInfos"][0]
            audio_clips = [clip for clip in timeline["trackInfos"][0]["clipList"] if clip.get("sourceUuid") == "split-source"]
            video_clips = [clip for clip in timeline["trackInfos"][1]["clipList"] if clip.get("sourceUuid") == "split-source"]
            self.assertEqual([(clip["tlBegin"], clip["tlEnd"]) for clip in audio_clips], [(40_000_000, 50_000_000), (50_000_000, 60_000_000)])
            self.assertEqual([(clip["tlBegin"], clip["tlEnd"]) for clip in video_clips], [(40_000_000, 50_000_000), (50_000_000, 60_000_000)])
            new_ids = {audio_clips[1]["thisUId"], video_clips[1]["thisUId"]}
            self.assertTrue(new_ids.isdisjoint({"split-audio", "split-video"}))

            targets = list_edit_targets(source)
            split_target = next(
                target
                for target in targets["linked_av_targets"]
                if target["selector"]["video_clip_uid"] == "split-video"
            )
            self.assertIn("split_linked_av_pair", split_target["capabilities"])
            plan = {
                "schema_version": 5,
                "source": {"sha256": project_sha256(source)},
                "operations": [
                    {
                        "op": "split_linked_av_pair",
                        "target": split_target["selector"],
                        "split_ticks": 50_000_000,
                    }
                ],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertEqual(explanation["api_version"], 10)
            self.assertFalse(explanation["writes_performed"])
            self.assertEqual(explanation["operations"][0]["op"], "split_linked_av_pair")
            self.assertEqual(explanation["operations"][0]["split_ticks"], 50_000_000)

            typed_plan = EditPlan(
                schema_version=5,
                source_sha256=project_sha256(source),
                operations=(
                    SplitLinkedAvPairOperation(
                        operation_id="typed-split",
                        video_clip_uid="split-video",
                        audio_clip_uid="split-audio",
                        old_start_ticks=40_000_000,
                        old_end_ticks=60_000_000,
                        split_ticks=50_000_000,
                    ),
                ),
            )
            self.assertIsInstance(
                load_edit_plan(typed_plan).operations[0], SplitLinkedAvPairOperation
            )

            plan_output = root / "split-plan.wfp"
            plan_result = apply_edit_plan(source, plan_output, plan)
            self.assertTrue(plan_result["verification"]["source_aware_audit_valid"])

            v4_plan = dict(plan)
            v4_plan["schema_version"] = 4
            with self.assertRaisesRegex(WfpError, "requires edit-plan schema version 5"):
                load_edit_plan(v4_plan)

            def invalidate_new_video_id(timeline_document):
                clips = timeline_document["timelineInfos"][0]["trackInfos"][1]["clipList"]
                next(
                    clip
                    for clip in clips
                    if clip.get("sourceUuid") == "split-source"
                    and clip.get("tlBegin") == 50_000_000
                )["thisUId"] = "not-a-canonical-uuid"

            tampered = _rewrite_main_timeline(
                output, root / "tampered.wfp", invalidate_new_video_id
            )
            tampered_audit = audit_linked_av_split_copy(
                source,
                tampered,
                video_clip_uid="split-video",
                audio_clip_uid="split-audio",
                old_start_ticks=40_000_000,
                old_end_ticks=60_000_000,
                split_ticks=50_000_000,
            )
            self.assertFalse(tampered_audit["valid"])
            self.assertTrue(
                any("invalid or reused" in error for error in tampered_audit["errors"]),
                tampered_audit,
            )

            stale = root / "stale.wfp"
            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                split_linked_av_pair(
                    source,
                    stale,
                    video_clip_uid="split-video",
                    audio_clip_uid="split-audio",
                    old_start_ticks=40_000_000,
                    old_end_ticks=60_000_000,
                    split_ticks=50_000_000,
                    expected_source_sha256="0" * 64,
                )
            self.assertFalse(stale.exists())

            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.linked_av_split.audit_linked_av_split_copy",
                return_value={"valid": False, "errors": ["controlled split audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled split audit failure"):
                    split_linked_av_pair(
                        source,
                        rejected,
                        video_clip_uid="split-video",
                        audio_clip_uid="split-audio",
                        old_start_ticks=40_000_000,
                        old_end_ticks=60_000_000,
                        split_ticks=50_000_000,
                    )
            self.assertFalse(rejected.exists())

    def test_replace_existing_clip_rotation_changes_only_selected_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_rotation(timeline):
                clip = {
                    "type": 1,
                    "thisUId": "video-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                }
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(clip)
                clip["effectChainList"] = [
                    {
                        "effectList": [
                            {
                                "id": "video/effect/transform",
                                "thisUId": "rotation-effect",
                                "paramList": [
                                    {"name": "dwValue", "fxParam": {"paramType": 5, "unValue": 1}},
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
                        ]
                    }
                ]

            source = _rewrite_main_timeline(base, root / "source.wfp", add_rotation)
            source_before = source.read_bytes()
            output = root / "output.wfp"
            result = replace_clip_rotation(
                source,
                output,
                clip_uid="video-clip",
                old_rotation="10.0",
                new_rotation="20.0",
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(output.is_file())
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["audit"]["details"]["rotation_occurrences_changed"], 1)
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 1)
            self.assertTrue(changes[0]["path"].endswith(".fxParam.unValue"))
            self.assertEqual(changes[0]["before"], 10.0)
            self.assertEqual(changes[0]["after"], 20.0)

    def test_replace_existing_clip_rotation_rejects_missing_or_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_unrotated_clip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "video-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "inPoint": 0,
                        "outPoint": 20_000_000,
                    }
                )

            source = _rewrite_main_timeline(
                base, root / "source.wfp", add_unrotated_clip
            )
            with self.assertRaisesRegex(WfpError, "exactly one existing Rotation"):
                replace_clip_rotation(
                    source,
                    root / "missing.wfp",
                    clip_uid="video-clip",
                    old_rotation=0,
                    new_rotation=10,
                )

            def add_rotation(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][1]["clipList"][-1]
                clip["effectChainList"] = [
                    {
                        "effectList": [
                            {
                                "id": "video/effect/transform",
                                "paramList": [
                                    {"name": "Rotation", "fxParam": {"unValue": 10.0}}
                                ],
                            }
                        ]
                    }
                ]

            rotated = _rewrite_main_timeline(source, root / "rotated.wfp", add_rotation)
            with self.assertRaisesRegex(WfpError, "does not match"):
                replace_clip_rotation(
                    rotated,
                    root / "stale.wfp",
                    clip_uid="video-clip",
                    old_rotation=5,
                    new_rotation=20,
                )

    def test_replace_existing_clip_position_uses_filmora_pixel_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            old_x, old_y = normalized_position(100, 100, 1920, 1080)

            def add_position(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "video-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [
                            {
                                "effectList": [
                                    {
                                        "id": "video/effect/transform",
                                        "paramList": [
                                            {
                                                "name": "Position_x",
                                                "fxParam": {"paramType": 3, "unValue": float(old_x)},
                                            },
                                            {
                                                "name": "Position_y",
                                                "fxParam": {"paramType": 3, "unValue": float(old_y)},
                                            },
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_position)
            source_before = source.read_bytes()
            output = root / "output.wfp"
            result = replace_clip_position(
                source,
                output,
                clip_uid="video-clip",
                old_position_x=old_x,
                old_position_y=old_y,
                new_x_pixels=200,
                new_y_pixels=-50,
                expected_source_sha256=project_sha256(source),
            )
            new_x, new_y = normalized_position(200, -50, 1920, 1080)

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["new_position_x"], str(new_x))
            self.assertEqual(result["new_position_y"], str(new_y))
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 2)
            self.assertEqual({change["after"] for change in changes}, {float(new_x), float(new_y)})
            self.assertTrue(
                audit_clip_position_copy(
                    source,
                    output,
                    clip_uid="video-clip",
                    old_position_x=old_x,
                    old_position_y=old_y,
                    new_position_x=new_x,
                    new_position_y=new_y,
                )["valid"]
            )
            self.assertEqual(
                preflight_clip_position(
                    source,
                    clip_uid="video-clip",
                    old_position_x=old_x,
                    old_position_y=old_y,
                    new_x_pixels=200,
                    new_y_pixels=-50,
                )["project_width"],
                1920,
            )
            targets = list_edit_targets(source)
            selector = targets["position_targets"][0]["selector"]
            self.assertEqual(
                selector,
                {
                    "clip_uid": "video-clip",
                    "position_x": str(old_x),
                    "position_y": str(old_y),
                },
            )
            plan = {
                "schema_version": 9,
                "source": {"sha256": project_sha256(source)},
                "operations": [{
                    "op": "replace_clip_position",
                    "target": selector,
                    "new_x_pixels": "250",
                    "new_y_pixels": "75",
                }],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertFalse(explanation["writes_performed"])
            self.assertEqual(explanation["operations"][0]["new_x_pixels"], "250")
            plan_output = root / "plan-output.wfp"
            plan_result = apply_edit_plan(source, plan_output, plan)
            self.assertTrue(plan_result["verification"]["source_aware_audit_valid"])
            self.assertEqual(len(diff_projects(source, plan_output)["json_changes"]), 2)

            v8_plan = dict(plan)
            v8_plan["schema_version"] = 8
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(v8_plan)

    def test_replace_existing_uniform_scale_explains_and_applies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_scale(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "scaled-video",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [{"effectList": [{
                            "id": "video/effect/transform",
                            "paramList": [
                                {"name": "Scale_x", "fxParam": {"paramType": 3, "unValue": 60.0}},
                                {"name": "Scale_y", "fxParam": {"paramType": 3, "unValue": 60.0}},
                            ],
                        }]}],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_scale)
            selector = list_edit_targets(source)["scale_targets"][0]["selector"]
            self.assertEqual(selector, {"clip_uid": "scaled-video", "scale_x": "60.0", "scale_y": "60.0"})
            plan = {
                "schema_version": 10,
                "source": {"sha256": project_sha256(source)},
                "operations": [{
                    "op": "replace_clip_scale",
                    "target": selector,
                    "new_scale": "70",
                }],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertFalse(explanation["writes_performed"])
            output = root / "output.wfp"
            result = apply_edit_plan(source, output, plan)
            self.assertTrue(result["verification"]["source_aware_audit_valid"])
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 2)
            self.assertTrue(
                audit_clip_scale_copy(
                    source,
                    output,
                    clip_uid="scaled-video",
                    old_scale_x="60.0",
                    old_scale_y="60.0",
                    new_scale_x="70.0",
                    new_scale_y="70.0",
                )["valid"]
            )
            self.assertEqual(
                preflight_clip_scale(
                    source,
                    clip_uid="scaled-video",
                    old_scale_x="60.0",
                    old_scale_y="60.0",
                    new_scale_x="70",
                    new_scale_y="70",
                )["new_scale_x"],
                "70.0",
            )
            with self.assertRaisesRegex(WfpError, "linked uniform"):
                replace_clip_scale(
                    source,
                    root / "nonuniform.wfp",
                    clip_uid="scaled-video",
                    old_scale_x="60",
                    old_scale_y="60",
                    new_scale_x="70",
                    new_scale_y="80",
                )

    def test_replace_existing_horizontal_flip_is_copy_only_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_flip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "flipped-video",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [{"effectList": [{
                            "id": "video/effect/horizontal_filp",
                            "display": "horizontal_filp",
                            "enable": False,
                            "userData": [
                                {"key": 101, "size": 4, "data": "AAAAAA=="},
                                {"key": 7, "size": 1, "data": "AQ=="},
                            ],
                        }]}],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_flip)
            output = root / "output.wfp"
            preflight = preflight_clip_horizontal_flip(
                source,
                clip_uid="flipped-video",
                old_enabled=False,
                new_enabled=True,
            )
            self.assertEqual(preflight["matching_archive_occurrences"], 1)
            result = replace_clip_horizontal_flip(
                source,
                output,
                clip_uid="flipped-video",
                old_enabled=False,
                new_enabled=True,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertTrue(
                audit_clip_horizontal_flip_copy(
                    source,
                    output,
                    clip_uid="flipped-video",
                    old_enabled=False,
                    new_enabled=True,
                )["valid"]
            )
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 2)
            self.assertTrue(source.exists())

            with self.assertRaisesRegex(WfpError, "must differ"):
                preflight_clip_horizontal_flip(
                    source,
                    clip_uid="flipped-video",
                    old_enabled=False,
                    new_enabled=False,
                )
            with self.assertRaisesRegex(WfpError, "expected False, found True"):
                preflight_clip_horizontal_flip(
                    output,
                    clip_uid="flipped-video",
                    old_enabled=False,
                    new_enabled=True,
                )

    def test_replace_existing_vertical_flip_is_copy_only_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_flip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "vertical-flipped-video",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [{"effectList": [{
                            "id": "video/effect/vertical_filp",
                            "display": "vertical_filp",
                            "enable": False,
                            "userData": [
                                {"key": 101, "size": 4, "data": "AAAAAA=="},
                                {"key": 7, "size": 1, "data": "AQ=="},
                            ],
                        }]}],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_flip)
            output = root / "output.wfp"
            preflight = preflight_clip_vertical_flip(
                source,
                clip_uid="vertical-flipped-video",
                old_enabled=False,
                new_enabled=True,
            )
            self.assertEqual(preflight["matching_archive_occurrences"], 1)
            result = replace_clip_vertical_flip(
                source,
                output,
                clip_uid="vertical-flipped-video",
                old_enabled=False,
                new_enabled=True,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertTrue(
                audit_clip_vertical_flip_copy(
                    source,
                    output,
                    clip_uid="vertical-flipped-video",
                    old_enabled=False,
                    new_enabled=True,
                )["valid"]
            )
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 2)
            self.assertTrue(source.exists())

            restored = root / "restored.wfp"
            restored_result = replace_clip_vertical_flip(
                output,
                restored,
                clip_uid="vertical-flipped-video",
                old_enabled=True,
                new_enabled=False,
                expected_source_sha256=project_sha256(output),
            )
            self.assertTrue(restored_result["audit"]["valid"])
            self.assertEqual(len(diff_projects(output, restored)["json_changes"]), 2)

            with self.assertRaisesRegex(WfpError, "must differ"):
                preflight_clip_vertical_flip(
                    source,
                    clip_uid="vertical-flipped-video",
                    old_enabled=False,
                    new_enabled=False,
                )
            with self.assertRaisesRegex(WfpError, "expected False, found True"):
                preflight_clip_vertical_flip(
                    output,
                    clip_uid="vertical-flipped-video",
                    old_enabled=False,
                    new_enabled=True,
                )

    def test_existing_overlay_opacity_preflight_is_source_aware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_project(root / "base.wfp")
            source = _rewrite_main_timeline(
                base,
                root / "source.wfp",
                lambda timeline: timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][0].update(
                    {"pipBuf": '{"Algorithm":"Bilinear","BlendMode":0,"Opacity":50.0}', "pipBufSize": 58}
                ),
            )
            result = preflight_clip_opacity(
                source, clip_uid="video-clip", old_opacity=50, new_opacity=25
            )
            self.assertEqual(result["matching_archive_occurrences"], 1)
            with self.assertRaisesRegex(WfpError, "does not match"):
                preflight_clip_opacity(
                    source, clip_uid="video-clip", old_opacity=40, new_opacity=25
                )

    def test_existing_audio_balance_preflight_normalizes_ui_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_project(root / "base.wfp")
            def add_audio_balance(timeline):
                timeline["timelineInfos"][0]["trackInfos"].append({
                    "trackType": 1,
                    "trackTag": 2,
                    "clipList": [{
                        "type": 2,
                        "thisUId": "audio-clip",
                        "effectChainList": [{
                            "effectList": [{
                                "id": "audio/effect/volume",
                                "paramList": [{
                                    "name": "Balance",
                                    "fxParam": {"paramType": 2, "unValue": 0.625},
                                }],
                            }],
                        }],
                    }],
                })

            source = _rewrite_main_timeline(base, root / "source.wfp", add_audio_balance)
            result = preflight_clip_audio_balance(
                source, clip_uid="audio-clip", old_balance=25, new_balance=-50
            )
            self.assertEqual(result["new_stored_balance"], "0.25")

    def test_existing_hsl_scalar_is_copy_only_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_hsl(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append({
                    "type": 1,
                    "thisUId": "hsl-video",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "effectChainList": [{"effectList": [{
                        "id": "662E16ED-4524-4D13-AAE9-11DBA0C63E17",
                        "display": "AdjustColor",
                        "paramList": [{
                            "name": "Orange_satVal",
                            "fxParam": {"paramType": 3, "unValue": 15.0},
                        }],
                    }]}],
                })

            source = _rewrite_main_timeline(base, root / "source.wfp", add_hsl)
            output = root / "output.wfp"
            preflight = preflight_clip_hsl(
                source,
                clip_uid="hsl-video",
                parameter_name="Orange_satVal",
                old_value=15,
                new_value=27,
            )
            self.assertEqual(preflight["matching_archive_occurrences"], 1)
            result = replace_clip_hsl(
                source,
                output,
                clip_uid="hsl-video",
                parameter_name="Orange_satVal",
                old_value=15,
                new_value=27,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 1)
            self.assertTrue(source.exists())
            with self.assertRaisesRegex(WfpError, "does not match"):
                preflight_clip_hsl(
                    output,
                    clip_uid="hsl-video",
                    parameter_name="Orange_satVal",
                    old_value=15,
                    new_value=30,
                )

    def test_existing_blend_mode_is_copy_only_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_overlay(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append({
                    "type": 1,
                    "thisUId": "blend-video",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "pipBuf": '{"Algorithm":"Bilinear","BlendMode":"Multiply","Enable":true}',
                    "pipBufSize": 76,
                })

            source = _rewrite_main_timeline(base, root / "source.wfp", add_overlay)
            output = root / "output.wfp"
            preflight = preflight_clip_blend_mode(
                source, clip_uid="blend-video", old_mode="Multiply", new_mode="Screen"
            )
            self.assertEqual(preflight["matching_archive_occurrences"], 1)
            result = replace_clip_blend_mode(
                source,
                output,
                clip_uid="blend-video",
                old_mode="Multiply",
                new_mode="Screen",
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertEqual(
                [c["path"] for c in diff_projects(source, output)["json_changes"]
                 if "BlendMode" in c["path"]],
                ["$.timelineInfos[0].trackInfos[1].clipList[1].pipBuf.$embedded_json.BlendMode"],
            )

    def test_existing_equalizer_preset_replacement_is_guarded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            rock = [
                ("31Hz", -1.08), ("63Hz", 2.88), ("125Hz", 2.16),
                ("250Hz", 2.88), ("500Hz", -1.08), ("1kHz", -1.08),
                ("4kHz", 2.16), ("8kHz", 2.16), ("16kHz", 3.96),
            ]

            def add_equalizer(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append({
                    "type": 2,
                    "thisUId": "equalizer-audio",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "effectChainList": [{"effectList": [{
                        "id": "audio/effect/equalizer",
                        "paramList": [
                            {"name": name, "fxParam": {"paramType": 2, "unValue": value}}
                            for name, value in rock
                        ],
                    }]}],
                })

            source = _rewrite_main_timeline(base, root / "source.wfp", add_equalizer)
            output = root / "output.wfp"
            self.assertEqual(
                preflight_clip_equalizer(
                    source,
                    clip_uid="equalizer-audio",
                    old_preset="Rock",
                    new_preset="Pop",
                )["matching_archive_occurrences"],
                1,
            )
            result = replace_clip_equalizer(
                source,
                output,
                clip_uid="equalizer-audio",
                old_preset="Rock",
                new_preset="Pop",
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            # Pop changes values and the param-list shape because it inserts 2kHz
            # and removes/reorders the Rock-only positions.
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 12)
            with self.assertRaisesRegex(WfpError, "does not match"):
                preflight_clip_equalizer(
                    output,
                    clip_uid="equalizer-audio",
                    old_preset="Rock",
                    new_preset="Pop",
                )

    def test_existing_stabilization_smooth_replacement_is_guarded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_stabilization(timeline):
                video = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                video["type"] = 1
                video["thisUId"] = "stabilization-video"
                video["stabilization"] = {
                    "cache_mode": 0,
                    "smooth": 5.0,
                    "status": 1,
                    "version": 1.0,
                }

            source = _rewrite_main_timeline(base, root / "source.wfp", add_stabilization)
            output = root / "output.wfp"
            self.assertEqual(
                preflight_clip_stabilization(
                    source,
                    clip_uid="stabilization-video",
                    old_smooth=5.0,
                    new_smooth=9.0,
                )["matching_archive_occurrences"],
                1,
            )
            result = replace_clip_stabilization(
                source,
                output,
                clip_uid="stabilization-video",
                old_smooth=5.0,
                new_smooth=9.0,
            )
            self.assertTrue(result["audit"]["valid"], result)
            self.assertTrue(evaluate_project(output)["valid"])
            diff = diff_projects(source, output)
            self.assertEqual(
                [change["path"] for change in diff["json_changes"]],
                ["$.timelineInfos[0].trackInfos[1].clipList[0].stabilization.smooth"],
            )

            def disable_stabilization(timeline):
                video = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip.get("thisUId") == "stabilization-video"
                )
                video["stabilization"]["status"] = 0

            disabled = _rewrite_main_timeline(source, root / "disabled.wfp", disable_stabilization)
            with self.assertRaisesRegex(WfpError, "enabled normalized state"):
                preflight_clip_stabilization(
                    disabled,
                    clip_uid="stabilization-video",
                    old_smooth=5.0,
                    new_smooth=9.0,
                )

    def test_existing_video_denoise_sigma_replacement_is_guarded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_denoise(timeline):
                video = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                video["type"] = 1
                video["thisUId"] = "video-denoise"
                video["image_denoise"] = {
                    "cache_mode": 0,
                    "sigma": 20.0,
                    "status": 1,
                    "version": 1.0,
                }

            source = _rewrite_main_timeline(base, root / "source.wfp", add_denoise)
            output = root / "output.wfp"
            self.assertEqual(
                preflight_clip_video_denoise(
                    source,
                    clip_uid="video-denoise",
                    old_sigma=20.0,
                    new_sigma=40.0,
                )["matching_archive_occurrences"],
                1,
            )
            result = replace_clip_video_denoise(
                source,
                output,
                clip_uid="video-denoise",
                old_sigma=20.0,
                new_sigma=40.0,
            )
            self.assertTrue(result["audit"]["valid"], result)
            self.assertTrue(evaluate_project(output)["valid"])
            diff = diff_projects(source, output)
            self.assertEqual(
                [change["path"] for change in diff["json_changes"]],
                ["$.timelineInfos[0].trackInfos[1].clipList[0].image_denoise.sigma"],
            )

    def test_existing_lut_strength_replacement_is_guarded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_lut(timeline):
                video = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                video["type"] = 1
                video["thisUId"] = "lut-video"
                video.setdefault("effectChainList", []).append({"name": "Color", "effectList": [{
                    "display": "AdjustColor",
                    "id": "662E16ED-4524-4D13-AAE9-11DBA0C63E17",
                    "paramList": [
                        {"name": "bEnableLUT", "fxParam": {"paramType": 5, "unValue": 1}},
                        {"name": "lut3dPath", "fxParam": {"paramType": 6, "unValue": "%Anonymous_dir%/Anon/Effect/test-red.cube"}},
                        {"name": "alpha", "fxParam": {"paramType": 5, "unValue": 48}},
                    ],
                }]})

            source = _rewrite_main_timeline(base, root / "source.wfp", add_lut)
            output = root / "output.wfp"
            self.assertEqual(
                preflight_clip_lut(
                    source,
                    clip_uid="lut-video",
                    old_strength=48,
                    new_strength=75,
                )["matching_archive_occurrences"],
                1,
            )
            result = replace_clip_lut(
                source,
                output,
                clip_uid="lut-video",
                old_strength=48,
                new_strength=75,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"], result)
            self.assertTrue(evaluate_project(output)["valid"])
            diff = diff_projects(source, output)
            self.assertEqual(
                [change["path"] for change in diff["json_changes"]],
                ["$.timelineInfos[0].trackInfos[1].clipList[0].effectChainList[0].effectList[0].paramList[2].fxParam.unValue"],
            )

            with self.assertRaisesRegex(WfpError, "does not match"):
                preflight_clip_lut(
                    output,
                    clip_uid="lut-video",
                    old_strength=48,
                    new_strength=80,
                )

    def test_replace_existing_uniform_corner_radius_is_guarded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_radius(timeline):
                parameters = [
                    {"name": name, "fxParam": {"paramType": 3, "unValue": 20.0}}
                    for name in ("LeftTop", "RightTop", "LeftBottom", "RightBottom")
                ]
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "rounded-video",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [{"effectList": [{
                            "id": "video/effect/transform",
                            "paramList": parameters,
                        }]}],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_radius)
            output = root / "output.wfp"
            self.assertEqual(
                preflight_clip_corner_radius(
                    source,
                    clip_uid="rounded-video",
                    old_radius="20",
                    new_radius="75",
                )["matching_archive_occurrences"],
                1,
            )
            result = replace_clip_corner_radius(
                source,
                output,
                clip_uid="rounded-video",
                old_radius="20",
                new_radius="75",
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertTrue(
                audit_clip_corner_radius_copy(
                    source,
                    output,
                    clip_uid="rounded-video",
                    old_radius="20",
                    new_radius="75",
                )["valid"]
            )
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 4)
            with self.assertRaisesRegex(WfpError, "greater than zero"):
                preflight_clip_corner_radius(
                    source,
                    clip_uid="rounded-video",
                    old_radius="20",
                    new_radius="0",
                )
            with self.assertRaisesRegex(WfpError, "at most 100"):
                preflight_clip_corner_radius(
                    source,
                    clip_uid="rounded-video",
                    old_radius="20",
                    new_radius="101",
                )

    def test_replace_existing_anchor_pair_is_copy_only_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")
            old_x, old_y = normalized_anchor(100, 100, 1920, 1080)

            def add_anchor(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {
                        "type": 1,
                        "thisUId": "anchored-video",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "effectChainList": [{"effectList": [{
                            "id": "video/effect/transform",
                            "paramList": [
                                {
                                    "name": "_Anchor_x",
                                    "fxParam": {"paramType": 3, "unValue": float(old_x)},
                                },
                                {
                                    "name": "_Anchor_y",
                                    "fxParam": {"paramType": 3, "unValue": float(old_y)},
                                },
                            ],
                        }]}],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_anchor)
            output = root / "output.wfp"
            preflight = preflight_clip_anchor(
                source,
                clip_uid="anchored-video",
                old_anchor_x=old_x,
                old_anchor_y=old_y,
                new_x_pixels=200,
                new_y_pixels=200,
            )
            result = replace_clip_anchor(
                source,
                output,
                clip_uid="anchored-video",
                old_anchor_x=old_x,
                old_anchor_y=old_y,
                new_x_pixels=200,
                new_y_pixels=200,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"])
            self.assertTrue(
                audit_clip_anchor_copy(
                    source,
                    output,
                    clip_uid="anchored-video",
                    old_anchor_x=old_x,
                    old_anchor_y=old_y,
                    new_anchor_x=preflight["new_anchor_x"],
                    new_anchor_y=preflight["new_anchor_y"],
                )["valid"]
            )
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 2)
            self.assertTrue(source.exists())
            with self.assertRaisesRegex(WfpError, "must differ"):
                preflight_clip_anchor(
                    output,
                    clip_uid="anchored-video",
                    old_anchor_x=preflight["new_anchor_x"],
                    old_anchor_y=preflight["new_anchor_y"],
                    new_x_pixels=200,
                    new_y_pixels=200,
                )

    def test_replace_existing_clip_position_rejects_missing_stale_and_failed_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_unpositioned_clip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][1]["clipList"].append(
                    {"type": 1, "thisUId": "video-clip", "tlBegin": 0, "tlEnd": 20_000_000}
                )

            missing = _rewrite_main_timeline(base, root / "missing.wfp", add_unpositioned_clip)
            with self.assertRaisesRegex(WfpError, "Position_x and Position_y"):
                replace_clip_position(
                    missing,
                    root / "missing-output.wfp",
                    clip_uid="video-clip",
                    old_position_x="0.5",
                    old_position_y="0.5",
                    new_x_pixels=100,
                    new_y_pixels=100,
                )

            old_x, old_y = normalized_position(100, 100, 1920, 1080)

            def add_position(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][1]["clipList"][-1]
                clip["effectChainList"] = [{"effectList": [{
                    "id": "video/effect/transform",
                    "paramList": [
                        {"name": "Position_x", "fxParam": {"unValue": float(old_x)}},
                        {"name": "Position_y", "fxParam": {"unValue": float(old_y)}},
                    ],
                }]}]

            source = _rewrite_main_timeline(missing, root / "source.wfp", add_position)
            with self.assertRaisesRegex(WfpError, "does not match"):
                replace_clip_position(
                    source,
                    root / "stale.wfp",
                    clip_uid="video-clip",
                    old_position_x="0.5",
                    old_position_y=old_y,
                    new_x_pixels=200,
                    new_y_pixels=200,
                )
            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.position.audit_clip_position_copy",
                return_value={"valid": False, "errors": ["controlled position audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled position audit failure"):
                    replace_clip_position(
                        source,
                        rejected,
                        clip_uid="video-clip",
                        old_position_x=old_x,
                        old_position_y=old_y,
                        new_x_pixels=200,
                        new_y_pixels=200,
                    )
            self.assertFalse(rejected.exists())

    def test_replace_existing_clip_volume_gain_changes_only_selected_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_volume_gain(timeline):
                clip = {
                    "type": 2,
                    "thisUId": "audio-clip",
                    "tlBegin": 40_000_000,
                    "tlEnd": 60_000_000,
                    "inPoint": 0,
                    "outPoint": 20_000_000,
                    "effectChainList": [
                        {
                            "effectList": [
                                {
                                    "id": "audio/effect/volume",
                                    "thisUId": "volume-effect",
                                    "paramList": [
                                        {
                                            "name": "VolumeGain",
                                            "fxParam": {"paramType": 2, "unValue": 3.0},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(clip)

            source = _rewrite_main_timeline(base, root / "source.wfp", add_volume_gain)
            source_before = source.read_bytes()
            output = root / "output.wfp"
            result = replace_clip_volume_gain(
                source,
                output,
                clip_uid="audio-clip",
                old_volume_gain="3.0",
                new_volume_gain="-3.0",
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(
                result["audit"]["details"]["volume_gain_occurrences_changed"], 1
            )
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["before"], 3.0)
            self.assertEqual(changes[0]["after"], -3.0)
            self.assertEqual(
                preflight_clip_volume_gain(
                    source,
                    clip_uid="audio-clip",
                    old_volume_gain=3,
                    new_volume_gain=6,
                )["matching_archive_occurrences"],
                1,
            )
            self.assertTrue(
                audit_clip_volume_gain_copy(
                    source,
                    output,
                    clip_uid="audio-clip",
                    old_volume_gain=3,
                    new_volume_gain=-3,
                )["valid"]
            )

            targets = list_edit_targets(source)
            self.assertEqual(
                targets["volume_gain_targets"][0]["selector"],
                {"clip_uid": "audio-clip", "volume_gain": "3.0"},
            )
            plan = {
                "schema_version": 6,
                "source": {"sha256": project_sha256(source)},
                "operations": [
                    {
                        "op": "replace_clip_volume_gain",
                        "target": targets["volume_gain_targets"][0]["selector"],
                        "new_volume_gain": "6.0",
                    }
                ],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertFalse(explanation["writes_performed"])
            self.assertEqual(
                explanation["operations"][0]["op"], "replace_clip_volume_gain"
            )
            plan_output = root / "plan-output.wfp"
            plan_result = apply_edit_plan(source, plan_output, plan)
            self.assertTrue(plan_result["verification"]["source_aware_audit_valid"])
            self.assertEqual(
                len(diff_projects(source, plan_output)["json_changes"]), 1
            )

            v5_plan = dict(plan)
            v5_plan["schema_version"] = 5
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(v5_plan)

    def test_replace_existing_clip_volume_gain_rejects_missing_or_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_audio_clip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {
                        "type": 2,
                        "thisUId": "audio-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 60_000_000,
                        "inPoint": 0,
                        "outPoint": 20_000_000,
                    }
                )

            missing = _rewrite_main_timeline(base, root / "missing-source.wfp", add_audio_clip)
            with self.assertRaisesRegex(WfpError, "exactly one existing VolumeGain"):
                replace_clip_volume_gain(
                    missing,
                    root / "missing.wfp",
                    clip_uid="audio-clip",
                    old_volume_gain=0,
                    new_volume_gain=3,
                )

            def add_volume_gain(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][-1]
                clip["effectChainList"] = [
                    {
                        "effectList": [
                            {
                                "id": "audio/effect/volume",
                                "paramList": [
                                    {"name": "VolumeGain", "fxParam": {"unValue": 3.0}}
                                ],
                            }
                        ]
                    }
                ]

            source = _rewrite_main_timeline(missing, root / "source.wfp", add_volume_gain)
            with self.assertRaisesRegex(WfpError, "does not match"):
                replace_clip_volume_gain(
                    source,
                    root / "stale.wfp",
                    clip_uid="audio-clip",
                    old_volume_gain=0,
                    new_volume_gain=6,
                )

            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                replace_clip_volume_gain(
                    source,
                    root / "stale-hash.wfp",
                    clip_uid="audio-clip",
                    old_volume_gain=3,
                    new_volume_gain=6,
                    expected_source_sha256="0" * 64,
                )

            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.volume.audit_clip_volume_gain_copy",
                return_value={"valid": False, "errors": ["controlled volume audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled volume audit failure"):
                    replace_clip_volume_gain(
                        source,
                        rejected,
                        clip_uid="audio-clip",
                        old_volume_gain=3,
                        new_volume_gain=6,
                    )
            self.assertFalse(rejected.exists())

    def test_replace_existing_clip_fade_in_changes_only_selected_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_fade_in(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {
                        "type": 2,
                        "thisUId": "audio-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 90_000_000,
                        "effectChainList": [
                            {
                                "effectList": [
                                    {
                                        "id": "audio/effect/fade",
                                        "paramList": [
                                            {
                                                "name": "FadeInTime",
                                                "fxParam": {
                                                    "paramType": 2,
                                                    "unValue": 1.0,
                                                },
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_fade_in)
            source_before = source.read_bytes()
            output = root / "output.wfp"
            result = replace_clip_fade_in(
                source,
                output,
                clip_uid="audio-clip",
                old_fade_in="1.0",
                new_fade_in="2.0",
                expected_source_sha256=project_sha256(source),
            )

            self.assertEqual(source.read_bytes(), source_before)
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["audit"]["details"]["fade_in_occurrences_changed"], 1)
            changes = diff_projects(source, output)["json_changes"]
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["before"], 1.0)
            self.assertEqual(changes[0]["after"], 2.0)
            self.assertEqual(
                preflight_clip_fade_in(
                    source,
                    clip_uid="audio-clip",
                    old_fade_in=1,
                    new_fade_in="1.5",
                )["matching_archive_occurrences"],
                1,
            )
            self.assertTrue(
                audit_clip_fade_in_copy(
                    source,
                    output,
                    clip_uid="audio-clip",
                    old_fade_in=1,
                    new_fade_in=2,
                )["valid"]
            )

            targets = list_edit_targets(source)
            self.assertEqual(
                targets["fade_in_targets"][0]["selector"],
                {"clip_uid": "audio-clip", "fade_in": "1.0"},
            )
            self.assertEqual(targets["fade_in_targets"][0]["max_fade_in"], "5")
            plan = {
                "schema_version": 7,
                "source": {"sha256": project_sha256(source)},
                "operations": [
                    {
                        "op": "replace_clip_fade_in",
                        "target": targets["fade_in_targets"][0]["selector"],
                        "new_fade_in": "1.5",
                    }
                ],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertFalse(explanation["writes_performed"])
            self.assertEqual(explanation["operations"][0]["op"], "replace_clip_fade_in")
            plan_output = root / "plan-output.wfp"
            plan_result = apply_edit_plan(source, plan_output, plan)
            self.assertTrue(plan_result["verification"]["source_aware_audit_valid"])
            self.assertEqual(len(diff_projects(source, plan_output)["json_changes"]), 1)

            v6_plan = dict(plan)
            v6_plan["schema_version"] = 6
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(v6_plan)

    def test_replace_existing_clip_fade_in_rejects_unsafe_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_audio_clip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {
                        "type": 2,
                        "thisUId": "audio-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 90_000_000,
                    }
                )

            missing = _rewrite_main_timeline(base, root / "missing.wfp", add_audio_clip)
            with self.assertRaisesRegex(WfpError, "exactly one existing FadeInTime"):
                replace_clip_fade_in(
                    missing,
                    root / "missing-output.wfp",
                    clip_uid="audio-clip",
                    old_fade_in=1,
                    new_fade_in=2,
                )

            def add_fade_in(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][-1]
                clip["effectChainList"] = [
                    {
                        "effectList": [
                            {
                                "id": "audio/effect/fade",
                                "paramList": [
                                    {"name": "FadeInTime", "fxParam": {"unValue": 1.0}}
                                ],
                            }
                        ]
                    }
                ]

            source = _rewrite_main_timeline(missing, root / "source.wfp", add_fade_in)
            for unsafe in (0, -1, "NaN", 6):
                with self.assertRaises(WfpError):
                    replace_clip_fade_in(
                        source,
                        root / ("unsafe-{0}.wfp".format(str(unsafe))),
                        clip_uid="audio-clip",
                        old_fade_in=1,
                        new_fade_in=unsafe,
                    )

            with self.assertRaisesRegex(WfpError, "does not match"):
                replace_clip_fade_in(
                    source,
                    root / "stale.wfp",
                    clip_uid="audio-clip",
                    old_fade_in=2,
                    new_fade_in=3,
                )
            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                replace_clip_fade_in(
                    source,
                    root / "stale-hash.wfp",
                    clip_uid="audio-clip",
                    old_fade_in=1,
                    new_fade_in=2,
                    expected_source_sha256="0" * 64,
                )

            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.audio_fade.audit_clip_fade_in_copy",
                return_value={"valid": False, "errors": ["controlled fade audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled fade audit failure"):
                    replace_clip_fade_in(
                        source,
                        rejected,
                        clip_uid="audio-clip",
                        old_fade_in=1,
                        new_fade_in=2,
                    )
            self.assertFalse(rejected.exists())

    def test_replace_existing_clip_fade_out_changes_only_selected_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_fade_out(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {
                        "type": 2,
                        "thisUId": "audio-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 90_000_000,
                        "effectChainList": [
                            {
                                "effectList": [
                                    {
                                        "id": "audio/effect/fade",
                                        "paramList": [
                                            {
                                                "name": "FadeOutTime",
                                                "fxParam": {
                                                    "paramType": 2,
                                                    "unValue": 1.0,
                                                },
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                )

            source = _rewrite_main_timeline(base, root / "source.wfp", add_fade_out)
            output = root / "output.wfp"
            result = replace_clip_fade_out(
                source,
                output,
                clip_uid="audio-clip",
                old_fade_out=1,
                new_fade_out=2,
                expected_source_sha256=project_sha256(source),
            )
            self.assertTrue(result["audit"]["valid"], result)
            self.assertEqual(result["audit"]["details"]["fade_out_occurrences_changed"], 1)
            self.assertEqual(len(diff_projects(source, output)["json_changes"]), 1)
            self.assertTrue(
                audit_clip_fade_out_copy(
                    source,
                    output,
                    clip_uid="audio-clip",
                    old_fade_out=1,
                    new_fade_out=2,
                )["valid"]
            )
            self.assertEqual(
                preflight_clip_fade_out(
                    source,
                    clip_uid="audio-clip",
                    old_fade_out=1,
                    new_fade_out="1.5",
                )["matching_archive_occurrences"],
                1,
            )

            targets = list_edit_targets(source)
            self.assertEqual(
                targets["fade_out_targets"][0]["selector"],
                {"clip_uid": "audio-clip", "fade_out": "1.0"},
            )
            self.assertEqual(targets["fade_out_targets"][0]["max_fade_out"], "5")
            plan = {
                "schema_version": 8,
                "source": {"sha256": project_sha256(source)},
                "operations": [
                    {
                        "op": "replace_clip_fade_out",
                        "target": targets["fade_out_targets"][0]["selector"],
                        "new_fade_out": "1.5",
                    }
                ],
            }
            explanation = explain_edit_plan(source, plan)
            self.assertFalse(explanation["writes_performed"])
            plan_output = root / "plan-output.wfp"
            plan_result = apply_edit_plan(source, plan_output, plan)
            self.assertTrue(plan_result["verification"]["source_aware_audit_valid"])
            self.assertEqual(len(diff_projects(source, plan_output)["json_changes"]), 1)

            v7_plan = dict(plan)
            v7_plan["schema_version"] = 7
            with self.assertRaisesRegex(WfpError, "Unsupported edit operation"):
                load_edit_plan(v7_plan)

    def test_replace_existing_clip_fade_out_rejects_unsafe_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_cloneable_title_project(root / "base.wfp")

            def add_audio_clip(timeline):
                timeline["timelineInfos"][0]["trackInfos"][0]["clipList"].append(
                    {
                        "type": 2,
                        "thisUId": "audio-clip",
                        "tlBegin": 40_000_000,
                        "tlEnd": 90_000_000,
                    }
                )

            missing = _rewrite_main_timeline(base, root / "missing.wfp", add_audio_clip)
            with self.assertRaisesRegex(WfpError, "exactly one existing FadeOutTime"):
                replace_clip_fade_out(
                    missing,
                    root / "missing-output.wfp",
                    clip_uid="audio-clip",
                    old_fade_out=1,
                    new_fade_out=2,
                )

            def add_fade_out(timeline):
                clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][-1]
                clip["effectChainList"] = [
                    {
                        "effectList": [
                            {
                                "id": "audio/effect/fade",
                                "paramList": [
                                    {"name": "FadeOutTime", "fxParam": {"unValue": 1.0}}
                                ],
                            }
                        ]
                    }
                ]

            source = _rewrite_main_timeline(missing, root / "source.wfp", add_fade_out)
            for unsafe in (0, -1, "NaN", 6):
                with self.assertRaises(WfpError):
                    replace_clip_fade_out(
                        source,
                        root / ("unsafe-{0}.wfp".format(str(unsafe))),
                        clip_uid="audio-clip",
                        old_fade_out=1,
                        new_fade_out=unsafe,
                    )
            with self.assertRaisesRegex(WfpError, "Source fingerprint changed"):
                replace_clip_fade_out(
                    source,
                    root / "stale-hash.wfp",
                    clip_uid="audio-clip",
                    old_fade_out=1,
                    new_fade_out=2,
                    expected_source_sha256="0" * 64,
                )

            rejected = root / "rejected.wfp"
            with patch(
                "filmora_wfp.audio_fade_out.audit_clip_fade_out_copy",
                return_value={"valid": False, "errors": ["controlled fade-out audit failure"]},
            ):
                with self.assertRaisesRegex(WfpError, "controlled fade-out audit failure"):
                    replace_clip_fade_out(
                        source,
                        rejected,
                        clip_uid="audio-clip",
                        old_fade_out=1,
                        new_fade_out=2,
                    )
            self.assertFalse(rejected.exists())

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
            self.assertEqual(targets["api_version"], 10)
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
            schema_v2 = edit_plan_schema(2)
            self.assertEqual(schema_v2["properties"]["schema_version"]["const"], 2)
            self.assertEqual(
                schema_v2["$defs"]["replaceTitleTextOperation"]["properties"]["op"]["const"],
                "replace_title_text",
            )
            schema_v3 = edit_plan_schema(3)
            self.assertEqual(schema_v3["properties"]["schema_version"]["const"], 3)
            self.assertEqual(
                schema_v3["$defs"]["replaceClipRotationOperation"]["properties"]["op"]["const"],
                "replace_clip_rotation",
            )
            schema_v4 = edit_plan_schema(4)
            self.assertEqual(schema_v4["properties"]["schema_version"]["const"], 4)
            self.assertEqual(
                schema_v4["$defs"]["moveLinkedAvPairOperation"]["properties"]["op"]["const"],
                "move_linked_av_pair",
            )
            schema_v5 = edit_plan_schema(5)
            self.assertEqual(schema_v5["properties"]["schema_version"]["const"], 5)
            self.assertEqual(
                schema_v5["$defs"]["splitLinkedAvPairOperation"]["properties"]["op"]["const"],
                "split_linked_av_pair",
            )
            schema_v6 = edit_plan_schema(6)
            self.assertEqual(schema_v6["properties"]["schema_version"]["const"], 6)
            self.assertEqual(
                schema_v6["$defs"]["replaceClipVolumeGainOperation"]["properties"]["op"]["const"],
                "replace_clip_volume_gain",
            )
            schema_v7 = edit_plan_schema(7)
            self.assertEqual(schema_v7["properties"]["schema_version"]["const"], 7)
            self.assertEqual(
                schema_v7["$defs"]["replaceClipFadeInOperation"]["properties"]["op"]["const"],
                "replace_clip_fade_in",
            )
            schema_v8 = edit_plan_schema(8)
            self.assertEqual(schema_v8["properties"]["schema_version"]["const"], 8)
            self.assertEqual(
                schema_v8["$defs"]["replaceClipFadeOutOperation"]["properties"]["op"]["const"],
                "replace_clip_fade_out",
            )
            schema_v9 = edit_plan_schema(9)
            self.assertEqual(schema_v9["properties"]["schema_version"]["const"], 9)
            self.assertEqual(
                schema_v9["$defs"]["replaceClipPositionOperation"]["properties"]["op"]["const"],
                "replace_clip_position",
            )
            schema_v10 = edit_plan_schema()
            self.assertEqual(schema_v10["properties"]["schema_version"]["const"], 10)
            self.assertEqual(
                schema_v10["$defs"]["replaceClipScaleOperation"]["properties"]["op"]["const"],
                "replace_clip_scale",
            )

    def test_v2_replace_title_text_plan_explains_and_applies_audited_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")
            source_before = source.read_bytes()
            output = root / "output.wfp"
            plan = _replace_text_plan(source)

            explanation = explain_edit_plan(source, plan)
            self.assertEqual(explanation["api_version"], 10)
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
            self.assertEqual(error["api_version"], 10)
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

    def test_map_profiles_audio_denoise_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_denoise(timeline):
                audio = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] in (2, 16)
                )
                audio["type"] = 2
                audio["denoiseV3Strength"] = 93.0
                audio["enableV3Denoise"] = True
                audio["effectChainList"] = [
                    {
                        "name": "Effect",
                        "effectList": [
                            {
                                "id": "audio/effect/volume",
                                "display": "volume",
                                "paramList": [
                                    {
                                        "name": "LoudnessGainEnable",
                                        "fxParam": {"paramType": 1, "unValue": True},
                                    },
                                    {
                                        "name": "LoudnessGain",
                                        "fxParam": {"paramType": 3, "unValue": 1.3743289709091187},
                                    },
                                ],
                            },
                            {
                                "id": "audio/effect/audio_forest",
                                "display": "audio_forest",
                                "paramList": [
                                    {
                                        "name": "effect_type",
                                        "fxParam": {"paramType": 5, "unValue": 2},
                                    }
                                ],
                            },
                        ],
                    }
                ]

            project = _rewrite_main_timeline(source, root / "denoise.wfp", add_denoise)
            result = map_project(project)
            audio_type = next(
                row for row in result["timeline"]["clip_types"] if row["type"] == "2"
            )
            self.assertEqual(
                audio_type["field_presence"]["denoiseV3Strength"], 1
            )
            self.assertEqual(audio_type["field_presence"]["enableV3Denoise"], 1)
            volume = next(
                effect for effect in result["effects"] if effect["id"] == "audio/effect/volume"
            )
            parameter_names = {item["name"] for item in volume["parameters"]}
            self.assertEqual(parameter_names, {"LoudnessGain", "LoudnessGainEnable"})
            voice_filter = next(
                effect
                for effect in result["effects"]
                if effect["id"] == "audio/effect/audio_forest"
            )
            voice_values = {
                item["value_path"]: item["examples"] for item in voice_filter["parameters"]
            }
            self.assertEqual(voice_values["fxParam.unValue"], [2])

    def test_map_profiles_motion_tracking_pointer_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_tracking(timeline):
                video = next(
                    clip
                    for track in timeline["timelineInfos"][0]["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                video["type"] = 1
                video["effectChainList"] = [
                    {
                        "name": "ObjTracking",
                        "effectList": [
                            {
                                "display": "ObjectTracking",
                                "id": "87289B96-239D-4740-BF86-023F54349902",
                                "paramList": [
                                    {
                                        "name": "ObjectTrackingPtr",
                                        "fxParam": {
                                            "paramType": 7,
                                            "unValue": {"enabled": False, "visble": True},
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]

            project = _rewrite_main_timeline(source, root / "tracking.wfp", add_tracking)
            result = map_project(project)
            tracking = next(
                effect
                for effect in result["effects"]
                if effect["id"] == "87289B96-239D-4740-BF86-023F54349902"
            )
            self.assertEqual(tracking["parameters"][0]["name"], "ObjectTrackingPtr")
            self.assertEqual(tracking["parameters"][0]["value_path"], "fxParam.paramType")

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

    def test_map_profiles_fast_wipe_transition_resource_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_cloneable_title_project(root / "source.wfp")

            def add_fast_wipe(timeline):
                current = next(item for item in timeline["timelineInfos"] if item["timelineId"] == 1)
                visual = next(
                    clip
                    for track in current["trackInfos"]
                    for clip in track["clipList"]
                    if clip["type"] == 6
                )
                visual["postTransition"] = {
                    "display": "Fast Wipe Left",
                    "id": "C8965C45-074B-4BF5-948E-D9373D10836C",
                    "thisUId": "fast-wipe-transition",
                    "tlBegin": 10_000_000,
                    "tlEnd": 20_000_000,
                    "type": 5,
                    "userData": [
                        {"key": 80, "data": "AQAAAA==", "size": 4},
                        {"key": 3, "data": "opaque", "size": 6},
                        {"key": 8, "data": "AwAAAA==", "size": 4},
                        {"key": 12, "data": "{}", "size": 2},
                    ],
                }

            project = _rewrite_main_timeline(source, root / "fast-wipe.wfp", add_fast_wipe)
            result = map_project(project)
            transition = next(item for item in result["transitions"] if item["display"] == "Fast Wipe Left")
            self.assertEqual(transition["id"], "C8965C45-074B-4BF5-948E-D9373D10836C")
            self.assertEqual(transition["position"], "postTransition")
            self.assertEqual(transition["duration_ticks"]["numeric_range"], [10_000_000, 10_000_000])
            self.assertTrue(evaluate_project(project)["valid"])

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

    def test_diff_expands_curve_color_json_below_generic_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = write_project(root / "base.wfp")

            def add_curve(value):
                def mutate(timeline):
                    clip = timeline["timelineInfos"][0]["trackInfos"][0]["clipList"][0]
                    payload = json.dumps(
                        {"points": [{"pos": 180.0, "val": value}]},
                        separators=(",", ":"),
                    )
                    clip["curve_color"] = [{"ICurveColor::Hue2Sat": payload}]
                return mutate

            before = _rewrite_main_timeline(base, root / "before.wfp", add_curve(1.5))
            after = _rewrite_main_timeline(base, root / "after.wfp", add_curve(1.75))
            result = diff_projects(before, after, member_filter="timeline.wesproj")
            curve_changes = [
                change
                for change in result["json_changes"]
                if change["path"].endswith(
                    "ICurveColor::Hue2Sat.$embedded_json.points[0].val"
                )
            ]
            self.assertEqual(len(curve_changes), 1)
            self.assertEqual(curve_changes[0]["before"], 1.5)
            self.assertEqual(curve_changes[0]["after"], 1.75)

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
