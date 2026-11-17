# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""FILLET joins a selected polyline branch to a standalone line."""

import math
from uuid import uuid4

import pytest

from mycad.core.polyline_fillet import polyline_line_fillet
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, PolylineEntity


@pytest.mark.parametrize("radius", [0.0, 2.0])
def test_polyline_line_fillet_joins_selected_open_branch(radius: float) -> None:
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    result = polyline_line_fillet(polyline, 0, line, (5, 0), (10, 8), radius)
    assert result.entity_id == polyline.entity_id and not result.closed
    assert result.points_mm[0] == (0, 0) and result.points_mm[-1] == (10, 10)
    if radius:
        assert result.points_mm[1] == pytest.approx((8, 0))
        assert result.points_mm[2] == pytest.approx((10, 2))
        assert result.bulges == pytest.approx((0, 2**0.5 - 1, 0))
    else:
        assert result.points_mm[1] == pytest.approx((10, 0))
        assert not result.bulges


def test_polyline_line_fillet_keeps_selected_other_branch() -> None:
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    result = polyline_line_fillet(polyline, 0, line, (17, 0), (10, 8), 2)
    assert result.points_mm[0] == (10, 10)
    assert result.points_mm[-2:] == ((20, 0), (20, -5))
    assert result.points_mm[1] == pytest.approx((10, 2))
    assert result.points_mm[2] == pytest.approx((12, 0))


def test_polyline_line_fillet_opens_closed_path_without_dropping_other_sides() -> None:
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -10), (0, -10)), True)
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    result = polyline_line_fillet(polyline, 0, line, (5, 0), (10, 8), 2)
    assert not result.closed and result.entity_id == polyline.entity_id
    assert all(point in result.points_mm for point in ((10, 0), (10, -10), (0, -10), (0, 0)))
    assert result.points_mm[-1] == (10, 10)


def test_polyline_line_fillet_rejects_impossible_radius_without_mutation() -> None:
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    with pytest.raises(ValueError):
        polyline_line_fillet(polyline, 0, line, (5, 0), (10, 8), 20)
    assert polyline.points_mm == ((0, 0), (10, 0), (10, -5)) and line.end_mm == (10, 10)


@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_polyline_circular_fillet_trims_segment_and_preserves_identity(kind: str) -> None:
    from mycad.core.polyline_fillet import polyline_circular_fillet

    source = PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (20, 10)))
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    result, target, arc, segment_index = polyline_circular_fillet(
        source, 0, circular, (-10, 0), (-2, 5), 2
    )
    assert result.entity_id == source.entity_id and result.points_mm[0] == (-20, 0)
    assert result.points_mm[-1] == pytest.approx((-math.sqrt(7), 0))
    assert segment_index == 0 and arc is not None
    assert arc.center_mm == pytest.approx((-math.sqrt(7), 2))
    if isinstance(circular, CircleEntity):
        assert target == circular
    else:
        assert isinstance(target, ArcEntity) and target != circular


def test_polyline_circle_zero_corner_uses_selected_intersection() -> None:
    from mycad.core.polyline_fillet import polyline_circular_fillet

    source = PolylineEntity(uuid4().hex, ((-10, 0), (0, 0), (0, -5)))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    result, target, arc, segment_index = polyline_circular_fillet(
        source, 0, circle, (-9, 0), (-5, 0), 0
    )
    assert result.points_mm == ((-10, 0), (-5, 0))
    assert target == circle and arc is None and segment_index == 0


@pytest.mark.parametrize("radius", [0.0, 2.0])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_two_polylines_fillet_join_selected_branches(
    radius: float, reverse_selection: bool
) -> None:
    from mycad.core.polyline_fillet import polyline_polyline_fillet

    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    second = PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (15, 10)))
    if reverse_selection:
        result = polyline_polyline_fillet(second, 0, first, 0, (10, 8), (5, 0), radius)
        assert result.entity_id == second.entity_id
        points = tuple(reversed(result.points_mm))
        bulges = tuple(-value for value in reversed(result.bulges))
    else:
        result = polyline_polyline_fillet(first, 0, second, 0, (5, 0), (10, 8), radius)
        assert result.entity_id == first.entity_id
        points, bulges = result.points_mm, result.bulges
    assert not result.closed and points[0] == (0, 0) and points[-2:] == ((10, 10), (15, 10))
    if radius:
        assert points[1] == pytest.approx((8, 0))
        assert points[2] == pytest.approx((10, 2))
        assert bulges == pytest.approx((0, 2**0.5 - 1, 0, 0))
    else:
        assert points[1] == pytest.approx((10, 0)) and not bulges


