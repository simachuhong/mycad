# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command schema for atomic geometric annotation changes."""

from mycad.commands.spec import CliSyntax, CommandSpec

_RECORD = {"type": "object"}
_ID = {"type": "string", "minLength": 32, "maxLength": 36}
_FIELDS: dict[str, object] = {
    key: {"type": "array", "items": _ID if key.startswith("remove_") else _RECORD}
    for key in (
        "add_frames",
        "update_frames",
        "remove_frames",
        "add_datums",
        "update_datums",
        "remove_datums",
    )
}
TOLERANCE_COMMAND_SPEC = CommandSpec(
    id="drawing.tolerance.batch",
    version=1,
    summary_en="Change geometric tolerances and datum labels atomically",
    label_zh="批量编辑形位公差与基准",
    params_schema={"type": "object", "properties": _FIELDS, "additionalProperties": False},
    cli=CliSyntax(verb_aliases=()),
    min_archive_version=4,
)

REFERENCE_DIMENSIONS_COMMAND_SPEC = CommandSpec(
    id="drawing.reference_dimensions.batch",
    version=1,
    summary_en="Change independent reference dimensions atomically",
    label_zh="批量编辑独立参考尺寸",
    params_schema={
        "type": "object",
        "properties": {
            "add": {"type": "array", "items": _RECORD},
            "update": {"type": "array", "items": _RECORD},
            "remove": {"type": "array", "items": _ID},
        },
        "additionalProperties": False,
    },
    cli=CliSyntax(verb_aliases=()),
    min_archive_version=4,
)
