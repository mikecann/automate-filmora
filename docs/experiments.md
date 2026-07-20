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
transition duration, transition removal, a linked A/V timeline move, and linked
A/V trims at both edges. See
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

## Existing linked A/V move acceptance

A same-session undo/redo pair isolated the move of one transition-free linked
type-1/type-2 source pair by one second. Both clips retained their source range,
source UUID, stream selection, effects, and instance IDs. Only these four values
changed:

- visual `tlBegin`: `24,800,000` to `34,800,000`;
- visual `tlEnd`: `50,000,000` to `60,000,000`;
- audio `tlBegin`: `24,800,000` to `34,800,000`;
- audio `tlEnd`: `50,000,000` to `60,000,000`.

A separate direct UI drag on adjacent clips triggered Filmora's magnetic
overwrite behaviour and removed the second pair. That snapshot is rejected as
move evidence. The writer therefore does not attempt to reproduce magnetic
timeline editing.

The narrow writer reproduced the isolated four-field move on a disposable
project whose title track already extended beyond the requested new end. It
rejects transitions, mismatched pair bounds or sources, same-track overlap, and
any move beyond the existing `project_timeline_duration`. Filmora 15.6.4.11894
opened the generated copy, visibly showed both pairs with the intended one-second
gap, saved it to a new path, and reopened it. The Filmora-saved copy retained
both linked clips at `34,800,000` through `60,000,000` and passed every format
probe.

This operation remains available as a guarded Python primitive and is also
exposed by edit-plan schema version 4. Schema version 3 remains immutable.

## Existing linked A/V end-trim acceptance

Dragging the end of the second linked pair one second earlier shortened both
clips together. A same-session undo/redo comparison reduced the Filmora-native
diff to six semantic changes:

- both `tlEnd` values: `60,000,000` to `50,000,000`;
- both `outPoint` values: `50,000,000` to `40,000,000`;
- both `speed.offsetEnd` values: `5.0` to `4.0`.

The paired `tlBegin`, `inPoint`, `speed.offset`, IDs, sources, effects, and the
serialized `speedParam` remained unchanged. This fixture used forward 1x speed.

The narrow writer reproduces exactly those six fields. It requires matching
type-1/type-2 source and timeline ranges, forward constant 1x speed, matching
decimal offsets, no transitions, and a new end strictly inside the existing
positive range. Filmora 15.6.4.11894 opened the generated copy, visibly showed
the shortened linked pair, saved it to another path, and reopened it. The
Filmora-saved copy retained `tlEnd: 50,000,000`, `outPoint: 40,000,000`, and
`speed.offsetEnd: 4.0` on both clips and passed every format probe.

Like movement, end trim remains a guarded Python primitive and is exposed by
edit-plan schema version 4. Schema version 3 remains immutable.

## Existing linked A/V start-trim acceptance

Dragging the start of the already end-trimmed linked pair one second later
changed the complementary six fields in the same-session normalized diff:

- both `tlBegin` values: `34,800,000` to `44,800,000`;
- both `inPoint` values: `24,800,000` to `34,800,000`;
- both `speed.offset` values: `2.48` to `3.4799999999999995`.

The long decimal was a Filmora UI floating-point artifact. The narrow writer
serialized the exact derived value `3.48` while changing only the same six
fields. Filmora 15.6.4.11894 opened the generated copy, visibly showed the
shortened pair, saved it, and reopened it. The Filmora-saved copy retained exact
`speed.offset: 3.48` on both clips, plus `tlBegin: 44,800,000` and
`inPoint: 34,800,000`, and passed every format probe.

The start writer enforces the same forward constant 1x, matching-pair,
transition-free, and positive-range restrictions as the end writer. Edit-plan
schema version 4 exposes it without changing schema version 3.

## Linked A/V edit-plan API milestone

API version 4 and plan schema version 4 promote the three Filmora-accepted
linked A/V writers. `edit-targets` returns only unambiguous transition-free
pairs with exact source and timeline bounds. Every pair supports guarded moves;
only pairs matching the audited forward constant-1x speed predicate advertise
start and end trims. Dry runs execute the same operation-specific preflight as
the writer, and application still writes a new path and runs its source-aware
audit. Synthetic coverage verifies the exact four-field move and both six-field
trim diffs. Schemas 1 through 3 remain byte-for-byte unchanged and supported.

The next controlled Filmora batch should evaluate:

1. linked splits with user-authored effects and keyframes;
2. linked movement and trimming on more source and track layouts;
3. a multi-operation plan only when a real workflow needs it.

Track operations and new effect insertion remain later work because their
persistence or identifier behaviour is less certain.

## Existing audio clip volume-gain acceptance

The first Basic Audio volume change from the default `0.00 dB` to `3.00 dB`
normalized the disposable audio clip by adding a `VolumeGain` parameter to its
existing `audio/effect/volume` node and inserting a default equalizer node. That
first-use graph change is not a writer target.

Repeating the edit from the normalized save isolated the actual property. The
`3.0` to `6.0` and `6.0` to `-3.0` saves each changed only
`VolumeGain.fxParam.unValue`, aside from the already-classified per-save timeline
token. The parameter uses `paramType: 2`; the UI value is in decibels.

