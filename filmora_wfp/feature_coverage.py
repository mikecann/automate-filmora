"""Curated coverage of Filmora features confirmed by controlled experiments."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


# area, feature, status, evidence. Frequency in a project corpus is never enough
# to move a row from open to mapped.
_ROWS: List[Tuple[str, str, str, str]] = [
    ("project", "WFP archive validation", "writable", "archive and eval-format probes"),
    ("project", "WFP bundle discovery", "mapped", "corpus survey"),
    ("project", "timeline graph and nested compounds", "mapped", "canonical map"),
    ("project", "track creation and reorder", "open", "no controlled pair"),
    ("project", "track visibility lock mute solo", "partial", "fields inventoried, enums open"),
    ("timeline", "linked A/V move", "writable", "edit-plan schema 4"),
    ("timeline", "linked A/V start and end trim", "writable", "edit-plan schema 4"),
    ("timeline", "linked A/V split", "writable", "edit-plan schema 5"),
    ("timeline", "unlink and relink clips", "open", "no controlled pair"),
    ("titles", "title text and style inspection", "mapped", "scriptBuf parser"),
    ("titles", "same-length title replacement", "writable", "edit-plan schema 2"),
    ("titles", "compound title-card clone", "writable", "source-aware clone audit"),
    ("titles", "arbitrary-length title auto-sizing", "partial", "scale derivation open"),
    ("transitions", "linked Dissolve insertion shape", "mapped", "controlled add and undo"),
    ("transitions", "linked Dissolve duration and removal", "writable", "edit-plan schema 3"),
    ("transitions", "other transition families", "mapped", "Fast Wipe Left insertion repeated; owner-side shape confirmed"),
    ("video.transform", "position X and Y", "writable", "edit-plan schema 9"),
    ("video.transform", "uniform scale", "writable", "edit-plan schema 10"),
    ("video.transform", "rotation", "writable", "edit-plan schema 3"),
    ("video.transform", "horizontal flip", "writable", "direct guarded writer"),
    ("video.transform", "vertical flip", "writable", "direct guarded writer"),
    ("video.transform", "anchor point X and Y", "writable", "direct guarded writer"),
    ("video.transform", "uniform corner radius", "writable", "direct guarded writer"),
    ("video.transform", "path curve", "open", "UI inventoried only"),
    ("video.effects", "ColorBlur typed parameters", "partial", "exact-build backup corpus; UI repeat pending"),
    ("video.effects", "Allpurpose Position effect", "partial", "exact-build backup corpus; keyframe payload opaque"),
    ("text.effects", "Text Dropout speed and scale", "partial", "exact-build backup corpus; UI repeat pending"),
    ("video.compositing", "static opacity", "writable", "guarded existing-overlay pipBuf replacement; repeated UI diff"),
    ("video.compositing", "blend mode", "writable", "guarded existing pipBuf modes: Normal, Multiply, Screen"),
    ("video.background", "blur enable and strength preset", "writable", "guarded existing-field writer; Filmora sample round trip"),
    ("video.background", "other fill types and styles", "partial", "Color enum 2 observed; payload and other types open"),
    ("video.animation", "Fade In and Fade Out presets", "mapped", "apply undo redo"),
    ("video.animation", "slide Pause Vortex and Zoom presets", "mapped", "independent matrix"),
    ("video.animation", "custom keyframes and interpolation", "partial", "MD5 generation open"),
    ("speed", "linked uniform speed", "mapped", "1.25 to 1.50 repeat"),
    ("speed", "Maintain Pitch", "mapped", "inverse speedWithPitch flag"),
    ("speed", "Reverse Speed", "mapped", "linked flags and animation mirroring"),
    ("speed", "stock speed ramps", "mapped", "six independent preset curves"),
    ("speed", "custom ramp editing", "open", "derivative and MD5 generation open"),
    ("speed", "AI frame interpolation", "open", "custom dropdown unresolved"),
    ("color.basic", "temperature tint vibrance saturation", "mapped", "direct scalar repeats"),
    ("color.basic", "first-use AdjustColor insertion", "mapped", "controlled Exposure insertion and Filmora round trip"),
    ("color.light", "exposure brightness contrast highlights shadows whites blacks", "mapped", "direct scalar repeats"),
    ("color.basic", "sharpen", "mapped", "separate effect repeat"),
    ("color.vignette", "amount size roundness feather exposure highlight", "mapped", "direct scalar repeats"),
    ("color.hsl", "channel hue prefixes and Red HSL", "mapped", "controlled channel sweep"),
    ("color.hsl", "non-Red saturation and luminance", "mapped", "Orange saturation and luminance repeats"),
    ("color.hsl", "existing static HSL scalar replacement", "writable", "guarded AdjustColor parameter writer"),
    ("color.curves", "RGB curves", "partial", "knots and derived controls mapped"),
    ("color.curves", "six Hue Saturation curve modes", "partial", "one mode edited"),
    ("color.wheels", "shadow midtone highlight red component", "partial", "conversion incomplete"),
    ("color", "LUT selection and intensity", "open", "fields inventoried only"),
    ("color", "Auto Color and white balance picker", "open", "no controlled pair"),
    ("audio", "volume gain", "writable", "edit-plan schema 6"),
    ("audio", "fade in", "writable", "edit-plan schema 7"),
    ("audio", "fade out", "writable", "edit-plan schema 8"),
    ("audio", "balance pan", "writable", "guarded Balance scalar; repeated UI normalization"),
    ("audio", "equalizer", "writable", "guarded existing Rock and Pop preset replacement; real-project round trip"),
    ("audio", "denoise ducking normalization voice effects", "partial", "Normal Denoise enable and strength repeated; other audio AI controls open"),
    ("video.analysis", "Motion Blur", "external_dependency", "toggle starts model update and processing"),
    ("video.analysis", "Stabilization", "open", "controlled save pending"),
    ("video.analysis", "Video Denoise and Lens Correction", "open", "UI inventoried only"),
    ("video.ai", "AI Video Enhancer modes", "external_dependency", "credit and model UI only"),
    ("video.ai", "AI Object Remover", "external_dependency", "UI inventoried only"),
    ("video.tracking", "Motion and Planar Tracking", "open", "UI inventoried only"),
]


def feature_coverage(status: Optional[str] = None) -> Dict[str, Any]:
    """Return the coverage matrix, optionally filtered without altering totals."""

    statuses = {row[2] for row in _ROWS}
    if status is not None and status not in statuses:
        raise ValueError("Unknown coverage status: {0}".format(status))
    features = [
        {"area": area, "feature": feature, "status": state, "evidence": evidence}
        for area, feature, state, evidence in _ROWS
        if status is None or state == status
    ]
    counts = Counter(row[2] for row in _ROWS)
    return {
        "schema_version": 1,
        "filmora_reference": "15.6.4.11894 macOS",
        "status_definitions": {
            "writable": "guarded copy writer exists and passed acceptance",
            "mapped": "a controlled UI diff confirms serialization",
            "partial": "some structure is confirmed but variants remain open",
            "open": "no sufficient controlled mapping yet",
            "external_dependency": "requires a model download, cloud service, or credits",
        },
        "summary": {
            "total": len(_ROWS),
            "areas": len({row[0] for row in _ROWS}),
            "by_status": dict(sorted(counts.items())),
        },
        "filter": status,
        "features": features,
    }
