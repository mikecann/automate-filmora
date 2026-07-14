"""Read-only tools for Wondershare Filmora project files."""

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .diffing import diff_projects

__all__ = [
    "WfpArchive",
    "WfpError",
    "diff_projects",
    "inspect_project",
    "list_titles",
    "validate_project",
]

__version__ = "0.1.0"
