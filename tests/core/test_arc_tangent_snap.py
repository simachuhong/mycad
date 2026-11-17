# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Tangent endpoint candidates for a three-point arc."""

import math

import pytest


def test_tangent_endpoint_to_finite_line_after_two_arc_points() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_line

    points = tangent_endpoints_to_line((0, 5), (10, 5), (-20, 0), (40, 0))
    assert len(points) == 1
    assert points[0] == pytest.approx((5, 0))
    assert tangent_endpoints_to_line((0, 5), (10, 5), (-20, 0), (0, 0)) == ()


def test_arc_points_on_opposite_sides_cannot_form_tangent_circle() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_line

    assert tangent_endpoints_to_line((0, -2), (10, 2), (-20, 0), (40, 0)) == ()


def test_two_geometric_tangent_solutions_are_returned() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_line

    points = tangent_endpoints_to_line((0, 4), (4, 8), (-20, 0), (40, 0))
    assert len(points) == 2
    assert sorted(point[0] for point in points) == pytest.approx([-12, 4])
    assert all(point[1] == pytest.approx(0) for point in points)


def test_three_point_arc_can_be_tangent_to_existing_circle() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle

    contacts = tangent_endpoints_to_circle((10, 5), (15, 0), (0, 0), 5)
    assert any(point == pytest.approx((5, 0)) for point in contacts)
    assert all(math.dist(point, (0, 0)) == pytest.approx(5) for point in contacts)


def test_three_point_arc_skips_degenerate_coincident_circles() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle

    contacts = tangent_endpoints_to_circle((5, 0), (0, 5), (0, 0), 5)
    assert all(math.dist(point, (0, 0)) == pytest.approx(5) for point in contacts)
    assert all(point != (5, 0) and point != (0, 5) for point in contacts)


def test_tangent_endpoints_to_circle_supports_internal_tangency() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle

    contacts = tangent_endpoints_to_circle((2, 3), (-1, 0), (0, 0), 5)
    assert any(math.dist(point, (5, 0)) < 1e-7 for point in contacts)


@pytest.mark.parametrize("factor", [1e-7, 1.0, 1e6])
def test_tangent_contacts_are_invariant_under_uniform_scale(factor: float) -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle, tangent_endpoints_to_line

    circle_contacts = tangent_endpoints_to_circle(
        (10 * factor, 5 * factor), (15 * factor, 0), (0, 0), 5 * factor
    )
    assert any(math.dist(point, (5 * factor, 0)) < factor * 1e-7 for point in circle_contacts)
    line_contacts = tangent_endpoints_to_line(
        (0, 5 * factor), (10 * factor, 5 * factor), (-20 * factor, 0), (40 * factor, 0)
    )
    assert any(math.dist(point, (5 * factor, 0)) < factor * 1e-7 for point in line_contacts)


def test_tangent_circle_candidates_survive_large_radius_difference() -> None:
    from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle

    radius = 100_000_000.0
    center_x = radius + 5
    contacts = tangent_endpoints_to_circle((center_x, radius), (center_x + radius, 0), (0, 0), 5)
    assert any(math.dist(point, (5, 0)) < 1e-5 for point in contacts)
    assert any(math.dist(point, (-5, 0)) < 1e-5 for point in contacts)
