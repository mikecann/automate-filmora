from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path
from typing import Any, Dict


def title_script(text: str) -> str:
    return json.dumps(
        {
            "Text": text,
            "TextData": [
                {
                    "Basic": {
                        "FontName": "Bebas Neue",
                        "FontSize": 80.0,
                        "TextColor": [{"Color": 16777215}],
                    },
                    "CharSpace": 2,
                }
            ],
            "PosX": 0.5,
            "PosY": 0.5,
            "ScaleX": 0.7,
            "ScaleY": 0.2,
            "Animation": {"ID": 274},
        },
        separators=(",", ":"),
    )


def project_documents(title: str = "Hello") -> Dict[str, Dict[str, Any]]:
    project_info = {
        "project_file_name": "Fixture",
        "project_editor_create_version": "15.6.4.11894",
        "project_editor_modify_version": "15.6.4.11894",
        "project_os_name": "MacOS",
        "project_timeline_duration": 30_000_000,
        "project_timeline_framerate": [30, 1],
        "project_timeline_resolution": [1920, 1080],
        "timeline_mediaId": "MAIN",
    }
    timeline = {
        "currentTimelineId": 1,
        "projectName": "TLB",
        "projectVersion": "fixture",
        "serializationVersion": "fixture",
        "resources": [
            {
                "sourceUuid": "source-1",
                "filename": "file:///private/example/source.mp4",
                "mediaLength": 100_000_000,
                "streamType": 2,
                "videoStreamCount": 1,
                "audioStreamCount": 1,
            }
        ],
        "timelineInfos": [
            {
                "timelineId": 1,
                "trackInfos": [
                    {
                        "trackType": 1,
                        "trackTag": 1,
                        "uuid": "video-track",
                        "clipList": [
                            {
                                "type": 1,
                                "filename": "file:///private/example/source.mp4",
                                "sourceUuid": "source-1",
                                "thisUId": "video-clip",
                                "tlBegin": 0,
                                "tlEnd": 30_000_000,
                                "inPoint": 0,
                                "outPoint": 30_000_000,
                            }
                        ],
                    },
                    {
                        "trackType": 1,
                        "trackTag": 2,
                        "uuid": "nested-track",
                        "clipList": [
                            {
                                "type": 7,
                                "timelineId": 2,
                                "thisUId": "nested-clip",
                                "tlBegin": 5_000_000,
                                "tlEnd": 25_000_000,
                                "inPoint": 0,
                                "outPoint": 20_000_000,
                            }
                        ],
                    },
                ],
            },
            {
                "timelineId": 2,
                "trackInfos": [
                    {
                        "trackType": 1,
                        "uuid": "title-track",
                        "clipList": [
                            {
                                "type": 4,
                                "thisUId": "title-clip",
                                "tlBegin": 0,
                                "tlEnd": 20_000_000,
                                "scriptBuf": title_script(title),
                            }
                        ],
                    }
                ],
            },
        ],
    }
    return {
        "ProjectFolder/project_info.json": project_info,
        "ProjectFolder/Medias/MAIN/timeline.wesproj": timeline,
    }


def write_project(path: Path, title: str = "Hello") -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, value in project_documents(title).items():
            archive.writestr(member, json.dumps(value, separators=(",", ":")))
    return path


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode("ascii")).decode("ascii")


def _cloneable_title_clip(text: str, uid: str, y: float) -> Dict[str, Any]:
    script = json.loads(title_script(text))
    script["TextData"][0]["CharData"] = text
    script["TextData"][0]["Basic"].update(
        {
            "FontHSize": 80.0,
            "FontVSize": 80.0,
        }
    )
    script["PosY"] = y
    serialized = json.dumps(script, separators=(",", ":"))
    return {
        "type": 4,
        "thisUId": uid,
        "tlBegin": 0,
        "tlEnd": 20_000_000,
        "scriptBuf": serialized,
        "scriptBufSize": len(serialized) + 1,
        "effectChainList": [
            {
                "effectList": [
                    {
                        "id": "transform",
                        "thisUId": "11111111-1111-4111-8111-{0}".format(uid[-12:]),
                        "paramList": [
                            {"name": "Scale_x", "fxParam": {"unValue": 70.0}},
                            {"name": "Scale_y", "fxParam": {"unValue": 20.0}},
                        ],
                    }
                ]
            }
        ],
        "userData": [{"key": 6, "data": base64.b64encode((12).to_bytes(4, "little")).decode("ascii")}],
    }


