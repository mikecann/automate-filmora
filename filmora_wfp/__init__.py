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
    ReplaceClipRotationOperation,
    ReplaceClipVolumeGainOperation,
    ReplaceLinkedTransitionDurationOperation,
    RemoveLinkedTransitionOperation,
    MoveLinkedAvPairOperation,
    TrimLinkedAvPairStartOperation,
    TrimLinkedAvPairEndOperation,
    SplitLinkedAvPairOperation,
    apply_edit_plan,
    edit_plan_schema,
    explain_edit_plan,
    list_edit_targets,
    load_edit_plan,
    project_sha256,
)
from .evals import evaluate_project
from .mapping import map_project
from .linked_av import (
    audit_linked_av_end_trim_copy,
    audit_linked_av_move_copy,
    move_linked_av_pair,
    preflight_linked_av_end_trim,
    preflight_linked_av_move,
    trim_linked_av_pair_end,
)
from .linked_av_start_trim import (
    audit_linked_av_start_trim_copy,
    preflight_linked_av_start_trim,
    trim_linked_av_pair_start,
)
from .linked_av_split import (
    audit_linked_av_split_copy,
    preflight_linked_av_split,
    split_linked_av_pair,
)
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
from .transitions import (
    audit_linked_transition_duration_copy,
    audit_linked_transition_removal_copy,
    preflight_linked_transition,
    remove_linked_transition,
    replace_linked_transition_duration,
)
from .volume import (
    audit_clip_volume_gain_copy,
    preflight_clip_volume_gain,
    replace_clip_volume_gain,
)

__all__ = [
    "WfpArchive",
    "WfpError",
    "EDIT_PLAN_API_VERSION",
    "EDIT_PLAN_SCHEMA_VERSION",
    "CloneTitleCardsOperation",
    "ReplaceTitleTextOperation",
    "ReplaceClipRotationOperation",
    "ReplaceClipVolumeGainOperation",
    "ReplaceLinkedTransitionDurationOperation",
    "RemoveLinkedTransitionOperation",
    "MoveLinkedAvPairOperation",
    "TrimLinkedAvPairStartOperation",
    "TrimLinkedAvPairEndOperation",
    "SplitLinkedAvPairOperation",
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
    "audit_clip_volume_gain_copy",
    "audit_linked_transition_duration_copy",
    "audit_linked_transition_removal_copy",
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
    "audit_linked_av_move_copy",
    "audit_linked_av_end_trim_copy",
    "audit_linked_av_start_trim_copy",
    "audit_linked_av_split_copy",
    "move_linked_av_pair",
    "preflight_linked_av_end_trim",
    "preflight_linked_av_start_trim",
    "preflight_linked_av_move",
    "preflight_linked_av_split",
    "trim_linked_av_pair_end",
    "trim_linked_av_pair_start",
    "split_linked_av_pair",
    "project_sha256",
    "preflight_clip_rotation",
    "preflight_clip_volume_gain",
    "preflight_linked_transition",
    "preflight_title_text_replacement",
    "replace_title_text",
    "replace_clip_rotation",
    "replace_clip_volume_gain",
    "replace_linked_transition_duration",
    "remove_linked_transition",
    "survey_projects",
    "validate_project",
]

__version__ = "0.8.0"
