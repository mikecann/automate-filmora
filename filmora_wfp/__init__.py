"""Evidence-driven tools for Wondershare Filmora project files."""

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .audit import audit_title_card_copy
from .diffing import diff_projects
from .evals import evaluate_project
from .mapping import map_project
from .title_cards import clone_title_cards, load_title_card_spec

__all__ = [
    "WfpArchive",
    "WfpError",
    "audit_title_card_copy",
    "diff_projects",
    "evaluate_project",
    "clone_title_cards",
    "inspect_project",
    "list_titles",
    "load_title_card_spec",
    "map_project",
    "validate_project",
]

__version__ = "0.1.0"
