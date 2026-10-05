# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Feature-layer tests (Phase 0, T5): extrude / revolve / hole / hole_pattern /
fillet / boolean_cut against analytic volumes and the plan's error contract.

Every expected volume is computed from a formula inside the test (never
hand-typed, never reverse-recorded from implementation output).
"""

from __future__ import annotations

import math

import pytest

from mycad.core.exceptions import (
    GeometryBuildError,
    TopologyReferenceError,
    ValidationError,
)
from mycad.geom.kernel import BuildKernel

VOLUME_TOLERANCE_MM3 = 1e-6


def _volume(kernel: BuildKernel) -> float:
    return kernel.mass_properties().volume


def test_extrude_circle_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 10.0}, "distance": 5.0},
    )
    assert _volume(kernel) == pytest.approx(math.pi * 10**2 * 5, abs=VOLUME_TOLERANCE_MM3)


def test_extrude_circle_bbox_spans_zero_to_distance() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 10.0, "center": (2.0, 3.0)}, "distance": 5.0},
    )
    props = kernel.mass_properties()
    assert props.bbox is not None
    assert props.bbox.zmin == pytest.approx(0.0, abs=1e-9)
    assert props.bbox.zmax == pytest.approx(5.0, abs=1e-9)


def test_extrude_rect_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.extrude",
        {"profile": {"type": "rect", "width": 10.0, "height": 20.0}, "distance": 5.0},
    )
    assert _volume(kernel) == pytest.approx(10 * 20 * 5, abs=VOLUME_TOLERANCE_MM3)


def test_extrude_negative_distance_extrudes_along_minus_z() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.extrude",
        {"profile": {"type": "circle", "radius": 10.0}, "distance": -5.0},
    )
    props = kernel.mass_properties()
    assert props.volume == pytest.approx(math.pi * 10**2 * 5, abs=VOLUME_TOLERANCE_MM3)
    assert props.bbox is not None
    assert props.bbox.zmin == pytest.approx(-5.0, abs=1e-9)
    assert props.bbox.zmax == pytest.approx(0.0, abs=1e-9)


# --- feature.revolve ---------------------------------------------------------


def test_revolve_rect_around_y_axis_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
            "axis": "Y",
        },
    )
    assert _volume(kernel) == pytest.approx(2 * math.pi * 5 * (2 * 3), abs=VOLUME_TOLERANCE_MM3)


def test_revolve_unit_vector_axis_matches_cardinal_axis() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
            "axis": (0.0, 1.0, 0.0),
        },
    )
    assert _volume(kernel) == pytest.approx(2 * math.pi * 5 * (2 * 3), abs=VOLUME_TOLERANCE_MM3)


def test_revolve_rect_around_x_axis_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (0.0, 5.0)},
            "axis": "X",
        },
    )
    assert _volume(kernel) == pytest.approx(2 * math.pi * 5 * (2 * 3), abs=VOLUME_TOLERANCE_MM3)


def test_revolve_partial_angle_volume_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.revolve",
        {
            "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
            "axis": "Y",
            "angle_deg": 180.0,
        },
    )
    assert _volume(kernel) == pytest.approx(math.pi * 5 * (2 * 3), abs=VOLUME_TOLERANCE_MM3)


def test_revolve_rejects_non_unit_axis_vector() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="norm"):
        kernel.apply(
            "feature.revolve",
            {
                "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
                "axis": (1.0, 1.0, 0.0),
            },
        )


def test_revolve_rejects_zero_axis_vector() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="norm"):
        kernel.apply(
            "feature.revolve",
            {
                "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
                "axis": (0.0, 0.0, 0.0),
            },
        )


def test_revolve_rejects_z_axis_string() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="axis"):
        kernel.apply(
            "feature.revolve",
            {
                "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
                "axis": "Z",
            },
        )


@pytest.mark.parametrize("angle_deg", [0.0, 360.5, -10.0])
def test_revolve_rejects_angle_out_of_range(angle_deg: float) -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="angle_deg"):
        kernel.apply(
            "feature.revolve",
            {
                "profile": {"type": "rect", "width": 2.0, "height": 3.0, "center": (5.0, 0.0)},
                "axis": "Y",
                "angle_deg": angle_deg,
            },
        )


# --- modify.fillet ------------------------------------------------------------


def _box10(kernel: BuildKernel) -> None:
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})


_FILLET_TOP_EDGES = {
    "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}],
    "radius": 1.0,
}


def test_fillet_top_edges_reduces_volume_and_adds_cylindrical_faces() -> None:
    kernel = BuildKernel()
    _box10(kernel)
    before = kernel.mass_properties()
    assert before.cylindrical_face_count == 0
    kernel.apply("modify.fillet", dict(_FILLET_TOP_EDGES))
    after = kernel.mass_properties()
    # build123d 0.11.1 measured value for Box 10^3 top edges, radius 1.0
    # (fillet_probe.py authority): 991.7994 — edge removal dominates, the
    # four corner patches add a small correction back.
    assert after.volume == pytest.approx(991.7994, abs=1e-3)
    assert after.volume < before.volume
    assert after.cylindrical_face_count == 4
    assert after.solid_count == 1


def test_fillet_radius_beyond_geometry_raises_geometry_build_error() -> None:
    kernel = BuildKernel()
    _box10(kernel)
    params = {"edges": _FILLET_TOP_EDGES["edges"], "radius": 999.0}
    with pytest.raises(GeometryBuildError, match="fillet"):
        kernel.apply("modify.fillet", params)


def test_fillet_on_empty_kernel_raises_topology_reference_error() -> None:
    kernel = BuildKernel()
    with pytest.raises(TopologyReferenceError):
        kernel.apply("modify.fillet", dict(_FILLET_TOP_EDGES))


def test_fillet_rejects_empty_edge_selector_list() -> None:
    kernel = BuildKernel()
    _box10(kernel)
    with pytest.raises(ValidationError, match="edges"):
        kernel.apply("modify.fillet", {"edges": [], "radius": 1.0})


def test_fillet_rejects_nonpositive_radius() -> None:
    kernel = BuildKernel()
    _box10(kernel)
    with pytest.raises(ValidationError, match="radius"):
        kernel.apply("modify.fillet", {"edges": _FILLET_TOP_EDGES["edges"], "radius": 0.0})


def test_fillet_rejects_unknown_parameter_key() -> None:
    kernel = BuildKernel()
    _box10(kernel)
    params: dict[str, object] = {"edges": _FILLET_TOP_EDGES["edges"], "radius": 1.0, "chamfer": 1}
    with pytest.raises(ValidationError, match="chamfer"):
        kernel.apply("modify.fillet", params)


# --- modify.boolean_cut -------------------------------------------------------


def test_boolean_cut_box_tool_from_cylinder_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})
    kernel.apply(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 10.0, "size_y": 10.0, "size_z": 30.0}},
    )
    assert _volume(kernel) == pytest.approx(
        math.pi * 40**2 * 8 - 10 * 10 * 8, abs=VOLUME_TOLERANCE_MM3
    )


def test_boolean_cut_cylinder_tool_from_box_is_analytic() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0})
    kernel.apply(
        "modify.boolean_cut",
        {"tool": {"type": "cylinder", "radius": 5.0, "height": 30.0, "center": (0.0, 0.0, 0.0)}},
    )
    assert _volume(kernel) == pytest.approx(
        20 * 20 * 10 - math.pi * 5**2 * 10, abs=VOLUME_TOLERANCE_MM3
    )


def test_boolean_cut_on_empty_kernel_raises_geometry_build_error() -> None:
    kernel = BuildKernel()
    with pytest.raises(GeometryBuildError):
        kernel.apply(
            "modify.boolean_cut",
            {"tool": {"type": "box", "size_x": 10.0, "size_y": 10.0, "size_z": 10.0}},
        )


def test_boolean_cut_rejects_mode_key() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0})
    params: dict[str, object] = {
        "tool": {"type": "box", "size_x": 10.0, "size_y": 10.0, "size_z": 10.0},
        "mode": "cut",
    }
    with pytest.raises(ValidationError, match="mode"):
        kernel.apply("modify.boolean_cut", params)


def test_boolean_cut_rejects_unknown_tool_type() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0})
    with pytest.raises(ValidationError, match="type"):
        kernel.apply(
            "modify.boolean_cut",
            {"tool": {"type": "sphere", "radius": 5.0}},
        )


def test_boolean_cut_rejects_missing_tool() -> None:
    kernel = BuildKernel()
    with pytest.raises(ValidationError, match="tool"):
        kernel.apply("modify.boolean_cut", {})


# --- feature.hole -------------------------------------------------------------


def _cylinder_flange_blank(kernel: BuildKernel) -> None:
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})


def _box20(kernel: BuildKernel) -> None:
    kernel.apply("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 20.0})


def _hole_params(axis: str, diameter: float, depth: dict[str, object]) -> dict[str, object]:
    return {
        "target_face": {"surface": "plane", "axis": axis, "rank": 0},
        "position": {"kind": "center"},
        "diameter": diameter,
        "depth": depth,
    }


def test_hole_through_all_at_face_center_is_analytic() -> None:
    kernel = BuildKernel()
    _cylinder_flange_blank(kernel)
    kernel.apply("feature.hole", _hole_params("+Z", 20.0, {"kind": "through_all"}))
    assert _volume(kernel) == pytest.approx(math.pi * 8 * (40**2 - 10**2), abs=VOLUME_TOLERANCE_MM3)


def test_hole_blind_depth_removes_exact_pocket_volume() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    kernel.apply("feature.hole", _hole_params("+Z", 4.0, {"kind": "blind", "value": 5.0}))
    # blind: exactly pi*r^2*5 removed (a through hole would remove pi*r^2*20)
    assert _volume(kernel) == pytest.approx(20**3 - math.pi * 2**2 * 5, abs=VOLUME_TOLERANCE_MM3)


def test_hole_blind_on_minus_z_face_drills_into_material() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    kernel.apply("feature.hole", _hole_params("-Z", 4.0, {"kind": "blind", "value": 5.0}))
    # outward normal is -Z; the blind pocket must run INTO the material
    # (same volume removed as the +Z case, not zero)
    assert _volume(kernel) == pytest.approx(20**3 - math.pi * 2**2 * 5, abs=VOLUME_TOLERANCE_MM3)


def test_hole_cylindrical_target_face_raises_target_not_plane() -> None:
    kernel = BuildKernel()
    _cylinder_flange_blank(kernel)
    params = _hole_params("+Z", 6.0, {"kind": "through_all"})
    params["target_face"] = {"surface": "cylinder", "rank": 0}
    with pytest.raises(TopologyReferenceError, match="target-not-plane"):
        kernel.apply("feature.hole", params)


def test_hole_predicate_no_match_raises_with_command_id() -> None:
    kernel = BuildKernel()
    _cylinder_flange_blank(kernel)
    params = _hole_params("+Z", 6.0, {"kind": "through_all"})
    params["target_face"] = {"surface": "plane", "axis": "+X"}
    with pytest.raises(TopologyReferenceError, match="no-match") as excinfo:
        kernel.apply("feature.hole", params)
    assert "feature.hole" in str(excinfo.value)


def test_hole_unsupported_position_kind_is_rejected() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    params = _hole_params("+Z", 4.0, {"kind": "through_all"})
    params["position"] = {"kind": "corner"}
    with pytest.raises(ValidationError, match="center"):
        kernel.apply("feature.hole", params)


def test_hole_unsupported_depth_kind_is_rejected() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    params = _hole_params("+Z", 4.0, {"kind": "through"})
    with pytest.raises(ValidationError, match="depth"):
        kernel.apply("feature.hole", params)


def test_hole_missing_diameter_is_rejected() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    params = _hole_params("+Z", 4.0, {"kind": "through_all"})
    del params["diameter"]
    with pytest.raises(ValidationError, match="diameter"):
        kernel.apply("feature.hole", params)


def test_hole_repeated_after_geometry_consumed_raises_explicitly() -> None:
    kernel = BuildKernel()
    _box20(kernel)
    # d=30 centered on the 20x20 top face consumes the entire box
    kernel.apply("feature.hole", _hole_params("+Z", 30.0, {"kind": "through_all"}))
    assert kernel.mass_properties().solid_count == 0
    # the target face no longer exists: the same predicate must fail
    # explicitly, never silently re-target another face
    with pytest.raises((TopologyReferenceError, GeometryBuildError)):
        kernel.apply("feature.hole", _hole_params("+Z", 30.0, {"kind": "through_all"}))


# --- feature.hole_pattern -----------------------------------------------------


from build123d import CenterOf  # noqa: E402

from mycad.core.selectors import FaceSelector  # noqa: E402


def _plate(kernel: BuildKernel) -> None:
    kernel.apply("feature.box", {"size_x": 100.0, "size_y": 100.0, "size_z": 5.0})


def _pattern_params(
    axis: str, start_angle_deg: float, *, count: int = 3, radius: float = 30.0
) -> dict[str, object]:
    return {
        "base_hole": {
            "target_face": {"surface": "plane", "axis": axis, "rank": 0},
            "position": {"kind": "center"},
            "diameter": 10.0,
            "depth": {"kind": "through_all"},
        },
        "pattern": {
            "kind": "polar",
            "radius": radius,
            "count": count,
            "start_angle_deg": start_angle_deg,
        },
    }


def _cylindrical_face_centers(kernel: BuildKernel) -> list[tuple[float, float, float]]:
    """Hole-axis positions of the cylindrical wall faces.

    ``Face.center()`` defaults to ``CenterOf.GEOMETRY``, which for a
    non-planar face is the parametric midpoint ON the surface — for a
    full cylinder band that is a point one hole-radius away from the
    axis (opposite the seam), not the hole center. The area centroid
    (``CenterOf.MASS``) of a full 360° band lies exactly on the axis,
    which is the quantity the polar-angle spec defines.
    """

    faces = kernel.face_candidates(FaceSelector(surface="cylinder"), "t")
    return sorted(
        (face.center(CenterOf.MASS).X, face.center(CenterOf.MASS).Y, face.center(CenterOf.MASS).Z)
        for face in faces
    )


def test_hole_pattern_plus_z_centers_follow_global_polar_angles() -> None:
    kernel = BuildKernel()
    _plate(kernel)
    kernel.apply("feature.hole_pattern", _pattern_params("+Z", 0.0))
    y = 30.0 * math.sin(2 * math.pi / 3)
    expected = [(-15.0, -y, 0.0), (-15.0, y, 0.0), (30.0, 0.0, 0.0)]
    assert _cylindrical_face_centers(kernel) == [pytest.approx(p, abs=1e-6) for p in expected]
    assert _volume(kernel) == pytest.approx(
        100 * 100 * 5 - 3 * math.pi * 5**2 * 5, abs=VOLUME_TOLERANCE_MM3
    )


def test_hole_pattern_start_angle_90_puts_first_hole_on_plus_y() -> None:
    kernel = BuildKernel()
    _plate(kernel)
    kernel.apply("feature.hole_pattern", _pattern_params("+Z", 90.0))
    # Off-axis holes at 210/330 deg: |x| = 30*cos(30 deg), not cos(120 deg).
    x = 30.0 * math.cos(math.pi / 6)
    expected = [(-x, -15.0, 0.0), (0.0, 30.0, 0.0), (x, -15.0, 0.0)]
    assert _cylindrical_face_centers(kernel) == [pytest.approx(p, abs=1e-6) for p in expected]


def test_hole_pattern_count4_centers_match_flange_bolt_circle() -> None:
    kernel = BuildKernel()
    _plate(kernel)
    kernel.apply("feature.hole_pattern", _pattern_params("+Z", 0.0, count=4, radius=25.0))
    expected = [(-25.0, 0.0, 0.0), (0.0, -25.0, 0.0), (0.0, 25.0, 0.0), (25.0, 0.0, 0.0)]
    assert _cylindrical_face_centers(kernel) == [pytest.approx(p, abs=1e-6) for p in expected]
