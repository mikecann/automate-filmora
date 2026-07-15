"""Low-level, read-only access to a Filmora WFP archive."""

from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union


PROJECT_INFO_MEMBER = "ProjectFolder/project_info.json"
MEDIAS_INFO_MEMBER = "ProjectFolder/Medias/medias_info.json"
TIMELINE_SUFFIX = "/timeline.wesproj"
Pathish = Union[os.PathLike[str], str]


class WfpError(RuntimeError):
    """Raised when a WFP archive cannot be understood safely."""


class WfpArchive:
    """Open a `.wfp` ZIP and expose its JSON documents without modifying it."""

    def __init__(self, path: Pathish) -> None:
        self.path = Path(path).expanduser().resolve()
        self._zip: Optional[zipfile.ZipFile] = None

    def __enter__(self) -> "WfpArchive":
        if not self.path.is_file():
            raise WfpError("Project does not exist: {0}".format(self.path))
        try:
            self._zip = zipfile.ZipFile(self.path, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise WfpError("Not a readable WFP ZIP: {0}".format(self.path)) from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._zip is not None:
            self._zip.close()
        self._zip = None

    @property
    def zip_file(self) -> zipfile.ZipFile:
        if self._zip is None:
            raise WfpError("WFP archive is not open")
        return self._zip

    def members(self) -> List[zipfile.ZipInfo]:
        return self.zip_file.infolist()

    def names(self) -> List[str]:
        return self.zip_file.namelist()

    def duplicate_names(self) -> List[str]:
        counts: Dict[str, int] = {}
        for name in self.names():
            counts[name] = counts.get(name, 0) + 1
        return sorted(name for name, count in counts.items() if count > 1)

    def read_json(self, member: str) -> Dict[str, Any]:
        try:
            raw = self.zip_file.read(member)
        except KeyError as exc:
            raise WfpError("Missing archive member: {0}".format(member)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WfpError("Invalid JSON in {0}: {1}".format(member, exc)) from exc
        if not isinstance(value, dict):
            raise WfpError("Expected a JSON object in {0}".format(member))
        return value

    def project_info(self) -> Dict[str, Any]:
        return self.read_json(PROJECT_INFO_MEMBER)

    def main_timeline_member(self) -> str:
        media_id = self.project_info().get("timeline_mediaId")
        if not media_id:
            raise WfpError("project_info.json does not contain timeline_mediaId")
        member = "ProjectFolder/Medias/{0}/timeline.wesproj".format(media_id)
        if member not in self.names():
            raise WfpError("Main timeline is missing: {0}".format(member))
        return member

    def main_timeline(self) -> Dict[str, Any]:
        return self.read_json(self.main_timeline_member())

    def timeline_members(self) -> List[str]:
        return sorted(name for name in self.names() if name.endswith(TIMELINE_SUFFIX))

    def timeline_documents(self) -> Iterator[Tuple[str, Dict[str, Any]]]:
        for member in self.timeline_members():
            yield member, self.read_json(member)

    def safe_extract(self, destination: Pathish) -> Path:
        """Extract to a new directory while rejecting traversal and symlinks."""

        root = Path(destination).expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise WfpError("Destination is not empty: {0}".format(root))
        root.mkdir(parents=True, exist_ok=True)

        for info in self.members():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise WfpError("Unsafe archive path: {0}".format(info.filename))

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise WfpError("Refusing archive symlink: {0}".format(info.filename))

            target = root.joinpath(*member.parts)
            if os.path.commonpath((str(root), str(target.resolve()))) != str(root):
                raise WfpError("Archive path escapes destination: {0}".format(info.filename))

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with self.zip_file.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

        return root
