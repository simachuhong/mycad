# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Planar measurement regions retain exact spline geometry."""

from uuid import uuid4

import pytest

from mycad.core.sketch import CircleEntity, LineEntity, SplineEntity


def test_spline_and_line_region_uses_exact_curve_area_and_perimeter() -> None:
    from mycad.geom.drawing_spline_regions import build_planar_measurement_regions

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    regions = build_planar_measurement_regions((spline, line))
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(60)
    assert regions[0].perimeter_mm == pytest.approx(30)
    assert regions[0].contains((5, 2))
    assert not regions[0].contains((5, 9))
    assert not regions[0].contains((5, 0))


def test_spline_boundary_is_split_by_line_and_keeps_circle_hole() -> None:
    from mycad.geom.drawing_spline_regions import build_planar_measurement_regions

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    baseline = LineEntity(uuid4().hex, (10, 0), (0, 0))
    split = LineEntity(uuid4().hex, (5, -2), (5, 10))
    hole = CircleEntity(uuid4().hex, (2.5, 2), 0.5)
    regions = build_planar_measurement_regions((spline, baseline, split, hole))
    assert len(regions) == 3
    left = next(region for region in regions if region.contains((1.5, 2)))
    right = next(region for region in regions if region.contains((8, 2)))
    inside = next(region for region in regions if region.contains((2.5, 2)))
    import math

    assert left.area_mm2 == pytest.approx(30 - math.pi / 4)
    assert right.area_mm2 == pytest.approx(30)
    assert inside.area_mm2 == pytest.approx(math.pi / 4)


def test_open_spline_does_not_create_region() -> None:
    from mycad.geom.drawing_spline_regions import build_planar_measurement_regions

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    assert build_planar_measurement_regions((spline,)) == ()


def test_spline_selection_returns_neutral_measurement_and_boundary() -> None:
    from mycad.geom.drawing_spline_regions import measure_planar_region_at

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    region = measure_planar_region_at((spline, line), (5, 2))
    assert region is not None
    assert region.area_mm2 == pytest.approx(60)
    assert region.perimeter_mm == pytest.approx(30)
    assert len(region.boundary) >= 20
    assert region.holes == ()
    assert measure_planar_region_at((spline, line), (5, 0)) is None


def test_spline_region_display_boundary_tracks_outer_wire_and_hole() -> None:
    import math

    from mycad.geom.drawing_spline_regions import measure_planar_region_at

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 10), (10, 10), (10, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    hole = CircleEntity(uuid4().hex, (5, 2), 0.5)
    region = measure_planar_region_at((spline, line, hole), (3, 2))
    assert region is not None
    assert region.area_mm2 == pytest.approx(60 - math.pi / 4)
    assert len(region.holes) == 1

    def sampled_area(points: tuple[tuple[float, float], ...]) -> float:
        return (
            abs(
                sum(
                    a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(points, (*points[1:], points[0]), strict=True)
                )
            )
            / 2
        )

    assert sampled_area(region.boundary) == pytest.approx(60, rel=0.001)
    assert sampled_area(region.holes[0]) == pytest.approx(math.pi / 4, rel=0.001)
