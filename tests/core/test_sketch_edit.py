# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, CAD-backend-free sketch edit geometry."""

from __future__ import annotations

import math
from collections.abc import Callable
from uuid import uuid4

import pytest

from mycad.core import sketch_edit
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
)
from mycad.core.sketch_edit import (
    circular_array_entities,
    copy_entities,
    extend_line_at,
    linear_array_entities,
    mirror_entities,
    move_entities,
    offset_entities,
    rotate_entities,
    split_line_at,
    trim_curve_at,
    trim_line_at,
)


def _line(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    construction: bool = False,
    layer_name: str = "0",
) -> LineEntity:
    return LineEntity(uuid4().hex, start, end, construction=construction, layer_name=layer_name)


@pytest.mark.parametrize("gap", (-5e-9, 5e-9))
def test_trim_extend_recognize_tangent_tolerance(gap: float) -> None:
    line = _line((-5, 2 + gap), (-1, 2 + gap))
    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    result = sketch_edit.extend_curve_at(
        (line, circle), line.end_mm, hit_tolerance_mm=0.1, target_entity_id=line.entity_id
    )
    assert isinstance(result[0], LineEntity)
    assert result[0].end_mm == pytest.approx((0, 2 + gap))

    arc = ArcEntity(uuid4().hex, (10, 0), 5, 90, 180)
    cutter = CircleEntity(uuid4().hex, (0, 0), 5 + gap)
    trimmed = trim_curve_at(
        (arc, cutter),
        (6.464466, 3.535534),
        hit_tolerance_mm=0.1,
        target_entity_id=arc.entity_id,
    )
    assert isinstance(trimmed[0], ArcEntity)
    assert trimmed[0].start_angle_deg == pytest.approx(180)
    assert trimmed[0].sweep_angle_deg == pytest.approx(90)


def test_intersections_outside_tangent_tolerance_remain_distinct() -> None:
    for gap, expected_count in ((2e-7, 0), (-2e-7, 2)):
        line_hits = sketch_edit.supporting_line_circle_intersections(
            (-5, 2 + gap), (5, 2 + gap), (0, 0), 2
        )
        circle_hits = sketch_edit.supporting_circle_intersections((0, 0), 5, (10 + gap, 0), 5)
        assert len(line_hits) == expected_count
        assert len(circle_hits) == expected_count


@pytest.mark.parametrize("gap", (-5e-9, 5e-9))
@pytest.mark.parametrize("closed", [False, True])
def test_polyline_trim_recognizes_tangent_tolerance(gap: float, closed: bool) -> None:
    points = ((-5, 0), (5, 0), (5, 5), (-5, 5))
    polyline = PolylineEntity(uuid4().hex, points, closed=closed)
    circle = CircleEntity(uuid4().hex, (0, -2 - gap), 2)
    cutter = _line((3, -1), (3, 6))
    result = trim_curve_at(
        (polyline, circle, cutter),
        (1.5, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=polyline.entity_id,
    )
    assert isinstance(result[0], PolylineEntity)
    if closed:
        assert result[0].points_mm[0] == pytest.approx((3, 0))
        assert result[0].points_mm[-1] == pytest.approx((0, 0))
    else:
        assert result[0].points_mm[-1] == pytest.approx((0, 0))


def test_uniform_scale_preserves_entity_types_identity_and_geometry() -> None:
    from mycad.core.sketch import PointEntity, SplineEntity
    from mycad.core.sketch_edit import scale_entities

    point = PointEntity(uuid4().hex, (2, 3), construction=True, layer_name="S")
    line = _line((1, 1), (3, 2), layer_name="S")
    path = PolylineEntity(uuid4().hex, ((1, 1), (3, 1), (3, 3)), bulges=(0.5, 0))
    circle = CircleEntity(uuid4().hex, (2, 2), 3)
    arc = ArcEntity(uuid4().hex, (3, 3), 2, 30, -90)
    rectangle = RectangleEntity(uuid4().hex, (1, 1), (4, 3))
    spline = SplineEntity(uuid4().hex, ((1, 1), (2, 2), (3, 2), (4, 1)))
    entities = (point, line, path, circle, arc, rectangle, spline)
    result = scale_entities(entities, tuple(item.entity_id for item in entities), (1, 1), 2)
    assert result == (
        PointEntity(point.entity_id, (3, 5), True, "S"),
        LineEntity(line.entity_id, (1, 1), (5, 3), layer_name="S"),
        PolylineEntity(path.entity_id, ((1, 1), (5, 1), (5, 5)), bulges=(0.5, 0)),
        CircleEntity(circle.entity_id, (3, 3), 6),
        ArcEntity(arc.entity_id, (5, 5), 4, 30, -90),
        RectangleEntity(rectangle.entity_id, (1, 1), (7, 5)),
        SplineEntity(spline.entity_id, ((1, 1), (3, 3), (5, 3), (7, 1))),
    )
    assert entities[1] == line


@pytest.mark.parametrize("factor", [0, -1, float("nan"), float("inf"), True])
def test_uniform_scale_rejects_invalid_factor(factor: float) -> None:
    from mycad.core.sketch_edit import scale_entities

    line = _line((0, 0), (1, 0))
    with pytest.raises(ValueError):
        scale_entities((line,), (line.entity_id,), (0, 0), factor)


def test_scaled_copy_preserves_original_and_allocates_stable_new_identity() -> None:
    from mycad.core.sketch_edit import copy_scaled_entities

    line = _line((1, 1), (3, 1), construction=True, layer_name="S")
    result = copy_scaled_entities((line,), (line.entity_id,), (1, 1), 0.5)
    assert result[0] == line and len(result) == 2
    copy = result[1]
    assert isinstance(copy, LineEntity) and copy.entity_id != line.entity_id
    assert copy.start_mm == (1, 1) and copy.end_mm == (2, 1)
    assert copy.layer_name == "S" and copy.construction


def test_trim_removes_clicked_side_and_preserves_surviving_entity_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    cutter = _line((10.0, -5.0), (10.0, 5.0))

    result = trim_line_at((target, cutter), (15.0, 0.0), hit_tolerance_mm=0.5)

    assert len(result) == 2
    trimmed = result[0]
    assert isinstance(trimmed, LineEntity)
    assert trimmed.entity_id == target.entity_id
    assert trimmed.start_mm == (0.0, 0.0)
    assert trimmed.end_mm == pytest.approx((10.0, 0.0))
    assert result[1] == cutter


def test_edge_extend_uses_supporting_line_as_virtual_boundary() -> None:
    target = _line((0, 0), (20, 0))
    boundary = _line((10, 2), (10, 5))
    with pytest.raises(ValueError, match="交点"):
        trim_curve_at(
            (target, boundary), (15, 0), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
        )
    result = trim_curve_at(
        (target, boundary),
        (15, 0),
        hit_tolerance_mm=0.2,
        target_entity_id=target.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], LineEntity) and result[0].end_mm == pytest.approx((10, 0))
    short = _line((0, 0), (5, 0))
    result = sketch_edit.extend_curve_at(
        (short, boundary),
        (5, 0),
        hit_tolerance_mm=0.2,
        target_entity_id=short.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], LineEntity) and result[0].end_mm == pytest.approx((10, 0))
    assert result[1] == boundary


def test_edge_extend_trims_circle_against_virtual_lines() -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    cutters = (_line((-3, 8), (-3, 10)), _line((3, 8), (3, 10)))
    with pytest.raises(ValueError, match="交点"):
        trim_curve_at(
            (circle, *cutters), (0, 5), hit_tolerance_mm=0.2, target_entity_id=circle.entity_id
        )
    result = trim_curve_at(
        (circle, *cutters),
        (0, 5),
        hit_tolerance_mm=0.2,
        target_entity_id=circle.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], ArcEntity) and result[0].radius_mm == pytest.approx(5)
    assert result[1:] == cutters


@pytest.mark.parametrize("closed", (False, True))
def test_edge_extend_trims_curved_polyline_against_virtual_lines(closed: bool) -> None:
    points = ((-5, 0), (5, 0), (5, -5), (-5, -5)) if closed else ((-5, 0), (5, 0))
    source = PolylineEntity(uuid4().hex, points, closed, bulges=(-1, 0, 0, 0) if closed else (-1,))
    cutters = (_line((-3, 8), (-3, 10)), _line((3, 8), (3, 10)))
    result = trim_curve_at(
        (source, *cutters),
        (0, 5),
        hit_tolerance_mm=0.2,
        target_entity_id=source.entity_id,
        extend_boundaries=True,
    )
    fragments = result[:-2]
    assert len(fragments) == (1 if closed else 2)
    assert all(isinstance(fragment, PolylineEntity) and fragment.bulges for fragment in fragments)
    assert result[-2:] == cutters


