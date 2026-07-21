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

### Controlled position change

On a disposable 1280x720 type `1` visual clip, the first non-zero Position X/Y
edits added `Position_x` and `Position_y` parameters to the existing
`video/effect/transform` node. Those first saves also normalized unrelated
metadata, so they do not authorize inserting either parameter.

Repeating X from 100 to 200 pixels isolated `Position_x.fxParam.unValue` from
`0.578125` to `0.65625`. Repeating Y from 100 to 200 pixels isolated
`Position_y.fxParam.unValue` from `0.3611111044883728` to
`0.2222222238779068`. The mapping is:

```text
Position_x = float32(0.5 + x_pixels / timeline_width)
Position_y = float32(0.5 - y_pixels / timeline_height)
```

The float32 conversion explains Filmora's visible decimal noise. A narrow
writer changed an existing pair to UI X `-150`, Y `-75`, producing normalized
values `0.3828125` and `0.6041666865348816` with exactly two semantic diffs.
Filmora 15.6.4.11894 displayed the requested pixel values, Save As retained
them, and a full quit/relaunch reopened the saved copy with the same values.
The saved project passed every format probe. This proves replacement of one
existing pair only. Insertion, keyframed position, and spatial interpretation
outside the declared timeline resolution remain unsupported.

### Controlled linked uniform scale change

On the same disposable visual clip, repeating linked Width/Height from 80% to
60% isolated `Scale_x` and `Scale_y` under `video/effect/transform`. Both
`fxParam.unValue` fields changed from `80.0` to `60.0`, apart from known Save As
metadata. The fields store UI percentages directly.

A replacement-only writer changed the existing pair to `70.0` with exactly two
semantic diffs. Filmora 15.6.4.11894 displayed `70.00%` for Width and Height,
Save As retained both values, and a full quit/relaunch reopened the saved copy
with both still visible. Every format probe passed. This proves positive linked
uniform replacement only. Missing scale parameters, zero or negative scale,
and unlocked non-uniform Width/Height remain unsupported.

### Controlled horizontal flip change

Filmora spells the effect identifier `video/effect/horizontal_filp`. On an
already-normalized visual clip, turning horizontal flip off added
`enable: false` and changed the four-byte key-101 payload from `AQAAAA==` to
`AAAAAA==`. Turning it back on removed `enable` and restored `AQAAAA==`.
No other clip field changed apart from known Save As metadata.

A copy-only writer reproduced the two-part off-to-on change. Filmora
15.6.4.11894 opened and displayed the generated project, then Save As retained
the enabled state and passed every format probe. Filmora regenerated all clip
and effect UIDs during that Save As, so round-trip checks must follow the
semantic effect state rather than require stable instance IDs.

Only replacement of an existing, exactly-shaped horizontal-flip node is
supported. First-use insertion remains unverified.

The same replacement shape is now confirmed for vertical flip. Its effect ID
is `video/effect/vertical_filp`, retaining Filmora's `filp` spelling. On an
existing node, off-to-on removed `enable: false` and changed key-101 data from
`AAAAAA==` to `AQAAAA==`; all other semantic fields stayed fixed. First-use
vertical insertion was observed only as incidental normalization during a
different edit, so insertion remains unsupported.

A guarded copy-only writer now supports replacement of this exact existing
vertical-flip shape. It rejects absent, duplicate, or unfamiliar state nodes and
audits the output for exactly the `enable` and key-101 changes before retaining
the copy. The generated off-to-on project opened in Filmora 15.6.4.11894, and a
Filmora Save As retained the absent `enable` field and `AQAAAA==` key-101 state.
The round-tripped project passed every format probe. First-use insertion is
still unsupported.

### Controlled uniform corner radius change

Repeating Basic > Corner Radius from 10% to 20% changed exactly four existing
`video/effect/transform` parameters, apart from Save As metadata:

```text
LeftTop:     10.0 -> 20.0
RightTop:    10.0 -> 20.0
LeftBottom:  10.0 -> 20.0
RightBottom: 10.0 -> 20.0
```

Each parameter used `paramType: 3`, and the stored value matched the UI
percentage. Later boundary probes confirmed positive values through 100.0.
Entering zero removed all four parameters instead of storing zero, entering
`-1` produced positive `1.0`, and the UI accepted both 99.0 and 100.0.

