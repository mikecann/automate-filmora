from __future__ import annotations

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
