# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Compatible hole@3: legacy query/sketch branches plus explicit design binding."""

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.bound_refs import BOUND_FACE_ROLES

BOUND_HOLE_SPEC = CommandSpec(
    id="feature.hole",
    version=3,
    summary_en="Drill query, sketch or design-bound face holes",
    label_zh="孔",
    params_schema={
        "oneOf": [
            {"$ref": "#/$defs/Hole"},
            {"$ref": "#/$defs/SketchHole"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["target_face", "position", "diameter", "depth"],
                "properties": {
                    "target_face": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "source_instance_id", "role"],
                        "properties": {
                            "kind": {"const": "bound_face"},
                            "source_instance_id": {
                                "type": "string",
                                "minLength": 32,
                                "maxLength": 32,
                            },
                            "role": {"type": "string", "enum": list(BOUND_FACE_ROLES)},
                        },
                    },
                    "position": {
                        "oneOf": [
                            {"$ref": "#/$defs/Position"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind", "uv_mm"],
                                "properties": {
                                    "kind": {"const": "local"},
                                    "uv_mm": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                            },
                        ]
                    },
                    "diameter": {"$ref": "#/$defs/Positive"},
                    "depth": {"$ref": "#/$defs/Depth"},
                },
            },
        ]
    },
    cli=CliSyntax(verb_aliases=("hole",)),
)