A guarded copy-only writer now replaces an existing complete uniform quartet
with another value greater than zero and at most 100. A generated 100-to-75
copy opened in Filmora 15.6.4.11894; Save As retained all four `75.0` values and
passed every format probe. Zero-removal, first-use insertion, and independent
per-corner editing remain unsupported.

### Controlled anchor-point changes

Basic > Anchor Point X repeated from 100 px to 200 px at 1280x720 by changing
only `_Anchor_x` from `0.578125` to `0.65625`. Anchor Point Y repeated from
100 px to 200 px by changing only `_Anchor_y` from
`0.3611111044883728` to `0.2222222238779068`. Both live under
`video/effect/transform` with `paramType: 3` and use the same conversion as
Position:

```text
stored Anchor X = 0.5 + pixels / timeline width
stored Anchor Y = 0.5 - pixels / timeline height
```

Both repeat snapshots passed every format probe. A guarded copy-only writer now
replaces an existing complete X/Y pair using the source project's declared
resolution and Filmora's float32 normalization. A generated 200-to-100 pair
opened in Filmora 15.6.4.11894; Save As retained `_Anchor_x = 0.578125` and
`_Anchor_y = 0.3611111044883728` and passed every format probe. First-use
insertion, accepted pixel-input bounds, and keyframed anchor points remain
unsupported.

### Controlled linked uniform speed change

With Ripple Edit and Maintain Pitch enabled, changing a linked A/V pair from
1.25x to 1.50x updated both type-1 and type-2 clips symmetrically. Each clip's
`tlEnd` and `outPoint` changed from `40000000` to `33333333`, while
`speed.offsetEnd` stayed at the five-second source duration. The embedded
`speed.speedParam` changed its first keyframe `_value`, matching derivative
fields, and its opaque `MD5` field. Project and media timeline durations also
changed to `33333333` ticks.

The second keyframe remained a 1.0 sentinel at source time 5.0. The meaning and
generation algorithm for the `MD5` value are not yet proven, so uniform-speed
writing is not authorized despite the surrounding duration math being clear.

### Controlled pitch, reverse, and speed-ramp changes

Turning Maintain Pitch off on the normalized linked pair added
`speedWithPitch: true` to only the type-2 audio clip. The inverted naming is
important: absence displayed as Maintain Pitch on, while `true` displayed it
off and lets pitch follow speed. No other semantic field changed.

Turning Reverse Speed on set `speed.reverse: true` on both linked clips. Because
the visual clip already carried a one-second Vortex In animation, Filmora also
mirrored every visual animation map across the 3.3333333-second clip. The ramp
became an equivalent Vortex Out at seconds 2.3333333 to 3.3333333, and opacity
used the corresponding 23,333,333 to 33,333,333 tick range. All affected
derivatives changed sign and all animation MD5 values were regenerated.
Reverse is therefore not safely modelled as a lone Boolean when animation is
present.

Applying a Speed Ramping preset warns that it will override Uniform Speed. The
controlled preset saves confirmed that it then:

- clears reverse and the explicit `speedWithPitch` field;
- writes the same `speed.speedParam` curve to linked audio and video;
- uses `Version: 3`, `ParameterType: 0`, and `Interpolation: 9`;
- changes both clips' `tlEnd` and `outPoint` to the curve-integrated duration;
- retimes every existing visual animation keyframe to preserve source-relative
  placement.

On the five-second source, the stock curves were:

| Preset | `_time:_value` points | Result ticks |
| --- | --- | --- |
| Montage | `0:0.9`, `0.5:0.9`, `2.5:6.8`, `3.25:0.3`, `4:1`, `5:1` | `34401502` |
| Hero | `0:1`, `0.25:1`, `1.75:5.5`, `2.25:0.5`, `2.75:0.5`, `3.25:5.5`, `4.75:1`, `5:1` | `27564103` |
| Bullet Time | `0:5.2`, `2:5.2`, `2.3:0.5`, `2.7:0.5`, `3:5.2`, `5:5.2` | `17797572` |
| Jumper | `0:0.6`, `2.15:0.6`, `2.5:6`, `2.85:0.6`, `5:0.6` | `73787878` |
| Flash In | `0:5.2`, `2:5.2`, `3:1`, `5:1` | `27071961` |
| Flash Out | `0:1`, `2:1`, `3:5.2`, `5:5.2` | `27071960` |

