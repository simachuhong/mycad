# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""feature.box / feature.cylinder three-mode tests against analytic volumes.

Every expected value is computed from a formula inside the test (never
hand-typed, never reverse-recorded from implementation output).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

import pytest

from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.geom.kernel import BuildKernel

VOLUME_TOLERANCE_MM3 = 1e-6


def _volume(kernel: BuildKernel) -> float:
    return kernel.mass_properties().volume


def test_box_new_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 80.0, "size_y": 80.0, "size_z": 8.0})
    assert _volume(kernel) == pytest.approx(80 * 80 * 8, abs=VOLUME_TOLERANCE_MM3)


def test_box_cut_removes_analytic_overlap() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 80.0, "size_y": 80.0, "size_z": 8.0})
    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 30.0, "mode": "cut"},
    )
    assert _volume(kernel) == pytest.approx(80 * 80 * 8 - 10 * 10 * 8, abs=VOLUME_TOLERANCE_MM3)


def test_box_add_disjoint_union_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 80.0, "size_y": 80.0, "size_z": 8.0})
    kernel.apply(
        "feature.box",
        {
            "size_x": 10.0,
            "size_y": 10.0,
            "size_z": 8.0,
            "center": (50.0, 0.0, 0.0),
            "mode": "add",
        },
    )
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(80 * 80 * 8 + 10 * 10 * 8, abs=VOLUME_TOLERANCE_MM3)
    assert props.solid_count == 2


def test_box_add_overlapping_union_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0, "center": (5.0, 0.0, 0.0), "mode": "add"},
    )
    assert _volume(kernel) == pytest.approx(2 * 10**3 - 5 * 10 * 10, abs=VOLUME_TOLERANCE_MM3)


def test_box_mode_new_replaces_previous_solid() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 80.0, "size_y": 80.0, "size_z": 8.0})
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(10**3, abs=VOLUME_TOLERANCE_MM3)
    assert props.solid_count == 1


def test_cylinder_new_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})
    assert _volume(kernel) == pytest.approx(math.pi * 40**2 * 8, abs=VOLUME_TOLERANCE_MM3)


def test_cylinder_cut_through_bore_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})
    kernel.apply("feature.cylinder", {"radius": 10.0, "height": 20.0, "mode": "cut"})
    assert _volume(kernel) == pytest.approx(math.pi * 8 * (40**2 - 10**2), abs=VOLUME_TOLERANCE_MM3)


def test_cylinder_add_disjoint_union_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})
    kernel.apply(
        "feature.cylinder",
        {
            "radius": 5.0,
            "height": 8.0,
            "center": (50.0, 0.0, 0.0),
            "mode": "add",
        },
    )
    assert _volume(kernel) == pytest.approx(math.pi * 8 * (40**2 + 5**2), abs=VOLUME_TOLERANCE_MM3)


def test_cylinder_center_places_z_span_symmetric() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.cylinder",
        {"radius": 5.0, "height": 8.0, "center": (10.0, 20.0, 30.0)},
    )
    props = kernel.mass_properties()
    assert props.bbox is not None
    assert props.bbox.zmin == pytest.approx(30.0 - 4.0, abs=1e-9)
    assert props.bbox.zmax == pytest.approx(30.0 + 4.0, abs=1e-9)
    assert props.center_of_mass == pytest.approx((10.0, 20.0, 30.0), abs=1e-9)


def test_box_center_places_bbox() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0, "center": (10.0, 0.0, 0.0)},
    )
    props = kernel.mass_properties()
    assert props.bbox is not None
    assert props.bbox.xmin == pytest.approx(5.0, abs=1e-9)
    assert props.bbox.xmax == pytest.approx(15.0, abs=1e-9)
    assert props.bbox.ymin == pytest.approx(-10.0, abs=1e-9)
    assert props.bbox.ymax == pytest.approx(10.0, abs=1e-9)
    assert props.bbox.zmin == pytest.approx(-15.0, abs=1e-9)
    assert props.bbox.zmax == pytest.approx(15.0, abs=1e-9)


