# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Schemas for independent 2D text and document font styles."""

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.drawing_text import TEXT_ALIGNMENTS

_ID = {"type": "string", "minLength": 32, "maxLength": 36}
_POSITIVE = {"type": "number", "exclusiveMinimum": 0}
_STYLE_PROPERTIES: dict[str, object] = {
    "style_id": {"type": "string", "minLength": 1},
    "name": {"type": "string", "minLength": 1},
    "font_family": {"type": "string"},
    "font_style": {"type": "string"},
    "font_file": {"type": "string"},
    "height_mm": _POSITIVE,
    "width_factor": _POSITIVE,
}
STYLE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": _STYLE_PROPERTIES,
    "required": ["style_id", "name"],
    "additionalProperties": False,
}
TEXT_STYLES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "styles": {"type": "array", "minItems": 1, "maxItems": 500, "items": STYLE_SCHEMA},
        "current_id": {"type": "string", "minLength": 1},
    },
    "required": ["styles", "current_id"],
    "additionalProperties": False,
}
TEXT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "text_id": _ID,
        "text": {"type": "string", "minLength": 1, "maxLength": 1_000_000},
        "position_mm": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "kind": {"type": "string", "enum": ["text", "mtext"]},
        "style_id": {"type": "string", "minLength": 1},
        "height_mm": {"oneOf": [_POSITIVE, {"const": None}]},
        "width_factor": {"oneOf": [_POSITIVE, {"const": None}]},
        "rotation_deg": {"type": "number"},
        "align": {"type": "string", "enum": list(TEXT_ALIGNMENTS)},
        "box_width_mm": {"type": "number", "minimum": 0},
        "line_spacing": _POSITIVE,
        "layer_name": {"type": "string", "minLength": 1},
    },
    "required": ["text_id", "text", "position_mm"],
    "additionalProperties": False,
}
TEXT_BATCH_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "add": {"type": "array", "items": TEXT_SCHEMA},
        "update": {"type": "array", "items": TEXT_SCHEMA},
        "remove": {"type": "array", "items": _ID},
        "styles": TEXT_STYLES_SCHEMA,
    },
    "additionalProperties": False,
}
_TEXT_COMMAND_SPECS_V1 = tuple(
    CommandSpec(
        id=identity,
        version=1,
        summary_en=summary,
        label_zh=label,
        params_schema=schema,
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=4,
    )
    for identity, summary, label, schema in (
        ("drawing.text.add", "Add model-space text", "添加文字", TEXT_SCHEMA),
        ("drawing.text.update", "Edit model-space text", "编辑文字", TEXT_SCHEMA),
        (
            "drawing.text.remove",
            "Remove model-space text",
            "删除文字",
            {
                "type": "object",
                "properties": {"text_id": _ID},
                "required": ["text_id"],
                "additionalProperties": False,
            },
        ),
        (
            "drawing.text.batch",
            "Change drawing text and styles atomically",
            "批量编辑文字",
            TEXT_BATCH_SCHEMA,
        ),
        ("drawing.text_styles.set", "Set document text styles", "文字样式", TEXT_STYLES_SCHEMA),
    )
)

TEXT_COMMAND_SPECS = (
    *_TEXT_COMMAND_SPECS_V1,
    CommandSpec(
        id="drawing.text_styles.set",
        version=2,
        summary_en="Set document text styles with recorded datum box updates",
        label_zh="文字样式",
        params_schema={
            "type": "object",
            "properties": {
                "styles": {"type": "array", "minItems": 1, "maxItems": 500, "items": STYLE_SCHEMA},
                "current_id": {"type": "string", "minLength": 1},
                "datum_updates": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["styles", "current_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=4,
    ),
)
