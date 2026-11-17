# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit dimension projections survive cross-sketch frame changes."""

import math
from dataclasses import replace
from typing import Literal
from uuid import uuid4

import pytest

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    project_coplanar_entity,
    validate_tangency_component,
)
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.cross_sketch_tangency import (
    solve_tangency_component,
    solve_tangency_component_constraint,
)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("ordinate", [False, True])
@pytest.mark.parametrize("negative", [False, True])
def test_cross_sketch_edit_uses_explicit_axis(
    opposite: bool, ordinate: bool, negative: bool
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((0, 0, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    first_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    second_line = LineEntity(uuid4().hex, (-6 * q, 14 * q * sign), (14 * q, -6 * q * sign))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    direction_sign = -1 if negative else 1
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(second_line.entity_id, "geometry"),),
        -20 if ordinate and negative else 20,
        "mm",
        axis="ordinate_x" if ordinate else "horizontal",
        projection_axis=(direction_sign * q, -direction_sign * sign * q),
    )
    reference = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(second_line.entity_id, "geometry"),),
        0,
        "mm",
        driving=False,
        axis="ordinate_y",
        projection_axis=(q, sign * q),
    )
    baseline = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first_line.entity_id, "geometry"),),
        20,
        "mm",
        axis="horizontal",
    )
    first = Sketch("1" * 32, WorkPlaneFrame.xy(), (first_line,), (baseline,))
    second = Sketch("2" * 32, frame, (second_line,), (dimension, reference))
    third = Sketch("3" * 32, WorkPlaneFrame.xy(), (circle,))
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, first_line.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_left",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, second_line.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_left" if opposite else "line_right",
        ),
    )
    initial = solve_tangency_component((first, second, third), relations, third.sketch_id)
    measured = next(item for item in initial if item.sketch_id == second.sketch_id)
    assert measured.constraints[0] == dimension
    assert measured.constraints[1].value == pytest.approx(0, abs=1e-7)
    value = -18 if ordinate and negative else 18
    solved = solve_tangency_component_constraint(
        initial, relations, second.sketch_id, replace(dimension, value=value)
    )
    updated = next(sketch for sketch in solved if sketch.sketch_id == second.sketch_id)
    result = updated.entities[0]
    assert isinstance(result, LineEntity)
    dx = result.end_mm[0] - result.start_mm[0]
    dy = result.end_mm[1] - result.start_mm[1]
    assert direction_sign * (dx * q - dy * sign * q) == pytest.approx(-18 if negative else 18)
    assert updated.constraints[1].value == pytest.approx(dx * q + dy * sign * q)


