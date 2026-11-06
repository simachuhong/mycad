# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bound hole commands preserve design source and placement through real replay."""

from __future__ import annotations

from dataclasses import replace
from math import pi
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from build123d import CenterOf

from mycad import app
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.persistence import document_payload, save_document
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.topology_evolution import TopologyEvolution
from mycad.geom.kernel import BuildKernel


def model() -> tuple[app.AppServices, app.LoadedDocument]:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    return services, loaded


def binding(identity: str, role: str = "box.+Z") -> dict[str, object]:
    return {"kind": "bound_face", "source_instance_id": identity, "role": role}


def hole(target: dict[str, object], u: float = -4, v: float = 3) -> dict[str, object]:
    return {
        "target_face": target,
        "position": {"kind": "local", "uv_mm": [u, v]},
        "diameter": 2,
        "depth": {"kind": "blind", "value": 2},
    }


def assert_hole_axis(
    services: app.AppServices,
    center: tuple[float, float, float],
    axis: str,
    lower: float,
    upper: float,
) -> None:
    wall = services.kernel.resolve_face({"surface": "cylinder", "radius_mm": 1}, "measure-test")
    actual = wall.center(CenterOf.MASS)
    assert pytest.approx(center, abs=1e-6) == (actual.X, actual.Y, actual.Z)
    bounds = wall.bounding_box()
    dimensions = {
        "X": (bounds.min.X, bounds.max.X),
        "Y": (bounds.min.Y, bounds.max.Y),
        "Z": (bounds.min.Z, bounds.max.Z),
    }
    assert dimensions[axis] == pytest.approx((lower, upper))
    assert wall.radius == pytest.approx(1)


def test_bound_hole_replays_local_position_after_trim_resize_and_open(tmp_path: Path) -> None:
    services, loaded = model()
    assert services.registry.get("feature.hole").version == 3
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 4, "size_y": 24, "size_z": 10, "center": [9, 0, 0]}},
    )
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    before = loaded.document.commands
    loaded.bus.edit_and_replay(0, {"size_x": 20, "size_y": 20, "size_z": 8}, "local", "thicker")
    assert loaded.document.commands[0].instance_id == identity
    assert loaded.document.commands[0].timestamp_utc == before[0].timestamp_utc
    assert len(loaded.document.commands[0].amendments) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(2720 - 2 * pi)
    assert_hole_axis(services, (-4, 3, 3), "Z", 2, 4)
    path = tmp_path / "bound.my3d"
    save_document(loaded.document, path)
    isolated = app.fork_app_services(services)
    reopened = app.open_app_document(isolated, path)
    assert reopened.document.commands == loaded.document.commands
    assert isolated.kernel.mass_properties().volume == pytest.approx(2720 - 2 * pi)
    assert_hole_axis(isolated, (-4, 3, 3), "Z", 2, 4)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(2720)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(2720 - 2 * pi)


def test_binding_branch_requires_v5_without_upgrading_legacy_query() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    with pytest.raises(ValidationError):
        loaded.bus.execute("feature.hole", hole(binding("a" * 32)))
    assert loaded.document.archive_version == 4
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 2,
            "depth": {"kind": "through_all"},
        },
    )
    assert loaded.document.archive_version == 4


@pytest.mark.parametrize("radius", [10.0, 5.0, 8.0])
def test_equal_or_size_flipped_bodies_keep_left_source(radius: float) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.cylinder", {"radius": 10, "height": 6, "center": [-20, 0, 0]})
    left_id = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "feature.cylinder", {"radius": 8, "height": 6, "center": [20, 0, 0], "mode": "add"}
    )
    loaded.bus.execute("feature.hole", hole(binding(left_id, "cylinder.top"), 0, 0))
    loaded.bus.edit_and_replay(
        0, {"radius": radius, "height": 6, "center": [-20, 0, 0]}, "local", "resize left"
    )
    assert services.kernel.mass_properties().volume == pytest.approx(
        6 * pi * (radius**2 + 64) - 2 * pi
    )
    assert_hole_axis(services, (-20, 0, 2), "Z", 1, 3)


