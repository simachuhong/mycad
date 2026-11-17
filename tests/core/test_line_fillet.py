# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Finite-line fillets retain the selected sides and meet the requested radius."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import LineEntity


def test_line_fillet_trims_selected_sides_and_is_tangent() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    a, b, arc = line_fillet(first, second, (5.0, 0.0), (0.0, 5.0), 2.0, uuid4().hex)
    assert a.entity_id == first.entity_id and b.entity_id == second.entity_id
    assert a.start_mm == pytest.approx((2.0, 0.0)) and a.end_mm == first.end_mm
    assert b.start_mm == pytest.approx((0.0, 2.0)) and b.end_mm == second.end_mm
    assert arc.center_mm == pytest.approx((2.0, 2.0)) and arc.radius_mm == 2.0
    start = math.radians(arc.start_angle_deg)
    end = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert (
        arc.center_mm[0] + 2 * math.cos(start),
        arc.center_mm[1] + 2 * math.sin(start),
    ) == pytest.approx(a.start_mm)
    assert (
        arc.center_mm[0] + 2 * math.cos(end),
        arc.center_mm[1] + 2 * math.sin(end),
    ) == pytest.approx(b.start_mm)


def test_line_fillet_uses_pick_sides_for_crossing_lines() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (-10.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, -10.0), (0.0, 10.0))
    a, b, arc = line_fillet(first, second, (-5.0, 0.0), (0.0, 5.0), 2.0, uuid4().hex)
    assert a.start_mm == first.start_mm and a.end_mm == pytest.approx((-2.0, 0.0))
    assert b.start_mm == pytest.approx((0.0, 2.0)) and b.end_mm == second.end_mm
    assert arc.center_mm == pytest.approx((-2.0, 2.0))


@pytest.mark.parametrize("reverse_first", [False, True])
@pytest.mark.parametrize("reverse_second", [False, True])
def test_line_fillet_extends_disjoint_lines_to_tangency(
    reverse_first: bool, reverse_second: bool
) -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (15.0, 5.0), (15.0, 20.0))
    if reverse_first:
        first = LineEntity(first.entity_id, first.end_mm, first.start_mm)
    if reverse_second:
        second = LineEntity(second.entity_id, second.end_mm, second.start_mm)
    a, b, arc = line_fillet(first, second, (5.0, 0.0), (15.0, 10.0), 2.0, uuid4().hex)
    assert a.entity_id == first.entity_id and b.entity_id == second.entity_id
    assert (a.start_mm if reverse_first else a.end_mm) == pytest.approx((13.0, 0.0))
    assert (a.end_mm if reverse_first else a.start_mm) == (0.0, 0.0)
    assert (b.end_mm if reverse_second else b.start_mm) == pytest.approx((15.0, 2.0))
    assert (b.start_mm if reverse_second else b.end_mm) == (15.0, 20.0)
    assert arc.center_mm == pytest.approx((13.0, 2.0))


@pytest.mark.parametrize("kind", ["same", "collinear", "too_short", "large", "zero", "ambiguous"])
def test_line_fillet_rejects_unsupported_or_degenerate_input(kind: str) -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    if kind == "same":
        second = first
    elif kind == "collinear":
        second = LineEntity(uuid4().hex, (2.0, 0.0), (12.0, 0.0))
    elif kind == "too_short":
        second = LineEntity(uuid4().hex, (20.0, 1.0), (20.0, 1.1))
    radius = 20.0 if kind == "large" else 0.0 if kind == "zero" else 2.0
    pick = (0.0, 0.0) if kind == "ambiguous" else (5.0, 0.0)
    with pytest.raises(ValueError):
        line_fillet(first, second, pick, (0.0, 5.0), radius, uuid4().hex)


def test_line_fillet_keeps_construction_status_and_rejects_mixed_kinds() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0), construction=True)
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0), construction=True)
    a, b, arc = line_fillet(first, second, (5.0, 0.0), (0.0, 5.0), 2.0, uuid4().hex)
    assert a.construction and b.construction and arc.construction
    ordinary = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    with pytest.raises(ValueError, match="构造线"):
        line_fillet(first, ordinary, (5.0, 0.0), (0.0, 5.0), 2.0, uuid4().hex)


