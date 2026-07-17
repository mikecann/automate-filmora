"""Evidence-driven tools for Wondershare Filmora project files."""

from .analysis import inspect_project, list_titles, validate_project
from .archive import WfpArchive, WfpError
from .audit import audit_title_card_copy
from .corpus import discover_projects, survey_projects
from .diffing import diff_projects
from .edit_plan import (
    EDIT_PLAN_API_VERSION,
    EDIT_PLAN_SCHEMA_VERSION,
    CloneTitleCardsOperation,
    EditPlan,
    EditPlanApplicationResult,
    EditPlanExplanation,
    EditPlanSource,
    EditTargetsResult,
    TitleCardSpec,
    TitleCardTemplateSelector,
    ReplaceTitleTextOperation,
    apply_edit_plan,
    edit_plan_schema,
    explain_edit_plan,
    list_edit_targets,
    load_edit_plan,
    project_sha256,
)
from .evals import evaluate_project
from .mapping import map_project
from .rotation import (
    audit_clip_rotation_copy,
    preflight_clip_rotation,
    replace_clip_rotation,
)
from .title_cards import clone_title_cards, load_title_card_spec
from .title_text import (
    audit_title_text_copy,
    preflight_title_text_replacement,
    replace_title_text,
)

__all__ = [
    "WfpArchive",
    "WfpError",
    "EDIT_PLAN_API_VERSION",
    "EDIT_PLAN_SCHEMA_VERSION",
    "CloneTitleCardsOperation",
    "ReplaceTitleTextOperation",
    "EditPlan",
    "EditPlanApplicationResult",
    "EditPlanExplanation",
    "EditPlanSource",
    "EditTargetsResult",
    "TitleCardSpec",
    "TitleCardTemplateSelector",
    "apply_edit_plan",
    "audit_title_text_copy",
    "audit_clip_rotation_copy",
    "edit_plan_schema",
    "audit_title_card_copy",
    "diff_projects",
    "evaluate_project",
    "explain_edit_plan",
    "clone_title_cards",
    "discover_projects",
    "inspect_project",
    "list_edit_targets",
    "list_titles",
    "load_edit_plan",
    "load_title_card_spec",
    "map_project",
    "project_sha256",
    "preflight_clip_rotation",
    "preflight_title_text_replacement",
    "replace_title_text",
    "replace_clip_rotation",
    "survey_projects",
    "validate_project",
]

__version__ = "0.3.0"
