# Serialized JSON and XML payloads

Filmora stores several editable structures as strings inside the timeline JSON.
The mapper parses successful JSON/XML payloads, profiles their schema, and drops
all values. `scriptBuf` remains handled separately by the title mapper because it
has extra text-mirror and byte-size invariants.

## Repeated JSON fields

The 2026-07-16 corpus survey observed:

| Timeline field | Projects | Main structural keys |
| --- | ---: | --- |
| `pipBuf` | 202 | `Algorithm`, `BlendMode`, `BlenderName`, `Enable`, `Opacity`, `OpacityKeyFrame` |
| `speed.speedParam` | 202 | `MD5`, `ParameterType`, `Version`, `_totalTime`, `keyframeSets`, optional `_freeze` and `reverse` |
| `audioDuckingframe.parameter` | 202 | parameter metadata and `keyframeSets` |
| `volumeKeyframe.parameter` | 202 | parameter metadata and `keyframeSets` |
| effect `paramMapList[].keyFrame.parameter` | 127 | time, value, interpolation, and derivative fields |

The keyframe JSON is structural evidence that speed, opacity, volume, ducking,
and effect parameters can have time-varying values. Exact interpolation enum and
derivative semantics remain unknown.

Near-current Filmora 15 projects also exposed:

- `hdr_color` JSON with a literal trailing NUL byte in Filmora 15.5/15.6;
- six `curve_color` payloads with bounds, steps, points, and control points;
- path/custom-mask payloads with path transforms, opacity, feather, per-point
  coordinates, and coordinate keyframes;
- smart-remove mask settings under
  `intelligenceSegmentSmartRemoveSerializeToJson`.

Never update a serialized string without updating any owning size, checksum, mask
file, or effect metadata confirmed by a controlled experiment. The mapper is
read-only for all of these fields.

The mapper removes trailing NUL bytes only for parsing and reports how many
payloads were NUL-terminated. It never normalizes the source string itself.

## Title animation XML

Type `4` title clips can carry XML in `animation.charXml` or `inAnimation.charXml`.
The observed shape is:

```text
AnimationParam
└── AnimationConfig
```

Observed attribute names include `MotionID`, `TransitionID`, `AnimationType`,
`DurationType`, `InterpolateType`, `Property`, `StartValue`, and `EndValue`.
Attribute values are deliberately omitted from maps because they are still
version-specific and may include user or asset data.

## Privacy and normalization

Embedded JSON is profiled with examples disabled. XML reports tag and attribute
names only. UUID and hex object keys, including UUIDs wrapped in braces, normalize
to `{id}`. This prevents marker, beat-detection, and mask identifiers from
exploding the schema or leaking into corpus reports.

`eval-format` includes a non-required `serialized_payload_candidates_parse`
probe. A failure is a format-drift observation, not automatic project corruption,
because a future build may reuse a string field for a different syntax.