def test_two_polyline_fillet_rejects_incompatible_sources() -> None:
    from mycad.core.polyline_fillet import polyline_polyline_fillet

    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)), construction=True)
    second = PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (15, 10)))
    with pytest.raises(ValueError, match="构造"):
        polyline_polyline_fillet(first, 0, second, 0, (5, 0), (10, 8), 2)


@pytest.mark.parametrize("reverse_selection", [False, True])
def test_joined_polylines_preserve_unrelated_curved_segments(reverse_selection: bool) -> None:
    from mycad.core.polyline_fillet import polyline_polyline_fillet

    first = PolylineEntity(uuid4().hex, ((-10, -5), (0, 0), (10, 0), (10, -5)), bulges=(0.5, 0, 0))
    second = PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (15, 10)), bulges=(0, 0.4))
    if reverse_selection:
        result = polyline_polyline_fillet(second, 0, first, 1, (10, 8), (5, 0), 2)
        points = tuple(reversed(result.points_mm))
        bulges = tuple(-value for value in reversed(result.bulges))
    else:
        result = polyline_polyline_fillet(first, 1, second, 0, (5, 0), (10, 8), 2)
        points, bulges = result.points_mm, result.bulges
    assert points[0] == (-10, -5) and points[-1] == (15, 10)
    assert bulges == pytest.approx((0.5, 0, 2**0.5 - 1, 0, 0.4))


@pytest.mark.parametrize("reverse_arc", [False, True])
@pytest.mark.parametrize("pick_left", [False, True])
@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_polyline_arc_segment_circular_fillet_preserves_picked_branch(
    reverse_arc: bool, pick_left: bool, kind: str
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_circular_fillet

    points = ((-5, 0), (5, 0)) if reverse_arc else ((5, 0), (-5, 0))
    source = PolylineEntity(uuid4().hex, points, bulges=(-1 if reverse_arc else 1,))
    circular = (
        CircleEntity(uuid4().hex, (0, 8), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 8), 2, 180, 180)
    )
    pick = (-3, 4) if pick_left else (3, 4)
    result, target, fillet, index = polyline_circular_fillet(source, 0, circular, pick, (0, 6), 1)
    assert fillet is not None and result.entity_id == source.entity_id and not result.closed
    retained = polyline_arc_segment(result, index)
    assert tangent_on_curves(retained, fillet)
    assert tangent_on_curves(target, fillet)
    assert (retained.sweep_angle_deg > 0) != reverse_arc
    retained_endpoint = (-5, 0) if pick_left else (5, 0)
    assert any(math.dist(point, retained_endpoint) < 1e-8 for point in result.points_mm)
    if kind == "circle":
        assert target == circular
    else:
        assert isinstance(target, ArcEntity)


@pytest.mark.parametrize("pick_left", [False, True])
def test_polyline_arc_segment_zero_radius_trims_to_selected_intersection(pick_left: bool) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_circular_fillet

    source = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    circular = CircleEntity(uuid4().hex, (0, 7), 3)
    pick = (-3, 4) if pick_left else (3, 4)
    circle_pick = (-2, 4.8) if pick_left else (2, 4.8)
    result, target, fillet, index = polyline_circular_fillet(
        source, 0, circular, pick, circle_pick, 0
    )
    assert fillet is None and target == circular
    retained = polyline_arc_segment(result, index)
    assert 0 < retained.sweep_angle_deg < 180
    intersection = result.points_mm[0] if pick_left else result.points_mm[-1]
    assert math.dist(intersection, circular.center_mm) == pytest.approx(circular.radius_mm)
    assert (intersection[0] < 0) == pick_left


