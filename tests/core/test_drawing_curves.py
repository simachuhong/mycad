# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Vector cubic approximation is bounded in paper units, not fixed sampling."""

import math

import pytest

from mycad.core.drawing_curves import cubic_segments
from mycad.core.drawing_projection import ArcCurve, SplineCurve


def test_large_circle_cubic_error_within_paper_tolerance() -> None:
    segments = cubic_segments(ArcCurve((0, 0), 10000), tolerance=0.01)
    assert len(segments) > 4
    for segment in segments:
        for i in range(21):
            point = segment.point(i / 20)
            assert abs(math.hypot(*point) - 10000) <= 0.010001


def test_rational_spline_cubic_preserves_curve_without_polylines() -> None:
    curve = SplineCurve(((0, 0), (10, 50), (40, -30), (80, 0)), 3, (0, 1), (4, 4), (1, 10, 0.2, 1))
    segments = cubic_segments(curve, tolerance=0.005)
    assert len(segments) > 1
    assert segments[0].start == curve.poles[0] and segments[-1].end == curve.poles[-1]
    for segment in segments:
        for i in range(11):
            t = i / 10
            u = segment.parameter_range[0] + t * (
                segment.parameter_range[1] - segment.parameter_range[0]
            )
            coefficients = [
                math.comb(3, j) * u**j * (1 - u) ** (3 - j) * curve.weights[j] for j in range(4)
            ]
            expected = tuple(
                sum(coefficients[j] * curve.poles[j][axis] for j in range(4)) / sum(coefficients)
                for axis in range(2)
            )
            assert segment.point(t) == pytest.approx(expected, abs=0.005)


def test_multispan_spline_keeps_knot_boundary() -> None:
    curve = SplineCurve(
        ((0, 0), (10, 40), (20, -10), (30, 40), (40, 0)), 3, (0, 0.5, 1), (4, 1, 4), (1, 1, 1, 1, 1)
    )
    segments = cubic_segments(curve, tolerance=1e-6)
    assert len(segments) == 2
    assert segments[0].end == segments[1].start
    assert segments[0].parameter_range == (0, 0.5)
    assert segments[1].parameter_range == (0.5, 1)
