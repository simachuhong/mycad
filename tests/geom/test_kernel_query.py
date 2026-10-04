# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mass-properties and tessellation query tests."""

from __future__ import annotations

import math

import pytest

from mycad.core.exceptions import ValidationError
from mycad.core.geometry_types import Tessellation
from mycad.geom.kernel import BuildKernel
from tests.geom._geometry import (
    FLANGE_HOLE_PCD_RADIUS,
    build_flange,
    flange_volume_formula,
)


def test_empty_kernel_mass_properties_are_zeros() -> None:
    props = BuildKernel().mass_properties()
    assert props.solid_count == 0
    assert props.volume == 0.0
    assert props.bbox is None
    assert props.center_of_mass == (0.0, 0.0, 0.0)
    assert props.cylindrical_face_count == 0


def test_reset_returns_kernel_to_empty_state() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    kernel.reset()
    props = kernel.mass_properties()
    assert props.solid_count == 0
    assert props.volume == 0.0
    assert props.bbox is None


def test_flange_mass_properties_full_readout() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(flange_volume_formula(), abs=1e-6)
    assert props.solid_count == 1
    assert props.cylindrical_face_count == 6
    assert props.bbox is not None
    dx, dy, dz = props.bbox.size
    assert (dx, dy, dz) == pytest.approx((80.0, 80.0, 8.0), abs=1e-9)
    assert props.center_of_mass == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_mass_properties_are_plain_python_types() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.cylinder",
        {"radius": 40.0, "height": 8.0, "center": (1.5, 2.5, 3.5)},
    )
    props = kernel.mass_properties()
    assert type(props.volume) is float
    assert type(props.solid_count) is int
    assert type(props.cylindrical_face_count) is int
    assert type(props.center_of_mass) is tuple
    for coord in props.center_of_mass:
        assert type(coord) is float


def test_tessellate_empty_kernel_returns_empty_mesh() -> None:
    mesh = BuildKernel().tessellate(1.0, 30.0)
    assert isinstance(mesh, Tessellation)
    assert mesh.vertices == ()
    assert mesh.triangle_indices == ()


def test_tessellate_yields_plain_tuples_and_valid_indices() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})
    mesh = kernel.tessellate(1.0, 30.0)
    assert len(mesh.triangle_indices) == 12
    # build123d tessellate emits one vertex block per face (4x6=24 for a box),
    # not a welded vertex soup; indices are offsets into the concatenated list.
    assert len(mesh.vertices) == 24
    for vertex in mesh.vertices:
        assert type(vertex) is tuple
        for coord in vertex:
            assert type(coord) is float
    for triangle in mesh.triangle_indices:
        assert type(triangle) is tuple
        for index in triangle:
            assert type(index) is int


def test_tessellate_halved_chord_tolerance_strictly_increases_triangles() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    coarse = kernel.tessellate(10.0, 30.0)
    fine = kernel.tessellate(5.0, 30.0)
    assert len(fine.triangle_indices) > len(coarse.triangle_indices)


def test_tessellate_vertices_lie_within_bounding_box() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    mesh = kernel.tessellate(5.0, 30.0)
    bbox = kernel.mass_properties().bbox
    assert bbox is not None
    slack = 1e-6
    for x, y, z in mesh.vertices:
        assert bbox.xmin - slack <= x <= bbox.xmax + slack
        assert bbox.ymin - slack <= y <= bbox.ymax + slack
        assert bbox.zmin - slack <= z <= bbox.zmax + slack


@pytest.mark.parametrize(
    ("linear", "angular"),
    [
        (0.0, 30.0),
        (-1.0, 30.0),
        (1.0, 0.0),
        (1.0, -5.0),
        (float("nan"), 30.0),
        (1.0, float("inf")),
    ],
)
def test_tessellate_rejects_nonpositive_or_nonfinite_tolerances(
    linear: float, angular: float
) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 5.0, "height": 8.0})
    with pytest.raises(ValidationError):
        kernel.tessellate(linear, angular)


def test_pcd_geometry_formula_sanity() -> None:
    # The fixture must encode PCD50: holes at |offset| == 25 from the axis.
    assert FLANGE_HOLE_PCD_RADIUS == 25.0
    assert flange_volume_formula() == pytest.approx(
        math.pi * 8 * (40**2 - 10**2 - 4 * 3**2), abs=1e-12
    )
