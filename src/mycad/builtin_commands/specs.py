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

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from typing import cast

from mycad.builtin_commands.bound_hole_spec import BOUND_HOLE_SPEC
from mycad.builtin_commands.datum_specs import DATUM_SPECS, PLANE
from mycad.builtin_commands.drawing_specs import DRAWING_COMMAND_SPECS
from mycad.builtin_commands.reference_specs import REFERENCE_COMMAND_SPECS
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
        id="feature.sphere",
        version=1,
        summary_en="Create a sphere",
        label_zh="球体",
        params_schema={
            "type": "object",
            "properties": {
                "radius": {"$ref": "#/$defs/Positive"},
                "center": {"$ref": "#/$defs/Center3"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
            "required": ["radius"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("sphere",)),
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


def _sketch_constraint_endpoint_schema() -> dict[str, object]:
    schema = _sketch_constraint_add_v3_schema()
    properties = cast("dict[str, object]", schema["properties"])
    constraint = cast("dict[str, object]", properties["constraint"])
    fields = cast("dict[str, object]", constraint["properties"])
    fields["first_endpoint"] = {"enum": ["start", "end"]}
    fields["second_endpoint"] = {"enum": ["start", "end"]}
    return schema


def _sketch_revise_schema() -> dict[str, object]:
    """Freeze local entities and existing relations for a single sketch revision."""
    create = _sketch_create_v3_schema()
    create_properties = cast("dict[str, object]", create["properties"])
    constraint = _sketch_constraint_add_v3_schema()
    constraint_properties = cast("dict[str, object]", constraint["properties"])
    return {
        "type": "object",
        "properties": {
            "sketch_id": deepcopy(create_properties["sketch_id"]),
            "base_state_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "entities": deepcopy(create_properties["entities"]),
            "constraints": {
                "type": "array",
                "items": deepcopy(constraint_properties["constraint"]),
            },
        },
        "required": ["sketch_id", "base_state_sha256", "entities", "constraints"],
        "additionalProperties": False,
    }


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


def _sketch_create_v4_schema() -> dict[str, object]:
    schema = _sketch_create_v3_schema()
    properties = cast("dict[str, object]", schema["properties"])
    properties.pop("frame")
    properties.pop("support_face", None)
    properties["support"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["plane", "offset_uv_mm", "rotation_deg", "flip_normal"],
        "properties": {
            "plane": PLANE,
            "offset_uv_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "rotation_deg": {"type": "number"},
            "flip_normal": {"type": "boolean"},
        },
    }
    required = cast("list[str]", schema["required"])
    required.remove("frame")
    required.append("support")
    return {"oneOf": [_sketch_create_v3_schema(), schema]}


def _with_point_entities(schema: dict[str, object]) -> dict[str, object]:
    properties = cast("dict[str, object]", schema["properties"])
    entity_array = cast("dict[str, object]", properties["entities"])
    items = cast("dict[str, object]", entity_array["items"])
    variants = cast("list[object]", items["oneOf"])
    variants.append(
        {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "kind": {"const": "point"},
                "construction": {"type": "boolean"},
                "layer_name": {"type": "string", "minLength": 1, "maxLength": 255},
                "position_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["entity_id", "kind", "construction", "layer_name", "position_mm"],
            "additionalProperties": False,
        }
    )
    return schema


def _sketch_create_v5_schema() -> dict[str, object]:
    variants = cast("list[dict[str, object]]", _sketch_create_v4_schema()["oneOf"])
    return {"oneOf": [_with_point_entities(variant) for variant in variants]}


def _sketch_create_v6_schema() -> dict[str, object]:
    """Allow inferred tangencies without changing previously released schemas."""
    schema = _sketch_create_v5_schema()
    variants = cast("list[dict[str, object]]", schema["oneOf"])
    for variant in variants:
        properties = cast("dict[str, object]", variant["properties"])
        constraints = cast("dict[str, object]", properties["constraints"])
        items = cast("dict[str, object]", constraints["items"])
        item_properties = cast("dict[str, object]", items["properties"])
        kind = cast("dict[str, object]", item_properties["kind"])
        cast("list[str]", kind["enum"]).append("tangent")
    return schema


def _associative_array_schema() -> dict[str, object]:
    reference: dict[str, object] = {
        "type": "object",
        "properties": {
            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
        },
        "required": ["sketch_id", "entity_id"],
        "additionalProperties": False,
    }
    point3: dict[str, object] = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }
    frame: dict[str, object] = {
        "type": "object",
        "properties": {
            name: deepcopy(point3) for name in ("origin_mm", "u_axis", "v_axis", "normal")
        },
        "required": ["origin_mm", "u_axis", "v_axis", "normal"],
        "additionalProperties": False,
    }
    member: dict[str, object] = {
        "type": "object",
        "properties": {
            "source": deepcopy(reference),
            "target": deepcopy(reference),
            "row": {"type": "integer", "minimum": 0},
            "column": {"type": "integer", "minimum": 0},
        },
        "required": ["source", "target", "row", "column"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
            "frame": frame,
            "rows": {"type": "integer", "minimum": 1, "maximum": 1000},
            "columns": {"type": "integer", "minimum": 1, "maximum": 1000},
            "row_spacing": {"type": "number"},
            "column_spacing": {"type": "number"},
            "sources": {"type": "array", "minItems": 1, "maxItems": 10000, "items": reference},
            "members": {"type": "array", "minItems": 1, "maxItems": 10000, "items": member},
        },
        "required": [
            "array_id",
            "frame",
            "rows",
            "columns",
            "row_spacing",
            "column_spacing",
            "sources",
            "members",
        ],
        "additionalProperties": False,
    }


def _oriented_associative_array_schema() -> dict[str, object]:
    schema = _associative_array_schema()
    cast("dict[str, object]", schema["properties"])["angle_deg"] = {"type": "number"}
    return schema


def _array_base_point_schema() -> dict[str, object]:
    identity = {"type": "string", "minLength": 32, "maxLength": 36}
    source = {
        "type": "object",
        "properties": {"sketch_id": deepcopy(identity), "entity_id": deepcopy(identity)},
        "required": ["sketch_id", "entity_id"],
        "additionalProperties": False,
    }
    reference = {
        "type": "object",
        "properties": {
            "entity_id": deepcopy(identity),
            "kind": {"enum": ["start", "end", "center", "vertex"]},
            "index": {"type": "integer", "minimum": 0},
        },
        "required": ["entity_id", "kind"],
        "additionalProperties": False,
    }
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "point_mm": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    }
                },
                "required": ["point_mm"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"source": source, "reference": reference},
                "required": ["source", "reference"],
                "additionalProperties": False,
            },
        ]
    }


def _based_associative_array_schema() -> dict[str, object]:
    schema = _oriented_associative_array_schema()
    cast("dict[str, object]", schema["properties"])["base_point"] = _array_base_point_schema()
    return schema


def _offset_associative_array_schema() -> dict[str, object]:
    schema = _based_associative_array_schema()
    properties = cast("dict[str, object]", schema["properties"])
    members = cast("dict[str, object]", properties["members"])
    items = cast("dict[str, object]", members["items"])
    cast("dict[str, object]", items["properties"])["offset_mm"] = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 2,
        "maxItems": 2,
    }
    return schema


def _rotated_member_array_schema() -> dict[str, object]:
    schema = _offset_associative_array_schema()
    members = cast("dict[str, object]", cast("dict[str, object]", schema["properties"])["members"])
    properties = cast(
        "dict[str, object]", cast("dict[str, object]", members["items"])["properties"]
    )
    properties["rotation_deg"] = {"type": "number"}
    properties["rotation_center_offset_mm"] = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 2,
        "maxItems": 2,
    }
    return schema


def _erased_member_array_schema() -> dict[str, object]:
    schema = _rotated_member_array_schema()
    members = cast("dict[str, object]", cast("dict[str, object]", schema["properties"])["members"])
    properties = cast(
        "dict[str, object]", cast("dict[str, object]", members["items"])["properties"]
    )
    properties["erased_index"] = {"type": "integer", "minimum": 0}
    return schema


def _anchored_erasure_array_schema() -> dict[str, object]:
    schema = _erased_member_array_schema()
    members = cast("dict[str, object]", cast("dict[str, object]", schema["properties"])["members"])
    properties = cast(
        "dict[str, object]", cast("dict[str, object]", members["items"])["properties"]
    )
    properties["erased_neighbors"] = {
        "type": "object",
        "properties": {
            name: {"type": "string", "minLength": 32, "maxLength": 36}
            for name in ("before", "after")
        },
        "additionalProperties": False,
    }
    return schema