@pytest.mark.parametrize("degrees", [30.0, 45.0, 120.0, 150.0])
def test_line_fillet_is_tangent_for_acute_and_obtuse_angles(degrees: float) -> None:
    from mycad.core.line_fillet import line_fillet

    angle = math.radians(degrees)
    direction = (math.cos(angle), math.sin(angle))
    first = LineEntity(uuid4().hex, (0.0, 0.0), (100.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (100.0 * direction[0], 100.0 * direction[1]))
    a, b, arc = line_fillet(
        first, second, (50.0, 0.0), (50.0 * direction[0], 50.0 * direction[1]), 2.0, uuid4().hex
    )
    expected_distance = 2.0 / math.tan(angle / 2)
    assert a.start_mm == pytest.approx((expected_distance, 0.0))
    assert b.start_mm == pytest.approx(
        (expected_distance * direction[0], expected_distance * direction[1])
    )
    assert math.dist(a.start_mm, arc.center_mm) == pytest.approx(arc.radius_mm)
    assert math.dist(b.start_mm, arc.center_mm) == pytest.approx(arc.radius_mm)
    second_radius = (b.start_mm[0] - arc.center_mm[0], b.start_mm[1] - arc.center_mm[1])
    assert second_radius[0] * direction[0] + second_radius[1] * direction[1] == pytest.approx(
        0.0, abs=1e-8
    )


def test_zero_radius_corner_extends_lines_and_retains_picked_sides() -> None:
    from mycad.core.line_fillet import line_corner

    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (15.0, 5.0), (15.0, 20.0))
    a, b = line_corner(first, second, (5.0, 0.0), (15.0, 10.0))
    assert a.entity_id == first.entity_id and b.entity_id == second.entity_id
    assert a.start_mm == first.start_mm and a.end_mm == pytest.approx((15.0, 0.0))
    assert b.start_mm == pytest.approx((15.0, 0.0)) and b.end_mm == second.end_mm


@pytest.mark.parametrize("radius", [0.0, 1.0, 20.0])
@pytest.mark.parametrize("reverse_first", [False, True])
@pytest.mark.parametrize("reverse_second", [False, True])
@pytest.mark.parametrize("end_x", [0.0, 10.0])
def test_parallel_lines_make_semicircle_at_picked_first_end(
    radius: float, reverse_first: bool, reverse_second: bool, end_x: float
) -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (-5, 4), (15, 4))
    if reverse_first:
        first = LineEntity(first.entity_id, first.end_mm, first.start_mm)
    if reverse_second:
        second = LineEntity(second.entity_id, second.end_mm, second.start_mm)
    first_pick = (1, 0) if end_x == 0 else (9, 0)
    second_pick = (5, 4)
    a, b, arc = line_fillet(first, second, first_pick, second_pick, radius, uuid4().hex)
    assert a == first
    assert arc.radius_mm == pytest.approx(2)
    assert arc.center_mm == pytest.approx((end_x, 2))
    assert abs(arc.sweep_angle_deg) == pytest.approx(180)
    angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg / 2)
    assert arc.center_mm[0] + arc.radius_mm * math.cos(angle) == pytest.approx(
        -2 if end_x == 0 else 12
    )
    assert (end_x, 4) in (b.start_mm, b.end_mm)
    assert (15, 4) in (b.start_mm, b.end_mm) if end_x == 0 else (-5, 4) in (b.start_mm, b.end_mm)


def test_parallel_line_fillet_rotation_and_selection_order() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (3, 1), (9, 9))
    second = LineEntity(uuid4().hex, (-0.2, 3.4), (5.8, 11.4))
    a, b, arc = line_fillet(second, first, (5.2, 10.6), (6, 5), 0, uuid4().hex)
    assert a == second
    assert b.end_mm == pytest.approx((9, 9))
    assert arc.center_mm == pytest.approx((7.4, 10.2))
    assert arc.radius_mm == pytest.approx(2)
    midangle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg / 2)
    midpoint = (
        arc.center_mm[0] + 2 * math.cos(midangle),
        arc.center_mm[1] + 2 * math.sin(midangle),
    )
    assert midpoint == pytest.approx((8.6, 11.8))


def test_parallel_fillet_rejects_ambiguous_first_pick_without_modification() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 4), (10, 4))
    with pytest.raises(ValueError, match="一端"):
        line_fillet(first, second, (5, 0), (5, 4), 1, uuid4().hex)


def test_nearly_parallel_long_lines_do_not_form_false_semicircle() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0, 0), (1e9, 0))
    second = LineEntity(uuid4().hex, (0, 4), (1e9, 4.1))
    with pytest.raises(ValueError, match="近乎平行"):
        line_fillet(first, second, (9e8, 0), (5e8, 4.05), 1, uuid4().hex)


def test_parallel_tolerance_uses_gap_at_selected_end() -> None:
    from mycad.core.line_fillet import line_fillet

    first = LineEntity(uuid4().hex, (0, 0), (1e12, 0))
    second = LineEntity(uuid4().hex, (0, 4), (1e12, 4.1))
    _, trimmed, arc = line_fillet(first, second, (9e11, 0), (5e11, 4.05), 1, uuid4().hex)
    assert trimmed.end_mm == pytest.approx((1e12, 4.1))
    assert arc.radius_mm == pytest.approx(2.05)
