# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The eight built-in Phase-0 command specs (T7a, plan Appendix A.1).

Every spec's ``params_schema`` references the shared A.0 definitions
exclusively via ``$ref`` — the table itself lives in
``mycad.builtin_commands.defs.COMMAND_SCHEMA_DEFS`` and is injected at the
composition root via ``CommandRegistry(schema_defs=...)``.

Conventions (A.2): every root object carries ``additionalProperties:
false``; ``properties`` declaration order IS the canonical ``to_cli`` key
order (the rule itself is owned by T3 — this module only declares the
order); ``feature.hole`` is a bare root-level ``$ref`` to the Hole
definition (#round11-3); ``modify.boolean_cut`` deliberately accepts no
``mode`` key (feature-command subtraction goes through ``mode=cut``).
"""

from __future__ import annotations

from mycad.commands.spec import CliSyntax, CommandSpec

__all__ = ["BUILTIN_COMMAND_SPECS"]

#: The eight Appendix A.1 commands, in catalog order.
BUILTIN_COMMAND_SPECS: tuple[CommandSpec, ...] = (
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
        summary_en="Extrude a parametric profile",
        label_zh="拉伸",
        params_schema={
            "type": "object",
            "properties": {
                "profile": {"$ref": "#/$defs/Profile"},
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
                    "items": {"$ref": "#/$defs/EdgeSelector"},
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
)
