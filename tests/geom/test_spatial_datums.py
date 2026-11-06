# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document-history datum definitions drive dependent sketch solids on replay."""

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame


def coordinate(x: float) -> dict[str, object]:
    return {
        "name": "machine",
        "parent": {"kind": "world"},
        "origin_mm": [x, 20, 30],
        "x_axis": [0, 1, 0],
        "y_axis": [-1, 0, 0],
        "z_axis": [0, 0, 1],
    }


def ref(kind: str, source: str, role: str) -> dict[str, object]:
    return {"kind": kind, "source_instance_id": source, "role": role}


def test_empty_candidate_exposes_isolated_datum_and_commit_replays_it() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=19)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("datum.coordinate_system.create", 1, coordinate(10), "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=19,
    )
    preview = candidate.preview(current_session_identity=19)
    assert preview.state == "succeeded"
    datums = preview.datums
    assert len(datums) == 1
    datum = datums[0]
    assert datum.name == "machine"
    assert datum.reference.source_instance_id == preview.proposal.commands[0].instance_id
    assert datum.frame.origin_mm == pytest.approx((10, 20, 30))
    assert services.kernel.datum_display_data() == ()
    candidate.commit(
        candidate.authorize_commit(current_session_identity=19), current_session_identity=19
    )
    assert services.kernel.datum_display_data() == datums
    loaded.bus.undo()
    assert services.kernel.datum_display_data() == ()
    loaded.bus.redo()
    assert services.kernel.datum_display_data() == datums


def test_datum_sketch_extrusion_replays_after_parent_edit_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=9)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("datum.coordinate_system.create", 1, coordinate(10), "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=9,
    )
    preview = candidate.preview(current_session_identity=9)
    again = candidate.preview(current_session_identity=9)
    assert preview.state == again.state == "succeeded"
    assert preview.proposal.digest == again.proposal.digest
    assert preview.proposal.commands[0].instance_id == again.proposal.commands[0].instance_id
    assert loaded.document.archive_version == 4
    grant = candidate.authorize_commit(current_session_identity=9)
    candidate.commit(grant, current_session_identity=9)
    source = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "datum.plane.create",
        {
            "name": "base",
            "construction": {
                "kind": "principal",
                "coordinate_system": ref("coordinate_system", source, "coordinate_system"),
                "plane": "xy",
            },
        },
    )
    base = cast("str", loaded.document.commands[1].instance_id)
    loaded.bus.execute(
        "datum.plane.create",
        {
            "name": "offset",
            "construction": {
                "kind": "offset",
                "plane": ref("datum_plane", base, "plane"),
                "distance_mm": 20,
            },
        },
    )
    offset = cast("str", loaded.document.commands[2].instance_id)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (2, 3), 4),))
    params = sketch.to_mapping(version=3)
    params.pop("frame")
    params["support"] = {
        "plane": ref("datum_plane", offset, "plane"),
        "offset_uv_mm": [0, 0],
        "rotation_deg": 0,
        "flip_normal": False,
    }
    loaded.bus.execute("sketch.create", params, version=4)
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
    )
    frame = services.kernel.sketches[0].frame
    assert frame.origin_mm == pytest.approx((10, 20, 50))
    assert frame.local_to_world((2, 3)) == pytest.approx((7, 22, 50))
    assert services.kernel.mass_properties().volume == pytest.approx(80 * 3.141592653589793)
    loaded.bus.edit_and_replay(0, coordinate(25), "local", "move coordinate")
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((25, 20, 50))
    assert services.kernel.sketches[0].entities == sketch.entities
    before = document_payload(loaded.document)
    invalid = {**coordinate(25), "x_axis": [2, 0, 0]}
    with pytest.raises(ValidationError):
        loaded.bus.edit_and_replay(0, invalid, "local", "invalid coordinate")
    assert document_payload(loaded.document) == before
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((25, 20, 50))
    assert services.kernel.mass_properties().volume == pytest.approx(80 * 3.141592653589793)
    path = tmp_path / "datum.my3d"
    save_document(loaded.document, path)
    other = app.fork_app_services(services)
    reopened = app.open_app_document(other, path)
    assert reopened.document.commands == loaded.document.commands
    assert other.kernel.sketches[0].frame.origin_mm == pytest.approx((25, 20, 50))
    reopened.bus.execute(
        "datum.plane.create",
        {
            "name": "after reopen",
            "construction": {
                "kind": "offset",
                "plane": ref("datum_plane", offset, "plane"),
                "distance_mm": 5,
            },
        },
    )
    new_plane = cast("str", reopened.document.commands[-1].instance_id)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 1),))
    second_params = second.to_mapping(version=3)
    second_params.pop("frame")
    second_params["support"] = {
        "plane": ref("datum_plane", new_plane, "plane"),
        "offset_uv_mm": [0, 0],
        "rotation_deg": 0,
        "flip_normal": False,
    }
    reopened.bus.execute("sketch.create", second_params, version=4)
    assert other.kernel.sketches[-1].frame.origin_mm == pytest.approx((25, 20, 55))
    loaded.bus.undo()
    assert len(loaded.document.commands) == 4
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(80 * 3.141592653589793)

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    current = services.kernel.sketches[0]
    constraint = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(sketch.entities[0].entity_id, "geometry"),),
        7,
        "mm",
    )
    result = solve_sketch_constraint(current, constraint)
    assert result.status == "success", result.message
    loaded.bus.execute("sketch.constraint.add", result.command_params(current, constraint))
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((25, 20, 50))
    assert services.kernel.mass_properties().volume == pytest.approx(245 * 3.141592653589793)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(80 * 3.141592653589793)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(245 * 3.141592653589793)


