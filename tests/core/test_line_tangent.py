# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deferred common tangents between finite circular curves."""

import math
from uuid import uuid4

import pytest

from mycad.core.fillet_curves import tangent_on_curves
from mycad.core.sketch import ArcEntity, CircleEntity


def test_common_tangent_matches_recorded_exercise_lower_side() -> None:
    from mycad.core.line_tangent import common_tangent_line

    lower = CircleEntity(uuid4().hex, (0, 0), 20)
    right = CircleEntity(uuid4().hex, (90, 45), 30)
    line = common_tangent_line(lower, right, (6, -19), (100, 17), uuid4().hex)
    assert tangent_on_curves(line, lower) and tangent_on_curves(line, right)
    assert line.start_mm[1] < 0 and line.end_mm[1] < right.center_mm[1]
    assert math.dist(line.start_mm, lower.center_mm) == pytest.approx(20)
    assert math.dist(line.end_mm, right.center_mm) == pytest.approx(30)


def test_common_tangent_supports_internal_tangent_and_finite_arcs() -> None:
    from mycad.core.line_tangent import common_tangent_line

    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    line = common_tangent_line(first, second, (0.8, 1.8), (9.2, -1.8), uuid4().hex)
    assert line.start_mm[1] > 0 and line.end_mm[1] < 0
    assert tangent_on_curves(line, first) and tangent_on_curves(line, second)
    upper_first = ArcEntity(first.entity_id, first.center_mm, 2, 0, 180)
    lower_second = ArcEntity(second.entity_id, second.center_mm, 2, 180, 180)
    finite = common_tangent_line(upper_first, lower_second, (0.8, 1.8), (9.2, -1.8), uuid4().hex)
    assert finite.start_mm == pytest.approx(line.start_mm)
    assert finite.end_mm == pytest.approx(line.end_mm)


def test_common_tangent_rejects_concentric_or_ambiguous_sources() -> None:
    from mycad.core.line_tangent import common_tangent_line

    first = CircleEntity(uuid4().hex, (0, 0), 2)
    concentric = CircleEntity(uuid4().hex, (0, 0), 5)
    with pytest.raises(ValueError):
        common_tangent_line(first, concentric, (2, 0), (5, 0), uuid4().hex)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    with pytest.raises(ValueError, match="不明确"):
        common_tangent_line(first, second, (2, 0), (8, 0), uuid4().hex)


def test_tangent_line_between_circle_and_point_supports_both_directions() -> None:
    from mycad.core.line_tangent import tangent_line_to_point

    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    anchor = (10.0, 0.0)
    line = tangent_line_to_point(circle, anchor, (2.5, 4.33), uuid4().hex)
    assert line.start_mm == anchor
    assert line.end_mm == pytest.approx((2.5, 5 * math.sqrt(3) / 2))
    assert tangent_on_curves(line, circle)
    reverse = tangent_line_to_point(circle, anchor, (2.5, 4.33), uuid4().hex, from_curve=True)
    assert reverse.start_mm == pytest.approx(line.end_mm) and reverse.end_mm == anchor


def test_tangent_line_from_point_rejects_inside_and_ambiguous() -> None:
    from mycad.core.line_tangent import tangent_line_to_point

    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    with pytest.raises(ValueError):
        tangent_line_to_point(circle, (3, 0), (0, 5), uuid4().hex)
    with pytest.raises(ValueError, match="不明确"):
        tangent_line_to_point(circle, (10, 0), (5, 0), uuid4().hex)
