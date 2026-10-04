# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Demo command (T3): the ONE command registered in product code.

``feature.cylinder`` is the framework's demonstration command, transcribed
verbatim from plan Appendix A.1. Its ``$ref`` targets resolve against
``DEMO_SCHEMA_DEFS`` — a PROTOTYPE defs table (Mode/Center3/Positive) used as
test fixture material. It is deliberately NOT named ``COMMAND_SCHEMA_DEFS``
and deliberately NOT a second formal table: the single formal constant lives
in T7's ``src/mycad/builtin_commands/defs.py`` (``COMMAND_SCHEMA_DEFS =`` may
be assigned only there); the other seven commands are T7's as well.
"""

from __future__ import annotations

from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec

__all__ = ["DEMO_SCHEMA_DEFS", "cylinder_spec", "demo_registry"]

#: Prototype ``$defs`` table (Mode/Center3/Positive). Treat as immutable.
DEMO_SCHEMA_DEFS: dict[str, object] = {
    "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
    "Center3": {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    },
    "Positive": {"type": "number", "exclusiveMinimum": 0.0},
}


def cylinder_spec() -> CommandSpec:
    """feature.cylinder per Appendix A.1 (fresh instance per call)."""
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


def demo_registry() -> CommandRegistry:
    """Fresh registry with the demo command and its prototype defs injected."""
    registry = CommandRegistry(schema_defs=DEMO_SCHEMA_DEFS)
    registry.register(cylinder_spec())
    return registry