The replacement-only writer changed an existing `3.0` value to `4.0` with one
semantic diff. Its source-aware audit and every format probe passed. Filmora
15.6.4.11894 opened the generated copy and visibly showed `4.00 dB`, saved it to
a new path, retained `VolumeGain: 4.0`, and reopened the saved copy.

API version 6 and immutable plan schema version 6 expose
`replace_clip_volume_gain`. Target discovery lists only audio clips containing
exactly one existing finite `VolumeGain` parameter. It does not claim support
for inserting a missing parameter or recreating Filmora's first-use effect
normalization. Schemas 1 through 5 remain unchanged and supported.

## Existing audio clip fade-in acceptance

On the same disposable five-second clip, the first Basic Audio fade-in change
from `0.00 s` to `1.00 s` added a `FadeInTime` parameter to the existing
`audio/effect/fade` node. That Save As also regenerated and reordered unrelated
effect and clip metadata, so insertion is not a writer target.

Repeating the edit from the normalized save, from `1.00 s` to `2.00 s`, isolated
one semantic property: `FadeInTime.fxParam.unValue` changed from `1.0` to `2.0`,
apart from the known per-save timeline token and project metadata. The parameter
uses `paramType: 2`, and its value matches the UI duration in seconds.

The replacement-only writer changed the existing value from `1.0` to `1.5` with
one semantic diff. Its source-aware audit and every format probe passed. Filmora
15.6.4.11894 opened the generated copy and visibly displayed `1.50 s`, saved it
to a new path, retained `FadeInTime: 1.5`, fully quit, relaunched, and reopened
the Filmora-saved copy with `1.50 s` still visible.

API version 7 and immutable plan schema version 7 expose
`replace_clip_fade_in`. Target discovery lists only audio clips with exactly one
existing positive `FadeInTime` not exceeding the clip duration. The writer also
rejects zero, negative, stale, missing, and over-duration values. Insertion,
and removal by setting zero remain unsupported. Schemas 1 through 6 remain
unchanged and supported.

## Existing audio clip fade-out acceptance

On the same disposable five-second clip, changing Basic Audio fade-out from
`0.00 s` to `1.00 s` added `FadeOutTime` beside the existing `FadeInTime` under
the `audio/effect/fade` node. That first use also performed Filmora save
normalization, so it is evidence for structure but not insertion safety.

Repeating the edit from `1.00 s` to `2.00 s` isolated one semantic property:
`FadeOutTime.fxParam.unValue` changed from `1.0` to `2.0`, apart from the known
per-save timeline token and project metadata. The parameter uses `paramType: 2`
and stores the UI duration in seconds independently of fade-in.

The replacement-only writer changed `1.0` to `1.5` with exactly one semantic
diff. Filmora 15.6.4.11894 displayed `1.50 s`, saved the generated project to a
new path, fully quit, relaunched, reopened that copy, and still displayed
`1.50 s`. Format evaluation also passed on both generated and Filmora-saved
copies.

API version 8 and immutable plan schema version 8 expose
`replace_clip_fade_out`. Target discovery requires exactly one existing positive
`FadeOutTime` no greater than clip duration. The writer rejects zero, negative,
stale, missing, and over-duration values. Insertion and removal remain
unsupported. Schemas 1 through 7 remain unchanged and supported.

## Existing linked A/V split acceptance

The initial 2.48-second split was repeated from a new Filmora Save As baseline.
Both controlled diffs produced the same structural rule: shorten the first
visual/audio halves, clone full second halves at the split point, regenerate
both clip IDs and every nested effect ID, and assign the new halves one shared
fresh key-3 pair UUID. Media-link user data, source UUID, stream selection,
effects, and serialized speed parameters remained otherwise unchanged.

The guarded split writer reproduced those rules on the repeated baseline. Its
source-aware audit passed, as did every format probe. Filmora 15.6.4.11894 opened
the generated project, visibly showed both linked halves, saved it to another
new path, retained `0..24,800,000` and `24,800,000..50,000,000` on both tracks
with exact `2.48` source/offset boundaries, and reopened the saved copy.

### 2026-07-20 dense-project split coverage

Two more copy-only splits used the current 16-minute AI Tips project without
modifying its source. One selected a linked pair on primary tracks 3/4; the other
used different source media on auxiliary tracks 9/10. Both generated projects
passed the source-aware audit and every format probe. Filmora 15.6.4.11894 opened
each generated copy, saved each to a new path, and reopened the saved copy.

The resaved primary project retained paired ranges
`5,550,999,996..5,638,833,329` and
`5,638,833,329..5,726,666,663`. The auxiliary project retained
`3,532,000,000..3,555,333,334` and
`3,555,333,334..3,578,666,669`. Visual and audio source points and decimal speed
offsets met exactly at each split. These cases add different media, long-project
normalization, and non-default track-layout evidence to the repeated minimal
fixture.

API version 5 and immutable plan schema version 5 now expose
`split_linked_av_pair`. Target discovery advertises it only for an unambiguous,
transition-free, forward constant-1x pair that also has the observed matching
key-3 link identifier shape. Explain and apply use the same preflight and
source-aware audit as the accepted Python writer. Schemas 1 through 4 remain
unchanged and supported.
