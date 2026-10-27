# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in command specs: the Phase-0 catalog plus released P2 commands.

Every spec's ``params_schema`` references the shared A.0 definitions
exclusively via ``$ref`` — the table itself lives in
``mycad.builtin_commands.defs.COMMAND_SCHEMA_DEFS`` and is injected at the
composition root via ``CommandRegistry(schema_defs=...)``.

Conventions (A.2): every root object carries ``additionalProperties:
false``; ``properties`` declaration order IS the canonical ``to_cli`` key
order (the rule itself is owned by T3 — this module only declares the
order); ``feature.hole`` is a bare root-level ``$ref`` to the Hole
definition (#round11-3); inline boolean commands deliberately accept no
``mode`` key (feature-command subtraction goes through ``mode=cut``).
"""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from mycad.commands.spec import CliSyntax, CommandSpec

__all__ = ["BUILTIN_COMMAND_SPECS"]

#: The Appendix A.1 commands followed by explicitly released P2 commands.
_BASE_BUILTIN_COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        id="feature.box",
        version=1,
        summary_en="Create a rectangular box",
        label_zh="长方体",
        params_schema={
            "type": "object",
            "properties": {
                "size_x": {"$ref": "#/$defs/Positive"},
                "size_y": {"$ref": "#/$defs/Positive"},
                "size_z": {"$ref": "#/$defs/Positive"},
                "center": {"$ref": "#/$defs/Center3"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["size_x", "size_y", "size_z"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("box",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.cylinder",
        version=1,
        summary_en="Create a cylinder",
        label_zh="圆柱体",
        params_schema={
            "type": "object",
            "properties": {
                "radius": {"$ref": "#/$defs/Positive"},
                "height": {"$ref": "#/$defs/Positive"},
                "center": {"$ref": "#/$defs/Center3"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["radius", "height"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("cylinder",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.extrude",
        version=1,
        summary_en="Extrude a parametric profile or a selected planar face",
        label_zh="拉伸",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/ExtrudeProfile"},
                "distance": {"type": "number"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["profile", "distance"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("extrude",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.extrude",
        version=2,
        summary_en="Extrude a parametric profile, sketch, or selected planar face",
        label_zh="拉伸",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/SketchExtrudeProfile"},
                "distance": {"type": "number"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["profile", "distance"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("extrude",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.extrude",
        version=3,
        summary_en="Extrude a profile with one-sided or symmetric extent",
        label_zh="拉伸",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/SketchExtrudeProfile"},
                "distance": {"type": "number"},
                "mode": {"$ref": "#/$defs/Mode"},
                "extent_mode": {
                    "type": "string",
                    "enum": ["one_sided", "symmetric"],
                    "default": "one_sided",
                    "description": (
                        "symmetric uses distance as total depth, split equally across the sketch plane"
                    ),
                },
            },
            "required": ["profile", "distance"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("extrude",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.revolve",
        version=1,
        summary_en="Revolve a parametric profile",
        label_zh="旋转",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/Profile"},
                "axis": {
                    "oneOf": [
                        {"const": "X"},
                        {"const": "Y"},
                        {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    ]
                },
                "angle_deg": {
                    "type": "number",
                    "exclusiveMinimum": 0.0,
                    "maximum": 360.0,
                    "default": 360.0,
                },
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["profile", "axis"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("revolve",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.revolve",
        version=2,
        summary_en="Revolve a parametric profile or sketch",
        label_zh="旋转",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/SketchRevolveProfile"},
                "axis": {
                    "oneOf": [
                        {"const": "X"},
                        {"const": "Y"},
                        {"const": "Z"},
                        {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    ]
                },
                "angle_deg": {
                    "type": "number",
                    "exclusiveMinimum": 0.0,
                    "maximum": 360.0,
                    "default": 360.0,
                },
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["profile", "axis"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("revolve",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.revolve",
        version=3,
        summary_en="Revolve a profile or sketch around a referenced construction line",
        label_zh="旋转",
        params_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "profile": {"$ref": "#/$defs/SketchRevolveProfile"},
                        "axis": {
                            "oneOf": [
                                {"const": "X"},
                                {"const": "Y"},
                                {"const": "Z"},
                                {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 3,
                                    "maxItems": 3,
                                },
                            ]
                        },
                        "angle_deg": {
                            "type": "number",
                            "exclusiveMinimum": 0.0,
                            "maximum": 360.0,
                            "default": 360.0,
                        },
                        "mode": {"$ref": "#/$defs/Mode"},
                    },
                    "required": ["profile", "axis"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "profile": {"$ref": "#/$defs/SketchProfileReference"},
                        "axis_reference": {
                            "type": "object",
                            "properties": {
                                "type": {"const": "sketch_line"},
                                "sketch_id": {
                                    "type": "string",
                                    "minLength": 32,
                                    "maxLength": 36,
                                },
                                "entity_id": {
                                    "type": "string",
                                    "minLength": 32,
                                    "maxLength": 36,
                                },
                            },
                            "required": ["type", "sketch_id", "entity_id"],
                            "additionalProperties": False,
                        },
                        "angle_deg": {
                            "type": "number",
                            "exclusiveMinimum": 0.0,
                            "maximum": 360.0,
                            "default": 360.0,
                        },
                        "mode": {"$ref": "#/$defs/Mode"},
                    },
                    "required": ["profile", "axis_reference"],
                    "additionalProperties": False,
                },
            ],
        },
        cli=CliSyntax(verb_aliases=("revolve",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.hole",
        version=1,
        summary_en="Drill a predicate-located hole",
        label_zh="孔",
        # #round11-3: root-level $ref — key order comes from the Hole def.
        params_schema={"$ref": "#/$defs/Hole"},
        cli=CliSyntax(verb_aliases=("hole",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.hole",
        version=2,
        summary_en="Drill a face hole or holes from a sketch",
        label_zh="孔",
        params_schema={
            "oneOf": [
                {"$ref": "#/$defs/Hole"},
                {"$ref": "#/$defs/SketchHole"},
            ]
        },
        cli=CliSyntax(verb_aliases=("hole",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="feature.hole_pattern",
        version=1,
        summary_en="Pattern a predicate-located hole",
        label_zh="孔阵列",
        params_schema={
            "type": "object",
            "properties": {
                "base_hole": {"$ref": "#/$defs/Hole"},
                "pattern": {"$ref": "#/$defs/Pattern"},
            },
            "required": ["base_hole", "pattern"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("hole-pattern",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.fillet",
        version=1,
        summary_en="Fillet selected edges",
        label_zh="圆角",
        params_schema={
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"$ref": "#/$defs/EdgeSelector"},
                            {"$ref": "#/$defs/InteractiveEdgeSelector"},
                        ]
                    },
                    "minItems": 1,
                },
                "radius": {"$ref": "#/$defs/Positive"},
            },
            "required": ["edges", "radius"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("fillet",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.boolean_cut",
        version=1,
        summary_en="Subtract an inline tool solid",
        label_zh="差集",
        params_schema={
            "type": "object",
            "properties": {"tool": {"$ref": "#/$defs/Tool"}},
            "required": ["tool"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("cut",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.boolean_intersect",
        version=1,
        summary_en="Intersect the current model with an inline tool solid",
        label_zh="交集",
        params_schema={
            "type": "object",
            "properties": {"tool": {"$ref": "#/$defs/Tool"}},
            "required": ["tool"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("intersect",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.boolean_bodies",
        version=1,
        summary_en="Apply a Boolean operation to two selected solid bodies",
        label_zh="实体布尔",
        params_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["union", "difference", "intersection"],
                },
                "target_body": {"$ref": "#/$defs/BodySelector"},
                "tool_body": {"$ref": "#/$defs/BodySelector"},
                "keep_tool": {"type": "boolean", "default": False},
            },
            "required": ["operation", "target_body", "tool_body"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("body-boolean",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.body_transform",
        version=1,
        summary_en="Move, rotate, mirror, or copy a selected solid body",
        label_zh="实体变换",
        params_schema={
            "type": "object",
            "properties": {
                "body": {"$ref": "#/$defs/BodySelector"},
                "transform": {"$ref": "#/$defs/BodyTransform"},
            },
            "required": ["body", "transform"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("body-transform",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.body_pattern",
        version=1,
        summary_en="Create a linear or circular pattern of a selected solid body",
        label_zh="实体阵列",
        params_schema={
            "type": "object",
            "properties": {
                "seed_body": {"$ref": "#/$defs/BodySelector"},
                "pattern": {"$ref": "#/$defs/BodyPattern"},
            },
            "required": ["seed_body", "pattern"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("body-pattern",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="modify.chamfer",
        version=1,
        summary_en="Chamfer selected edges with equal setbacks",
        label_zh="倒角",
        params_schema={
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"$ref": "#/$defs/EdgeSelector"},
                            {"$ref": "#/$defs/InteractiveEdgeSelector"},
                        ]
                    },
                    "minItems": 1,
                },
                "distance": {"$ref": "#/$defs/Positive"},
            },
            "required": ["edges", "distance"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("chamfer",)),
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.create",
        version=1,
        summary_en="Create a persistent 2D sketch",
        label_zh="创建草图",
        params_schema={
            "type": "object",
            "properties": {
                "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "frame": {
                    "type": "object",
                    "properties": {
                        "origin_mm": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "u_axis": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "v_axis": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "normal": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    },
                    "required": ["origin_mm", "u_axis", "v_axis", "normal"],
                    "additionalProperties": False,
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {"const": "line"},
                                    "construction": {"type": "boolean"},
                                    "start_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                    "end_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "required": [
                                    "entity_id",
                                    "kind",
                                    "construction",
                                    "start_mm",
                                    "end_mm",
                                ],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {"const": "polyline"},
                                    "construction": {"type": "boolean"},
                                    "points_mm": {
                                        "type": "array",
                                        "items": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 2,
                                            "maxItems": 2,
                                        },
                                        "minItems": 2,
                                    },
                                    "closed": {"type": "boolean"},
                                },
                                "required": [
                                    "entity_id",
                                    "kind",
                                    "construction",
                                    "points_mm",
                                    "closed",
                                ],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {"const": "circle"},
                                    "construction": {"type": "boolean"},
                                    "center_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                    "radius_mm": {"type": "number", "exclusiveMinimum": 0.0},
                                },
                                "required": [
                                    "entity_id",
                                    "kind",
                                    "construction",
                                    "center_mm",
                                    "radius_mm",
                                ],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {"const": "arc"},
                                    "construction": {"type": "boolean"},
                                    "center_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                    "radius_mm": {"type": "number", "exclusiveMinimum": 0.0},
                                    "start_angle_deg": {"type": "number"},
                                    "sweep_angle_deg": {"type": "number"},
                                },
                                "required": [
                                    "entity_id",
                                    "kind",
                                    "construction",
                                    "center_mm",
                                    "radius_mm",
                                    "start_angle_deg",
                                    "sweep_angle_deg",
                                ],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {"const": "rectangle"},
                                    "construction": {"type": "boolean"},
                                    "first_corner_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                    "opposite_corner_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "required": [
                                    "entity_id",
                                    "kind",
                                    "construction",
                                    "first_corner_mm",
                                    "opposite_corner_mm",
                                ],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
            },
            "required": ["sketch_id", "frame", "entities"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.add",
        version=1,
        summary_en="Add and solve a persistent sketch constraint",
        label_zh="添加草图约束",
        params_schema={
            "type": "object",
            "properties": {
                "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "base_state_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
                "constraint": {
                    "type": "object",
                    "properties": {
                        "constraint_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "kind": {
                            "type": "string",
                            "enum": [
                                "coincident",
                                "horizontal",
                                "vertical",
                                "parallel",
                                "perpendicular",
                                "tangent",
                                "concentric",
                                "equal",
                                "fixed",
                                "length",
                                "distance",
                                "angle",
                                "radius",
                                "diameter",
                            ],
                        },
                        "references": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "entity_id": {
                                        "type": "string",
                                        "minLength": 32,
                                        "maxLength": 36,
                                    },
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "geometry",
                                            "start",
                                            "end",
                                            "center",
                                            "vertex",
                                            "segment",
                                        ],
                                    },
                                    "index": {"type": "integer", "minimum": 0},
                                },
                                "required": ["entity_id", "kind"],
                                "additionalProperties": False,
                            },
                        },
                        "value": {"type": "number"},
                        "unit": {"type": "string", "enum": ["mm", "deg"]},
                        "driving": {"type": "boolean"},
                        "source": {"type": "string", "enum": ["user", "inferred"]},
                    },
                    "required": ["constraint_id", "kind", "references", "driving", "source"],
                    "additionalProperties": False,
                },
                "solver_id": {"const": "planegcs"},
                "solver_version": {"type": "string", "minLength": 1},
                "degrees_of_freedom": {"type": "integer"},
                "solution_entities": {"type": "array", "items": {"type": "object"}},
            },
            "required": [
                "sketch_id",
                "base_state_sha256",
                "constraint",
                "solver_id",
                "solver_version",
                "degrees_of_freedom",
                "solution_entities",
            ],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
)


def _sketch_create_v2_schema() -> dict[str, object]:
    """Extend the released sketch schema without changing v1 replay rules."""
    legacy = next(
        spec
        for spec in _BASE_BUILTIN_COMMAND_SPECS
        if spec.id == "sketch.create" and spec.version == 1
    )
    schema = deepcopy(dict(legacy.params_schema))
    properties = cast("dict[str, object]", schema["properties"])
    properties["layers"] = {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 255},
                "color_rgb": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 255},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "linetype": {
                    "type": "string",
                    "enum": ["CONTINUOUS", "DASHED", "DOTTED", "DASHDOT"],
                },
                "lineweight_mm": {
                    "type": "number",
                    "enum": [
                        0.0,
                        0.05,
                        0.09,
                        0.13,
                        0.15,
                        0.18,
                        0.2,
                        0.25,
                        0.3,
                        0.35,
                        0.4,
                        0.5,
                        0.53,
                        0.6,
                        0.7,
                        0.8,
                        0.9,
                        1.0,
                        1.06,
                        1.2,
                        1.4,
                        1.58,
                        2.0,
                        2.11,
                    ],
                },
                "visible": {"type": "boolean"},
                "locked": {"type": "boolean"},
                "frozen": {"type": "boolean"},
            },
            "required": [
                "name",
                "color_rgb",
                "linetype",
                "lineweight_mm",
                "visible",
                "locked",
            ],
            "additionalProperties": False,
        },
    }
    properties["support_face"] = {
        "type": "object",
        "properties": {
            "surface": {"const": "plane"},
            "axis": {"enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
            "center_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "rank": {"type": "integer", "minimum": 0},
        },
        "required": ["surface", "center_mm"],
        "additionalProperties": False,
    }
    entity_array = cast("dict[str, object]", properties["entities"])
    entity_items = cast("dict[str, object]", entity_array["items"])
    variants = cast("list[object]", entity_items["oneOf"])
    for raw_variant in variants:
        variant = cast("dict[str, object]", raw_variant)
        entity_properties = cast("dict[str, object]", variant["properties"])
        entity_properties["layer_name"] = {"type": "string", "minLength": 1, "maxLength": 255}
        required = cast("list[str]", variant["required"])
        required.append("layer_name")
    required_root = cast("list[str]", schema["required"])
    required_root.append("layers")
    return schema


def _dimension_presentation_properties() -> dict[str, object]:
    point = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
    return {
        "layer_name": {"type": "string", "minLength": 1, "maxLength": 255},
        "anchor_mode": {"enum": ["auto", "start", "end", "symmetric"]},
        "position_mm": point,
        "text_position_mm": deepcopy(point),
        "axis": {"enum": ["aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y"]},
    }


def _sketch_create_v3_schema() -> dict[str, object]:
    """Accept v2 sketches with validated dimensions and inferred drawing relations."""
    schema = _sketch_create_v2_schema()
    properties = cast("dict[str, object]", schema["properties"])
    entity_array = cast("dict[str, object]", properties["entities"])
    entity_items = cast("dict[str, object]", entity_array["items"])
    variants = cast("list[object]", entity_items["oneOf"])
    variants.append(
        {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "kind": {"const": "spline"},
                "construction": {"type": "boolean"},
                "layer_name": {"type": "string", "minLength": 1, "maxLength": 255},
                "control_points_mm": {
                    "type": "array",
                    "minItems": 4,
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
            },
            "required": ["entity_id", "kind", "construction", "layer_name", "control_points_mm"],
            "additionalProperties": False,
        }
    )
    properties["constraints"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "constraint_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "kind": {
                    "type": "string",
                    "enum": [
                        "coincident",
                        "horizontal",
                        "vertical",
                        "length",
                        "distance",
                        "angle",
                        "radius",
                        "diameter",
                        "arc_length",
                    ],
                },
                "references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            "kind": {
                                "type": "string",
                                "enum": ["geometry", "start", "end", "center", "vertex", "segment"],
                            },
                            "index": {"type": "integer", "minimum": 0},
                        },
                        "required": ["entity_id", "kind"],
                        "additionalProperties": False,
                    },
                },
                "value": {"type": "number"},
                "unit": {"type": "string", "enum": ["mm", "deg"]},
                "driving": {"type": "boolean"},
                "source": {"type": "string", "enum": ["user", "inferred"]},
                "precision": {"type": "integer", "minimum": 0, "maximum": 8},
                "scale": {"type": "number", "minimum": 0.1, "maximum": 100.0},
                **_dimension_presentation_properties(),
            },
            "required": ["constraint_id", "kind", "references", "driving", "source"],
            "additionalProperties": False,
        },
    }
    return schema


def _sketch_constraint_add_v2_schema() -> dict[str, object]:
    """Add dimension formatting while preserving released constraint @1."""
    legacy = next(
        spec
        for spec in _BASE_BUILTIN_COMMAND_SPECS
        if spec.id == "sketch.constraint.add" and spec.version == 1
    )
    schema = deepcopy(dict(legacy.params_schema))
    properties = cast("dict[str, object]", schema["properties"])
    constraint = cast("dict[str, object]", properties["constraint"])
    constraint_properties = cast("dict[str, object]", constraint["properties"])
    constraint_properties["precision"] = {
        "type": "integer",
        "minimum": 0,
        "maximum": 8,
    }
    constraint_properties["scale"] = {
        "type": "number",
        "minimum": 0.1,
        "maximum": 100.0,
    }
    return schema


def _sketch_constraint_add_v3_schema() -> dict[str, object]:
    """Regenerate consumers explicitly; old command versions retain their behavior."""
    schema = _sketch_constraint_add_v2_schema()
    properties = cast("dict[str, object]", schema["properties"])
    constraint = cast("dict[str, object]", properties["constraint"])
    cp = cast("dict[str, object]", constraint["properties"])
    cp.update(_dimension_presentation_properties())
    kind = cast("dict[str, object]", cp["kind"])
    kinds = cast("list[str]", kind["enum"])
    if "arc_length" not in kinds:
        kinds.append("arc_length")
    properties["rebuild_consumers"] = {"type": "boolean", "const": True, "default": True}
    return schema


def _drawing_layers_schema() -> dict[str, object]:
    sketch = _sketch_create_v2_schema()
    properties = cast("dict[str, object]", sketch["properties"])
    return {
        "type": "object",
        "properties": {
            "layers": properties["layers"],
            "dimension_layer": {"type": "string", "minLength": 1, "maxLength": 255},
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sketch_id": {"type": "string"},
                        "constraint_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                        "layer_name": {"type": "string", "minLength": 1, "maxLength": 255},
                    },
                    "required": ["sketch_id", "constraint_ids", "layer_name"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["layers", "dimension_layer"],
        "additionalProperties": False,
    }


BUILTIN_COMMAND_SPECS = (
    *_BASE_BUILTIN_COMMAND_SPECS,
    CommandSpec(
        id="feature.extrude",
        version=4,
        summary_en="Extrude profiles with one-sided, symmetric, or sketch to-face extent",
        label_zh="拉伸",
        params_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "profile": {"$ref": "#/$defs/SketchExtrudeProfile"},
                        "distance": {"type": "number"},
                        "mode": {"$ref": "#/$defs/Mode"},
                        "extent_mode": {
                            "type": "string",
                            "enum": ["one_sided", "symmetric"],
                            "default": "one_sided",
                        },
                    },
                    "required": ["profile", "distance"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "profile": {"$ref": "#/$defs/SketchProfileReference"},
                        "mode": {"$ref": "#/$defs/Mode"},
                        "extent_mode": {"const": "to_face"},
                        "target_face": {"$ref": "#/$defs/PlanarFaceSelector"},
                    },
                    "required": ["profile", "extent_mode", "target_face"],
                    "additionalProperties": False,
                },
            ]
        },
        cli=CliSyntax(verb_aliases=("extrude",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.create",
        version=2,
        summary_en="Create a layered persistent 2D sketch",
        label_zh="创建草图",
        params_schema=_sketch_create_v2_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.create",
        version=3,
        summary_en="Create a sketch with dimensions and inferred axis relations",
        label_zh="创建含约束草图",
        params_schema=_sketch_create_v3_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.add",
        version=2,
        summary_en="Add and solve a formatted sketch dimension or constraint",
        label_zh="添加草图约束",
        params_schema=_sketch_constraint_add_v2_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.add",
        version=3,
        summary_en="Constrain a sketch and regenerate existing solid features",
        label_zh="添加草图约束并重建",
        params_schema=_sketch_constraint_add_v3_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.update",
        version=1,
        summary_en="Revise an existing sketch dimension and regenerate its consumers",
        label_zh="修改草图尺寸",
        params_schema=_sketch_constraint_add_v3_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.layers.set",
        version=1,
        summary_en="Set shared drawing layers and dimension defaults",
        label_zh="更新图纸图层",
        params_schema=_drawing_layers_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=2,
        undo_compensation="history_replay",
    ),
)
