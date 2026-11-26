# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Unassociated external dimensions retain explicit values and tolerances."""

from uuid import uuid4

import pytest

from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_tolerance import DimensionTolerance


def test_detached_linear_dimension_roundtrip_preserves_explicit_measurement() -> None:
    dimension = DetachedDimension(
        uuid4().hex,
        "rotated",
        (0, 0),
        (10, 4),
        (0, 5),
        0,
        10,
        DimensionTolerance("deviation", 0.1, -0.2, 2),
        layer_name="DIM",
    )
    assert DetachedDimension.from_mapping(dimension.to_mapping()) == dimension
    assert dimension.nominal == 10


def test_three_point_straight_angle_rejects_ambiguous_or_opposite_location() -> None:
    for location in ((5, 0), (0, -5)):
        with pytest.raises(ValueError, match="semicircle"):
            DetachedDimension(
                uuid4().hex, "angular_3p", (10, 0), (-10, 0), location, 0, 180, vertex_mm=(0, 0)
            )


def test_detached_dimension_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, "rotated", (0, 0), (1, 1), (0, 2), 0, float("nan"))
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, "unrecognized", (0, 0), (1, 1), (0, 2), 0, 1)


def test_detached_dimension_rejects_integer_overflow_as_validation_error() -> None:
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, "rotated", (10**1000, 0), (1, 1), (0, 2), 0, 1)
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, "rotated", (0, 0), (1, 1), (0, 2), 0, 10**1000)


def test_detached_dimension_rejects_nominal_inconsistent_with_definition_points() -> None:
    with pytest.raises(ValueError, match="nominal"):
        DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 20)


@pytest.mark.parametrize("kind", ("radius", "diameter"))
def test_radial_reference_validates_geometry_and_factor(kind: str) -> None:
    dimension = DetachedDimension(
        uuid4().hex, kind, (0, 0), (10, 0), (15, 0), 0, 20, linear_factor=2
    )
    assert DetachedDimension.from_mapping(dimension.to_mapping()) == dimension
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, kind, (0, 0), (0, 0), (15, 0), 0, 0)
    with pytest.raises(ValueError):
        DetachedDimension(uuid4().hex, kind, (0, 0), (10, 0), (15, 0), 0, 10, linear_factor=2)


def test_angular_reference_rejects_clockwise_or_wrong_measurement() -> None:
    with pytest.raises(ValueError):
        DetachedDimension(
            uuid4().hex, "angular_3p", (0, 10), (10, 0), (5, 5), 0, 90, vertex_mm=(0, 0)
        )
    with pytest.raises(ValueError):
        DetachedDimension(
            uuid4().hex, "angular_3p", (10, 0), (0, 10), (5, 5), 0, 45, vertex_mm=(0, 0)
        )


def test_three_point_reflex_reference_preserves_counterclockwise_angle() -> None:
    dimension = DetachedDimension(
        uuid4().hex,
        "angular_3p",
        (0, 10),
        (10, 0),
        (-5, -5),
        0,
        270,
        DimensionTolerance("deviation", 0.1, -0.2),
        vertex_mm=(0, 0),
    )
    assert DetachedDimension.from_mapping(dimension.to_mapping()) == dimension


def test_two_line_reflex_reference_preserves_counterclockwise_angle() -> None:
    dimension = DetachedDimension(
        uuid4().hex, "angular_2l", (0, 10), (10, 0), (-5, -5), 0, 270, vertex_mm=(0, 0)
    )
    assert DetachedDimension.from_mapping(dimension.to_mapping()) == dimension


def test_three_point_straight_angle_has_explicit_vertex_and_semicircle() -> None:
    dimension = DetachedDimension(
        uuid4().hex,
        "angular_3p",
        (10, 0),
        (-10, 0),
        (0, 15),
        0,
        180,
        DimensionTolerance("deviation", 0.1, -0.2),
        vertex_mm=(0, 0),
    )
    assert DetachedDimension.from_mapping(dimension.to_mapping()) == dimension
