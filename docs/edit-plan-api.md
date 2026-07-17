# Declarative edit-plan API

Status: API version `1`, plan schema version `1`. This is a strict orchestration
layer over mutations that have already passed a Filmora load, save, and reopen
experiment. It is not a generic JSON patcher.

Version 1 supports one operation: `clone_title_cards`. One operation can create
many cards. Unsupported operation names, unknown fields, stale projects, and
lossy time values are rejected before an output file is created. Planned cards
must not overlap one another.

## Safety contract

- Plans require the byte-level SHA-256 of the exact source project.
- `explain-plan` runs source validation and format probes without writing.
- `apply-plan` accepts a `.wfp` source and writes only to a new output path.
- The existing title-card writer still performs the mutation and source-aware
  audit. A failed audit removes the generated output.
- A generated project still requires a Filmora open, save, and reopen check.
- `.wfpbundle` remains read-only because writing its embedded project would also
  require a tested bundle-repacking policy.

## CLI workflow

First discover selectors and the current source fingerprint:

```bash
python3 -m filmora_wfp edit-targets project.wfp --json
```

The preferred selector uses visible title text, so it resolves against the latest
source even after Filmora renumbers timeline IDs. A raw `timeline_id` selector is
available as an escape hatch when visible text is ambiguous, but it must never be
cached across a Filmora Save As. Target discovery also reports the template
layers' current font, font size, and X/Y scale as evidence for constructing the
plan. It does not claim those values will auto-fit different text.

Create a plan such as `work/add-cards.json`:

```json
{
  "schema_version": 1,
  "description": "Add the next two section cards",
  "source": {
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "operations": [
    {
      "id": "add-section-cards",
      "op": "clone_title_cards",
      "template": {
        "heading": "5. Existing heading",
        "subheading": "Existing subtitle"
      },
      "cards": [
        {
          "at": {"seconds": "92.4"},
          "heading": "6. New heading",
          "subheading": "New subtitle",
          "heading_font_size": "72",
          "heading_scale_x": "0.7",
          "subheading_font_size": "32",
          "subheading_scale_x": "0.45"
        },
        {
          "at": {"ticks": 1050000000},
          "heading": "7. Another heading",
          "subheading": "Another subtitle",
          "heading_font_size": "72",
          "heading_scale_x": "0.72",
          "subheading_font_size": "32",
          "subheading_scale_x": "0.48"
        }
      ]
    }
  ]
}
```

Replace the example digest with the exact value returned by `edit-targets`; the
placeholder cannot authorize a real project mutation.

Use decimal strings when exact input spelling matters. Seconds may contain at
most seven decimal places because Filmora uses 10,000,000 ticks per second.

Resolve the plan without writing:

```bash
python3 -m filmora_wfp explain-plan project.wfp work/add-cards.json --json
```

The result includes `writes_performed: false`, the resolved current timeline,
exact output ticks, preflight results, and the remaining Filmora round-trip gate.
It also reports each card's resolved end tick using the selected template's
current duration.

Apply it to a new copy:

```bash
python3 -m filmora_wfp apply-plan \
  project.wfp \
  work/project-with-cards.wfp \
  work/add-cards.json \
  --json
```

The command fails if the source hash changed or the output already exists. A
successful response reports `source_aware_audit_valid: true` and
`filmora_round_trip_performed: false`. That final false is deliberate rather than
an optimistic claim that structural validation can replace Filmora.

Successful edit-plan commands exit with code `0`. A rejected plan exits with code
`2`. With `--json`, the error is emitted to stderr as a versioned object:

```json
{
  "api_version": 1,
  "error": {
    "code": "wfp_error",
    "message": "Source fingerprint changed: ..."
  }
}
```

## Python API

```python
from filmora_wfp import (
    apply_edit_plan,
    edit_plan_schema,
    explain_edit_plan,
    list_edit_targets,
    load_edit_plan,
)

targets = list_edit_targets("project.wfp")
schema = edit_plan_schema()
plan = load_edit_plan("work/add-cards.json")
dry_run = explain_edit_plan("project.wfp", plan)

assert dry_run["writes_performed"] is False
result = apply_edit_plan("project.wfp", "work/output.wfp", plan)
assert result["verification"]["source_aware_audit_valid"] is True
```

Typed immutable input models are also exported: `EditPlan`,
`CloneTitleCardsOperation`, `TitleCardTemplateSelector`, and `TitleCardSpec`.
Manually constructed models pass through the same runtime safety validation as
JSON plans.

## Versioning

`schema_version` versions the plan document. `api_version` versions the result
shape returned by target discovery, explanation, and application. Published plan
schemas are immutable. Adding another operation or changing field, time, or
selector semantics requires a new schema version. Changing the meaning of an
existing result field requires a new API version.

The machine-readable schema is
[`filmora_wfp/schemas/edit-plan-v1.schema.json`](../filmora_wfp/schemas/edit-plan-v1.schema.json)
and is included in the installed wheel. Python callers can obtain an independent
dictionary with `edit_plan_schema()`.

## Adding another operation

Do not add an operation merely because corpus evidence suggests which fields to
change. Each new operation must have:

1. a minimal Filmora before/after experiment from the exact build;
2. a narrow mutation that preserves unrelated members and opaque values;
3. a source-aware automated audit;
4. a synthetic regression test;
5. a generated-project open, save, and reopen result in Filmora.

This keeps the API smaller than the mapped format on purpose.