def test_bad_or_forward_datum_reference_does_not_change_history() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=3)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=3
    )
    assert candidate.preview(current_session_identity=3).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=3), current_session_identity=3
    )
    before = document_payload(loaded.document)
    with pytest.raises(TopologyReferenceError):
        loaded.bus.execute(
            "datum.plane.create",
            {
                "name": "bad",
                "construction": {
                    "kind": "offset",
                    "plane": ref("datum_plane", uuid4().hex, "plane"),
                    "distance_mm": 1,
                },
            },
        )
    assert document_payload(loaded.document) == before


def test_failed_datum_candidate_reports_parameter_and_preserves_source() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    before = document_payload(loaded.document)
    candidate = app.create_replay_candidate(services, loaded, session_identity=8)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "datum.plane.create",
                    1,
                    {
                        "name": "missing",
                        "construction": {
                            "kind": "offset",
                            "plane": ref("datum_plane", uuid4().hex, "plane"),
                            "distance_mm": 1,
                        },
                    },
                    None,
                ),
            ),
            False,
            target_archive_version=6,
        ),
        current_session_identity=8,
    )
    result = candidate.preview(current_session_identity=8)
    assert result.state == "failed"
    assert result.failure is not None
    assert result.failure.ordinal == 0
    assert result.failure.parameter_path == "construction.plane"
    assert result.failure.reason == "missing-reference"
    assert document_payload(loaded.document) == before
    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=8)


def test_datum_sketch_local_offset_rotation_and_flip_are_deterministic() -> None:
    from mycad.geom.spatial_datums import associated_frame

    identity = uuid4().hex
    parent = WorkPlaneFrame.xy()
    frame = associated_frame(
        {
            "plane": ref("datum_plane", identity, "plane"),
            "offset_uv_mm": [3, 4],
            "rotation_deg": 90,
            "flip_normal": True,
        },
        {identity: ("datum_plane", parent)},
    )
    assert frame.origin_mm == pytest.approx((3, 4, 0))
    assert frame.u_axis == pytest.approx((0, -1, 0), abs=1e-12)
    assert frame.v_axis == pytest.approx((-1, 0, 0), abs=1e-12)
    assert frame.normal == pytest.approx((0, 0, -1))
    assert frame.local_to_world((2, 1)) == pytest.approx((2, 2, 0))


def test_relative_coordinate_chain_drives_plane_and_sketch_after_parent_edit() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=10)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=10
    )
    assert candidate.preview(current_session_identity=10).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=10), current_session_identity=10
    )
    loaded.bus.execute("datum.coordinate_system.create", coordinate(10))
    parent = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "datum.coordinate_system.create",
        {
            "name": "child",
            "parent": ref("coordinate_system", parent, "coordinate_system"),
            "origin_mm": [2, 3, 4],
            "x_axis": [1, 0, 0],
            "y_axis": [0, 1, 0],
            "z_axis": [0, 0, 1],
        },
    )
    child = cast("str", loaded.document.commands[1].instance_id)
    loaded.bus.execute(
        "datum.plane.create",
        {
            "name": "child xz",
            "construction": {
                "kind": "principal",
                "coordinate_system": ref("coordinate_system", child, "coordinate_system"),
                "plane": "xz",
            },
        },
    )
    principal = cast("str", loaded.document.commands[2].instance_id)
    loaded.bus.execute(
        "datum.plane.create",
        {
            "name": "offset",
            "construction": {
                "kind": "offset",
                "plane": ref("datum_plane", principal, "plane"),
                "distance_mm": 20,
            },
        },
    )
    plane = cast("str", loaded.document.commands[3].instance_id)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (2, 3), 4),))
    params = sketch.to_mapping(version=3)
    params.pop("frame")
    params["support"] = {
        "plane": ref("datum_plane", plane, "plane"),
        "offset_uv_mm": [0, 0],
        "rotation_deg": 0,
        "flip_normal": False,
    }
    loaded.bus.execute("sketch.create", params, version=4)
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
    )
    actual = services.kernel.sketches[0].frame
    assert actual.origin_mm == pytest.approx((-13, 22, 34))
    assert actual.local_to_world((2, 3)) == pytest.approx((-13, 24, 31))
    loaded.bus.edit_and_replay(0, coordinate(25), "local", "move parent")
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((2, 22, 34))
    assert services.kernel.sketches[0].entities == sketch.entities
    assert services.kernel.mass_properties().volume == pytest.approx(80 * 3.141592653589793)
