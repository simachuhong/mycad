# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Circle construction tangent to two picked curves at a given radius."""

import math
from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity


def test_ttr_selects_circle_center_nearest_two_picks() -> None:
    from mycad.core.circle_ttr import circle_ttr

    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    circle = circle_ttr(first, second, (2, 1), (8, 1), 4, uuid4().hex)
    assert circle.center_mm == pytest.approx((5, math.sqrt(11)))
    assert circle.radius_mm == 4
    assert math.dist(circle.center_mm, first.center_mm) == pytest.approx(6)
    assert math.dist(circle.center_mm, second.center_mm) == pytest.approx(6)


def test_ttr_reference_profile_supports_enclosing_internal_tangencies() -> None:
    from mycad.core.circle_ttr import circle_ttr

    upper = CircleEntity(uuid4().hex, (0, 0), 27)
    lower = CircleEntity(uuid4().hex, (0, -65), 20)
    circle = circle_ttr(upper, lower, (-23, 13), (-13, -80), 70, uuid4().hex)
    assert circle.center_mm[0] > 0
    assert math.dist(circle.center_mm, upper.center_mm) == pytest.approx(70 - 27)
    assert math.dist(circle.center_mm, lower.center_mm) == pytest.approx(70 - 20)


def test_ttr_two_lines_uses_picked_corner() -> None:
    from mycad.core.circle_ttr import circle_ttr

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    circle = circle_ttr(first, second, (5, 0), (0, 5), 2, uuid4().hex)
    assert circle.center_mm == pytest.approx((2, 2))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("arc_source", [False, True])
def test_ttr_line_and_circular_source(reverse: bool, arc_source: bool) -> None:
    from mycad.core.circle_ttr import circle_ttr

    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    circular = (
        ArcEntity(uuid4().hex, (0, 5), 2, 180, 90)
        if arc_source
        else CircleEntity(uuid4().hex, (0, 5), 2)
    )
    sources = (circular, line) if reverse else (line, circular)
    picks = ((-1.3, 3.5), (-3, 0)) if reverse else ((-3, 0), (-1.3, 3.5))
    result = circle_ttr(*sources, *picks, 2, uuid4().hex, construction=True, layer_name="A")
    assert result.center_mm == pytest.approx((-math.sqrt(7), 2))
    assert result.construction and result.layer_name == "A"


def test_ttr_rejects_ambiguous_or_invalid_input() -> None:
    from mycad.core.circle_ttr import circle_ttr

    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    with pytest.raises(ValueError):
        circle_ttr(first, second, (2, 0), (8, 0), 4, uuid4().hex)
    with pytest.raises(ValueError):
        circle_ttr(first, second, (2, 1), (8, 1), 0, uuid4().hex)