def _array_replacement_schema() -> dict[str, object]:
    identity = {"type": "string", "minLength": 32, "maxLength": 36}
    return {
        "type": "object",
        "properties": {
            "source": {
                "type": "object",
                "properties": {
                    "sketch_id": deepcopy(identity),
                    "entity_id": deepcopy(identity),
                },
                "required": ["sketch_id", "entity_id"],
                "additionalProperties": False,
            },
            "base_offset_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "required": ["source", "base_offset_mm"],
        "additionalProperties": False,
    }


def _replacement_member_array_schema() -> dict[str, object]:
    schema = _anchored_erasure_array_schema()
    members = cast("dict[str, object]", cast("dict[str, object]", schema["properties"])["members"])
    properties = cast(
        "dict[str, object]", cast("dict[str, object]", members["items"])["properties"]
    )
    properties["replacement"] = _array_replacement_schema()
    return schema


def _cross_tangency_relation_schema() -> dict[str, object]:
    reference: dict[str, object] = {
        "type": "object",
        "properties": {
            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
        },
        "required": ["sketch_id", "entity_id"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "relation_id": {"type": "string", "minLength": 32, "maxLength": 36},
            "first": deepcopy(reference),
            "second": deepcopy(reference),
            "branch": {
                "enum": [
                    "external",
                    "first_contains_second",
                    "second_contains_first",
                    "line_left",
                    "line_right",
                ]
            },
        },
        "required": ["relation_id", "first", "second", "branch"],
        "additionalProperties": False,
    }


def _cross_tangency_segment_relation_schema() -> dict[str, object]:
    """Extend relation identities while retaining the previous schema unchanged."""
    schema = _cross_tangency_relation_schema()
    properties = cast("dict[str, object]", schema["properties"])
    for name in ("first", "second"):
        reference = cast("dict[str, object]", properties[name])
        fields = cast("dict[str, object]", reference["properties"])
        fields["segment_index"] = {"type": "integer", "minimum": 0}
    return schema


def _cross_tangency_endpoint_relation_schema() -> dict[str, object]:
    """Preserve explicit endpoint connections in new command versions only."""
    schema = _cross_tangency_segment_relation_schema()
    fields = cast("dict[str, object]", schema["properties"])
    fields["first_endpoint"] = {"enum": ["start", "end"]}
    fields["second_endpoint"] = {"enum": ["start", "end"]}
    return schema


def _sketch_create_v7_schema() -> dict[str, object]:
    """Atomically create a sketch with document-level tangent relations."""
    schema = _sketch_create_v6_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        properties["cross_tangencies"] = {
            "type": "array",
            "minItems": 1,
            "items": _cross_tangency_relation_schema(),
        }
    return schema


def _with_curved_polylines(schema: dict[str, object]) -> dict[str, object]:
    """Allow directed bulges without changing any earlier command schema."""
    properties = cast("dict[str, object]", schema["properties"])
    entities = cast("dict[str, object]", properties["entities"])
    items = cast("dict[str, object]", entities["items"])
    for variant in cast("list[dict[str, object]]", items["oneOf"]):
        fields = cast("dict[str, object]", variant["properties"])
        kind = cast("dict[str, object]", fields["kind"])
        if kind.get("const") == "polyline":
            fields["bulges"] = {"type": "array", "items": {"type": "number"}, "minItems": 1}
    return schema


def _sketch_create_v8_schema() -> dict[str, object]:
    schema = _sketch_create_v7_schema()
    variants = cast("list[dict[str, object]]", schema["oneOf"])
    return {"oneOf": [_with_curved_polylines(variant) for variant in variants]}


def _sketch_create_v9_schema() -> dict[str, object]:
    """Allow all supported local geometric relations in new sketches."""
    schema = _sketch_create_v8_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        constraints = cast("dict[str, object]", properties["constraints"])
        items = cast("dict[str, object]", constraints["items"])
        fields = cast("dict[str, object]", items["properties"])
        kind = cast("dict[str, object]", fields["kind"])
        cast("list[str]", kind["enum"]).extend(
            ("parallel", "perpendicular", "concentric", "equal", "fixed")
        )
    return schema


def _sketch_create_v10_schema() -> dict[str, object]:
    """Create a draft with indexed cross-sketch segment references."""
    schema = _sketch_create_v9_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        tangencies = cast("dict[str, object]", properties["cross_tangencies"])
        tangencies["items"] = _cross_tangency_segment_relation_schema()
    return schema


def _sketch_create_v11_schema() -> dict[str, object]:
    """Atomically create a sketch with associative rectangular arrays."""
    schema = _sketch_create_v10_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        properties["associative_arrays"] = {
            "type": "array",
            "minItems": 1,
            "items": _associative_array_schema(),
        }
    return schema


def _sketch_create_v12_schema() -> dict[str, object]:
    schema = _sketch_create_v11_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        tangencies = cast("dict[str, object]", properties["cross_tangencies"])
        tangencies["items"] = _cross_tangency_endpoint_relation_schema()
    return schema


def _with_local_endpoint_constraints(schema: dict[str, object]) -> dict[str, object]:
    properties = cast("dict[str, object]", schema["properties"])
    constraints = cast("dict[str, object]", properties["constraints"])
    items = cast("dict[str, object]", constraints["items"])
    fields = cast("dict[str, object]", items["properties"])
    fields["first_endpoint"] = {"enum": ["start", "end"]}
    fields["second_endpoint"] = {"enum": ["start", "end"]}
    return schema


def _sketch_create_v13_schema() -> dict[str, object]:
    schema = _sketch_create_v12_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        _with_local_endpoint_constraints(variant)
    return schema


def _sketch_create_v14_schema() -> dict[str, object]:
    schema = _sketch_create_v13_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _oriented_associative_array_schema()
        )
    return schema


def _sketch_create_v15_schema() -> dict[str, object]:
    schema = _sketch_create_v14_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _based_associative_array_schema()
        )
    return schema


def _sketch_create_v16_schema() -> dict[str, object]:
    schema = _sketch_create_v15_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _offset_associative_array_schema()
        )
    return schema


def _sketch_create_v17_schema() -> dict[str, object]:
    schema = _sketch_create_v16_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _rotated_member_array_schema()
        )
    return schema


def _sketch_create_v18_schema() -> dict[str, object]:
    schema = _sketch_create_v17_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _erased_member_array_schema()
        )
    return schema


def _sketch_create_v19_schema() -> dict[str, object]:
    schema = _sketch_create_v18_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _anchored_erasure_array_schema()
        )
    return schema


def _sketch_create_v20_schema() -> dict[str, object]:
    schema = _sketch_create_v19_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _replacement_member_array_schema()
        )
    return schema


def _curved_revision_schema() -> dict[str, object]:
    return _with_curved_polylines(_with_point_entities(_sketch_revise_schema()))


def _drawing_curved_revision_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "revisions": {"type": "array", "minItems": 1, "items": _curved_revision_schema()},
            "cross_tangencies": {"type": "array", "items": _cross_tangency_relation_schema()},
            "remove_tangencies": {
                "type": "array",
                "items": {"type": "string", "minLength": 32, "maxLength": 36},
            },
        },
        "required": ["revisions"],
        "additionalProperties": False,
    }


def _drawing_dimension_revision_schema() -> dict[str, object]:
    schema = _drawing_curved_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    properties.pop("cross_tangencies")
    properties.pop("remove_tangencies")
    constraint_schema = _sketch_constraint_add_v3_schema()
    constraint_properties = cast("dict[str, object]", constraint_schema["properties"])
    properties["dimension"] = {
        "type": "object",
        "properties": {
            "sketch_id": {"type": "string", "minLength": 1},
            "constraint": deepcopy(constraint_properties["constraint"]),
        },
        "required": ["sketch_id", "constraint"],
        "additionalProperties": False,
    }
    properties["solver_id"] = {"type": "string", "const": "planegcs"}
    properties["solver_version"] = {"type": "string", "minLength": 1}
    schema["required"] = ["revisions", "dimension", "solver_id", "solver_version"]
    return schema


def _drawing_segment_relation_revision_schema() -> dict[str, object]:
    schema = _drawing_curved_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    tangencies = cast("dict[str, object]", properties["cross_tangencies"])
    tangencies["items"] = _cross_tangency_segment_relation_schema()
    return schema


def _drawing_array_revision_schema() -> dict[str, object]:
    schema = _drawing_segment_relation_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    properties["associative_arrays"] = {
        "type": "array",
        "minItems": 1,
        "items": _associative_array_schema(),
    }
    return schema


def _drawing_endpoint_revision_schema() -> dict[str, object]:
    schema = _drawing_array_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    tangencies = cast("dict[str, object]", properties["cross_tangencies"])
    tangencies["items"] = _cross_tangency_endpoint_relation_schema()
    return schema


def _drawing_local_endpoint_revision_schema(*, dimension: bool = False) -> dict[str, object]:
    schema = (
        _drawing_dimension_revision_schema() if dimension else _drawing_endpoint_revision_schema()
    )
    properties = cast("dict[str, object]", schema["properties"])
    revisions = cast("dict[str, object]", properties["revisions"])
    _with_local_endpoint_constraints(cast("dict[str, object]", revisions["items"]))
    return schema


def _drawing_oriented_array_revision_schema() -> dict[str, object]:
    schema = _drawing_local_endpoint_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _oriented_associative_array_schema()
    )
    return schema


def _drawing_based_array_revision_schema() -> dict[str, object]:
    schema = _drawing_oriented_array_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _based_associative_array_schema()
    )
    return schema


def _drawing_offset_array_revision_schema() -> dict[str, object]:
    schema = _drawing_based_array_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _offset_associative_array_schema()
    )
    return schema


def _drawing_rotated_member_revision_schema() -> dict[str, object]:
    schema = _drawing_offset_array_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _rotated_member_array_schema()
    )
    return schema


def _drawing_erased_member_revision_schema() -> dict[str, object]:
    schema = _drawing_rotated_member_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _erased_member_array_schema()
    )
    return schema


def _drawing_anchored_erasure_revision_schema() -> dict[str, object]:
    schema = _drawing_erased_member_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _anchored_erasure_array_schema()
    )
    return schema


def _drawing_replacement_member_revision_schema() -> dict[str, object]:
    schema = _drawing_anchored_erasure_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _replacement_member_array_schema()
    )
    return schema


def _drawing_member_erasure_revision_schema() -> dict[str, object]:
    schema = _drawing_replacement_member_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    properties["erase_array_members"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 10000,
        "items": {
            "type": "object",
            "properties": {
                "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
            },
            "required": ["sketch_id", "entity_id"],
            "additionalProperties": False,
        },
    }
    return schema


def _array_replace_command_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
            "members": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10000,
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "object",
                            "properties": {
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
                            "required": ["sketch_id", "entity_id"],
                            "additionalProperties": False,
                        },
                        "replacement": _array_replacement_schema(),
                    },
                    "required": ["target", "replacement"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["array_id", "members"],
        "additionalProperties": False,
    }


def _shared_anchor_replacement_schema() -> dict[str, object]:
    schema = _array_replacement_schema()
    properties = cast("dict[str, object]", schema["properties"])
    properties["anchor_source"] = deepcopy(properties["source"])
    return schema


