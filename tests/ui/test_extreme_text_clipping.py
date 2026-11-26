# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Degenerate curves must retain the visible parts of glyph outlines."""

from decimal import Decimal

from mycad.ui.extreme_text_clipping import flatten_glyph_cubic


def test_collinear_curve_that_reverses_direction_enters_viewport() -> None:
    def point(x: int) -> tuple[Decimal, Decimal]:
        return (Decimal(x), Decimal(0))

    rect = (Decimal(0), Decimal(-1), Decimal(10), Decimal(1))
    flattened = flatten_glyph_cubic(point(-10), point(30), point(30), point(-5), rect)
    assert max(x for x, _ in flattened) > 0
