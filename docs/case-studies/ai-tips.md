# AI Tips project, sanitized observations

Source project: `AI Tips.wfp`, created and modified by Filmora 15.6.4.11894 on
macOS. The original project and its absolute media paths are intentionally not
stored in this repository.

This study spans several Filmora saves. Counts in the next two sections describe
the smaller starting save used for the first copy experiment. The current source
at SHA-256 `8d264f5910d...` is about 2.58 MB and maps to 121 archive members,
55 canonical timelines, 46 title buffers, and 61 transitions.

## Historical starting shape

- ZIP size: about 319 KB.
- Uncompressed members: about 2.8 MB across 22 files.
- Main timeline: 3840x2160, 30 fps, 988.267 seconds.
- Main camera edit: 113 paired video and audio cuts.
- Current timeline: 7 tracks.
- Main timeline document: 17 `timelineInfos` entries.

## Nested inserts

The inspected source edit contains six paired nested placements:

- timeline `10`: subscribe animation, about 3.467 seconds;
- timeline `11`: first section card, about 3.067 seconds;
- timeline `12`: second section card, about 3.100 seconds;
- timeline `13`: third section card, about 3.100 seconds;
- timeline `14`: fourth section card, about 3.133 seconds;
- timeline `15`: fifth section card, about 3.133 seconds.

The section cards use an animated abstract WebM background, `Diagonal in`,
`Cut Slide Transition 03`, two staggered text layers, and four sound-effect layers.

## Decoded titles

- `1. Low Change Cost` / `Just Do It & Reverse`
- `2. Screenshots in PRs` / `a screeny is worth 1000 words`
- `3. Read Schema.ts!` / `Its the most important File`
- `4. Agent INterview` / `Work with your collaborator`
- `5. Discriminated Unions` / `statemachines good`

The heading uses Bebas Neue, usually at size 80. The subtitle uses Bebas Neue Book
at size 32 with character spacing 5. Both use title animation ID `274`.

## Copy experiment

The original copy-only experiment cloned timeline `15` nine times to add tips 6
through 14.
That generated project contains 44 timelines, 17 timeline documents, 15 paired
nested placements, and 28 decoded non-empty title layers. ZIP validation, media
resolution, timeline-reference validation, and identifier/routing audits pass.
Only the three expected original members changed, and 18 standalone card members
were added. All other source members remained byte-identical.

The first generated copy was rejected by Filmora even though every structural
check passed. Controlled load tests isolated the cause: the writer changed
`project_date_modify` without changing the opaque `project_source` integrity
value. A one-second timestamp-only change reproduced the same rejection.

After preserving both fields, a generated one-card copy loaded in Filmora
15.6.4.11894 and Filmora rendered its changed `LOAD TEST` title in the media
thumbnail. The historical nine-card copy also opened, but a fresh source-aware
audit now proves that file is stale relative to the current source. Keep it only
as load-test evidence.

That stale generated file had one conflicting standalone timeline cache copy. Filmora
tolerated it and converted it during Save As into an unreferenced,
standalone-only timeline with resources declared in that standalone document
root. This exposed and fixed an eval bug: `sourceUuid` definitions must be
collected from every timeline document root, not only the routed main document.

The current regression was rebuilt from the exact source hash into an ignored
fixture. It added nine card graphs and 18 title layers, changed only the routed
main timeline, media index, and project metadata, removed nothing, and passed
both the source-aware audit and `eval-format`. It opened in Filmora, displayed
added-card thumbnails, saved to a new path, retained identical semantic counts,
passed `eval-format` again, and reopened.

The current source already contains tip-card headings 6 through 14. The old
nine-card content spec therefore creates duplicates and is now a regression
fixture only, not a usable edit for the current project.

## Headless edit-plan dry run

The version 1 `edit-targets` command inspected the current source without opening
Filmora and found 12 templates compatible with `clone_title_cards`. It resolved a
plan selecting tip 6 by its visible heading and subtitle, converted 300 seconds
to 3,000,000,000 ticks, passed all source format probes, and returned
`writes_performed: false`.