@pytest.mark.parametrize("opposite", [False, True])
def test_projection_dimension_preserves_tangent_branch_with_radius_constraint(
    opposite: bool,
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2, "mm"
    )
    first = Sketch(uuid4().hex, frame, (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (radius,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right" if opposite else "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    solved_circle = next(
        sketch for sketch in solved if sketch.sketch_id == second.sketch_id
    ).entities[0]
    assert isinstance(solved_circle, CircleEntity)
    assert solved_circle.radius_mm == pytest.approx(2)


@pytest.mark.parametrize("opposite", [False, True])
def test_projection_dimension_preserves_tangency_with_unrelated_fixed_geometry(
    opposite: bool,
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other = LineEntity(uuid4().hex, (30, 30), (40, 30), construction=True)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(other.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, frame, (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, other), (fixed,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right" if opposite else "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    result = next(sketch for sketch in solved if sketch.sketch_id == second.sketch_id)
    unchanged = next(entity for entity in result.entities if entity.entity_id == other.entity_id)
    assert isinstance(unchanged, LineEntity)
    assert unchanged.start_mm == pytest.approx(other.start_mm)
    assert unchanged.end_mm == pytest.approx(other.end_mm)
    assert result.constraints == (fixed,)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("second_side", [1, -1])
def test_projection_dimension_preserves_two_cross_sketch_tangencies(
    opposite: bool, second_side: int
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    first = Sketch(uuid4().hex, frame, (line,))
    circles = tuple(
        CircleEntity(uuid4().hex, point, 2) for point in ((-5, 2), (5, second_side * 2))
    )
    others = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)) for circle in circles)
    relations = tuple(
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, line.entity_id),
            CrossSketchRef(sketch.sketch_id, circle.entity_id),
            "line_left" if (circle.center_mm[1] > 0) != opposite else "line_right",
        )
        for sketch, circle in zip(others, circles, strict=True)
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    solved = solve_tangency_component_constraint(
        (first, *others), relations, first.sketch_id, dimension
    )
    validate_tangency_component(solved, relations, first.sketch_id)
    solved_line = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[
        0
    ]
    assert isinstance(solved_line, LineEntity)
    start = frame.local_to_world(solved_line.start_mm)
    end = frame.local_to_world(solved_line.end_mm)
    assert end[0] - start[0] == pytest.approx(15)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("unrelated_fixed", [False, True])
@pytest.mark.parametrize("endpoint_link", [False, True])
def test_projection_dimension_preserves_cross_sketch_arc_tangency(
    opposite: bool, unrelated_fixed: bool, endpoint_link: bool
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (0, 0) if endpoint_link else (10, 0)),
        WorkPlaneFrame.xy(),
        frame,
    )
    arc = ArcEntity(
        uuid4().hex, (0, 2), 2, 270 if endpoint_link else 180, 90 if endpoint_link else 180
    )
    other = LineEntity(uuid4().hex, (30, 30), (40, 30), construction=True)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(other.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, frame, (line,))
    second = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (arc, other) if unrelated_fixed else (arc,),
        (fixed,) if unrelated_fixed else (),
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_right" if opposite else "line_left",
        first_endpoint="end" if endpoint_link else None,
        second_endpoint="start" if endpoint_link else None,
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        8 if endpoint_link else 15,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    solved_line = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[
        0
    ]
    assert isinstance(solved_line, LineEntity)
    start = frame.local_to_world(solved_line.start_mm)
    end = frame.local_to_world(solved_line.end_mm)
    assert end[0] - start[0] == pytest.approx(8 if endpoint_link else 15)


@pytest.mark.parametrize("reverse_order", [False, True])
def test_projection_dimension_preserves_tangent_chain(reverse_order: bool) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (q, -q, 0), (0, 0, -1))
    line = project_coplanar_entity(
        LineEntity("4" * 32, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = CircleEntity("5" * 32, (-4, 2), 2)
    follower = CircleEntity("6" * 32, (-4, 6), 2)
    first = Sketch("3" * 32, frame, (line,))
    second = Sketch("2" * 32, WorkPlaneFrame.xy(), (circle,))
    third = Sketch("1" * 32, WorkPlaneFrame.xy(), (follower,))
    relation_ids = ("8" * 32, "7" * 32) if reverse_order else ("7" * 32, "8" * 32)
    relations = (
        CrossSketchTangency(
            relation_ids[0],
            CrossSketchRef(first.sketch_id, line.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "line_right",
        ),
        CrossSketchTangency(
            relation_ids[1],
            CrossSketchRef(second.sketch_id, circle.entity_id),
            CrossSketchRef(third.sketch_id, follower.entity_id),
            "external",
        ),
    )
    dimension = SketchConstraint(
        "9" * 32,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    solved = solve_tangency_component_constraint(
        (first, second, third), relations, first.sketch_id, dimension
    )
    validate_tangency_component(solved, relations, first.sketch_id)
    solved_line = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[
        0
    ]
    assert isinstance(solved_line, LineEntity)
    start, end = (
        frame.local_to_world(solved_line.start_mm),
        frame.local_to_world(solved_line.end_mm),
    )
    assert end[0] - start[0] == pytest.approx(15)


@pytest.mark.parametrize("fixed_end", ["start", "end"])
@pytest.mark.parametrize("opposite", [False, True])
def test_projection_dimension_keeps_fixed_line_endpoint_and_tangency(
    fixed_end: Literal["start", "end"], opposite: bool
) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity("4" * 32, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = CircleEntity("5" * 32, (0, 2), 2)
    fixed = SketchConstraint(
        "6" * 32, "fixed", (SketchGeometryReference(line.entity_id, fixed_end),)
    )
    first = Sketch("3" * 32, frame, (line,), (fixed,))
    second = Sketch("2" * 32, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        "7" * 32,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right" if opposite else "line_left",
    )
    dimension = SketchConstraint(
        "8" * 32,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    result = updated.entities[0]
    assert isinstance(result, LineEntity)
    assert getattr(result, f"{fixed_end}_mm") == pytest.approx(getattr(line, f"{fixed_end}_mm"))
    start, end = frame.local_to_world(result.start_mm), frame.local_to_world(result.end_mm)
    assert end[0] - start[0] == pytest.approx(15)
    assert fixed in updated.constraints
