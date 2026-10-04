# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""FaceSelector resolution matrix ①–⑩ from the Phase 0 plan (T2).

The resolution contract: filter by surface kind (plane normal / undirected
cylinder axis), order candidates by area descending then face-center
(x, y, z) lexicographic ascending, then apply rank semantics.
"""

from __future__ import annotations

import math

import pytest
from build123d import Box, BuildPart, Face, GeomType, Locations, Mode

from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.selectors import FaceSelector
from mycad.geom.kernel import BuildKernel
from mycad.geom.selectors import resolve_face as module_resolve_face
from tests.geom._geometry import (
    FLANGE_BORE_RADIUS,
    FLANGE_HOLE_RADIUS,
    FLANGE_OUTER_RADIUS,
    build_flange,
    build_offset_equal_tops,
    build_stacked_blocks,
)


def _flange() -> BuildKernel:
    kernel = BuildKernel()
    build_flange(kernel)
    return kernel


def _face_center(face: Face) -> tuple[float, float, float]:
    center = face.center()
    return (center.X, center.Y, center.Z)


def _face_area(face: Face) -> float:
    return face.area


def _face_radius(face: Face) -> float:
    radius = face.radius
    assert radius is not None, "radius is only meaningful on cylindrical faces"
    return radius


# ① (plane, +Z) rank=0 selects the largest flange end face (annulus).
def test_matrix_1_plane_up_rank0_largest_flange_face() -> None:
    kernel = _flange()
    face = kernel.resolve_face(FaceSelector(surface="plane", axis="+Z", rank=0), "t")
    expected_area = math.pi * (
        FLANGE_OUTER_RADIUS**2 - FLANGE_BORE_RADIUS**2 - 4 * FLANGE_HOLE_RADIUS**2
    )
    assert _face_area(face) == pytest.approx(expected_area, abs=1e-6)
    center = _face_center(face)
    assert abs(abs(center[2]) - 4.0) < 1e-9


# ② two +Z outward horizontal faces with different areas -> exactly 2
#    candidates; omitted rank is ambiguous.
def test_matrix_2_two_block_construction_is_ambiguous_without_rank() -> None:
    kernel = BuildKernel()
    build_stacked_blocks(kernel)
    candidates = kernel.face_candidates(FaceSelector(surface="plane", axis="+Z"), "t")
    assert len(candidates) == 2
    areas = sorted((_face_area(face) for face in candidates), reverse=True)
    assert areas[0] == pytest.approx(300.0, abs=1e-6)
    assert areas[1] == pytest.approx(100.0, abs=1e-6)
    with pytest.raises(TopologyReferenceError, match="ambiguous") as excinfo:
        kernel.resolve_face(FaceSelector(surface="plane", axis="+Z"), "t")
    assert "2" in str(excinfo.value)


# ③ rank=1 takes the second-largest +Z plane (the small block top face).
def test_matrix_3_rank1_takes_second_largest_plane() -> None:
    kernel = BuildKernel()
    build_stacked_blocks(kernel)
    face = kernel.resolve_face(FaceSelector(surface="plane", axis="+Z", rank=1), "t")
    assert _face_area(face) == pytest.approx(100.0, abs=1e-6)
    assert _face_center(face) == pytest.approx((0.0, 0.0, 10.0), abs=1e-9)
    # face-by-face equivalence with direct algebraic selection on the same
    # construction built through raw build123d
    with BuildPart() as part:
        with Locations((0.0, 0.0, 2.5)):
            Box(20, 20, 5)
        with Locations((0.0, 0.0, 7.5)):
            Box(10, 10, 5, mode=Mode.ADD)

    algebraic = module_resolve_face(
        FaceSelector(surface="plane", axis="+Z", rank=1), part.part, "t"
    )
    assert _face_center(algebraic) == pytest.approx(_face_center(face), abs=1e-9)
    assert _face_area(algebraic) == pytest.approx(_face_area(face), abs=1e-9)


# ④ rank=99 exceeds the candidate count -> TopologyReferenceError with the
#    candidate count in the reason.
def test_matrix_4_rank_out_of_range_reports_candidate_count() -> None:
    kernel = _flange()
    candidates = kernel.face_candidates(FaceSelector(surface="cylinder", axis="+Z"), "t")
    assert len(candidates) == 6
    with pytest.raises(TopologyReferenceError, match="rank=99") as excinfo:
        kernel.resolve_face(FaceSelector(surface="cylinder", axis="+Z", rank=99), "t")
    assert "6" in str(excinfo.value)


# ⑤ (cylinder, None) selects all 6 cylindrical faces of the flange.
def test_matrix_5_cylinder_none_selects_all_six_cylindrical_faces() -> None:
    kernel = _flange()
    candidates = kernel.face_candidates(FaceSelector(surface="cylinder"), "t")
    assert len(candidates) == 6
    radii = sorted(_face_radius(face) for face in candidates)
    assert radii == pytest.approx([3.0, 3.0, 3.0, 3.0, 10.0, 40.0], abs=1e-9)


# ⑥ cylinder axis matching is undirected: +Z and -Z give identical results.
def test_matrix_6_cylinder_axis_matching_is_undirected() -> None:
    kernel = _flange()
    plus = kernel.face_candidates(FaceSelector(surface="cylinder", axis="+Z"), "t")
    minus = kernel.face_candidates(FaceSelector(surface="cylinder", axis="-Z"), "t")
    assert len(plus) == 6
    assert [_face_center(face) for face in plus] == pytest.approx(
        [_face_center(face) for face in minus], abs=1e-12
    )
    assert [_face_area(face) for face in plus] == pytest.approx(
        [_face_area(face) for face in minus], abs=1e-12
    )


# ⑦ (cylinder, +X) does not match Z-axis cylinders -> no-match.
def test_matrix_7_cylinder_plus_x_is_no_match_on_z_axis() -> None:
    kernel = _flange()
    assert kernel.face_candidates(FaceSelector(surface="cylinder", axis="+X"), "t") == []
    with pytest.raises(TopologyReferenceError, match="no-match") as excinfo:
        kernel.resolve_face(FaceSelector(surface="cylinder", axis="+X"), "t")
    assert '"surface": "cylinder"' in str(excinfo.value)


# ⑧ plane with axis omitted (None) -> ValidationError.
def test_matrix_8_plane_requires_explicit_axis() -> None:
    kernel = _flange()
    with pytest.raises(ValidationError, match="plane"):
        kernel.resolve_face(FaceSelector(surface="plane"), "t")
    with pytest.raises(ValidationError, match="plane"):
        kernel.resolve_face({"surface": "plane"}, "t")


# ⑨ "" and None axis behave identically (isomorphic inputs).
def test_matrix_9_empty_string_axis_is_isomorphic_to_none() -> None:
    kernel = _flange()
    via_dataclass = kernel.face_candidates(FaceSelector(surface="cylinder"), "t")
    via_dict_none = kernel.face_candidates({"surface": "cylinder"}, "t")
    via_dict_empty = kernel.face_candidates({"surface": "cylinder", "axis": ""}, "t")
    assert len(via_dataclass) == len(via_dict_none) == len(via_dict_empty) == 6
    with pytest.raises(ValidationError):
        kernel.resolve_face({"surface": "plane"}, "t")
    with pytest.raises(ValidationError):
        kernel.resolve_face({"surface": "plane", "axis": ""}, "t")


# ⑩ equal-area faces tie-break by face-center (x, y, z) lexicographic order.
def test_matrix_10_equal_area_tiebreak_is_lexicographic() -> None:
    kernel = BuildKernel()
    build_offset_equal_tops(kernel)
    candidates = kernel.face_candidates(FaceSelector(surface="plane", axis="+Z"), "t")
    assert len(candidates) == 2
    areas = [_face_area(face) for face in candidates]
    assert areas[0] == pytest.approx(areas[1], abs=1e-9)
    assert _face_center(candidates[0]) == pytest.approx((-10.0, 0.0, 5.0), abs=1e-9)
    assert _face_center(candidates[1]) == pytest.approx((10.0, 0.0, 5.0), abs=1e-9)
    face = kernel.resolve_face(FaceSelector(surface="plane", axis="+Z", rank=0), "t")
    assert _face_center(face) == pytest.approx((-10.0, 0.0, 5.0), abs=1e-9)


def test_no_match_reports_candidate_count_zero() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    with pytest.raises(TopologyReferenceError, match="no-match") as excinfo:
        kernel.resolve_face(FaceSelector(surface="cylinder"), "t")
    assert "0" in str(excinfo.value)


def test_empty_kernel_face_resolution_is_no_match() -> None:
    kernel = BuildKernel()
    with pytest.raises(TopologyReferenceError, match="no-match"):
        kernel.resolve_face(FaceSelector(surface="plane", axis="+Z"), "t")


def test_plane_axis_directed_matching() -> None:
    kernel = _flange()
    top = kernel.resolve_face(FaceSelector(surface="plane", axis="+Z", rank=0), "t")
    bottom = kernel.resolve_face(FaceSelector(surface="plane", axis="-Z", rank=0), "t")
    assert _face_center(top)[2] > 0
    assert _face_center(bottom)[2] < 0


def test_descriptor_json_echoed_in_failure_messages() -> None:
    kernel = _flange()
    selector = {"surface": "cylinder", "axis": "+X", "rank": 3}
    with pytest.raises(TopologyReferenceError) as excinfo:
        kernel.resolve_face(selector, "feature.hole")
    message = str(excinfo.value)
    assert "feature.hole" in message
    assert '"surface": "cylinder"' in message
    assert '"axis": "+X"' in message


def test_malformed_descriptors_raise_validation_error() -> None:
    kernel = _flange()
    for bad in (
        {"surface": "sphere"},
        {"surface": "plane", "axis": "diagonal"},
        {"surface": "plane", "axis": "+Z", "rank": -1},
        {"surface": "plane", "axis": "+Z", "rank": "first"},
    ):
        with pytest.raises(ValidationError):
            kernel.resolve_face(bad, "t")


def test_geom_type_filtering_uses_build123d_surfaces() -> None:
    kernel = _flange()
    for face in kernel.face_candidates(FaceSelector(surface="cylinder"), "t"):
        assert face.geom_type == GeomType.CYLINDER
    for face in kernel.face_candidates(FaceSelector(surface="plane", axis="+Z"), "t"):
        assert face.geom_type == GeomType.PLANE
