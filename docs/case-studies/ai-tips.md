# AI Tips project, sanitized observations

Source project: `AI Tips.wfp`, created and modified by Filmora 15.6.4.11894 on
macOS. The original project and its absolute media paths are intentionally not
stored in this repository.

## Project shape

- ZIP size: about 319 KB.
- Uncompressed members: about 2.8 MB across 22 files.
- Main timeline: 3840x2160, 30 fps, 988.267 seconds.
- Main camera edit: 113 paired video and audio cuts.
- Current timeline: 7 tracks.
- Main timeline document: 17 `timelineInfos` entries.

## Nested inserts

The inspected source edit contains six paired nested placements:

- timeline `10`: subscribe animation, about 3.467 seconds;
- timeline `11`: first section card, about 3.067 seconds;
- timeline `12`: second section card, about 3.100 seconds;
- timeline `13`: third section card, about 3.100 seconds;
- timeline `14`: fourth section card, about 3.133 seconds;
- timeline `15`: fifth section card, about 3.133 seconds.

The section cards use an animated abstract WebM background, `Diagonal in`,
`Cut Slide Transition 03`, two staggered text layers, and four sound-effect layers.

## Decoded titles

- `1. Low Change Cost` / `Just Do It & Reverse`
- `2. Screenshots in PRs` / `a screeny is worth 1000 words`
- `3. Read Schema.ts!` / `Its the most important File`
- `4. Agent INterview` / `Work with your collaborator`
- `5. Discriminated Unions` / `statemachines good`

The heading uses Bebas Neue, usually at size 80. The subtitle uses Bebas Neue Book
at size 32 with character spacing 5. Both use title animation ID `274`.

## Copy experiment

The copy-only writer cloned timeline `15` nine times to add tips 6 through 14.
The generated project contains 44 timelines, 17 timeline documents, 15 paired
nested placements, and 28 decoded non-empty title layers. ZIP validation, media
resolution, timeline-reference validation, and identifier/routing audits pass.
Only the three expected original members changed, and 18 standalone card members
were added. All other source members remained byte-identical.

The source SHA-256 remained unchanged throughout the write. The generated copy's
Filmora open/save round-trip is still pending.

A Filmora save occurred during the experiment. It compacted the previously sparse
nested IDs into the contiguous range `10` through `25`, set `serialNumber` to
`26`, rewrote every standalone timeline document, removed one compound thumbnail,
and inserted 31 frames after tip 5. Every later camera clip moved by exactly those
31 frames. The source fingerprint guard caught the stale input, and the final copy
was rebuilt from the newer save with all remaining card positions shifted by the
same amount.

## Remaining open questions

- Meaning of timeline `type` values `0` and `1`.
- Exact distinction between nested clip types `6`, `7`, and `16`.
- Whether Filmora recalculates any title metrics or archive metadata on first save.
- Whether the generated cards render identically before and after that save.
