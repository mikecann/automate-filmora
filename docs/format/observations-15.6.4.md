# Filmora 15.6.4 observation snapshot

This is a sanitized structural baseline for detecting format drift. It was built
on macOS 26.5.2 using Filmora 15.6.4.11894. The source project stayed untouched;
all UI work used byte-identical or disposable copies under ignored `work/`
directories.

## Large production sample

Archive inventory:

| Kind | Count |
| --- | ---: |
| archive members | 121 |
| project metadata | 1 |
| media library index | 1 |
| timeline documents | 22 |
| timeline `extra.json` documents | 22 |
| source `media.json` documents | 35 |
| media thumbnails | 38 |
| cover thumbnails | 1 |
| function-extra documents | 1 |

After de-duplicating exact standalone timeline copies, the canonical edit graph
contained:

| Structure | Count |
| --- | ---: |
| canonical timelines | 55 |
| definitions in routed main document | 54 |
| exact standalone copies | 50 |
| standalone-only definitions | 1 |
| conflicting standalone copies | 0 |
| track type `1` | 166 |
| track type `2` | 177 |
| title `scriptBuf` documents | 46 |
| effects | 3,077 |
| transitions | 61 |

Canonical clip type counts:

| Clip type | Count | Strongest current observation |
| --- | ---: | --- |
| `1` | 219 | ordinary visual source clips |
| `2` | 246 | ordinary audio source clips |
| `4` | 46 | generated title clips containing `scriptBuf` |
| `6` | 20 | nested-timeline placement variant |
| `7` | 33 | nested or compound visual placement variant |
| `16` | 20 | paired nested-timeline placement variant |

All 46 title buffers parsed as JSON. Every declared `scriptBufSize` equalled the
UTF-8 byte length of `scriptBuf` plus one. All 46 `Text` values matched their
`TextData[0].CharData` mirror.

The identifier audit found 55 timeline definitions and 73 references with no
unresolved targets. It found 48 resource `sourceUuid` definitions and 450
references with no unresolved targets. All 3,722 `thisUId` occurrences were
unique. Track UUIDs were not unique by design: 343 occurrences represented 90
values, with one value reused 15 times.

## JSON field coverage

The broad mapper observed these normalized field counts:

| Document kind | Documents | Normalized fields |
| --- | ---: | ---: |
| `project_info.json` | 1 | 46 |
| `medias_info.json` | 1 | 36 |
| `timeline.wesproj` | 22 | 284 |
| `extra.json` | 22 | 20 |
| `media.json` | 35 | 64 |
| `functionExtraData.json` | 1 | 2 |
| decoded title `scriptBuf` | 46 | 284 |

Array indexes and dynamic media or timeline IDs are normalized, so another
project can be compared against the same paths. String examples are redacted
when they look like absolute paths, and base64 content is summarized instead of
copied into the report.

`medias_info.json` had one deliberate duplicate-key pattern: 56 `media_item`
keys inside one `media_structure.Folder` object. That represents 55 values an
ordinary JSON object parser would lose.

## Disposable-project experiment matrix

Each step was saved to a new `.wfp` path in the same Filmora build.