Tips 7 and 9 were deliberately absent from compatible targets. Their standalone
graphs have paired type `16` and `6` placements, but each has only one non-empty
title layer. The proven writer requires exactly two non-empty layers, so the API
rejects those cards as templates instead of guessing how an empty subtitle should
be treated.

A Filmora save occurred during the experiment. It compacted the previously sparse
nested IDs into the contiguous range `10` through `25`, set `serialNumber` to
`26`, rewrote every standalone timeline document, removed one compound thumbnail,
and inserted 31 frames after tip 5. Every later camera clip moved by exactly those
31 frames. The source fingerprint guard caught the stale input, and the final copy
was rebuilt from the newer save with all remaining card positions shifted by the
same amount.

## Remaining open questions

- Meaning of timeline `type` values `0` and `1`.
- Exact distinction between nested clip types `6`, `7`, and `16`.
- Whether Filmora recalculates any title metrics or archive metadata on first save.
- Whether every generated card's complete animation renders identically before
  and after the save; the load test verified visible added-card thumbnails but did
  not play every animation end to end.

## Headless rough-cut benchmark, 2026-07-20

The original `1838.533` second camera recording and the `113` linked-pair
`AI Tips - completed intros.wfp` edit provide source-time ground truth for a
rough-cut planner. The reference camera clips retain `952.067` seconds. The main
timeline spans `988.267` seconds because it also contains gaps and compound
intro placements.

The first planner benchmark used:

- cached faster-whisper `small.en` with word timestamps and VAD;
- ffmpeg silence threshold `-35 dB`;
- minimum silence `0.5` seconds;
- softening buffer `0.4` seconds;
- exact five-word repeated sequences within a 90-second window;
- the earlier repeated occurrence as the proposed abandoned take.

After fixing whole-segment text being incorrectly copied into every overlapping
audible region, the source-time evaluation reported:

- predicted keep duration: `1183.350` seconds;
- manual keep duration: `952.067` seconds;
- keep precision: `80.16%`;
- keep recall: `99.63%`;
- keep intersection-over-union: `79.92%`;
- proposed repeated-take removal: `168.109` seconds;
- proposed repeated-take removal overlapping a manual keep: `0.000` seconds.

This is encouraging high-precision evidence on one recording, not proof that
five-word repetition generalizes to other presenters. The plan still keeps
about `231.3` seconds more than the manual edit, so semantic bad-take recall
needs more work. The evaluation compares unordered unions of source ranges; it
does not score the one source-order reversal, title-card gaps, final pacing, or
rendered output.

## Generated rough-cut project, 2026-07-20

A Filmora 15.7.3.12221 seed containing the untouched camera recording as one
linked pair passed the new guarded seed check. The writer rounded every keep
start down and keep end up to the nearest 30 fps boundary, merging ranges that
touched after rounding. It converted the `203` source-time keep ranges into
`198` linked pairs and a gapless `1189.900` second timeline.

The generated disposable `.wfp` passed its source-aware audit, media resolution,
and every format probe. The main timeline contains `198` visual plus `198` audio
clips and `1,782` unique instance IDs. No real project or recording was changed.

Filmora's Open dialog displayed the generated file, but the Mac locked before
the final Open action. The pending exact-build Save As and reopen check is still
required before using this generated copy as production evidence.

The first generated project retained `55` short audible regions with no word
timestamps, including six mouse or handling-noise clips before the first spoken
word. Requiring transcript-word overlap removed `63.489` seconds of these noise
islands. The revised plan retained `1119.861` source seconds and improved its
manual-reference precision from `80.16%` to `84.67%`, while recall remained
`99.59%`. After outward frame quantization, the revised Filmora project contains
`143` linked pairs and spans `1124.667` seconds.

