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

See [timeline.md](timeline.md) and [titles.md](titles.md) for current field maps.
