# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The circular datum indicator has a radial leader and perpendicular bar."""

import math

import pytest

from mycad.core.geometric_tolerance_geometry import circular_datum_geometry


def test_circular_datum_geometry_connects_circle_to_centered_bar() -> None:
    circle, leader, bar = circular_datum_geometry((0, 0), (0, 10), 2, 4)
    assert circle == ((0, 0), 2)
    assert leader == ((0, 2), (0, 10))
    assert bar == ((-2, 10), (2, 10))


def test_circular_datum_geometry_rotates_bar_without_rotating_label() -> None:
    circle, leader, bar = circular_datum_geometry((0, 0), (10, 0), 2, 4)
    assert circle == ((0, 0), 2)
    assert leader == ((2, 0), (10, 0))
    assert bar == ((10, 2), (10, -2))


def test_explicit_bar_direction_is_independent_of_slanted_connector() -> None:
    _, _, bar = circular_datum_geometry((8, 10), (0, 0), 2, 4, bar_direction=(1, 0))
    assert bar == ((-2, 0), (2, 0))


@pytest.mark.parametrize(
    ("center", "target", "radius", "bar_length"),
    [
        ((0, 0), (0, 0), 1, 2),
        ((0, 0), (1, 0), 1, 2),
        ((0, 0), (4, 0), 0, 2),
        ((0, 0), (4, 0), 1, math.inf),
        ((math.nan, 0), (4, 0), 1, 2),
    ],
)
def test_circular_datum_geometry_rejects_invalid_input(
    center: tuple[float, float], target: tuple[float, float], radius: float, bar_length: float
) -> None:
    with pytest.raises(ValueError):
        circular_datum_geometry(center, target, radius, bar_length)