def test_split_source_fails_with_location_and_restores_previous_state() -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 4, "size_y": 24, "size_z": 10, "center": [9, 0, 0]}},
    )
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 4})
    redo_command = loaded.document.commands[-1]
    loaded.bus.undo()
    before = loaded.document.commands
    before_payload = document_payload(loaded.document)
    volume = services.kernel.mass_properties().volume
    with pytest.raises(TopologyReferenceError) as error:
        loaded.bus.edit_and_replay(
            1,
            {"tool": {"type": "box", "size_x": 4, "size_y": 24, "size_z": 10, "center": [0, 0, 0]}},
            "local",
            "split",
        )
    assert error.value.reason == "split"
    assert error.value.ordinal == 2
    assert error.value.parameter_path == "target_face"
    assert loaded.document.commands == before
    assert document_payload(loaded.document) == before_payload
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    loaded.bus.redo()
    assert loaded.document.commands[-1] == redo_command
    assert services.kernel.mass_properties().volume == pytest.approx(16 * pi)


@pytest.mark.parametrize(
    ("role", "center", "axis", "lower", "upper"),
    [
        ("box.+Z", (12, 23, 41), "Z", 40, 42),
        ("box.-Z", (12, 17, 19), "Z", 18, 20),
        ("box.+X", (19, 17, 32), "X", 18, 20),
        ("box.-X", (1, 23, 32), "X", 0, 2),
        ("box.+Y", (13, 30, 32), "Y", 29, 31),
        ("box.-Y", (7, 10, 32), "Y", 9, 11),
    ],
)
def test_each_box_role_has_fixed_outward_frame(
    role: str,
    center: tuple[float, float, float],
    axis: str,
    lower: float,
    upper: float,
) -> None:
    services, loaded = model()
    loaded.bus.execute(
        "feature.box", {"size_x": 20, "size_y": 22, "size_z": 24, "center": [10, 20, 30]}
    )
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute("feature.hole", hole(binding(identity, role), 2, 3))
    assert_hole_axis(services, center, axis, lower, upper)


@pytest.mark.parametrize(
    ("role", "center", "lower", "upper"),
    [
        ("cylinder.top", (2, 3, 2), 1, 3),
        ("cylinder.bottom", (2, -3, -2), -3, -1),
    ],
)
def test_cylinder_cap_local_frame(
    role: str, center: tuple[float, float, float], lower: float, upper: float
) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.cylinder", {"radius": 8, "height": 6})
    loaded.bus.execute(
        "feature.hole",
        hole(binding(cast("str", loaded.document.commands[0].instance_id), role), 2, 3),
    )
    assert_hole_axis(services, center, "Z", lower, upper)


def test_pick_mints_binding_and_rejects_stale_foreign_and_generated_faces() -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    snapshot = services.kernel.viewport_data()[-1]
    top = next(
        face
        for face in snapshot.faces
        if services.kernel.interactive_face_frame(face.topology_id).normal == (0, 0, 1)
    )
    target = services.kernel.interactive_face_binding(top.topology_id)
    assert target == binding(cast("str", loaded.document.commands[0].instance_id))
    other, _other_loaded = model()
    with pytest.raises(TopologyReferenceError):
        other.kernel.interactive_face_binding(top.topology_id)
    loaded.bus.execute("feature.hole", hole(target))
    with pytest.raises(TopologyReferenceError):
        services.kernel.interactive_face_binding(top.topology_id)
    rejected = 0
    for face in services.kernel.viewport_data()[-1].faces:
        try:
            services.kernel.interactive_face_frame(face.topology_id)
        except TopologyReferenceError:
            with pytest.raises(TopologyReferenceError):
                services.kernel.interactive_face_binding(face.topology_id)
            rejected += 1
    assert rejected == 1  # The newly generated cylindrical hole wall.


