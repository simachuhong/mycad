# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Constraints in datum-local coordinates survive changes to their parent frame."""

from dataclasses import replace
from math import pi
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_local_constraint_replays_after_associated_datum_moves(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    coordinate: dict[str, object] = {
        "name": "CS",
        "parent": {"kind": "world"},
        "origin_mm": [0, 0, 0],
        "x_axis": [1, 0, 0],
        "y_axis": [0, 1, 0],
        "z_axis": [0, 0, 1],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=18)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("datum.coordinate_system.create", 1, coordinate, "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=18,
    )
    assert candidate.preview(current_session_identity=18).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=18), current_session_identity=18
    )
    coordinate_id = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "datum.plane.create",
        {
            "name": "P",
            "construction": {
                "kind": "principal",
                "coordinate_system": {
                    "kind": "coordinate_system",
                    "source_instance_id": coordinate_id,
                    "role": "coordinate_system",
                },
                "plane": "xy",
            },
        },
    )
    plane_id = cast("str", loaded.document.commands[1].instance_id)
    circle = CircleEntity(uuid4().hex, (2, 3), 4)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    params = sketch.to_mapping(version=3)
    params.pop("frame")
    params["support"] = {
        "plane": {"kind": "datum_plane", "source_instance_id": plane_id, "role": "plane"},
        "offset_uv_mm": [0, 0],
        "rotation_deg": 0,
        "flip_normal": False,
    }
    loaded.bus.execute("sketch.create", params, version=4)
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
    )
    current = services.kernel.sketches[0]
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 6, "mm"
    )
    solution = services.kernel.preview_sketch_constraint(current, radius)
    assert solution.status == "success", solution.message
    loaded.bus.execute(
        "sketch.constraint.add",
        solution.command_params(current, radius, local_frame=True),
        version=4,
    )

    moved = {**coordinate, "origin_mm": [15, 0, 0]}
    loaded.bus.edit_and_replay(0, moved, "local", "move datum parent")
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((15, 0, 0))
    assert services.kernel.mass_properties().volume == pytest.approx(180 * pi)

    current = services.kernel.sketches[0]
    revised = replace(radius, value=7)
    update = services.kernel.preview_sketch_constraint_update(current, revised)
    assert update.status == "success", update.message
    loaded.bus.execute(
        "sketch.constraint.update",
        update.command_params(current, revised, local_frame=True),
        version=2,
    )
    moved_again = {**coordinate, "origin_mm": [20, 0, 0]}
    loaded.bus.edit_and_replay(0, moved_again, "local", "move datum again")
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((20, 0, 0))
    assert services.kernel.mass_properties().volume == pytest.approx(245 * pi)

    accepted = document_payload(loaded.document)
    outdated = update.command_params(current, revised, local_frame=True)
    with pytest.raises(ValidationError, match="stale"):
        loaded.bus.execute("sketch.constraint.update", outdated, version=2)
    assert document_payload(loaded.document) == accepted
    assert services.kernel.mass_properties().volume == pytest.approx(245 * pi)

    path = tmp_path / "associated.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    reopened = app.open_app_document(reopened_services, path)
    assert reopened.document.commands == loaded.document.commands
    assert reopened_services.kernel.sketches[0].frame.origin_mm == pytest.approx((20, 0, 0))
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(245 * pi)

    current = reopened_services.kernel.sketches[0]
    line = LineEntity(uuid4().hex, (0, 0), (1, 0), construction=True)
    modified = replace(current, entities=(*current.entities, line))
    frozen = modified.to_mapping(version=3)
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": frozen["entities"],
        "constraints": frozen["constraints"],
    }
    draft = app.create_replay_candidate(reopened_services, reopened, session_identity=25)
    draft.stage(
        ReplayChangeSet((), (ReplayAppend("sketch.revise", 1, revision, "local"),), False),
        current_session_identity=25,
    )
    assert draft.preview(current_session_identity=25).state == "succeeded"
    assert reopened_services.kernel.sketches[0] == current
    draft.commit(draft.authorize_commit(current_session_identity=25), current_session_identity=25)
    assert reopened_services.kernel.sketches[0].entities == modified.entities
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(245 * pi)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0] == current
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == modified.entities

    current = reopened_services.kernel.sketches[0]
    changed_circle = replace(cast("CircleEntity", current.entities[0]), radius_mm=8)
    invalid = replace(current, entities=(changed_circle, *current.entities[1:]))
    bad_revision = {
        **revision,
        "base_state_sha256": current.local_state_digest(),
        "entities": invalid.to_mapping(version=3)["entities"],
    }
    before = document_payload(reopened.document)
    failing = app.create_replay_candidate(reopened_services, reopened, session_identity=25)
    failing.stage(
        ReplayChangeSet((), (ReplayAppend("sketch.revise", 1, bad_revision, "local"),), False),
        current_session_identity=25,
    )
    result = failing.preview(current_session_identity=25)
    assert result.state == "failed"
    assert result.failure is not None
    assert result.failure.command_id == "sketch.revise"
    assert "violates existing constraints" in result.failure.reason
    assert document_payload(reopened.document) == before
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(245 * pi)

    moved_final = {**coordinate, "origin_mm": [30, 0, 0]}
    reopened.bus.edit_and_replay(0, moved_final, "local", "move revised sketch parent")
    current = reopened_services.kernel.sketches[0]
    assert current.frame.origin_mm == pytest.approx((30, 0, 0))
    assert current.entities[1] == line
    revised_again = replace(radius, value=8)
    solved_again = reopened_services.kernel.preview_sketch_constraint_update(current, revised_again)
    assert solved_again.status == "success", solved_again.message
    reopened.bus.execute(
        "sketch.constraint.update",
        solved_again.command_params(current, revised_again, local_frame=True),
        version=2,
    )
    assert reopened_services.kernel.sketches[0].entities[1] == line
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(320 * pi)
