# Observed WFP structure

Status: experimental observations from Filmora 15.6.4 on macOS. None of this is
an official Wondershare schema.

## Container

A `.wfp` file is a ZIP archive. An observed non-archived project contains:

```text
ProjectFolder/
├── project_info.json
├── Medias/
│   ├── medias_info.json
│   ├── <timeline-media-id>/
│   │   ├── timeline.wesproj
│   │   └── extra.json
│   └── <source-media-id>/
│       ├── media.json
│       └── thumbnail.png
└── Anon/
    └── Cover/
```

The exact member set varies. Compound clips can also have their own media folders,
`timeline.wesproj`, and `extra.json` files.

Observed archives can also contain `ProjectFolder/functionExtraData.json`, media
metadata, several thumbnails, and one cover thumbnail. Compression is mixed:
Filmora may store some members and deflate others.

## Root project metadata

`ProjectFolder/project_info.json` provides the routing information needed to find
the main edit:

- `timeline_mediaId`: folder containing the main `timeline.wesproj`.
- `project_editor_create_version` / `project_editor_modify_version`: Filmora build.
- `project_timeline_duration`: project duration in 10,000,000 ticks per second.
- `project_timeline_framerate`: `[numerator, denominator]`.
- `project_timeline_resolution`: `[width, height]`.
- `project_guid`: project identifier.

## Timeline document

The main `timeline.wesproj` is JSON with these observed top-level fields:

- `currentTimelineId`
- `productName`
- `projectName`
- `projectVersion`
- `resources`
- `serialNumber`
- `serializationVersion`
- `timelineInfos`

`timelineInfos` contains both the main timeline and nested timelines used by
compound clips and title resources. `trackInfos[].clipList[]` contains the actual
edit decisions.

## Map before interpreting

Run the structural mapper before making assumptions about a project:

```bash
python3 -m filmora_wfp map project.wfp --json > work/format-map.json
python3 -m filmora_wfp eval-format project.wfp
```

The mapper preserves duplicate JSON object keys while profiling the document.
That matters because an observed `medias_info.json` serialized every
`media_structure.Folder.media_item` as another key in the same object. A normal
`json.load()` keeps only the last one.

The mapper also de-duplicates timeline definitions semantically. The main media
folder can contain many nested timelines, while individual media folders repeat
some of those definitions in standalone `timeline.wesproj` files. Counting every
document independently inflates clips, effects, and titles.

See [project-info.md](project-info.md), [timeline.md](timeline.md),
[media-library.md](media-library.md), [titles.md](titles.md),
[effects-transitions-userdata.md](effects-transitions-userdata.md),
[observations-15.6.4.md](observations-15.6.4.md), and
[compound-title-cards.md](compound-title-cards.md) for current field maps.