@pytest.mark.parametrize("closed", (False, True))
def test_edge_extend_trims_straight_polyline_against_virtual_lines(closed: bool) -> None:
    points = ((0, 0), (20, 0), (20, 10), (0, 10)) if closed else ((0, 0), (20, 0))
    source = PolylineEntity(uuid4().hex, points, closed)
    cutters = (_line((5, -5), (5, -2)), _line((15, -5), (15, -2)))
    result = trim_curve_at(
        (source, *cutters),
        (10, 0),
        hit_tolerance_mm=0.2,
        target_entity_id=source.entity_id,
        extend_boundaries=True,
    )
    assert len(result) == (3 if closed else 4)
    assert result[-2:] == cutters


def test_edge_extend_extends_arc_polyline_to_virtual_line() -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (0, 5)), bulges=(-math.tan(math.pi / 8),))
    cutter = _line((5, 8), (5, 10))
    result = sketch_edit.extend_curve_at(
        (source, cutter),
        (0, 5),
        hit_tolerance_mm=0.2,
        target_entity_id=source.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((5, 0))


def test_edge_extend_trims_rectangle_with_virtual_boundaries() -> None:
    target = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutters = (_line((5, -5), (5, -2)), _line((15, -5), (15, -2)))
    result = trim_curve_at(
        (target, *cutters),
        (10, 0),
        hit_tolerance_mm=0.2,
        target_entity_id=target.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], PolylineEntity) and not result[0].closed
    assert result[-2:] == cutters


def test_edge_extend_uses_arc_supporting_circle_as_boundary() -> None:
    target = _line((-10, 4), (10, 4))
    boundary = ArcEntity(uuid4().hex, (0, 0), 5, 0, -180)
    with pytest.raises(ValueError, match="交点"):
        trim_curve_at(
            (target, boundary), (0, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
        )
    result = trim_curve_at(
        (target, boundary),
        (0, 4),
        hit_tolerance_mm=0.2,
        target_entity_id=target.entity_id,
        extend_boundaries=True,
    )
    assert isinstance(result[0], LineEntity) and isinstance(result[1], LineEntity)
    assert result[0].end_mm == pytest.approx((-3, 4))
    assert result[1].start_mm == pytest.approx((3, 4))
    assert result[2] == boundary


def test_curved_polyline_is_an_exact_line_trim_boundary() -> None:
    target = _line((-10, 4), (10, 4))
    cutter = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    result = trim_curve_at(
        (target, cutter), (0, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
    )
    first, second = result[:2]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == pytest.approx((-3, 4))
    assert second.start_mm == pytest.approx((3, 4))
    assert result[2] == cutter


def test_fence_intersections_use_finite_arc_and_straight_segments() -> None:
    curved = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    hits = sketch_edit.fence_intersections((-10, 4), (10, 4), curved)
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-3, 4))
    assert hits[1] == pytest.approx((3, 4))
    assert not sketch_edit.fence_intersections((-10, -4), (10, -4), curved)
    assert not sketch_edit.fence_intersections((-2, 4), (2, 4), curved)


def test_fence_rejects_overlapping_line_interval() -> None:
    line = _line((0, 0), (10, 0))
    with pytest.raises(ValueError, match="重叠"):
        sketch_edit.fence_intersections((5, 0), (12, 0), line)
    assert not sketch_edit.fence_intersections((11, 0), (12, 0), line)


def test_curved_polyline_is_an_exact_line_extend_and_split_boundary() -> None:
    cutter = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    target = _line((-10, 4), (-5, 4))
    extended = sketch_edit.extend_curve_at(
        (target, cutter), (-5, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
    )
    assert isinstance(extended[0], LineEntity) and extended[0].end_mm == pytest.approx((-3, 4))
    span = _line((-10, 4), (10, 4))
    split = split_line_at(
        (span, cutter), (-3, 4), hit_tolerance_mm=0.2, target_entity_id=span.entity_id
    )
    assert isinstance(split[0], LineEntity) and split[0].end_mm == pytest.approx((-3, 4))
    assert isinstance(split[1], LineEntity) and split[1].start_mm == pytest.approx((-3, 4))
    lower = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(1,))
    with pytest.raises(ValueError, match="没有有效交点"):
        sketch_edit.extend_curve_at(
            (target, lower), (-5, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
        )


def test_curved_polyline_is_an_exact_circle_and_path_boundary() -> None:
    cutter = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    circle = CircleEntity(uuid4().hex, (0, 4), 4)
    result = trim_curve_at(
        (circle, cutter), (0, 8), hit_tolerance_mm=0.2, target_entity_id=circle.entity_id
    )
    assert isinstance(result[0], ArcEntity) and result[0].entity_id == circle.entity_id
    arc = result[0]
    for angle in (arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg):
        point = (
            arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(angle)),
            arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(angle)),
        )
        assert math.dist(point, (0, 0)) == pytest.approx(5)
        assert point[1] > 0
    target = PolylineEntity(uuid4().hex, ((-10, 4), (10, 4)))
    result = trim_curve_at(
        (target, cutter), (0, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
    )
    assert isinstance(result[0], PolylineEntity) and isinstance(result[1], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((-3, 4))
    assert result[1].points_mm[0] == pytest.approx((3, 4))
    closed = PolylineEntity(uuid4().hex, ((-10, -4), (10, -4), (10, 4), (-10, 4)), True)
    result = trim_curve_at(
        (closed, cutter), (0, 4), hit_tolerance_mm=0.2, target_entity_id=closed.entity_id
    )
    assert isinstance(result[0], PolylineEntity) and not result[0].closed
    assert {
        tuple(round(value, 6) for value in point)
        for point in (result[0].points_mm[0], result[0].points_mm[-1])
    } == {(-3, 4), (3, 4)}


def test_curved_construction_polyline_is_not_a_cutting_boundary() -> None:
    target = _line((-10, 4), (10, 4))
    curved = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), construction=True, bulges=(-1,))
    cutter = _line((0, 0), (0, 8))
    result = trim_curve_at(
        (target, curved, cutter), (5, 4), hit_tolerance_mm=0.2, target_entity_id=target.entity_id
    )
    assert isinstance(result[0], LineEntity) and result[0].end_mm == pytest.approx((0, 4))
    assert result[1:] == (curved, cutter)


def test_curve_polyline_target_without_intersection_is_not_treated_as_chord() -> None:
    curved = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    unrelated = _line((-10, 10), (10, 10))
    with pytest.raises(ValueError, match="没有.*交点"):
        trim_curve_at((curved, unrelated), (0, 5), hit_tolerance_mm=0.2)
    assert curved.points_mm == ((-5, 0), (5, 0)) and curved.bulges == (-1,)


