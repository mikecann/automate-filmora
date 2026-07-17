# Reverse-engineering experiments

Use controlled before/after saves. Do not infer a field from one complicated edit.

## Protocol

1. Create the smallest possible Filmora project.
2. Save it as `before.wfp` and close or pause editing.
3. Change exactly one property in Filmora.
4. Save as `after.wfp` using the same Filmora build.
5. Record the Filmora build, OS, exact UI control, old value, and new value.
6. Run:

   ```bash
   python3 -m filmora_wfp map before.wfp --json > work/before-map.json
   python3 -m filmora_wfp map after.wfp --json > work/after-map.json
   python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
   ```

7. Separate meaningful field changes from timestamps, serials, UUIDs, and save
   noise by repeating the experiment.
8. Add the confirmed observation to `docs/format/` and add a synthetic regression
   test.

Run `eval-format` on both files as a cheap corruption and format-drift gate:

```bash
python3 -m filmora_wfp eval-format before.wfp
python3 -m filmora_wfp eval-format after.wfp
```

## First experiments

- Change only one title's text.
- Change only the title font size.
- Move a title by a known amount.
- Add one empty video track.
- Split one media clip at an exact frame.
- Change one clip's volume.
- Add and remove one transition.
- Create one compound clip and then unpack it in Filmora.

## Completed Filmora 15.6.4 experiments

The disposable sequence now covers blank save, media import, timeline insertion,
linked A/V split at an exact time, Basic Title insertion, and a Filmora-native
round trip of a generated title-card copy. A second controlled batch covered
track lock/mute persistence, source-clip rotation, linked Dissolve insertion,
transition duration, and transition removal. See
[`format/observations-15.6.4.md`](format/observations-15.6.4.md) for the sanitized
results.

Still open:

- more transition modes and transition parameters;
- more effect parameters and effect insertion/removal;
- track creation, reorder, visibility, and solo;
- compound creation and unpacking;
- repeated experiment on the next Filmora build.

### 2026-07-16 external corpus survey

The read-only `survey` command mapped 204 unique projects from the external
backup's video tree. It separated 56 Filmora 15 projects from 148 legacy Filmora
14 projects, handled 38 media-heavy bundles through their embedded WFP, and found
no archive parser failures. The closest cohort was three Windows
`15.6.10.20319` projects, not an exact match for the macOS `15.6.4.11894`
fixture.

Corpus evidence is useful for finding new shapes and choosing controlled tests.
It does not confirm enum semantics. See
[`case-studies/external-backup-corpus.md`](case-studies/external-backup-corpus.md).

The Basic Title text experiment is complete for mirrored text serialization and
byte-size handling. Arbitrary text auto-sizing remains open because Filmora also
updates `ScaleX` and the transform effect's `Scale_x` when the replacement width
changes.

### 2026-07-16 controlled batch

- Filmora: `15.6.4.11894`
- macOS: `26.5.2 (25F84)`
- source: disposable copy under ignored `work/`; no user project opened or written
- rotation pair: `0b1f9145...` at 0 degrees, `29fa1e4d...` at 10 degrees
- transition baseline: `021191a5...`
- two-second Dissolve plus audio fade: `a042309f...`
- one-second linked duration: `4286fa0d...`
- transition removed by undo: `73696a37...`

The exact controls were Basic > Rotate, Transitions > Dissolve > Apply, the
timeline Duration button, and Undo. Every frozen snapshot passed `eval-format`.
The track Lock and Mute controls reverted after reopening their saved copies, so
they are recorded as session-state observations rather than writer targets.

## Writer acceptance gate

A writer is acceptable only when it:

- refuses to overwrite the input;
- changes a narrow, named property;
- preserves unrelated archive members;
- produces valid JSON and resolvable timeline references;
- opens in the originating Filmora build;
- preserves the intended edit after Filmora saves the project again.

## Repeatable title-card regression eval

Keep the real fixture and generated files outside the repository. For each new
Filmora build:

1. Record the Filmora build, macOS version, fixture SHA-256, and template outer
   timeline ID.
