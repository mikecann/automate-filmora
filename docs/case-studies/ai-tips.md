# AI Tips project, sanitized observations

Source project: `AI Tips.wfp`, created and modified by Filmora 15.6.4.11894 on
macOS. The original project and its absolute media paths are intentionally not
stored in this repository.

## Project shape

- ZIP size: about 296 KB.
- Uncompressed members: about 2.6 MB across 20 files.
- Main timeline: 3840x2160, 30 fps, 990.233 seconds.
- Main camera edit: 113 paired video and audio cuts.
- Current timeline: 7 tracks.
- Main timeline document: 14 `timelineInfos` entries.

## Nested inserts

The main edit contains five paired nested placements:

- timeline `10`: subscribe animation, about 3.467 seconds;
- timeline `71`: first section card, about 3.067 seconds;
- timeline `97`: second section card, about 3.100 seconds;
- timeline `103`: third section card, about 3.100 seconds;
- timeline `126`: copied fourth section card, about 3.133 seconds.

The section cards use an animated abstract WebM background, `Diagonal in`,
`Cut Slide Transition 03`, two staggered text layers, and four sound-effect layers.

## Decoded titles

- `1. Low Change Cost` / `Just Do It & Reverse`
- `2. Screenshots in PRs` / `a screeny is worth 1000 words`
- `3. Read Schema.ts!` / `Its the most important File`
- timeline `126` currently repeats the first card's text.

The heading uses Bebas Neue, usually at size 80. The subtitle uses Bebas Neue Book
at size 32 with character spacing 5. Both use title animation ID `274`.

## Open questions

- Meaning of timeline `type` values `0` and `1`.
- Exact distinction between nested clip types `6`, `7`, and `16`.
- Whether all duplicated timeline documents must be updated by a writer.
- Which UUIDs can safely be preserved when cloning a compound clip.
- Whether Filmora recalculates `scriptBufSize`, archive metadata, or serial fields.
