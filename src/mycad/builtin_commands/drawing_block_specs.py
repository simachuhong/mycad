# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned independent drawing block command schemas."""

from mycad.commands.spec import CliSyntax, CommandSpec

_ID = {"type": "string", "minLength": 32, "maxLength": 36}
_DEFINITION = {
    "type": "object",
    "properties": {
        "definition_id": _ID,
        "name": {"type": "string", "minLength": 1},
        "entities": {"type": "array", "items": {"type": "object"}},
        "texts": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["definition_id", "name", "entities", "texts"],
    "additionalProperties": False,
}
_INSTANCE = {
    "type": "object",
    "properties": {
        "instance_id": _ID,
        "definition_id": _ID,
        "insertion_mm": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "rotation_deg": {"type": "number"},
        "scale": {"type": "number", "exclusiveMinimum": 0},
        "layer_name": {"type": "string", "minLength": 1},
    },
    "required": [
        "instance_id",
        "definition_id",
        "insertion_mm",
        "rotation_deg",
        "scale",
        "layer_name",
    ],
    "additionalProperties": False,
}
_EXPLODE = {
    "type": "object",
    "properties": {
        "instance_id": _ID,
        "source_digest": {"type": "string", "minLength": 64, "maxLength": 64},
        "sketch_id": {"oneOf": [_ID, {"const": None}]},
        "geometry_ids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_id": _ID,
                    "point_ids": {"type": "array", "items": _ID},
                },
                "required": ["entity_id", "point_ids"],
                "additionalProperties": False,
            },
        },
        "text_ids": {"type": "array", "items": _ID},
    },
    "required": ["instance_id", "source_digest", "sketch_id", "geometry_ids", "text_ids"],
    "additionalProperties": False,
}


def _remove(identity: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {identity: _ID},
        "required": [identity],
        "additionalProperties": False,
    }


DRAWING_BLOCK_SPECS = tuple(
    CommandSpec(
        id=command,
        version=1,
        summary_en=summary,
        label_zh=label,
        params_schema=schema,
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=8,
    )
    for command, summary, label, schema in (
        (
            "drawing.block_library.bind",
            "Bind block library origin",
            "绑定块库来源",
            {
                "type": "object",
                "properties": {
                    "definition_id": _ID,
                    "asset_id": _ID,
                    "content_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
                },
                "required": ["definition_id", "asset_id", "content_sha256"],
                "additionalProperties": False,
            },
        ),
        ("drawing.block.create", "Create a block definition", "创建块定义", _DEFINITION),
        ("drawing.block.update", "Update a block definition", "修改块定义", _DEFINITION),
        (
            "drawing.block.remove",
            "Remove a block definition",
            "删除块定义",
            _remove("definition_id"),
        ),
        ("drawing.block_instance.insert", "Insert a block instance", "插入块实例", _INSTANCE),
        ("drawing.block_instance.update", "Update a block instance", "修改块实例", _INSTANCE),
        ("drawing.block_instance.explode", "Explode a block instance", "分解块实例", _EXPLODE),
        (
            "drawing.block_instance.remove",
            "Remove a block instance",
            "删除块实例",
            _remove("instance_id"),
        ),
    )
)
