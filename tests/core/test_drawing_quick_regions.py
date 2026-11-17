# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded faces of linear drawing networks for read-only measurement."""

from uuid import uuid4

import pytest

from mycad.core.drawing_quick_regions import build_linear_regions
from mycad.core.sketch import LineEntity


def segment(a: tuple[float, float], b: tuple[float, float]) -> LineEntity:
    return LineEntity(uuid4().hex, a, b)


def rectangle(x1: float, y1: float, x2: float, y2: float) -> tuple[LineEntity, ...]:
    points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    return tuple(segment(a, b) for a, b in zip(points, (*points[1:], points[0]), strict=True))


def test_rectangle_and_intersection_produce_independent_faces() -> None:
    lines = (*rectangle(0, 0, 10, 6), segment((4, 0), (4, 6)))
    regions = build_linear_regions(lines)
    assert sorted(r.area_mm2 for r in regions) == pytest.approx([24, 36])
    assert sorted(r.perimeter_mm for r in regions) == pytest.approx([20, 24])
    assert sum(r.contains((2, 3)) for r in regions) == 1
    assert sum(r.contains((7, 3)) for r in regions) == 1
    assert not any(r.contains((11, 3)) for r in regions)


def test_nested_boundaries_form_hole_and_inner_region() -> None:
    regions = build_linear_regions((*rectangle(0, 0, 10, 10), *rectangle(2, 2, 4, 4)))
    assert sorted(r.area_mm2 for r in regions) == pytest.approx([4, 96])
    outside_hole = next(r for r in regions if r.contains((1, 1)))
    inner = next(r for r in regions if r.contains((3, 3)))
    assert outside_hole.perimeter_mm == pytest.approx(48)
    assert inner.perimeter_mm == pytest.approx(8)
    assert not outside_hole.contains((3, 3))
    assert not outside_hole.contains((2, 3))
    assert not inner.contains((2, 3))


def test_open_and_overlapping_linework_do_not_create_false_region() -> None:
    assert build_linear_regions((segment((0, 0), (1, 0)),)) == ()
    assert build_linear_regions((segment((0, 0), (10, 0)), segment((5, 0), (15, 0)))) == ()


def test_overlapping_straight_boundaries_form_one_region() -> None:
    lines = (*rectangle(0, 0, 10, 10), segment((8, 0), (2, 0)), segment((0, 0), (10, 0)))
    regions = build_linear_regions(lines)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(100)
    assert regions[0].perimeter_mm == pytest.approx(40)


def test_overlapping_diagonal_segments_preserve_triangle() -> None:
    lines = (
        segment((0, 0), (10, 10)),
        segment((8, 8), (2, 2)),
        segment((0, 0), (10, 0)),
        segment((10, 0), (10, 10)),
    )
    regions = build_linear_regions(lines)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(50)


def test_duplicate_circles_are_counted_once() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    circles = (CircleEntity(uuid4().hex, (0, 0), 5), CircleEntity(uuid4().hex, (0, 0), 5))
    regions = build_quick_regions((), circles)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(25 * math.pi)


def test_small_region_at_large_coordinates_and_open_spur() -> None:
    origin = 1e15
    lines = (
        *rectangle(origin, origin, origin + 1, origin + 2),
        segment((origin + 1, origin + 1), (origin + 3, origin + 1)),
    )
    regions = build_linear_regions(lines)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(2)
    assert regions[0].perimeter_mm == pytest.approx(6)
    assert regions[0].contains((origin + 0.5, origin + 1))


def test_circles_and_mixed_nested_regions_preserve_holes() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    outer = CircleEntity(uuid4().hex, (0, 0), 10)
    inner = CircleEntity(uuid4().hex, (0, 0), 2)
    regions = build_quick_regions((), (outer, inner))
    annulus = next(r for r in regions if r.contains((5, 0)))
    assert annulus.area_mm2 == pytest.approx(96 * math.pi)
    assert annulus.perimeter_mm == pytest.approx(24 * math.pi)
    assert not annulus.contains((0, 0))
    assert next(r for r in regions if r.contains((0, 0))).area_mm2 == pytest.approx(4 * math.pi)
    regions = build_quick_regions(rectangle(-5, -5, 5, 5), (inner,))
    outside_circle = next(r for r in regions if r.contains((4, 0)))
    assert outside_circle.area_mm2 == pytest.approx(100 - 4 * math.pi)
    assert outside_circle.perimeter_mm == pytest.approx(40 + 4 * math.pi)
    assert not outside_circle.contains((0, 0))
    regions = build_quick_regions(rectangle(-2, -2, 2, 2), (outer,))
    outside_rectangle = next(r for r in regions if r.contains((5, 0)))
    assert outside_rectangle.area_mm2 == pytest.approx(100 * math.pi - 16)
    assert outside_rectangle.perimeter_mm == pytest.approx(20 * math.pi + 16)


