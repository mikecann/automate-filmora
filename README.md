# automate-filmora

Experimental, evidence-driven tooling for inspecting and narrowly automating
Wondershare Filmora project files.

Filmora 15 `.wfp` projects are ZIP archives containing JSON project metadata,
timeline documents, thumbnails, and references to external media. A `.wfpbundle`
is an outer ZIP carrying one embedded `.wfp` plus copied source media; the tools
inspect that embedded project without extracting or reading the bundled footage.
This repository documents the observed format and provides copy-only tools for
exploring it.

## Safety contract

- Treat Filmora's format as undocumented and version-specific.
- Never modify the only copy of a project.
- Every mutation must write a new project path and refuse to overwrite either file.
- Do not commit real `.wfp` files, bundled media, or private absolute paths.
- Record the Filmora build and the controlled experiment behind every claimed field.

## Quick start

No dependencies are required beyond Python 3.9 or newer.

```bash
python3 -m filmora_wfp validate "/path/to/project.wfp"
python3 -m filmora_wfp inspect "/path/to/project.wfp"
python3 -m filmora_wfp map "/path/to/project.wfp"
python3 -m filmora_wfp eval-format "/path/to/project.wfp"
python3 -m filmora_wfp survey "/path/to/project-folder" --reference-version 15.6.4.11894
python3 -m filmora_wfp titles "/path/to/project.wfp"
python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
```

`map` is the broad reverse-engineering command. It inventories normalized JSON
paths, duplicate keys, the canonical timeline graph, clip signatures, identifier
references, effects, transitions, title schemas, media metadata, and opaque
`userData` payload shapes without modifying the project. It also profiles schemas
inside parseable JSON strings and tag/attribute names inside XML strings without
retaining their values. `eval-format` turns the
important invariants into repeatable pass/fail probes for future Filmora builds.
`survey` recursively discovers and SHA-256 de-duplicates a read-only project
corpus, then aggregates redacted versions, schema fields, clip types, effects,
transitions, title shapes, and eval failures. For `.wfpbundle`, the fingerprint is
of the embedded project rather than its potentially huge media payload. Pass
`--json` for the full evidence map, or `--output work/corpus.json` to save it
without shell redirection. Source paths are omitted unless `--reveal-paths` is
explicitly supplied, and an existing output file is never overwritten.

Add `--json` to `inspect`, `map`, `eval-format`, `titles`, `validate`, or `diff`
for machine-readable output. Paths are reduced to basenames unless
`--reveal-paths` is supplied.

`unpack` safely extracts a project to a new directory without touching the source:

```bash
python3 -m filmora_wfp unpack project.wfp work/unpacked-project
```

The first narrow writer clones a known compound title-card graph. It requires an
existing card made by the same Filmora build, exact timeline ticks, explicit text
metrics, and a new output path:

```bash
python3 -m filmora_wfp clone-title-cards project.wfp completed.wfp \
  --template-timeline <outer-timeline-id> \
  --spec work/title-cards.json \
  --expect-sha256 <source-sha256>
```

The specification is a JSON array. Each entry supplies `start_ticks`, `heading`,
`subheading`, `heading_font_size`, `heading_scale_x`, `subheading_font_size`, and
`subheading_scale_x`. The command refuses an existing output and aborts if the
source changes while the copy is being written. It also runs a source-aware audit
before returning. A failed audit removes the newly generated output.

Repeat the same audit explicitly with:

```bash
python3 -m filmora_wfp audit-title-card-copy project.wfp completed.wfp --check-media
```

Unlike the generic validator, this command can confirm that Filmora's protected
project timestamp and integrity token stayed unchanged, unrelated source members
remain byte-identical, new card media folders are complete, and every new outer
timeline has paired visual/audio placements.

## Repository map

- `filmora_wfp/`: dependency-free inspection, validation, diff, unpack, and narrow copy tools.
- `docs/format/`: observed project structure and field notes.
- `docs/experiments.md`: repeatable reverse-engineering protocol.
- `docs/case-studies/`: sanitized observations from real projects.
- `.agents/skills/filmora-project-automation/`: reusable Codex workflow.
- `tests/`: synthetic fixtures and safety tests.

## Current scope

The tools can currently:

- locate the main timeline through `timeline_mediaId`;
- inventory ZIP members, resources, timelines, tracks, clips, effects, and transitions;
- build a duplicate-key-preserving field and enum map across every JSON document;
- distinguish canonical timelines from exact standalone timeline cache copies;
- classify identifier relationships and opaque base64 payloads without guessing semantics;
- profile JSON/XML strings and NUL-terminated JSON without retaining payload values;
- run content-independent compatibility probes against real projects;
- survey and de-duplicate a directory corpus without retaining project paths;
- decode title text and typography stored as JSON inside `scriptBuf`;
- locate nested timeline placements used for compound clips;
- compare two controlled project saves, including embedded JSON changes;
- detect malformed archives, unresolved timeline references, and unsafe ZIP paths;
- clone the observed three-timeline section-card graph into a new project copy;
- audit a generated copy against its exact source project.

The title-card cloner is deliberately not a generic WFP writer. A generated copy
must still be opened and saved in the exact Filmora build that created its template
before it should be trusted for production editing.

## Related work

- [ItsQuesty/WFP-Renderer-bypass](https://github.com/ItsQuesty/WFP-Renderer-bypass)
  is an early Filmora-to-FFmpeg renderer. Its parser is useful prior art, but its v1
  model does not cover nested title timelines like the ones documented here.
- [Filmora project documentation](https://filmora.wondershare.com/guide/create-a-project.html)
  confirms that WFP files store edit decisions and external media references, but
  does not publish a schema.
