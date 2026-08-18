# Contributing

Thanks for helping make Filmora project research more reproducible and safer.
The format is undocumented, so this project treats every field as an observation
until a controlled experiment confirms what it does.

## Keep private material out of the repository

Do not commit or attach real `.wfp` or `.wfpbundle` projects, recordings, bundled
media, private absolute paths, credentials, or opaque tokens copied from a real
project. These files can expose filenames, title text, machine paths, and edit
history even when no footage is included.

Use synthetic fixtures in tests. For bug reports, prefer redacted command output
and describe the Filmora structure without uploading the source project. Check
the output manually because redaction covers absolute paths, not every possible
piece of private edit content.

## Report a format observation

A useful observation includes:

1. the exact Filmora version and build;
2. the operating system and version;
3. the one UI action performed, including old and new values;
4. separate before and after saves made from the same baseline;
5. the relevant archive member and normalized JSON path;
6. whether an independent repeat produced the same semantic change;
7. any remaining uncertainty or unrelated save noise.

Start with the [experiment protocol](docs/experiments.md) and use the read-only
tools:

```bash
python3 -m filmora_wfp map before.wfp --json
python3 -m filmora_wfp map after.wfp --json
python3 -m filmora_wfp diff before.wfp after.wfp --member timeline.wesproj
python3 -m filmora_wfp eval-format after.wfp
```

Put local experiments under ignored `work/` or `samples/private/` directories.
Update the relevant file under `docs/format/` and add a focused synthetic test
when a field becomes understood.

## Propose a writer

A new writer needs a narrow, named use case and repeatable before/after evidence.
It must:

- preserve its source and write only to a new, nonexistent output;
- reject stale source values and unsupported graph shapes;
- change the minimum proven fields;
- preserve opaque data and unrelated archive members;
- validate and audit its own output;
- remove a failed output;
- pass an open, Save As, close, and reopen round trip in the originating Filmora
  build.

Please do not add a generic JSON patcher, archive repacker, or guessed enum
mapping.

## Develop and test

The code supports Python 3.9 or newer and prefers the standard library.

```bash
python3 -m unittest discover -s tests -v
python3 -m filmora_wfp feature-coverage
git diff --check
```

Keep tests deterministic and build fixtures in temporary directories. Do not
download third-party Filmora executables or commit generated build artifacts.

Start a pull request with a `## Why` section that explains what prompted the
change and why it is worth making. Keep format evidence, implementation, and the
focused regression test together so the claim can be reviewed as one unit.
