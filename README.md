# automate-filmora

Experimental, evidence-driven tooling for inspecting and eventually automating
Wondershare Filmora project files.

Filmora 15 `.wfp` projects are ZIP archives containing JSON project metadata,
timeline documents, thumbnails, and references to external media. This repository
documents the observed format and provides read-only tools for exploring it.

## Safety contract

- Treat Filmora's format as undocumented and version-specific.
- Never modify the only copy of a project.
- Keep mutation out of the CLI until a round-trip can be tested against Filmora.
- Do not commit real `.wfp` files, bundled media, or private absolute paths.
- Record the Filmora build and the controlled experiment behind every claimed field.

## Quick start

No dependencies are required beyond Python 3.9 or newer.

```bash
python3 -m filmora_wfp validate "/path/to/project.wfp"
python3 -m filmora_wfp inspect "/path/to/project.wfp"
python3 -m filmora_wfp titles "/path/to/project.wfp"
python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
```

Add `--json` to `inspect`, `titles`, `validate`, or `diff` for machine-readable
output. Paths are reduced to basenames unless `--reveal-paths` is supplied.

`unpack` safely extracts a project to a new directory without touching the source:

```bash
python3 -m filmora_wfp unpack project.wfp work/unpacked-project
```

## Repository map

- `filmora_wfp/`: dependency-free inspection, validation, diff, and unpack tools.
- `docs/format/`: observed project structure and field notes.
- `docs/experiments.md`: repeatable reverse-engineering protocol.
- `docs/case-studies/`: sanitized observations from real projects.
- `.agents/skills/filmora-project-automation/`: reusable Codex workflow.
- `tests/`: synthetic fixtures and safety tests.

## Current scope

The tools can currently:

- locate the main timeline through `timeline_mediaId`;
- inventory ZIP members, resources, timelines, tracks, clips, effects, and transitions;
- decode title text and typography stored as JSON inside `scriptBuf`;
- locate nested timeline placements used for compound clips;
- compare two controlled project saves, including embedded JSON changes;
- detect malformed archives, unresolved timeline references, and unsafe ZIP paths.

Writing projects is deliberately not implemented yet. The first writer should make
one narrow change to a copied project, preserve unrelated bytes where possible, and
round-trip through the exact Filmora build that created it.

## Related work

- [ItsQuesty/WFP-Renderer-bypass](https://github.com/ItsQuesty/WFP-Renderer-bypass)
  is an early Filmora-to-FFmpeg renderer. Its parser is useful prior art, but its v1
  model does not cover nested title timelines like the ones documented here.
- [Filmora project documentation](https://filmora.wondershare.com/guide/create-a-project.html)
  confirms that WFP files store edit decisions and external media references, but
  does not publish a schema.