2. Generate exactly one card with unmistakable text such as `LOAD TEST`.
3. Run the synthetic suite:

   ```bash
   python3 -m unittest discover -s tests -v
   ```

4. Run the source-aware eval and retain its JSON output:

   ```bash
   python3 -m filmora_wfp audit-title-card-copy source.wfp generated.wfp \
     --check-media --json
   ```

5. Open the generated file in Filmora. Fail the eval if Filmora reports an
   incompatible project, the new card is absent, or the expected text does not
   render.
6. Save the opened project to another new path. Run `validate`, then diff the
   generated and Filmora-saved copies. Do not run the source-aware copy audit on
   the Filmora-saved file because Filmora legitimately rotates protected metadata.
7. Repeat with the multi-card fixture to catch identifier-allocation collisions.

The source-aware audit is the automated pass/fail result. Application open,
render, and save remain required compatibility gates because the WFP schema is
undocumented.

## Headless edit-plan API milestone

API version 1 and edit-plan schema version 1 wrap the existing verified
title-card cloner. Target discovery, strict plan parsing, source fingerprinting,
dry-run explanation, application, and the source-aware audit all run without
opening Filmora. The result keeps `filmora_round_trip_performed` false until an
application check actually happens.

## Equal-length title replacement acceptance

Filmora 15.6.4.11894 on macOS accepted a generated copy that changed only the
two mirrored title values inside one type-4 clip's `scriptBuf`. The controlled
fixture changed `FORMAT MAP TITLX` to `FORMAT MAP TITLY`, preserving the complete
serialized script byte length. The source-aware audit reported exactly the two
intended semantic changes and `eval-format` passed.

Filmora opened the generated project and visibly rendered `FORMAT MAP TITLY`.
It then saved the project to a second new path, the saved copy passed every
format probe, retained the new text, and reopened successfully. Filmora rotated
and reordered extensive protected metadata during Save As, so those differences
remain normalization noise rather than writer requirements.

API version 2 and plan schema version 2 now expose this as
`replace_title_text`. Schema version 1 remains immutable and supported. The
operation requires a source hash, exact clip UID, exact old text, and refuses a
replacement unless the actual serialized `scriptBuf` byte length is unchanged.

## Existing rotation replacement acceptance

Using the normalized 10-degree fixture as source, the narrow rotation writer
changed the selected type-1 video clip's existing `Rotation` value from `10.0`
to `20.0`. The source-aware diff contained exactly one semantic change under the
clip's `video/effect/transform`, and `eval-format` passed.

Filmora 15.6.4.11894 opened the generated copy and visibly rendered only the
first source clip at 20 degrees. Save As preserved the value, the Filmora-saved
copy passed every format probe, and it reopened successfully. Missing Rotation
parameters remain unsupported; the evidence only covers replacement of an
already-present value.

## Existing linked transition acceptance

Using the controlled two-second Dissolve/audio-fade fixture, the duration writer
moved exactly the two `postTransition.tlBegin` values from `30,000,000` to
`40,000,000`. Using the controlled one-second fixture, the removal writer deleted
exactly the two paired `postTransition` objects. Both outputs passed the
source-aware audit and every format probe.

Filmora 15.6.4.11894 opened both generated copies and saved each to another new
path. The one-second saved copy retained both matched transition ranges, the
removal copy contained none, both passed `eval-format`, and both reopened. The
writers remain restricted to the exact observed visual Dissolve and linked audio
fade IDs, matching type-1/type-2 owner clips, and an existing end-contained pair.

API version 3 and plan schema version 3 expose the accepted rotation and linked
transition operations with selectors discovered from the current source. Earlier
published schemas remain unchanged and supported.

The next controlled Filmora batch should evaluate operations in this order:

1. move or trim a linked A/V pair;
2. split a linked A/V pair and verify every regenerated identifier.

Each operation stays absent from the public plan schema until its generated copy
passes the writer acceptance gate above. Track operations and new effect
insertion remain later work because their persistence or identifier behaviour is
less certain.