| Step | Single UI action | High-signal structural result |
| --- | --- | --- |
| 00 | save blank project | one timeline, no clips, 1920x1080 at 25 fps |
| 01 | import one 5-second A/V MP4 | library entry, `media.json`, thumbnail; no timeline resource |
| 02 | insert imported media | root resource plus linked type `1` and `2` clips; project became 1280x720 |
| 03 | split linked pair at 2.48 s | four clips; new halves began at tick 24,800,000 with new instance IDs |
| 04 | add Basic Title at playhead | type `7` parent placement, new nested timeline, type `4` title clip |
| 05-06 | edit Basic Title text through properties panel | updated both text mirrors, byte size, script scale, and transform scale |
| 06-07 | repeat with same-byte-length text | only `Text` and `TextData[0].CharData` changed |
| track lock | toggle one Lock Track control, save, reopen | control returned to its original state; no persisted track field identified |
| track mute | toggle one Mute control, save, reopen | control returned to its original state; no persisted track field identified |
| rotation | change one source clip from 0 to 10 degrees | added `Rotation` with `paramType: 3` and `unValue: 10.0` to its Basic transform |
| position X repeat | change existing X from 100 px to 200 px at 1280x720 | changed only `Position_x.fxParam.unValue` from `0.578125` to `0.65625` plus save metadata |
| position Y repeat | change existing Y from 100 px to 200 px at 1280x720 | changed only `Position_y.fxParam.unValue` from `0.3611111044883728` to `0.2222222238779068` plus save metadata |
| linked uniform scale repeat | change existing Width/Height from 80% to 60% | changed only `Scale_x` and `Scale_y` from `80.0` to `60.0` plus save metadata |
| horizontal flip repeat | toggle an existing horizontal flip off and back on | toggled `enable: false` and key-101 data `AAAAAA==`/`AQAAAA==`; generated copy survived Filmora Save As |
| vertical flip repeat | toggle an existing vertical flip off and back on | same two-part state as horizontal under `video/effect/vertical_filp`; guarded generated copy survived Filmora Save As; insertion remains unverified |
| uniform corner radius repeat and boundaries | change 10% to 20%, then probe 0, -1, 99, and 100 | four named values store positive 1–100 directly; zero removes the quartet; guarded 100-to-75 copy survived Filmora Save As |
| anchor X repeat | change existing Anchor Point X from 100 px to 200 px at 1280x720 | changed only `_Anchor_x` from `0.578125` to `0.65625`; guarded paired generated copy survived Filmora Save As |
| anchor Y repeat | change existing Anchor Point Y from 100 px to 200 px at 1280x720 | changed only `_Anchor_y` from `0.3611111044883728` to `0.2222222238779068`; paired writer uses the same resolution conversion |
| linked uniform speed repeat | change linked A/V from 1.25x to 1.50x with ripple edit | updated both clip ends, both serialized speed payloads, media duration, and project duration; speed-payload `MD5` generation remains opaque |
| Maintain Pitch off | toggle off on normalized 1.50x linked pair | added `speedWithPitch: true` to only the type-2 audio clip; field naming is inverse to the UI label |
| Reverse Speed on | reverse linked pair carrying Vortex In animation | set both `speed.reverse` flags and mirrored all visual animation keys across the clip duration |
| stock speed ramps | independently apply Montage, Hero, Bullet Time, Jumper, Flash In, and Flash Out | mapped identical linked A/V interpolation-9 curves and curve-integrated durations; presets clear reverse/pitch mode and retime visual animation |
| Basic Color temperature repeat | change existing Temperature from 10 to 20 | changed only AdjustColor `u_temperature` from `10.0` to `20.0` plus save metadata |
| Basic Color scalar sweep | repeat Tint, Vibrance, Saturation, Exposure, Brightness, Contrast, Highlight, Shadow, White, and Black | each changed exactly one named AdjustColor scalar from `10.0` to `20.0` |
| Basic Color first use | set Exposure to 10 on a clip with no Color effect, then Save As | inserted one `AdjustColor` effect with `u_exposure=10.0`; generated file passed eval and Filmora round trip |
| Basic Sharpen repeat | change Sharpen from 10 to 20 | changed only separate Sharpen effect parameter `amount` from `10.0` to `20.0` |
| Basic Vignette scalar sweep | repeat Amount, Size, Roundness, Feather, Exposure, and Highlight | each changed exactly one named AdjustColor scalar; all stored the UI number directly |
| HSL Red scalar sweep | repeat Red Hue, Saturation, and Luminance from 10 to 20 | changed `Red_hueVal`, `Red_satVal`, and `Red_brightnessVal` independently |
| HSL channel sweep | repeat Hue for Orange, Yellow, Green, Cyan, Blue, Purple, and Magenta | confirmed all serialized prefixes; cyan is stored as `Aqua_hueVal` |
| HSL Orange saturation repeat | repeat Orange Saturation from 15 to 27 | changed only `Orange_satVal`, `paramType: 3`, direct UI scalar |
| HSL Orange luminance repeat | repeat Orange Luminance from 15 to 27 | changed only `Orange_brightnessVal`, `paramType: 3`, direct UI scalar |
| luma Curves repeat | move one midpoint upward | changed `yKnots` plus both derived Bezier-control arrays under the `rgbcurve` effect |
| Hue-vs-Sat Curves repeat | move one midpoint upward | changed only the `ICurveColor::Hue2Sat` JSON payload under `video/effect/curvecolor`; all six curve-mode payloads were identified |
| Color Wheels red-component sweep | repeat Shadows, Midtones, and Highlights red from 0.25 to 0.50 | confirmed `lift`, `gamma`, and `gain` families; each visible red edit also changed derived saturation and lightness |
| Fade In keyframe preset | double-click preset, Undo, Redo | populated `pipBuf.OpacityKeyFrame` with a one-second 0-to-100 ramp; Undo restored an empty string; payload MD5 remains opaque |
| remaining keyframe presets | apply each card independently from the same no-preset baseline | mapped Fade Out, Pause, four slide directions, Vortex In/Out, and Zoom In/Out across `pipBuf.OpacityKeyFrame` and transform `paramMapList`; sequential application can retain stale keys |
| base-track compositing negative control | try Opacity 100 to 50 with text entry and slider drag | no persisted semantic change; a true upper-track overlay is required before mapping static opacity or blend modes |
| track Hide toggle | toggle Video 1 Hide Track on a disposable project | track objects were unchanged; only an opaque timeline `userData` blob changed, so the field remains unresolved |
| upper-track overlay opacity | set Compositing Opacity 100 to 50, then 50 to 25 | each repeat changed only embedded `pipBuf.Opacity`; the guarded static-opacity writer passed eval on an existing overlay |
| Background blur enable and preset | enable default Blur, select 40%, disable | enable adds/removes `backgroundFillEnable: true`; preset changes retained `backgroundFillBluredness` from `20` to `40` |
| Motion Blur dependency probe | toggle Motion Blur on, cancel processing, toggle off, Save As | triggered an AI-model update and clip-processing pass; the final off save added no semantic project field, so mapping requires an explicitly accepted completed model run |
| transition add | apply Dissolve to one selected linked clip | added linked visual Dissolve and audio fade `postTransition` objects |
| transition duration | change two seconds to one second | moved both transition starts by 10,000,000 ticks; ends stayed fixed |
| transition undo | undo the insertion | removed both transition objects and restored the prior instance-ID count |
| linked A/V move | move a transition-free pair one second later | moved only both clips' `tlBegin`/`tlEnd` in a normalized undo/redo pair |
| linked A/V end trim | shorten a forward 1x pair by one second | changed both clips' `tlEnd`, `outPoint`, and `speed.offsetEnd` |
| linked A/V start trim | shorten the same pair's start by one second | changed both clips' `tlBegin`, `inPoint`, and `speed.offset` |
| audio volume repeat | change an existing gain from 3 dB to 6 dB | changed only `VolumeGain.fxParam.unValue` plus the per-save token |
| audio balance repeat | set Sound Balance to 25, 50, and -50 | changed one existing `Balance` scalar; UI-to-storage conversion was `(ui + 100) / 200` |
| audio fade-in repeat | change an existing fade from 1 s to 2 s | changed only `FadeInTime.fxParam.unValue` plus the per-save token |
| audio fade-out repeat | change an existing fade from 1 s to 2 s | changed only `FadeOutTime.fxParam.unValue` plus the per-save token |