@pytest.mark.parametrize("reverse", (False, True))
def test_trim_open_curved_polyline_preserves_exact_arc_fragments(reverse: bool) -> None:
    points = ((-5, 0), (5, 0), (10, 0))
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(0, 1) if reverse else (-1, 0),
        layer_name="curve",
    )
    cutters = (_line((-3, 2), (-3, 6)), _line((3, 2), (3, 6)))
    result = trim_curve_at(
        (source, *cutters), (0, 5), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    first, second = result[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.entity_id == source.entity_id and second.entity_id != source.entity_id
    assert first.layer_name == second.layer_name == "curve"
    assert first.points_mm[-1] == pytest.approx((3 if reverse else -3, 4))
    assert second.points_mm[0] == pytest.approx((-3 if reverse else 3, 4))
    from mycad.core.polyline_curves import polyline_curve_segments

    first_arc = polyline_curve_segments(first.points_mm, first.bulges, False, first.entity_id)[-1]
    second_arc = polyline_curve_segments(second.points_mm, second.bulges, False, second.entity_id)[
        0
    ]
    assert isinstance(first_arc, ArcEntity) and isinstance(second_arc, ArcEntity)
    assert first_arc.radius_mm == pytest.approx(5) and second_arc.radius_mm == pytest.approx(5)
    assert result[2:] == cutters


@pytest.mark.parametrize("click, expected_start", [((-4, 3), (0, 5)), ((4, 3), (-5, 0))])
def test_trim_curved_terminal_interval_preserves_identity(
    click: tuple[float, float], expected_start: tuple[float, float]
) -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    cutter = _line((0, 3), (0, 7))
    result = trim_curve_at((source, cutter), click, hit_tolerance_mm=0.2)
    assert isinstance(result[0], PolylineEntity)
    assert result[0].entity_id == source.entity_id
    assert result[0].points_mm[0] == pytest.approx(expected_start)
    assert result[0].bulges == pytest.approx((-math.tan(math.pi / 8),))
    assert result[1] == cutter


def test_trim_straight_part_of_curved_path_preserves_prior_arc() -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (10, 0)), bulges=(-1, 0))
    cutter = _line((7, -2), (7, 2))
    result = trim_curve_at(
        (source, cutter), (9, 0), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    assert isinstance(result[0], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((7, 0))
    assert result[0].bulges == pytest.approx((-1, 0))


@pytest.mark.parametrize("operation", ("trim", "split"))
@pytest.mark.parametrize("reverse", (False, True))
def test_edit_closed_curved_polyline_preserves_arc_and_path(
    operation: str,
    reverse: bool,
) -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((-5, -5), (5, -5), (5, 0), (-5, 0)) if reverse else ((-5, 0), (5, 0), (5, -5), (-5, -5)),
        True,
        bulges=(0, 0, 1, 0) if reverse else (-1, 0, 0, 0),
        layer_name="curve",
    )
    cutters = (_line((-3, 2), (-3, 6)), _line((3, 2), (3, 6)))
    edit = trim_curve_at if operation == "trim" else sketch_edit.split_entity_at
    result = edit(
        (source, *cutters), (0, 5), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    fragments = result[:-2]
    assert len(fragments) == (1 if operation == "trim" else 2)
    assert result[-2:] == cutters
    from mycad.core.polyline_curves import polyline_curve_segments

    for fragment in fragments:
        assert isinstance(fragment, PolylineEntity) and not fragment.closed
        assert fragment.layer_name == "curve"
        assert {
            tuple(round(v, 6) for v in point)
            for point in (fragment.points_mm[0], fragment.points_mm[-1])
        } == {(-3, 4), (3, 4)}
        arcs = [
            segment
            for segment in polyline_curve_segments(
                fragment.points_mm, fragment.bulges, False, fragment.entity_id
            )
            if isinstance(segment, ArcEntity)
        ]
        assert arcs and all(arc.radius_mm == pytest.approx(5) for arc in arcs)
    assert isinstance(fragments[0], PolylineEntity)
    assert fragments[0].entity_id == source.entity_id


@pytest.mark.parametrize("at_start", (False, True))
def test_extend_curved_polyline_arc_endpoint(at_start: bool) -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((0, 5), (-5, 0)) if at_start else ((-5, 0), (0, 5)),
        bulges=(math.tan(math.pi / 8) if at_start else -math.tan(math.pi / 8),),
        layer_name="curve",
    )
    cutter = _line((5, -2), (5, 2))
    result = sketch_edit.extend_curve_at(
        (source, cutter), (0, 5), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    assert isinstance(result[0], PolylineEntity)
    assert result[0].entity_id == source.entity_id and result[0].layer_name == "curve"
    assert result[0].points_mm[0 if at_start else -1] == pytest.approx((5, 0))
    assert result[0].bulges == pytest.approx((1 if at_start else -1,))
    assert result[1] == cutter


def test_extend_straight_endpoint_of_curved_polyline_preserves_arc() -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (8, 0)), bulges=(-1, 0))
    cutter = _line((10, -2), (10, 2))
    result = sketch_edit.extend_curve_at(
        (source, cutter), (8, 0), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    assert isinstance(result[0], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((10, 0))
    assert result[0].bulges == pytest.approx((-1, 0))


@pytest.mark.parametrize("distance, radius", ((1, 6), (-1, 4)))
def test_offset_tangent_line_arc_polyline_preserves_exact_curves(
    distance: float, radius: float
) -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((-5, 0), (0, 5), (5, 5)),
        bulges=(-math.tan(math.pi / 8), 0),
        layer_name="curve",
    )
    result = offset_entities((source,), (source.entity_id,), distance)
    assert result[0] == source and isinstance(result[1], PolylineEntity)
    offset = result[1]
    assert offset.layer_name == "curve" and offset.entity_id != source.entity_id
    assert offset.points_mm[0] == pytest.approx((-radius, 0))
    assert offset.points_mm[1] == pytest.approx((0, radius))
    assert offset.points_mm[2] == pytest.approx((5, radius))
    assert offset.bulges == pytest.approx(source.bulges)


def test_offset_curved_polyline_rejects_collapsed_arc() -> None:
    tangent = PolylineEntity(
        uuid4().hex, ((-5, 0), (0, 5), (5, 5)), bulges=(-math.tan(math.pi / 8), 0)
    )
    with pytest.raises(ValueError, match="半径"):
        offset_entities((tangent,), (tangent.entity_id,), -5)


def test_offset_curved_polyline_miters_line_arc_corner() -> None:
    source = PolylineEntity(
        uuid4().hex, ((-5, 0), (0, 5), (0, 10)), bulges=(-math.tan(math.pi / 8), 0)
    )
    result = offset_entities((source,), (source.entity_id,), 1)
    assert isinstance(result[1], PolylineEntity)
    offset = result[1]
    assert offset.points_mm[1] == pytest.approx((-1, math.sqrt(35)))
    assert offset.points_mm[2] == pytest.approx((-1, 10))
    from mycad.core.polyline_curves import polyline_curve_segments

    arc = polyline_curve_segments(offset.points_mm, offset.bulges, False, offset.entity_id)[0]
    assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(6)


@pytest.mark.parametrize("distance", (-1.0, 1.0))
def test_offset_curved_polyline_miters_two_arc_corner(distance: float) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    source = PolylineEntity(
        uuid4().hex, ((-5, 0), (0, 5), (5, 0)), bulges=(-math.tan(math.pi / 8), 0.2)
    )
    original = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    result = offset_entities((source,), (source.entity_id,), distance)
    assert isinstance(result[1], PolylineEntity)
    offset = result[1]
    arcs = polyline_curve_segments(offset.points_mm, offset.bulges, False, offset.entity_id)
    for first, second in zip(original, arcs, strict=True):
        assert isinstance(first, ArcEntity) and isinstance(second, ArcEntity)
        expected = first.radius_mm - distance * math.copysign(1, first.sweep_angle_deg)
        assert second.center_mm == pytest.approx(first.center_mm)
        assert second.radius_mm == pytest.approx(expected)
        assert math.copysign(1, second.sweep_angle_deg) == math.copysign(1, first.sweep_angle_deg)
    assert offset.points_mm[1] != source.points_mm[1]


def test_offset_rejects_adjacent_overlapping_curved_segments() -> None:
    bulge = math.tan(3 * math.pi / 8)
    source = PolylineEntity(uuid4().hex, ((5, 0), (0, -5), (-5, 0)), bulges=(bulge, bulge))
    with pytest.raises(ValueError, match="重合|自相交"):
        offset_entities((source,), (source.entity_id,), 0.5)


@pytest.mark.parametrize("distance, radius", ((1, 4), (-1, 6)))
def test_offset_closed_curved_polyline_preserves_capsule(distance: float, radius: float) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    source = PolylineEntity(
        uuid4().hex, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1)
    )
    result = offset_entities((source,), (source.entity_id,), distance)
    assert isinstance(result[1], PolylineEntity) and result[1].closed
    segments = polyline_curve_segments(
        result[1].points_mm, result[1].bulges, True, result[1].entity_id
    )
    arcs = [segment for segment in segments if isinstance(segment, ArcEntity)]
    assert len(arcs) == 2 and all(arc.radius_mm == pytest.approx(radius) for arc in arcs)
    assert result[1].points_mm[0] == pytest.approx((-5, distance))
    assert result[1].points_mm[2] == pytest.approx((5, 10 - distance))


def test_offset_curved_polyline_with_straight_miter_corner() -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((-5, 0), (0, 5), (5, 5), (5, 10)),
        bulges=(-math.tan(math.pi / 8), 0, 0),
    )
    result = offset_entities((source,), (source.entity_id,), 1)
    assert isinstance(result[1], PolylineEntity)
    assert result[1].points_mm[1] == pytest.approx((0, 6))
    assert result[1].points_mm[2] == pytest.approx((4, 6))
    assert result[1].points_mm[3] == pytest.approx((4, 10))
    assert result[1].bulges == pytest.approx(source.bulges)


