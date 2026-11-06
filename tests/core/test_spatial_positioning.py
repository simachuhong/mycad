# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared world/workplane positioning and explicit numeric entry."""

import pytest

from mycad.core.sketch import WorkPlaneFrame
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_positioning import (
    ProjectedAnchor,
    choose_object_snap,
    intersect_plane,
    locate_uv,
    object_snap_candidates,
)


def test_rotated_plane_rays_and_parent_coordinates() -> None:
    plane = RigidFrame.identity().principal_plane("xz")
    point = intersect_plane((3, 10, 4), (0, -1, 0), plane)
    assert point is not None
    assert point == pytest.approx((3, 0, 4))
    assert plane.world_to_local(point) == pytest.approx((3, -4))
    assert intersect_plane((3, 10, 4), (1, 0, 0), plane) is None
    assert intersect_plane((3, 10, 4), (0, 1, 0), plane) is None
    assert intersect_plane((3, float("nan"), 4), (0, -1, 0), plane) is None


def test_numeric_entry_is_never_snapped_and_grid_is_independent() -> None:
    plane = WorkPlaneFrame.xy()
    numeric = locate_uv((1.23, -4.56), plane, numeric=True, grid_enabled=True, spacing=1)
    assert numeric.uv == pytest.approx((1.23, -4.56))
    assert numeric.source == "numeric"
    snapped = locate_uv((1.23, -4.56), plane, numeric=False, grid_enabled=True, spacing=1)
    assert snapped.uv == pytest.approx((1, -5))
    assert snapped.source == "grid"
    raw = locate_uv((1.23, -4.56), plane, numeric=False, grid_enabled=False, spacing=1)
    assert raw.uv == pytest.approx((1.23, -4.56))


def test_object_snap_uses_screen_distance_and_explicit_off_plane_projection() -> None:
    plane = WorkPlaneFrame.xy()
    anchors = (
        ProjectedAnchor("midpoint", "m", (3, 4, 0), (100, 100)),
        ProjectedAnchor("vertex", "v", (8, 9, 5), (100, 100)),
    )
    result = choose_object_snap(anchors, (100, 100), plane)
    assert result is not None and result.anchor.key == "m" and not result.projected
    result = choose_object_snap(anchors, (100, 100), plane, allow_projection=True)
    assert result is not None and result.anchor.key == "v" and result.projected
    assert result.world == pytest.approx((8, 9, 0))
    assert choose_object_snap(anchors, (200, 200), plane, allow_projection=True) is None
    options = object_snap_candidates(anchors, (100, 100), plane, allow_projection=True)
    assert [option.anchor.key for option in options] == ["v", "m"]
    assert options[0].anchor.world == (8, 9, 5)
    assert options[0].world == (8, 9, 0)
