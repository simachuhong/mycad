# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Projected and arc dimensions measure and drive their actual geometry."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_constraints import measure_sketch_dimension, solve_sketch_constraint


@pytest.mark.parametrize("axis,expected", [("horizontal", 30), ("vertical", 40)])
def test_projected_length_is_not_diagonal(axis: str, expected: float) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        expected,
        "mm",
        axis=axis,
    )
    assert measure_sketch_dimension(sketch, constraint) == pytest.approx(expected)
    from dataclasses import replace

    constraint = replace(constraint, value=12)
    result = solve_sketch_constraint(sketch, constraint)
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert measure_sketch_dimension(result.sketch, constraint) == pytest.approx(12)


def test_arc_length_dimension_measures_and_drives() -> None:
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    constraint = SketchConstraint(
        uuid4().hex,
        "arc_length",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        5 * math.pi,
        "mm",
    )
    assert measure_sketch_dimension(sketch, constraint) == pytest.approx(5 * math.pi)
    from dataclasses import replace

    constraint = replace(constraint, value=12)
    result = solve_sketch_constraint(sketch, constraint)
    assert result.status == "success", result.message
    assert result.sketch is not None
    assert measure_sketch_dimension(result.sketch, constraint) == pytest.approx(12)


def test_ordinate_dimension_keeps_signed_projection() -> None:
    line = LineEntity(uuid4().hex, (10, 10), (-20, -30))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    constraint = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        -30,
        "mm",
        driving=False,
        axis="ordinate_x",
    )
    assert measure_sketch_dimension(sketch, constraint) == -30