def write_cloneable_title_project(path: Path) -> Path:
    template_media_id = "AA-AA-AA-AA-AA-AA-4A-AA-8A-AA-AA-AA-AA-AA-AA-AA"
    template_timeline_uuid = "BB-BB-BB-BB-BB-BB-4B-BB-8B-BB-BB-BB-BB-BB-BB-BB"
    outer_timeline = {
        "timelineId": 10,
        "audioBusInfos": [{"busUid": "10000000-0000-4000-8000-000000000001"}],
        "trackInfos": [
            {
                "trackType": 1,
                "uuid": "10000000-0000-4000-8000-000000000002",
                "busUuids": ["10000000-0000-4000-8000-000000000001"],
                "clipList": [
                    {
                        "type": 7,
                        "timelineId": 12,
                        "thisUId": "10000000-0000-4000-8000-000000000003",
                        "tlBegin": 0,
                        "tlEnd": 20_000_000,
                        "userData": [
                            {"key": 6, "data": base64.b64encode((10).to_bytes(4, "little")).decode("ascii")}
                        ],
                    }
                ],
            }
        ],
        "userData": [{"key": 30309, "data": _encoded(template_timeline_uuid)}],
    }
    title_timeline = {
        "timelineId": 12,
        "trackInfos": [
            {
                "trackType": 1,
                "uuid": "12000000-0000-4000-8000-000000000001",
                "clipList": [
                    _cloneable_title_clip(
                        "1. Template",
                        "12000000-0000-4000-8000-000000000002",
                        0.5,
                    )
                ],
            },
            {
                "trackType": 1,
                "uuid": "12000000-0000-4000-8000-000000000003",
                "clipList": [
                    _cloneable_title_clip(
                        "Template subtitle",
                        "12000000-0000-4000-8000-000000000004",
                        0.72,
                    )
                ],
            },
        ],
    }
    placement_audio = {
        "type": 16,
        "timelineId": 10,
        "thisUId": "01000000-0000-4000-8000-000000000001",
        "tlBegin": 10_000_000,
        "tlEnd": 30_000_000,
        "inPoint": 0,
        "outPoint": 20_000_000,
        "userData": [
            {"key": 6, "data": base64.b64encode((1).to_bytes(4, "little")).decode("ascii")},
            {"key": 10, "data": _encoded(template_media_id)},
        ],
    }
    placement_video = dict(placement_audio)
    placement_video.update(
        {
            "type": 6,
            "thisUId": "01000000-0000-4000-8000-000000000002",
            "userData": list(placement_audio["userData"]),
        }
    )
    main_timeline = {
        "timelineId": 1,
        "trackInfos": [
            {"trackType": 2, "uuid": "01000000-0000-4000-8000-000000000003", "clipList": [placement_audio]},
            {"trackType": 1, "uuid": "01000000-0000-4000-8000-000000000004", "clipList": [placement_video]},
        ],
    }
    root_fields = {
        "productName": "Filmora",
        "projectName": "TLB",
        "projectVersion": "fixture",
        "serializationVersion": "fixture",
        "resources": [],
    }
    main = {
        "currentTimelineId": 1,
        **root_fields,
        "serialNumber": 13,
        "timelineInfos": [main_timeline, outer_timeline, title_timeline],
    }
    standalone = {
        "currentTimelineId": 10,
        **root_fields,
        "serialNumber": 13,
        "timelineInfos": [outer_timeline, title_timeline],
    }
    project_info = {
        "project_file_name": "Fixture",
        "project_date_modify": 1,
        "project_editor_create_version": "15.6.4.11894",
        "project_editor_modify_version": "15.6.4.11894",
        "project_os_name": "MacOS",
        "project_timeline_duration": 100_000_000,
        "project_timeline_framerate": [30, 1],
        "project_timeline_resolution": [1920, 1080],
        "proj_zip_save_path": str(path),
        "timeline_mediaId": "MAIN",
    }
    media_info = (
        '{"media_structure":{"Folder":{"media_item":"%s"},"media_item":"MAIN"},'
        '"media_items":{"MAIN":{"id":"MAIN","timeline_uuid":"CC-CC-CC-CC-CC-CC-4C-CC-8C-CC-CC-CC-CC-CC-CC-CC"},'
        '"%s":{"id":"%s","timeline_uuid":"%s","create_time":1}}}'
        % (template_media_id, template_media_id, template_media_id, template_timeline_uuid)
    )
    members = {
        "ProjectFolder/project_info.json": json.dumps(project_info, indent=4),
        "ProjectFolder/Medias/medias_info.json": media_info,
        "ProjectFolder/Medias/MAIN/timeline.wesproj": json.dumps(main, separators=(",", ":")),
        "ProjectFolder/Medias/{0}/timeline.wesproj".format(template_media_id): json.dumps(
            standalone, separators=(",", ":")
        ),
        "ProjectFolder/Medias/{0}/extra.json".format(template_media_id): json.dumps(
            {"mediaClipsMapInfo": {}, "allMarkersInfo": {}}, separators=(",", ":")
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, value in members.items():
            archive.writestr(member, value)
    return path
