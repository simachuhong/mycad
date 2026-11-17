# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact bounded faces formed by crossing line and circle boundaries."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import CircleEntity, LineEntity


def test_circle_and_two_crossing_lines_form_four_quarters() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    lines = (
        LineEntity(uuid4().hex, (-20, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, -20), (0, 20)),
    )
    faces = build_curved_faces(lines, (circle,))
    assert len(faces) == 4
    assert [face.area_mm2 for face in faces] == pytest.approx([25 * math.pi] * 4)
    assert [face.perimeter_mm for face in faces] == pytest.approx([20 + 5 * math.pi] * 4)
    for point in ((4, 4), (-4, 4), (4, -4), (-4, -4)):
        assert sum(face.contains(point) for face in faces) == 1


def test_circle_with_overlapping_diameter_still_forms_two_faces() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    lines = (
        LineEntity(uuid4().hex, (-20, 0), (20, 0)),
        LineEntity(uuid4().hex, (5, 0), (-5, 0)),
    )
    regions = build_curved_faces(lines, (circle,))
    assert len(regions) == 2
    assert [region.area_mm2 for region in regions] == pytest.approx([50 * math.pi] * 2)


def test_crossing_circles_form_lens_and_two_crescents() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    first = CircleEntity(uuid4().hex, (-3, 0), 5)
    second = CircleEntity(uuid4().hex, (3, 0), 5)
    faces = build_curved_faces((), (first, second))
    assert len(faces) == 3
    lens = next(face for face in faces if face.contains((0, 0)))
    overlap = 50 * math.acos(0.6) - 24
    assert lens.area_mm2 == pytest.approx(overlap)
    assert lens.perimeter_mm == pytest.approx(20 * math.acos(0.6))
    for point in ((-6, 0), (6, 0)):
        assert next(face for face in faces if face.contains(point)).area_mm2 == pytest.approx(
            25 * math.pi - overlap
        )


def test_near_tangent_circles_keep_two_arc_lens() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    first = CircleEntity(uuid4().hex, (0, 0), 5)
    second = CircleEntity(uuid4().hex, (7, 7), 5)
    regions = build_curved_faces((), (first, second))
    distance = math.sqrt(98)
    expected = 50 * math.acos(distance / 10) - distance * math.sqrt(100 - distance**2) / 2
    assert len(regions) == 3
    lens = next(region for region in regions if region.contains((3.5, 3.5)))
    assert lens.area_mm2 == pytest.approx(expected)


def test_nearby_distinct_vertices_at_large_coordinates_are_not_merged() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    origin = 1e15
    circle = CircleEntity(uuid4().hex, (origin, origin), 2)
    line = LineEntity(uuid4().hex, (origin - 3, origin + 0.25), (origin + 3, origin + 0.25))
    with pytest.raises(ValueError, match="顶点过近"):
        build_curved_faces((line,), (circle,))


def test_open_arc_and_lines_form_two_exact_quarter_faces() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    diameter = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    bisector = LineEntity(uuid4().hex, (0, 0), (0, 10))
    faces = build_curved_faces((diameter, bisector), (), (arc,))
    assert len(faces) == 2
    assert [face.area_mm2 for face in faces] == pytest.approx([25 * math.pi] * 2)
    assert [face.perimeter_mm for face in faces] == pytest.approx([20 + 5 * math.pi] * 2)
    assert sum(face.contains((3, 3)) for face in faces) == 1
    assert sum(face.contains((-3, 3)) for face in faces) == 1


def test_two_arcs_with_shared_endpoints_enclose_circle() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    upper = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    lower = ArcEntity(uuid4().hex, (0, 0), 10, 180, 180)
    faces = build_curved_faces((), (), (upper, lower))
    assert len(faces) == 1
    assert faces[0].area_mm2 == pytest.approx(100 * math.pi)
    assert faces[0].perimeter_mm == pytest.approx(20 * math.pi)
    assert faces[0].contains((0, 0))


def test_partially_overlapping_reversed_arcs_are_one_boundary() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    arcs = (
        ArcEntity(uuid4().hex, (0, 0), 10, 0, 180),
        ArcEntity(uuid4().hex, (0, 0), 10, 150, -120),
    )
    diameter = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    regions = build_curved_faces((diameter,), (), arcs)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(50 * math.pi)
    assert regions[0].perimeter_mm == pytest.approx(20 + 10 * math.pi)


