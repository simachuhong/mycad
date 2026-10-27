# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Snapshot-semantics viewport tests (phase 1, todo 3).

BuildKernel must expose one mesh snapshot per successful ``apply``; the
undo/redo rebuild path resets the kernel and re-applies the whole
history, so the snapshot list is naturally rebuilt in ordinal order.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from build123d import Part

from mycad.core.exceptions import EmptyGeometryError
from mycad.core.geometry_types import Tessellation
from mycad.core.viewport_protocol import ViewportData, ViewportPort
from mycad.geom import kernel as kernel_module
from mycad.geom.kernel import BuildKernel
from tests.geom._geometry import build_flange


def test_empty_kernel_yields_no_snapshots() -> None:
    assert BuildKernel().viewport_data() == ()


def test_kernel_satisfies_viewport_port() -> None:
    assert isinstance(BuildKernel(), ViewportPort)


def test_flange_snapshot_count_ids_and_vertices() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    snapshots = kernel.viewport_data()
    assert len(snapshots) == 1
    assert snapshots[0].state_id == "feature.cylinder:5"
    assert kernel.viewport_state_ids() == tuple(f"feature.cylinder:{i}" for i in range(6))
    assert all(isinstance(snapshot, ViewportData) for snapshot in snapshots)
    assert all(len(snapshot.mesh.vertices) > 0 for snapshot in snapshots)


def test_brep_boundaries_are_revision_stable_and_expire_after_mutation() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 12, "size_z": 14})

    first = kernel.viewport_data()[0]
    assert len(first.boundary_edges) == 12
    assert all(edge.body_id in kernel.body_ids for edge in first.boundary_edges)
    assert len({edge.topology_id for edge in first.boundary_edges}) == 12
    assert first.boundary_edges == kernel.viewport_data()[0].boundary_edges
    assert all(len(edge.points) == 2 for edge in first.boundary_edges)
    assert all(point[0] in {-5.0, 5.0} for edge in first.boundary_edges for point in edge.points)

    kernel.apply("feature.box", {"size_x": 20, "size_y": 22, "size_z": 24})
    second = kernel.viewport_data()[0]
    assert all(not kernel.is_current_topology(edge.topology_id) for edge in first.boundary_edges)
    assert all(kernel.is_current_topology(edge.topology_id) for edge in second.boundary_edges)
    assert {edge.topology_id for edge in first.boundary_edges}.isdisjoint(
        edge.topology_id for edge in second.boundary_edges
    )


def test_curved_boundary_polylines_follow_cylinder_brep_edges() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 10, "height": 5})

    boundaries = kernel.viewport_data()[0].boundary_edges
    assert len(boundaries) == 2
    curved_edges = tuple(edge for edge in boundaries if len(edge.points) > 2)
    assert len(curved_edges) == 2
    for edge in curved_edges:
        assert edge.points[0] == pytest.approx(edge.points[-1])
        assert all(
            (point[0] ** 2 + point[1] ** 2) ** 0.5 == pytest.approx(10.0, abs=0.03)
            for point in edge.points
        )
        z_values = tuple(point[2] for point in edge.points)
        assert max(z_values) - min(z_values) < 1e-8


def test_viewport_snapshot_maps_faces_vertices_and_triangles_to_runtime_ids() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 12, "size_z": 14})
    snapshot = kernel.viewport_data()[0]

    assert snapshot.geometry_revision == kernel.geometry_revision
    assert len(snapshot.faces) == 6
    assert len(snapshot.vertices) == 8
    assert len(snapshot.triangle_face_ids) == len(snapshot.mesh.triangle_indices)
    assert len(snapshot.triangle_body_ids) == len(snapshot.mesh.triangle_indices)
    face_ids = {face.topology_id for face in snapshot.faces}
    vertex_ids = {vertex.topology_id for vertex in snapshot.vertices}
    assert len(face_ids) == 6
    assert len(vertex_ids) == 8
    assert set(snapshot.triangle_face_ids) <= face_ids
    assert set(snapshot.triangle_body_ids) == set(kernel.body_ids)
    assert all(kernel.is_current_topology(identity) for identity in face_ids | vertex_ids)
    assert all(face.body_id == kernel.body_ids[0] for face in snapshot.faces)
    assert all(vertex.body_id == kernel.body_ids[0] for vertex in snapshot.vertices)

    kernel.apply("feature.box", {"size_x": 20, "size_y": 22, "size_z": 24})
    updated = kernel.viewport_data()[0]
    assert updated.geometry_revision == kernel.geometry_revision
    assert all(not kernel.is_current_topology(identity) for identity in face_ids | vertex_ids)
    assert set(face_ids).isdisjoint(face.topology_id for face in updated.faces)
    assert set(vertex_ids).isdisjoint(vertex.topology_id for vertex in updated.vertices)


