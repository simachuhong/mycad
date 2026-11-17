# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Line/circle external fillets retain both source entities."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import CircleEntity, LineEntity


@pytest.mark.parametrize("reverse_line", [False, True])
@pytest.mark.parametrize("side", [-1, 1])
def test_line_circle_fillet_is_tangent_and_uses_picked_side(reverse_line: bool, side: int) -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_notrim

    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    if reverse_line:
        line = LineEntity(line.entity_id, line.end_mm, line.start_mm)
    circle = CircleEntity(uuid4().hex, (0.0, 5.0), 2.0)
    arc = line_circle_fillet_notrim(
        line, circle, (side * 3.0, 0.0), (side * 1.3, 3.5), 2.0, uuid4().hex
    )
    assert arc.center_mm == pytest.approx((side * math.sqrt(7.0), 2.0))
    assert arc.radius_mm == 2.0
    assert math.dist(arc.center_mm, circle.center_mm) == pytest.approx(4.0)
    start = math.radians(arc.start_angle_deg)
    end = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert arc.center_mm[1] + 2.0 * math.sin(start) == pytest.approx(0.0)
    contact = (arc.center_mm[0] + 2.0 * math.cos(end), arc.center_mm[1] + 2.0 * math.sin(end))
    assert math.dist(contact, circle.center_mm) == pytest.approx(circle.radius_mm)


def test_line_circle_fillet_preserves_construction_and_rejects_mixed_types() -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_notrim

    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0), construction=True)
    circle = CircleEntity(uuid4().hex, (0.0, 5.0), 2.0, construction=True)
    args = (line, circle, (-3.0, 0.0), (-1.3, 3.5), 2.0, uuid4().hex)
    assert line_circle_fillet_notrim(*args, layer_name="custom").construction
    assert line_circle_fillet_notrim(*args, layer_name="custom").layer_name == "custom"
    ordinary = CircleEntity(circle.entity_id, circle.center_mm, circle.radius_mm)
    with pytest.raises(ValueError, match="构造线"):
        line_circle_fillet_notrim(line, ordinary, (-3.0, 0.0), (-1.3, 3.5), 2.0, uuid4().hex)


@pytest.mark.parametrize("reverse_line", [False, True])
def test_line_circle_fillet_trims_line_on_picked_side(reverse_line: bool) -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_trim

    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    if reverse_line:
        line = LineEntity(line.entity_id, line.end_mm, line.start_mm)
    circle = CircleEntity(uuid4().hex, (0.0, 5.0), 2.0)
    trimmed, arc = line_circle_fillet_trim(
        line, circle, (-10.0, 0.0), (-1.3, 3.5), 2.0, uuid4().hex
    )
    assert trimmed.entity_id == line.entity_id
    assert (trimmed.end_mm if reverse_line else trimmed.start_mm) == (-20.0, 0.0)
    assert (trimmed.start_mm if reverse_line else trimmed.end_mm) == pytest.approx(
        (-math.sqrt(7), 0.0)
    )
    assert arc.center_mm == pytest.approx((-math.sqrt(7), 2.0))


@pytest.mark.parametrize("reverse_line", [False, True])
def test_line_circle_fillet_extends_line_to_external_tangent(reverse_line: bool) -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_trim

    line = LineEntity(uuid4().hex, (-20.0, 0.0), (-5.0, 0.0))
    if reverse_line:
        line = LineEntity(line.entity_id, line.end_mm, line.start_mm)
    circle = CircleEntity(uuid4().hex, (0.0, 5.0), 2.0)
    trimmed, arc = line_circle_fillet_trim(
        line, circle, (-10.0, 0.0), (-1.3, 3.5), 2.0, uuid4().hex
    )
    assert (trimmed.end_mm if reverse_line else trimmed.start_mm) == (-20.0, 0.0)
    assert (trimmed.start_mm if reverse_line else trimmed.end_mm) == pytest.approx(
        (-math.sqrt(7), 0.0)
    )
    assert arc.center_mm == pytest.approx((-math.sqrt(7), 2.0))


def test_line_circle_fillet_selects_internal_tangency() -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_trim

    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    circle = CircleEntity(uuid4().hex, (0.0, 4.0), 5.0)
    trimmed, arc = line_circle_fillet_trim(
        line, circle, (-3.0, 0.0), (-3.73, 0.67), 2.0, uuid4().hex
    )
    assert arc.center_mm == pytest.approx((-math.sqrt(5), 2.0))
    assert math.dist(arc.center_mm, circle.center_mm) == pytest.approx(
        circle.radius_mm - arc.radius_mm
    )
    assert trimmed.end_mm == pytest.approx((-math.sqrt(5), 0.0))


@pytest.mark.parametrize("case", ["short", "impossible", "ambiguous", "zero"])
def test_line_circle_fillet_rejects_unsupported_input(case: str) -> None:
    from mycad.core.line_circle_fillet import line_circle_fillet_notrim

    line = (
        LineEntity(uuid4().hex, (-1.0, 0.0), (1.0, 0.0))
        if case == "short"
        else LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    )
    circle = CircleEntity(uuid4().hex, (0.0, 20.0 if case == "impossible" else 5.0), 2.0)
    pick = (0.0, 0.0) if case == "ambiguous" else (-3.0, 0.0)
    circle_pick = (0.0, 3.0) if case == "ambiguous" else (-1.3, 3.5)
    with pytest.raises(ValueError):
        line_circle_fillet_notrim(
            line, circle, pick, circle_pick, 0.0 if case == "zero" else 2.0, uuid4().hex
        )
