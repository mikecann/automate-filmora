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
   python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
   ```

7. Separate meaningful field changes from timestamps, serials, UUIDs, and save
   noise by repeating the experiment.
8. Add the confirmed observation to `docs/format/` and add a synthetic regression
   test.

## First experiments

- Change only one title's text.
- Change only the title font size.
- Move a title by a known amount.
- Add one empty video track.
- Split one media clip at an exact frame.
- Change one clip's volume.
- Add and remove one transition.
- Create one compound clip and then unpack it in Filmora.

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
