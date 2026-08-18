# automate-filmora

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`automate-filmora` is an experimental Python toolkit for inspecting Wondershare
Filmora project files and making a small set of evidence-backed edits to new
copies.

Filmora's `.wfp` format is undocumented and changes between versions. This
project exists to replace guesswork with repeatable inspection, controlled
before/after experiments, and conservative automation that fails closed when a
project does not match a proven shape.

This is not a generic Filmora API, a full WFP writer, or an AI video editor.

## What works today

| Area | Current support |
| --- | --- |
| Project inspection | Summarize, validate, map, diff, and safely unpack `.wfp` projects. Absolute paths are redacted by default. |
| Bundles | Read the single embedded project inside a `.wfpbundle` without inspecting or extracting its bundled footage. Bundle writing is not supported. |
| Format research | Inventory timeline graphs, duplicate JSON keys, titles, effects, transitions, identifiers, and opaque payload shapes. Run compatibility probes against new Filmora builds. |
| Copy-only edits | Apply strictly validated operations for selected existing titles, transforms, audio settings, transitions, and linked A/V clips. Some additional guarded operations are available through the Python API. |
| Rough cuts | Build a reviewable silence and repeated-take plan, then generate a gapless project from a narrowly supported Filmora-created single-source seed. |

The project deliberately distinguishes between a field that has merely been
observed and one that is safe to write. Run the coverage report for the current
inventory:

```bash
python3 -m filmora_wfp feature-coverage
python3 -m filmora_wfp feature-coverage --status writable
```

See [Filmora feature coverage](docs/feature-coverage.md) for the meaning of
`writable`, `mapped`, `partial`, `open`, and `external_dependency`.

## Install from this repository

The inspector and project tools support Python 3.9 or newer and have no runtime
Python dependencies.

```bash
git clone https://github.com/mikecann/automate-filmora.git
cd automate-filmora
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/filmora-project --help
```

The installed command is `filmora-project`. You can also run the same CLI from a
checkout without installing it:

```bash
python3 -m filmora_wfp --help
```

Rough-cut silence detection additionally needs an `ffmpeg` executable.
Transcription uses the optional `faster-whisper` package, or you can provide an
existing SRT or planner JSON transcript. This repository does not download
either dependency for you.

## Try a read-only inspection

Start with `inspect` and `validate`. Neither command changes the project:

```bash
filmora-project inspect "/path/to/My Project.wfp"
filmora-project validate "/path/to/My Project.wfp"
filmora-project titles "/path/to/My Project.wfp"
```

Use `--check-media` when you also want validation to fail for missing external
source files:

```bash
filmora-project validate "/path/to/My Project.wfp" --check-media
```

For reverse engineering, compare two saves made by the same Filmora build with
exactly one UI change between them:

```bash
filmora-project diff before.wfp after.wfp --member timeline.wesproj
filmora-project map after.wfp --json
filmora-project eval-format after.wfp
```

The tools redact absolute paths unless `--reveal-paths` is explicitly supplied.
Project names, title text, media basenames, and other edit content can still be
sensitive, so review any output before sharing it.

## Make a supported project copy

The preferred mutation interface is the versioned edit-plan API:

```bash
filmora-project edit-targets project.wfp --json
filmora-project explain-plan project.wfp work/edit-plan.json --json
filmora-project apply-plan \
  project.wfp \
  work/output.wfp \
  work/edit-plan.json \
  --json
```

`edit-targets` reports only shapes the current code knows how to edit and
includes the exact source SHA-256 required by a plan. `explain-plan` performs a
dry run. `apply-plan` writes a new output and runs an operation-specific audit.

The declarative API currently covers:

- cloning the observed compound title-card graph;
- replacing same-serialization-length title text;
- replacing existing rotation, position, uniform scale, volume, fade-in, and
  fade-out values;
- changing or removing the observed linked Dissolve and audio-fade pair;
- moving, shortening, or splitting a supported transition-free linked A/V pair.

That list is intentionally narrow. Missing parameters, first-use effect
insertion, arbitrary JSON patches, and unrecognized graph shapes are rejected.
See the [edit-plan API](docs/edit-plan-api.md) for plan schemas and exact
preconditions.

## Rough-cut workflow

The rough-cut tools turn silence boundaries and transcript evidence into a
reviewable source-time keep plan. They do not decide that silence alone means a
bad take, and every proposed cut remains available for human review.

```bash
filmora-project rough-cut-plan \
  recording.mp4 \
  work/recording-rough-cut \
  --model small.en

filmora-project rough-cut-seed seed.wfp

filmora-project rough-cut-project \
  seed.wfp \
  work/recording-rough-cut/rough-cut-plan.json \
  work/recording-rough-cut/output.wfp \
  --expect-sha256 <seed-sha256>
```

The writer supports one Filmora-created linked video/audio seed pair with the
observed normal-speed structure. It does not create a project from scratch. Read
the [rough-cut guide](docs/rough-cut.md) before using it on production footage.

## Enforced safeguards

- Read-only commands never rewrite their source project.
- Mutating commands require different input and output paths and refuse an
  existing output.
- Edit plans are bound to the exact input bytes with SHA-256.
- Writers change only fields covered by a controlled experiment and preserve
  unrelated archive members where their contract requires it.
- Every writer runs structural and operation-specific audits. A failed audit
  removes the newly created output.
- `.wfpbundle` mutation is disabled because safe bundle repacking has not been
  established.
- Real projects, bundled media, and private absolute paths are ignored and must
  not be committed.

These checks catch known structural mistakes. They cannot prove that an
undocumented project will render correctly. Always keep the original and open,
save, close, and reopen a generated copy in the exact Filmora build that created
its template before relying on it.

## Compatibility and limitations

Most format mappings and writer acceptance tests come from Filmora
`15.6.4.11894` on macOS `26.5.2`. The rough-cut work has additional,
project-specific evidence from Filmora `15.7.3.12221` and `15.7.11.12437` on
macOS. This is an evidence base, not a promise of compatibility with every
Filmora 15 release, newer releases, Windows projects, or projects containing
untested structures.

Run `eval-format` on a real project from the target build before trusting a new
version. Even a passing result establishes structural compatibility only. It
does not replace the Filmora round trip.

Tests use synthetic project fixtures. No real WFP project or source media is
included in this repository.

## Documentation

- [Observed WFP structure](docs/format/README.md)
- [Feature coverage](docs/feature-coverage.md)
- [Reverse-engineering experiment protocol](docs/experiments.md)
- [Declarative edit-plan API](docs/edit-plan-api.md)
- [Rough-cut planning and generation](docs/rough-cut.md)
- [Sanitized case studies](docs/case-studies/)
- [Contributing](CONTRIBUTING.md)

The repository is not affiliated with or endorsed by Wondershare. Filmora is a
trademark of its respective owner.

## License

Released under the [MIT License](LICENSE). Copyright 2026 Mike Cann.
