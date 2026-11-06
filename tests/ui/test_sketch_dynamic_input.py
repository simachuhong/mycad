# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact sketch dimensions resolve independently of mouse movement."""

import pytest

from mycad.ui.sketch_dynamic_input import resolve_dynamic_point


def test_line_locks_length_and_angle() -> None:
    assert resolve_dynamic_point("line", (1, 2), (100, 100), length=10, angle_deg=90) == (
        pytest.approx(1),
        pytest.approx(12),
    )
    assert resolve_dynamic_point("line", (0, 0), (3, 4), length=10) == pytest.approx((6, 8))
    assert resolve_dynamic_point("line", (0, 0), (3, 4), angle_deg=180) == pytest.approx((-5, 0))


def test_rectangle_dimensions_keep_cursor_quadrant() -> None:
    assert resolve_dynamic_point("rectangle", (1, 2), (-4, 9), width=8, height=3) == (
        -7,
        5,
    )
    assert resolve_dynamic_point("rectangle", (1, 2), (-4, 9), width=8) == (-7, 9)


def test_circle_radius_preserves_direction() -> None:
    assert resolve_dynamic_point("circle", (1, 2), (4, 6), radius=10) == pytest.approx((7, 10))


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_locked_length_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        resolve_dynamic_point("line", (0, 0), (1, 1), length=value)
