# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Zero-radius corner selection for circular curves."""

import math

import pytest

from mycad.core.curve_corner import curve_corner
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity


@pytest.mark.parametrize("end", [0.0, -7.0])
def test_line_circle_corner_trims_or_extends_line(end: float) -> None:
    line = LineEntity("11" * 16, (-10, 0), (end, 0))
    circle = CircleEntity("22" * 16, (0, 0), 5)
    result, same_circle = curve_corner(line, circle, (-9, 0), (-5, 0))
    assert isinstance(result, LineEntity)
    assert result.start_mm == (-10, 0)
    assert result.end_mm == pytest.approx((-5, 0))
    assert same_circle == circle


def test_line_arc_corner_preserves_picked_arc_side() -> None:
    line = LineEntity("11" * 16, (-10, 0), (0, 0))
    arc = ArcEntity("22" * 16, (0, 0), 5, 90, 180)
    result, trimmed = curve_corner(line, arc, (-9, 0), (0, 5))
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((-5, 0))
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.start_angle_deg == pytest.approx(90)
    assert trimmed.sweep_angle_deg == pytest.approx(90)


def test_arc_line_corner_extends_selected_arc_and_retains_identity() -> None:
    line = LineEntity("11" * 16, (-10, 0), (-7, 0))
    arc = ArcEntity("22" * 16, (0, 0), 5, 90, 45)
    extended_arc, extended_line = curve_corner(arc, line, (0, 5), (-9, 0))
    assert isinstance(extended_arc, ArcEntity) and isinstance(extended_line, LineEntity)
    assert extended_arc.entity_id == arc.entity_id
    assert extended_arc.start_angle_deg == pytest.approx(90)
    assert extended_arc.sweep_angle_deg == pytest.approx(90)
    assert extended_line.end_mm == pytest.approx((-5, 0))


def test_two_arc_corner_selects_intersection_near_both_picks() -> None:
    first = ArcEntity("11" * 16, (0, 0), 5, 0, 180)
    second = ArcEntity("22" * 16, (6, 0), 5, 0, 180)
    a, b = curve_corner(first, second, (0, 5), (6, 5))
    assert isinstance(a, ArcEntity) and isinstance(b, ArcEntity)
    assert a.start_angle_deg == pytest.approx(math.degrees(math.atan2(4, 3)))
    assert b.sweep_angle_deg == pytest.approx(math.degrees(math.atan2(4, -3)))


@pytest.mark.parametrize("circle_first", [False, True])
def test_circle_arc_corner_leaves_circle_and_trims_arc(circle_first: bool) -> None:
    circle = CircleEntity("11" * 16, (0, 0), 5)
    arc = ArcEntity("22" * 16, (6, 0), 5, 0, 180)
    if circle_first:
        unchanged, trimmed = curve_corner(circle, arc, (0, 5), (6, 5))
    else:
        trimmed, unchanged = curve_corner(arc, circle, (6, 5), (0, 5))
    assert unchanged == circle and isinstance(trimmed, ArcEntity)
    assert trimmed.start_angle_deg == pytest.approx(0)
    assert trimmed.sweep_angle_deg == pytest.approx(math.degrees(math.atan2(4, -3)))


def test_corner_without_intersection_leaves_inputs_unchanged() -> None:
    line = LineEntity("11" * 16, (-10, 0), (0, 0))
    circle = CircleEntity("22" * 16, (0, 10), 2)
    with pytest.raises(ValueError, match="交点"):
        curve_corner(line, circle, (-9, 0), (0, 12))
    assert line.end_mm == (0, 0) and circle.radius_mm == 2


def test_corner_rejects_ambiguous_intersections() -> None:
    line = LineEntity("11" * 16, (-10, 0), (10, 0))
    circle = CircleEntity("22" * 16, (0, 0), 5)
    with pytest.raises(ValueError, match="不明确"):
        curve_corner(line, circle, (0, 0), (0, 5))


def test_corner_keeps_two_circles_unchanged() -> None:
    first = CircleEntity("11" * 16, (0, 0), 5)
    second = CircleEntity("22" * 16, (6, 0), 5)
    with pytest.raises(ValueError, match="圆不需要修剪"):
        curve_corner(first, second, (0, 5), (6, 5))
    assert first.center_mm == (0, 0) and second.center_mm == (6, 0)


def test_corner_exposes_selected_contact_even_if_source_is_unchanged() -> None:
    from mycad.core.curve_corner import curve_corner_with_contact

    line = LineEntity("11" * 16, (-5, 0), (5, 0))
    circle = CircleEntity("22" * 16, (0, 0), 5)
    result, same_circle, contact = curve_corner_with_contact(line, circle, (-4, 0), (-5, 0))
    assert result == line and same_circle == circle
    assert contact == pytest.approx((-5, 0))
