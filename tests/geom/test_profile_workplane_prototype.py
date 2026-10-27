# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral work-plane profile prototype round trips and rejects bad values."""

from __future__ import annotations

import math

import pytest

from mycad.core.sketch import WorkPlaneFrame as CoreWorkPlaneFrame
from mycad.geom.profiles import (
    ConstructionSegment2D,
    DimensionLabel,
    ProfileSketch,
    WireContour,
    WorkPlaneFrame,
)


def test_profile_prototype_reuses_the_neutral_core_workplane_frame() -> None:
    assert WorkPlaneFrame is CoreWorkPlaneFrame


def test_holed_profile_and_oblique_frame_round_trip_as_neutral_values() -> None:
    root_half = math.sqrt(0.5)
    sketch = ProfileSketch(
        frame=WorkPlaneFrame(
            origin_mm=(10.0, 20.0, 30.0),
            u_axis=(root_half, 0.0, root_half),
            v_axis=(0.0, 1.0, 0.0),
            normal=(-root_half, 0.0, root_half),
        ),
        contours=(
            WireContour(vertices_mm=((-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0))),
            WireContour(
                vertices_mm=((-5.0, -5.0), (-5.0, 5.0), (5.0, 5.0), (5.0, -5.0)),
                is_hole=True,
            ),
        ),
        construction_geometry=(ConstructionSegment2D(start_mm=(-25.0, 0.0), end_mm=(25.0, 0.0)),),
        dimensions=(DimensionLabel("bore", 10.0, "mm", "reference"),),
    )

    restored = ProfileSketch.from_mapping(sketch.to_mapping())

    assert restored == sketch
    assert restored.frame.normal == pytest.approx((-root_half, 0.0, root_half))
    assert restored.contours[1].is_hole
    assert restored.dimensions[0].kind == "reference"


def test_oblique_frame_rejects_non_orthonormal_axes() -> None:
    with pytest.raises(ValueError, match="orthonormal"):
        WorkPlaneFrame(
            origin_mm=(0.0, 0.0, 0.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(1.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
        )


def test_profile_rejects_open_or_zero_area_contours() -> None:
    with pytest.raises(ValueError, match="closed"):
        WireContour(vertices_mm=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), closed=False)
    with pytest.raises(ValueError, match="area"):
        WireContour(vertices_mm=((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)))


def test_profile_rejects_hole_that_crosses_or_touches_outer_boundary() -> None:
    frame = WorkPlaneFrame(
        origin_mm=(0.0, 0.0, 0.0),
        u_axis=(1.0, 0.0, 0.0),
        v_axis=(0.0, 1.0, 0.0),
        normal=(0.0, 0.0, 1.0),
    )
    outer = WireContour(vertices_mm=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    crossing_hole = WireContour(
        vertices_mm=((1.0, 1.0), (1.0, 9.0), (12.0, 9.0), (12.0, 1.0)),
        is_hole=True,
    )

    with pytest.raises(ValueError, match="inside"):
        ProfileSketch(frame, (outer, crossing_hole))
