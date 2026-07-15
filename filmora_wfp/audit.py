"""Source-aware audits for generated Filmora title-card copies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Union

from .analysis import validate_project
from .archive import MEDIAS_INFO_MEMBER, PROJECT_INFO_MEMBER, TIMELINE_SUFFIX, WfpArchive, WfpError


Pathish = Union[str, Path]
_PROTECTED_PROJECT_FIELDS = (
    "project_date_modify",
    "project_source",
    "project_guid",
    "timeline_mediaId",
)


def _timeline_ids(document: Dict[str, Any]) -> Set[Any]:
    timelines = document.get("timelineInfos")
    if not isinstance(timelines, list):
        return set()
    return {
        timeline.get("timelineId")
        for timeline in timelines
        if isinstance(timeline, dict) and timeline.get("timelineId") is not None
    }


def _values_for_key(value: Any, target_key: str) -> List[str]:
    found: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == target_key and isinstance(item, str):
                found.append(item)
            found.extend(_values_for_key(item, target_key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_values_for_key(item, target_key))
    return found


def _audit_added_titles(member: str, document: Dict[str, Any], errors: List[str]) -> int:
    title_count = 0
    for timeline in document.get("timelineInfos") or []:
        if not isinstance(timeline, dict):
            continue
        for track in timeline.get("trackInfos") or []:
            if not isinstance(track, dict):
                continue
            for clip in track.get("clipList") or []:
                if not isinstance(clip, dict) or clip.get("type") != 4:
                    continue
                script_buffer = clip.get("scriptBuf")
                if not isinstance(script_buffer, str):
                    continue
                try:
                    script = json.loads(script_buffer)
                except json.JSONDecodeError:
                    errors.append("Added title has invalid scriptBuf JSON in {0}".format(member))
                    continue
                text = script.get("Text")
                if not text:
                    continue
                title_count += 1

                expected_size = len(script_buffer.encode("utf-8")) + 1
                if clip.get("scriptBufSize") != expected_size:
                    errors.append("Added title has an inconsistent scriptBufSize in {0}".format(member))

                text_data = script.get("TextData") or []
                first = text_data[0] if text_data and isinstance(text_data[0], dict) else {}
                if first.get("CharData") != text:
                    errors.append("Added title Text and CharData differ in {0}".format(member))
                basic = first.get("Basic") if isinstance(first.get("Basic"), dict) else {}
                sizes = [basic.get(field) for field in ("FontSize", "FontHSize", "FontVSize")]
                if any(value is None for value in sizes) or len(set(sizes)) != 1:
                    errors.append("Added title font-size fields differ in {0}".format(member))

                transform_values: Dict[str, Any] = {}
                for chain in clip.get("effectChainList") or []:
                    if not isinstance(chain, dict):
                        continue
                    for effect in chain.get("effectList") or []:
                        if not isinstance(effect, dict):
                            continue
                        effect_id = str(effect.get("id") or "")
                        is_transform = effect.get("display") == "transform" or effect_id == "transform"
                        if not is_transform and not effect_id.endswith("/transform"):
                            continue
                        for parameter in effect.get("paramList") or []:
                            if not isinstance(parameter, dict):
                                continue
                            name = parameter.get("name")
                            fx_param = parameter.get("fxParam")
                            if name in ("Scale_x", "Scale_y") and isinstance(fx_param, dict):
                                transform_values[name] = fx_param.get("unValue")
                for script_field, transform_field in (("ScaleX", "Scale_x"), ("ScaleY", "Scale_y")):
                    script_value = script.get(script_field)
                    transform_value = transform_values.get(transform_field)
                    try:
                        difference = abs(float(transform_value) - float(script_value) * 100.0)
                    except (TypeError, ValueError):
                        difference = float("inf")
                    if difference > 0.0001:
                        errors.append(
                            "Added title {0} does not match its transform in {1}".format(
                                script_field, member
                            )
                        )
    return title_count


def audit_title_card_copy(
    source: Pathish,
    output: Pathish,
    check_media: bool = False,
) -> Dict[str, Any]:
    """Check invariants that only make sense relative to the source project."""

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    errors: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    if source_path == output_path:
        return {
            "valid": False,
            "errors": ["Source and output paths must differ"],
            "warnings": [],
            "details": {},
        }

    structural = validate_project(output_path, check_media=check_media)
    errors.extend(structural.get("errors") or [])
    warnings.extend(structural.get("warnings") or [])

    try:
        with WfpArchive(source_path) as source_archive, WfpArchive(output_path) as output_archive:
            source_names = set(source_archive.names())
            output_names = set(output_archive.names())
            removed_members = sorted(source_names - output_names)
            added_members = sorted(output_names - source_names)
            changed_members = sorted(
                member
                for member in source_names & output_names
                if source_archive.zip_file.read(member) != output_archive.zip_file.read(member)
            )

            source_main_member = source_archive.main_timeline_member()
            output_main_member = output_archive.main_timeline_member()
            allowed_changed = {PROJECT_INFO_MEMBER, MEDIAS_INFO_MEMBER, source_main_member}
            unexpected_changed = sorted(set(changed_members) - allowed_changed)

            if removed_members:
                errors.append("Generated copy removed source archive members")
            if output_main_member != source_main_member:
                errors.append("Generated copy changed the main timeline route")
            if unexpected_changed:
                errors.append(
                    "Generated copy changed unrelated members: {0}".format(
                        ", ".join(unexpected_changed)
                    )
                )

            source_info = source_archive.project_info()
            output_info = output_archive.project_info()
            changed_protected_fields: List[str] = []
            for field in _PROTECTED_PROJECT_FIELDS:
                if source_info.get(field) != output_info.get(field):
                    changed_protected_fields.append(field)
            if changed_protected_fields:
                errors.append(
                    "Generated copy changed protected project metadata: {0}".format(
                        ", ".join(changed_protected_fields)
                    )
                )

            if output_info.get("project_file_name") != output_path.stem:
                warnings.append("project_file_name does not match the generated filename")
            if output_info.get("proj_zip_save_path") != str(output_path):
                warnings.append("proj_zip_save_path does not match the generated path")

            added_timeline_members = sorted(
                member for member in added_members if member.endswith(TIMELINE_SUFFIX)
            )
            added_extra_members = sorted(
                member for member in added_members if member.endswith("/extra.json")
            )
            expected_added: Set[str] = set()
            for timeline_member in added_timeline_members:
                expected_added.add(timeline_member)
                expected_added.add(timeline_member[: -len("timeline.wesproj")] + "extra.json")
            unexpected_added = sorted(set(added_members) - expected_added)
            missing_pairs = sorted(expected_added - set(added_members))
            if unexpected_added:
                errors.append(
                    "Generated copy added unexpected members: {0}".format(
                        ", ".join(unexpected_added)
                    )
                )
            if missing_pairs or len(added_timeline_members) != len(added_extra_members):
                errors.append("Generated card media folders do not contain timeline/extra pairs")
            if not added_timeline_members:
                errors.append("Generated copy contains no new card timelines")

            source_main = source_archive.main_timeline()
            output_main = output_archive.main_timeline()
            source_ids = _timeline_ids(source_main)
            output_ids = _timeline_ids(output_main)
            source_instance_ids = set(_values_for_key(source_main, "thisUId"))
            output_current_id = output_main.get("currentTimelineId")
            output_current = next(
                (
                    timeline
                    for timeline in output_main.get("timelineInfos") or []
                    if isinstance(timeline, dict) and timeline.get("timelineId") == output_current_id
                ),
                None,
            )
            if output_current is None:
                errors.append("Generated copy has no resolvable current timeline")

            new_outer_ids: List[Any] = []
            standalone_ids: Set[Any] = set()
            added_title_count = 0
            new_instance_ids: List[str] = []
            for member in added_timeline_members:
                document = output_archive.read_json(member)
                outer_id = document.get("currentTimelineId")
                ids = _timeline_ids(document)
                new_outer_ids.append(outer_id)
                standalone_ids.update(ids)
                if outer_id not in ids:
                    errors.append("Added standalone timeline has an unresolved currentTimelineId")
                if not ids.issubset(output_ids):
                    errors.append("Added standalone timeline IDs are missing from the main document")
                if ids & source_ids:
                    errors.append("Added standalone timeline reuses source timeline IDs")
                member_title_count = _audit_added_titles(member, document, errors)
                added_title_count += member_title_count
                new_instance_ids.extend(_values_for_key(document, "thisUId"))
                if member_title_count != 2:
                    errors.append(
                        "Added card timeline contains {0} non-empty titles instead of two: {1}".format(
                            member_title_count, member
                        )
                    )

            if len(new_outer_ids) != len(set(new_outer_ids)):
                errors.append("Added standalone cards reuse an outer timeline ID")
            if len(new_instance_ids) != len(set(new_instance_ids)):
                errors.append("Added standalone cards reuse thisUId instance identifiers")
            if set(new_instance_ids) & source_instance_ids:
                errors.append("Added standalone cards reuse source thisUId instance identifiers")

            if output_current is not None:
                placements: Dict[Any, List[Dict[str, Any]]] = {
                    outer_id: [] for outer_id in new_outer_ids
                }
                for track in output_current.get("trackInfos") or []:
                    if not isinstance(track, dict):
                        continue
                    for clip in track.get("clipList") or []:
                        if isinstance(clip, dict) and clip.get("timelineId") in placements:
                            placements[clip.get("timelineId")].append(
                                {"track_type": track.get("trackType"), "clip": clip}
                            )
                for outer_id, placement_entries in placements.items():
                    track_types = [entry["track_type"] for entry in placement_entries]
                    if len(track_types) != 2 or set(track_types) != {1, 2}:
                        errors.append(
                            "Generated outer timeline {0} is not placed once on visual and audio tracks".format(
                                outer_id
                            )
                        )
                        continue
                    ranges = {
                        (
                            entry["clip"].get("tlBegin"),
                            entry["clip"].get("tlEnd"),
                            entry["clip"].get("inPoint"),
                            entry["clip"].get("outPoint"),
                        )
                        for entry in placement_entries
                    }
                    if len(ranges) != 1:
                        errors.append(
                            "Generated outer timeline {0} has mismatched visual/audio ranges".format(
                                outer_id
                            )
                        )

            details = {
                "source": str(source_path),
                "output": str(output_path),
                "changed_members": changed_members,
                "added_members": added_members,
                "removed_members": removed_members,
                "new_card_count": len(added_timeline_members),
                "new_title_count": added_title_count,
                "new_instance_id_count": len(new_instance_ids),
                "new_outer_timeline_ids": new_outer_ids,
                "new_timeline_ids": sorted(standalone_ids, key=str),
                "protected_project_fields": list(_PROTECTED_PROJECT_FIELDS),
                "structural_validation": structural,
            }
    except WfpError as exc:
        errors.append(str(exc))

    return {"valid": not errors, "errors": errors, "warnings": warnings, "details": details}
