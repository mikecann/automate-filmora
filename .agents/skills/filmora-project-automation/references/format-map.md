# WFP format map

## Container routing

- `.wfp` is an observed ZIP container.
- Read `ProjectFolder/project_info.json` first.
- Preserve `project_date_modify` and `project_source` in generated copies. A
  one-second `project_date_modify` change with an unchanged `project_source`
  makes Filmora 15.6.4 reject an otherwise valid project.
- Resolve `timeline_mediaId` to
  `ProjectFolder/Medias/<id>/timeline.wesproj`.
- Treat 10,000,000 timeline ticks as one second for observed Filmora 15.6.4
  projects.

## Timeline traversal

- Select `currentTimelineId` from `timelineInfos[]` for the main edit.
- Traverse every `trackInfos[].clipList[]`.
- Resolve clips with `timelineId` recursively against other `timelineInfos[]`.
- Do not require nested clips to have `filename`; Filmora compound clips often do
  not.
- Track types observed: `1` visual, `2` audio.

## Titles

- Generated titles are observed as clip type `4`.
- Parse `scriptBuf` as a second JSON document.
- Useful fields: `Text`, `TextData[0].Basic.FontName`, `FontSize`, `TextColor`,
  `CharSpace`, `PosX`, `PosY`, `ScaleX`, `ScaleY`, and `Animation.ID`.
- Keep `Text` and `TextData[0].CharData` consistent in write experiments.

## Effects and transitions

- Effects: `effectChainList[].effectList[]`.
- Parameters: `paramList[].{name,fxParam.unValue}`.
- Transitions: `preTransition` and `postTransition` on clips.
- Preserve unknown `userData` entries byte-for-byte.

## Detailed repository docs

Use `docs/format/README.md`, `docs/format/timeline.md`,
`docs/format/titles.md`, and `docs/format/compound-title-cards.md` for the current
evidence and open questions.
