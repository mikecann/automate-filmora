# Silence removal, false starts, and repeated takes

Read this reference when the user wants Filmora Silence Detection-like editing
without keeping Filmora busy during analysis. The goal is a reviewable cut plan
and an openable Filmora project, not just a transcript or list of timestamps.

Also read `docs/rough-cut.md` for the current CLI contract. Read
`docs/case-studies/ai-tips.md` when the AI Tips recording or its learned false
start patterns are relevant.

## Inputs and outputs

Resolve these inputs before starting:

1. The current absolute path to the source recording. Check that it still
   exists. A renamed parent directory leaves a structurally valid WFP with
   missing external media.
2. A clean Filmora-created seed with the recording as exactly one linked video
   and audio pair, both starting at timeline and source zero.
3. An existing planner `transcript.json` when available. Prefer it over an old
   whole-recording transcript because it contains independent audible-region
   word timestamps.
4. An optional manually edited WFP for source-range evaluation.

Keep the source recording, seed, and every existing WFP untouched. Put each new
plan and generated project in a versioned ignored `work/` directory. Preserve:

- `transcript.json` for word-level evidence;
- `rough-cut-plan.json` for every keep, drop, and reason;
- `review.txt` for human review;
- the generated `.wfp` as a new file.

## Standard workflow

Create a plan:

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

Reuse the planner transcript on later iterations:

```bash
python3 -m filmora_wfp rough-cut-plan \
  "/path/to/recording.mp4" \
  work/recording-rough-cut-v2 \
  --transcript work/recording-rough-cut/transcript.json
```

Inspect `review.txt` and the plan before writing a project. When a manual edit
exists, compare source-time coverage:

```bash
python3 -m filmora_wfp rough-cut-eval \
  work/recording-rough-cut/rough-cut-plan.json \
  "/path/to/manual-reference.wfp"
```

Check the seed and use its exact hash guard:

```bash
python3 -m filmora_wfp rough-cut-seed "/path/to/seed.wfp" --json

python3 -m filmora_wfp rough-cut-project \
  "/path/to/seed.wfp" \
  work/recording-rough-cut/rough-cut-plan.json \
  work/recording-rough-cut/recording-rough-cut.wfp \
  --expect-sha256 <seed-sha256>
```

Run the structural and media gates on the generated copy:

```bash
python3 -m filmora_wfp validate \
  work/recording-rough-cut/recording-rough-cut.wfp \
  --check-media --json
python3 -m filmora_wfp eval-format \
  work/recording-rough-cut/recording-rough-cut.wfp
```

Treat any `Missing external media` result as a failed handoff. The current
validator makes an explicit media check invalid; older versions only emitted a
warning while calling the archive structurally valid. Resolve the recording's
current path before generation or relink it manually in Filmora and save a new
copy.

## Decision rules

Silence is a boundary signal, not proof of a bad take. Apply these rules in
combination:

- Remove an audible island with no transcript-word overlap by default. It is
  normally mouse, keyboard, handling, or room noise that crossed the amplitude
  threshold. Use `--keep-untranscribed-audio` when quiet or unusual speech may
  be missed.
- Prefer the later complete take when an earlier take repeats it. This matches
  the presenter's recording convention, but keep the policy configurable for a
  different speaker.
- Treat an earlier phrase that is an ordered prefix of a nearby fuller take as
  a false start. For example, an earlier "it's such an exciting" should be
  removed when the next attempt completes "it's such an exciting time to be a
  developer right now."
- Look for several earlier fragments before one final take. Exact phrase
  matching alone can remove the substantial attempts while leaving tiny stumble
  clips between them.
- Split an internal restart when a repeated opening occurs twice inside one
  audible island. Silence detection may not have produced a boundary there.
- Use ordered token coverage for reworded takes where no exact five-word span
  survives.
- Treat retained clips shorter than five seconds as suspicious review items,
  not automatic deletions. Short complete sentences and grammatical
  continuations are common.
- Let a transcript-only model suggest candidates, but keep deterministic
  timestamp evidence and Filmora listening as the acceptance gates.

Never reverse the later-take policy merely because an earlier delivery sounds
smoother in the transcript. The user may be pointing out fragments around the
later retry, not asking to preserve the earlier wording.

## Verification levels

Report these levels separately:

1. **Headless plan:** transcript, cut decisions, and review report exist.
2. **Writer audit:** the output contains the intended gapless linked source
   ranges, fresh identifiers, consistent durations, and unchanged unrelated
   archive members.
3. **Media check:** every external source path resolves on the current machine.
4. **Filmora open:** the exact originating build opens the generated project.
5. **Filmora save and reopen:** Filmora accepts and persists the generated
   structure.
6. **Listening review:** the user checks pacing, words, and semantic take
   choices. Distinguish a brief scan from a full playthrough.

Do not call the edit production-ready from precision and recall alone. Those
metrics compare source-time unions and cannot judge pacing, clip order,
rendering, or whether a spoken retry was intentional.
