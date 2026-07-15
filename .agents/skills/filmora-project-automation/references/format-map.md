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
- Parse `medias_info.json` with duplicate-key preservation. Repeated
  `media_structure.Folder.media_item` keys are observed and ordinary object
  parsing loses all but the last.

Start every broad inspection with:

```bash
python3 -m filmora_wfp map project.wfp --json > work/format-map.json
python3 -m filmora_wfp eval-format project.wfp
```

## Timeline traversal

- Select `currentTimelineId` from `timelineInfos[]` for the main edit.
- Build the canonical graph from the routed main document, then merge only
  standalone-only timeline IDs. Do not count exact standalone copies twice.
- Treat a different standalone body under the same ID as a cache conflict.
- Traverse every `trackInfos[].clipList[]`.
- Resolve clips with `timelineId` recursively against other `timelineInfos[]`.
- Do not require nested clips to have `filename`; Filmora compound clips often do
  not.
- Track types observed: `1` visual, `2` audio.
- Numeric timeline IDs are save-local. Filmora Save As can renumber every ID and
  update every reference without changing the semantic edit.
- Validate `timelineId`, `sourceUuid`, media-folder, and clip-instance identity
  relationships before interpreting a project or accepting a generated copy.

## Titles

- Generated titles are observed as clip type `4`.
- Parse `scriptBuf` as a second JSON document.
- Useful fields: `Text`, `TextData[0].Basic.FontName`, `FontSize`, `TextColor`,
  `CharSpace`, `PosX`, `PosY`, `ScaleX`, `ScaleY`, and `Animation.ID`.
- Keep `Text` and `TextData[0].CharData` consistent in write experiments.
- Check `scriptBufSize == len(scriptBuf.encode("utf-8")) + 1` when the size is
  declared.
- Check that readable `Text` and `TextData[0].CharData` values match.
- A Basic Title insertion was observed as a type `7` parent placement pointing to
  a nested timeline containing the type `4` title clip.

## Effects and transitions

- Effects: `effectChainList[].effectList[]`.
- Parameters: `paramList[].{name,fxParam.unValue}`.
- Transitions: `preTransition` and `postTransition` on clips.
- Preserve unknown `userData` entries byte-for-byte.
- Classify base64 by scope, key, length, and decoded shape before forming a
  hypothesis. A repeated relationship in one project is still not permission to
  rewrite that key generically.

## Detailed repository docs

Use `docs/format/README.md`, `docs/format/timeline.md`,
`docs/format/media-library.md`, `docs/format/titles.md`,
`docs/format/effects-transitions-userdata.md`,
`docs/format/observations-15.6.4.md`, and
`docs/format/compound-title-cards.md` for the current evidence and open questions.
