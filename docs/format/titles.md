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
