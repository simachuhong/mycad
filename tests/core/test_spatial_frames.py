# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Rigid coordinate composition must preserve local design intent."""

import math

import pytest

from mycad.core.spatial_frames import RigidFrame


def test_relative_frame_composition_and_inverse() -> None:
    parent = RigidFrame((10, 20, 30), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    child = RigidFrame((2, 3, 4), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    world = parent.compose(child)
    assert world.origin_mm == pytest.approx((7, 22, 34))
    assert world.local_to_world((5, 6, 7)) == pytest.approx((1, 27, 41))
    assert world.world_to_local((1, 27, 41)) == pytest.approx((5, 6, 7))


def test_principal_xz_plane_preserves_existing_axis_orientation() -> None:
    frame = RigidFrame.identity().principal_plane("xz")
    assert frame.u_axis == (1, 0, 0)
    assert frame.v_axis == (0, 0, -1)
    assert frame.normal == (0, 1, 0)


@pytest.mark.parametrize(
    ("origin", "x", "y", "z"),
    [
        ((math.nan, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0, 0), (2, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((0, 0, 0), (1, 0, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, -1)),
    ],
)
def test_invalid_coordinate_frames_are_rejected(
    origin: tuple[float, float, float],
    x: tuple[float, float, float],
    y: tuple[float, float, float],
    z: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError):
        RigidFrame(origin, x, y, z)