@pytest.mark.parametrize("reverse", (False, True))
def test_split_open_curved_polyline_preserves_exact_arc_segments(reverse: bool) -> None:
    points = ((-5, 0), (5, 0), (10, 0))
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(0, 1) if reverse else (-1, 0),
        layer_name="curve",
    )
    boundary = _line((0, 3), (0, 7))
    result = sketch_edit.split_entity_at(
        (source, boundary), (0, 5), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    first, second = result[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.entity_id == source.entity_id and second.entity_id != source.entity_id
    assert first.layer_name == second.layer_name == "curve"
    assert first.points_mm[-1] == pytest.approx((0, 5))
    assert second.points_mm[0] == pytest.approx((0, 5))
    expected = math.tan(math.pi / 8) * (1 if reverse else -1)
    assert first.bulges[-1] == pytest.approx(expected)
    assert second.bulges[0] == pytest.approx(expected)
    assert result[2] == boundary


def test_split_straight_portion_keeps_other_polyline_arcs() -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (10, 0)), bulges=(-1, 0))
    boundary = _line((7, -2), (7, 2))
    result = sketch_edit.split_entity_at(
        (source, boundary), (7, 0), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    first, second = result[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((7, 0))
    assert first.bulges == pytest.approx((-1, 0))
    assert second.points_mm == ((7, 0), (10, 0)) and not second.bulges


def test_split_curved_segment_uses_finite_circle_intersection() -> None:
    source = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    boundary = CircleEntity(uuid4().hex, (0, 4), 4)
    result = sketch_edit.split_entity_at(
        (source, boundary), (3.9, 3.125), hit_tolerance_mm=0.2, target_entity_id=source.entity_id
    )
    first, second = result[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    point = first.points_mm[-1]
    assert math.dist(point, (0, 0)) == pytest.approx(5)
    assert math.dist(point, boundary.center_mm) == pytest.approx(boundary.radius_mm)
    assert second.points_mm[0] == pytest.approx(point)
    from mycad.core.polyline_curves import polyline_curve_segments

    first_arc = polyline_curve_segments(first.points_mm, first.bulges, False, first.entity_id)[0]
    second_arc = polyline_curve_segments(second.points_mm, second.bulges, False, second.entity_id)[
        0
    ]
    assert isinstance(first_arc, ArcEntity) and isinstance(second_arc, ArcEntity)
    assert first_arc.radius_mm == pytest.approx(5) and second_arc.radius_mm == pytest.approx(5)
    assert first_arc.sweep_angle_deg + second_arc.sweep_angle_deg == pytest.approx(-180)


def test_trim_middle_interval_splits_and_assigns_a_new_identity_to_new_fragment() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_line_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    fragments = tuple(item for item in result if isinstance(item, LineEntity))
    assert len(fragments) == 4
    retained_fragments = fragments[:2]
    assert retained_fragments[0].start_mm == (0.0, 0.0)
    assert retained_fragments[0].end_mm == pytest.approx((5.0, 0.0))
    assert retained_fragments[1].start_mm == pytest.approx((15.0, 0.0))
    assert retained_fragments[1].end_mm == (20.0, 0.0)
    assert retained_fragments[0].entity_id == target.entity_id
    assert retained_fragments[1].entity_id != target.entity_id
    assert len({entity.entity_id for entity in fragments}) == len(fragments)
    assert result[2:] == (first_cutter, second_cutter)


def test_trim_open_polyline_segment_splits_path_and_preserves_prefix_identity() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)), construction=True)
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == target.entity_id
    assert first.points_mm == ((0.0, 0.0), (2.0, 0.0), (5.0, 0.0))
    assert second.entity_id != target.entity_id
    assert second.points_mm == ((15.0, 0.0), (20.0, 0.0))
    assert first.construction and second.construction
    assert not first.closed and not second.closed
    assert result[2:] == (first_cutter, second_cutter)


def test_trim_open_polyline_rejects_closed_paths_or_missing_intersections() -> None:
    closed = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
        closed=True,
    )
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    closed_entities: tuple[SketchEntity, ...] = (closed, cutter)
    with pytest.raises(ValueError, match="闭合多段线"):
        trim_curve_at(closed_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert closed_entities == (closed, cutter)

    open_path = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    open_entities: tuple[SketchEntity, ...] = (open_path,)
    with pytest.raises(ValueError, match="交点"):
        trim_curve_at(open_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert open_entities == (open_path,)


def test_trim_open_polyline_uses_circle_intersections_as_cutters() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    first_cutter = CircleEntity(uuid4().hex, (5.0, 5.0), 5.0)
    second_cutter = CircleEntity(uuid4().hex, (15.0, 5.0), 5.0)

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((5.0, 0.0))
    assert second.points_mm[0] == pytest.approx((15.0, 0.0))


@pytest.mark.parametrize(
    ("click", "cutter_x", "expected_points"),
    [
        ((2.0, 0.0), 5.0, ((5.0, 0.0), (10.0, 0.0), (20.0, 0.0))),
        ((18.0, 0.0), 15.0, ((0.0, 0.0), (10.0, 0.0), (15.0, 0.0))),
    ],
)
def test_trim_open_polyline_terminal_interval_to_single_intersection(
    click: tuple[float, float],
    cutter_x: float,
    expected_points: tuple[tuple[float, float], ...],
) -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
        construction=True,
    )
    cutter = _line((cutter_x, -5.0), (cutter_x, 5.0))

    result = trim_curve_at((target, cutter), click, hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, PolylineEntity)
    assert trimmed.entity_id == target.entity_id
    assert trimmed.points_mm == expected_points
    assert trimmed.construction
    assert result[1] == cutter


def test_trim_open_polyline_single_intersection_on_internal_segment_splits_path() -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (20.0, 10.0)),
        construction=True,
    )
    cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_curve_at((target, cutter), (12.0, 0.0), hit_tolerance_mm=0.5)

    prefix, suffix = result[:2]
    assert isinstance(prefix, PolylineEntity)
    assert isinstance(suffix, PolylineEntity)
    assert prefix.entity_id == target.entity_id
    assert prefix.points_mm == ((0.0, 0.0), (10.0, 0.0))
    assert suffix.entity_id != target.entity_id
    assert suffix.points_mm == ((15.0, 0.0), (20.0, 0.0), (20.0, 10.0))
    assert prefix.construction and suffix.construction
    assert result[2] == cutter


@pytest.mark.parametrize(
    ("click", "message"),
    (((5.0, 0.0), "不明确"), ((0.0, 0.0), "区间|顶点|交点")),
)
def test_trim_open_polyline_rejects_intersection_and_vertex_clicks_without_mutation(
    click: tuple[float, float], message: str
) -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    entities: tuple[SketchEntity, ...] = (target, cutter)

    with pytest.raises(ValueError, match=message):
        trim_curve_at(entities, click, hit_tolerance_mm=0.5)

    assert entities == (target, cutter)


def test_trim_open_polyline_filters_arc_cutters_to_their_valid_sweeps() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    first_cutter = ArcEntity(uuid4().hex, (5.0, 5.0), 5.0, 250.0, 40.0)
    second_cutter = ArcEntity(uuid4().hex, (15.0, 5.0), 5.0, 250.0, 40.0)

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((5.0, 0.0))
    assert second.points_mm[0] == pytest.approx((15.0, 0.0))


def test_trim_preserves_original_direction_and_ignores_construction_cutters() -> None:
    target = _line((20.0, 0.0), (0.0, 0.0))
    cutter = LineEntity(uuid4().hex, (10.0, -5.0), (10.0, 5.0), construction=True)

    with pytest.raises(ValueError, match="交点"):
        trim_line_at((target, cutter), (5.0, 0.0), hit_tolerance_mm=0.5)

    regular_cutter = _line((10.0, -5.0), (10.0, 5.0))
    result = trim_line_at((target, regular_cutter), (5.0, 0.0), hit_tolerance_mm=0.5)

    retained = result[0]
    assert isinstance(retained, LineEntity)
    assert retained.entity_id == target.entity_id
    assert retained.start_mm == (20.0, 0.0)
    assert retained.end_mm == pytest.approx((10.0, 0.0))


