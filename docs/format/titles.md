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

The text-edit pass did not produce a clean saved after-file, so the exact minimal
set of title-text mutations is still unconfirmed. The existing compound-card
cloner updates both text representations because its output passed a Filmora load
and native-save round trip, but that is evidence for that narrow template only.

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