Each point also has preset-specific left/right derivatives and the payload has
an opaque MD5. The one-tick Flash In/Out duration difference is retained as an
observation, not rounded away. Custom ramp editing, the Customize card, and AI
frame-interpolation modes remain open. No speed writer is authorized.

### Controlled Basic Color temperature change

Repeating Color > Basic > Temperature from 10 to 20 changed only
`u_temperature.fxParam.unValue` from `10.0` to `20.0` under the AdjustColor
effect with ID `662E16ED-4524-4D13-AAE9-11DBA0C63E17`. The parameter used
`paramType: 3`, and the stored value matched the UI directly. The normalized
effect also exposed enable flags for Color, white balance, Light, LUT, HSL,
Vignette, and Auto Color, but their enum semantics are not inferred from this
temperature experiment. First-use insertion and keyframed color remain open.

The rest of the visible Basic Color surface was then repeated on the same
normalized node. Every control changed exactly one `paramType: 3` scalar and
stored the UI number directly:

| Filmora control | Parameter |
| --- | --- |
| Tint | `u_tint` |
| Vibrance | `u_vibrance` |
| Saturation | `u_saturation` |
| Exposure | `u_exposure` |
| Brightness | `u_brightness` |
| Contrast | `u_contrast` |
| Highlight | `u_highLight` |
| Shadow | `u_shadow` |
| White | `u_whiteLevel` |
| Black | `u_blackLevel` |
| Vignette Amount | `amount` |
| Vignette Size | `size` |
| Vignette Roundness | `roundness` |
| Vignette Feather | `feather` |
| Vignette Exposure | `exposure` |
| Vignette Highlight | `highlights` |

Sharpen is the exception to the shared AdjustColor node. It lives in a separate
effect with ID `616D7BAC-39DB-415A-9EEA-798678A43617`, display `Sharpen`, and
parameter `amount`. Its 10-to-20 repeat was otherwise the same direct scalar
change. All 17 repeat pairs, including Temperature, passed the format eval.

These observations prove existing-parameter replacement, not the valid range
of every control, section enable/disable semantics, presets, auto white
balance, LUT selection, HSL, or Curves.

### Controlled Basic Color first-use insertion

Applying Color > Basic > Light > Exposure to a clip with no prior color effect
inserted one `AdjustColor` effect in the existing color effect chain. Filmora
also materialized its normal Color and Mask holding chains, but did not add
media or duplicate the clip. The inserted effect used the same stable ID and
parameter shape as the repeat experiments: `u_exposure` was a `paramType: 3`
scalar storing the UI value directly (`10.0`). The generated project passed
the format evaluator and Filmora Save As round trip. This confirms first-use
insertion for Basic Color/Light only; other color surfaces and keyframes remain
unverified.

### Controlled HSL channel changes

The HSL panel exposes eight color chips. Red Hue, Saturation, and Luminance each
repeated from 10 to 20 as one direct AdjustColor scalar:

```text
Red_hueVal
Red_satVal
Red_brightnessVal
```

Hue repeats across the other seven chips confirmed the remaining serialized
prefixes: `Orange`, `Yellow`, `Green`, `Aqua`, `Blue`, `Purple`, and `Magenta`.
In particular, Filmora's cyan-colored chip uses `Aqua_hueVal`, not `Cyan`.
All values used `paramType: 3` and stored the UI number directly. A controlled
Orange repeat from saturation `15` to `27` added no new structure and changed
only `Orange_satVal`, confirming the same direct scalar rule outside the Red
channel. A second controlled Orange repeat from luminance `15` to `27` changed
only `Orange_brightnessVal`, confirming the brightness/luminance suffix rule as
well. These scalar observations are mapped. The guarded `replace_clip_hsl`
writer supports one existing static scalar at a time; it does not synthesize
first-use fields or touch keyframes.

### Controlled RGB Curves change

The Curves effect has ID `0FDB786D-A9A9-4ED7-9964-AC6954FB441A` and display
`rgbcurve`. Adding a midpoint to the white/luma curve and moving it upward on a
repeat save changed three `paramType: 6` JSON-string parameters:

