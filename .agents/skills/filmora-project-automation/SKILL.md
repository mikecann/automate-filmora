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
classifies opaque payloads without assigning semantics. It also profiles schemas
inside parseable JSON/XML strings without retaining their values. Use
`eval-format` as the repeatable compatibility gate for a real project or a future
Filmora build.

Read [references/format-map.md](references/format-map.md) when tracing timeline,
clip, title, effect, or transition fields.

## Survey a project corpus

Use the read-only corpus command when the user supplies a directory or backup:

```bash
python3 -m filmora_wfp survey "/path/to/projects" \
  --reference-version 15.6.4.11894 \
  --output work/corpus.json
```

The survey recursively discovers projects, fingerprints unique edit archives,
maps each project, runs format evals, and aggregates versions, fields, clip types,
effects, transitions, and serialized payloads. A `.wfpbundle` is fingerprinted
and mapped through its embedded WFP, so bundled media is never hashed or read.

Keep paths hidden for reusable evidence. Use `--reveal-paths` only for an ignored
private report needed to select local samples, and never commit that report.

Always set `--reference-version` to the exact build under investigation. Treat
cohorts as follows:

- `exact`: direct compatibility evidence;
- `same_major`: useful discovery evidence, still sensitive to patch and OS;
- `legacy`: historical structure and hypotheses only;
- `future`: possible format drift that needs a new controlled baseline.

Corpus frequency can reveal missing structures and choose representative
projects. It cannot prove an enum or field meaning. Require a minimal Filmora UI
before/after experiment before adding writer behavior.

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

Prefer the declarative API for a supported operation:

```bash
python3 -m filmora_wfp edit-targets input.wfp --json
python3 -m filmora_wfp explain-plan input.wfp plan.json --json
python3 -m filmora_wfp apply-plan input.wfp output.wfp plan.json --json
```

`explain-plan` must report `writes_performed: false`. The plan must contain the
exact current source SHA-256 and the output must not exist. If an operation is not
listed by `edit-targets`, do not encode it as an edit plan until it passes the
controlled experiment and writer acceptance workflow.

1. Add a targeted command that refuses identical input/output paths.
2. Copy the input and change the minimum JSON fields.
3. Preserve unrelated members and avoid regenerating UUIDs.
4. Validate JSON, archive paths, and timeline references.
5. Run `filmora_wfp eval-format` on the generated copy.
6. Run the operation's source-aware audit. Use
   `filmora_wfp audit-title-card-copy` for compound card clones; title replacement
   is audited automatically by its writer and edit-plan result.
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
