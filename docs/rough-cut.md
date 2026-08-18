# Headless rough-cut planning and project generation

Status: planning, evaluation, and a guarded single-source WFP writer are
implemented. Generated projects still require an exact-build Filmora open,
Save As, and reopen check before production use.

The rough-cut workflow keeps Filmora off the desktop while the expensive work
runs. It produces source-time edit decisions rather than driving Filmora's
Silence Detection window through GUI automation.

## Create a plan

```bash
python3 -m filmora_wfp rough-cut-plan \
  "/path/to/recording.mp4" \
  work/recording-rough-cut \
  --ffmpeg /path/to/ffmpeg \
  --model small.en \
  --threshold-db -35 \
  --minimum-silence 0.5 \
  --softening-buffer 0.4
```

The output directory must not exist. Silence detection runs first, then Whisper
transcribes each retained audible range with independent language context. This
prevents a short abandoned prefix and a later complete take being stitched into
one transcript sentence across a pause. The command writes:

- `transcript.json`: segment and word timestamps from faster-whisper;
- `rough-cut-plan.json`: silence intervals, audible regions, decisions, and
  source-time keep ranges;
- `review.txt`: every proposed duplicate drop and untranscribed audible region.

Pass `--transcript previous.srt` or `--transcript previous/transcript.json` to
skip transcription. For false-start detection, reuse a `transcript.json` made by
the current independent-region workflow. An older whole-recording transcript can
hide repetitions by joining words across silence. SRT works for region text, but
word-timestamp JSON is needed for the higher-coverage repeated-word detector.

`faster-whisper` remains optional so the base WFP inspector keeps its zero
dependency contract. If it is unavailable, provide an existing transcript.
ffmpeg is an external executable and is never downloaded by this repository.

## Decision model

The current defaults are conservative:

1. ffmpeg detects silence below `-35 dB` for at least `0.5` seconds.
2. Each audible range retains a `0.4` second softening buffer.
3. Whisper transcribes those ranges independently with absolute source-time
   word timestamps. Segments with at least `0.60` no-speech probability are
   discarded to suppress handling-noise hallucinations.
4. An exact sequence of at least five words repeated within 90 seconds links
   the two candidate takes. The later occurrence is kept.
5. If separate repeated phrases identify the first and last islands of one
   earlier attempt, the intervening false-start islands are removed with it.
   This stops non-matching stumble words between repeated sections surviving as
   tiny clips, without replacing the last take.
6. A chained `A -> B -> final take` match removes two or more short restart
   fragments trapped between the first two proven attempts. This covers several
   tiny "oh / one / ah" clips that contain too few words to match by themselves.
   Both substantial attempts must independently repeat later, and every trapped
   fragment must be no longer than three seconds.
7. Ordered token coverage catches nearby reworded versions whose meaning and
   word order are substantially shared even when no five-word block is exact.
   Brief takes get a slightly different evidence threshold so `4.9` versus
   `5.1` seconds is not an arbitrary semantic cliff.
8. When an exact restart happens near the beginning of one continuous audible
   range, its later occurrence becomes a new boundary. This exposes false starts
   that silence detection could not separate.
9. Any otherwise retained clip shorter than `5.0` seconds is marked `review`,
   not deleted. Use `--short-clip-suspicion 0` to disable this review signal or
   supply another positive duration to change it.
10. A fuzzy repeated-opening check catches a smaller number of obvious false
    starts.
11. Audible regions without transcript-word overlap are treated as handling,
   keyboard, mouse, or room noise and removed. This catches short sounds that
   cross the volume threshold without containing speech.

Pass `--keep-untranscribed-audio` when working with quiet or unusual speech that
Whisper may miss. Those regions then remain in the timeline and are marked for
review instead of being removed.

Every drop and suspicious short keep remains visible in `review.txt`. Non-speech removals are listed in
`non_speech_drop_ranges`, and grouped earlier attempts are explained in
`fragmented_false_start_groups` in the JSON plan. These repeated-word rules are
observed useful defaults from one presenter and recording, not universal rules
for speech editing.

## Evaluate against a manual edit

```bash
python3 -m filmora_wfp rough-cut-eval \
  work/recording-rough-cut/rough-cut-plan.json \
  "/path/to/manually-edited.wfp"
```

The command discovers the linked A/V source ranges in the reference project and
reports time-weighted keep precision, keep recall, and intersection-over-union.
If the project uses more than one linked media source, pass `--source-uuid` from
`edit-targets`.

These metrics compare the union of source ranges. They do not measure clip
order, title-card gaps, pacing, transitions, or whether Filmora rendered every
effect correctly.

## Filmora seed and project generation

A project write requires a clean Filmora-created seed containing the
untouched recording as exactly one linked video/audio pair starting at timeline
and source tick zero:

```bash
python3 -m filmora_wfp rough-cut-seed "/path/to/seed.wfp"
```

This check is read-only. When it reports `Filmora writer available: yes`, create
a new project from the reviewed keep ranges:

```bash
python3 -m filmora_wfp rough-cut-project \
  "/path/to/seed.wfp" \
  work/recording-rough-cut/rough-cut-plan.json \
  work/recording-rough-cut/recording-automated-rough-cut.wfp \
  --expect-sha256 <seed-sha256>
```

The writer refuses to overwrite either path. It verifies the plan filename and
duration against the seed media, allows up to one conservative frame of
Filmora-native stream/timeline duration rounding, rounds keep starts down and
keep ends up to the nearest project frame, packs the retained ranges from
timeline zero, and creates one linked visual/audio pair per resulting range. It
assigns fresh clip, effect, and pair-link identifiers to every clone.

The source-aware audit checks the complete linked range list, gapless placement,
unique identifiers, project and media duration metadata, archive integrity, and
byte preservation of unrelated members. It deliberately preserves
`project_date_modify`, `project_source`, and `project_guid` together because the
integrity relationship is opaque.

## Evidence and remaining acceptance step

Filmora 15.7.11.12437 on macOS 26.5.2 accepted a real 4K Cannvas camera project
whose imported stream `offsetEnd` was about 5.7 ms shorter than its
frame-quantized linked clip duration. A 177-pair Video HQ rough cut generated
from that source passed the writer audit, media validation, and format
evaluation, then opened, played, saved, and reopened in Filmora. The Filmora
resave also passed media validation and format evaluation with all 1,593
instance identifiers unique.

A repeated Filmora 15.7.3.12221 experiment on macOS 26.5.2 proved deletion and
ripple behaviour for a middle linked pair:

1. the selected visual/audio pair is removed together;
2. every following pair moves left by the deleted source duration while retaining
   its source points, speed offsets, clip IDs, effect IDs, and pair-link ID;
3. `project_timeline_duration` and the timeline entry in `medias_info.json` lose
   the same duration;
4. the same before/delete/after sequence produced identical timing semantics on
   a second run.

The AI Tips workflow continued through several listening-led revisions. Its
`v12` plan generated a `111`-pair project spanning `997.600` seconds after frame
quantization. Against the manual source-range reference it measured `95.39%`
keep precision, `99.59%` recall, and `95.03%` intersection-over-union.

On 2026-07-21 the recording's parent directory had been renamed, so Filmora
correctly requested a manual media relink. After relinking, the user briefly
scanned `v12` in Filmora and reported that it looked good. That confirms the
project opens and gives useful semantic spot-check evidence. It is not a
documented full playthrough or Filmora Save As and reopen test. See
[`format/observations-15.7.3.md`](format/observations-15.7.3.md) and
[`case-studies/ai-tips.md`](case-studies/ai-tips.md).