def test_cut_on_empty_kernel_raises_geometry_build_error() -> None:
    kernel = BuildKernel()
    with pytest.raises(GeometryBuildError):
        kernel.apply("feature.cylinder", {"radius": 10.0, "height": 8.0, "mode": "cut"})


def test_total_cut_yields_empty_geometry_not_error() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    kernel.apply("feature.box", {"size_x": 100.0, "size_y": 100.0, "size_z": 100.0, "mode": "cut"})
    props = kernel.mass_properties()
    assert props.solid_count == 0
    assert props.volume == 0.0
    assert props.bbox is None


def test_add_on_empty_kernel_behaves_like_new() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0, "mode": "add"})
    assert _volume(kernel) == pytest.approx(10**3, abs=VOLUME_TOLERANCE_MM3)


def test_flange_full_construction_volume_is_analytic() -> None:
    from tests.geom._geometry import build_flange, flange_volume_formula

    kernel = BuildKernel()
    build_flange(kernel)
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(flange_volume_formula(), abs=VOLUME_TOLERANCE_MM3)
    assert props.solid_count == 1
    assert props.cylindrical_face_count == 6


@pytest.mark.parametrize(
    ("command_id", "params"),
    [
        ("feature.sphere", {"radius": 5.0}),
        ("garbage.command", {}),
        ("feature.box", {}),
    ],
)
def test_apply_rejects_unknown_or_unimplemented_commands(
    command_id: str, params: dict[str, object]
) -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match=command_id):
        kernel.apply(command_id, params)


@pytest.mark.parametrize(
    ("command_id", "params", "bad_key"),
    [
        ("feature.box", {"size_x": 10.0, "size_y": 10.0}, "size_z"),
        ("feature.cylinder", {"radius": 5.0}, "height"),
    ],
)
def test_apply_rejects_missing_required_parameters(
    command_id: str, params: dict[str, object], bad_key: str
) -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match=bad_key):
        kernel.apply(command_id, params)


@pytest.mark.parametrize(
    ("command_id", "params", "bad_key"),
    [
        ("feature.box", {"size_x": 0.0, "size_y": 10.0, "size_z": 10.0}, "size_x"),
        ("feature.box", {"size_x": -5.0, "size_y": 10.0, "size_z": 10.0}, "size_x"),
        (
            "feature.box",
            {"size_x": float("inf"), "size_y": 10.0, "size_z": 10.0},
            "size_x",
        ),
        ("feature.cylinder", {"radius": 0.0, "height": 10.0}, "radius"),
        ("feature.cylinder", {"radius": 5.0, "height": -1.0}, "height"),
        (
            "feature.cylinder",
            {"radius": 5.0, "height": float("nan")},
            "height",
        ),
    ],
)
def test_apply_rejects_nonpositive_or_nonfinite_sizes(
    command_id: str, params: dict[str, object], bad_key: str
) -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match=bad_key):
        kernel.apply(command_id, params)


def test_apply_rejects_unknown_parameter_key() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="colour"):
        kernel.apply(
            "feature.box",
            {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0, "colour": "red"},
        )


def test_apply_rejects_invalid_mode() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="mode"):
        kernel.apply(
            "feature.box",
            {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0, "mode": "xor"},
        )


def test_apply_rejects_bool_as_number() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="radius"):
        kernel.apply("feature.cylinder", {"radius": True, "height": 10.0})


@pytest.mark.parametrize(
    "center",
    [
        (1.0, 2.0),
        (1.0, 2.0, 3.0, 4.0),
        "origin",
        (1.0, "two", 3.0),
    ],
)
def test_apply_rejects_malformed_center(center: object) -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="center"):
        kernel.apply(
            "feature.box",
            {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0, "center": center},
        )


def test_apply_rejects_non_mapping_params() -> None:
    kernel = BuildKernel()
    bad_params = cast("Mapping[str, object]", ["size_x", 10.0])
    with pytest.raises(ValidationError):
        kernel.apply("feature.box", bad_params)


def test_export_step_and_stl_are_placeholders() -> None:
    kernel = BuildKernel()
    with pytest.raises(NotImplementedError):
        kernel.export_step("out.step")
    with pytest.raises(NotImplementedError):
        kernel.export_stl("out.stl")
