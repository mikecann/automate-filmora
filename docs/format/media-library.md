# Media library and per-media folders

Status: observations from Filmora 15.6.4.11894 on macOS. Numeric media types are
not named until controlled experiments prove them.

## `medias_info.json`

`ProjectFolder/Medias/medias_info.json` is the library index. Its observed root
contains a `media_items` map plus `media_structure` data used to order the media
panel.

An imported media item can contain:

- `id`, `name`, `media_type`, and `media_length`;
- `import_time`, `src_md5`, and `stream_idx`;
- `download_url` and `mediaCreationInfo`;
- marker and scene-analysis structures;
- opaque `userData`.

Do not parse this file with an ordinary object-only round trip. One real project
stored 56 `media_item` keys in the same `media_structure.Folder` object. Python's
normal `json.load()` silently keeps only the final value. Inspection uses a
duplicate-key-preserving representation, and the existing narrow writer preserves
the repeated keys during serialization.

## Folder layouts

Observed external-source folder:

```text
ProjectFolder/Medias/<media-id>/
├── media.json
└── thumbnail.png
```

Observed timeline-backed folder:

```text
ProjectFolder/Medias/<media-id>/
├── timeline.wesproj
└── extra.json
```

The routed main timeline and nested or compound assets can share the second
layout. A media folder may be referenced by readable IDs, timeline routing, or
opaque `userData`, so removal is unsafe without a full reference audit.

## `media.json`

The observed schema version was `1.1.7`. `sourceInfo` contained:

- `basicInfo` for container-level duration and source properties;
- `vidStreamInfos[]` for dimensions, frame rate, codec, and video stream data;
- `audStreamInfos[]` for sample rate, channels, codec, and audio stream data;
- `recordInfos` for recording metadata.

The arrays are direct children of `sourceInfo`, not children of `basicInfo`.

## Controlled import and insertion

Importing one generated MP4 with audio created the library entry, `media.json`,
and thumbnail. It did not add `resources[]` or timeline clips.

Inserting the item onto the timeline then added:

- one root `resources[]` definition;
- one type `1` visual clip using stream `0`;
- one type `2` audio clip using stream `1`;
- `extra.json.mediaClipsMapInfo` and beat-detection state;
- default visual and audio effect chains.

The first inserted clip also changed the blank project's resolution from
1920x1080 to the source's 1280x720 resolution. Its 25 fps frame rate remained
unchanged. That is Filmora UI behaviour, not a rule that a writer should emulate.

## Observed `media_type` correlation

The studied project correlated values with these archive shapes:

| Value | Count | Observed shape |
| --- | ---: | --- |
| `1048576` | 22 | timeline-backed folder with `timeline.wesproj` and `extra.json` |
| `16` | 2 | PNG source with `media.json` and thumbnail |
| `2` | 14 | MP4 source with `media.json` and thumbnail |
| `8` | 19 | MP4 source with `media.json` and thumbnail |

The two MP4 categories need another controlled experiment before they get names.
Preserve the values instead of inferring their meaning from file extensions.

## `extra.json`

Observed fields include:

- `TextSentence.TextSentence`;
- beat detection entries with `algorithmType` and `level`;
- `fontNameInfo`, `highlightInfo`, and `pendingMarkersInfo`;
- `mediaClipsMapInfo` entries containing `mediaId` and `subClips`;
- `usedBizFont` and `usedTemplateResInfo`.

Not every folder has every field. Treat absent structures as normal.
