# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sphere primitive behavior at the geometry boundary."""

import math

import pytest

from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.geom.kernel import BuildKernel


def test_sphere_volume_and_centered_bounds() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.sphere", {"radius": 10, "center": [3, -4, 5]})
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(4 * math.pi * 10**3 / 3)
    assert props.center_of_mass == pytest.approx((3, -4, 5))
    assert props.bbox is not None
    assert (props.bbox.xmin, props.bbox.xmax) == pytest.approx((-7, 13))
    assert (props.bbox.ymin, props.bbox.ymax) == pytest.approx((-14, 6))
    assert (props.bbox.zmin, props.bbox.zmax) == pytest.approx((-5, 15))


@pytest.mark.parametrize("radius", [0, -1, float("nan"), float("inf"), True])
def test_sphere_rejects_invalid_radius(radius: object) -> None:
    with pytest.raises(ValidationError):
        BuildKernel().apply("feature.sphere", {"radius": radius})


def test_sphere_cut_on_empty_model_is_rejected() -> None:
    with pytest.raises(GeometryBuildError):
        BuildKernel().apply("feature.sphere", {"radius": 1, "mode": "cut"})


def test_full_sphere_exposes_exact_center_anchor() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.sphere", {"radius": 10, "center": [3, -4, 5]})
    anchors = kernel.snap_anchor_data()
    assert any(a.kind == "center" and a.point == pytest.approx((3, -4, 5)) for a in anchors)


def test_trimmed_sphere_does_not_expose_center_as_full_sphere() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.sphere", {"radius": 10, "center": [3, -4, 5]})
    kernel.apply(
        "feature.box",
        {"size_x": 20, "size_y": 30, "size_z": 30, "center": [18, -4, 5], "mode": "cut"},
    )
    assert not any(
        a.kind == "center" and a.point == pytest.approx((3, -4, 5))
        for a in kernel.snap_anchor_data()
    )


def test_sphere_modes_replace_add_cut_and_leave_failed_model_intact() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    kernel.apply("feature.sphere", {"radius": 2, "center": [20, 0, 0], "mode": "add"})
    assert kernel.mass_properties().volume == pytest.approx(1000 + 32 * math.pi / 3)
    kernel.apply("feature.sphere", {"radius": 2, "center": [20, 0, 0], "mode": "cut"})
    assert kernel.mass_properties().volume == pytest.approx(1000)
    with pytest.raises(ValidationError):
        kernel.apply("feature.sphere", {"radius": -2, "mode": "new"})
    assert kernel.mass_properties().volume == pytest.approx(1000)
    kernel.apply("feature.sphere", {"radius": 3})
    assert kernel.mass_properties().volume == pytest.approx(36 * math.pi)
