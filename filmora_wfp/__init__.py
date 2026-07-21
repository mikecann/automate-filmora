"""Evidence-driven tools for Wondershare Filmora project files."""

__version__ = "0.13.9"

from .analysis import inspect_project, list_titles, validate_project
from .anchor import (
    audit_clip_anchor_copy,
    normalized_anchor,
    preflight_clip_anchor,
    replace_clip_anchor,
)
from .archive import WfpArchive, WfpError
from .background_blur import (
    audit_clip_background_blur_copy,
    preflight_clip_background_blur,
    replace_clip_background_blur,
)
from .blend_mode import audit_clip_blend_mode_copy, preflight_clip_blend_mode, replace_clip_blend_mode
from .audio_fade import (
    audit_clip_fade_in_copy,
    preflight_clip_fade_in,
    replace_clip_fade_in,
)
from .audio_fade_out import (
    audit_clip_fade_out_copy,
    preflight_clip_fade_out,
    replace_clip_fade_out,
)
from .audio_balance import audit_clip_audio_balance_copy, preflight_clip_audio_balance, replace_clip_audio_balance
from .hsl import audit_clip_hsl_copy, preflight_clip_hsl, replace_clip_hsl
from .equalizer import audit_clip_equalizer_copy, preflight_clip_equalizer, replace_clip_equalizer
from .audit import audit_title_card_copy
from .corpus import discover_projects, survey_projects
from .corner_radius import (
    audit_clip_corner_radius_copy,
    preflight_clip_corner_radius,
    replace_clip_corner_radius,
)
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
    ReplaceClipPositionOperation,
    ReplaceClipScaleOperation,
    ReplaceClipVolumeGainOperation,
    ReplaceClipFadeInOperation,
    ReplaceClipFadeOutOperation,
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
from .position import (
    audit_clip_position_copy,
    normalized_position,
    preflight_clip_position,
    replace_clip_position,
)
from .opacity import audit_clip_opacity_copy, preflight_clip_opacity, replace_clip_opacity
from .scale import (
    audit_clip_scale_copy,
    preflight_clip_scale,
    replace_clip_scale,
)
from .stabilization import (
    audit_clip_stabilization_copy,
    preflight_clip_stabilization,
    replace_clip_stabilization,
)
from .video_denoise import (
    audit_clip_video_denoise_copy,
    preflight_clip_video_denoise,
    replace_clip_video_denoise,
)
from .horizontal_flip import (
    audit_clip_horizontal_flip_copy,
    preflight_clip_horizontal_flip,
    replace_clip_horizontal_flip,
)
from .vertical_flip import (
    audit_clip_vertical_flip_copy,
    preflight_clip_vertical_flip,
    replace_clip_vertical_flip,
)
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
from .rough_cut import (
    SilenceInterval,
    RepeatedWordSpan,
    SpeechRegion,
    TakeDecision,
    TranscriptSegment,
    TranscriptWord,
    build_rough_cut_plan,
    compare_keep_ranges,
    detect_duplicate_takes,
    detect_repeated_word_spans,
    detect_silence,
    evaluate_rough_cut_plan,
    inspect_rough_cut_seed,
    load_transcript,
    parse_ffmpeg_silence_output,
    parse_srt,
    speech_regions_from_silences,
    transcribe_media,
    transcribe_media_ranges,
    write_rough_cut_outputs,
)
from .rough_cut_wfp import (
    audit_rough_cut_project,
    inspect_rough_cut_seed_shape,
    preflight_rough_cut_project,
    write_rough_cut_project,
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
    "ReplaceClipPositionOperation",
    "ReplaceClipScaleOperation",
    "ReplaceClipVolumeGainOperation",
    "ReplaceClipFadeInOperation",
    "ReplaceClipFadeOutOperation",
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
    "audit_clip_fade_in_copy",
    "audit_clip_anchor_copy",
    "audit_clip_corner_radius_copy",
    "audit_clip_fade_out_copy",
    "audit_clip_position_copy",
    "audit_clip_scale_copy",
    "audit_clip_horizontal_flip_copy",
    "audit_clip_vertical_flip_copy",
    "audit_title_text_copy",
    "audit_clip_rotation_copy",
    "audit_clip_volume_gain_copy",
    "audit_clip_hsl_copy",
    "audit_clip_equalizer_copy",
    "audit_clip_stabilization_copy",
    "audit_clip_video_denoise_copy",
    "audit_clip_blend_mode_copy",
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
    "preflight_clip_anchor",
    "preflight_clip_corner_radius",
    "preflight_clip_fade_in",
    "preflight_clip_fade_out",
    "preflight_clip_position",
    "preflight_clip_scale",
    "preflight_clip_horizontal_flip",
    "preflight_clip_vertical_flip",
    "preflight_clip_volume_gain",
    "preflight_clip_hsl",
    "preflight_clip_equalizer",
    "preflight_clip_stabilization",
    "preflight_clip_video_denoise",
    "preflight_clip_blend_mode",
    "preflight_linked_transition",
    "preflight_title_text_replacement",
    "replace_title_text",
    "replace_clip_rotation",
    "replace_clip_anchor",
    "replace_clip_corner_radius",
    "replace_clip_fade_in",
    "replace_clip_fade_out",
    "replace_clip_position",
    "replace_clip_scale",
    "replace_clip_horizontal_flip",
    "replace_clip_vertical_flip",
    "replace_clip_volume_gain",
    "replace_clip_hsl",
    "replace_clip_equalizer",
    "replace_clip_stabilization",
    "replace_clip_video_denoise",
    "replace_clip_blend_mode",
    "replace_linked_transition_duration",
    "remove_linked_transition",
    "survey_projects",
    "validate_project",
    "normalized_position",
    "normalized_anchor",
    "SilenceInterval",
    "RepeatedWordSpan",
    "SpeechRegion",
    "TakeDecision",
    "TranscriptSegment",
    "TranscriptWord",
    "build_rough_cut_plan",
    "compare_keep_ranges",
    "detect_duplicate_takes",
    "detect_repeated_word_spans",
    "detect_silence",
    "evaluate_rough_cut_plan",
    "inspect_rough_cut_seed",
    "load_transcript",
    "parse_ffmpeg_silence_output",
    "parse_srt",
    "speech_regions_from_silences",
    "transcribe_media",
    "transcribe_media_ranges",
    "write_rough_cut_outputs",
    "audit_rough_cut_project",
    "inspect_rough_cut_seed_shape",
    "preflight_rough_cut_project",
    "write_rough_cut_project",
]
