# Filmora 15.7.3 linked deletion and rough-cut observations

Status: repeated native deletion experiment and headless generated-project
audit. The generated project still needs the final Filmora Save As and reopen
round trip.

Environment:

- Filmora `15.7.3.12221`;
- macOS `26.5.2` build `25F84` on arm64;
- experiment date `2026-07-20`;
- source: one `1838.5333333` second 3840x2160 30 fps camera recording;
- every save used a new disposable path under ignored `work/` storage.

## Controlled linked-pair delete and ripple

The untouched seed contained one linked type-1/type-2 pair at
`0..18,385,333,333` ticks. Filmora split it at `899,333,333` and
`1,004,000,000`, producing three linked pairs. Magnetic Timeline was enabled.
The only edit after the split baseline was selecting and deleting the middle
pair.

The first and repeated runs both produced:

- linked pair count `3 -> 2`;
- timeline duration `18,385,333,333 -> 18,280,666,666`;
- removed duration `104,666,667` ticks;
- the first pair unchanged at `0..899,333,333`;
- the trailing source range unchanged at
  `1,004,000,000..18,385,333,333`;
- the trailing timeline range moved from
  `1,004,000,000..18,385,333,333` to
  `899,333,333..18,280,666,666`.

The trailing visual and audio clips retained their source points, speed offsets,
clip IDs, nested effect IDs, and shared key-3 link ID. Filmora removed the middle
clips and their marker/map entries. It subtracted the same duration from
`project_info.json.project_timeline_duration` and the routed timeline media
entry in `medias_info.json`.

Save As also rotated project and timeline tokens, and array order changed in
several opaque `userData` and effect lists. Those changes repeated as save noise
and are not part of the narrow timing rule.

## Filmora 15.7.3 seed rounding

The untouched linked pair had exact matching timeline and source ticks. Audio
stored `speed.offsetEnd: 1838.5333333`, while visual stored
`speed.offsetEnd: 1838.533`. Filmora itself split that pair successfully and
normalized the created halves to matching offsets. The rough-cut seed check
therefore permits at most `0.001` second of this native visual/audio end-offset
difference while still requiring exact linked ticks, source UUID, speed
parameters, and key-3 link shape.

## Guarded batch writer

The narrow writer clones the accepted seed pair for frame-aligned keep ranges.
It sets only the paired timeline/source bounds and speed offsets, creates fresh
clip/effect IDs and one shared link ID for every additional pair, packs the
pairs from timeline zero, and updates the two duration fields proven above.
Opaque integrity fields remain unchanged together.

For the AI Tips plan it produced:

- `198` linked A/V pairs after outward 30 fps quantization;
- `1,782` unique `thisUId` values;
- duration `11,899,000,000` ticks, or `1189.900` seconds;
- no gaps, overlaps, unresolved source UUIDs, or archive member changes outside
  the timeline and two metadata documents.

The generated file passed ZIP CRC, structural validation, routing, reference,
payload, uniqueness, source-aware, and media-resolution checks. Filmora's Open
dialog resolved and displayed the file, but the Mac locked before the final Open
action. Do not treat the headless result as proof of Filmora load/save survival
until the exact generated file completes Open, Save As, close, and reopen.

## Transcript-gated noise correction

The first plan kept every audible region without transcript evidence for manual
review. On the actual recording this created `55` short clips containing mouse,
keyboard, handling, or room noise, including six clips before speech began.
Together they retained `63.489` seconds.

The corrected default requires overlap with an actual Whisper word timestamp.
It does not use a broad segment envelope because a segment can span handling
noise between spoken words. SRT input has no word timestamps, so segment overlap
remains the fallback evidence for SRT-only plans. An explicit
`--keep-untranscribed-audio` option restores the conservative review behaviour.

The corrected AI Tips project contains `143` linked pairs, `1,287` unique
`thisUId` values, and a gapless `11,246,666,669` tick timeline. It passed the
same source-aware and format gates as the first generated project.
