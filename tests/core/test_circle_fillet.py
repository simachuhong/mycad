# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Two-circle fillets retain their inputs and use the chosen side."""

import math
from uuid import uuid4

import pytest

from mycad.core.circle_fillet import circle_fillet_notrim
from mycad.core.sketch import CircleEntity


@pytest.mark.parametrize("side", [1, -1])
def test_external_fillet_is_tangent_and_follows_picks(side: int) -> None:
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    arc = circle_fillet_notrim(first, second, (2, side), (8, side), 4, uuid4().hex)
    assert arc.center_mm == pytest.approx((5, side * math.sqrt(11)))
    assert arc.radius_mm == 4
    for angle, circle in (
        (arc.start_angle_deg, first),
        (arc.start_angle_deg + arc.sweep_angle_deg, second),
    ):
        point = (
            arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(angle)),
            arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(angle)),
        )
        assert math.dist(point, circle.center_mm) == pytest.approx(circle.radius_mm)
    assert first.center_mm == (0, 0) and second.center_mm == (10, 0)


@pytest.mark.parametrize("radius", [0, -1, float("inf"), float("nan")])
def test_invalid_radius_rejected(radius: float) -> None:
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    with pytest.raises(ValueError):
        circle_fillet_notrim(first, second, (2, 1), (8, 1), radius, uuid4().hex)


def test_disjoint_offset_circles_and_concentric_circles_rejected() -> None:
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    for second in (CircleEntity(uuid4().hex, (20, 0), 2), CircleEntity(uuid4().hex, (0, 0), 3)):
        with pytest.raises(ValueError):
            circle_fillet_notrim(first, second, (2, 1), (8, 1), 4, uuid4().hex)


def test_ambiguous_picks_and_same_circle_are_rejected() -> None:
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    with pytest.raises(ValueError, match="方向"):
        circle_fillet_notrim(first, second, (2, 0), (8, 0), 4, uuid4().hex)
    with pytest.raises(ValueError, match="不同"):
        circle_fillet_notrim(first, first, (2, 1), (2, -1), 4, uuid4().hex)