```text
yKnots
yKnot_First_Controls
yKnot_Second_Controls
```

`yKnots` held the endpoints plus the edited midpoint. The two control arrays
held derived Bezier handles, and both changed when the one visible point moved.
The untouched red, green, and blue channels use the same triplet with `r`, `g`,
and `b` prefixes. This means curve automation must reproduce Filmora's handle
derivation rather than changing only the visible knot. No curve writer is
authorized yet.

### Controlled Hue/Saturation Curves change

The lower Curves panel is a separate effect with ID
`video/effect/curvecolor`, display `CurveColor`, and a `curve_color` array. It
serializes six named JSON-string curve objects:

```text
ICurveColor::Hue2Hue
ICurveColor::Hue2Sat
ICurveColor::Hue2Lum
ICurveColor::Lum2Sat
ICurveColor::Sat2Sat
ICurveColor::Sat2Lum
```

Moving one Hue-vs-Sat midpoint upward changed only the `Hue2Sat` object. The
point stayed at hue position `180.0`; its value changed from `1.63736260` to
`1.83516479`, and the matching left/right control values changed with it. The
object also declares explicit X/Y bounds, steps, selected point index, and
control arrays. This repeat proves the routing and payload shape, but not every
mode's point/control derivation, so no writer is authorized.

### Controlled Color Wheels changes

Color Wheels use effect ID `5C720A04-AC9C-4DF3-811D-EDB3C1B0D14A`, display
`ColorWheel`. Repeating the visible red numeric component from 0.25 to 0.50 on
each wheel changed three parameters per wheel:

| Wheel | Prefix | Changed parameters |
| --- | --- | --- |
| Shadows | `lift` | `lift_red`, `lift_saturation`, `lift_lightness` |
| Midtones | `gamma` | `gamma_red`, `gamma_saturation`, `gamma_lightness` |
| Highlights | `gain` | `gain_red`, `gain_saturation`, `gain_lightness` |

For all three, the visible red value and stored red/saturation values matched
directly, while lightness changed from `0.0833333358168602` to
`0.1666666716337204`. This proves that Filmora derives multiple stored wheel
parameters from one visible component; they are not independent RGB scalars.
Green, blue, the outer luminance controls, negative values, and the full
conversion model remain open. No writer is authorized.

A second controlled Midtones repeat from visible red `0.75` to `0.50` changed
only `gamma_red` and `gamma_saturation` from `0.75` to `0.50`, plus
`gamma_lightness` from `0.25` to `0.1666666716337204` (approximately one-third
of the visible red value). Both the baseline and after copy passed
`eval-format`; this strengthens the positive-red conversion evidence without
closing the remaining channel and direction cases.

A controlled Green first-use edit inserted `gamma_green` and derived hue,
saturation, and lightness fields. From that normalized save, Green `0.50 → 0.25`
changed `gamma_green` directly but also changed `gamma_hue` `40.00008 → 20.00004`,
`gamma_saturation` `0.9790566 → 0.7981336`, and
`gamma_lightness` `0.4166667 → 0.3333333`. The nonlinear derived values make
formula invention unsafe; no Color Wheels writer is authorized.

### Controlled Animation keyframe presets

Animation > Keyframe Presets > Fade In requires a double-click; a single click
only selects the card and produced no semantic project change. A controlled
apply, Undo, and Redo isolated one field inside the visual clip's `pipBuf`:

```json
{
  "Opacity": 100.0,
  "OpacityKeyFrame": {
    "Version": 3,
    "ParameterType": 0,
    "keyframeSets": [
      {"_time": 0.0, "Interpolation": 1, "_value": 0.0, "_rightDerivative": 0.00001},
      {"_time": 10000000.0, "Interpolation": 1, "_value": 100.0, "_leftDerivative": 0.00001}
    ],
    "MD5": "712a3850c4397ef473f8cda30cbac193"
  }
}
```

Undo restored `OpacityKeyFrame` to an empty string. Redo restored the exact
one-second 0-to-100 opacity ramp and increased `pipBufSize` from 131 to 415.
This confirms opacity keyframe routing, timing units, interpolation, and the
static opacity scale. The MD5 generation remains opaque, so preset/keyframe
writing is not authorized.

