# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Snapshot-semantics viewport tests (phase 1, todo 3).

BuildKernel must expose one mesh snapshot per successful ``apply``; the
undo/redo rebuild path resets the kernel and re-applies the whole
history, so the snapshot list is naturally rebuilt in ordinal order.
"""

from __future__ import annotations

from mycad.core.viewport_protocol import ViewportData, ViewportPort
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
    assert len(snapshots) == 6
    assert [s.feature_id for s in snapshots] == [f"feature.cylinder:{i}" for i in range(6)]
    assert all(isinstance(snapshot, ViewportData) for snapshot in snapshots)
    assert all(len(snapshot.mesh.vertices) > 0 for snapshot in snapshots)


def test_repeatable_at_same_tolerance() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    assert kernel.viewport_data(0.2, 15.0) == kernel.viewport_data(0.2, 15.0)


def test_finer_tolerance_does_not_lose_triangles() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    coarse = kernel.viewport_data(0.5, 30.0)
    fine = kernel.viewport_data(0.1, 15.0)
    assert all(
        len(coarse_snapshot.mesh.triangle_indices) <= len(fine_snapshot.mesh.triangle_indices)
        for coarse_snapshot, fine_snapshot in zip(coarse, fine, strict=True)
    )


def test_last_snapshot_matches_whole_model_tessellation() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    snapshots = kernel.viewport_data(0.2, 10.0)
    assert snapshots[-1].mesh == kernel.tessellate(0.2, 10.0)
