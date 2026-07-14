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

Do not encode these labels into a writer until controlled experiments confirm the
semantics across new projects and Filmora versions.

## Nested timelines

A compound placement has a `timelineId` instead of a usable `filename`. Resolve it
against `timelineInfos[].timelineId`, then traverse that timeline's tracks.

Nested timelines can themselves reference more timelines. Any exporter or writer
therefore needs a graph traversal, not a flat first-track parser.

## Effects and transitions

Effects live under:

```text
effectChainList[].effectList[]
```

Useful fields include `id`, `display`, `paramList`, and `userData`.

Transitions are embedded on clips as `preTransition` and `postTransition`, with
their own IDs, display names, time ranges, and user data.