def test_polyline_arc_segment_fillet_opens_closed_path_and_keeps_other_segments() -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_circular_fillet

    source = PolylineEntity(
        uuid4().hex, ((5, 0), (-5, 0), (-5, -5), (5, -5)), True, bulges=(1, 0, 0, 0)
    )
    circular = CircleEntity(uuid4().hex, (0, 8), 2)
    result, _, fillet, index = polyline_circular_fillet(source, 0, circular, (3, 4), (0, 6), 1)
    assert not result.closed and fillet is not None
    assert all(point in result.points_mm for point in source.points_mm)
    assert tangent_on_curves(polyline_arc_segment(result, index), fillet)


@pytest.mark.parametrize("reverse_arc", [False, True])
@pytest.mark.parametrize("pick_left", [False, True])
@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_polyline_arc_segment_fillet_joins_line_and_preserves_bulges(
    reverse_arc: bool, pick_left: bool, radius: float
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_line_fillet

    points = ((-5, 0), (5, 0)) if reverse_arc else ((5, 0), (-5, 0))
    source = PolylineEntity(uuid4().hex, points, bulges=(-1 if reverse_arc else 1,))
    line = LineEntity(uuid4().hex, (-10, 3 if radius == 0 else 7), (10, 3 if radius == 0 else 7))
    source_pick = (
        ((-math.sqrt(24), 1) if pick_left else (math.sqrt(24), 1))
        if radius == 0
        else ((-3, 4) if pick_left else (3, 4))
    )
    line_pick = (-8, line.start_mm[1]) if pick_left else (8, line.start_mm[1])
    result = polyline_line_fillet(source, 0, line, source_pick, line_pick, radius)
    assert result.entity_id == source.entity_id and not result.closed
    pieces = polyline_curve_segments(
        result.points_mm, result.bulges, result.closed, result.entity_id
    )
    assert sum(isinstance(piece, ArcEntity) for piece in pieces) == (2 if radius else 1)
    assert any(
        math.dist(point, (-5, 0) if pick_left else (5, 0)) < 1e-8 for point in result.points_mm
    )
    assert any(
        math.dist(point, line.start_mm if pick_left else line.end_mm) < 1e-8
        for point in result.points_mm
    )


@pytest.mark.parametrize("second_curved", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_two_polylines_fillet_with_arc_segment(
    second_curved: bool, reverse_selection: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_polyline_fillet

    first = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    second = (
        PolylineEntity(uuid4().hex, ((-2, 8), (2, 8)), bulges=(1,))
        if second_curved
        else PolylineEntity(uuid4().hex, ((-10, 7), (10, 7)))
    )
    first_pick, second_pick = (3, 4), (0, 6) if second_curved else (8, 7)
    if reverse_selection:
        first, second = second, first
        first_pick, second_pick = second_pick, first_pick
    joined = polyline_polyline_fillet(first, 0, second, 0, first_pick, second_pick, 1)
    assert joined.entity_id == first.entity_id and not joined.closed
    parts = polyline_curve_segments(
        joined.points_mm, joined.bulges, joined.closed, joined.entity_id
    )
    assert len(parts) == 3
    assert sum(isinstance(part, ArcEntity) for part in parts) == (3 if second_curved else 2)
    from mycad.core.fillet_curves import tangent_on_curves

    assert tangent_on_curves(parts[0], parts[1])
    assert tangent_on_curves(parts[1], parts[2])


@pytest.mark.parametrize("second_curved", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_two_polylines_with_arc_segment_zero_radius_corner(
    second_curved: bool, reverse_selection: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_polyline_fillet

    first = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    second = (
        PolylineEntity(uuid4().hex, ((-3, 7), (3, 7)), bulges=(1,))
        if second_curved
        else PolylineEntity(uuid4().hex, ((-10, 3), (10, 3)))
    )
    first_pick = (3, 4) if second_curved else (math.sqrt(24), 1)
    second_pick = (2, 4.8) if second_curved else (8, 3)
    if reverse_selection:
        first, second = second, first
        first_pick, second_pick = second_pick, first_pick
    joined = polyline_polyline_fillet(first, 0, second, 0, first_pick, second_pick, 0)
    parts = polyline_curve_segments(
        joined.points_mm, joined.bulges, joined.closed, joined.entity_id
    )
    assert len(parts) == 2
    assert sum(isinstance(part, ArcEntity) for part in parts) == (2 if second_curved else 1)
