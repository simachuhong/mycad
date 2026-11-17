# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fillet candidates must touch the finite arc, not its full supporting circle."""

import math
from uuid import uuid4

import pytest

from mycad.core.circle_fillet import circle_fillet_notrim
from mycad.core.line_circle_fillet import line_circle_fillet_notrim
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity


def test_line_arc_fillet_filters_candidates_outside_arc() -> None:
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    arc = ArcEntity(uuid4().hex, (0.0, 5.0), 2.0, 180.0, 90.0)
    result = line_circle_fillet_notrim(line, arc, (3.0, 0.0), (1.3, 3.5), 2.0, uuid4().hex)
    assert result.center_mm == pytest.approx((-(7.0**0.5), 2.0))


def test_two_arcs_fillet_filters_candidates_outside_arcs() -> None:
    first = ArcEntity(uuid4().hex, (0.0, 0.0), 2.0, 0.0, 90.0)
    second = ArcEntity(uuid4().hex, (10.0, 0.0), 2.0, 90.0, 90.0)
    result = circle_fillet_notrim(first, second, (1.7, -1.1), (8.3, -1.1), 4.0, uuid4().hex)
    assert result.center_mm[1] > 0


def test_tangency_check_respects_finite_entities() -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    line = LineEntity(uuid4().hex, (-5.0, 0.0), (0.0, 0.0))
    touching = ArcEntity(uuid4().hex, (0.0, 2.0), 2.0, 180.0, 90.0)
    outside = ArcEntity(uuid4().hex, (0.0, 2.0), 2.0, 0.0, 90.0)
    assert tangent_on_curves(line, touching)
    assert not tangent_on_curves(line, outside)
    short = LineEntity(uuid4().hex, (-5.0, 0.0), (-1.0, 0.0))
    assert not tangent_on_curves(short, touching)


def test_two_circles_fillet_can_choose_internal_tangency() -> None:
    first = CircleEntity(uuid4().hex, (0.0, 0.0), 5.0)
    second = CircleEntity(uuid4().hex, (6.0, 0.0), 2.0)
    result = circle_fillet_notrim(first, second, (4.03, 2.96), (4.21, 0.89), 2.0, uuid4().hex)
    assert result.center_mm[0] == pytest.approx(29.0 / 12.0)
    assert result.center_mm[1] > 0
    assert math.dist(result.center_mm, first.center_mm) == pytest.approx(3.0)
    assert math.dist(result.center_mm, second.center_mm) == pytest.approx(4.0)


@pytest.mark.parametrize("sweep", [90.0, -90.0])
@pytest.mark.parametrize("retain_start", [False, True])
def test_trim_arc_retains_the_picked_side(sweep: float, retain_start: bool) -> None:
    from mycad.core.fillet_curves import trim_arc_at_contact

    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, sweep)
    contact_angle = math.radians(sweep / 2)
    pick_angle = math.radians(sweep * (0.25 if retain_start else 0.75))
    contact = (10 * math.cos(contact_angle), 10 * math.sin(contact_angle))
    pick = (10 * math.cos(pick_angle), 10 * math.sin(pick_angle))
    result = trim_arc_at_contact(arc, contact, pick)
    assert result.entity_id == arc.entity_id
    assert result.start_angle_deg == pytest.approx(0.0 if retain_start else sweep / 2)
    assert result.sweep_angle_deg == pytest.approx(sweep / 2)


def test_trim_arc_rejects_contact_on_wrong_radius() -> None:
    from mycad.core.fillet_curves import trim_arc_at_contact

    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    with pytest.raises(ValueError):
        trim_arc_at_contact(arc, (1.0, 1.0), (10.0, 0.0))


@pytest.mark.parametrize("sweep", [90.0, -90.0])
@pytest.mark.parametrize("extend_start", [False, True])
def test_arc_extends_to_contact_retaining_original_span(sweep: float, extend_start: bool) -> None:
    from mycad.core.fillet_curves import trim_arc_at_contact

    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, sweep)
    angle = math.radians((-30.0 if extend_start else 120.0) * math.copysign(1, sweep))
    pick = math.radians(sweep / 2)
    result = trim_arc_at_contact(
        arc,
        (10 * math.cos(angle), 10 * math.sin(angle)),
        (10 * math.cos(pick), 10 * math.sin(pick)),
    )
    assert result.entity_id == arc.entity_id
    assert result.start_angle_deg == pytest.approx(
        -30 * math.copysign(1, sweep) if extend_start else 0
    )
    assert result.sweep_angle_deg == pytest.approx(120 * math.copysign(1, sweep))


def test_arc_extension_rejects_equally_short_directions() -> None:
    from mycad.core.fillet_curves import trim_arc_at_contact

    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    angle = math.radians(225)
    with pytest.raises(ValueError, match="方向"):
        trim_arc_at_contact(arc, (10 * math.cos(angle), 10 * math.sin(angle)), (10, 0))


def test_line_arc_fillet_can_extend_arc_only_in_trim_mode() -> None:
    from mycad.core.fillet_curves import trim_arc_at_contact
    from mycad.core.line_circle_fillet import line_circle_fillet_trim

    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    source = ArcEntity(uuid4().hex, (0, 5), 2, 180, 30)
    line_pick, arc_pick = (-3.0, 0.0), (-1.93, 4.48)
    with pytest.raises(ValueError):
        line_circle_fillet_notrim(line, source, line_pick, arc_pick, 2.0, uuid4().hex)
    _trimmed_line, arc = line_circle_fillet_trim(
        line, source, line_pick, arc_pick, 2.0, uuid4().hex
    )
    angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    contact = (
        arc.center_mm[0] + arc.radius_mm * math.cos(angle),
        arc.center_mm[1] + arc.radius_mm * math.sin(angle),
    )
    extended = trim_arc_at_contact(source, contact, arc_pick)
    assert extended.entity_id == source.entity_id
    assert extended.sweep_angle_deg > source.sweep_angle_deg


def test_two_arc_fillet_can_extend_both_arcs() -> None:
    first = ArcEntity(uuid4().hex, (0, 0), 2, 0, 20)
    second = ArcEntity(uuid4().hex, (10, 0), 2, 90, 30)
    first_pick = (2 * math.cos(math.radians(10)), 2 * math.sin(math.radians(10)))
    second_pick = (10 + 2 * math.cos(math.radians(105)), 2 * math.sin(math.radians(105)))
    with pytest.raises(ValueError):
        circle_fillet_notrim(first, second, first_pick, second_pick, 4, uuid4().hex)
    result = circle_fillet_notrim(
        first, second, first_pick, second_pick, 4, uuid4().hex, extend_arcs=True
    )
    assert result.center_mm[0] == pytest.approx(5)
    assert result.center_mm[1] > 0