def _shared_anchor_replace_command_schema() -> dict[str, object]:
    schema = _array_replace_command_schema()
    properties = cast("dict[str, object]", schema["properties"])
    members = cast("dict[str, object]", properties["members"])
    items = cast("dict[str, object]", members["items"])
    cast("dict[str, object]", items["properties"])["replacement"] = (
        _shared_anchor_replacement_schema()
    )
    return schema


def _shared_anchor_array_schema() -> dict[str, object]:
    schema = _replacement_member_array_schema()
    members = cast("dict[str, object]", cast("dict[str, object]", schema["properties"])["members"])
    properties = cast(
        "dict[str, object]", cast("dict[str, object]", members["items"])["properties"]
    )
    properties["replacement"] = _shared_anchor_replacement_schema()
    return schema


def _cell_replace_command_schema() -> dict[str, object]:
    schema = _shared_anchor_replace_command_schema()
    properties = cast("dict[str, object]", schema["properties"])
    replacement = _shared_anchor_replacement_schema()
    ref = cast("dict[str, object]", replacement["properties"])["source"]
    properties["erase_members"] = {"type": "array", "minItems": 1, "maxItems": 10000, "items": ref}
    return schema


def _shared_anchor_sketch_create_schema() -> dict[str, object]:
    schema = _sketch_create_v20_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        properties = cast("dict[str, object]", variant["properties"])
        cast("dict[str, object]", properties["associative_arrays"])["items"] = (
            _shared_anchor_array_schema()
        )
    return schema


def _shared_anchor_revision_schema() -> dict[str, object]:
    schema = _drawing_member_erasure_revision_schema()
    properties = cast("dict[str, object]", schema["properties"])
    cast("dict[str, object]", properties["associative_arrays"])["items"] = (
        _shared_anchor_array_schema()
    )
    return schema


def _array_extra_output_schema() -> dict[str, object]:
    replacement = _shared_anchor_replacement_schema()
    props = cast("dict[str, object]", replacement["properties"])
    return {
        "type": "object",
        "properties": {
            "source": deepcopy(props["source"]),
            "target": deepcopy(props["source"]),
            "anchor_source": deepcopy(props["source"]),
            "row": {"type": "integer", "minimum": 0},
            "column": {"type": "integer", "minimum": 0},
            "base_offset_mm": deepcopy(props["base_offset_mm"]),
        },
        "required": ["source", "target", "anchor_source", "row", "column", "base_offset_mm"],
        "additionalProperties": False,
    }


def _extra_output_array_schema() -> dict[str, object]:
    schema = _shared_anchor_array_schema()
    cast("dict[str, object]", schema["properties"])["extra_outputs"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 10000,
        "items": _array_extra_output_schema(),
    }
    return schema


def _extra_output_replace_schema() -> dict[str, object]:
    schema = _cell_replace_command_schema()
    cast("dict[str, object]", schema["properties"])["extra_outputs"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 10000,
        "items": _array_extra_output_schema(),
    }
    return schema


def _extra_output_sketch_schema() -> dict[str, object]:
    schema = _shared_anchor_sketch_create_schema()
    for variant in cast("list[dict[str, object]]", schema["oneOf"]):
        cast(
            "dict[str, object]",
            cast("dict[str, object]", variant["properties"])["associative_arrays"],
        )["items"] = _extra_output_array_schema()
    return schema


def _extra_output_revision_schema() -> dict[str, object]:
    schema = _shared_anchor_revision_schema()
    cast(
        "dict[str, object]", cast("dict[str, object]", schema["properties"])["associative_arrays"]
    )["items"] = _extra_output_array_schema()
    return schema


