# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persistent projection axes keep old dimension encodings compatible."""

import math
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_projection_axis_roundtrip_does_not_change_legacy_dimensions() -> None:
    old = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        5,
        "mm",
        axis="horizontal",
    )
    assert "projection_axis" not in old.to_mapping()
    assert SketchConstraint.from_mapping(old.to_mapping()) == old
    q = math.sqrt(0.5)
    angled = replace(old, projection_axis=(q, -q))
    assert angled.to_mapping()["projection_axis"] == [q, -q]
    assert SketchConstraint.from_mapping(angled.to_mapping()) == angled


@pytest.mark.parametrize("axis", [(0.0, 0.0), (2.0, 0.0), (math.inf, 0.0), (True, 0.0)])
def test_projection_axis_must_be_finite_unit_vector(axis: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(uuid4().hex, "geometry"),),
            5,
            "mm",
            axis="horizontal",
            projection_axis=axis,
        )


def test_projection_axis_requires_directional_linear_dimension() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "length", (ref,), 5, "mm", projection_axis=(1, 0))
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "radius", (ref,), 5, "mm", projection_axis=(1, 0))


def test_released_constraint_and_create_versions_reject_new_axis() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        axis="horizontal",
        projection_axis=(1, 0),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    create = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 27)
    with pytest.raises(ValidationError):
        validate_params(create, sketch.to_state_mapping(), defs=COMMAND_SCHEMA_DEFS)
    new_create = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 28
    )
    assert validate_params(new_create, sketch.to_state_mapping(), defs=COMMAND_SCHEMA_DEFS)
    add = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.constraint.add" and s.version == 5
    )
    with pytest.raises(ValidationError):
        validate_params(
            add,
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": "0" * 64,
                "constraint": dimension.to_mapping(),
            },
            defs=COMMAND_SCHEMA_DEFS,
        )


@pytest.mark.parametrize(
    ("command", "version"),
    [
        ("sketch.create", 28),
        ("sketch.constraint.add", 6),
        ("sketch.constraint.update", 4),
        ("sketch.revise", 5),
        ("drawing.sketch.revise", 31),
        ("drawing.tangency.add", 7),
    ],
)
def test_new_command_schemas_accept_projection_axis(command: str, version: int) -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS

    spec = next(s for s in BUILTIN_COMMAND_SPECS if s.id == command and s.version == version)

    def constraints(value: object) -> list[dict[str, object]]:
        if isinstance(value, dict):
            mapping = cast("dict[str, object]", value)
            properties = mapping.get("properties")
            result = (
                [cast("dict[str, object]", properties)]
                if isinstance(properties, dict)
                and {"constraint_id", "kind", "references", "driving", "source"}
                <= cast("dict[str, object]", properties).keys()
                else []
            )
            return result + [item for child in mapping.values() for item in constraints(child)]
        if isinstance(value, list):
            return [item for child in cast("list[object]", value) for item in constraints(child)]
        return []

    found = constraints(spec.params_schema)
    assert found and all("projection_axis" in properties for properties in found)
