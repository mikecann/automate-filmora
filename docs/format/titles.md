# Title observations

Filmora title clips use clip `type: 4` and store an escaped JSON object in the
`scriptBuf` string. Decode the outer timeline JSON, then decode `scriptBuf` again.

Observed useful fields inside `scriptBuf`:

- `Text`: displayed title string.
- `TextData[0].Basic.FontName`: font family.
- `TextData[0].Basic.FontSize`: font size.
- `TextData[0].Basic.TextColor`: colour values.
- `TextData[0].CharSpace`: character spacing.
- `PosX` / `PosY`: normalized position.
- `ScaleX` / `ScaleY`: title box scale.
- `Animation.ID`: numeric title animation identifier.
- `ViewSize` and `Aspect`: authoring canvas.

The full observed document also has background, edge, glow, gradient, curve,
layout, texture, rotation, record, alignment, and feature-version structures.
Use `filmora_wfp map --json` to inspect their normalized paths and value ranges.
Most fields have not been tied to a single UI control yet.

Across 46 title clips in one project, every declared `scriptBufSize` equalled the
UTF-8 byte length of `scriptBuf` plus one. This is now a required format eval.
All 46 also had identical `Text` and `TextData[0].CharData` strings. The
format eval rejects a mismatch between those two readable text representations.

Title presets may be a nested graph rather than one clip. In the AI Tips sample a
section card contains:

1. a compound timeline placed on the main edit;
2. an animated background media resource;
3. a nested title preset timeline;
4. separate heading and subtitle clips with staggered starts;
5. transitions and four audio effects.

Changing title text is a promising first write experiment because `Text` and
`TextData[0].CharData` are directly readable. Both fields must be tested together,
and every edit must target a copied project.

## Basic Title insertion

Adding one Basic Title to a disposable project produced a graph rather than a
single parent clip:

1. a type `7` compound placement in the parent timeline;
2. a new nested timeline;
3. a type `4` title clip inside that timeline;
4. a new visual track and paired empty audio track in the parent.

The default five-second title inserted at 2.48 seconds extended the project to
7.48 seconds. Its transform effect duplicated script geometry: `Position_y`
matched `PosY`, while effect `Scale_x` and `Scale_y` were script `ScaleX` and
`ScaleY` multiplied by 100.

## Controlled title-text edits

A later controlled pass used the Basic Title properties panel and its explicit
`Apply Changes` action. Changing `Text Here` to `FORMAT MAP TITLE` changed:

- `scriptBuf.Text`;
- `scriptBuf.TextData[0].CharData`;
- `scriptBufSize`, from 3468 to 3481;
- `scriptBuf.ScaleX`, from `0.1237293556` to `0.2724495530`;
- the transform effect's `Scale_x`, from `12.37293625` to `27.24495506`.

The scale relationship remained exact within float32 precision:

```text
transform Scale_x = scriptBuf ScaleX * 100
```

The first properties-panel application also normalized the document heavily,
including effect instance IDs and ordering of several keyed arrays. That noise was
not caused solely by the new text. A second Save As, changing the normalized title
from `FORMAT MAP TITLE` to the same-byte-length `FORMAT MAP TITLX`, changed exactly
two semantic paths: `Text` and `TextData[0].CharData`. `scriptBufSize`, both scale
values, and every other field stayed unchanged.

This confirms the two mirrored text fields and byte-size invariant. It does not
yet prove a safe generic auto-sizing algorithm for arbitrary replacement text.
The existing compound-card cloner remains the only title writer because its
callers supply explicit scale and font metrics.

## Observed sizing relationships

Across five AI Tips heading cards, measuring the bundled Bebas Neue font at the
stored `FontSize` produced this exact relationship within rounding:

```text
ScaleX = rendered text width / 700
ScaleY = FontSize / 360
```

The scale values and the matching transform-effect percentages are serialized at
float32 precision. Subtitle sizing is less exact and still requires explicit
values in write experiments.
