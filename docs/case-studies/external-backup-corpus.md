# External backup corpus survey

Date: 2026-07-16

This is a sanitized, read-only survey of the external backup's video tree. No
project names, absolute paths, title text, media, or raw projects are committed.
The private path-to-sample report remains under ignored `work/`.

## Scope and relevance

The survey found 204 structurally unique projects:

- 166 `.wfp` files and 38 `.wfpbundle` files;
- 21 distinct modified-with builds from `14.0.8.9637` through
  `15.6.10.20319`;
- 56 Filmora 15 projects, all saved on Windows;
- 148 Filmora 14 projects, including 11 macOS projects;
- three Windows projects from `15.6.10.20319`, the closest build cohort to the
  current macOS `15.6.4.11894` research fixture.

The containers totalled 238.8 GB because bundles carry copied source media. The
survey fingerprinted and inspected only each bundle's embedded WFP. It did not
read the bundled footage.

All 204 project archives mapped successfully. One Filmora
`14.4.13.12098` bundle failed only the `sourceUuid` resolution probe with one
unresolved value; its archive, timeline routing, cache copies, and other
identifiers remained valid. Treat that as a legacy compatibility observation,
not evidence that the current resolver is wrong.

There is no exact `15.6.4.11894` project in this backup corpus. The Filmora 15
files are strong cross-project evidence, but Windows/macOS and patch-build
differences still require controlled tests before any writer uses a field.

## Clip shapes beyond AI Tips

The corpus expanded the observed canonical clip types from six to ten:

| Type | Projects | Canonical occurrences | Structural evidence |
| --- | ---: | ---: | --- |
| `1` | 201 | 17,106 | ordinary visual media shape |
| `2` | 202 | 18,062 | ordinary audio media shape |
| `4` | 152 | 3,303 | title shape with `scriptBuf` |
| `6` | 144 | 641 | visual nested placement shape |
| `7` | 152 | 3,075 | nested placement shape |
| `8` | 36 | 101 | effect or adjustment asset shape |
| `14` | 15 | 387 | legacy screen-recording visual shape |
| `15` | 11 | 235 | legacy screen-recording audio shape |
| `16` | 144 | 641 | audio nested placement shape |
| `26` | 2 | 2 | pen/path graphic shape |

Type `8` is not simply an adjustment layer enum. Eighty-two instances had
`adjustLayer`, including pixelate adjustment graphs, while other type `8`
instances carried stock overlay effects without that flag.

Both type `26` instances came from Filmora `15.5.3.19727` variants of the same
editing subject. They had `serviceType: "pen"` and a `graphic` effect chain with
path clear, rectangle, stroke, fill, trim, shape render, shadows, and path render
effects. This is good evidence for a path-graphic family, but too narrow to assign
a universal enum name.

Types `14` and `15` appeared only in Filmora 14.0/14.3 projects. Their clip fields
include keyboard-overlay, mouse-highlight, and mouse-audio controls, so they are
legacy screen-recording variants rather than current writer targets.

## Serialized structures

The mapper now parses JSON and XML strings without retaining values. The corpus
revealed these repeated schemas:

- `pipBuf` in 202 projects: blend mode, blender name, enable, opacity, and
  opacity keyframe fields;
- `speed.speedParam` in 202 projects: keyframe sets plus optional freeze and
  reverse fields;
- audio ducking and volume parameter JSON in 202 projects;
- effect parameter keyframe JSON in 127 projects;
- title animation XML in seven projects, including Filmora 15.4 and 15.6, using
  `AnimationParam` / `AnimationConfig` elements and motion, transition,
  interpolation, duration, property, start, and end attributes;
- six colour-curve JSON variants in three near-current projects;
- path/custom-mask JSON in the two type `26` projects;
- `intelligenceSegmentSmartRemoveSerializeToJson` on 17 visual clips in one
  Filmora `15.3.3.18203` project.

The smart-remove object contained frame-rate, in/out, feather, colour, invert,
preview, working-mode, and enable fields. Those names are observed serialization,
not a licence to synthesize mask files. The associated mask reference remains an
opaque dependency.

## Markers, proxies, and effect coverage

Every Filmora 15 project had `allMarkersInfo.beatDetectInfo` entries in one or
more `extra.json` documents. Thirteen Filmora 15 projects also had marker arrays
with `name`, `comments`, `position`, and `color`. A representative marker used
the normal 10,000,000-ticks-per-second timebase. The UUID-keyed marker group and
beat maps are now normalized so reports do not retain their opaque IDs.

Forty-eight of the 56 Filmora 15 projects included `proxyFilename` on visual
clips. Proxy paths are optional cache/dependency references and remain redacted.

The aggregate found 78 effect ID/display pairs and 52 transition
position/ID/display combinations. High-coverage effects absent from the AI Tips
fixture included audio enhancer, speech enhance, human/hair segmentation, and
newer inner-shadow chains. The transition mapper already handles the additional
push, slide, fade, glitch, and audio-effect transition shapes generically.

## What this survey does not prove

- The projects are correlated examples from one editor, not an independent
  random sample of Filmora usage.
- Repeated effect chains may be defaults or copied templates rather than explicit
  user changes.
- Filmora 14 observations are legacy hypotheses for Filmora 15.
- Windows projects can establish structure but not macOS loadability.
- Enum meanings still need minimal before/after UI experiments.

The practical result is broader read-only coverage and better experiment
selection, not permission for a generic writer.

## Local macOS backup refresh

A later read-only survey of four exact-build copies from the local Filmora Mac
backup (`15.6.4.11894`, macOS) found no evaluator failures. It added three
effect families to the research inventory that were not present in the AI Tips
fixture: `ColorBlur`, `Allpurpose Position`, and `Text Dropout`. It also exposed
additional Push-family transition IDs. These are corpus observations only; the
new effect payloads have not had controlled UI edits and remain non-writable.

The transition names were `Push Down` (`57EA5A5B-7EFA-4787-9199-31425E26AF00`),
`Push Left` (`B5DA95B1-733E-43C1-9A8E-AA46921E46B0`), `push`
(`925C36FB-9EE1-4fca-899F-549D8328F2DC`), `Diagonal in`
(`ABAF9A79-678E-453D-94BC-AAC165DE2D45`), and `Cut Slide Transition 03`
(`7DA29585-DDAB-4345-84C0-8F511FC7C17A`). Their duration payloads remain
subject to the existing transition-family experiment boundary.

The newly observed typed fields were `ColorBlur.uEclosion` (enum),
`uEnhance`, `RBlurIntension`, and `BBlurIntension` (scalars), `Text Dropout`
`Speed` and `Scale` (scalars), and `Allpurpose Position.position_y`, `rotate`,
and `scale` (scalars). Allpurpose Position also carries opaque keyframe JSON,
so replacing its visible defaults would not be safe without reproducing the
derived curves and payload checksums.

Across the four exact-build backup copies, each of these three effect families
occurred in only one project and each exposed one parameter tuple. They are
therefore useful schema examples, not evidence of universal defaults or valid
value ranges.
