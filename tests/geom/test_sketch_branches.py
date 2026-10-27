# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometrically valid solver branches still need visible design-intent feedback."""

from dataclasses import replace
from math import sqrt

import pytest

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_branches import detect_branch_changes


def _id(number: int) -> str:
    return f"{number:032x}"


def _triangle(height: float = 5.0) -> Sketch:
    points = ((0.0, 0.0), (10.0, 0.0), (5.0, height))
    return Sketch(
        _id(100),
        WorkPlaneFrame.xy(),
        tuple(CircleEntity(_id(index + 1), point, 1.0) for index, point in enumerate(points)),
        tuple(
            SketchConstraint(
                _id(10 + index),
                "distance",
                (
                    SketchGeometryReference(_id(first), "center"),
                    SketchGeometryReference(_id(second), "center"),
                ),
                value,
                "mm",
            )
            for index, (first, second, value) in enumerate(
                ((1, 2, 10.0), (1, 3, sqrt(50)), (2, 3, sqrt(50)))
            )
        ),
    )


def test_line_reversal_identifies_the_persistent_entity() -> None:
    line = LineEntity(_id(1), (0.0, 0.0), (10.0, 0.0))
    before = Sketch(_id(100), WorkPlaneFrame.xy(), (line,))
    after = replace(before, entities=(replace(line, end_mm=(-10.0, 0.0)),))
    changes = detect_branch_changes(before, after)
    assert any(change.kind == "direction" and change.entity_ids == (_id(1),) for change in changes)


def test_mirrored_distance_triangle_is_detected_without_drawn_edges() -> None:
    before = _triangle()
    after = _triangle(-5.0)
    changes = detect_branch_changes(before, after)
    assert any(
        change.kind == "side" and set(change.entity_ids) == {_id(1), _id(2), _id(3)}
        for change in changes
    )


def test_translation_and_small_rotation_preserve_triangle_branch() -> None:
    before = _triangle()
    moved: list[CircleEntity] = []
    for entity in before.entities:
        assert isinstance(entity, CircleEntity)
        x, y = entity.center_mm
        moved.append(replace(entity, center_mm=(0.8 * x - 0.6 * y + 100, 0.6 * x + 0.8 * y - 30)))
    assert detect_branch_changes(before, replace(before, entities=tuple(moved))) == ()


def test_tolerance_does_not_report_numerical_side_jitter() -> None:
    assert detect_branch_changes(_triangle(1e-10), _triangle(-1e-10)) == ()


def test_rectangle_end_and_circle_geometry_use_the_solver_point_meanings() -> None:
    rectangle = RectangleEntity(_id(1), (0.0, 0.0), (10.0, 10.0))
    circle = CircleEntity(_id(2), (15.0, 5.0), 1.0)
    distance = SketchConstraint(
        _id(10),
        "distance",
        (SketchGeometryReference(_id(1), "end"), SketchGeometryReference(_id(2), "geometry")),
        sqrt(50),
        "mm",
    )
    before = Sketch(_id(100), WorkPlaneFrame.xy(), (rectangle, circle), (distance,))
    after = replace(before, entities=(rectangle, replace(circle, center_mm=(5.0, 15.0))))
    assert any(
        change.kind == "direction" and set(change.entity_ids) == {_id(1), _id(2)}
        for change in detect_branch_changes(before, after)
    )


def test_concentric_inner_outer_order_change_is_reported() -> None:
    outer = CircleEntity(_id(1), (0.0, 0.0), 5.0)
    inner = CircleEntity(_id(2), (0.0, 0.0), 2.0)
    relation = SketchConstraint(
        _id(10),
        "concentric",
        tuple(SketchGeometryReference(_id(index), "geometry") for index in (1, 2)),
    )
    before = Sketch(_id(100), WorkPlaneFrame.xy(), (outer, inner), (relation,))
    after = replace(before, entities=(outer, replace(inner, radius_mm=7.0)))
    assert any(change.kind == "nesting" for change in detect_branch_changes(before, after))


def test_external_to_internal_tangency_is_reported() -> None:
    outer = CircleEntity(_id(1), (0.0, 0.0), 5.0)
    other = CircleEntity(_id(2), (7.0, 0.0), 2.0)
    tangent = SketchConstraint(
        _id(10),
        "tangent",
        tuple(SketchGeometryReference(_id(index), "geometry") for index in (1, 2)),
    )
    before = Sketch(_id(100), WorkPlaneFrame.xy(), (outer, other), (tangent,))
    after = replace(before, entities=(outer, replace(other, center_mm=(3.0, 0.0))))
    assert any(change.kind == "tangency" for change in detect_branch_changes(before, after))


@pytest.mark.parametrize("sweep,kind", [(-90.0, "arc_sweep"), (270.0, "arc_span")])
def test_arc_orientation_and_minor_major_branch_are_reported(sweep: float, kind: str) -> None:
    arc = ArcEntity(_id(1), (0.0, 0.0), 5.0, 0.0, 90.0)
    before = Sketch(_id(100), WorkPlaneFrame.xy(), (arc,))
    after = replace(before, entities=(replace(arc, sweep_angle_deg=sweep),))
    assert any(change.kind == kind for change in detect_branch_changes(before, after))
