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
| transition add | apply Dissolve to one selected linked clip | added linked visual Dissolve and audio fade `postTransition` objects |
| transition duration | change two seconds to one second | moved both transition starts by 10,000,000 ticks; ends stayed fixed |
| transition undo | undo the insertion | removed both transition objects and restored the prior instance-ID count |

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
