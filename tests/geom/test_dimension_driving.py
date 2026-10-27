# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drive coordinates with correct signs and predictable edit anchors."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.sketch import CircleEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_constraints import solve_sketch_constraint


def length(
    line: LineEntity, value: float, axis: str = "horizontal", mode: str = "auto"
) -> SketchConstraint:
    raw = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value,
        "mm",
        axis=axis,
    ).to_mapping()
    if mode != "auto":
        raw["anchor_mode"] = mode
    return SketchConstraint.from_mapping(raw)


@pytest.mark.parametrize(
    "axis,finish",
    [
        ("horizontal", (40, 0)),
        ("vertical", (0, 40)),
        ("ordinate_x", (-40, 0)),
        ("ordinate_y", (0, -40)),
    ],
)
def test_fixed_start_directed_projection(axis: str, finish: tuple[int, int]) -> None:
    line = LineEntity(
        uuid4().hex, (0, 0), (30, 0) if axis.endswith("x") or axis == "horizontal" else (0, 30)
    )
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed,))
    result = solve_sketch_constraint(
        sketch, length(line, -40 if axis.startswith("ordinate") else 40, axis)
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((0, 0))
    assert solved.end_mm == pytest.approx(finish)
    if not axis.startswith("ordinate"):
        assert not result.branch_changes


@pytest.mark.parametrize(
    "mode,start,end", [("auto", 0, 40), ("start", 0, 40), ("end", -10, 30), ("symmetric", -5, 35)]
)
def test_linear_anchor_modes_do_not_add_permanent_relations(
    mode: str, start: int, end: int
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dim = length(line, 40, mode=mode)
    result = solve_sketch_constraint(sketch, dim)
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((start, 0))
    assert solved.end_mm == pytest.approx((end, 0))
    assert result.sketch.constraints == (dim,)
    assert result.degrees_of_freedom == 3
    assert sketch.entities == (line,)


def test_auto_anchor_respects_existing_fixed_end_and_explicit_conflict_fails() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed,))
    result = solve_sketch_constraint(sketch, length(line, 40))
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((-10, 0))
    assert solved.end_mm == pytest.approx((30, 0))
    conflict = solve_sketch_constraint(sketch, length(line, 40, mode="start"))
    assert conflict.status != "success"
    assert conflict.sketch is None
    assert sketch.entities == (line,)


def test_reverse_linear_direction_is_preserved() -> None:
    line = LineEntity(uuid4().hex, (30, 0), (0, 0))
    result = solve_sketch_constraint(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), length(line, 40)
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((30, 0))
    assert solved.end_mm == pytest.approx((-10, 0))


def test_rectangle_width_keeps_height_and_circle_radius_keeps_center() -> None:
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (80, 40))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        120,
        "mm",
        axis="horizontal",
    )
    result = solve_sketch_constraint(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,)), constraint
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, RectangleEntity)
    assert solved.first_corner_mm == pytest.approx((0, 0))
    assert solved.opposite_corner_mm == pytest.approx((120, 40))
    centered = solve_sketch_constraint(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,)),
        SketchConstraint.from_mapping({**constraint.to_mapping(), "anchor_mode": "symmetric"}),
    )
    assert centered.status == "success", centered.message
    assert centered.sketch is not None
    box = centered.sketch.entities[0]
    assert isinstance(box, RectangleEntity)
    assert box.first_corner_mm == pytest.approx((-20, 0))
    assert box.opposite_corner_mm == pytest.approx((100, 40))
    circle = CircleEntity(uuid4().hex, (10, 20), 5)
    radial = replace(
        constraint,
        constraint_id=uuid4().hex,
        kind="radius",
        references=(SketchGeometryReference(circle.entity_id, "geometry"),),
        value=7,
        axis="aligned",
    )
    radius_result = solve_sketch_constraint(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)), radial
    )
    assert radius_result.status == "success", radius_result.message
    assert radius_result.sketch is not None
    assert radius_result.sketch.entities == (replace(circle, radius_mm=7),)


def test_connected_lines_follow_driver_and_existing_dimensions() -> None:
    first = LineEntity(uuid4().hex, (0, 0), (30, 0))
    second = LineEntity(uuid4().hex, (30, 0), (50, 0))
    join = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(second.entity_id, "geometry"),)
    )
    other_length = length(second, 20)
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (first, second), (join, horizontal, other_length)
    )
    result = solve_sketch_constraint(sketch, length(first, 40))
    assert result.status == "success", result.message
    assert result.sketch is not None
    a, b = result.sketch.entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    assert a.start_mm == pytest.approx((0, 0))
    assert a.end_mm == pytest.approx((40, 0))
    assert b.start_mm == pytest.approx((40, 0))
    assert b.end_mm == pytest.approx((60, 0))
    assert result.sketch.constraints[:3] == sketch.constraints


def test_hole_position_driver_keeps_fixed_outline_and_circle_radius() -> None:
    outline = RectangleEntity(uuid4().hex, (0, 0), (80, 40))
    hole = CircleEntity(uuid4().hex, (10, 20), 5)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(outline.entity_id, "vertex", 0),)
    )
    width = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(outline.entity_id, "segment", 0),), 80, "mm"
    )
    height = replace(
        width,
        constraint_id=uuid4().hex,
        references=(SketchGeometryReference(outline.entity_id, "segment", 1),),
        value=40,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (outline, hole), (fixed, width, height))
    offset = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(outline.entity_id, "vertex", 0),
            SketchGeometryReference(hole.entity_id, "center"),
        ),
        30,
        "mm",
        axis="horizontal",
    )
    result = solve_sketch_constraint(sketch, offset)
    assert result.status == "success", result.message
    assert result.sketch is not None
    box, circle = result.sketch.entities
    assert isinstance(box, RectangleEntity) and isinstance(circle, CircleEntity)
    assert box.first_corner_mm == pytest.approx((0, 0))
    assert box.opposite_corner_mm == pytest.approx((80, 40))
    assert circle.center_mm == pytest.approx((30, 20))
    assert circle.radius_mm == pytest.approx(5)
