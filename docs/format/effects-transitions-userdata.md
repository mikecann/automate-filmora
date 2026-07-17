# Effects, transitions, and opaque `userData`

Status: structural observations from Filmora 15.6.4.11894. Effect display names
are useful evidence, but IDs, numeric parameters, and base64 payloads remain
version-specific.

## Effects

Clip effects live under:

```text
effectChainList[].effectList[]
```

Observed fields include `id`, `display`, `paramList`, `userData`, and instance
identifiers. A parameter commonly stores its value in
`paramList[].fxParam.unValue`, but its type varies.

Default insertion of a generated A/V file added:

- visual: crop/pan/zoom and transform;
- audio: clip volume, channel selection, volume, fades, and ducking.

The studied production project also contained colour, curve, wheel, sharpen,
object-tracking, equalizer, and title-animation effects. The mapper reports every
observed ID/display pair, count, parameter name, value type, and numeric range.

A 204-project Filmora 14/15 corpus expanded this to 78 ID/display pairs. Effects
not present in AI Tips included audio enhancer, speech enhance, human/hair
segmentation, inner shadow, pixelate, masks, stock overlays, and a path-graphic
chain. Treat display names as evidence only; effect IDs and availability remain
build-specific.

Effect instance IDs are separate from clip IDs. A split duplicated the default
effect chains onto the new halves and allocated fresh effect instance IDs.

### Controlled rotation change

On a disposable type `1` visual clip, changing Rotate from `0` to `10` in the
Basic properties panel added this parameter to the existing Basic transform:

```json
{
  "name": "Rotation",
  "fxParam": {"paramType": 3, "unValue": 10.0}
}
```

The owning effect had `id: "video/effect/transform"` and
`display: "transform"`. The tested zero-degree save did not contain a
`Rotation` parameter at all. That is an omission rule for this clip, not a
universal rule: the production sample contained one explicitly serialized
zero-degree `Rotation` value.

A narrow writer then changed the already-present value from `10.0` to `20.0`
without adding or removing fields. Its source-aware diff contained exactly one
semantic change at the selected parameter's `fxParam.unValue`. Filmora
15.6.4.11894 opened the generated project and visibly rendered the first source
clip at 20 degrees while leaving the neighboring clip unchanged. Filmora Save As
preserved `20.0`, the saved project passed every format probe, and it reopened.

This proves replacement of one existing `Rotation` parameter. It does not yet
authorize inserting a missing Rotation parameter or changing other transform
parameters.

## Transitions

Transitions are not a separate top-level timeline list. They appear on clips as:

```text
preTransition
postTransition
```

Each can contain an ID, display name, range information, parameters, and
`userData`. The studied project had 61 canonical transition placements across
cuts, pushes, diagonal transitions, fades, and audio fades.

The wider corpus contained 52 position/ID/display combinations. Because pre and
post placements are counted separately, that is not 52 unique UI transition
names. It confirms the generic owner-side model across Filmora 14 and 15 but does
not make any individual asset ID portable.

Placement matters. A transition with the same display name can appear as a pre or
post transition, so automation must preserve both its body and its owning side.

### Controlled Dissolve change

Applying Filmora's Dissolve to the selected second half of a linked A/V clip
created two `postTransition` objects:

| Owning clip | Display | ID |
| --- | --- | --- |
| visual type `1` | `Dissolve` | `2981D185-D52E-44f4-ABD5-3CE83890E32E` |
| audio type `2` | `audio fade` | `audio/blender/transition-fade` |

At two seconds, both transitions covered timeline ticks `30,000,000` through
`50,000,000`. Changing Duration to one second through Filmora's Duration Setting
dialog moved both starts to `40,000,000` and kept both ends at `50,000,000`.
That confirms duration is `tlEnd - tlBegin` for these objects and that Filmora
keeps the linked visual and audio ranges together for this edit.

Undoing the insertion removed both objects and returned the project from 26 to
24 unique `thisUId` values. The audio object also contained
`includeTrimFrames: false`; the current evidence does not justify assigning a
broader meaning to that flag.

The format eval now requires every observed transition group to have a complete,
positive numeric range. A future Filmora build failing that probe may represent
format drift rather than corruption, so inspect the new structure before changing
the rule.

## Base64 `userData`

`userData` appears at project, timeline, track, clip, effect, and transition
scopes. The mapper decodes base64 only to classify the payload. It reports:

- scope and numeric key;
- decoded length;
- whether the bytes are UTF-8, JSON, UUID-like, or four-byte little-endian data;
- whether readable values match known timeline IDs or media folders.

It does not rewrite or assign names to unknown keys.

Two clip-level relationships repeated across the entire studied project:

- key `6`: all 584 four-byte little-endian values matched the containing
  timeline ID;
- key `10`: 392 UTF-8 values matched archive media-folder IDs, while another 115
  readable payloads did not.

Those are strong observations for this file, not enough evidence for a generic
writer. Key `10` clearly has more than one payload role. Preserve all unknown
entries byte-for-byte and require a controlled diff before changing any of them.
