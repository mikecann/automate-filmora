# Project metadata and load integrity

Status: controlled load experiments with Filmora 15.6.4.11894 on macOS.

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

The project name and stored save path may be updated for a copy. Filmora still
uses the actual opened path as the project location.