def test_arc_overlapping_circle_does_not_duplicate_boundary() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 25, 110)
    diameter = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    regions = build_curved_faces((diameter,), (circle,), (arc,))
    assert len(regions) == 2
    assert [region.area_mm2 for region in regions] == pytest.approx([50 * math.pi] * 2)


def test_overlapping_arcs_across_angle_zero_keep_one_small_segment() -> None:
    from mycad.core.drawing_curved_arrangement import arc_point, build_curved_faces
    from mycad.core.sketch import ArcEntity

    main = ArcEntity(uuid4().hex, (0, 0), 10, 350, 40)
    overlapping = ArcEntity(uuid4().hex, (0, 0), 10, 10, -20)
    chord = LineEntity(uuid4().hex, arc_point(main, 0), arc_point(main, 1))
    regions = build_curved_faces((chord,), (), (main, overlapping))
    theta = math.radians(40)
    assert len(regions) == 1
    assert regions[0].area_mm2 == pytest.approx(50 * (theta - math.sin(theta)))


@pytest.mark.parametrize("start,sweep", [(350.0, 40.0), (30.0, -40.0)])
def test_arc_crossing_angle_wrap_preserves_its_finite_sweep(start: float, sweep: float) -> None:
    from mycad.core.drawing_curved_arrangement import arc_point, build_curved_faces
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 10, start, sweep)
    chord = LineEntity(uuid4().hex, arc_point(arc, 0), arc_point(arc, 1))
    faces = build_curved_faces((chord,), (), (arc,))
    theta = math.radians(40)
    assert len(faces) == 1
    assert faces[0].area_mm2 == pytest.approx(50 * (theta - math.sin(theta)))
    assert faces[0].perimeter_mm == pytest.approx(10 * theta + 20 * math.sin(theta / 2))


def test_arc_tangent_to_three_rectangle_sides_forms_three_faces() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
    diameter = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    right = LineEntity(uuid4().hex, (10, 0), (10, 10))
    top = LineEntity(uuid4().hex, (10, 10), (-10, 10))
    left = LineEntity(uuid4().hex, (-10, 10), (-10, 0))
    faces = build_curved_faces((diameter, right, top, left), (), (arc,))
    assert len(faces) == 3
    assert next(face for face in faces if face.contains((0, 5))).area_mm2 == pytest.approx(
        50 * math.pi
    )
    for point in ((-9, 9), (9, 9)):
        assert next(face for face in faces if face.contains(point)).area_mm2 == pytest.approx(
            (200 - 50 * math.pi) / 2
        )


def test_circle_tangent_to_closed_semicircular_arc_forms_two_regions() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    diameter = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    circle = CircleEntity(uuid4().hex, (10, 0), 5)
    faces = build_curved_faces((diameter,), (circle,), (arc,))
    assert len(faces) == 2
    assert next(face for face in faces if face.contains((0, 2))).area_mm2 == pytest.approx(
        12.5 * math.pi
    )
    assert next(face for face in faces if face.contains((10, 0))).area_mm2 == pytest.approx(
        25 * math.pi
    )


def test_two_semicircular_arcs_meet_tangentially() -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces
    from mycad.core.sketch import ArcEntity

    arcs = (
        ArcEntity(uuid4().hex, (-5, 0), 5, 0, 180),
        ArcEntity(uuid4().hex, (5, 0), 5, 0, 180),
    )
    lines = (
        LineEntity(uuid4().hex, (-10, 0), (0, 0)),
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
    )
    faces = build_curved_faces(lines, (), arcs)
    assert len(faces) == 2
    assert [face.area_mm2 for face in faces] == pytest.approx([12.5 * math.pi] * 2)
    for point in ((-5, 2), (5, 2)):
        assert sum(face.contains(point) for face in faces) == 1


@pytest.mark.parametrize("center", [(5, 0), (1, 8)])
def test_external_tangent_circles_remain_two_separate_faces(center: tuple[int, int]) -> None:
    from mycad.core.drawing_curved_arrangement import build_curved_faces

    first = CircleEntity(uuid4().hex, (-5, 0), 5)
    second = CircleEntity(uuid4().hex, center, 5)
    regions = build_curved_faces((), (first, second))
    assert len(regions) == 2
    assert [region.area_mm2 for region in regions] == pytest.approx([25 * math.pi] * 2)
    assert sum(region.contains((-5, 0)) for region in regions) == 1
    assert sum(region.contains(center) for region in regions) == 1