def test_extend_line_end_to_nearest_intersection_preserves_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    near_cutter = _line((30.0, -5.0), (30.0, 5.0))
    far_cutter = _line((40.0, -5.0), (40.0, 5.0))

    result = extend_line_at((target, near_cutter, far_cutter), (20.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.start_mm == (0.0, 0.0)
    assert extended.end_mm == (30.0, 0.0)
    assert result[1:] == (near_cutter, far_cutter)


def test_extend_line_start_to_intersection_and_reject_invalid_targets() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    cutter = _line((-5.0, -5.0), (-5.0, 5.0))

    result = extend_line_at((target, cutter), (0.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.start_mm == (-5.0, 0.0)
    assert extended.end_mm == (20.0, 0.0)

    with pytest.raises(ValueError, match="端点"):
        extend_line_at((target, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        extend_line_at((target,), (20.0, 0.0), hit_tolerance_mm=0.5)


@pytest.mark.parametrize("cutter_kind", ("circle", "arc"))
def test_extend_line_to_nearest_valid_circular_cutter_hit(cutter_kind: str) -> None:
    target = _line((0.0, 0.0), (10.0, 0.0))
    cutter: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (15.0, 0.0), 2.0)
        if cutter_kind == "circle"
        else ArcEntity(uuid4().hex, (15.0, 0.0), 2.0, 90.0, 180.0)
    )

    result = extend_line_at((target, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.end_mm == pytest.approx((13.0, 0.0))
    assert result[1] == cutter


@pytest.mark.parametrize(
    ("at_start", "expected_points", "cutters"),
    [
        (
            True,
            ((-5.0, 0.0), (2.0, 0.0), (20.0, 0.0)),
            (_line((-5.0, -5.0), (-5.0, 5.0)), _line((-10.0, -5.0), (-10.0, 5.0))),
        ),
        (
            False,
            ((0.0, 0.0), (2.0, 0.0), (25.0, 0.0)),
            (_line((25.0, -5.0), (25.0, 5.0)), _line((30.0, -5.0), (30.0, 5.0))),
        ),
    ],
)
def test_extend_open_polyline_terminal_endpoint_to_nearest_straight_hit(
    at_start: bool,
    expected_points: tuple[tuple[float, float], ...],
    cutters: tuple[LineEntity, LineEntity],
) -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)),
        construction=True,
    )
    endpoint = target.points_mm[0] if at_start else target.points_mm[-1]

    result = sketch_edit.extend_curve_at((target, *cutters), endpoint, hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, PolylineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.points_mm == expected_points
    assert not extended.closed
    assert extended.construction
    assert result[1:] == cutters


@pytest.mark.parametrize("cutter_kind", ("circle", "arc"))
def test_extend_open_polyline_terminal_endpoint_to_circular_cutter(cutter_kind: str) -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0)))
    cutter: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (5.0, 0.0), 1.0)
        if cutter_kind == "circle"
        else ArcEntity(uuid4().hex, (5.0, 0.0), 1.0, 90.0, 180.0)
    )

    result = sketch_edit.extend_curve_at(
        (target, cutter), target.points_mm[-1], hit_tolerance_mm=0.5
    )

    extended = result[0]
    assert isinstance(extended, PolylineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.points_mm[0] == (0.0, 0.0)
    assert extended.points_mm[-1] == pytest.approx((4.0, 0.0))
    assert result[1] == cutter


def test_extend_open_polyline_rejects_closed_internal_and_no_hit_without_mutation() -> None:
    open_target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)))
    closed_target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)),
        closed=True,
    )
    cutter = _line((15.0, -5.0), (15.0, 5.0))
    construction_cutter = _line((15.0, -5.0), (15.0, 5.0), construction=True)
    no_hit = (open_target,)
    construction_only: tuple[SketchEntity, ...] = (open_target, construction_cutter)
    closed_entities: tuple[SketchEntity, ...] = (closed_target, cutter)
    internal_entities: tuple[SketchEntity, ...] = (open_target, cutter)

    with pytest.raises(ValueError, match="开放多段线端点"):
        sketch_edit.extend_curve_at(closed_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="端点"):
        sketch_edit.extend_curve_at(internal_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        sketch_edit.extend_curve_at(no_hit, (10.0, 10.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        sketch_edit.extend_curve_at(construction_only, (10.0, 10.0), hit_tolerance_mm=0.5)

    assert closed_entities == (closed_target, cutter)
    assert internal_entities == (open_target, cutter)
    assert no_hit == (open_target,)
    assert construction_only == (open_target, construction_cutter)


def test_extend_counterclockwise_arc_start_to_nearest_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = sketch_edit.extend_curve_at((arc, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, ArcEntity)
    assert extended.entity_id == arc.entity_id
    assert extended.start_angle_deg == pytest.approx(300.0)
    assert extended.sweep_angle_deg == pytest.approx(150.0)
    assert result[1] == cutter


def test_extend_clockwise_arc_end_to_nearest_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 90.0, -90.0)
    cutter = _line((-10.0, -5.0), (10.0, -5.0))

    result = sketch_edit.extend_curve_at((arc, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, ArcEntity)
    assert extended.entity_id == arc.entity_id
    assert extended.start_angle_deg == pytest.approx(90.0)
    assert extended.sweep_angle_deg == pytest.approx(-120.0)
    assert result[1] == cutter


def test_extend_arc_rejects_endpoint_without_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    cutter = _line((5.0, 0.0), (15.0, 0.0))
    entities: tuple[SketchEntity, ...] = (arc, cutter)

    with pytest.raises(ValueError, match="延伸方向上没有交点"):
        sketch_edit.extend_curve_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (arc, cutter)


def test_extend_arc_rejects_closing_to_a_full_circle() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 350.0)
    cutter = _line((10.0, -5.0), (10.0, 5.0))
    entities: tuple[SketchEntity, ...] = (arc, cutter)
    end = (
        10.0 * math.cos(math.radians(350.0)),
        10.0 * math.sin(math.radians(350.0)),
    )

    with pytest.raises(ValueError, match="整圆"):
        sketch_edit.extend_curve_at(entities, end, hit_tolerance_mm=0.5)
    assert entities == (arc, cutter)


def test_split_line_at_nearest_intersection_preserves_first_fragment_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = split_line_at((target, first_cutter, second_cutter), (13.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, LineEntity)
    assert isinstance(second, LineEntity)
    assert first.entity_id == target.entity_id
    assert first.start_mm == (0.0, 0.0)
    assert first.end_mm == pytest.approx((15.0, 0.0))
    assert second.start_mm == pytest.approx((15.0, 0.0))
    assert second.end_mm == (20.0, 0.0)
    assert second.entity_id != target.entity_id
    assert result[2:] == (first_cutter, second_cutter)


def test_split_line_rejects_missing_intersection_without_mutating_input() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    entities = (target,)
    with pytest.raises(ValueError, match="交点"):
        split_line_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (target,)


def test_split_open_polyline_segment_keeps_prefix_identity_and_new_suffix_identity() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)), construction=True)
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = sketch_edit.split_entity_at(
        (target, first_cutter, second_cutter), (13.0, 0.0), hit_tolerance_mm=0.5
    )

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == target.entity_id
    assert first.points_mm == ((0.0, 0.0), (2.0, 0.0), (15.0, 0.0))
    assert not first.closed
    assert first.construction
    assert second.entity_id != target.entity_id
    assert second.points_mm == ((15.0, 0.0), (20.0, 0.0))
    assert not second.closed
    assert second.construction
    assert result[2:] == (first_cutter, second_cutter)


def test_split_closed_polyline_rejects_without_mutating_input() -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
        closed=True,
    )
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    entities: tuple[SketchEntity, ...] = (target, cutter)

    with pytest.raises(ValueError, match="闭合多段线"):
        sketch_edit.split_entity_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (target, cutter)


