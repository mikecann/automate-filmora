# Timeline observations

## Timebase

Observed values use 100-nanosecond ticks:

```text
10,000,000 ticks = 1 second
```

This applies to `tlBegin`, `tlEnd`, `inPoint`, `outPoint`, `mediaLength`, and
`project_timeline_duration` in the Filmora 15.6.4 sample.

## Timeline and tracks

Each `timelineInfos[]` entry has:

- `timelineId`: numeric identifier referenced by nested clips.
- `type`: observed `0` and `1`; exact semantics remain unconfirmed.
- `trackInfos`: ordered track array.
- resolution, aspect ratio, frame rate, sample rate, and audio bus metadata.

Observed `trackType` values:

- `1`: video or visual track.
- `2`: audio track.

`trackTag` appears to preserve UI ordering or pairing, but needs a controlled
experiment before stronger claims.

## Canonical definitions and standalone copies

Do not concatenate every `timelineInfos[]` array in the archive. In the studied
Filmora 15.6.4 project, the timeline document routed by `timeline_mediaId`
contained 54 definitions and 50 of those appeared again as exact standalone
copies. One additional definition existed only in a standalone document. The
canonical graph therefore had 55 timelines, not 105.

The mapper applies these rules:

1. take the routed main document's definitions as canonical;
2. classify a standalone definition with the same `timelineId` and identical
   JSON as an exact cache copy;
3. report a different body under the same ID as a conflict;
4. include an unseen standalone ID once as a standalone-only definition.

A conflicting copy fails `eval-format`. Exact copies should be kept in sync by a
future narrow writer if the edited timeline is duplicated there.

## Clips

Common clip fields:

- `thisUId`: clip instance UUID.
- `type`: clip kind enum.
- `filename` and `sourceUuid`: external media reference.
- `tlBegin` / `tlEnd`: placement in the containing timeline.
- `inPoint` / `outPoint`: selected range in the source.
- `streamId`: selected audio or video stream.
- `effectChainList`: effects and parameters.
- `userData`: undocumented keyed binary metadata, usually base64.

Observed clip `type` values in the AI Tips sample:

- `1`: ordinary visual media.
- `2`: ordinary audio media.
- `4`: generated title/caption clip with `scriptBuf`.
- `6`, `7`, `16`: nested timeline variants. Exact distinctions remain open.

A controlled basic-title insertion added a type `7` placement to the parent
timeline and a type `4` title clip to a new nested timeline. Existing compound
cards also pair types `6` and `16` against the same nested timeline ID on visual
and audio tracks. These are strong structural observations, not stable enum names.

Do not encode these labels into a writer until controlled experiments confirm the
semantics across new projects and Filmora versions.

### Corpus-only clip shapes

A read-only survey of 204 Filmora 14/15 projects added four types absent from AI
Tips:

- `8`: effect/adjustment asset shape. Some instances have `adjustLayer: true`,
  while others are stock overlays without that field.
- `14`: legacy visual screen-recording shape with keyboard and mouse display
  fields. Seen only in Filmora 14.0/14.3.
- `15`: linked legacy screen-recording audio shape with mouse audio controls.
  Seen only in Filmora 14.0/14.3.
- `26`: `serviceType: "pen"` path-graphic shape with a dedicated graphic effect
  chain. Seen only twice in Filmora 15.5 variants of the same subject.

These labels describe observed shapes, not stable enum definitions. See
[`../case-studies/external-backup-corpus.md`](../case-studies/external-backup-corpus.md)
for counts and limitations.

## Nested timelines

A compound placement has a `timelineId` instead of a usable `filename`. Resolve it
against `timelineInfos[].timelineId`, then traverse that timeline's tracks.

Nested timelines can themselves reference more timelines. Any exporter or writer
therefore needs a graph traversal, not a flat first-track parser.

## Identifier graph

At minimum, validate these relationships:

- `project_info.timeline_mediaId` resolves to a media folder;
- clip `timelineId` resolves to one canonical `timelineInfos[].timelineId`;
- clip `sourceUuid` resolves to a root `resources[].sourceUuid`;
- clip `thisUId` values remain unique;
- title or compound media folders referenced by opaque metadata remain present.

`eval-format` currently enforces unique routed-main timeline IDs, resolved
timeline and source references, and unique `thisUId` instance identifiers.

Numeric timeline IDs are not durable identities. A Filmora-native Save As of an
unchanged project rewrote every numeric timeline ID and every reference while
preserving the semantic graph, clip IDs, and track UUID cardinalities. Automation
must follow references, not memorize IDs from an earlier save.

## Effects and transitions

Effects live under:

```text
effectChainList[].effectList[]
```

Useful fields include `id`, `display`, `paramList`, and `userData`.

Transitions are embedded on clips as `preTransition` and `postTransition`, with
their own IDs, display names, time ranges, and user data.

Several apparent scalar fields are serialized documents. `pipBuf`,
`speed.speedParam`, audio parameter/keyframe fields, effect parameter keyframes,
smart-mask settings, colour curves, and title animation XML are profiled in
[`serialized-payloads.md`](serialized-payloads.md).

## Controlled media and split observations

Importing a media file into the library alone did not add a timeline resource or
clip. Inserting it on the timeline added one visual clip and one linked audio clip
with the same `sourceUuid`, source range, and timeline range. The visual and audio
clips used different `streamId` values and received different default effect
chains.

Splitting that linked pair at 2.48 seconds produced four clips. The first halves
kept their object IDs and shortened their ranges. The second halves received new
clip and effect instance IDs, started at tick 24,800,000, and retained the same
resource and stream references. `speed.offset` and `speed.offsetEnd` tracked the
new source ranges in seconds in this experiment.
