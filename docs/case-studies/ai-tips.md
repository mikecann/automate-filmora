# AI Tips project, sanitized observations

Source project: `AI Tips.wfp`, created and modified by Filmora 15.6.4.11894 on
macOS. The original project and its absolute media paths are intentionally not
stored in this repository.

This study spans several Filmora saves. Counts in the next two sections describe
the smaller starting save used for the first copy experiment. The current source
at SHA-256 `8d264f5910d...` is about 2.58 MB and maps to 121 archive members,
55 canonical timelines, 46 title buffers, and 61 transitions.

## Historical starting shape

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

The original copy-only experiment cloned timeline `15` nine times to add tips 6
through 14.
That generated project contains 44 timelines, 17 timeline documents, 15 paired
nested placements, and 28 decoded non-empty title layers. ZIP validation, media
resolution, timeline-reference validation, and identifier/routing audits pass.
Only the three expected original members changed, and 18 standalone card members
were added. All other source members remained byte-identical.

The first generated copy was rejected by Filmora even though every structural
check passed. Controlled load tests isolated the cause: the writer changed
`project_date_modify` without changing the opaque `project_source` integrity
value. A one-second timestamp-only change reproduced the same rejection.

After preserving both fields, a generated one-card copy loaded in Filmora
15.6.4.11894 and Filmora rendered its changed `LOAD TEST` title in the media
thumbnail. The historical nine-card copy also opened, but a fresh source-aware
audit now proves that file is stale relative to the current source. Keep it only
as load-test evidence.

That stale generated file had one conflicting standalone timeline cache copy. Filmora
tolerated it and converted it during Save As into an unreferenced,
standalone-only timeline with resources declared in that standalone document
root. This exposed and fixed an eval bug: `sourceUuid` definitions must be
collected from every timeline document root, not only the routed main document.

The current regression was rebuilt from the exact source hash into an ignored
fixture. It added nine card graphs and 18 title layers, changed only the routed
main timeline, media index, and project metadata, removed nothing, and passed
both the source-aware audit and `eval-format`. It opened in Filmora, displayed
added-card thumbnails, saved to a new path, retained identical semantic counts,
passed `eval-format` again, and reopened.

The current source already contains tip-card headings 6 through 14. The old
nine-card content spec therefore creates duplicates and is now a regression
fixture only, not a usable edit for the current project.

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
- Whether every generated card's complete animation renders identically before
  and after the save; the load test verified visible added-card thumbnails but did
  not play every animation end to end.