The remaining built-in cards were then applied independently from the same
Undo-produced no-preset baseline. This matters: applying presets sequentially
does not reliably remove every keyframe from the previous preset. Filmora can
therefore produce a hybrid payload if experiments are chained.

Transform animation is stored on the clip's existing transform effect in
`paramMapList`. Each entry has `key: 3`, a parameter name, and a JSON keyframe
payload with the same `Version: 3`, `ParameterType: 0`, `Interpolation: 1`, and
opaque `MD5` shape as opacity animation. Unlike `OpacityKeyFrame`, transform
`_time` values are seconds rather than 10,000,000-tick units.

The fixture already had Scale X/Y `70`, Position X `0.3828125`, Position Y
`0.60416669`, and Rotation `0`. The independently captured presets produced:

| Preset | One-second result |
| --- | --- |
| Fade Out | opacity `100 -> 0`; no transform map |
| Slide Right | Position X `-0.6171875 -> 0.3828125` |
| Slide Left | Position X `1.3828125 -> 0.3828125` |
| Slide Up | Position Y `1.60416675 -> 0.60416669` |
| Slide Down | Position Y `-0.39583331 -> 0.60416669` |
| Vortex In | opacity `0 -> 100`, Scale X/Y `0 -> 70`, Rotation `360 -> 0` |
| Vortex Out | opacity `100 -> 0`, Scale X/Y `70 -> 0`, Rotation `0 -> 360` |
| Zoom In | Scale X/Y `0 -> 70`; opacity stays `100` |
| Zoom Out | Scale X/Y `70 -> 0`; opacity stays `100` |

Every transform preset also writes unchanged two-point maps for Scale X,
Scale Y, Position X, Position Y, and Rotation. The Pause preset is different:
it writes four points at seconds `0`, `1`, `2`, and `3`. Position X is
`-0.6171875, 0.3828125, 0.3828125, 1.3828125`, which means slide in, hold for
one second, then slide out. Its other transform values and all four opacity
values remain constant.

The observed +/- `1.0` position offsets are relative to this fixture's stored
position, not yet proven as universal frame-width units. Derivatives and every
payload MD5 must remain opaque. No animation writer is authorized.

### Compositing control caveat

Filmora displayed Basic > Compositing > Blend Mode and Opacity for the only
visual clip on the base video track. Attempts to enter or drag Opacity from 100
to 50 produced no persisted semantic change: Save As changed only the known
timeline save token and `pipBuf.Opacity` remained `100.0`. Dragging the media
asset into blank space above that track also did not auto-create an overlay
track in this layout.

This negative control matters. Visibility of the Compositing UI is not proof
that its controls apply to a base-track clip. Static opacity and Blend Mode
remain open until a controlled project contains a genuine upper-track overlay;
the existing `pipBuf` field names are structural evidence only.

On a disposable genuine upper-track overlay, changing Compositing > Opacity
from 100 to 50 and then from 50 to 25 changed only the embedded
`pipBuf.Opacity` number and its `pipBufSize` byte count. Both generated
projects passed the format evaluator. The guarded `replace_clip_opacity`
writer supports this existing static overlay field only; keyframed opacity and
first-use insertion remain unsupported. Blend Mode still has no controlled
pair.

Focusing and saving the same overlay's Blend Mode with the visible value still
set to Normal normalized the embedded `pipBuf.BlendMode` from numeric `0` to
the string `"Normal"`. This is a serialization-normalization observation, not
a controlled non-Normal mode change, so Blend Mode remains open.

### Controlled Background blur

Basic > Background is separate from Compositing and did persist on the same
base-track clip. Enabling the default Blur background added only:

```json
"backgroundFillEnable": true
```

The clip already carried `backgroundFillBluredness: 20` while Background was
off. Selecting the visible 40% preset changed that integer from `20` to `40`.
Turning Background off again removed `backgroundFillEnable` but retained the
chosen `backgroundFillBluredness: 40`, so absence of the enable field is the
observed off state and the last configuration survives.

Changing Background Type from Blur to Color on a normalized disposable copy
added only `backgroundFillType: 2`, apart from the known opaque timeline token;
both copies passed `eval-format`. The Color panel then exposes a separate color
payload, which has not been changed yet. Other Background types, Blur Style,
custom blur strength, color/image payloads, and Apply to All remain open.
Existing-field replacement is structurally
simple. The guarded `replace_clip_background_blur` writer now supports an
existing clip's strength and enable state without synthesizing first-use
holding chains; its generated copy passed format evaluation and the Filmora
sample round-trip gate.

