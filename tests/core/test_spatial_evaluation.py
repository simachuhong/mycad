# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A datum must follow its parent coordinate system during evaluation."""

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.spatial_evaluation import evaluate_coordinate, evaluate_offset, evaluate_principal
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference

COORD_ID = "11111111111111111111111111111111"
PLANE_ID = "22222222222222222222222222222222"


def test_relative_coordinate_principal_plane_and_offset_follow_parent() -> None:
    parent = RigidFrame((10, 20, 30), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    local = RigidFrame((2, 3, 4), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    coord = evaluate_coordinate(
        SpatialReference("coordinate_system", COORD_ID, "coordinate_system"),
        local,
        {COORD_ID: ("coordinate_system", parent)},
    )
    plane = evaluate_principal(
        SpatialReference("coordinate_system", COORD_ID, "coordinate_system"),
        "xz",
        {COORD_ID: ("coordinate_system", coord)},
    )
    result = evaluate_offset(
        SpatialReference("datum_plane", PLANE_ID, "plane"),
        20,
        {PLANE_ID: ("datum_plane", plane)},
    )
    assert result.origin_mm == pytest.approx((-13, 22, 34))
    assert result.u_axis == pytest.approx((0, 1, 0))
    assert result.normal == pytest.approx((-1, 0, 0))
    assert result.local_to_world((2, 3)) == pytest.approx((-13, 24, 31))


def test_wrong_parent_type_and_nonfinite_offset_fail() -> None:
    reference = SpatialReference("datum_plane", PLANE_ID, "plane")
    with pytest.raises(ValidationError):
        evaluate_offset(reference, 2, {PLANE_ID: ("datum_plane", RigidFrame.identity())})
    plane = RigidFrame.identity().principal_plane("xy")
    with pytest.raises(ValidationError):
        evaluate_offset(reference, float("inf"), {PLANE_ID: ("datum_plane", plane)})