@pytest.mark.parametrize(
    ("entities", "point", "message"),
    [
        ((_line((0.0, 0.0), (20.0, 0.0)),), (10.0, 0.0), "交点"),
        (
            (_line((0.0, 0.0), (20.0, 0.0)), _line((10.0, -5.0), (10.0, 5.0))),
            (10.0, 0.0),
            "不明确",
        ),
        (
            (
                _line((0.0, 0.0), (20.0, 0.0)),
                _line((0.0, 1.0), (20.0, 1.0)),
                _line((5.0, -5.0), (5.0, 5.0)),
            ),
            (10.0, 0.5),
            "不明确",
        ),
    ],
)
def test_trim_rejects_missing_ambiguous_or_intersection_clicks(
    entities: tuple[SketchEntity, ...], point: tuple[float, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        trim_line_at(entities, point, hit_tolerance_mm=0.5)


def test_move_and_copy_transform_all_entity_kinds_without_mutating_input() -> None:
    line = _line((0.0, 0.0), (2.0, 0.0))
    polyline = PolylineEntity(uuid4().hex, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
    circle = CircleEntity(uuid4().hex, (2.0, 2.0), 1.0)
    arc = ArcEntity(uuid4().hex, (3.0, 3.0), 2.0, 30.0, 90.0)
    rectangle = RectangleEntity(uuid4().hex, (0.0, 0.0), (2.0, 1.0))
    entities: tuple[SketchEntity, ...] = (line, polyline, circle, arc, rectangle)
    selected = tuple(entity.entity_id for entity in entities)

    moved = move_entities(entities, selected, (5.0, -2.0))
    copied = copy_entities(entities, selected, (5.0, -2.0))

    assert entities[0] == line
    assert isinstance(moved[0], LineEntity)
    assert moved[0].entity_id == line.entity_id
    assert moved[0].start_mm == (5.0, -2.0)
    assert isinstance(moved[1], PolylineEntity)
    assert moved[1].points_mm == ((5.0, -2.0), (6.0, -2.0), (6.0, -1.0))
    assert isinstance(moved[2], CircleEntity)
    assert moved[2].center_mm == (7.0, 0.0)
    assert isinstance(moved[3], ArcEntity)
    assert moved[3].center_mm == (8.0, 1.0)
    assert isinstance(moved[4], RectangleEntity)
    assert moved[4].first_corner_mm == (5.0, -2.0)
    assert copied[:5] == entities
    clones = copied[5:]
    assert len(clones) == len(entities)
    assert {entity.entity_id for entity in clones}.isdisjoint(selected)
    assert isinstance(clones[0], LineEntity)
    assert clones[0].start_mm == (5.0, -2.0)


def test_draft_transforms_preserve_layer_assignment_on_originals_and_copies() -> None:
    entity = LineEntity(
        uuid4().hex,
        (0.0, 0.0),
        (10.0, 0.0),
        layer_name="OUTLINE",
    )

    moved = move_entities((entity,), (entity.entity_id,), (0.0, 5.0))[0]
    copied = copy_entities((entity,), (entity.entity_id,), (0.0, 5.0))[1]
    offset = offset_entities((entity,), (entity.entity_id,), 2.0)[1]

    assert moved.layer_name == "OUTLINE"
    assert copied.layer_name == "OUTLINE"
    assert offset.layer_name == "OUTLINE"


@pytest.mark.parametrize("operation", ("trim", "split", "extend"))
def test_line_edit_fragments_keep_the_source_layer(operation: str) -> None:
    if operation == "trim":
        target = _line((0.0, 0.0), (20.0, 0.0), layer_name="OUTLINE")
        cutters = (_line((5.0, -5.0), (5.0, 5.0)), _line((15.0, -5.0), (15.0, 5.0)))
        result = trim_curve_at((target, *cutters), (10.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:2]
    elif operation == "split":
        target = _line((0.0, 0.0), (20.0, 0.0), layer_name="OUTLINE")
        cutters = (_line((5.0, -5.0), (5.0, 5.0)), _line((15.0, -5.0), (15.0, 5.0)))
        result = split_line_at((target, *cutters), (13.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:2]
    else:
        target = _line((0.0, 0.0), (5.0, 0.0), layer_name="OUTLINE")
        cutter = _line((10.0, -5.0), (10.0, 5.0))
        result = extend_line_at((target, cutter), (5.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:1]

    assert all(entity.layer_name == "OUTLINE" for entity in fragments)


def test_rotate_and_mirror_preserve_identity_and_curve_orientation() -> None:
    arc = ArcEntity(uuid4().hex, (2.0, 0.0), 1.0, 0.0, 90.0)
    rectangle = RectangleEntity(uuid4().hex, (0.0, 0.0), (2.0, 1.0))
    entities: tuple[SketchEntity, ...] = (arc, rectangle)
    selected = (arc.entity_id, rectangle.entity_id)

    rotated = rotate_entities(entities, selected, (0.0, 0.0), 90.0)
    mirrored = mirror_entities(entities, selected, (0.0, 0.0), (0.0, 1.0))

    assert isinstance(rotated[0], ArcEntity)
    assert rotated[0].entity_id == arc.entity_id
    assert rotated[0].center_mm == pytest.approx((0.0, 2.0))
    assert rotated[0].start_angle_deg == pytest.approx(90.0)
    assert rotated[0].sweep_angle_deg == 90.0
    assert isinstance(rotated[1], RectangleEntity)
    assert rotated[1].entity_id == rectangle.entity_id
    assert rotated[1].first_corner_mm == pytest.approx((-1.0, 0.0))
    assert rotated[1].opposite_corner_mm == pytest.approx((0.0, 2.0))

    assert isinstance(mirrored[0], ArcEntity)
    assert mirrored[0].center_mm == (-2.0, 0.0)
    assert mirrored[0].start_angle_deg == pytest.approx(180.0)
    assert mirrored[0].sweep_angle_deg == -90.0
    assert isinstance(mirrored[1], RectangleEntity)
    assert mirrored[1].entity_id == rectangle.entity_id
    assert mirrored[1].first_corner_mm == (-2.0, 0.0)
    assert mirrored[1].opposite_corner_mm == (0.0, 1.0)

    oblique = rotate_entities(entities, (rectangle.entity_id,), (0.0, 0.0), 45.0)
    assert isinstance(oblique[1], PolylineEntity)
    assert oblique[1].entity_id == rectangle.entity_id
    assert oblique[1].closed


def test_linear_and_circular_arrays_include_original_and_allocate_fresh_ids() -> None:
    source = CircleEntity(uuid4().hex, (10.0, 0.0), 2.0, construction=True)
    entities: tuple[SketchEntity, ...] = (source,)

    linear = linear_array_entities(entities, (source.entity_id,), count=3, step_mm=(0.0, 5.0))
    circular = circular_array_entities(
        entities, (source.entity_id,), count=4, center_mm=(0.0, 0.0), total_angle_deg=360.0
    )

    assert len(linear) == 3
    assert linear[0] == source
    assert [item.center_mm for item in linear if isinstance(item, CircleEntity)] == [
        (10.0, 0.0),
        (10.0, 5.0),
        (10.0, 10.0),
    ]
    assert len({item.entity_id for item in linear}) == 3
    assert all(item.construction for item in linear)
    assert len(circular) == 4
    circular_circles = [item for item in circular if isinstance(item, CircleEntity)]
    assert [item.center_mm for item in circular_circles] == [
        pytest.approx((10.0, 0.0)),
        pytest.approx((0.0, 10.0)),
        pytest.approx((-10.0, 0.0)),
        pytest.approx((0.0, -10.0)),
    ]
    assert len({item.entity_id for item in circular}) == 4


@pytest.mark.parametrize(
    ("operation", "args", "match"),
    [
        (move_entities, (("missing",), (1.0, 0.0)), "选择"),
        (move_entities, ((), (1.0, 0.0)), "至少"),
        (move_entities, (("selected", "selected"), (1.0, 0.0)), "重复"),
        (move_entities, (("selected",), (math.inf, 0.0)), "finite"),
    ],
)
def test_entity_transform_rejects_invalid_selection_and_coordinates(
    operation: Callable[..., object], args: tuple[object, ...], match: str
) -> None:
    entity = _line((0.0, 0.0), (1.0, 0.0))
    with pytest.raises(ValueError, match=match):
        operation((entity,), *args)


def test_arrays_reject_count_below_two_and_zero_mirror_axis() -> None:
    entity = _line((0.0, 0.0), (1.0, 0.0))
    with pytest.raises(ValueError, match="至少为 2"):
        linear_array_entities((entity,), (entity.entity_id,), count=1, step_mm=(1.0, 0.0))
    with pytest.raises(ValueError, match="镜像轴"):
        mirror_entities((entity,), (entity.entity_id,), (1.0, 1.0), (1.0, 1.0))


def test_offset_supports_lines_curves_and_open_or_closed_polylines() -> None:
    line = _line((0.0, 0.0), (10.0, 0.0))
    open_path = PolylineEntity(uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)))
    closed_path = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), closed=True
    )
    circle = CircleEntity(uuid4().hex, (20.0, 0.0), 5.0)
    counterclockwise_arc = ArcEntity(uuid4().hex, (30.0, 0.0), 5.0, 0.0, 90.0)
    clockwise_arc = ArcEntity(uuid4().hex, (40.0, 0.0), 5.0, 0.0, -90.0)
    entities: tuple[SketchEntity, ...] = (
        line,
        open_path,
        closed_path,
        circle,
        counterclockwise_arc,
        clockwise_arc,
    )

    result = offset_entities(entities, tuple(item.entity_id for item in entities), 1.0)
    offsets = result[len(entities) :]

    assert result[: len(entities)] == entities
    assert len(offsets) == len(entities)
    assert len({entity.entity_id for entity in offsets}) == len(offsets)
    assert isinstance(offsets[0], LineEntity)
    assert offsets[0].start_mm == (0.0, 1.0)
    assert offsets[0].end_mm == (10.0, 1.0)
    assert isinstance(offsets[1], PolylineEntity)
    assert offsets[1].points_mm == ((0.0, 1.0), (9.0, 1.0), (9.0, 10.0))
    assert isinstance(offsets[2], PolylineEntity)
    assert offsets[2].points_mm == ((1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0))
    assert offsets[2].closed
    assert isinstance(offsets[3], CircleEntity)
    assert offsets[3].radius_mm == 6.0
    assert isinstance(offsets[4], ArcEntity)
    assert offsets[4].radius_mm == 4.0
    assert isinstance(offsets[5], ArcEntity)
    assert offsets[5].radius_mm == 6.0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("gap_type", [0, 1, 2])
def test_offset_gap_type_outside_corner(reverse: bool, gap_type: int) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments

    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points)
    result = offset_entities(
        (source,), (source.entity_id,), 2 if reverse else -2, gap_type=gap_type
    )[1]
    assert isinstance(result, PolylineEntity)
    segments = polyline_curve_segments(
        result.points_mm,
        result.bulges or (0.0,) * (len(result.points_mm) - 1),
        False,
        result.entity_id,
    )
    assert len(segments) == (2 if gap_type == 0 else 3)
    if gap_type == 1:
        assert isinstance(segments[1], ArcEntity)
        assert segments[1].center_mm == pytest.approx((10, 0))
        assert segments[1].radius_mm == pytest.approx(2)
        assert tangent_on_curves(segments[0], segments[1])
        assert tangent_on_curves(segments[1], segments[2])
    elif gap_type == 2:
        chamfer = segments[1]
        assert isinstance(chamfer, LineEntity)
        x1, y1 = chamfer.start_mm
        x2, y2 = chamfer.end_mm
        distance = abs((x2 - x1) * (0 - y1) - (y2 - y1) * (10 - x1)) / math.dist(
            chamfer.start_mm, chamfer.end_mm
        )
        assert distance == pytest.approx(2)


@pytest.mark.parametrize("gap_type", [1, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_offset_gap_type_closed_and_inward_corner(gap_type: int, reverse: bool) -> None:
    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    source = PolylineEntity(
        uuid4().hex, tuple(reversed(points)) if reverse else points, closed=True
    )
    outward_distance = 2 if reverse else -2
    outward = offset_entities((source,), (source.entity_id,), outward_distance, gap_type=gap_type)[
        1
    ]
    assert isinstance(outward, PolylineEntity)
    assert outward.closed and len(outward.points_mm) == 8
    assert sum(bool(value) for value in outward.bulges) == (4 if gap_type == 1 else 0)
    inward = offset_entities((source,), (source.entity_id,), -outward_distance, gap_type=gap_type)[
        1
    ]
    assert isinstance(inward, PolylineEntity)
    assert inward.closed and len(inward.points_mm) == 4 and not inward.bulges
    assert {tuple(round(x, 6) for x in point) for point in inward.points_mm} == {
        (2, 2),
        (2, 8),
        (8, 2),
        (8, 8),
    }


def test_offset_gap_type_rejects_unsupported_and_invalid() -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.5, 0))
    with pytest.raises(ValueError, match="间隙模式"):
        offset_entities((source,), (source.entity_id,), 1, gap_type=3)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind", ["line_arc", "arc_arc"])
def test_offset_round_gap_joins_non_smooth_curves(kind: str, reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments

    quarter = 2**0.5 - 1
    points = (
        ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
        if kind == "line_arc"
        else ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
    )
    bulges = (0.0, quarter) if kind == "line_arc" else (quarter, quarter)
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=tuple(-value for value in reversed(bulges)) if reverse else bulges,
    )
    distance = -1 if kind == "line_arc" else 1
    result = offset_entities(
        (source,), (source.entity_id,), -distance if reverse else distance, gap_type=1
    )[1]
    assert isinstance(result, PolylineEntity)
    segments = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
    assert len(segments) == 3
    assert isinstance(segments[1], ArcEntity)
    assert segments[1].center_mm == pytest.approx((10, 0))
    assert segments[1].radius_mm == pytest.approx(1)
    assert tangent_on_curves(segments[0], segments[1])
    assert tangent_on_curves(segments[1], segments[2])


def test_offset_round_gap_result_can_be_offset_again() -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    first = offset_entities((source,), (source.entity_id,), -2, gap_type=1)[1]
    assert isinstance(first, PolylineEntity) and first.bulges
    second = offset_entities((first,), (first.entity_id,), -2, gap_type=1)[1]
    assert isinstance(second, PolylineEntity) and second.bulges
    from mycad.core.polyline_curves import polyline_curve_segments

    segments = polyline_curve_segments(second.points_mm, second.bulges, False, second.entity_id)
    assert isinstance(segments[1], ArcEntity) and segments[1].radius_mm == pytest.approx(4)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind", ["line_arc", "arc_arc"])
def test_offset_chamfer_gap_joins_non_smooth_curves(kind: str, reverse: bool) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    quarter = 2**0.5 - 1
    points = (
        ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
        if kind == "line_arc"
        else ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
    )
    bulges = (0.0, quarter) if kind == "line_arc" else (quarter, quarter)
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=tuple(-value for value in reversed(bulges)) if reverse else bulges,
    )
    distance = -1 if kind == "line_arc" else 1
    result = offset_entities(
        (source,), (source.entity_id,), -distance if reverse else distance, gap_type=2
    )[1]
    assert isinstance(result, PolylineEntity)
    segments = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
    assert len(segments) == 3 and isinstance(segments[1], LineEntity)
    chamfer = segments[1]
    x1, y1 = chamfer.start_mm
    x2, y2 = chamfer.end_mm
    separation = abs((x2 - x1) * -y1 - (y2 - y1) * (10 - x1)) / math.dist(
        chamfer.start_mm, chamfer.end_mm
    )
    assert separation == pytest.approx(1)


