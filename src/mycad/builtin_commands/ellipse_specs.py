# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Version-preserving schema augmentation for exact sketch ellipses."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import cast


def with_ellipse_entities(schema: Mapping[str, object]) -> dict[str, object]:
    """Copy a command schema and add ellipses to its sketch-entity alternatives."""

    def visit(value: object) -> object:
        if isinstance(value, list):
            items = [visit(item) for item in cast("list[object]", value)]
            if any(_kind(item) == "ellipse" for item in items):
                return items
            for item in items:
                if not isinstance(item, dict):
                    continue
                fields = cast("dict[str, object]", item).get("properties")
                if not isinstance(fields, dict):
                    continue
                properties = cast("dict[str, object]", fields)
                kind = properties.get("kind")
                if (
                    isinstance(kind, dict)
                    and cast("dict[str, object]", kind).get("const") == "line"
                    and "start_mm" in properties
                    and "end_mm" in properties
                    and "entity_id" in properties
                ):
                    items.append(_ellipse_schema())
                    break
            return items
        if isinstance(value, dict):
            return {key: visit(item) for key, item in cast("dict[str, object]", value).items()}
        return value

    return cast("dict[str, object]", visit(deepcopy(dict(schema))))


def _kind(value: object) -> object:
    if not isinstance(value, dict):
        return None
    fields = cast("dict[str, object]", value).get("properties")
    if not isinstance(fields, dict):
        return None
    kind = cast("dict[str, object]", fields).get("kind")
    return cast("dict[str, object]", kind).get("const") if isinstance(kind, dict) else None


def _ellipse_schema() -> dict[str, object]:
    fields: dict[str, object] = {
        "entity_id": {"type": "string", "minLength": 32, "maxLength": 36},
        "kind": {"const": "ellipse"},
        "construction": {"type": "boolean"},
        "layer_name": {"type": "string", "minLength": 1, "maxLength": 255},
        "center_mm": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "major_radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "minor_radius_mm": {"type": "number", "exclusiveMinimum": 0},
        "rotation_deg": {"type": "number"},
        "start_angle_deg": {"type": "number"},
        "sweep_angle_deg": {"type": "number", "minimum": -360, "maximum": 360},
    }
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }
