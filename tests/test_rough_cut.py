from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from filmora_wfp.cli import main as cli_main
from filmora_wfp.rough_cut import (
    SilenceInterval,
    SpeechRegion,
    TranscriptSegment,
    TranscriptWord,
    build_rough_cut_inputs,
    build_rough_cut_plan,
    compare_keep_ranges,
    detect_duplicate_takes,
    inspect_rough_cut_seed,
    parse_ffmpeg_silence_output,
    parse_srt,
    speech_regions_from_silences,
    transcribe_media_ranges,
)


class RoughCutPlanningTest(unittest.TestCase):
    def test_builds_unclassified_inputs_for_codex_without_take_heuristics(self) -> None:
        inputs = build_rough_cut_inputs(
            source_name="recording.mp4",
            duration_seconds=10.0,
            silences=[SilenceInterval(2.0, 3.0), SilenceInterval(7.0, 8.0)],
            transcript=[
                TranscriptSegment(0.2, 1.8, "So the idea is"),
                TranscriptSegment(3.2, 6.8, "So the idea is to keep this"),
                TranscriptSegment(8.2, 9.8, "and finish the sentence"),
            ],
            softening_buffer=0.0,
        )

        self.assertEqual(
            [region["text"] for region in inputs["regions"]],
            [
                "So the idea is",
                "So the idea is to keep this",
                "and finish the sentence",
            ],
        )
        self.assertEqual(
            [region["decision"] for region in inputs["regions"]],
            ["review", "review", "review"],
        )
        self.assertEqual(
            {region["reason"] for region in inputs["regions"]},
            {"awaiting_codex_analysis"},
        )
        self.assertNotIn("repeated_word_spans", inputs)

    def test_parses_ffmpeg_duration_and_silence_intervals(self) -> None:
        output = """
Duration: 00:01:05.250, start: 0.000000, bitrate: 128 kb/s
[silencedetect @ 0x1] silence_start: 3.2
[silencedetect @ 0x1] silence_end: 4.7 | silence_duration: 1.5
[silencedetect @ 0x1] silence_start: 60.0
[silencedetect @ 0x1] silence_end: 65.25 | silence_duration: 5.25
"""

        duration, silences = parse_ffmpeg_silence_output(output)

        self.assertEqual(duration, 65.25)
        self.assertEqual(
            silences,
            [SilenceInterval(3.2, 4.7), SilenceInterval(60.0, 65.25)],
        )

    def test_builds_buffered_speech_regions_from_silence(self) -> None:
        regions = speech_regions_from_silences(
            10.0,
            [SilenceInterval(2.0, 4.0), SilenceInterval(7.0, 8.0)],
            softening_buffer=0.4,
        )

        self.assertEqual(
            regions,
            [(0.0, 2.4), (3.6, 7.4), (7.6, 10.0)],
        )

    def test_softening_buffer_merges_regions_when_it_consumes_a_short_silence(self) -> None:
        regions = speech_regions_from_silences(
            5.0,
            [SilenceInterval(2.0, 2.5)],
            softening_buffer=0.4,
        )

        self.assertEqual(regions, [(0.0, 5.0)])

    def test_parses_multiline_srt_blocks(self) -> None:
        srt = """1
00:00:01,000 --> 00:00:02,500
Hello there

2
00:00:03,250 --> 00:00:05,000
This is
two lines
"""

        segments = parse_srt(srt)

        self.assertEqual(
            segments,
            [
                TranscriptSegment(1.0, 2.5, "Hello there"),
                TranscriptSegment(3.25, 5.0, "This is two lines"),
            ],
        )

    def test_marks_an_earlier_false_start_as_a_duplicate_of_the_later_take(self) -> None:
        regions = [
            SpeechRegion(
                id="speech-0001",
                start=0.0,
                end=3.0,
                text="The important thing to remember is that schema changes",
            ),
            SpeechRegion(
                id="speech-0002",
                start=5.0,
                end=11.0,
                text=(
                    "The important thing to remember is that schema changes are "
                    "much harder to reverse later"
                ),
            ),
        ]

        decisions = detect_duplicate_takes(regions)

        self.assertEqual(decisions[0].decision, "drop")
        self.assertEqual(decisions[0].duplicate_of, "speech-0002")
        self.assertGreaterEqual(decisions[0].confidence, 0.9)
        self.assertEqual(decisions[1].decision, "keep")

    def test_does_not_drop_neighbouring_sentences_with_only_generic_words_in_common(self) -> None:
        regions = [
            SpeechRegion(
                id="speech-0001",
                start=0.0,
                end=3.0,
                text="The important thing is to review the generated screenshot",
            ),
            SpeechRegion(
                id="speech-0002",
                start=4.0,
                end=8.0,
                text="The important thing is to keep your database schema reversible",
            ),
        ]

        decisions = detect_duplicate_takes(regions)

        self.assertEqual([item.decision for item in decisions], ["keep", "keep"])

    def test_drops_reworded_normal_length_and_brief_earlier_takes(self) -> None:
        regions = [
            SpeechRegion(
                id="speech-0001",
                start=0.0,
                end=7.0,
                text=(
                    "It might be a bit wasteful token wise but I sometimes iterate "
                    "using that screenshot on the PR as well"
                ),
            ),
            SpeechRegion(
                id="speech-0002",
                start=9.0,
                end=20.0,
                text=(
                    "It might seem a bit wasteful but I actually sometimes just iterate "
                    "using that screenshot in the PR and regenerate a new screenshot"
                ),
            ),
            SpeechRegion(
                id="speech-0003",
                start=25.0,
                end=30.2,
                text=(
                    "It is really interesting that the image model itself is much better "
                    "at design than the LLMs"
                ),
            ),
            SpeechRegion(
                id="speech-0004",
                start=32.0,
                end=38.0,
                text=(
                    "I find it really interesting that the image models are really good "
                    "at design compared to the LLMs"
                ),
            ),
        ]

        decisions = detect_duplicate_takes(regions)

        self.assertEqual(decisions[0].decision, "drop")
        self.assertEqual(decisions[0].reason, "reworded_take_repeated_later")
        self.assertEqual(decisions[2].decision, "drop")
        self.assertEqual(decisions[2].reason, "brief_take_repeated_later")
        self.assertEqual(decisions[3].decision, "keep")

    def test_drops_narrow_recording_direction_and_post_outro_marker(self) -> None:
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=10.0,
            silences=[SilenceInterval(2.0, 3.0), SilenceInterval(7.0, 8.5)],
            transcript=[
                TranscriptSegment(
                    0.2,
                    1.8,
                    "Actually before we do that let me just add this to the intro.",
                ),
                TranscriptSegment(3.2, 6.8, "This useful section stays in the edit."),
                TranscriptSegment(8.7, 9.5, "Okay"),
            ],
            softening_buffer=0.0,
            short_clip_suspicion_seconds=0.0,
        )

        self.assertEqual(
            [(region["decision"], region["reason"]) for region in plan["regions"]],
            [
                ("drop", "recording_direction"),
                ("keep", "no_high_confidence_duplicate"),
                ("drop", "trailing_recording_marker"),
            ],
        )

    def test_builds_a_reviewable_plan_without_silently_dropping_untranscribed_audio(self) -> None:
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=12.0,
            silences=[SilenceInterval(3.0, 5.0), SilenceInterval(9.0, 10.0)],
            transcript=[
                TranscriptSegment(0.0, 2.8, "This is the opening sentence"),
                TranscriptSegment(5.2, 8.8, "This is the useful second sentence"),
            ],
            softening_buffer=0.4,
            drop_untranscribed_audio=False,
        )

        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(plan["source"]["duration_seconds"], 12.0)
        self.assertEqual(len(plan["regions"]), 3)
        self.assertEqual(plan["regions"][-1]["decision"], "review")
        self.assertEqual(
            plan["filmora_handoff"]["status"],
            "writer_available_after_seed_check",
        )
        self.assertTrue(plan["keep_ranges"])

    def test_drops_handling_noise_without_transcript_word_overlap_by_default(self) -> None:
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=6.0,
            silences=[SilenceInterval(1.0, 2.0), SilenceInterval(3.0, 4.0)],
            transcript=[
                TranscriptSegment(
                    0.0,
                    6.0,
                    "spoken",
                    (TranscriptWord(2.2, 2.8, "spoken"),),
                )
            ],
            softening_buffer=0.0,
        )

        self.assertEqual(
            [region["decision"] for region in plan["regions"]],
            ["drop", "review", "drop"],
        )
        self.assertEqual(
            [region["has_transcript_evidence"] for region in plan["regions"]],
            [False, True, False],
        )
        self.assertEqual(plan["keep_ranges"], [{"start": 2.0, "end": 3.0}])
        self.assertEqual(
            plan["non_speech_drop_ranges"],
            [{"start": 0.0, "end": 1.0}, {"start": 4.0, "end": 6.0}],
        )

    def test_word_timestamps_are_not_duplicated_across_adjacent_speech_regions(self) -> None:
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=6.0,
            silences=[SilenceInterval(2.0, 4.0)],
            transcript=[
                TranscriptSegment(
                    0.5,
                    5.5,
                    "first words second words",
                    (
                        TranscriptWord(0.5, 1.0, "first"),
                        TranscriptWord(1.0, 1.5, "words"),
                        TranscriptWord(4.5, 5.0, "second"),
                        TranscriptWord(5.0, 5.5, "words"),
                    ),
                )
            ],
            softening_buffer=0.0,
        )

        self.assertEqual(
            [region["text"] for region in plan["regions"]],
            ["first words", "second words"],
        )

    def test_repeated_word_sequence_drops_only_the_earlier_spoken_range(self) -> None:
        words = (
            TranscriptWord(0.2, 0.5, "please"),
            TranscriptWord(0.5, 0.8, "review"),
            TranscriptWord(0.8, 1.1, "every"),
            TranscriptWord(1.1, 1.4, "database"),
            TranscriptWord(1.4, 1.7, "schema"),
            TranscriptWord(4.2, 4.5, "please"),
            TranscriptWord(4.5, 4.8, "review"),
            TranscriptWord(4.8, 5.1, "every"),
            TranscriptWord(5.1, 5.4, "database"),
            TranscriptWord(5.4, 5.7, "schema"),
            TranscriptWord(5.7, 6.0, "change"),
        )
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=7.0,
            silences=[SilenceInterval(2.0, 4.0)],
            transcript=[
                TranscriptSegment(
                    0.2,
                    6.0,
                    "please review every database schema please review every database schema change",
                    words,
                )
            ],
            softening_buffer=0.0,
            minimum_duplicate_words=5,
        )

        self.assertEqual(plan["regions"][0]["decision"], "drop")
        self.assertEqual(plan["regions"][0]["reason"], "repeated_word_sequence")
        self.assertEqual(plan["regions"][1]["decision"], "review")
        self.assertEqual(plan["duplicate_drop_ranges"], [{"start": 0.0, "end": 2.0}])

    def test_drops_islands_between_repeated_parts_of_an_earlier_false_start(self) -> None:
        earlier_texts = (
            "please",
            "review",
            "every",
            "database",
            "schema",
            "no",
            "wait",
            "that",
            "is",
            "wrong",
            "always",
            "back",
            "up",
            "before",
            "migrations",
        )
        earlier_times = (
            0.2,
            0.5,
            0.8,
            1.1,
            1.4,
            3.1,
            3.25,
            3.4,
            3.55,
            3.7,
            5.2,
            5.5,
            5.8,
            6.1,
            6.4,
        )
        later_texts = (
            "please",
            "review",
            "every",
            "database",
            "schema",
            "carefully",
            "and",
            "always",
            "back",
            "up",
            "before",
            "migrations",
        )
        later_times = tuple(9.2 + index * 0.3 for index in range(len(later_texts)))
        words = tuple(
            TranscriptWord(start, start + 0.2, text)
            for start, text in zip(earlier_times + later_times, earlier_texts + later_texts)
        )
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=13.0,
            silences=[
                SilenceInterval(2.0, 3.0),
                SilenceInterval(4.0, 5.0),
                SilenceInterval(7.0, 9.0),
            ],
            transcript=[
                TranscriptSegment(
                    0.2,
                    12.7,
                    " ".join(earlier_texts + later_texts),
                    words,
                )
            ],
            softening_buffer=0.0,
            minimum_duplicate_words=5,
        )

        self.assertEqual(
            [region["decision"] for region in plan["regions"]],
            ["drop", "drop", "drop", "review"],
        )
        self.assertTrue(
            plan["regions"][0]["reason"] == "repeated_word_sequence"
            and plan["regions"][1]["reason"] == "fragmented_false_start_group"
            and plan["regions"][2]["reason"] == "repeated_word_sequence"
        )
        self.assertEqual(plan["keep_ranges"], [{"start": 9.0, "end": 13.0}])
        self.assertEqual(len(plan["fragmented_false_start_groups"]), 1)
        self.assertEqual(
            plan["fragmented_false_start_groups"][0]["earlier_region_ids"],
            ["speech-0001", "speech-0002", "speech-0003"],
        )
        self.assertEqual(
            plan["fragmented_false_start_groups"][0]["trapped_region_ids"],
            ["speech-0002"],
        )

    def test_drops_short_restarts_between_chained_false_start_attempts(self) -> None:
        first_attempt = ("oh", "and", "one", "quick", "tip")
        restart_fragments = ("oh", "a", "one", "one", "ah", "no")
        second_attempt = ("oh", "and", "one", "quick", "tip", "about", "schema")
        final_attempt = (
            "oh",
            "and",
            "one",
            "quick",
            "tip",
            "about",
            "schema",
            "changes",
        )
        timed_words = (
            tuple((0.2 + index * 0.3, word) for index, word in enumerate(first_attempt))
            + ((3.2, "oh"), (3.5, "a"))
            + ((5.2, "one"), (5.5, "one"))
            + ((7.2, "ah"), (7.5, "no"))
            + tuple((9.2 + index * 0.3, word) for index, word in enumerate(second_attempt))
            + tuple((14.2 + index * 0.3, word) for index, word in enumerate(final_attempt))
        )
        words = tuple(
            TranscriptWord(start, start + 0.2, word) for start, word in timed_words
        )
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=18.0,
            silences=[
                SilenceInterval(2.0, 3.0),
                SilenceInterval(4.0, 5.0),
                SilenceInterval(6.0, 7.0),
                SilenceInterval(8.0, 9.0),
                SilenceInterval(12.0, 14.0),
            ],
            transcript=[
                TranscriptSegment(
                    0.2,
                    16.5,
                    " ".join(word.text for word in words),
                    words,
                )
            ],
            softening_buffer=0.0,
            minimum_duplicate_words=5,
        )

        self.assertEqual(
            [region["decision"] for region in plan["regions"]],
            ["drop", "drop", "drop", "drop", "drop", "review"],
        )
        self.assertEqual(
            [region["reason"] for region in plan["regions"][1:4]],
            ["fragmented_false_start_group"] * 3,
        )
        chained_group = next(
            group
            for group in plan["fragmented_false_start_groups"]
            if group["reason"] == "chained_false_start_attempts"
        )
        self.assertEqual(
            chained_group["trapped_region_ids"],
            ["speech-0002", "speech-0003", "speech-0004"],
        )
        self.assertEqual(chained_group["final_region_id"], "speech-0006")
        self.assertEqual(plan["keep_ranges"], [{"start": 14.0, "end": 18.0}])

    def test_drops_a_reworded_short_take_and_trapped_restart_fragment(self) -> None:
        first = (
            "okay",
            "comment",
            "specific",
            "tip",
            "here",
            "if",
            "you",
            "read",
            "any",
        )
        fragment = ("okay", "comment", "and")
        final = (
            "okay",
            "this",
            "is",
            "a",
            "comment",
            "specific",
            "tip",
            "here",
            "if",
            "you",
            "read",
            "any",
            "schema",
            "changes",
        )
        timed_words = (
            tuple((0.2 + index * 0.3, word) for index, word in enumerate(first))
            + tuple((4.2 + index * 0.3, word) for index, word in enumerate(fragment))
            + tuple((7.2 + index * 0.3, word) for index, word in enumerate(final))
        )
        words = tuple(
            TranscriptWord(start, start + 0.2, word) for start, word in timed_words
        )
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=12.0,
            silences=[SilenceInterval(3.0, 4.0), SilenceInterval(5.5, 7.0)],
            transcript=[
                TranscriptSegment(
                    0.2,
                    11.3,
                    " ".join(word.text for word in words),
                    words,
                )
            ],
            softening_buffer=0.0,
            minimum_duplicate_words=10,
        )

        self.assertEqual(
            [region["decision"] for region in plan["regions"]],
            ["drop", "drop", "keep"],
        )
        self.assertEqual(
            plan["regions"][0]["reason"],
            "short_clip_repeated_in_later_take",
        )
        self.assertEqual(
            plan["regions"][1]["reason"],
            "fragmented_false_start_group",
        )

    def test_splits_a_leading_restart_inside_one_audible_range(self) -> None:
        first = ("as", "they", "say", "two", "heads", "are", "better", "than", "one")
        final = first + ("and", "here", "is", "the", "complete", "thought")
        timed_words = (
            tuple((0.2 + index * 0.3, word) for index, word in enumerate(first))
            + tuple((4.0 + index * 0.3, word) for index, word in enumerate(final))
        )
        words = tuple(
            TranscriptWord(start, start + 0.2, word) for start, word in timed_words
        )
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=9.0,
            silences=[],
            transcript=[
                TranscriptSegment(
                    0.2,
                    8.4,
                    " ".join(word.text for word in words),
                    words,
                )
            ],
            softening_buffer=0.0,
            minimum_duplicate_words=5,
        )

        self.assertEqual(len(plan["internal_restart_splits"]), 1)
        self.assertEqual(len(plan["regions"]), 2)
        self.assertEqual(plan["regions"][0]["decision"], "drop")
        self.assertEqual(plan["regions"][0]["reason"], "repeated_word_sequence")
        self.assertEqual(plan["regions"][1]["decision"], "keep")
        self.assertEqual(plan["keep_ranges"], [{"start": 4.0, "end": 9.0}])

    def test_marks_unmatched_short_complete_sentence_for_review_without_dropping_it(self) -> None:
        plan = build_rough_cut_plan(
            source_name="recording.mp4",
            duration_seconds=4.0,
            silences=[],
            transcript=[TranscriptSegment(0.2, 3.5, "This is for two big reasons.")],
            softening_buffer=0.0,
        )

        self.assertEqual(plan["regions"][0]["decision"], "review")
        self.assertEqual(plan["regions"][0]["reason"], "short_clip_suspicious")
        self.assertEqual(plan["keep_ranges"], [{"start": 0.0, "end": 4.0}])

    def test_transcribes_silence_cut_ranges_with_independent_whisper_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "recording.mp4"
            media.write_bytes(b"fixture")
            generated = [
                SimpleNamespace(
                    start=10.2,
                    end=11.1,
                    text=" It's such an exciting",
                    no_speech_prob=0.01,
                    words=[
                        SimpleNamespace(start=10.2, end=10.4, word=" It's"),
                        SimpleNamespace(start=10.4, end=10.6, word=" such"),
                    ],
                ),
                SimpleNamespace(
                    start=20.2,
                    end=20.8,
                    text=" Thanks for watching!",
                    no_speech_prob=0.85,
                    words=[
                        SimpleNamespace(start=20.2, end=20.5, word=" Thanks"),
                    ],
                ),
            ]
            model = Mock()
            model.transcribe.return_value = (iter(generated), SimpleNamespace())
            with patch(
                "filmora_wfp.rough_cut._load_whisper_model",
                return_value=model,
            ):
                transcript = transcribe_media_ranges(
                    media,
                    [(10.0, 12.0), (20.0, 25.0)],
                )

        self.assertEqual(transcript[0].text, "It's such an exciting")
        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0].words[0].start, 10.2)
        _media, = model.transcribe.call_args.args
        options = model.transcribe.call_args.kwargs
        self.assertEqual(options["clip_timestamps"], [10.0, 12.0, 20.0, 25.0])
        self.assertFalse(options["condition_on_previous_text"])
        self.assertTrue(options["vad_filter"])

    def test_cli_writes_new_plan_directory_and_reports_writer_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "recording.mp4"
            media.write_bytes(b"fixture")
            output = root / "rough-cut"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "filmora_wfp.cli.detect_silence",
                return_value=(6.0, [SilenceInterval(2.0, 3.0)]),
            ), patch(
                "filmora_wfp.cli.transcribe_media_ranges",
                return_value=[TranscriptSegment(0.0, 5.5, "A useful complete take")],
            ) as transcribe_mock, redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main(
                    ["rough-cut-plan", str(media), str(output), "--json"]
                )

            self.assertEqual(exit_code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(
                result["filmora_handoff"]["status"],
                "writer_available_after_seed_check",
            )
            self.assertTrue((output / "rough-cut-plan.json").is_file())
            self.assertTrue((output / "transcript.json").is_file())
            self.assertTrue((output / "review.txt").is_file())
            self.assertEqual(
                transcribe_mock.call_args.args[1],
                [(0.0, 2.4), (2.6, 6.0)],
            )

    def test_cli_writes_unclassified_codex_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "recording.mp4"
            media.write_bytes(b"fixture")
            output = root / "rough-cut"
            stdout = io.StringIO()
            with patch(
                "filmora_wfp.cli.detect_silence",
                return_value=(6.0, [SilenceInterval(2.0, 3.0)]),
            ), patch(
                "filmora_wfp.cli.transcribe_media_ranges",
                return_value=[TranscriptSegment(0.0, 5.5, "A complete transcript")],
            ), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                exit_code = cli_main(
                    ["rough-cut-inputs", str(media), str(output), "--json"]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "rough-cut-input.json").is_file())
            self.assertTrue((output / "transcript.json").is_file())
            self.assertFalse((output / "rough-cut-plan.json").exists())
            inputs = json.loads((output / "rough-cut-input.json").read_text())
            self.assertEqual(
                {region["reason"] for region in inputs["regions"]},
                {"awaiting_codex_analysis"},
            )

    def test_compares_predicted_and_manual_keep_ranges_by_time(self) -> None:
        result = compare_keep_ranges(
            [(0.0, 5.0), (10.0, 15.0)],
            [(0.0, 4.0), (12.0, 16.0)],
        )

        self.assertEqual(result["predicted_keep_seconds"], 10.0)
        self.assertEqual(result["actual_keep_seconds"], 8.0)
        self.assertEqual(result["intersection_seconds"], 7.0)
        self.assertAlmostEqual(result["keep_precision"], 0.7)
        self.assertAlmostEqual(result["keep_recall"], 0.875)
        self.assertAlmostEqual(result["keep_iou"], 7 / 11)

    def test_seed_check_delegates_to_guarded_project_writer_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "seed.wfp"
            project.write_bytes(b"fixture")
            expected = {
                "valid_seed_shape": True,
                "issues": [],
                "source": {"filename": "seed.wfp"},
                "seed": {"duration_ticks": 50_000_000},
                "filmora_writer_available": True,
                "remaining_gate": None,
            }
            with patch(
                "filmora_wfp.rough_cut_wfp.inspect_rough_cut_seed_shape",
                return_value=expected,
            ):
                result = inspect_rough_cut_seed(project)

            self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