@pytest.mark.parametrize("reverse", [False, True])
def test_offset_round_closed_polyline_can_be_offset_again(reverse: bool) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    points = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    source = PolylineEntity(
        uuid4().hex, tuple(reversed(points)) if reverse else points, closed=True
    )
    distance = 2 if reverse else -2
    first = offset_entities((source,), (source.entity_id,), distance, gap_type=1)[1]
    assert isinstance(first, PolylineEntity)
    second = offset_entities((first,), (first.entity_id,), distance, gap_type=1)[1]
    assert isinstance(second, PolylineEntity) and second.closed
    segments = polyline_curve_segments(second.points_mm, second.bulges, True, second.entity_id)
    arcs = [segment for segment in segments if isinstance(segment, ArcEntity)]
    assert len(arcs) == 4 and all(arc.radius_mm == pytest.approx(4) for arc in arcs)


@pytest.mark.parametrize("gap_type", [1, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_offset_gap_type_preserves_major_arc_branch(gap_type: int, reverse: bool) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    points = ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    major = -(2**0.5 + 1)
    bulges = (0.0, major)
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=tuple(-value for value in reversed(bulges)) if reverse else bulges,
    )
    result = offset_entities(
        (source,), (source.entity_id,), -1 if reverse else 1, gap_type=gap_type
    )[1]
    assert isinstance(result, PolylineEntity)
    segments = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
    original_arc = segments[0] if reverse else segments[-1]
    assert isinstance(original_arc, ArcEntity)
    assert abs(original_arc.sweep_angle_deg) > 180
    assert math.copysign(1, original_arc.sweep_angle_deg) == (1 if reverse else -1)


@pytest.mark.parametrize("gap_type", [1, 2])
def test_offset_gap_type_rejects_collapsed_inner_segments(gap_type: int) -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    with pytest.raises(ValueError, match="距离过大"):
        offset_entities((source,), (source.entity_id,), 6, gap_type=gap_type)


@pytest.mark.parametrize("gap_type", [1, 2])
def test_offset_gap_type_handles_convex_and_concave_corners(gap_type: int) -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    result = offset_entities((source,), (source.entity_id,), -2, gap_type=gap_type)[1]
    assert isinstance(result, PolylineEntity)
    assert len(result.points_mm) == 5
    assert (12, 8) in result.points_mm
    assert sum(bool(value) for value in result.bulges) == (1 if gap_type == 1 else 0)


@pytest.mark.parametrize("angle", [90.0, -90.0, 45.0, 450.0])
def test_rectangular_array_angle_rotates_grid_not_source(angle: float) -> None:
    source = _line((2, 3), (3, 3), layer_name="A")
    result = sketch_edit.rectangular_array_entities(
        (source,),
        (source.entity_id,),
        rows=2,
        columns=2,
        row_spacing=-4,
        column_spacing=5,
        angle_deg=angle,
    )
    assert len(result) == 4 and result[0] == source
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for item, (row, column) in zip(result, ((0, 0), (0, 1), (1, 0), (1, 1)), strict=True):
        assert isinstance(item, LineEntity)
        shift = (column * 5 * cosine + row * 4 * sine, column * 5 * sine - row * 4 * cosine)
        assert item.start_mm == pytest.approx((2 + shift[0], 3 + shift[1]))
        assert item.end_mm == pytest.approx((3 + shift[0], 3 + shift[1]))
        assert item.layer_name == "A"


@pytest.mark.parametrize("angle", [math.inf, -math.inf, math.nan])
def test_rectangular_array_rejects_nonfinite_angle(angle: float) -> None:
    source = _line((0, 0), (1, 0))
    with pytest.raises(ValueError, match="angle"):
        sketch_edit.rectangular_array_entities(
            (source,),
            (source.entity_id,),
            rows=1,
            columns=2,
            row_spacing=0,
            column_spacing=1,
            angle_deg=angle,
        )


def test_rectangular_array_copies_independent_objects_in_rows_and_columns() -> None:
    source = _line((0, 0), (1, 0), layer_name="A")
    result = sketch_edit.rectangular_array_entities(
        (source,), (source.entity_id,), rows=2, columns=3, row_spacing=-4, column_spacing=5
    )
    assert result[0] == source and len(result) == 6
    assert len({item.entity_id for item in result}) == 6
    assert all(isinstance(item, LineEntity) and item.layer_name == "A" for item in result)
    assert {item.start_mm for item in result if isinstance(item, LineEntity)} == {
        (0, 0),
        (5, 0),
        (10, 0),
        (0, -4),
        (5, -4),
        (10, -4),
    }


@pytest.mark.parametrize(
    ("rows", "columns", "row_spacing", "column_spacing"),
    [
        (1, 1, 1, 1),
        (0, 2, 1, 1),
        (True, 2, 1, 1),
        (2, 2, 0, 1),
        (2, 2, 1, 0),
        (40, 40, 1, 1),
        (2, 2, math.inf, 1),
    ],
)
def test_rectangular_array_rejects_invalid_settings(
    rows: int, columns: int, row_spacing: float, column_spacing: float
) -> None:
    source = _line((0, 0), (1, 0))
    with pytest.raises(ValueError):
        sketch_edit.rectangular_array_entities(
            (source,),
            (source.entity_id,),
            rows=rows,
            columns=columns,
            row_spacing=row_spacing,
            column_spacing=column_spacing,
        )


@pytest.mark.parametrize(("rows", "columns"), [(1, 3), (3, 1)])
def test_rectangular_array_single_axis_does_not_require_other_spacing(
    rows: int, columns: int
) -> None:
    source = _line((0, 0), (1, 0))
    result = sketch_edit.rectangular_array_entities(
        (source,),
        (source.entity_id,),
        rows=rows,
        columns=columns,
        row_spacing=2 if rows > 1 else 0,
        column_spacing=3 if columns > 1 else 0,
    )
    assert len(result) == 3


def test_rectangular_array_caps_generated_geometry_before_creating_copies() -> None:
    sources = tuple(_line((0, index), (1, index)) for index in range(11))
    with pytest.raises(ValueError, match="10000"):
        sketch_edit.rectangular_array_entities(
            sources,
            tuple(item.entity_id for item in sources),
            rows=1,
            columns=1000,
            row_spacing=0,
            column_spacing=1,
        )
    assert len({item.entity_id for item in sources}) == 11


def test_offset_follows_signed_left_normal_and_rejects_collapsed_results() -> None:
    clockwise = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)), closed=True
    )
    outward = offset_entities((clockwise,), (clockwise.entity_id,), 1.0)[1]
    assert isinstance(outward, PolylineEntity)
    assert outward.points_mm == ((-1.0, -1.0), (-1.0, 11.0), (11.0, 11.0), (11.0, -1.0))

    counterclockwise = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), closed=True
    )
    with pytest.raises(ValueError, match="距离过大"):
        offset_entities((counterclockwise,), (counterclockwise.entity_id,), 6.0)
    with pytest.raises(ValueError, match="非零"):
        offset_entities((counterclockwise,), (counterclockwise.entity_id,), 0.0)


