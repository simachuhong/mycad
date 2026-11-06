# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned coordinate-system and datum-plane command definitions."""

from mycad.commands.spec import CliSyntax, CommandSpec

VECTOR3: dict[str, object] = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}


def reference(kind: str, role: str) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "source_instance_id", "role"],
        "properties": {
            "kind": {"const": kind},
            "source_instance_id": {"type": "string", "minLength": 32, "maxLength": 32},
            "role": {"const": role},
        },
    }


WORLD: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {"kind": {"const": "world"}},
}
COORD = reference("coordinate_system", "coordinate_system")
PLANE = reference("datum_plane", "plane")

DATUM_SPECS = (
    CommandSpec(
        id="datum.coordinate_system.create",
        version=1,
        summary_en="Create a relative coordinate system",
        label_zh="创建坐标系",
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "parent", "origin_mm", "x_axis", "y_axis", "z_axis"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "parent": {"oneOf": [WORLD, COORD]},
                "origin_mm": VECTOR3,
                "x_axis": VECTOR3,
                "y_axis": VECTOR3,
                "z_axis": VECTOR3,
            },
        },
    ),
    CommandSpec(
        id="datum.plane.create",
        version=1,
        summary_en="Create a principal or offset datum plane",
        label_zh="创建基准平面",
        cli=CliSyntax(verb_aliases=()),
        min_archive_version=6,
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "construction"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "construction": {
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kind", "coordinate_system", "plane"],
                            "properties": {
                                "kind": {"const": "principal"},
                                "coordinate_system": {"oneOf": [WORLD, COORD]},
                                "plane": {"enum": ["xy", "xz", "yz"]},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kind", "plane", "distance_mm"],
                            "properties": {
                                "kind": {"const": "offset"},
                                "plane": PLANE,
                                "distance_mm": {"type": "number"},
                            },
                        },
                    ]
                },
            },
        },
    ),
)