The first interpretation of listening feedback around "the cost of
implementing" incorrectly reversed the policy and preferred the earlier smooth
take over a fragmented later take. The presenter clarified that the last take is
normally intentional and that the target was the false-start fragments. That
`v5` artifact is superseded.

The planner keeps the last repeated take. Its additional grouping is limited to
earlier attempts where two or more repeat spans progress through separate
audible islands in both versions. It removes the earlier islands between that
evidence, including non-matching stumble words that the per-region detector
would otherwise retain. This preserves the established last-take convention
while improving cleanup of fragmented false starts.

Further Filmora listening review showed the first generated clip was the prefix
"It's such an exciting", followed by a later clip that repeated and completed
the opening. The whole-recording Whisper transcript had incorrectly assigned
only "time to be a developer" to the later clip, hiding the repeated opening.
The same timestamp smearing hid two separate "the cost of implementing" false
starts at source `181.107-183.558` and `183.861-186.077` seconds before the
complete take at `186.960-193.639` seconds.

Whisper now receives all silence-cut ranges through `clip_timestamps` with
`condition_on_previous_text` disabled. The returned words retain absolute source
times, but each range gets independent language context. On the same recording
this exposed and removed the opening prefix plus both incomplete cost starts.
An explicit `0.60` no-speech probability filter also rejected eight short noise
hallucinations, including several bogus "Thanks for watching" segments. The
resulting `v9` project contains `140` linked pairs and spans `1125.433` seconds;
its source-aware audit and external-media validation passed.

Listening review at about timeline `05:31` exposed a second false-start shape.
The presenter made one partial "Oh and one last quick tip" attempt, five tiny
restart clips, another substantial failed attempt ending in frustration, and
then the complete take. Exact repeated-word matching already removed the two
substantial attempts but left the five fragments at source `581.802-591.346`
seconds.

The planner now recognizes a narrowly guarded chain: an earlier attempt repeats
in a later attempt, and that later attempt independently repeats in the final
take. When at least two intervening audible regions are each no longer than
three seconds, those trapped restart fragments are grouped with the failed
attempts. On this recording the change affected only those five regions out of
`231`; the complete take at source `612.883-624.918` remained. The generated
`v10` project contains `135` linked pairs and spans `1117.600` seconds. Its
archive, references, source-aware writer audit, and external media all passed
headless validation. Filmora listening remains the final quality gate.

Further review showed that duration alone is a poor bad-take classifier. Of the
`33` retained regions shorter than five seconds in `v10`, many were necessary
complete sentences or grammatical continuations. The planner now treats this
duration as a review signal while ordered token coverage detects reworded takes,
incomplete attempts, and short fragments trapped before the final take. It also
splits a repeated restart at source `1199.150` that silence detection had left
inside one audible region.

Claude Fable independently reviewed the transcript-only `v11` plan. It judged
`14` of the `18` short candidates as keeps, two as drops, and two as uncertain,
confirming that deleting every sub-five-second clip would be destructive. It
also identified three longer repeated takes missed by the duration signal. A
follow-up ordered-token scan found one additional ten-second earlier take. All
four longer candidates and the two definite short drops were absent from the
manual Filmora reference.

The resulting `v12` plan retains `993.980` source seconds. Against the manual
reference it has `95.39%` keep precision, `99.59%` recall, and `95.03%`
intersection-over-union. Its `290.794` seconds of proposed duplicate removals
have zero overlap with manual keeps. The generated project contains `111`
linked pairs and spans `997.600` seconds after frame quantization. Its writer
audit, archive validation, and external-media check passed. These measurements
are useful evidence for this recording, but neither the manual reference nor a
transcript-only model replaces listening in Filmora.

On 2026-07-21 Filmora initially reported the source recording as missing because
its parent directory had been renamed after `v12` was generated. The user
manually relinked the same recording and briefly scanned the resulting timeline,
reporting that `v12` looked good. This is direct open and semantic spot-check
evidence, but it is not a recorded full playthrough or Save As and reopen test.
