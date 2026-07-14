"""Evidence-driven tools for Wondershare Filmora project files."""

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .diffing import diff_projects
from .title_cards import clone_title_cards, load_title_card_spec

__all__ = [
    "WfpArchive",
    "WfpError",
    "diff_projects",
    "clone_title_cards",
    "inspect_project",
    "list_titles",
    "load_title_card_spec",
    "validate_project",
]

__version__ = "0.1.0"
