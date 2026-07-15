---
name: filmora-project-automation
description: Inspect, diff, document, and safely automate Wondershare Filmora `.wfp` and `.wfpbundle` project files. Use when Codex needs to understand Filmora timelines, media references, compound clips, titles, effects, transitions, controlled before/after saves, project corruption, or a narrowly scoped project-file mutation.
---

# Filmora Project Automation

Treat the format as undocumented and version-specific. Gather evidence from the
actual project and Filmora build before asserting field semantics.

## Safety rules

- Read the source project without modifying it.
- Never overwrite the only copy of a project.
- Do not commit real projects, media, or private absolute paths.
- Keep opaque base64 values and numeric enums unchanged unless a controlled
  experiment proves their meaning.
- Do not run third-party Filmora executables. Inspect source code only.
- If the user requests a mutation, create a new output file and make one narrow,
  named change. The only current writer clones the observed compound title-card
  graph; there is no generic writer.

## Inspect a project

Run from the repository root:

```bash
python3 -m filmora_wfp validate "/path/to/project.wfp"
python3 -m filmora_wfp inspect "/path/to/project.wfp"
python3 -m filmora_wfp map "/path/to/project.wfp"
python3 -m filmora_wfp eval-format "/path/to/project.wfp"
python3 -m filmora_wfp titles "/path/to/project.wfp"
```

Use `--json` when consuming the result programmatically. Paths are redacted by
default; use `--reveal-paths` only when resolving local media is required.

Use `inspect` for a quick human summary. Use `map --json` before any new format
claim or mutation: it preserves duplicate JSON keys, builds the canonical
timeline graph, profiles normalized fields and enums, checks identifiers, and
classifies opaque payloads without assigning semantics. Use `eval-format` as the
repeatable compatibility gate for a real project or a future Filmora build.

Read [references/format-map.md](references/format-map.md) when tracing timeline,
clip, title, effect, or transition fields.

## Reverse-engineer a field

Require two saves from the same Filmora build with exactly one UI change between
them. Then run:

```bash
python3 -m filmora_wfp map before.wfp --json > work/before-map.json
python3 -m filmora_wfp map after.wfp --json > work/after-map.json
python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
python3 -m filmora_wfp eval-format after.wfp
```

Narrow noisy output with `--member` and `--max-changes`. Repeat the experiment to
separate the target field from timestamps, serials, UUIDs, and save noise.

Read [references/experiment-protocol.md](references/experiment-protocol.md) before
designing or interpreting a controlled experiment.

## Document an observation

Record:

1. Filmora build and operating system.
2. Exact UI action and old/new values.
3. Archive member and JSON path.
4. Whether the finding repeated.
5. Remaining uncertainty.

Update `docs/format/` and add a synthetic regression test. Mark unconfirmed
interpretations as hypotheses.

## Make a project-file change

Only proceed after the field has a repeatable before/after mapping.

1. Add a targeted command that refuses identical input/output paths.
2. Copy the input and change the minimum JSON fields.
3. Preserve unrelated members and avoid regenerating UUIDs.
4. Validate JSON, archive paths, and timeline references.
5. Run `filmora_wfp eval-format` on the generated copy.
6. Audit the generated copy against its source with
   `filmora_wfp audit-title-card-copy`.
7. Compare input/output with `filmora_wfp diff` and semantic `map` output.
8. Open the output in the originating Filmora build as the final gate.
9. Save it again in Filmora and confirm the intended change survives. Expect
   Filmora to rotate protected metadata and possibly renumber timeline IDs.

Do not improvise archive rewrites with one-off shell substitutions.

For a project containing the observed three-timeline compound title-card graph,
use the copy-only command instead of editing ZIP members directly:

```bash
python3 -m filmora_wfp clone-title-cards input.wfp output.wfp \
  --template-timeline <outer-timeline-id> \
  --spec cards.json \
  --expect-sha256 <source-sha256>

python3 -m filmora_wfp audit-title-card-copy input.wfp output.wfp --check-media
```

Read [references/format-map.md](references/format-map.md) and
`docs/format/compound-title-cards.md` first. The output must not already exist.