The basic title defaulted to five seconds and extended the project to 7.48
seconds. Its title document was 3,467 UTF-8 bytes with `scriptBufSize` 3,468. The
title transform duplicated script values: effect `Position_y` matched `PosY`,
and effect scale percentages matched `ScaleX` and `ScaleY` multiplied by 100.

The first title-properties application performed a broad normalization pass, but
the repeated same-length edit isolated the two mirrored text fields cleanly.
Repeated saves also reorder keyed arrays and rotate opaque IDs, so raw JSON diff
output remains noisy. The semantic mapper is the better comparison surface.

The tested Lock Track and Mute controls behaved as editor-session state in this
build. That is deliberately narrower than claiming all track controls are absent
from the project format. Visibility, solo, track reorder, and track creation still
need isolated experiments.

A guarded writer later reproduced the linked move by changing exactly four local
placement fields while keeping the new end within the already declared project
duration. Filmora opened the copy, showed both pairs at the expected positions,
saved it again, and reopened the saved copy. A separate drag against adjacent
clips invoked magnetic overwrite behaviour instead, so that result was rejected
as evidence for the local move mapping.

A second guarded writer reproduced the one-second end trim with exactly six
changes. The generated and Filmora-resaved copies retained `tlEnd: 50,000,000`,
`outPoint: 40,000,000`, and `speed.offsetEnd: 4.0` on both clips. The saved copy
reopened and passed all format probes. Evidence remains limited to forward
constant 1x speed and an end trim that does not extend project duration.

