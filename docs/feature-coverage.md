# Filmora feature coverage

The format notes are the detailed evidence. The coverage command is the compact,
machine-readable answer to a different question: how much of Filmora can this
repository currently understand or safely change?

```bash
python3 -m filmora_wfp feature-coverage
python3 -m filmora_wfp feature-coverage --status writable
python3 -m filmora_wfp feature-coverage --status open --json
```

Each feature has one status:

- `writable`: a guarded copy-only writer exists and passed its acceptance flow;
- `mapped`: a controlled Filmora UI before/after diff confirms serialization;
- `partial`: a useful part is confirmed, but variants or derived values remain;
- `open`: there is not yet enough controlled evidence;
- `external_dependency`: investigation requires a model download, cloud service,
  or Filmora credits.

The total and per-status summary always describe the whole curated matrix, even
when `--status` filters the returned rows. That makes coverage snapshots stable
for evals and lets future runs choose high-value gaps without re-reading every
experiment note.

This inventory is intentionally conservative. Corpus frequency, a visible UI
control, or a plausible field name cannot promote a feature to `mapped`.
Likewise, a direct scalar mapping cannot promote itself to `writable` until the
copy writer refuses stale inputs, audits its own semantic diff, passes format
evaluation, opens in Filmora, and survives a Filmora Save As round trip.