def test_circle_inscribed_in_square_forms_five_regions() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    regions = build_quick_regions(rectangle(0, 0, 10, 10), (circle,))
    assert len(regions) == 5
    assert next(region for region in regions if region.contains((5, 5))).area_mm2 == pytest.approx(
        25 * math.pi
    )
    for point in ((0.5, 0.5), (9.5, 0.5), (0.5, 9.5), (9.5, 9.5)):
        assert next(
            region for region in regions if region.contains(point)
        ).area_mm2 == pytest.approx((100 - 25 * math.pi) / 4)


def test_internal_tangent_circles_form_annulus_and_inner_region() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    outer = CircleEntity(uuid4().hex, (0, 0), 5)
    inner = CircleEntity(uuid4().hex, (3, 0), 2)
    regions = build_quick_regions((), (outer, inner))
    assert len(regions) == 2
    annulus = next(region for region in regions if region.contains((0, 0)))
    assert annulus.area_mm2 == pytest.approx(21 * math.pi)
    assert annulus.perimeter_mm == pytest.approx(14 * math.pi)
    assert not annulus.contains((3, 0))
    assert next(region for region in regions if region.contains((3, 0))).area_mm2 == pytest.approx(
        4 * math.pi
    )
    assert not any(region.contains((5, 0)) for region in regions)


def test_three_internally_tangent_circles_preserve_nested_regions() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    circles = tuple(
        CircleEntity(uuid4().hex, (center, 0), radius)
        for center, radius in ((0, 10), (5, 5), (7, 3))
    )
    regions = build_quick_regions((), circles)
    assert len(regions) == 3
    for point, area in (((-5, 0), 75 * math.pi), ((2, 0), 16 * math.pi), ((7, 0), 9 * math.pi)):
        matches = [region for region in regions if region.contains(point)]
        assert len(matches) == 1
        assert matches[0].area_mm2 == pytest.approx(area)


def test_circle_split_by_lines_and_nested_circle() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    outer = CircleEntity(uuid4().hex, (0, 0), 10)
    inner = CircleEntity(uuid4().hex, (4, 4), 1)
    lines = (segment((-20, 0), (20, 0)), segment((0, -20), (0, 20)))
    regions = build_quick_regions(lines, (outer, inner))
    assert len(regions) == 5
    first_quadrant = next(region for region in regions if region.contains((2, 2)))
    assert first_quadrant.area_mm2 == pytest.approx(24 * math.pi)
    assert first_quadrant.perimeter_mm == pytest.approx(20 + 7 * math.pi)
    assert next(region for region in regions if region.contains((4, 4))).area_mm2 == pytest.approx(
        math.pi
    )


def test_crossing_circle_and_square_form_nine_distinct_regions() -> None:
    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity

    circle = CircleEntity(uuid4().hex, (5, 5), 6)
    regions = build_quick_regions(rectangle(0, 0, 10, 10), (circle,))
    assert len(regions) == 9
    for point in ((5, 5), (0.2, 0.2), (5, -0.5), (10.5, 5)):
        assert sum(region.contains(point) for region in regions) == 1


def test_independent_arc_participates_in_region_construction() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    lines = (segment((-10, 0), (10, 0)), segment((0, 0), (0, 10)))
    regions = build_quick_regions(lines, (), (), (arc,))
    assert len(regions) == 2
    assert next(region for region in regions if region.contains((3, 3))).area_mm2 == pytest.approx(
        25 * math.pi
    )


def test_open_bulged_polyline_can_close_region_with_line() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import PolylineEntity

    arc = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0)), False, bulges=(-1.0,))
    regions = build_quick_regions((segment((-10, 0), (10, 0)),), (), (), (), (arc,))
    assert len(regions) == 1
    assert regions[0].contains((0, 5))
    assert regions[0].area_mm2 == pytest.approx(50 * math.pi)


def test_open_bulged_polyline_uses_authored_non_cardinal_endpoints() -> None:
    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import PolylineEntity

    first, second = (1.3, 2.2), (7.1, 4.4)
    arc = PolylineEntity(uuid4().hex, (first, second), False, bulges=(0.5,))
    regions = build_quick_regions((segment(first, second),), (), (), (), (arc,))
    assert len(regions) == 1
    assert regions[0].area_mm2 > 0


