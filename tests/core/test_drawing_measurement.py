# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact area for closed straight and circular polyline segments."""

import math
from uuid import uuid4

import pytest

from mycad.core.drawing_measurement import polyline_area_perimeter
from mycad.core.sketch import PolylineEntity


def test_semicircular_segment_area_and_perimeter() -> None:
    entity = PolylineEntity(
        uuid4().hex,
        ((-1, 0), (1, 0), (1, 1), (-1, 1)),
        True,
        bulges=(1, 0, 0, 0),
    )
    area, perimeter = polyline_area_perimeter(entity)
    assert area == pytest.approx(2 + math.pi / 2)
    assert perimeter == pytest.approx(4 + math.pi)


def test_self_touching_curved_boundary_is_rejected() -> None:
    entity = PolylineEntity(
        uuid4().hex,
        ((-1, 0), (1, 0), (1, 1), (-1, 1)),
        True,
        bulges=(-1, 0, 0, 0),
    )
    with pytest.raises(ValueError, match="自交|重叠"):
        polyline_area_perimeter(entity)


def test_clockwise_boundary_and_small_bulge() -> None:
    reverse = PolylineEntity(
        uuid4().hex,
        ((-1, 0), (-1, 1), (1, 1), (1, 0)),
        True,
        bulges=(0, 0, 0, -1),
    )
    assert polyline_area_perimeter(reverse) == pytest.approx((2 + math.pi / 2, 4 + math.pi))
    shallow = PolylineEntity(
        uuid4().hex,
        ((-1, 0), (1, 0), (1, 1), (-1, 1)),
        True,
        bulges=(1e-8, 0, 0, 0),
    )
    area, _ = polyline_area_perimeter(shallow)
    assert area == pytest.approx(2 + 4e-8 / 3, abs=1e-13)


def test_adjacent_quarter_arcs_form_circle_without_self_intersection() -> None:
    entity = PolylineEntity(
        uuid4().hex,
        ((1, 0), (0, 1), (-1, 0), (0, -1)),
        True,
        bulges=(math.tan(math.pi / 8),) * 4,
    )
    assert polyline_area_perimeter(entity) == pytest.approx((math.pi, 2 * math.pi))


def test_overlapping_concentric_arcs_are_rejected() -> None:
    entity = PolylineEntity(
        uuid4().hex,
        ((1, 0), (0, 1), (-1, 0), (0, -1)),
        True,
        bulges=(math.tan(math.pi / 8), -math.tan(3 * math.pi / 8), 0, 0),
    )
    with pytest.raises(ValueError, match="自交|重叠"):
        polyline_area_perimeter(entity)


def test_nearly_concentric_adjacent_arcs_are_not_overlaps() -> None:
    quarter = math.tan(math.pi / 8)
    entity = PolylineEntity(
        uuid4().hex,
        ((1, 0), (0, 1), (-1, 0), (0, -1)),
        True,
        bulges=(quarter, quarter + 1e-10, quarter, quarter),
    )
    assert polyline_area_perimeter(entity) == pytest.approx((math.pi, 2 * math.pi), abs=1e-8)


def test_crossing_near_adjacent_endpoint_is_rejected() -> None:
    entity = PolylineEntity(
        uuid4().hex,
        ((0, 0), (1, 0), (1, 2), (0, 2)),
        True,
        bulges=(-1.00000001, 0, 0, 0),
    )
    with pytest.raises(ValueError, match="自交|重叠"):
        polyline_area_perimeter(entity)


def test_nearly_concentric_nonadjacent_arcs_detect_crossing() -> None:
    from mycad.core.drawing_measurement import curve_intersections
    from mycad.core.sketch import ArcEntity

    first = ArcEntity(uuid4().hex, (0, 0), 1, 0, 270)
    second = ArcEntity(uuid4().hex, (1e-10, 0), 1, 0, 270)
    assert len(curve_intersections(first, second, None)) == 1


def test_curve_boundary_intersections_are_translation_invariant() -> None:
    origin = 1e10
    quarter = math.tan(math.pi / 8)
    valid = PolylineEntity(
        uuid4().hex,
        ((origin + 1, origin), (origin, origin + 1), (origin - 1, origin), (origin, origin - 1)),
        True,
        bulges=(quarter, quarter + 1e-5, quarter, quarter),
    )
    area, _ = polyline_area_perimeter(valid)
    assert area == pytest.approx(math.pi, abs=1e-4)
    crossed = PolylineEntity(
        uuid4().hex,
        ((origin, origin), (origin + 1, origin), (origin + 1, origin + 2), (origin, origin + 2)),
        True,
        bulges=(-1.00001, 0, 0, 0),
    )
    with pytest.raises(ValueError, match="自交|重叠"):
        polyline_area_perimeter(crossed)


def test_short_separate_segments_do_not_look_collinear() -> None:
    scale = 1e-6
    entity = PolylineEntity(
        uuid4().hex,
        ((0, 0), (2 * scale, 0), (2 * scale, 2 * scale), (0, 2 * scale), (-1, 1), (-1, 0)),
        True,
        bulges=(0, 0, 0, 0, 0, 0.1),
    )
    area, perimeter = polyline_area_perimeter(entity)
    assert area > 0
    assert perimeter > 0


def test_small_arc_and_separate_line_do_not_falsely_intersect() -> None:
    scale = 0.001
    entity = PolylineEntity(
        uuid4().hex,
        ((-scale, 0), (scale, 0), (scale, -2 * scale), (-scale, -2 * scale)),
        True,
        bulges=(1, 0, 0, 0),
    )
    area, perimeter = polyline_area_perimeter(entity)
    assert area == pytest.approx((4 - math.pi / 2) * scale**2)
    assert perimeter == pytest.approx((6 + math.pi) * scale)


def test_major_arc_uses_its_full_sweep() -> None:
    bulge = 5.0
    entity = PolylineEntity(
        uuid4().hex,
        ((-1, 0), (1, 0), (1, 1), (-1, 1)),
        True,
        bulges=(bulge, 0, 0, 0),
    )
    radius = (bulge + 1 / bulge) / 2
    theta = 4 * math.atan(bulge)
    area, perimeter = polyline_area_perimeter(entity)
    assert area == pytest.approx(2 + radius**2 * (theta - math.sin(theta)) / 2)
    assert perimeter == pytest.approx(4 + radius * theta)