def test_triangle_body_mapping_keeps_disjoint_solids_separate() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.cylinder",
        {"radius": 3, "height": 5, "center": [-10, 0, 0], "mode": "new"},
    )
    kernel.apply(
        "feature.cylinder",
        {"radius": 4, "height": 5, "center": [10, 0, 0], "mode": "add"},
    )
    snapshot = kernel.viewport_data()[0]

    assert len(kernel.body_ids) == 2
    assert {face.body_id for face in snapshot.faces} == set(kernel.body_ids)
    assert {vertex.body_id for vertex in snapshot.vertices} == set(kernel.body_ids)
    assert set(snapshot.triangle_body_ids) == set(kernel.body_ids)
    assert all(
        triangle_body_id == face.body_id
        for triangle_body_id, face_id in zip(
            snapshot.triangle_body_ids,
            snapshot.triangle_face_ids,
            strict=True,
        )
        for face in snapshot.faces
        if face.topology_id == face_id
    )


def test_repeatable_at_same_tolerance() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    assert kernel.viewport_data(0.2, 15.0) == kernel.viewport_data(0.2, 15.0)


def test_finer_tolerance_does_not_lose_triangles() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    coarse = kernel.viewport_data(0.5, 30.0)
    fine = kernel.viewport_data(0.1, 15.0)
    assert len(fine[0].mesh.triangle_indices) >= len(coarse[0].mesh.triangle_indices)


def test_last_snapshot_matches_whole_model_tessellation() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    snapshots = kernel.viewport_data(0.2, 10.0)
    assert snapshots[0].mesh == kernel.tessellate(0.2, 10.0)


def test_current_mesh_is_cached_and_only_current_state_is_tessellated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    first = kernel.viewport_data()
    second = kernel.viewport_data()
    assert first == second
    assert len(calls) == 1
    assert kernel.viewport_state_ids() == tuple(f"feature.cylinder:{i}" for i in range(6))
    assert len(calls) == 1


def test_historical_mesh_is_generated_on_demand_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    assert kernel.viewport_data()
    assert len(calls) == 1
    first = kernel.historical_viewport_data("feature.cylinder:1", 0.5, 30.0)
    second = kernel.historical_viewport_data("feature.cylinder:1", 0.5, 30.0)
    assert first == second
    assert first is not None
    assert first.state_id == "feature.cylinder:1"
    assert len(calls) == 2
    fine = kernel.historical_viewport_data("feature.cylinder:1", 0.1, 15.0)
    assert fine is not None
    assert len(calls) == 3
    assert kernel.historical_viewport_data("feature.cylinder:1", 0.5, 30.0) == first
    assert len(calls) == 3


def test_current_mesh_cache_separates_tolerances_and_geometry_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    coarse = kernel.viewport_data(0.5, 30.0)
    fine = kernel.viewport_data(0.1, 15.0)
    assert len(calls) == 2
    assert fine[0].state_id == "feature.box:0"
    assert kernel.viewport_data(0.5, 30.0) == coarse
    assert len(calls) == 2

    kernel.apply("feature.box", {"size_x": 20, "size_y": 20, "size_z": 20})
    updated = kernel.viewport_data(0.5, 30.0)
    assert updated[0].state_id == "feature.box:1"
    assert updated != coarse
    assert len(calls) == 3


