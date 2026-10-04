# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Test-local schema fixtures for the T3 command framework (sub-task A).

``DEFS`` is an INLINE, test-only transcription of plan Appendix A.0 (the
$defs shared table). The formal table (``src/mycad/builtin_commands/defs.py``
with symbol ``COMMAND_SCHEMA_DEFS``) belongs to T7 — it must NOT be imported
or duplicated as a second formal table anywhere in ``src/``.

Command specs below are minimal local fixtures transcribing Appendix A.1
(the full 8-command set plus demo.ping); ``synthetic_registry`` assembles
them into a test-only registry with ``DEFS`` injected.
"""

from __future__ import annotations

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec

# ---------------------------------------------------------------------------
# Appendix A.0 shared $defs (inline test fixture — NOT the formal T7 table)
# ---------------------------------------------------------------------------

DEFS: dict[str, object] = {
    "FaceSelector": {
        "oneOf": [
            {
                "type": "object",
                "required": ["surface", "axis"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "plane"},
                    "axis": {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
                    "rank": {"type": "integer", "minimum": 0},
                },
                "description": "plane branch: axis required, six signed values",
            },
            {
                "type": "object",
                "required": ["surface"],
                "additionalProperties": False,
                "properties": {
                    "surface": {"const": "cylinder"},
                    "axis": {
                        "type": "string",
                        "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z", ""],
                    },
                    "rank": {"type": "integer", "minimum": 0},
                },
                "description": "cylinder branch: axis optional, empty string = all",
            },
        ],
        "description": "face predicate descriptor (plane/cylinder)",
    },
    "EdgeSelector": {
        "type": "object",
        "required": ["parent_faces"],
        "additionalProperties": False,
        "properties": {
            "parent_faces": {
                "type": "array",
                "items": {"$ref": "#/$defs/FaceSelector"},
                "minItems": 1,
            },
            "curve": {"type": "string", "enum": ["line", "circle", ""]},
        },
    },
    "Position": {
        "oneOf": [
            {
                "type": "object",
                "properties": {"kind": {"const": "center"}},
                "required": ["kind"],
                "additionalProperties": False,
            }
        ],
        "description": "v1: face center only",
    },
    "Depth": {
        "oneOf": [
            {
                "type": "object",
                "properties": {"kind": {"const": "through_all"}},
                "required": ["kind"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "blind"},
                    "value": {"type": "number", "exclusiveMinimum": 0.0},
                },
                "required": ["kind", "value"],
                "additionalProperties": False,
            },
        ]
    },
    "Pattern": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "polar"},
                    "radius": {"type": "number", "exclusiveMinimum": 0.0},
                    "count": {"type": "integer", "minimum": 2, "maximum": 64},
                    "start_angle_deg": {"type": "number", "default": 0.0},
                },
                "required": ["kind", "radius", "count"],
                "additionalProperties": False,
            }
        ]
    },
    "Profile": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "type": {"const": "circle"},
                    "radius": {"type": "number", "exclusiveMinimum": 0.0},
                    "center": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                        "default": [0.0, 0.0],
                    },
                },
                "required": ["type", "radius"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"const": "rect"},
                    "width": {"type": "number", "exclusiveMinimum": 0.0},
                    "height": {"type": "number", "exclusiveMinimum": 0.0},
                    "center": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                        "default": [0.0, 0.0],
                    },
                },
                "required": ["type", "width", "height"],
                "additionalProperties": False,
            },
        ],
        "description": "profile on the XY work plane z=0",
    },
    "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
    "Center3": {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    },
    "Positive": {"type": "number", "exclusiveMinimum": 0.0},
    "Tool": {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "type": {"const": "box"},
                    "size_x": {"$ref": "#/$defs/Positive"},
                    "size_y": {"$ref": "#/$defs/Positive"},
                    "size_z": {"$ref": "#/$defs/Positive"},
                    "center": {"$ref": "#/$defs/Center3"},
                },
                "required": ["type", "size_x", "size_y", "size_z"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"const": "cylinder"},
                    "radius": {"$ref": "#/$defs/Positive"},
                    "height": {"$ref": "#/$defs/Positive"},
                    "center": {"$ref": "#/$defs/Center3"},
                },
                "required": ["type", "radius", "height"],
                "additionalProperties": False,
            },
        ]
    },
    "Hole": {
        "type": "object",
        "required": ["target_face", "position", "diameter", "depth"],
        "additionalProperties": False,
        "properties": {
            "target_face": {"$ref": "#/$defs/FaceSelector"},
            "position": {"$ref": "#/$defs/Position"},
            "diameter": {"$ref": "#/$defs/Positive"},
            "depth": {"$ref": "#/$defs/Depth"},
        },
        "description": "shared definition of every hole parameter",
    },
}

# ---------------------------------------------------------------------------
# Minimal local command specs (subset of Appendix A.1 for validation tests)
# ---------------------------------------------------------------------------


def cylinder_spec() -> CommandSpec:
    """feature.cylinder per Appendix A.1 (demo command, T3-A test fixture)."""
    return CommandSpec(
        id="feature.cylinder",
        version=1,
        summary_en="Create a cylinder",
        label_zh="圆柱体",
        params_schema={
            "type": "object",
            "required": ["radius", "height"],
            "additionalProperties": False,
            "properties": {
                "radius": {"$ref": "#/$defs/Positive"},
                "height": {"$ref": "#/$defs/Positive"},
                "center": {"$ref": "#/$defs/Center3"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
        },
        cli=CliSyntax(verb_aliases=("cylinder",)),
    )


def hole_spec() -> CommandSpec:
    """feature.hole: root-level $ref form (params_schema IS the ref)."""
    return CommandSpec(
        id="feature.hole",
        version=1,
        summary_en="Drill a predicate-located hole",
        label_zh="孔",
        params_schema={"$ref": "#/$defs/Hole"},
        cli=CliSyntax(verb_aliases=("hole",)),
    )


def hole_pattern_spec() -> CommandSpec:
    """feature.hole_pattern: base_hole reuses Hole via $ref."""
    return CommandSpec(
        id="feature.hole_pattern",
        version=1,
        summary_en="Pattern a predicate-located hole",
        label_zh="孔阵列",
        params_schema={
            "type": "object",
            "required": ["base_hole", "pattern"],
            "additionalProperties": False,
            "properties": {
                "base_hole": {"$ref": "#/$defs/Hole"},
                "pattern": {"$ref": "#/$defs/Pattern"},
            },
        },
        cli=CliSyntax(verb_aliases=("hole-pattern",)),
    )


def fillet_spec() -> CommandSpec:
    """modify.fillet: EdgeSelector array exercises items + deep nesting."""
    return CommandSpec(
        id="modify.fillet",
        version=1,
        summary_en="Fillet selected edges",
        label_zh="圆角",
        params_schema={
            "type": "object",
            "required": ["edges", "radius"],
            "additionalProperties": False,
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/EdgeSelector"},
                    "minItems": 1,
                },
                "radius": {"$ref": "#/$defs/Positive"},
            },
        },
        cli=CliSyntax(verb_aliases=("fillet",)),
    )


def extrude_spec() -> CommandSpec:
    """feature.extrude: Profile oneOf with nested defaults."""
    return CommandSpec(
        id="feature.extrude",
        version=1,
        summary_en="Extrude a parametric profile",
        label_zh="拉伸",
        params_schema={
            "type": "object",
            "required": ["profile", "distance"],
            "additionalProperties": False,
            "properties": {
                "profile": {"$ref": "#/$defs/Profile"},
                "distance": {"type": "number"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
        },
        cli=CliSyntax(verb_aliases=("extrude",)),
    )


def box_spec() -> CommandSpec:
    """feature.box per Appendix A.1."""
    return CommandSpec(
        id="feature.box",
        version=1,
        summary_en="Create a rectangular box",
        label_zh="长方体",
        params_schema={
            "type": "object",
            "required": ["size_x", "size_y", "size_z"],
            "additionalProperties": False,
            "properties": {
                "size_x": {"$ref": "#/$defs/Positive"},
                "size_y": {"$ref": "#/$defs/Positive"},
                "size_z": {"$ref": "#/$defs/Positive"},
                "center": {"$ref": "#/$defs/Center3"},
                "mode": {"$ref": "#/$defs/Mode"},
            },
        },
        cli=CliSyntax(verb_aliases=("box",)),
    )


def revolve_spec() -> CommandSpec:
    """feature.revolve per Appendix A.1 (axis: X | Y | 3-numbers)."""
    return CommandSpec(
        id="feature.revolve",
        version=1,
        summary_en="Revolve a parametric profile",
        label_zh="旋转",
        params_schema={
            "type": "object",
            "required": ["profile", "axis"],
            "additionalProperties": False,
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
        },
        cli=CliSyntax(verb_aliases=("revolve",)),
    )


def boolean_cut_spec() -> CommandSpec:
    """modify.boolean_cut per Appendix A.1 (`cut` maps ONLY here; no mode key)."""
    return CommandSpec(
        id="modify.boolean_cut",
        version=1,
        summary_en="Subtract an inline tool solid",
        label_zh="差集",
        params_schema={
            "type": "object",
            "required": ["tool"],
            "additionalProperties": False,
            "properties": {"tool": {"$ref": "#/$defs/Tool"}},
        },
        cli=CliSyntax(verb_aliases=("cut",)),
    )


def ping_spec() -> CommandSpec:
    """demo.ping: plugin-namespace spec for category-derivation tests."""
    return CommandSpec(
        id="demo.ping",
        version=1,
        summary_en="Ping the demo registry",
        label_zh="演示",
        params_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("ping",)),
    )


#: All 8 Appendix A.1 command ids, in catalog order.
ALL_COMMAND_IDS: tuple[str, ...] = (
    "feature.box",
    "feature.cylinder",
    "feature.extrude",
    "feature.revolve",
    "feature.hole",
    "feature.hole_pattern",
    "modify.fillet",
    "modify.boolean_cut",
)


def _all_specs() -> list[CommandSpec]:
    return [
        box_spec(),
        cylinder_spec(),
        extrude_spec(),
        revolve_spec(),
        hole_spec(),
        hole_pattern_spec(),
        fillet_spec(),
        boolean_cut_spec(),
    ]


def synthetic_registry() -> CommandRegistry:
    """Fresh test-only registry: all 8 Appendix A.1 commands + demo.ping.

    The real 8-command registration is T7's; this synthetic instance exists
    for grammar round-trip / category / search tests only.
    """
    registry = CommandRegistry(schema_defs=DEFS)
    for spec in _all_specs():
        registry.register(spec)
    registry.register(ping_spec())
    return registry