_RELEASED_COMMAND_SPECS = (
    *_BASE_BUILTIN_COMMAND_SPECS,
    *DATUM_SPECS,
    CommandSpec(
        id="sketch.create",
        version=4,
        summary_en="Create a datum-associated sketch",
        label_zh="创建关联草图",
        params_schema=_sketch_create_v4_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=5,
        summary_en="Create a sketch with positioning points",
        label_zh="创建含点草图",
        params_schema=_sketch_create_v5_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=6,
        summary_en="Create a sketch with inferred tangency relations",
        label_zh="创建含相切关系草图",
        params_schema=_sketch_create_v6_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=7,
        summary_en="Create a sketch with cross-sketch tangencies",
        label_zh="创建含跨草图相切关系草图",
        params_schema=_sketch_create_v7_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=8,
        summary_en="Create a sketch with curved polylines",
        label_zh="创建含圆弧多段线草图",
        params_schema=_sketch_create_v8_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=9,
        summary_en="Create a sketch with local geometric relations",
        label_zh="创建含几何关系草图",
        params_schema=_sketch_create_v9_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=10,
        summary_en="Create a sketch with cross-sketch polyline segment tangencies",
        label_zh="创建含多段线段相切关系的草图",
        params_schema=_sketch_create_v10_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=11,
        summary_en="Create a sketch with associative rectangular arrays",
        label_zh="创建含关联矩形阵列的草图",
        params_schema=_sketch_create_v11_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=12,
        summary_en="Create a sketch with endpoint-connected tangencies",
        label_zh="创建含端点连接相切关系的草图",
        params_schema=_sketch_create_v12_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=13,
        summary_en="Create a sketch with local endpoint-connected tangencies",
        label_zh="创建含草图内端点相切关系的草图",
        params_schema=_sketch_create_v13_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=14,
        summary_en="Create a sketch with oriented associative arrays",
        label_zh="创建含方向阵列的草图",
        params_schema=_sketch_create_v14_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=15,
        summary_en="Create a sketch with associative array base points",
        label_zh="创建含基点阵列的草图",
        params_schema=_sketch_create_v15_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=16,
        summary_en="Create a sketch with array member offsets",
        label_zh="创建含成员偏移阵列的草图",
        params_schema=_sketch_create_v16_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=17,
        summary_en="Create a sketch with rotated array members",
        label_zh="创建含旋转成员阵列的草图",
        params_schema=_sketch_create_v17_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=18,
        summary_en="Create a sketch with erased array members",
        label_zh="创建含已擦除阵列成员的草图",
        params_schema=_sketch_create_v18_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=19,
        summary_en="Create a sketch with anchored erased members",
        label_zh="创建含邻接记录的擦除阵列成员",
        params_schema=_sketch_create_v19_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=20,
        summary_en="Create a sketch with replaced array members",
        label_zh="创建含替换成员的阵列",
        params_schema=_sketch_create_v20_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=21,
        summary_en="Create a sketch with internal array replacements",
        label_zh="创建含内部替换依赖的阵列",
        params_schema=_sketch_create_v20_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=22,
        summary_en="Create sketches with interleaved array dependencies",
        label_zh="创建含交错依赖的阵列",
        params_schema=_sketch_create_v20_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=23,
        summary_en="Create sketches with shared replacement anchors",
        label_zh="创建含共同替换锚点的阵列",
        params_schema=_shared_anchor_sketch_create_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.create",
        version=24,
        summary_en="Create sketches with extra array outputs",
        label_zh="创建含额外输出的阵列",
        params_schema=_extra_output_sketch_schema(),
        cli=CliSyntax(verb_aliases=("sketch-create",)),
        min_archive_version=6,
    ),
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
        id="sketch.constraint.add",
        version=4,
        summary_en="Constrain an associated sketch using its local state",
        label_zh="添加关联草图约束",
        params_schema=_sketch_constraint_add_v3_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.update",
        version=2,
        summary_en="Revise an associated sketch dimension using its local state",
        label_zh="修改关联草图尺寸",
        params_schema=_sketch_constraint_add_v3_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.add",
        version=5,
        summary_en="Add a local endpoint-connected tangency",
        label_zh="添加草图内端点相切关系",
        params_schema=_sketch_constraint_endpoint_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.constraint.update",
        version=3,
        summary_en="Update a local endpoint-connected tangency",
        label_zh="修改草图内端点相切关系",
        params_schema=_sketch_constraint_endpoint_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.revise",
        version=1,
        summary_en="Revise existing sketch geometry and regenerate its consumers",
        label_zh="修改草图几何",
        params_schema=_sketch_revise_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="sketch.revise",
        version=2,
        summary_en="Revise sketch geometry including positioning points",
        label_zh="修改含点草图",
        params_schema=_with_point_entities(_sketch_revise_schema()),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.revise",
        version=3,
        summary_en="Revise sketch geometry including curved polylines",
        label_zh="修改含圆弧多段线草图",
        params_schema=_curved_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
    ),
    CommandSpec(
        id="sketch.revise",
        version=4,
        summary_en="Revise a sketch with local endpoint-connected tangencies",
        label_zh="修改含端点相切关系的草图",
        params_schema=_with_local_endpoint_constraints(_curved_revision_schema()),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=1,
        summary_en="Revise multiple sketches as one atomic operation",
        label_zh="批量修改草图几何",
        params_schema={
            "type": "object",
            "properties": {
                "revisions": {
                    "type": "array",
                    "minItems": 1,
                    "items": _with_point_entities(_sketch_revise_schema()),
                }
            },
            "required": ["revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.add",
        version=1,
        summary_en="Add a cross-sketch tangent relation with frozen sketch revisions",
        label_zh="添加跨草图相切关系",
        params_schema={
            "type": "object",
            "properties": {
                "relation": {
                    "type": "object",
                    "properties": {
                        "relation_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "first": {
                            "type": "object",
                            "properties": {
                                "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                                "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            },
                            "required": ["sketch_id", "entity_id"],
                            "additionalProperties": False,
                        },
                        "second": {
                            "type": "object",
                            "properties": {
                                "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                                "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            },
                            "required": ["sketch_id", "entity_id"],
                            "additionalProperties": False,
                        },
                        "branch": {
                            "enum": [
                                "external",
                                "first_contains_second",
                                "second_contains_first",
                                "line_left",
                                "line_right",
                            ]
                        },
                    },
                    "required": ["relation_id", "first", "second", "branch"],
                    "additionalProperties": False,
                },
                "revisions": {
                    "type": "array",
                    "items": _with_point_entities(_sketch_revise_schema()),
                },
            },
            "required": ["relation", "revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.add",
        version=2,
        summary_en="Add a cross-sketch tangent relation with curved-polyline revisions",
        label_zh="添加跨草图相切关系（圆弧多段线）",
        params_schema={
            "type": "object",
            "properties": {
                "relation": _cross_tangency_relation_schema(),
                "revisions": {"type": "array", "items": _curved_revision_schema()},
            },
            "required": ["relation", "revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.add",
        version=3,
        summary_en="Add a cross-sketch tangent relation to a polyline segment",
        label_zh="添加多段线段跨草图相切关系",
        params_schema={
            "type": "object",
            "properties": {
                "relation": _cross_tangency_segment_relation_schema(),
                "revisions": {"type": "array", "items": _curved_revision_schema()},
            },
            "required": ["relation", "revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.add",
        version=4,
        summary_en="Add an endpoint-connected cross-sketch tangency",
        label_zh="添加端点连接的跨草图相切关系",
        params_schema={
            "type": "object",
            "properties": {
                "relation": _cross_tangency_endpoint_relation_schema(),
                "revisions": {"type": "array", "items": _curved_revision_schema()},
            },
            "required": ["relation", "revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.add",
        version=5,
        summary_en="Add a cross-sketch tangency with local endpoint-connected revisions",
        label_zh="添加跨草图相切及草图内端点关系",
        params_schema={
            "type": "object",
            "properties": {
                "relation": _cross_tangency_endpoint_relation_schema(),
                "revisions": {
                    "type": "array",
                    "items": _with_local_endpoint_constraints(_curved_revision_schema()),
                },
            },
            "required": ["relation", "revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=2,
        summary_en="Revise sketches and cross-sketch tangencies atomically",
        label_zh="批量修改草图及跨草图相切",
        params_schema={
            "type": "object",
            "properties": {
                "revisions": {
                    "type": "array",
                    "minItems": 1,
                    "items": _with_point_entities(_sketch_revise_schema()),
                },
                "cross_tangencies": {
                    "type": "array",
                    "items": _cross_tangency_relation_schema(),
                },
                "remove_tangencies": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 32, "maxLength": 36},
                },
            },
            "required": ["revisions"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=3,
        summary_en="Revise curved polylines and cross-sketch tangencies atomically",
        label_zh="批量修改圆弧多段线及相切关系",
        params_schema=_drawing_curved_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=4,
        summary_en="Revise a dimension and linked sketches atomically",
        label_zh="联动修改尺寸和草图",
        params_schema=_drawing_dimension_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=5,
        summary_en="Revise sketches and indexed cross-sketch tangent relations",
        label_zh="批量修改草图及多段线段相切关系",
        params_schema=_drawing_segment_relation_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=6,
        summary_en="Revise sketches and add associative arrays atomically",
        label_zh="批量修改草图并创建关联阵列",
        params_schema=_drawing_array_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=7,
        summary_en="Revise sketches with endpoint-connected tangencies",
        label_zh="批量修改草图及端点连接相切关系",
        params_schema=_drawing_endpoint_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=8,
        summary_en="Revise sketches with local endpoint-connected tangencies",
        label_zh="批量修改含草图内端点相切关系的草图",
        params_schema=_drawing_local_endpoint_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=9,
        summary_en="Revise a dimension with local endpoint-connected tangencies",
        label_zh="联动修改含端点相切关系的尺寸",
        params_schema=_drawing_local_endpoint_revision_schema(dimension=True),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=10,
        summary_en="Revise sketches with proven inferred reference rebinding",
        label_zh="批量修改草图并重绑定推断引用",
        params_schema=_drawing_local_endpoint_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=11,
        summary_en="Revise sketches with oriented associative arrays",
        label_zh="批量修改草图并创建方向阵列",
        params_schema=_drawing_oriented_array_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=12,
        summary_en="Revise sketches with associative array base points",
        label_zh="批量修改草图并创建基点阵列",
        params_schema=_drawing_based_array_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=13,
        summary_en="Revise sketches with array member offsets",
        label_zh="批量修改草图并创建成员偏移阵列",
        params_schema=_drawing_offset_array_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=14,
        summary_en="Revise sketches with rotated array members",
        label_zh="批量修改草图并创建旋转成员阵列",
        params_schema=_drawing_rotated_member_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=15,
        summary_en="Revise sketches with erased array members",
        label_zh="批量修改草图并创建含擦除成员的阵列",
        params_schema=_drawing_erased_member_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=16,
        summary_en="Revise sketches with anchored erased array members",
        label_zh="批量修改草图并创建含邻接记录的擦除成员",
        params_schema=_drawing_anchored_erasure_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=17,
        summary_en="Revise sketches with replaced array members",
        label_zh="批量修改草图并创建含替换成员的阵列",
        params_schema=_drawing_replacement_member_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=18,
        summary_en="Revise sketches with internal array replacements",
        label_zh="批量修改草图并创建内部替换依赖",
        params_schema=_drawing_replacement_member_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=19,
        summary_en="Revise sketches with interleaved array dependencies",
        label_zh="批量修改草图并创建交错依赖",
        params_schema=_drawing_replacement_member_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=20,
        summary_en="Revise sketches while erasing associative array members",
        label_zh="批量修改草图并擦除阵列成员",
        params_schema=_drawing_member_erasure_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=21,
        summary_en="Revise sketches with shared replacement anchors",
        label_zh="批量修改含共同替换锚点的阵列",
        params_schema=_shared_anchor_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=22,
        summary_en="Revise sketches with extra array outputs",
        label_zh="批量修改含额外输出的阵列",
        params_schema=_extra_output_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.sketch.revise",
        version=23,
        summary_en="Revise sketches while deleting extra array outputs",
        label_zh="批量修改草图并删除额外阵列输出",
        params_schema=_extra_output_revision_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=1,
        summary_en="Add an associative rectangular sketch array",
        label_zh="添加关联矩形阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=2,
        summary_en="Add an oriented associative rectangular sketch array",
        label_zh="添加带方向的关联矩形阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _oriented_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=3,
        summary_en="Add an associative array with a base point",
        label_zh="添加带基点的关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _based_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=4,
        summary_en="Add an associative array with member offsets",
        label_zh="添加含成员偏移的关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _offset_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=5,
        summary_en="Add an array with rotated members",
        label_zh="添加含旋转成员的关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _rotated_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=6,
        summary_en="Add an array with erased members",
        label_zh="添加含擦除成员的关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _erased_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=7,
        summary_en="Add an array with anchored erased members",
        label_zh="添加含邻接记录的擦除成员阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _anchored_erasure_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=8,
        summary_en="Add an array with replaced members",
        label_zh="添加含替换成员的关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=9,
        summary_en="Add an array with internal replacements",
        label_zh="添加含内部替换依赖的阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=10,
        summary_en="Add an array with interleaved dependencies",
        label_zh="添加含交错依赖的阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=11,
        summary_en="Add an array with shared replacement anchors",
        label_zh="添加含共同替换锚点的阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _shared_anchor_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.add",
        version=12,
        summary_en="Add an array with extra outputs",
        label_zh="添加含额外输出的阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _extra_output_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.update",
        version=1,
        summary_en="Update the spacing of an associative rectangular array",
        label_zh="修改关联矩形阵列间距",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "row_spacing": {"type": "number"},
                "column_spacing": {"type": "number"},
            },
            "required": ["array_id", "row_spacing", "column_spacing"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.update",
        version=2,
        summary_en="Update spacing and direction of an associative rectangular array",
        label_zh="修改关联矩形阵列间距和方向",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "row_spacing": {"type": "number"},
                "column_spacing": {"type": "number"},
                "angle_deg": {"type": "number"},
            },
            "required": ["array_id", "row_spacing", "column_spacing"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.update",
        version=3,
        summary_en="Update an associative array base point",
        label_zh="修改关联阵列基点",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "row_spacing": {"type": "number"},
                "column_spacing": {"type": "number"},
                "angle_deg": {"type": "number"},
                "base_point": _array_base_point_schema(),
                "reset_base_point": {"type": "boolean"},
            },
            "required": ["array_id", "row_spacing", "column_spacing"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=1,
        summary_en="Resize an associative rectangular array with stable member identities",
        label_zh="修改关联矩形阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=2,
        summary_en="Resize an oriented associative rectangular array",
        label_zh="修改带方向的关联矩形阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _oriented_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=3,
        summary_en="Resize an associative array with a base point",
        label_zh="修改带基点的关联阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _based_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=4,
        summary_en="Resize an array with member offsets",
        label_zh="调整含成员偏移的关联阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _offset_associative_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=5,
        summary_en="Resize an array with rotated members",
        label_zh="调整含旋转成员的关联阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _rotated_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=6,
        summary_en="Resize an array with erased members",
        label_zh="调整含擦除成员的关联阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _erased_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=7,
        summary_en="Resize an array with anchored erased members",
        label_zh="调整含邻接记录的擦除成员阵列",
        params_schema={
            "type": "object",
            "properties": {"array": _anchored_erasure_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=8,
        summary_en="Resize an array with replaced members",
        label_zh="调整含替换成员的关联阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=9,
        summary_en="Resize an array with internal replacements",
        label_zh="调整含内部替换依赖的阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=10,
        summary_en="Resize an array with interleaved dependencies",
        label_zh="调整含交错依赖的阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _replacement_member_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=11,
        summary_en="Resize an array with shared replacement anchors",
        label_zh="调整含共同替换锚点的阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _shared_anchor_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=12,
        summary_en="Resize an array with extra outputs",
        label_zh="调整含额外输出的阵列数量",
        params_schema={
            "type": "object",
            "properties": {"array": _extra_output_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.resize",
        version=13,
        summary_en="Resize array cells and remove their extra outputs",
        label_zh="调整阵列数量并移除额外输出",
        params_schema={
            "type": "object",
            "properties": {"array": _extra_output_array_schema()},
            "required": ["array"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.move",
        version=1,
        summary_en="Move an associative rectangular array",
        label_zh="移动关联矩形阵列",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "displacement": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["array_id", "displacement"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.move",
        version=2,
        summary_en="Move an associative array with upstream member offsets",
        label_zh="移动含上游副本的关联矩形阵列",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "displacement": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["array_id", "displacement"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.move",
        version=3,
        summary_en="Move arrays sourced from extra array outputs",
        label_zh="移动以额外阵列输出为来源的阵列",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "displacement": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["array_id", "displacement"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.offset",
        version=1,
        summary_en="Edit or reset associative array member position offsets",
        label_zh="修改或重置阵列成员位置偏移",
        params_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "members": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 10000,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "target": {
                                        "type": "object",
                                        "properties": {
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
                                        "required": ["sketch_id", "entity_id"],
                                        "additionalProperties": False,
                                    },
                                    "offset_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "required": ["target", "offset_mm"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["array_id", "members"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "reset_all": {"const": True},
                    },
                    "required": ["array_id", "reset_all"],
                    "additionalProperties": False,
                },
            ]
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.rotate",
        version=1,
        summary_en="Rotate associative array members",
        label_zh="旋转关联阵列成员",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "members": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "object",
                                "properties": {
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
                                "required": ["sketch_id", "entity_id"],
                                "additionalProperties": False,
                            },
                            "angle_deg": {"type": "number"},
                            "center_offset_mm": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                        },
                        "required": ["target", "angle_deg", "center_offset_mm"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["array_id", "members"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.erase",
        version=1,
        summary_en="Erase associative array members",
        label_zh="擦除关联阵列成员",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "targets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "properties": {
                            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        },
                        "required": ["sketch_id", "entity_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["array_id", "targets"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.erase",
        version=2,
        summary_en="Erase associative array members preserving neighbor identity",
        label_zh="擦除关联阵列成员并记录邻接顺序",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "targets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "properties": {
                            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        },
                        "required": ["sketch_id", "entity_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["array_id", "targets"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.erase",
        version=3,
        summary_en="Erase ordinary drawing entities and array members atomically",
        label_zh="批量删除草图对象及阵列成员",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "targets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10000,
                    "items": {
                        "type": "object",
                        "properties": {
                            "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                            "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        },
                        "required": ["sketch_id", "entity_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["targets"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.erase",
        version=4,
        summary_en="Erase drawing entities and extra array outputs atomically",
        label_zh="批量删除草图对象及额外阵列输出",
        params_schema={
            "type": "object",
            "properties": {
                "array_id": {"type": "string", "minLength": 32, "maxLength": 36},
                "targets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10000,
                    "items": deepcopy(
                        cast("dict[str, object]", _array_replacement_schema()["properties"])[
                            "source"
                        ]
                    ),
                },
            },
            "required": ["targets"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=1,
        summary_en="Replace associative array members with live sources",
        label_zh="替换关联阵列成员",
        params_schema=_array_replace_command_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=2,
        summary_en="Replace array members using internal dependencies",
        label_zh="替换阵列成员并支持内部依赖",
        params_schema=_array_replace_command_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=3,
        summary_en="Replace members in interleaved array networks",
        label_zh="替换交错依赖网络中的阵列成员",
        params_schema=_array_replace_command_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=4,
        summary_en="Replace array members with a shared source anchor",
        label_zh="以共同锚点替换阵列成员",
        params_schema=_shared_anchor_replace_command_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=5,
        summary_en="Replace array cells with fewer entities",
        label_zh="以较少图元替换阵列单元",
        params_schema=_cell_replace_command_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.replace",
        version=6,
        summary_en="Replace array cells with extra outputs",
        label_zh="以更多图元替换阵列单元",
        params_schema=_extra_output_replace_schema(),
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.reset",
        version=1,
        summary_en="Reset associative array member overrides",
        label_zh="重置阵列成员覆盖",
        params_schema={
            "type": "object",
            "properties": {"array_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["array_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.reset",
        version=2,
        summary_en="Restore erased array members and reset overrides",
        label_zh="恢复并重置阵列成员",
        params_schema={
            "type": "object",
            "properties": {"array_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["array_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.reset",
        version=3,
        summary_en="Reset replaced array members and overrides",
        label_zh="恢复阵列成员及全部覆盖",
        params_schema={
            "type": "object",
            "properties": {"array_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["array_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.reset",
        version=4,
        summary_en="Reset array cells with extra outputs",
        label_zh="重置含额外输出的阵列",
        params_schema={
            "type": "object",
            "properties": {"array_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["array_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.array.remove",
        version=1,
        summary_en="Remove an associative array relation while retaining geometry",
        label_zh="解除关联阵列",
        params_schema={
            "type": "object",
            "properties": {"array_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["array_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.tangency.remove",
        version=1,
        summary_en="Remove a cross-sketch tangent relation",
        label_zh="移除跨草图相切关系",
        params_schema={
            "type": "object",
            "properties": {"relation_id": {"type": "string", "minLength": 32, "maxLength": 36}},
            "required": ["relation_id"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
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
    CommandSpec(
        id="drawing.chamfer_values.set",
        version=1,
        summary_en="Set the drawing's 2D chamfer distances and angle",
        label_zh="设置图纸倒角参数",
        params_schema={
            "type": "object",
            "properties": {
                "distance_first": {"type": "number", "minimum": 0},
                "distance_second": {"type": "number", "minimum": 0},
                "angle_length": {"type": "number", "minimum": 0},
                "angle": {"type": "number", "minimum": 0, "exclusiveMaximum": 180},
            },
            "required": ["distance_first", "distance_second", "angle_length", "angle"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=3,
        undo_compensation="history_replay",
    ),
    CommandSpec(
        id="drawing.fillet_radius.set",
        version=1,
        summary_en="Set the drawing's 2D fillet radius",
        label_zh="设置图纸圆角半径",
        params_schema={
            "type": "object",
            "properties": {"radius": {"type": "number", "minimum": 0}},
            "required": ["radius"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=3,
        undo_compensation="history_replay",
    ),
    *(
        CommandSpec(
            id=f"drawing.raster.{action}",
            version=1,
            summary_en=f"{action.title()} an embedded drawing image",
            label_zh={"add": "添加图纸图片", "update": "修改图纸图片", "remove": "删除图纸图片"}[
                action
            ],
            params_schema={
                "type": "object",
                "properties": (
                    {"image_id": {"type": "string", "minLength": 32, "maxLength": 36}}
                    if action == "remove"
                    else {
                        "image_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "png_base64": {"type": "string", "minLength": 1, "maxLength": 16000000},
                        "origin_mm": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "width_mm": {"type": "number", "exclusiveMinimum": 0},
                        "height_mm": {"type": "number", "exclusiveMinimum": 0},
                        "layer_name": {"type": "string", "minLength": 1},
                    }
                ),
                "required": ["image_id"]
                if action == "remove"
                else ["image_id", "png_base64", "origin_mm", "width_mm", "height_mm", "layer_name"],
                "additionalProperties": False,
            },
            cli=CliSyntax(verb_aliases=()),
            min_archive_version=8,
            undo_compensation="history_replay",
        )
        for action in ("add", "update", "remove")
    ),
    *DRAWING_COMMAND_SPECS,
    *REFERENCE_COMMAND_SPECS,
    BOUND_HOLE_SPEC,
)


def _region_schema(value: object) -> object:
    """Copy a released schema while replacing only its sketch profile references."""
    if isinstance(value, dict):
        return {key: _region_schema(item) for key, item in cast("dict[str, object]", value).items()}
    if isinstance(value, list):
        return [_region_schema(item) for item in cast("list[object]", value)]
    if isinstance(value, str):
        return {
            "#/$defs/SketchProfileReference": "#/$defs/SketchRegionProfileReference",
            "#/$defs/SketchExtrudeProfile": "#/$defs/RegionSketchExtrudeProfile",
            "#/$defs/SketchRevolveProfile": "#/$defs/RegionSketchRevolveProfile",
        }.get(value, value)
    return value


def _region_spec(command_id: str, source_version: int, target_version: int) -> CommandSpec:
    source = next(
        spec
        for spec in _RELEASED_COMMAND_SPECS
        if spec.id == command_id and spec.version == source_version
    )
    return replace(
        source,
        version=target_version,
        summary_en=f"{source.summary_en}; optionally select a sketch region",
        params_schema=cast("dict[str, object]", _region_schema(source.params_schema)),
    )


def _extra_offset_schema(value: object) -> object:
    """Add optional position overrides only to the extra-output record schema."""
    if isinstance(value, dict):
        data = {
            key: _extra_offset_schema(item)
            for key, item in cast("dict[str, object]", value).items()
        }
        properties = data.get("properties")
        if isinstance(properties, dict):
            props = cast("dict[str, object]", properties)
            if {"source", "target", "anchor_source", "row", "column", "base_offset_mm"}.issubset(
                props
            ):
                props["offset_mm"] = deepcopy(props["base_offset_mm"])
        return data
    if isinstance(value, list):
        return [_extra_offset_schema(item) for item in cast("list[object]", value)]
    return value


def _extra_offset_spec(command_id: str, source_version: int, target_version: int) -> CommandSpec:
    source = next(
        spec
        for spec in _RELEASED_COMMAND_SPECS
        if spec.id == command_id and spec.version == source_version
    )
    return replace(
        source,
        version=target_version,
        summary_en=f"{source.summary_en}; support extra output position overrides",
        params_schema=cast("dict[str, object]", _extra_offset_schema(source.params_schema)),
    )


def _extra_rotation_schema(value: object) -> object:
    if isinstance(value, dict):
        data = {
            key: _extra_rotation_schema(item)
            for key, item in cast("dict[str, object]", value).items()
        }
        properties = data.get("properties")
        if isinstance(properties, dict):
            props = cast("dict[str, object]", properties)
            if {"source", "target", "anchor_source", "row", "column", "base_offset_mm"}.issubset(
                props
            ):
                props["rotation_deg"] = {"type": "number"}
                props["rotation_center_offset_mm"] = deepcopy(props["base_offset_mm"])
        return data
    if isinstance(value, list):
        return [_extra_rotation_schema(item) for item in cast("list[object]", value)]
    return value


def _extra_rotation_spec(command_id: str, source_version: int, target_version: int) -> CommandSpec:
    source = _extra_offset_spec(command_id, source_version, target_version)
    return replace(
        source,
        summary_en=f"{source.summary_en}; support extra output rotation overrides",
        params_schema=cast("dict[str, object]", _extra_rotation_schema(source.params_schema)),
    )


def _rectangle_transform_revision_spec() -> CommandSpec:
    source = _extra_rotation_spec("drawing.sketch.revise", 23, 28)
    schema = deepcopy(source.params_schema)
    properties = cast("dict[str, object]", schema["properties"])
    properties["rectangle_transforms"] = {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "object",
                    "properties": {
                        "sketch_id": {"type": "string", "minLength": 32, "maxLength": 36},
                        "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
                    },
                    "required": ["sketch_id", "entity_id"],
                    "additionalProperties": False,
                },
                "matrix": {
                    "type": "array",
                    "minItems": 6,
                    "maxItems": 6,
                    "items": {"type": "number"},
                },
            },
            "required": ["reference", "matrix"],
            "additionalProperties": False,
        },
    }
    return replace(
        source, summary_en="Revise rectangle tangencies with rigid transforms", params_schema=schema
    )


def _projection_axis_schema(value: object) -> object:
    """Add the optional projection vector only to dimension constraint records."""
    if isinstance(value, dict):
        data = {
            key: _projection_axis_schema(item)
            for key, item in cast("dict[str, object]", value).items()
        }
        properties = data.get("properties")
        if isinstance(properties, dict):
            props = cast("dict[str, object]", properties)
            if {"constraint_id", "kind", "references", "driving", "source"}.issubset(props):
                props["projection_axis"] = {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                }
        return data
    if isinstance(value, list):
        return [_projection_axis_schema(item) for item in cast("list[object]", value)]
    return value


def _batch_array_override_spec() -> CommandSpec:
    offset = next(spec for spec in _RELEASED_COMMAND_SPECS if spec.id == "drawing.array.offset")
    rotation = next(spec for spec in _RELEASED_COMMAND_SPECS if spec.id == "drawing.array.rotate")
    offset_options = cast("list[dict[str, object]]", offset.params_schema["oneOf"])
    branches: list[dict[str, object]] = []
    for operation, group_schema in (
        ("offset", offset_options[0]),
        ("rotate", rotation.params_schema),
    ):
        branches.append(
            {
                "type": "object",
                "properties": {
                    "operation": {"const": operation},
                    "groups": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10000,
                        "items": deepcopy(group_schema),
                    },
                },
                "required": ["operation", "groups"],
                "additionalProperties": False,
            }
        )
    return CommandSpec(
        id="drawing.array.batch_override",
        version=1,
        summary_en="Edit members across associative arrays atomically",
        label_zh="批量修改多个阵列的成员",
        params_schema={"oneOf": branches},
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    )


_BEFORE_PROJECTION_AXIS_SPECS = (
    *_RELEASED_COMMAND_SPECS,
    _batch_array_override_spec(),
    _region_spec("feature.extrude", 4, 5),
    _region_spec("feature.revolve", 3, 4),
    _extra_offset_spec("sketch.create", 24, 25),
    _extra_offset_spec("drawing.sketch.revise", 23, 24),
    _extra_offset_spec("drawing.array.add", 12, 13),
    _extra_offset_spec("drawing.array.resize", 13, 14),
    _extra_offset_spec("drawing.array.replace", 6, 7),
    _extra_offset_spec("drawing.array.offset", 1, 2),
    _extra_rotation_spec("sketch.create", 24, 26),
    _extra_rotation_spec("sketch.create", 24, 27),
    _extra_rotation_spec("drawing.sketch.revise", 23, 25),
    _extra_rotation_spec("drawing.sketch.revise", 23, 26),
    _extra_rotation_spec("drawing.sketch.revise", 23, 27),
    _rectangle_transform_revision_spec(),
    replace(
        _rectangle_transform_revision_spec(),
        version=29,
        summary_en="Revise transformed rectangle tangencies and local references",
    ),
    replace(
        _rectangle_transform_revision_spec(),
        version=30,
        summary_en="Revise locally constrained rectangle transforms in mixed drafts",
    ),
    replace(
        next(
            spec
            for spec in _RELEASED_COMMAND_SPECS
            if spec.id == "drawing.tangency.add" and spec.version == 5
        ),
        version=6,
        summary_en="Add a cross-sketch tangency using rectangle edges",
    ),
    _extra_rotation_spec("drawing.array.add", 12, 14),
    _extra_rotation_spec("drawing.array.resize", 13, 15),
    _extra_rotation_spec("drawing.array.replace", 6, 8),
    _extra_rotation_spec("drawing.array.rotate", 1, 2),
)

_PROJECTION_COMMAND_SPECS = (
    *_BEFORE_PROJECTION_AXIS_SPECS,
    *(
        replace(
            source,
            version=version,
            summary_en=f"{source.summary_en}; support explicit dimension projection axes",
            params_schema={
                "oneOf": [
                    _projection_axis_schema(source.params_schema),
                    _projection_axis_schema(
                        next(
                            spec.params_schema
                            for spec in _BEFORE_PROJECTION_AXIS_SPECS
                            if spec.id == command_id and spec.version == 9
                        )
                    ),
                ]
            }
            if command_id == "drawing.sketch.revise"
            else cast("dict[str, object]", _projection_axis_schema(source.params_schema)),
        )
        for command_id, version in (
            ("sketch.create", 28),
            ("sketch.constraint.add", 6),
            ("sketch.constraint.update", 4),
            ("sketch.revise", 5),
            ("drawing.sketch.revise", 31),
            ("drawing.tangency.add", 7),
        )
        for source in (
            max(
                (spec for spec in _BEFORE_PROJECTION_AXIS_SPECS if spec.id == command_id),
                key=lambda spec: spec.version,
            ),
        )
    ),
)

_BEFORE_POLYLINE_TRANSFORM_SPECS = (
    *_PROJECTION_COMMAND_SPECS,
    *(
        replace(
            next(
                spec
                for spec in _PROJECTION_COMMAND_SPECS
                if spec.id == command_id and spec.version == base
            ),
            version=version,
            summary_en="Revise sketches with proven unchanged user polyline references",
        )
        for command_id, base, version in (
            ("sketch.revise", 5, 6),
            ("drawing.sketch.revise", 31, 32),
        )
    ),
)

_POLYLINE_TRANSFORM_BASE = next(
    spec
    for spec in _BEFORE_POLYLINE_TRANSFORM_SPECS
    if spec.id == "drawing.sketch.revise" and spec.version == 32
)
_POLYLINE_TRANSFORM_SCHEMA = deepcopy(_POLYLINE_TRANSFORM_BASE.params_schema)
_TRANSFORM_PROPERTY = cast(
    "dict[str, object]", _rectangle_transform_revision_spec().params_schema["properties"]
)["rectangle_transforms"]
for _choice in cast("list[dict[str, object]]", _POLYLINE_TRANSFORM_SCHEMA["oneOf"]):
    _properties = cast("dict[str, object]", _choice["properties"])
    _properties["polyline_transforms"] = deepcopy(_TRANSFORM_PROPERTY)
_WITH_POLYLINE_TRANSFORM_SPECS = (
    *_BEFORE_POLYLINE_TRANSFORM_SPECS,
    replace(
        _POLYLINE_TRANSFORM_BASE,
        version=33,
        summary_en="Revise polyline tangencies with proven rigid transforms",
        params_schema=_POLYLINE_TRANSFORM_SCHEMA,
    ),
)

_LINE_TRANSFORM_BASE = _WITH_POLYLINE_TRANSFORM_SPECS[-1]
_LINE_TRANSFORM_SCHEMA = deepcopy(_LINE_TRANSFORM_BASE.params_schema)
for _choice in cast("list[dict[str, object]]", _LINE_TRANSFORM_SCHEMA["oneOf"]):
    cast("dict[str, object]", _choice["properties"])["line_transforms"] = deepcopy(
        _TRANSFORM_PROPERTY
    )


def _raster_frame_spec(action: str) -> CommandSpec:
    source = next(
        spec
        for spec in _RELEASED_COMMAND_SPECS
        if spec.id == f"drawing.raster.{action}" and spec.version == 1
    )
    schema = deepcopy(source.params_schema)
    properties = cast("dict[str, object]", schema["properties"])
    properties.update({"angle_deg": {"type": "number"}, "mirrored": {"type": "boolean"}})
    cast("list[str]", schema["required"]).extend(["angle_deg", "mirrored"])
    return replace(source, version=2, params_schema=schema)


def _raster_batch_spec() -> CommandSpec:
    image_schema = deepcopy(_raster_frame_spec("add").params_schema)
    image_ids = {
        "type": "array",
        "minItems": 1,
        "maxItems": 1000,
        "items": {"type": "string", "minLength": 32, "maxLength": 36},
    }
    images = {"type": "array", "minItems": 1, "maxItems": 1000, "items": image_schema}
    return CommandSpec(
        id="drawing.raster.batch",
        version=1,
        summary_en="Apply one atomic change to drawing images",
        label_zh="批量修改图纸图片",
        params_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"action": {"enum": ["add", "update"]}, "images": images},
                    "required": ["action", "images"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {"action": {"const": "remove"}, "image_ids": image_ids},
                    "required": ["action", "image_ids"],
                    "additionalProperties": False,
                },
            ]
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=8,
        undo_compensation="history_replay",
    )


_MIXED_RASTER_REVISION_SCHEMA = deepcopy(_LINE_TRANSFORM_SCHEMA)
for _choice in cast("list[dict[str, object]]", _MIXED_RASTER_REVISION_SCHEMA["oneOf"]):
    cast("dict[str, object]", _choice["properties"])["raster_batch"] = deepcopy(
        _raster_batch_spec().params_schema
    )
    cast("list[str]", _choice["required"]).append("raster_batch")

_MIXED_RASTER_CREATE_BASE = next(
    spec
    for spec in _WITH_POLYLINE_TRANSFORM_SPECS
    if spec.id == "sketch.create" and spec.version == 28
)
_MIXED_RASTER_CREATE_SCHEMA = deepcopy(_MIXED_RASTER_CREATE_BASE.params_schema)
_RASTER_ADD_SCHEMA = deepcopy(
    cast("list[dict[str, object]]", _raster_batch_spec().params_schema["oneOf"])[0]
)
cast("dict[str, object]", _RASTER_ADD_SCHEMA["properties"])["action"] = {"const": "add"}
for _choice in cast("list[dict[str, object]]", _MIXED_RASTER_CREATE_SCHEMA["oneOf"]):
    cast("dict[str, object]", _choice["properties"])["raster_batch"] = deepcopy(_RASTER_ADD_SCHEMA)
    cast("list[str]", _choice["required"]).append("raster_batch")


_BEFORE_DIMENSION_TEXT_SPECS = (
    *_WITH_POLYLINE_TRANSFORM_SPECS,
    *(_raster_frame_spec(action) for action in ("add", "update")),
    _raster_batch_spec(),
    replace(
        _MIXED_RASTER_CREATE_BASE,
        version=29,
        summary_en="Create a sketch and images in one replayable operation",
        params_schema=_MIXED_RASTER_CREATE_SCHEMA,
        min_archive_version=8,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=34,
        summary_en="Revise line and polyline tangencies with proven rigid transforms",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=35,
        summary_en="Revise tangencies with uniquely proven extended polyline segments",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=36,
        summary_en="Revise tangencies with uniquely proven containing polyline arcs",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=37,
        summary_en="Revise tangencies with uniquely retained polyline arc contacts",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=38,
        summary_en="Add a tangent constraint while revising linked drawing objects",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=39,
        summary_en="Retain circle identity when trimming to an arc",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=40,
        summary_en="Retain unique tangent contacts on trimmed polyline segments",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=41,
        summary_en="Rebind local tangencies to uniquely retained trimmed segments",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=42,
        summary_en="Rebind local tangencies to uniquely retained trimmed fragments",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=43,
        summary_en="Rebind drawing tangencies to uniquely retained trimmed fragments",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=44,
        summary_en="Rebind drawing tangencies to uniquely retained split lines",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=45,
        summary_en="Rebind local tangencies to uniquely retained split lines",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=46,
        summary_en="Rebind tangencies to uniquely retained split arcs",
        params_schema=_LINE_TRANSFORM_SCHEMA,
    ),
    replace(
        _LINE_TRANSFORM_BASE,
        version=47,
        summary_en="Revise drawing objects and images in one replayable operation",
        params_schema=_MIXED_RASTER_REVISION_SCHEMA,
        min_archive_version=8,
    ),
)


def _dimension_text_schema(value: object) -> object:
    """Add display text only in newly versioned constraint record schemas."""
    if isinstance(value, dict):
        data = {
            key: _dimension_text_schema(item)
            for key, item in cast("dict[str, object]", value).items()
        }
        properties = data.get("properties")
        if isinstance(properties, dict):
            props = cast("dict[str, object]", properties)
            if {"constraint_id", "kind", "references", "driving", "source"}.issubset(props):
                props["text_override"] = {"type": "string", "minLength": 1, "maxLength": 256}
        return data
    if isinstance(value, list):
        return [_dimension_text_schema(item) for item in cast("list[object]", value)]
    return value


_BEFORE_DIMENSION_STYLE_SPECS = (
    *_BEFORE_DIMENSION_TEXT_SPECS,
    CommandSpec(
        id="drawing.dimension_styles.set",
        version=1,
        summary_en="Set drawing-local dimension styles",
        label_zh="设置图纸标注样式",
        params_schema={
            "type": "object",
            "properties": {
                "styles": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 80},
                            "precision": {"type": "integer", "minimum": 0, "maximum": 8},
                            "scale": {"type": "number", "minimum": 0.1, "maximum": 100},
                        },
                        "required": ["name", "precision", "scale"],
                        "additionalProperties": False,
                    },
                },
                "current": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "required": ["styles", "current"],
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        undo_compensation="history_replay",
    ),
    *(
        replace(
            source,
            version=version,
            summary_en=f"{source.summary_en}; support dimension text overrides",
            params_schema=cast("dict[str, object]", _dimension_text_schema(source.params_schema)),
        )
        for command_id, base, version in (
            ("sketch.create", 28, 30),
            ("sketch.create", 29, 31),
            ("sketch.constraint.add", 6, 7),
            ("sketch.constraint.update", 4, 5),
            ("sketch.revise", 6, 7),
            ("drawing.sketch.revise", 46, 48),
            ("drawing.sketch.revise", 47, 49),
            ("drawing.tangency.add", 7, 8),
        )
        for source in (
            next(
                spec
                for spec in _BEFORE_DIMENSION_TEXT_SPECS
                if spec.id == command_id and spec.version == base
            ),
        )
    ),
)


def _dimension_style_reference_schema(value: object) -> object:
    """Add optional style identity to newly versioned constraint records."""
    if isinstance(value, dict):
        data = {
            key: _dimension_style_reference_schema(item)
            for key, item in cast("dict[str, object]", value).items()
        }
        properties = data.get("properties")
        if isinstance(properties, dict):
            props = cast("dict[str, object]", properties)
            if {"constraint_id", "kind", "references", "driving", "source"}.issubset(props):
                props["style_name"] = {"type": "string", "minLength": 1, "maxLength": 80}
        return data
    if isinstance(value, list):
        return [_dimension_style_reference_schema(item) for item in cast("list[object]", value)]
    return value


_BEFORE_DIMENSION_LAYER_SPECS = (
    *_BEFORE_DIMENSION_STYLE_SPECS,
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_STYLE_SPECS
            if spec.id == "drawing.dimension_styles.set"
        ),
        version=2,
        params_schema={
            "type": "object",
            "properties": {
                "styles": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 80},
                            "precision": {"type": "integer", "minimum": 0, "maximum": 8},
                            "scale": {"type": "number", "minimum": 0.1, "maximum": 100},
                            "arrow_first": {"enum": ["open", "closed", "filled", "tick", "none"]},
                            "arrow_second": {"enum": ["open", "closed", "filled", "tick", "none"]},
                            "arrow_size": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "maximum": 10000,
                            },
                            "dimline_extension": {"type": "number", "minimum": 0, "maximum": 10000},
                            "extline_extension": {"type": "number", "minimum": 0, "maximum": 10000},
                            "extline_offset": {"type": "number", "minimum": 0, "maximum": 10000},
                            "text_height": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "maximum": 10000,
                            },
                        },
                        "required": [
                            "name",
                            "precision",
                            "scale",
                            "arrow_first",
                            "arrow_second",
                            "arrow_size",
                            "dimline_extension",
                            "extline_extension",
                            "extline_offset",
                            "text_height",
                        ],
                        "additionalProperties": False,
                    },
                },
                "current": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "required": ["styles", "current"],
            "additionalProperties": False,
        },
    ),
    *(
        replace(
            source,
            version=version,
            summary_en=f"{source.summary_en}; support drawing dimension style references",
            params_schema=cast(
                "dict[str, object]", _dimension_style_reference_schema(source.params_schema)
            ),
        )
        for command_id, base, version in (
            ("sketch.create", 30, 32),
            ("sketch.create", 31, 33),
            ("sketch.constraint.add", 7, 8),
            ("sketch.constraint.update", 5, 6),
            ("sketch.revise", 7, 8),
            ("drawing.sketch.revise", 48, 50),
            ("drawing.sketch.revise", 49, 51),
            ("drawing.tangency.add", 8, 9),
        )
        for source in (
            next(
                spec
                for spec in _BEFORE_DIMENSION_STYLE_SPECS
                if spec.id == command_id and spec.version == base
            ),
        )
    ),
)

_DIMENSION_LAYER_REVISION_SCHEMA = deepcopy(
    next(
        spec.params_schema
        for spec in _BEFORE_DIMENSION_LAYER_SPECS
        if spec.id == "drawing.sketch.revise" and spec.version == 51
    )
)
for _choice in cast("list[dict[str, object]]", _DIMENSION_LAYER_REVISION_SCHEMA["oneOf"]):
    cast("list[str]", _choice["required"]).remove("raster_batch")

_DIMENSION_STYLE_V3_SCHEMA = deepcopy(
    next(
        spec.params_schema
        for spec in _BEFORE_DIMENSION_LAYER_SPECS
        if spec.id == "drawing.dimension_styles.set" and spec.version == 2
    )
)
_style_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V3_SCHEMA["properties"])["styles"],
)
_style_item = cast("dict[str, object]", _style_array["items"])
_style_properties = cast("dict[str, object]", _style_item["properties"])
_style_properties["center_mark"] = {"enum": ["none", "mark", "line"]}
_style_properties["center_size"] = {"type": "number", "exclusiveMinimum": 0, "maximum": 10000}
cast("list[str]", _style_item["required"]).extend(("center_mark", "center_size"))

_CLIPBOARD_STYLE_CREATE_SCHEMA = deepcopy(
    next(
        spec.params_schema
        for spec in _BEFORE_DIMENSION_LAYER_SPECS
        if spec.id == "sketch.create" and spec.version == 33
    )
)
for _choice in cast("list[dict[str, object]]", _CLIPBOARD_STYLE_CREATE_SCHEMA["oneOf"]):
    cast("dict[str, object]", _choice["properties"])["clipboard_styles"] = deepcopy(
        _DIMENSION_STYLE_V3_SCHEMA
    )
    cast("list[str]", _choice["required"]).append("clipboard_styles")

_IMPORT_STYLE_CREATE_SCHEMA = deepcopy(
    next(
        spec.params_schema
        for spec in _BEFORE_DIMENSION_LAYER_SPECS
        if spec.id == "sketch.create" and spec.version == 32
    )
)
for _choice in cast("list[dict[str, object]]", _IMPORT_STYLE_CREATE_SCHEMA["oneOf"]):
    cast("dict[str, object]", _choice["properties"])["clipboard_styles"] = deepcopy(
        _DIMENSION_STYLE_V3_SCHEMA
    )
    cast("list[str]", _choice["required"]).append("clipboard_styles")

_CLIPBOARD_PREPARE_SCHEMA = deepcopy(_drawing_layers_schema())
cast("dict[str, object]", _CLIPBOARD_PREPARE_SCHEMA["properties"])["clipboard_styles"] = deepcopy(
    _DIMENSION_STYLE_V3_SCHEMA
)
cast("list[str]", _CLIPBOARD_PREPARE_SCHEMA["required"]).append("clipboard_styles")

_DIMENSION_STYLE_V4_SCHEMA = deepcopy(_DIMENSION_STYLE_V3_SCHEMA)
_color_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V4_SCHEMA["properties"])["styles"],
)
_color_item = cast("dict[str, object]", _color_array["items"])
for _color_field in ("dimension_color", "extension_color", "text_color"):
    cast("dict[str, object]", _color_item["properties"])[_color_field] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 256,
    }
    cast("list[str]", _color_item["required"]).append(_color_field)


_DIMENSION_STYLE_V5_SCHEMA = deepcopy(_DIMENSION_STYLE_V4_SCHEMA)
_weight_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V5_SCHEMA["properties"])["styles"],
)
_weight_item = cast("dict[str, object]", _weight_array["items"])
for _weight_field in ("dimension_lineweight", "extension_lineweight"):
    cast("dict[str, object]", _weight_item["properties"])[_weight_field] = {
        "enum": [
            -1,
            0,
            5,
            9,
            13,
            15,
            18,
            20,
            25,
            30,
            35,
            40,
            50,
            53,
            60,
            70,
            80,
            90,
            100,
            106,
            120,
            140,
            158,
            200,
            211,
        ]
    }
    cast("list[str]", _weight_item["required"]).append(_weight_field)

_DIMENSION_STYLE_V6_SCHEMA = deepcopy(_DIMENSION_STYLE_V5_SCHEMA)
_linetype_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V6_SCHEMA["properties"])["styles"],
)
_linetype_item = cast("dict[str, object]", _linetype_array["items"])
for _linetype_field in (
    "dimension_linetype",
    "extension_linetype_first",
    "extension_linetype_second",
):
    cast("dict[str, object]", _linetype_item["properties"])[_linetype_field] = {
        "enum": ["BYLAYER", "CONTINUOUS", "DASHED", "DOTTED", "DASHDOT"]
    }
    cast("list[str]", _linetype_item["required"]).append(_linetype_field)

_DIMENSION_STYLE_V7_SCHEMA = deepcopy(_DIMENSION_STYLE_V6_SCHEMA)
_visibility_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V7_SCHEMA["properties"])["styles"],
)
_visibility_item = cast("dict[str, object]", _visibility_array["items"])
for _visibility_field in ("suppress_extension_first", "suppress_extension_second"):
    cast("dict[str, object]", _visibility_item["properties"])[_visibility_field] = {
        "type": "boolean"
    }
    cast("list[str]", _visibility_item["required"]).append(_visibility_field)

_DIMENSION_STYLE_V8_SCHEMA = deepcopy(_DIMENSION_STYLE_V7_SCHEMA)
_dimension_visibility_array = cast(
    "dict[str, object]",
    cast("dict[str, object]", _DIMENSION_STYLE_V8_SCHEMA["properties"])["styles"],
)
_dimension_visibility_item = cast("dict[str, object]", _dimension_visibility_array["items"])
for _field in ("suppress_dimension_first", "suppress_dimension_second"):
    cast("dict[str, object]", _dimension_visibility_item["properties"])[_field] = {
        "type": "boolean"
    }
    cast("list[str]", _dimension_visibility_item["required"]).append(_field)


def _with_color_styles(
    schema: Mapping[str, object],
    *,
    union: bool,
    weights: bool = False,
    linetypes: bool = False,
    visibility: bool = False,
    dimension_visibility: bool = False,
) -> dict[str, object]:
    updated = deepcopy(dict(schema))
    choices = cast("list[dict[str, object]]", updated["oneOf"]) if union else [updated]
    for choice in choices:
        cast("dict[str, object]", choice["properties"])["clipboard_styles"] = deepcopy(
            _DIMENSION_STYLE_V8_SCHEMA
            if dimension_visibility
            else _DIMENSION_STYLE_V7_SCHEMA
            if visibility
            else _DIMENSION_STYLE_V6_SCHEMA
            if linetypes
            else _DIMENSION_STYLE_V5_SCHEMA
            if weights
            else _DIMENSION_STYLE_V4_SCHEMA
        )
    return updated


BUILTIN_COMMAND_SPECS = (
    *_BEFORE_DIMENSION_LAYER_SPECS,
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=6,
        min_archive_version=8,
        summary_en="Import drawing layers and dimension styles",
        label_zh="导入剪贴板图层和标注样式",
        params_schema=_with_color_styles(
            _CLIPBOARD_PREPARE_SCHEMA, union=False, dimension_visibility=True
        ),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=44,
        summary_en="Create a mixed sketch with dimension styles",
        params_schema=_with_color_styles(
            _CLIPBOARD_STYLE_CREATE_SCHEMA, union=True, dimension_visibility=True
        ),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=45,
        min_archive_version=8,
        summary_en="Create a sketch with imported dimension styles",
        params_schema=_with_color_styles(
            _IMPORT_STYLE_CREATE_SCHEMA, union=True, dimension_visibility=True
        ),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=8,
        params_schema=_DIMENSION_STYLE_V8_SCHEMA,
    ),
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=5,
        min_archive_version=8,
        summary_en="Import drawing layers and dimension styles",
        label_zh="导入剪贴板图层和标注样式",
        params_schema=_with_color_styles(_CLIPBOARD_PREPARE_SCHEMA, union=False, visibility=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=42,
        summary_en="Create a mixed sketch with dimension styles",
        params_schema=_with_color_styles(
            _CLIPBOARD_STYLE_CREATE_SCHEMA, union=True, visibility=True
        ),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=43,
        min_archive_version=8,
        summary_en="Create a sketch with imported dimension styles",
        params_schema=_with_color_styles(_IMPORT_STYLE_CREATE_SCHEMA, union=True, visibility=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=7,
        params_schema=_DIMENSION_STYLE_V7_SCHEMA,
    ),
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=1,
        summary_en="Import drawing layers and clipboard dimension styles together",
        label_zh="导入剪贴板图层和标注样式",
        min_archive_version=8,
        params_schema=_CLIPBOARD_PREPARE_SCHEMA,
    ),
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=2,
        summary_en="Import drawing layers and color-aware dimension styles together",
        label_zh="导入剪贴板图层和标注样式",
        min_archive_version=8,
        params_schema=_with_color_styles(_CLIPBOARD_PREPARE_SCHEMA, union=False),
    ),
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=3,
        min_archive_version=8,
        summary_en="Import drawing layers and dimension styles together",
        label_zh="导入剪贴板图层和标注样式",
        params_schema=_with_color_styles(_CLIPBOARD_PREPARE_SCHEMA, union=False, weights=True),
    ),
    replace(
        next(spec for spec in _BEFORE_DIMENSION_LAYER_SPECS if spec.id == "drawing.layers.set"),
        id="drawing.clipboard.prepare",
        version=4,
        min_archive_version=8,
        summary_en="Import drawing layers and dimension styles together",
        label_zh="导入剪贴板图层和标注样式",
        params_schema=_with_color_styles(_CLIPBOARD_PREPARE_SCHEMA, union=False, linetypes=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=34,
        summary_en="Create a sketch, images and imported dimension styles atomically",
        params_schema=_CLIPBOARD_STYLE_CREATE_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=36,
        summary_en="Create a mixed sketch with color-aware styles",
        params_schema=_with_color_styles(_CLIPBOARD_STYLE_CREATE_SCHEMA, union=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=38,
        summary_en="Create a mixed sketch with dimension styles",
        params_schema=_with_color_styles(_CLIPBOARD_STYLE_CREATE_SCHEMA, union=True, weights=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 33
        ),
        version=40,
        summary_en="Create a mixed sketch with dimension styles",
        params_schema=_with_color_styles(
            _CLIPBOARD_STYLE_CREATE_SCHEMA, union=True, linetypes=True
        ),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=35,
        min_archive_version=8,
        summary_en="Create a sketch and imported dimension styles atomically",
        params_schema=_IMPORT_STYLE_CREATE_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=37,
        min_archive_version=8,
        summary_en="Create a sketch with color-aware styles",
        params_schema=_with_color_styles(_IMPORT_STYLE_CREATE_SCHEMA, union=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=39,
        min_archive_version=8,
        summary_en="Create a sketch with imported dimension styles",
        params_schema=_with_color_styles(_IMPORT_STYLE_CREATE_SCHEMA, union=True, weights=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "sketch.create" and spec.version == 32
        ),
        version=41,
        min_archive_version=8,
        summary_en="Create a sketch with imported dimension styles",
        params_schema=_with_color_styles(_IMPORT_STYLE_CREATE_SCHEMA, union=True, linetypes=True),
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=3,
        params_schema=_DIMENSION_STYLE_V3_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=4,
        params_schema=_DIMENSION_STYLE_V4_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=5,
        params_schema=_DIMENSION_STYLE_V5_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.dimension_styles.set" and spec.version == 2
        ),
        version=6,
        params_schema=_DIMENSION_STYLE_V6_SCHEMA,
    ),
    replace(
        next(
            spec
            for spec in _BEFORE_DIMENSION_LAYER_SPECS
            if spec.id == "drawing.sketch.revise" and spec.version == 51
        ),
        version=52,
        summary_en="Revise drawing objects and dimension layers in one operation",
        params_schema=_DIMENSION_LAYER_REVISION_SCHEMA,
    ),
)