def test_history_mesh_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = BuildKernel()
    cache_limit = kernel_module.HISTORY_MESH_CACHE_MAX_ENTRIES
    for size in range(1, cache_limit + 3):
        kernel.apply("feature.box", {"size_x": size, "size_y": size, "size_z": size})
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    history_ids = kernel.viewport_state_ids()[:-1]
    for state_id in history_ids[:cache_limit]:
        kernel.historical_viewport_data(state_id)
    assert len(calls) == cache_limit

    kernel.historical_viewport_data(history_ids[0])
    assert len(calls) == cache_limit
    kernel.historical_viewport_data(history_ids[cache_limit])
    assert len(calls) == cache_limit + 1
    kernel.historical_viewport_data(history_ids[0])
    kernel.historical_viewport_data(history_ids[1])
    assert len(calls) == cache_limit + 2


def test_current_mesh_tolerance_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    cache_limit = kernel_module.CURRENT_MESH_CACHE_MAX_ENTRIES
    requests = tuple((0.1 + index, 15.0) for index in range(cache_limit + 1))
    for linear, angular in requests[:cache_limit]:
        kernel.viewport_data(linear, angular)
    assert len(calls) == cache_limit

    kernel.viewport_data(*requests[0])
    assert len(calls) == cache_limit
    kernel.viewport_data(*requests[cache_limit])
    assert len(calls) == cache_limit + 1
    kernel.viewport_data(*requests[0])
    kernel.viewport_data(*requests[1])
    assert len(calls) == cache_limit + 2


def test_reset_and_state_replacement_do_not_reuse_stale_meshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    kernel.apply("feature.box", {"size_x": 12, "size_y": 12, "size_z": 12})
    first = kernel.viewport_data()[0].mesh
    first_history = kernel.historical_viewport_data("feature.box:0")
    assert first_history is not None
    original = kernel_module.build_tessellation
    calls: list[object] = []

    def count_calls(part: Part | None, linear: object, angular: object) -> Tessellation:
        calls.append(part)
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    kernel.reset()
    kernel.apply("feature.box", {"size_x": 20, "size_y": 20, "size_z": 20})
    kernel.apply("feature.box", {"size_x": 22, "size_y": 22, "size_z": 22})
    second = kernel.viewport_data()[0].mesh
    second_history = kernel.historical_viewport_data("feature.box:0")
    assert second_history is not None
    assert second != first
    assert second_history.mesh != first_history.mesh
    assert len(calls) == 2

    candidate = BuildKernel()
    candidate.apply("feature.box", {"size_x": 30, "size_y": 30, "size_z": 30})
    candidate.apply("feature.box", {"size_x": 32, "size_y": 32, "size_z": 32})
    kernel.replace_state_from(candidate)
    third = kernel.viewport_data()[0].mesh
    third_history = kernel.historical_viewport_data("feature.box:0")
    assert third_history is not None
    assert third != second
    assert third_history.mesh != second_history.mesh
    assert len(calls) == 4


def test_empty_result_keeps_snapshot_position_and_matches_current_geometry(tmp_path: Path) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    kernel.apply("feature.box", {"size_x": 20, "size_y": 20, "size_z": 20, "mode": "cut"})
    snapshots = kernel.viewport_data()
    assert len(snapshots) == 1
    first_history = kernel.historical_viewport_data("feature.box:0")
    assert first_history is not None
    assert first_history.mesh.triangle_indices
    assert not snapshots[0].mesh.vertices
    assert not snapshots[0].mesh.triangle_indices
    assert kernel.mass_properties().solid_count == 0
    for extension, export in (("step", kernel.export_step), ("stl", kernel.export_stl)):
        path = tmp_path / f"empty.{extension}"
        with pytest.raises(EmptyGeometryError):
            export(path)
        assert not path.exists()
    kernel.apply("feature.box", {"size_x": 5, "size_y": 5, "size_z": 5})
    assert kernel.viewport_state_ids() == (
        "feature.box:0",
        "feature.box:1",
        "feature.box:2",
    )
