# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Arbitrary projection directions measure and solve without axis substitution."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_constraints import measure_sketch_dimension, solve_sketch_constraint


@pytest.mark.parametrize("ordinate", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_reference_dimension_uses_explicit_axis(ordinate: bool, reverse: bool) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (-4, -2) if reverse else (4, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        0,
        "mm",
        driving=False,
        axis="ordinate_x" if ordinate else "horizontal",
        projection_axis=(q, q),
    )
    expected = -6 * q if ordinate and reverse else 6 * q
    assert measure_sketch_dimension(sketch, constraint) == pytest.approx(expected)
    result = solve_sketch_constraint(sketch, constraint)
    assert result.status == "success" and result.sketch is not None
    assert result.sketch.constraints[0].value == pytest.approx(expected)


def test_driving_dimension_solves_along_explicit_axis() -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    result = solve_sketch_constraint(sketch, dimension)
    assert result.status == "success" and result.sketch is not None, result.message
    assert measure_sketch_dimension(result.sketch, dimension) == pytest.approx(10)
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert (
        solved.end_mm[0] - solved.start_mm[0] + solved.end_mm[1] - solved.start_mm[1]
    ) * q == pytest.approx(10)


@pytest.mark.parametrize("value", [-8.0, 0.0, 8.0])
def test_driving_ordinate_preserves_signed_projection(value: float) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value,
        "mm",
        axis="ordinate_x",
        projection_axis=(q, q),
    )
    result = solve_sketch_constraint(sketch, dimension)
    assert result.status == "success" and result.sketch is not None, result.message
    assert measure_sketch_dimension(result.sketch, dimension) == pytest.approx(value, abs=1e-6)
