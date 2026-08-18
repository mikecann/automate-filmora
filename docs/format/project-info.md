# Project metadata and load integrity

Status: controlled load experiments with Filmora 15.6.4.11894 and
15.7.11.12437 on macOS.

`ProjectFolder/project_info.json` is not just descriptive metadata. At least one
field participates in a Filmora load-integrity check.

## Controlled experiment

Starting from one byte-identical project copy that loaded successfully, five
variants rewrote only `project_info.json`:

| Change | Filmora result |
| --- | --- |
| JSON whitespace only | loaded |
| `project_file_name` only | loaded |
| `proj_zip_save_path` only | loaded |
| `project_date_modify` increased by one | rejected as incompatible |
| all three fields above | rejected as incompatible |

The same build accepted compact reserialization of the main timeline and
duplicate-preserving reserialization of `medias_info.json`, both separately and
together.

`project_source` remained unchanged in every variant. It looks like an integrity
token, but its exact input and algorithm are not known. The narrow writer must
therefore preserve `project_date_modify` and `project_source` unchanged. Filmora
can normalize them itself on the next application save.

Observed Filmora-created backup/save-as files changed `project_date_modify`,
`project_source`, and `project_guid` together while retaining the same
`timeline_mediaId`. That is consistent with an integrity relationship, but does
not prove its algorithm. Generated copies preserve all four fields.

A second Filmora-native Save As kept the semantic graph unchanged but again
rotated those three fields, rewrote the stored filename and path, and renumbered
every timeline ID with matching reference updates. `project_source` must stay
opaque. There is still no evidence that external tooling can calculate it.

The project name and stored save path may be updated for a copy. Filmora still
uses the actual opened path as the project location.

## Seedless creation experiment, Filmora 15.7.11.12437

On 2026-07-31, two independent single-source Fixture A projects and one
single-source Fixture B project were created in Filmora on macOS 26.5.2. The
same media received the same `sourceUuid` across both A projects, while project,
timeline, track, clip, effect, and link identifiers varied. A no-op save made
no byte change.

A scratch-built project passed archive validation, media validation, format
evaluation, and the rough-cut seed-shape audit, but Filmora rejected it as
incompatible before timeline parsing. Preserving the observed
`project_guid`/`project_source`/`project_date_modify` tuple was not enough.
This confirms that a truly seedless WFP writer is still unsafe. Do not ship an
embedded opaque token or machine-specific bootstrap project as a substitute.

The practical supported path remains a Filmora-created single-source project.
Callers such as Video HQ may discover and reuse that project automatically, so
the user does not need to create or name a separate automation template.