def test_curved_polyline_region_uses_exact_area_and_nested_hole() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import PolylineEntity

    curved = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (2, 0), (2, 2), (-2, 2)),
        True,
        bulges=(1.0, 0.0, 0.0, 0.0),
    )
    regions = build_quick_regions(rectangle(-5, -5, 5, 5), (), (curved,))
    inner = next(region for region in regions if region.contains((0, -1)))
    outer = next(region for region in regions if region.contains((4, 0)))
    assert inner.area_mm2 == pytest.approx(8 + 2 * math.pi)
    assert inner.perimeter_mm == pytest.approx(8 + 2 * math.pi)
    assert outer.area_mm2 == pytest.approx(92 - 2 * math.pi)
    assert not outer.contains((0, -1))
    assert not any(region.contains((0, -2)) for region in regions)

    reversed_curve = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (-2, 2), (2, 2), (2, 0)),
        True,
        bulges=(0.0, 0.0, 0.0, -1.0),
    )
    reversed_region = build_quick_regions((), (), (reversed_curve,))[0]
    assert reversed_region.contains((0, -1))
    assert not reversed_region.contains((0, -2))
    assert reversed_region.area_mm2 == pytest.approx(inner.area_mm2)


def test_curved_polyline_crossing_line_forms_two_regions() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import PolylineEntity

    curved = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (2, 0), (2, 2), (-2, 2)),
        True,
        bulges=(1.0, 0.0, 0.0, 0.0),
    )
    regions = build_quick_regions((segment((0, -3), (0, 3)),), (), (curved,))
    assert len(regions) == 2
    assert sorted(region.area_mm2 for region in regions) == pytest.approx([4 + math.pi] * 2)
    assert sorted(region.perimeter_mm for region in regions) == pytest.approx([8 + math.pi] * 2)
    assert sum(region.contains((-1, 0)) for region in regions) == 1
    assert sum(region.contains((1, 0)) for region in regions) == 1


def test_curved_polyline_crossing_circle_creates_three_regions() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity, PolylineEntity

    curved = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (2, 0), (2, 2), (-2, 2)),
        True,
        bulges=(1.0, 0.0, 0.0, 0.0),
    )
    circle = CircleEntity(uuid4().hex, (0, 2), 1)
    regions = build_quick_regions((), (circle,), (curved,))
    assert len(regions) == 3
    assert next(
        region for region in regions if region.contains((0, 1.5))
    ).area_mm2 == pytest.approx(math.pi / 2)
    assert next(
        region for region in regions if region.contains((0, 2.5))
    ).area_mm2 == pytest.approx(math.pi / 2)
    assert next(region for region in regions if region.contains((-1, 0))).area_mm2 == pytest.approx(
        8 + 1.5 * math.pi
    )


def test_two_crossing_closed_curved_polylines_form_lens() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import PolylineEntity

    bulge = math.tan(math.pi / 8)

    def disk(x: float) -> PolylineEntity:
        return PolylineEntity(
            uuid4().hex,
            ((x - 5, 0), (x, 5), (x + 5, 0)),
            True,
            bulges=(-bulge, -bulge, -1),
        )

    regions = build_quick_regions((), (), (disk(-3), disk(3)))
    assert len(regions) == 3
    lens = next(region for region in regions if region.contains((0, 0)))
    assert lens.area_mm2 == pytest.approx(50 * math.acos(0.6) - 24)


def test_major_arc_containment_and_nested_circle() -> None:
    import math

    from mycad.core.drawing_quick_regions import build_quick_regions
    from mycad.core.sketch import CircleEntity, PolylineEntity

    curved = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (2, 0), (2, 2), (-2, 2)),
        True,
        bulges=(2.0, 0.0, 0.0, 0.0),
    )
    circle = CircleEntity(uuid4().hex, (0, -1), 0.25)
    regions = build_quick_regions((), (circle,), (curved,))
    outside_hole = next(region for region in regions if region.contains((0, -3)))
    theta = 4 * math.atan(2)
    radius = 2.5
    expected = 8 + radius**2 * (theta - math.sin(theta)) / 2
    assert outside_hole.area_mm2 == pytest.approx(expected - math.pi * 0.25**2)
    assert not outside_hole.contains(circle.center_mm)
    assert not outside_hole.contains((0, -4))
