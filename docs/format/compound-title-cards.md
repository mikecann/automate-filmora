# Compound title-card observations

Status: repeated observation from Filmora 15.6.4.11894 on macOS. The generated
copy described below passes structural validation, but its Filmora open/save
round-trip is still pending.

## Repeated UI result

The AI Tips project contains five section cards made by copying the same card in
Filmora, changing its two text layers, and placing it at a later cut. Every copy
uses a three-timeline graph:

1. an outer compound timeline with the animated background, transitions, and four
   audio effects;
2. a nested empty caption/preset timeline;
3. a nested title timeline with the background layer, heading, and subtitle.

The main edit places the outer timeline twice at the same range: clip type `16`
on the audio track and clip type `6` on the visual track.

## Archive and media routing

Each copied card also has its own archive folder:

```text
ProjectFolder/Medias/<media-id>/
├── timeline.wesproj
└── extra.json
```

The standalone `timeline.wesproj` repeats the same three timeline objects that
also appear in the main timeline document. Its `currentTimelineId` selects the
outer timeline.

`ProjectFolder/Medias/medias_info.json` adds both a `media_items[<media-id>]`
object and another `media_item` entry in the folder structure. The folder object
contains repeated `media_item` keys. A normal JSON object parser keeps only the
last one and corrupts the index when writing it again, so a writer must preserve
ordered duplicate key/value pairs.

Observed routing fields:

- outer timeline `userData` key `30309` contains a timeline UUID;
- main placement `userData` key `10` contains the media folder ID;
- `userData` key `6`, when four bytes long in a nested timeline, is the timeline
  ID encoded as a little-endian integer;
- `serialNumber` becomes one greater than the highest allocated timeline ID.

In one save, outer key `30309` matched the media item's `timeline_uuid`. A later
Filmora save changed the media-item UUID without changing key `30309`, so equality
is not an invariant. A clone must regenerate both values consistently with the
template's current relationship instead of forcing them to match.

## Identifier behavior

Filmora regenerates timeline IDs, media IDs, media timeline UUIDs, bus UUIDs,
`thisUId` values, and GUIDs embedded in base64 `userData` payloads.

Filmora deliberately preserves track `uuid` values across copied card timelines.
It also preserves external-media `sourceUuid`, `alphaVideoUuid`, and
`visualImageUuid` values. Regenerating all strings that look like UUIDs does not
match the application's own behavior.

`extra.json` indexes resource instances by the same GUIDs embedded in clip
`userData`, so both documents must be remapped with one shared ID map.

## Title fields

Changing a title requires keeping these values consistent:

- `scriptBuf.Text` and `scriptBuf.TextData[0].CharData`;
- `scriptBufSize`, observed as UTF-8 byte length plus one;
- `TextData[0].Basic.FontSize`, `FontHSize`, and `FontVSize`;
- `scriptBuf.ScaleX` / `ScaleY` and the title clip's transform `Scale_x` /
  `Scale_y` parameters.

For the observed Bebas Neue heading layers, rendered font width divided by `700`
matches `ScaleX`, and font size divided by `360` matches `ScaleY`. Scale values
and their percentage transform parameters are stored with float32 precision.
Subtitle width fitting is close to the same pattern but remains a hypothesis, so
the writer requires explicit scale values instead of inventing them.

## Implemented copy operation

`filmora-project clone-title-cards` clones one observed card template into a new
output project. It preserves every unrelated original archive member byte-for-byte,
updates the main and standalone timeline graphs together, preserves duplicate JSON
keys, refuses an existing output, and can require the exact source SHA-256.

The final compatibility gate is to open the generated copy in Filmora 15.6.4,
inspect all new cards, save it again, and diff that save against the generated file.

## Save-time normalization

A later Filmora save of the source compacted sparse timeline IDs into a contiguous
range and rewrote the main and every standalone timeline document. It also moved
all main camera clips after one card by exactly 31 frames. This confirms that
timeline IDs and downstream positions must be read from the latest source save;
they cannot be cached between runs. Use `--expect-sha256` whenever an open Filmora
session may autosave while a copy is being prepared.