@pytest.mark.parametrize(
    ("change", "reason"),
    [("replace", "deleted"), ("merge", "merged"), ("unsupported", "unsupported-operation")],
)
def test_invalidated_source_never_falls_back_to_another_face(change: str, reason: str) -> None:
    _services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    if change == "replace":
        loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    elif change == "merge":
        loaded.bus.execute(
            "feature.box",
            {"size_x": 20, "size_y": 20, "size_z": 6, "center": [20, 0, 0], "mode": "add"},
        )
    else:
        loaded.bus.execute(
            "modify.chamfer",
            {
                "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}], "curve": "line"}],
                "distance": 0.5,
            },
        )
    before = loaded.document.commands
    with pytest.raises(TopologyReferenceError) as error:
        loaded.bus.execute("feature.hole", hole(binding(identity)))
    assert error.value.reason == reason
    assert loaded.document.commands == before


def test_unknown_owner_and_removed_local_region_fail_without_history_mutation() -> None:
    _services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    with pytest.raises(TopologyReferenceError, match="no-match"):
        loaded.bus.execute("feature.hole", hole(binding("a" * 32)))
    loaded.bus.execute("feature.hole", hole(binding(identity), 0, 0))
    before = loaded.document.commands
    with pytest.raises(TopologyReferenceError) as error:
        loaded.bus.execute("feature.hole", hole(binding(identity), 0, 0))
    assert error.value.reason == "outside-face"
    assert error.value.parameter_path == "position"
    assert loaded.document.commands == before


def test_two_cuts_then_bound_hole_and_live_pick() -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 4, "size_y": 24, "size_z": 10, "center": [9, 0, 0]}},
    )
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "point", "point": [2, 0, 3]},
            "diameter": 4,
            "depth": {"kind": "through_all"},
        },
    )
    target = next(
        services.kernel.interactive_face_binding(face.topology_id)
        for face in services.kernel.viewport_data()[-1].faces
        if services.kernel.interactive_face_selector(face.topology_id).get("axis") == "+Z"
    )
    assert target == binding(identity)
    loaded.bus.execute("feature.hole", hole(target))
    assert services.kernel.mass_properties().volume == pytest.approx(2040 - 26 * pi)
    assert_hole_axis(services, (-4, 3, 2), "Z", 1, 3)


@pytest.mark.parametrize("primitive", ["box", "cylinder"])
def test_primitive_cut_keeps_original_face_but_does_not_bind_tool_faces(primitive: str) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    dimensions: dict[str, object] = (
        {"size_x": 4, "size_y": 24, "size_z": 10}
        if primitive == "box"
        else {"radius": 3, "height": 10}
    )
    loaded.bus.execute(f"feature.{primitive}", {**dimensions, "center": [9, 0, 0], "mode": "cut"})
    tool_id = cast("str", loaded.document.commands[-1].instance_id)
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    assert_hole_axis(services, (-4, 3, 2), "Z", 1, 3)
    with pytest.raises(TopologyReferenceError, match="no-match"):
        loaded.bus.execute(
            "feature.hole",
            hole(binding(tool_id, "box.+Z" if primitive == "box" else "cylinder.top")),
        )


@pytest.mark.parametrize("remove", [False, True])
def test_missing_history_or_deleted_face_fails_safely(
    monkeypatch: pytest.MonkeyPatch, remove: bool
) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    if not remove:

        def discard(_e: TopologyEvolution) -> None:
            pass

        monkeypatch.setattr(services.kernel, "_capture_topology_evolution", discard)
    loaded.bus.execute(
        "modify.boolean_cut",
        {
            "tool": {
                "type": "box",
                "size_x": 40 if remove else 4,
                "size_y": 40,
                "size_z": 10,
                "center": [0, 0, 0] if remove else [9, 0, 0],
            }
        },
    )
    with pytest.raises(TopologyReferenceError) as error:
        loaded.bus.execute("feature.hole", hole(binding(identity)))
    assert error.value.reason == ("deleted" if remove else "unknown")


