# Agent instructions

Think critically and challenge assumptions about the format. Every field is an
observation until a controlled before/after experiment confirms it.

## Safety

- Default to read-only operations.
- Never overwrite a `.wfp` or `.wfpbundle` input.
- Do not add a generic writer or repacker without a narrow, tested use case.
- Put experimental outputs in ignored directories such as `work/` or
  `samples/private/`.
- Do not commit real projects, media, private paths, credentials, or downloaded
  third-party binaries.
- Treat base64 blobs and numeric enums as opaque until evidence proves otherwise.

## Development

- Support Python 3.9 or newer and prefer the standard library.
- Run `python3 -m unittest discover -s tests -v` after changes.
- Run the CLI against a real project when one is supplied, but keep the project
  outside the repository.
- Update `docs/format/` and a focused test whenever a field becomes understood.
- Record Filmora version, operating system, exact UI change, and before/after
  evidence for reverse-engineering experiments.

## Agent skills

- Use `.agents/skills/filmora-project-automation/SKILL.md` for WFP inspection,
  controlled diffs, format documentation, and any future automation work.