### Controlled audio volume-gain change

On a disposable type `2` audio clip, the first Basic Audio volume change from
`0.00 dB` to `3.00 dB` added a `VolumeGain` parameter under the existing
`audio/effect/volume` node:

```json
{
  "name": "VolumeGain",
  "fxParam": {"paramType": 2, "unValue": 3.0}
}
```

That first save also inserted a default `audio/effect/equalizer` node, so it is
normalization evidence rather than permission to synthesize a volume graph.
From the normalized save, changing `3.0` to `6.0` and then `6.0` to `-3.0`
changed only `fxParam.unValue` plus the known per-save timeline token.

A narrow writer changed an already-present value from `3.0` to `4.0` with one
semantic diff. Filmora 15.6.4.11894 opened the generated copy and displayed
`4.00 dB`; Save As retained `4.0`, all format probes passed, and the saved copy
reopened. This proves replacement only. A default clip with no serialized
`VolumeGain`, fades, balance, equalizer settings, and automation remain outside
the writer contract.

### Controlled audio balance change

On the same disposable type `2` audio clip, Sound Balance values of `25`, `50`,
and `-50` stored under the existing `audio/effect/volume` node as a `Balance`
parameter with `paramType: 2` values `0.625`, `0.75`, and `0.25`. The repeated
conversion is `stored = (ui + 100) / 200`. The guarded
`replace_clip_audio_balance` writer supports only this existing parameter and
rejects missing or stale targets; first-use insertion remains unsupported.

### Controlled audio fade-in change

On a disposable five-second type `2` audio clip, the first Basic Audio fade-in
change from `0.00 s` to `1.00 s` added this parameter under the existing
`audio/effect/fade` node:

```json
{
  "name": "FadeInTime",
  "fxParam": {"paramType": 2, "unValue": 1.0}
}
```

That first Save As also regenerated and reordered unrelated effect and clip
metadata, so it does not authorize insertion. From the normalized save, changing
`1.00 s` to `2.00 s` changed only `fxParam.unValue` plus the known per-save
timeline token and project metadata.

A narrow writer changed an already-present value from `1.0` to `1.5` with one
semantic diff. Filmora 15.6.4.11894 displayed `1.50 s` on the generated copy,
Save As retained `1.5`, all format probes passed, and a full quit/relaunch
reopened the saved copy with `1.50 s` still visible. This proves positive
replacement up to the clip duration only. Insertion, zero/removal, curve shape,
and automation remain outside the writer contract.

### Controlled audio fade-out change

On the same disposable type `2` audio clip, the first Basic Audio fade-out
change from `0.00 s` to `1.00 s` added a second parameter under
`audio/effect/fade`:

```json
{
  "name": "FadeOutTime",
  "fxParam": {"paramType": 2, "unValue": 1.0}
}
```

The normalized repeat from `1.00 s` to `2.00 s` changed only that parameter's
`fxParam.unValue` plus known save metadata. A narrow writer then changed the
existing value to `1.5` with one semantic diff. Filmora 15.6.4.11894 displayed
`1.50 s`, Save As retained the value, and a full quit/relaunch reopened the
saved copy with `1.50 s` still visible. This proves independent positive
replacement up to clip duration. Insertion, zero/removal, curve shape, and
automation remain outside the writer contract.

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

Two narrow writers reproduced those UI edits on disposable copies. The duration
writer changed only the two `postTransition.tlBegin` values from `30,000,000` to
`40,000,000`; the removal writer deleted only the paired `postTransition`
objects. Filmora 15.6.4.11894 opened both generated projects, saved each to a new
path, preserved the requested state, and reopened both saved copies. The saved
duration copy retained the matched `40,000,000` through `50,000,000` ranges and
the saved removal copy contained no transitions.

This only proves an already-present linked visual Dissolve and audio fade with
the exact IDs above, matching owner ranges, and transitions contained at the end
of those clips. It does not authorize transition insertion, another transition
asset, a pre-transition, or an unlinked edit.

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