The complementary start-trim writer changed exactly six fields and used exact
`speed.offset: 3.48` rather than Filmora UI's floating artifact
`3.4799999999999995`. Filmora accepted and preserved the exact value through
Save As and reopen. The accepted copy retained `tlBegin: 44,800,000` and
`inPoint: 34,800,000` on both clips and passed every format probe.

The original linked-pair split at `24,800,000` was repeated from a fresh Filmora
Save As baseline. Both runs shortened the first halves' `tlEnd`, `outPoint`, and
`speed.offsetEnd`, cloned complete second halves, and assigned fresh `thisUId`
values to both new clips and every nested effect. The new visual/audio halves
shared one new key-3 pair UUID while retaining the original pair's media-link
key. A guarded writer reproduced that structure. Filmora opened the generated
copy, saved it, preserved all four half ranges and exact `2.48` offsets, and
reopened the saved copy. The writer remains limited to transition-free forward
constant-1x pairs with the observed key-3 link identifier shape.

On 2026-07-20, two additional copy-only splits from the 16-minute AI Tips
timeline exercised primary tracks 3/4 and auxiliary tracks 9/10 with different
source media. Both generated copies passed their audits, opened and saved in the
same Filmora build, retained exact paired split boundaries and offsets after
Save As, and reopened. This clears the evidence gate for edit-plan schema v5;
it does not extend support to variable speed, transitions, or unobserved linked
identifier encodings.

## Filmora-native round trip

A previously generated, loadable title-card copy was opened in Filmora and saved
to another new path. The before and after semantic maps matched exactly for:

- canonical timeline and clip-type counts;
- title, effect, and transition counts;
- clip `thisUId` and track UUID cardinalities;
- resource and nested-timeline reference integrity.

Filmora still rewrote every numeric timeline ID and every corresponding reference.
It also rotated `project_guid`, `project_source`, and `project_date_modify`, updated
the stored filename and save path, and removed three stale nested thumbnails.

A later nine-card round trip exposed another cache normalization. The generated
file opened and rendered, despite one standalone timeline conflicting with the
routed main copy. Save As converted that conflict into an unreferenced,
standalone-only timeline. Its source resource was declared in the standalone
document root rather than the routed main root. Resource-reference evals must
therefore union definitions from every timeline document root.

That round trip proves two useful things. Semantic map comparison is more stable
than raw JSON diffing, and Filmora itself must remain the final compatibility gate.
It does not reveal how to synthesize `project_source`.

## Repeat the snapshot

For a new Filmora build:

```bash
python3 -m filmora_wfp map fixture.wfp --json > work/map.json
python3 -m filmora_wfp eval-format fixture.wfp --json > work/eval.json
python3 -m unittest discover -s tests -v
```

Then repeat the disposable-project matrix one UI action per Save As. Record the
Filmora build, OS, source SHA-256, exact control used, and before/after reports.
