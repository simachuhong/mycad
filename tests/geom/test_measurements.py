# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact BREP-backed measurements on analytical shapes."""

from __future__ import annotations

import math

import pytest
from build123d import Edge, Plane

from mycad.core.measurements import MeasurementRequest
from mycad.core.semantic_refs import EdgePredicate, FacePredicate
from mycad.geom.kernel import BuildKernel
from mycad.geom.query import measure_circular_edge_center_distance
from tests.geom._geometry import build_flange


def test_measure_diametric_flange_hole_pitch_from_exact_circle_centers() -> None:
    first = Edge.make_circle(3.0, Plane(origin=(-25.0, 0.0, 0.0)))
    opposite = Edge.make_circle(3.0, Plane(origin=(25.0, 0.0, 0.0)))

    pitch = measure_circular_edge_center_distance(first, opposite)

    assert pitch == pytest.approx(50.0)


def test_measure_flange_hole_diameter_from_selected_cylindrical_face() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    reference, _face = kernel.bind_semantic_face(
        "selected-hole",
        FacePredicate(surface="cylinder", center_mm=(0.0, -25.0, 0.0)),
        "measure.select",
    )

    result = kernel.measure(
        MeasurementRequest(
            kind="cylindrical_face_diameter",
            references=(reference,),
            revision=kernel.geometry_revision,
        )
    )

    assert result.value == pytest.approx(6.0)
    assert result.unit == "mm"


def test_measure_body_volume_uses_exact_brep_mass_properties() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 40.0, "height": 8.0})

    result = kernel.measure(
        MeasurementRequest(kind="body_volume", revision=kernel.geometry_revision)
    )

    assert result.value == pytest.approx(math.pi * 40.0**2 * 8.0, rel=1e-10)
    assert result.unit == "mm³"
    assert result.source == "BREP"
    assert result.error is None


def test_measure_flange_pitch_from_selected_brep_edges() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    top_face = FacePredicate(surface="plane", axis="+Z")
    first, _first_edge = kernel.bind_semantic_edge(
        "first-hole-edge",
        EdgePredicate(
            parent_faces=(top_face,),
            curve="circle",
            center_mm=(-25.0, 0.0, 4.0),
            radius_mm=3.0,
        ),
        "measure.select",
    )
    opposite, _opposite_edge = kernel.bind_semantic_edge(
        "opposite-hole-edge",
        EdgePredicate(
            parent_faces=(top_face,),
            curve="circle",
            center_mm=(25.0, 0.0, 4.0),
            radius_mm=3.0,
        ),
        "measure.select",
    )

    result = kernel.measure(
        MeasurementRequest(
            kind="circular_edge_center_distance",
            references=(first, opposite),
            revision=kernel.geometry_revision,
        )
    )

    assert result.value == pytest.approx(50.0)


def test_flange_measurement_targets_are_exact_and_neutral() -> None:
    kernel = BuildKernel()
    build_flange(kernel)

    diameter_targets = kernel.measurement_targets("cylindrical_face_diameter")
    edge_targets = kernel.measurement_targets("circular_edge_center_distance")
    plane_targets = kernel.measurement_targets("parallel_plane_separation")

    assert len(diameter_targets) == 6
    assert len(edge_targets) == 12
    assert len(plane_targets) == 2
    assert all("BREP" not in target.label for target in diameter_targets)


def test_circular_edge_targets_survive_ambiguous_same_axis_parent_faces() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.cylinder",
        {"radius": 3.0, "height": 8.0, "center": [-20.0, 0.0, 0.0]},
    )
    kernel.apply(
        "feature.cylinder",
        {
            "radius": 3.0,
            "height": 8.0,
            "center": [20.0, 0.0, 0.0],
            "mode": "add",
        },
    )

    targets = kernel.measurement_targets("circular_edge_center_distance")

    assert len(targets) == 4


def test_measure_cylindrical_face_diameter_exactly() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 3.0, "height": 8.0})
    reference, _face = kernel.bind_semantic_face(
        "outer-cylinder", FacePredicate(surface="cylinder"), "measure.select"
    )

    result = kernel.measure(
        MeasurementRequest(
            kind="cylindrical_face_diameter",
            references=(reference,),
            revision=kernel.geometry_revision,
        )
    )

    assert result.value == pytest.approx(6.0)
    assert result.unit == "mm"


def test_measure_parallel_planar_face_separation() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 5.0, "height": 8.0})
    bottom, _ = kernel.bind_semantic_face(
        "bottom", FacePredicate(surface="plane", axis="-Z"), "measure.select"
    )
    top, _ = kernel.bind_semantic_face(
        "top", FacePredicate(surface="plane", axis="+Z"), "measure.select"
    )

    result = kernel.measure(
        MeasurementRequest(
            kind="parallel_plane_separation",
            references=(bottom, top),
            revision=kernel.geometry_revision,
        )
    )

    assert result.value == pytest.approx(8.0)
    assert result.unit == "mm"


def test_measure_reports_nonparallel_plane_selection() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 12.0, "size_z": 8.0})
    bottom, _ = kernel.bind_semantic_face(
        "bottom", FacePredicate(surface="plane", axis="-Z"), "measure.select"
    )
    side, _ = kernel.bind_semantic_face(
        "side", FacePredicate(surface="plane", axis="+X"), "measure.select"
    )

    result = kernel.measure(
        MeasurementRequest(
            kind="parallel_plane_separation",
            references=(bottom, side),
            revision=kernel.geometry_revision,
        )
    )

    assert result.value is None
    assert result.error == "selected planar faces are not parallel"


def test_measure_reports_insufficient_reference_and_stale_revision() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 3.0, "height": 8.0})
    missing = kernel.measure(
        MeasurementRequest(kind="cylindrical_face_diameter", revision=kernel.geometry_revision)
    )
    stale = kernel.measure(MeasurementRequest(kind="body_volume", revision=0))

    assert missing.value is None
    assert "one cylindrical face" in (missing.error or "")
    assert stale.value is None
    assert "stale" in (stale.error or "").lower()
    assert stale.revision == 0
