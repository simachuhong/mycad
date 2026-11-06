# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real geometry coverage for full-history isolated replay candidates."""

from __future__ import annotations

from math import pi
from typing import cast

import pytest
from build123d import CenterOf

from mycad import app
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet, ReplayEdit
from mycad.core.viewport_protocol import ViewportFace
from mycad.geom.kernel import BuildKernel


def test_v4_upgrade_and_bound_hole_candidate_has_expected_geometry() -> None:
    session_identity = 101
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    candidate = app.create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(ReplayChangeSet((), (), True), current_session_identity=session_identity)
    identity_preview = candidate.preview(current_session_identity=session_identity)

    assert identity_preview.state == "succeeded"
    assert identity_preview.viewport is not None
    candidate_kernel = cast(
        "BuildKernel",
        getattr(candidate, "_candidate_kernel"),  # noqa: B009
    )
    top_face = next(
        face
        for face in identity_preview.viewport.faces
        if candidate_kernel.interactive_face_frame(face.topology_id).normal[2] > 0.99
    )
    binding = candidate.interactive_face_binding(
        top_face.topology_id,
        generation=identity_preview.proposal.generation,
        current_session_identity=session_identity,
    )
    frame = candidate.interactive_bound_face_frame(
        top_face.topology_id,
        generation=identity_preview.proposal.generation,
        current_session_identity=session_identity,
    )
    assert frame.local_to_world((-4, 3)) == pytest.approx((-4, 3, 3))
    source_identity = identity_preview.proposal.commands[0].instance_id
    assert binding["source_instance_id"] == source_identity

    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "feature.hole",
                    3,
                    {
                        "target_face": binding,
                        "position": {"kind": "local", "uv_mm": [-4, 3]},
                        "diameter": 2,
                        "depth": {"kind": "blind", "value": 2},
                    },
                    None,
                ),
            ),
            True,
        ),
        current_session_identity=session_identity,
    )
    hole_preview = candidate.preview(current_session_identity=session_identity)

    assert hole_preview.state == "succeeded"
    assert hole_preview.viewport is not None
    assert hole_preview.proposal.commands[0].instance_id == source_identity
    assert hole_preview.proposal.commands[1].params["target_face"] == binding
    candidate_kernel = cast(
        "BuildKernel",
        getattr(candidate, "_candidate_kernel"),  # noqa: B009
    )
    assert candidate_kernel.mass_properties().volume == pytest.approx(2400 - 2 * pi)
    wall = candidate_kernel.resolve_face({"surface": "cylinder", "radius_mm": 1}, "test-hole")
    center = wall.center(CenterOf.MASS)
    assert pytest.approx((-4, 3, 2), abs=1e-6) == (center.X, center.Y, center.Z)
    bounds = wall.bounding_box()
    assert pytest.approx((1, 3)) == (bounds.min.Z, bounds.max.Z)
    assert wall.radius == pytest.approx(1)
    assert services.kernel.mass_properties().volume == pytest.approx(2400)
    assert loaded.document.archive_version == 4
    assert len(loaded.document.commands) == 1

    grant = candidate.authorize_commit(current_session_identity=session_identity)
    candidate.commit(grant, current_session_identity=session_identity)

    assert candidate.state == "committed"
    assert loaded.document.archive_version == 5
    assert loaded.document.commands == hole_preview.proposal.commands
    assert services.kernel.mass_properties().volume == pytest.approx(2400 - 2 * pi)
    actual_wall = services.kernel.resolve_face(
        {"surface": "cylinder", "radius_mm": 1}, "committed-hole"
    )
    actual_center = actual_wall.center(CenterOf.MASS)
    assert pytest.approx((-4, 3, 2), abs=1e-6) == (
        actual_center.X,
        actual_center.Y,
        actual_center.Z,
    )


