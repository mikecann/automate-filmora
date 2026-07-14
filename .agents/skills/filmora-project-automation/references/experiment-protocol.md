# Controlled experiment protocol

1. Use the smallest possible project.
2. Save `before.wfp`.
3. Change exactly one Filmora UI property.
4. Save `after.wfp` with the same Filmora build.
5. Record build, OS, UI action, old value, and new value.
6. Diff the relevant JSON member with `python3 -m filmora_wfp diff`.
7. Repeat once to identify save noise.
8. Document the observed JSON path and uncertainty.
9. Add a synthetic regression test before building a writer.

Never use the user's only project copy as an experiment.
