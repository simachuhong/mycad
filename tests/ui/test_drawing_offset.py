# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Side selection for interactive 2D offset."""

import math

import pytest

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity
from mycad.ui.drawing_offset import signed_offset_distance


def test_curved_polyline_offset_side_and_through_use_arc() -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.drawing_offset import through_offset_distance

    path = PolylineEntity(
        "44444444444444448444444444444444",
        ((-5, 0), (0, 5), (5, 5)),
        bulges=(-math.tan(math.pi / 8), 0),
    )
    outer = (-6 / math.sqrt(2), 6 / math.sqrt(2))
    inner = (-4 / math.sqrt(2), 4 / math.sqrt(2))
    assert signed_offset_distance(path, outer, 1) == pytest.approx(1)
    assert signed_offset_distance(path, inner, 1) == pytest.approx(-1)
    assert through_offset_distance(path, outer) == pytest.approx(1)
    assert through_offset_distance(path, inner) == pytest.approx(-1)


@pytest.mark.parametrize(
    ("entity", "point", "expected"),
    [
        (LineEntity("11111111111141118111111111111111", (0, 0), (10, 0)), (5, 3), 2),
        (LineEntity("11111111111141118111111111111111", (10, 0), (0, 0)), (5, 3), -2),
        (CircleEntity("22222222222242228222222222222222", (0, 0), 5), (8, 0), 2),
        (CircleEntity("22222222222242228222222222222222", (0, 0), 5), (2, 0), -2),
        (ArcEntity("33333333333343338333333333333333", (0, 0), 5, 0, 90), (8, 0), -2),
        (ArcEntity("33333333333343338333333333333333", (0, 0), 5, 0, -90), (8, 0), 2),
    ],
)
def test_side_uses_entity_orientation(
    entity: object, point: tuple[float, float], expected: int
) -> None:
    assert signed_offset_distance(entity, point, 2) == expected


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf")])
def test_distance_must_be_finite_positive(distance: float) -> None:
    with pytest.raises(ValueError):
        signed_offset_distance(
            LineEntity("11111111111141118111111111111111", (0, 0), (10, 0)), (0, 1), distance
        )


def test_side_on_object_is_ambiguous() -> None:
    with pytest.raises(ValueError):
        signed_offset_distance(
            LineEntity("11111111111141118111111111111111", (0, 0), (10, 0)), (5, 0), 2
        )


def test_polyline_side_follows_nearest_segment_and_rejects_ambiguous_corner() -> None:
    from mycad.core.sketch import PolylineEntity

    entity = PolylineEntity("44444444444444448444444444444444", ((0, 0), (10, 0), (10, 10)))
    assert signed_offset_distance(entity, (5, 3), 2) == 2
    assert signed_offset_distance(entity, (13, 5), 2) == -2
    with pytest.raises(ValueError):
        signed_offset_distance(entity, (11, -1), 2)


def test_rectangle_side_respects_corner_order() -> None:
    from mycad.core.sketch import RectangleEntity

    entity = RectangleEntity("55555555555545558555555555555555", (0, 0), (10, 10))
    assert signed_offset_distance(entity, (5, 2), 1) == 1
    assert signed_offset_distance(entity, (5, -2), 1) == -1


@pytest.mark.parametrize("sweep", [90.0, -90.0])
def test_arc_side_produces_expected_radius_using_real_offset_algorithm(sweep: float) -> None:
    from mycad.core.sketch_edit import offset_entities

    arc = ArcEntity("66666666666646668666666666666666", (0, 0), 5, 0, sweep)
    outer = signed_offset_distance(arc, (8, 0), 2)
    inner = signed_offset_distance(arc, (2, 0), 2)
    outer_copy = offset_entities((arc,), (arc.entity_id,), outer)[1]
    inner_copy = offset_entities((arc,), (arc.entity_id,), inner)[1]
    assert isinstance(outer_copy, ArcEntity) and outer_copy.radius_mm == pytest.approx(7)
    assert isinstance(inner_copy, ArcEntity) and inner_copy.radius_mm == pytest.approx(3)


def test_side_rejects_nonfinite_intermediate_geometry() -> None:
    line = LineEntity("77777777777747778777777777777777", (0, 0), (1e200, 1e200))
    with pytest.raises(ValueError):
        signed_offset_distance(line, (1e200, -1e200), 1)


@pytest.mark.parametrize(
    ("entity", "point", "expected"),
    [
        (LineEntity("11111111111141118111111111111111", (0, 0), (10, 0)), (5, 3), 3),
        (LineEntity("11111111111141118111111111111111", (10, 0), (0, 0)), (5, 3), -3),
        (CircleEntity("22222222222242228222222222222222", (0, 0), 5), (8, 0), 3),
        (CircleEntity("22222222222242228222222222222222", (0, 0), 5), (2, 0), -3),
        (ArcEntity("33333333333343338333333333333333", (0, 0), 5, 0, 90), (8, 0), -3),
    ],
)
def test_through_point_resolves_signed_distance(
    entity: object, point: tuple[float, float], expected: float
) -> None:
    from mycad.ui.drawing_offset import through_offset_distance

    assert through_offset_distance(entity, point) == pytest.approx(expected)


def test_through_point_rejects_outside_arc_and_ambiguous_source() -> None:
    from mycad.ui.drawing_offset import through_offset_distance

    arc = ArcEntity("33333333333343338333333333333333", (0, 0), 5, 0, 90)
    with pytest.raises(ValueError):
        through_offset_distance(arc, (-8, 0))
    with pytest.raises(ValueError):
        through_offset_distance(arc, (5, 0))
    line = LineEntity("11111111111141118111111111111111", (0, 0), (10, 0))
    with pytest.raises(ValueError):
        through_offset_distance(line, (15, 3))


def test_through_point_supports_unambiguous_polyline_and_rectangle() -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.drawing_offset import through_offset_distance

    polyline = PolylineEntity("44444444444444448444444444444444", ((0, 0), (10, 0), (10, 10)))
    rectangle = RectangleEntity("55555555555545558555555555555555", (0, 0), (10, 10))
    assert through_offset_distance(polyline, (5, 2)) == pytest.approx(2)
    assert through_offset_distance(rectangle, (5, -2)) == pytest.approx(-2)
    with pytest.raises(ValueError):
        through_offset_distance(polyline, (11, -1))
