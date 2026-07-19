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

### Controlled linked-pair move

Moving the second transition-free linked visual/audio pair one second later in a
same-session normalized experiment changed only both clips' `tlBegin` and
`tlEnd`. The range moved from `24,800,000..50,000,000` to
`34,800,000..60,000,000`; its duration, `inPoint`/`outPoint`, `sourceUuid`, clip
IDs, and effects stayed unchanged.

When the move extends the furthest occupied end, Filmora also updates
`project_info.project_timeline_duration` and duration fields in
`medias_info.json`. Those project-wide derived fields are not yet automated. The
accepted writer instead requires the requested new end to fit within the
project's already declared duration and rejects collisions on either selected
track. It changes exactly the four local placement fields. Filmora 15.6.4.11894
opened, saved, and reopened such a generated copy while preserving the moved
range.

This is direct placement evidence, not a model of Filmora's magnetic timeline.
Dragging an adjacent linked pair in another controlled attempt invoked overwrite
behaviour and removed clips rather than performing a simple move.

### Controlled linked-pair end trim

Shortening the same forward 1x linked pair's end by one second changed three
fields on each clip. `tlEnd` moved from `60,000,000` to `50,000,000`, the
absolute source `outPoint` moved from `50,000,000` to `40,000,000`, and
`speed.offsetEnd` moved from `5.0` to `4.0`. Filmora left `tlBegin`, `inPoint`,
`speed.offset`, and the serialized `speedParam` unchanged.

The accepted writer is limited to this relationship. It confirms that source
and timeline durations match at 1x speed, that both clips expose identical
forward constant-speed state, and that the requested end retains a positive
range. It does not claim support for reverse, variable-speed, transitioned,
start-trimmed, or duration-extending clips. Filmora opened, saved, and reopened
the generated six-field copy, and the saved copy retained all six values.

### Controlled linked-pair start trim

Shortening the same pair's start by one second changed the complementary fields.
Both `tlBegin` values moved from `34,800,000` to `44,800,000`, both absolute
source `inPoint` values moved from `24,800,000` to `34,800,000`, and both
`speed.offset` values advanced from `2.48` seconds.

Filmora's direct UI save serialized the new offset as
`3.4799999999999995`. A narrow writer instead stored the exact derived value
`3.48`; Filmora opened it, preserved `3.48` through Save As, and reopened the
saved copy. This confirms that the longer value was floating-point noise, not a
required representation.

The start-trim writer has the same forward constant 1x, matching source/range,
transition-free, and positive-duration boundary as the end-trim writer. It
changes exactly paired `tlBegin`, `inPoint`, and `speed.offset` fields.

### Controlled linked-pair split

Splitting the original five-second linked pair at `24,800,000` ticks was repeated
from a new Filmora Save As baseline. On both the visual and audio clips, Filmora
shortened the first half to `0..24,800,000`, set `outPoint` to `24,800,000`, and
set `speed.offsetEnd` to `2.48`. It cloned a second half at
`24,800,000..50,000,000`, with matching `inPoint` and `speed.offset: 2.48`.

Each second-half clip received a fresh canonical `thisUId`, as did every nested
effect in that clone. The two new halves shared one fresh uppercase pair-style
UUID in clip `userData` key `3`; the visual encoding retained its 64-byte NUL
padding and the audio encoding retained its 47-byte form. Other media, stream,
effect, speed-parameter, and opaque user-data values were copied unchanged.
Save As also rotated a timeline key-11000 UUID, but repeated saves show that to
be save noise rather than a required split mutation, so the writer preserves it.

The guarded writer enforces a transition-free type-1/type-2 pair, identical
source and timeline ranges, forward constant 1x speed, an interior split point,
and the observed shared key-3 link shape. Its audit reconstructs the expected
halves, rejects reused clip/effect IDs, and checks that unrelated timeline and
archive values remain unchanged. Filmora 15.6.4.11894 opened the generated copy,
saved it to a new path, retained all four half ranges and exact offsets, and
reopened the saved copy.
