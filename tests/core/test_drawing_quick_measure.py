# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Quick measurements use finite geometric segments, without changing entities."""

import math
from uuid import uuid4

import pytest

from mycad.core.drawing_quick_measure import measure_line_pair
from mycad.core.sketch import LineEntity


def line(start: tuple[float, float], end: tuple[float, float]) -> LineEntity:
    return LineEntity(uuid4().hex, start, end)


def test_parallel_line_gap_uses_finite_segment_witnesses() -> None:
    first = line((0, 0), (10, 0))
    second = line((2, 4), (8, 4))
    result = measure_line_pair(first, second)
    assert result.distance_mm == pytest.approx(4)
    assert result.angle_deg == pytest.approx(0)
    assert result.first_point[1] == pytest.approx(0)
    assert result.second_point[1] == pytest.approx(4)
    assert 2 <= result.first_point[0] <= 8
    assert first.start_mm == (0, 0) and second.end_mm == (8, 4)


def test_perpendicular_segments_with_intersection_have_zero_distance() -> None:
    result = measure_line_pair(line((0, 0), (10, 0)), line((5, -2), (5, 3)))
    assert result.distance_mm == 0
    assert result.angle_deg == pytest.approx(90)
    assert result.first_point == result.second_point == pytest.approx((5, 0))


def test_disjoint_segments_do_not_measure_their_infinite_extensions() -> None:
    result = measure_line_pair(line((0, 0), (2, 0)), line((5, 4), (5, 10)))
    assert result.first_point == pytest.approx((2, 0))
    assert result.second_point == pytest.approx((5, 4))
    assert result.distance_mm == pytest.approx(5)
    assert result.angle_deg == pytest.approx(90)


def test_collinear_overlap_and_direction_reversal() -> None:
    first = line((10, 0), (0, 0))
    second = line((3, 0), (8, 0))
    result = measure_line_pair(first, second)
    assert result.distance_mm == 0
    assert result.first_point == result.second_point
    assert 3 <= result.first_point[0] <= 8
    assert result.angle_deg == pytest.approx(0)


def test_parallel_line_measurement_uses_cursor_nearby_witness() -> None:
    first = line((-1000, 0), (1000, 0))
    second = line((-1000, 10), (1000, 10))
    result = measure_line_pair(first, second, near=(50, 5))
    assert result.distance_mm == pytest.approx(10)
    assert result.first_point == pytest.approx((50, 0))
    assert result.second_point == pytest.approx((50, 10))


def test_right_angle_marker_only_for_intersecting_perpendicular_segments() -> None:
    first = line((-10, 0), (10, 0))
    second = line((0, -10), (0, 10))
    marker = measure_line_pair(first, second, near=(-2, 3)).right_angle_directions
    assert marker is not None
    assert marker[0] == pytest.approx((-1, 0))
    assert marker[1] == pytest.approx((0, 1))
    assert measure_line_pair(first, line((0, 2), (0, 10))).right_angle_directions is None
    assert measure_line_pair(first, line((-5, -5), (5, 5))).right_angle_directions is None


def test_line_circle_distance_handles_exterior_interior_and_intersection() -> None:
    from mycad.core.drawing_quick_measure import measure_line_circle
    from mycad.core.sketch import CircleEntity

    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    exterior = measure_line_circle(line((-2, 8), (2, 8)), circle)
    assert exterior.distance_mm == pytest.approx(3)
    assert exterior.first_point == pytest.approx((0, 8))
    assert exterior.second_point == pytest.approx((0, 5))
    inside = measure_line_circle(line((0, 0), (3, 0)), circle)
    assert inside.distance_mm == pytest.approx(2)
    assert inside.first_point == pytest.approx((3, 0))
    assert inside.second_point == pytest.approx((5, 0))
    crossed = measure_line_circle(line((-10, 0), (10, 0)), circle, near=(5, 0))
    assert crossed.distance_mm == 0
    assert crossed.first_point == crossed.second_point == pytest.approx((5, 0))


def test_circle_pair_distance_handles_disjoint_nested_intersection_and_concentric() -> None:
    from mycad.core.drawing_quick_measure import measure_circle_pair
    from mycad.core.sketch import CircleEntity

    first = CircleEntity(uuid4().hex, (0, 0), 5)
    for center, radius, expected in [
        ((12, 0), 2, 5),
        ((1, 0), 2, 2),
        ((6, 0), 5, 0),
        ((0, 0), 2, 3),
    ]:
        second = CircleEntity(uuid4().hex, center, radius)
        result = measure_circle_pair(first, second, near=(0, 5))
        assert result.distance_mm == pytest.approx(expected)
        assert math.dist(result.first_point, first.center_mm) == pytest.approx(first.radius_mm)
        assert math.dist(result.second_point, second.center_mm) == pytest.approx(second.radius_mm)
        assert math.dist(result.first_point, result.second_point) == pytest.approx(expected)


def test_line_arc_distance_respects_arc_sweep_endpoints_and_intersections() -> None:
    from mycad.core.drawing_quick_measure import measure_line_arc
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    tangent_side = measure_line_arc(line((8, -2), (8, 8)), arc)
    assert tangent_side.distance_mm == pytest.approx(3)
    assert tangent_side.second_point == pytest.approx((5, 0))
    end_limited = measure_line_arc(line((-10, -2), (-10, 2)), arc)
    assert end_limited.distance_mm == pytest.approx(math.sqrt(109))
    assert end_limited.second_point == pytest.approx((0, 5))
    crossed = measure_line_arc(line((3, -1), (3, 8)), arc)
    assert crossed.distance_mm == 0
    assert crossed.first_point == pytest.approx((3, 4))
    reversed_arc = ArcEntity(uuid4().hex, (0, 0), 5, 90, -90)
    assert measure_line_arc(line((8, -2), (8, 8)), reversed_arc).distance_mm == pytest.approx(3)


def test_circular_curve_pair_distance_respects_finite_arcs() -> None:
    from mycad.core.drawing_quick_measure import measure_circular_curves
    from mycad.core.sketch import ArcEntity, CircleEntity

    first = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    circle = CircleEntity(uuid4().hex, (12, 0), 2)
    assert measure_circular_curves(first, circle).distance_mm == pytest.approx(5)
    second = ArcEntity(uuid4().hex, (0, 0), 3, 180, 90)
    result = measure_circular_curves(first, second)
    assert result.distance_mm == pytest.approx(math.sqrt(34))
    overlap = ArcEntity(uuid4().hex, (0, 0), 5, 45, 90)
    assert measure_circular_curves(first, overlap).distance_mm == pytest.approx(0, abs=1e-12)