def test_bound_preview_is_isolated_and_measures_the_actual_hole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    before = document_payload(loaded.document)
    scratch = BuildKernel()
    monkeypatch.setattr(app, "BuildKernel", lambda: scratch)
    app.preview_command(services, loaded.document.commands, "feature.hole", hole(binding(identity)))
    assert_hole_axis(replace(services, kernel=scratch), (-4, 3, 2), "Z", 1, 3)
    assert document_payload(loaded.document) == before
    assert services.kernel.mass_properties().volume == pytest.approx(2400)
    with pytest.raises(TopologyReferenceError):
        app.preview_command(
            services, loaded.document.commands, "feature.hole", hole(binding("a" * 32))
        )
    assert document_payload(loaded.document) == before
    assert services.kernel.mass_properties().volume == pytest.approx(2400)


def test_save_as_keeps_binding_and_redo_then_opens_exactly(tmp_path: Path) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    commands = loaded.document.commands
    loaded.bus.undo()
    _same_services, copied = app.copy_app_document(services, loaded.document, source_bus=loaded.bus)
    assert copied.document.file_id != loaded.document.file_id
    copied.bus.redo()
    assert copied.document.commands == commands
    assert_hole_axis(services, (-4, 3, 2), "Z", 1, 3)
    path = tmp_path / "copy.my3d"
    save_document(copied.document, path)
    isolated = app.fork_app_services(services)
    reopened = app.open_app_document(isolated, path)
    assert reopened.document.commands == commands
    assert_hole_axis(isolated, (-4, 3, 2), "Z", 1, 3)


def test_bound_part_snapshot_replays_in_its_own_document_scope(tmp_path: Path) -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    source = app.reference_parameters(loaded.document)
    host_services = app.fork_app_services(services)
    host = app.new_workspace_document(host_services, kind="drawing")
    host.bus.apply_identity_upgrade(host.bus.prepare_identity_upgrade())
    host.bus.execute("reference.attach", source)
    assert_hole_axis(host_services, (-4, 3, 2), "Z", 1, 3)
    for face in host_services.kernel.viewport_data()[-1].faces:
        with pytest.raises(TopologyReferenceError):
            host_services.kernel.interactive_face_binding(face.topology_id)
    path = tmp_path / "bound-source.my2d"
    save_document(host.document, path)
    isolated = app.fork_app_services(host_services)
    app.open_app_document(isolated, path)
    assert_hole_axis(isolated, (-4, 3, 2), "Z", 1, 3)


def test_sketch_consumer_regeneration_keeps_bound_face_and_native_pick() -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    circle_id, sketch_id = uuid4().hex, uuid4().hex
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle_id, "geometry"),), 2.0, "mm"
    )
    sketch = Sketch(
        sketch_id,
        replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 3)),
        (CircleEntity(circle_id, (4, 0), 2),),
        (radius,),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    loaded.bus.execute(
        "feature.hole",
        {
            "profile": {"type": "sketch", "sketch_id": sketch_id},
            "target_face": {"surface": "plane", "axis": "+Z"},
            "depth": {"kind": "through_all"},
        },
    )
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    current = services.kernel.sketches[0]
    revised = replace(radius, value=3.0)
    proposal = services.kernel.preview_sketch_constraint_update(current, revised)
    assert proposal.status == "success", proposal.message
    loaded.bus.execute("sketch.constraint.update", proposal.command_params(current, revised))
    assert services.kernel.mass_properties().volume == pytest.approx(2400 - 56 * pi)
    assert_hole_axis(services, (-4, 3, 2), "Z", 1, 3)
    target = next(
        services.kernel.interactive_face_binding(face.topology_id)
        for face in services.kernel.viewport_data()[-1].faces
        if services.kernel.interactive_face_selector(face.topology_id).get("axis") == "+Z"
    )
    assert target == binding(identity)


def test_bound_box_face_survives_disjoint_sphere_cut() -> None:
    services, loaded = model()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    identity = cast("str", loaded.document.commands[0].instance_id)
    loaded.bus.execute("feature.sphere", {"radius": 2, "center": [40, 0, 0], "mode": "cut"})
    loaded.bus.execute("feature.hole", hole(binding(identity)))
    assert services.kernel.mass_properties().volume == pytest.approx(2400 - 2 * pi)
    assert_hole_axis(services, (-4, 3, 2), "Z", 1, 3)