def test_candidate_commits_upstream_and_downstream_bound_hole_repair() -> None:
    session_identity = 111
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20, "size_y": 20, "size_z": 6, "center": [-20, 0, 0]},
    )
    loaded.bus.execute(
        "feature.cylinder",
        {"radius": 8, "height": 6, "center": [20, 0, 0], "mode": "add"},
    )
    box_id = cast("str", loaded.document.commands[0].instance_id)
    cylinder_id = cast("str", loaded.document.commands[1].instance_id)
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"kind": "bound_face", "source_instance_id": box_id, "role": "box.+Z"},
            "position": {"kind": "local", "uv_mm": [0, 0]},
            "diameter": 2,
            "depth": {"kind": "blind", "value": 2},
        },
    )
    candidate = app.create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(ReplayChangeSet((), (), False), current_session_identity=session_identity)
    preview = candidate.preview(current_session_identity=session_identity)
    assert preview.state == "succeeded"
    assert preview.viewport is not None
    candidate_kernel = cast(
        "BuildKernel",
        getattr(candidate, "_candidate_kernel"),  # noqa: B009
    )

    def is_cylinder_top(face: ViewportFace) -> bool:
        try:
            frame = candidate_kernel.interactive_face_frame(face.topology_id)
        except TopologyReferenceError:
            return False
        return frame.normal[2] > 0.99 and frame.origin[0] > 15

    cylinder_top = next(face for face in preview.viewport.faces if is_cylinder_top(face))
    cylinder_binding = candidate.interactive_face_binding(
        cylinder_top.topology_id,
        generation=preview.proposal.generation,
        current_session_identity=session_identity,
    )
    source_revision = loaded.document.revision
    source_volume = services.kernel.mass_properties().volume
    assert source_volume == pytest.approx(2400 + 382 * pi)

    candidate.stage(
        ReplayChangeSet(
            (
                ReplayEdit(
                    1,
                    {"radius": 8, "height": 6, "center": [20, 0, 0], "mode": "new"},
                    "alice",
                    "replace the upstream body",
                ),
            ),
            (),
            False,
        ),
        current_session_identity=session_identity,
    )
    failed = candidate.preview(current_session_identity=session_identity)
    assert failed.state == "failed" and failed.scene is None
    assert failed.failure_scene is not None and failed.failure_scene.viewport is not None
    assert failed.failure is not None and failed.failure.ordinal == 2
    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=session_identity)
    candidate_kernel = cast("BuildKernel", getattr(candidate, "_candidate_kernel"))  # noqa: B009
    cylinder_top = next(
        face for face in failed.failure_scene.viewport.faces if is_cylinder_top(face)
    )
    cylinder_binding = candidate.interactive_failure_face_binding(
        cylinder_top.topology_id,
        generation=failed.proposal.generation,
        current_session_identity=session_identity,
    )
    assert cylinder_binding["source_instance_id"] == cylinder_id
    assert loaded.document.revision == source_revision

    candidate.stage(
        ReplayChangeSet(
            (
                ReplayEdit(
                    1,
                    {"radius": 8, "height": 6, "center": [20, 0, 0], "mode": "new"},
                    "alice",
                    "replace the upstream body",
                ),
                ReplayEdit(
                    2,
                    {
                        "target_face": cylinder_binding,
                        "position": {"kind": "local", "uv_mm": [0, 0]},
                        "diameter": 2,
                        "depth": {"kind": "blind", "value": 2},
                    },
                    "alice",
                    "rebind the downstream hole",
                ),
            ),
            (),
            False,
        ),
        current_session_identity=session_identity,
    )
    with pytest.raises(ValidationError):
        candidate.interactive_failure_face_binding(
            cylinder_top.topology_id,
            generation=failed.proposal.generation,
            current_session_identity=session_identity,
        )
    repaired = candidate.preview(current_session_identity=session_identity)

    assert repaired.state == "succeeded"
    assert repaired.proposal.commands[1].instance_id == cylinder_id
    assert repaired.proposal.commands[2].params["target_face"] == cylinder_binding
    assert len(repaired.proposal.commands[1].amendments) == 1
    assert len(repaired.proposal.commands[2].amendments) == 1
    assert loaded.document.revision == source_revision
    assert services.kernel.mass_properties().volume == pytest.approx(source_volume)

    grant = candidate.authorize_commit(current_session_identity=session_identity)
    candidate.commit(grant, current_session_identity=session_identity)

    assert loaded.document.revision == source_revision + 1
    assert loaded.document.commands == repaired.proposal.commands
    assert services.kernel.mass_properties().volume == pytest.approx(382 * pi)
    committed_wall = services.kernel.resolve_face(
        {"surface": "cylinder", "radius_mm": 1}, "repaired-hole"
    )
    center = committed_wall.center(CenterOf.MASS)
    assert pytest.approx((20, 0, 2), abs=1e-6) == (center.X, center.Y, center.Z)
