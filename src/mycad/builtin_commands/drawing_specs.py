# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Released engineering drawing commands, all persisted in v3 part histories."""

from collections.abc import Mapping

from mycad.commands.spec import CliSyntax, CommandSpec


def _point(count: int) -> dict[str, object]:
    return {"type": "array", "items": {"type": "number"}, "minItems": count, "maxItems": count}


def _object(properties: Mapping[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_TEXT = {"type": "string"}
_BOOL = {"type": "boolean"}
_POSITIVE = {"type": "number", "exclusiveMinimum": 0}
_NULLABLE_TEXT = {"oneOf": [{"type": "string"}, {"const": None}]}
_REFERENCE = _object(
    {
        "kind": {"enum": ["cylindrical_face", "planar_face", "edge"]},
        "parameters": {"type": "object"},
        "owner_command": _NULLABLE_TEXT,
        "role": {"enum": ["geometry", "start", "end", "center"]},
    },
    ["kind"],
)
_SHEET = {
    "sheet_id": _TEXT,
    "name": _TEXT,
    "size_mm": _point(2),
    "margin_mm": {"type": "number", "minimum": 0},
    "projection_angle": {"enum": ["first", "third"]},
    "default_scale": _POSITIVE,
    "title": {
        "type": "array",
        "items": {"type": "array", "items": _TEXT, "minItems": 2, "maxItems": 2},
    },
}
_VIEW = {
    "view_id": _TEXT,
    "sheet_id": _TEXT,
    "source": _object({"kind": {"const": "current_part"}}, ["kind"]),
    "basis": _object(
        {"right": _point(3), "up": _point(3), "normal": _point(3)}, ["right", "up", "normal"]
    ),
    "parent_id": _NULLABLE_TEXT,
    "direction": {"enum": ["front", "back", "top", "bottom", "left", "right"]},
    "anchor_mm": _point(2),
    "offset_mm": _point(2),
    "scale": _POSITIVE,
    "inherit_scale": _BOOL,
    "aligned": _BOOL,
    "hidden_lines": _BOOL,
    "tangent_lines": _BOOL,
    "inherit_display": _BOOL,
}
_ANNOTATION = {
    "annotation_id": _TEXT,
    "view_id": _TEXT,
    "kind": {
        "enum": ["horizontal", "vertical", "aligned", "radius", "diameter", "angle", "center"]
    },
    "references": {"type": "array", "items": _REFERENCE, "minItems": 1, "maxItems": 2},
    "position_mm": _point(2),
    "precision": {"type": "integer", "minimum": 0, "maximum": 8},
    "layer": _TEXT,
    "prefix": _TEXT,
    "suffix": _TEXT,
}


_VIEW_V2 = {
    **_VIEW,
    "source": {
        "oneOf": [
            _VIEW["source"],
            _object({"kind": {"const": "sketch"}, "sketch_id": _TEXT}, ["kind", "sketch_id"]),
        ]
    },
}
_REFERENCE_V2 = {
    "oneOf": [
        _REFERENCE,
        _object(
            {
                "kind": {"const": "sketch_entity"},
                "parameters": {"type": "object"},
                "role": {"enum": ["geometry", "start", "end", "center"]},
                "sketch_id": _TEXT,
                "entity_id": _TEXT,
            },
            ["kind", "sketch_id", "entity_id"],
        ),
    ]
}
_ANNOTATION_V2 = {
    **_ANNOTATION,
    "references": {
        "type": "array",
        "items": _REFERENCE_V2,
        "minItems": 1,
        "maxItems": 2,
    },
}


def _spec(kind: str, action: str, version: int = 1) -> CommandSpec:
    fields = {
        "sheet": _SHEET,
        "view": _VIEW if version == 1 else _VIEW_V2,
        "annotation": _ANNOTATION if version == 1 else _ANNOTATION_V2,
    }[kind]
    identity = f"{kind}_id"
    required = [identity]
    if action == "create":
        if kind == "view":
            required.append("sheet_id")
        elif kind == "annotation":
            required.extend(["view_id", "kind", "references", "position_mm"])
    schema = _object({identity: _TEXT} if action == "delete" else fields, required)
    if kind == "view" and action != "delete":
        schema = {
            "oneOf": [
                schema,
                _object(
                    {"views": {"type": "array", "items": schema, "minItems": 1, "maxItems": 6}},
                    ["views"],
                ),
            ]
        }
    label = {"sheet": "图纸", "view": "工程视图", "annotation": "工程标注"}[kind]
    verb = {"create": "创建", "update": "修改", "delete": "删除"}[action]
    return CommandSpec(
        id=f"drawing.{kind}.{action}",
        version=version,
        summary_en=f"{action.title()} drawing {kind}",
        label_zh=f"{verb}{label}",
        params_schema=schema,
        cli=CliSyntax(verb_aliases=(f"drawing.{kind}.{action}",)),
        min_archive_version=3,
    )


DRAWING_COMMAND_SPECS = tuple(
    _spec(kind, action)
    for kind in ("sheet", "view", "annotation")
    for action in ("create", "update", "delete")
) + tuple(
    _spec(kind, action, 2) for kind in ("view", "annotation") for action in ("create", "update")
)
