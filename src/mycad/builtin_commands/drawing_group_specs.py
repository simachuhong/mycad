# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned schemas for independent drawing group commands."""

from mycad.commands.spec import CliSyntax, CommandSpec

_ID = {"type": "string", "minLength": 32, "maxLength": 36}
_REF = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "object_id": _ID,
        "sketch_id": {"oneOf": [_ID, {"const": None}]},
    },
    "required": ["kind", "object_id", "sketch_id"],
    "additionalProperties": False,
}
_GROUP = {
    "type": "object",
    "properties": {
        "group_id": _ID,
        "members": {"type": "array", "minItems": 1, "items": _REF},
        "name": {"oneOf": [{"type": "string", "minLength": 1}, {"const": None}]},
        "description": {"type": "string"},
        "selectable": {"type": "boolean"},
    },
    "required": ["group_id", "members", "name", "description", "selectable"],
    "additionalProperties": False,
}
_REMOVE = {
    "type": "object",
    "properties": {"group_id": _ID},
    "required": ["group_id"],
    "additionalProperties": False,
}

DRAWING_GROUP_SPECS = tuple(
    CommandSpec(
        id=f"drawing.group.{action}",
        version=1,
        summary_en=f"{action.title()} a drawing group",
        label_zh=label,
        params_schema=schema,
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=8,
    )
    for action, label, schema in (
        ("create", "创建二维组", _GROUP),
        ("update", "修改二维组", _GROUP),
        ("remove", "删除二维组", _REMOVE),
    )
)

DRAWING_OBJECT_BATCH_SPEC = CommandSpec(
    id="drawing.objects.batch",
    version=1,
    summary_en="Apply one atomic drawing operation",
    label_zh="二维对象复合操作",
    params_schema={
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "version": {"type": "integer", "minimum": 1},
                        "params": {"type": "object"},
                    },
                    "required": ["id", "version", "params"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["operations"],
        "additionalProperties": False,
    },
    cli=CliSyntax(verb_aliases=()),
    min_archive_version=8,
)