def test_trim_circle_at_line_intersections_keeps_the_untrimmed_major_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    first_cutter = _line((5.0, -10.0), (5.0, 10.0))
    second_cutter = _line((-5.0, -10.0), (-5.0, 10.0))

    result = trim_curve_at((circle, first_cutter, second_cutter), (0.0, 10.0), hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.entity_id == circle.entity_id
    assert trimmed.center_mm == circle.center_mm
    assert trimmed.radius_mm == circle.radius_mm
    assert trimmed.start_angle_deg == pytest.approx(120.0)
    assert trimmed.sweep_angle_deg == pytest.approx(300.0)
    assert result[1:] == (first_cutter, second_cutter)


def test_trim_circle_against_circle_intersections_keeps_complementary_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutter = CircleEntity(uuid4().hex, (10.0, 0.0), 10.0)

    result = trim_curve_at((circle, cutter), (0.0, 10.0), hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.entity_id == circle.entity_id
    assert trimmed.start_angle_deg == pytest.approx(300.0)
    assert trimmed.sweep_angle_deg == pytest.approx(120.0)
    assert result[1] == cutter


def test_trim_circle_ignores_construction_cutters() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutters = (
        _line((5.0, -10.0), (5.0, 10.0), construction=True),
        _line((-5.0, -10.0), (-5.0, 10.0), construction=True),
    )

    with pytest.raises(ValueError, match="至少需要两个唯一曲线交点"):
        trim_curve_at((circle, *cutters), (0.0, 10.0), hit_tolerance_mm=0.5)


def test_trim_circle_ignores_circle_intersections_outside_cutter_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutter = ArcEntity(uuid4().hex, (10.0, 0.0), 10.0, 100.0, 60.0)

    with pytest.raises(ValueError, match="至少需要两个唯一曲线交点"):
        trim_curve_at((circle, cutter), (0.0, 10.0), hit_tolerance_mm=0.5)


def test_trim_arc_splits_at_nearest_curve_intersections_and_preserves_direction() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 30.0, 300.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = trim_curve_at((arc, cutter), (-10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, ArcEntity)
    assert isinstance(second, ArcEntity)
    assert first.entity_id == arc.entity_id
    assert first.start_angle_deg == 30.0
    assert first.sweep_angle_deg == pytest.approx(30.0)
    assert second.entity_id != arc.entity_id
    assert second.start_angle_deg == pytest.approx(300.0)
    assert second.sweep_angle_deg == pytest.approx(30.0)
    assert result[2] == cutter


def test_trim_clockwise_arc_preserves_negative_sweep_for_both_fragments() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 330.0, -300.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = trim_curve_at((arc, cutter), (-10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, ArcEntity)
    assert isinstance(second, ArcEntity)
    assert first.entity_id == arc.entity_id
    assert first.start_angle_deg == pytest.approx(330.0)
    assert first.sweep_angle_deg == pytest.approx(-30.0)
    assert second.entity_id != arc.entity_id
    assert second.start_angle_deg == pytest.approx(60.0)
    assert second.sweep_angle_deg == pytest.approx(-30.0)


def test_trim_curve_rejects_missing_intersections_and_endpoint_clicks_without_mutation() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, -180.0)
    tangent = _line((10.0, -5.0), (10.0, 5.0))
    entities: tuple[SketchEntity, ...] = (arc, tangent)

    with pytest.raises(ValueError, match="至少需要一个内部"):
        trim_curve_at(entities, (0.0, -10.0), hit_tolerance_mm=0.5)
    assert entities == (arc, tangent)

    cutters = (_line((5.0, -10.0), (5.0, 10.0)),)
    with pytest.raises(ValueError, match="端点"):
        trim_curve_at((arc, *cutters), (10.0, 0.0), hit_tolerance_mm=0.5)


@pytest.mark.parametrize(
    ("points", "distance", "message"),
    [
        (((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), 6.0, "反转"),
        (((0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0)), 0.5, "自交"),
        (
            ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0), (5.0, 0.0)),
            1.0,
            "交叠",
        ),
        (((0.0, 0.0), (1e-10, 0.0), (10.0, 10.0)), 1.0, "过短"),
        (((0.0, 0.0), (10.0, 0.0), (0.0, 0.0), (0.0, 10.0)), 1.0, "没有唯一交点"),
    ],
)
def test_offset_open_paths_reject_reversal_crossing_short_edges_and_nonunique_corners(
    points: tuple[tuple[float, float], ...],
    distance: float,
    message: str,
) -> None:
    path = PolylineEntity(uuid4().hex, points)
    with pytest.raises(ValueError, match=message):
        offset_entities((path,), (path.entity_id,), distance)
    assert path.points_mm == points


@pytest.mark.parametrize("rectangle", [False, True])
@pytest.mark.parametrize("wrap_click", [False, True])
@pytest.mark.parametrize("split", [False, True])
def test_closed_path_edits_preserve_perimeter_order(
    rectangle: bool, wrap_click: bool, split: bool
) -> None:
    target = (
        RectangleEntity(uuid4().hex, (0.0, 0.0), (20.0, 20.0), layer_name="outline")
        if rectangle
        else PolylineEntity(
            uuid4().hex,
            ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
            closed=True,
            layer_name="outline",
        )
    )
    cutters = (_line((5.0, -2.0), (5.0, 2.0)), _line((15.0, -2.0), (15.0, 2.0)))
    long_path = ((15.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0), (5.0, 0.0))
    short_path = ((5.0, 0.0), (15.0, 0.0))
    clicked, retained = (long_path, short_path) if wrap_click else (short_path, long_path)
    operation = sketch_edit.split_entity_at if split else trim_curve_at
    result = operation(
        (target, *cutters), (0.0, 10.0) if wrap_click else (10.0, 0.0), hit_tolerance_mm=0.5
    )
    fragments = result[:-2]
    expected = (clicked, retained) if split else (retained,)
    assert len(fragments) == len(expected)
    for fragment, points in zip(fragments, expected, strict=True):
        assert isinstance(fragment, PolylineEntity)
        assert fragment.points_mm == points
        assert not fragment.closed
        assert fragment.layer_name == "outline"
    assert fragments[0].entity_id == target.entity_id
    assert len({item.entity_id for item in result}) == len(result)
    assert result[-2:] == cutters
    total_length = sum(
        math.dist(first, second)
        for points in expected
        for first, second in zip(points, points[1:], strict=False)
    )
    assert total_length == (80.0 if split else 10.0 if wrap_click else 70.0)


def test_move_preserves_rectangle_edge_order_only_when_requested() -> None:
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_edit import move_entities

    rectangle = RectangleEntity(uuid4().hex, (10, 20), (-2, -4))
    old = move_entities((rectangle,), (rectangle.entity_id,), (3, 5))[0]
    new = move_entities(
        (rectangle,), (rectangle.entity_id,), (3, 5), preserve_rectangle_order=True
    )[0]
    assert isinstance(old, RectangleEntity) and isinstance(new, RectangleEntity)
    assert old.first_corner_mm == (1, 1) and old.opposite_corner_mm == (13, 25)
    assert new.first_corner_mm == (13, 25) and new.opposite_corner_mm == (1, 1)
    assert rectangle.first_corner_mm == (10, 20)
