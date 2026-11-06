# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Candidate rendering and selection must consume the same isolated scene."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.spatial_frames import RigidFrame
from mycad.ui.viewport import GLViewport


def test_candidate_scene_picks_candidate_and_rejects_changed_source(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    candidate = app.create_replay_candidate(services, loaded, session_identity=24)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("feature.box", 1, {"size_x": 30, "size_y": 20, "size_z": 4}, "local"),),
            False,
        ),
        current_session_identity=24,
    )
    preview = candidate.preview(current_session_identity=24)
    scene = preview.scene
    assert scene is not None and scene.viewport is not None
    view.show_interaction_scene(
        scene,
        session_identity=24,
        is_current=lambda: candidate.is_scene_current(scene, current_session_identity=24),
    )
    target = view.selection_target_at(400, 300, "body")
    assert target is not None
    assert target.body_ids[0] in scene.viewport.triangle_body_ids
    assert target.body_ids[0] not in services.kernel.body_ids
    assert view.pick_at(400, 300)
    assert view.selection() == target
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("feature.box", 1, {"size_x": 14, "size_y": 14, "size_z": 4}, "local"),),
            False,
        ),
        current_session_identity=24,
    )
    assert view.selection_target_at(400, 300, "body") is None
    assert view.selection() is None
    loaded.bus.execute("feature.box", {"size_x": 4, "size_y": 4, "size_z": 2})
    assert view.selection_target_at(400, 300, "body") is None
    with pytest.raises(ValueError):
        view.show_interaction_scene(
            scene,
            session_identity=24,
            is_current=lambda: candidate.is_scene_current(scene, current_session_identity=24),
        )


def test_unbound_preview_does_not_pick_source_topology(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    snapshot = app.preview_command(
        services,
        loaded.document.commands,
        "feature.box",
        {"size_x": 30, "size_y": 20, "size_z": 4},
        source_archive_version=loaded.document.archive_version,
    )
    view.set_modeling_context_active(True)
    view.show_candidate_preview(snapshot, preserve_view=True)
    assert view.selection_target_at(400, 300, "body") is None
    view.clear_candidate_preview()
    assert view.selection_target_at(400, 300, "body") is not None


def test_source_scene_cannot_pick_old_geometry_between_write_and_refresh(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    before = view.selection_target_at(400, 300, "body")
    assert before is not None
    loaded.bus.execute("feature.box", {"size_x": 30, "size_y": 20, "size_z": 4})
    assert view.selection_target_at(400, 300, "body") is None
    assert view.interaction_snap_anchors() == ()
    view.refresh()
    after = view.selection_target_at(400, 300, "body")
    assert after is not None and after.body_ids != before.body_ids


def test_metadata_rebinds_source_scene_without_geometry_rebuild(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    count = view.rebuild_count()
    target = view.selection_target_at(400, 300, "body")
    loaded.document.set_metadata("part_name", "label")
    QApplication.processEvents()
    assert view.rebuild_count() == count
    assert view.selection_target_at(400, 300, "body") == target


def test_empty_candidate_renders_and_disambiguates_coincident_datums(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    coordinate = {
        "name": "坐标系",
        "parent": {"kind": "world"},
        "origin_mm": [0, 0, 0],
        "x_axis": [1, 0, 0],
        "y_axis": [0, 1, 0],
        "z_axis": [0, 0, 1],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("datum.coordinate_system.create", 1, coordinate, "local"),), False, 6
        ),
        current_session_identity=1,
    )
    candidate.preview(current_session_identity=1)
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    plane = {
        "name": "面",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xy",
        },
    }
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, plane, "local"),), False),
        current_session_identity=1,
    )
    scene = candidate.preview(current_session_identity=1).scene
    assert scene is not None
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    view.show_interaction_scene(
        scene,
        session_identity=1,
        is_current=lambda: candidate.is_scene_current(scene, current_session_identity=1),
    )
    hits = view.datum_targets_at(400, 300)
    assert {hit.name for hit in hits} == {"坐标系", "面"}
    assert len({hit.reference for hit in hits}) == 2
    assert view.datum_display_count() == 2
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(400, 300),
            QPointF(400, 300),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert view.preselected_datum() in {hit.reference for hit in hits}
    QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))
    assert view.preselected_datum() is None
    view.clear_candidate_preview()
    assert view.datum_display_count() == 1


def test_overlapping_datum_and_solid_can_both_be_selected(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    plane = {
        "name": "XY",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xy",
        },
    }
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, plane, "local"),), False, 6),
        current_session_identity=1,
    )
    candidate.preview(current_session_identity=1)
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    picked: list[object] = []
    view.datum_selection_changed.connect(picked.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert picked
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    selection = view.selection()
    assert selection is not None
    assert selection.kind == "body"


def test_datum_visibility_is_restored_with_document_view(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    plane = {
        "name": "XY",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xy",
        },
    }
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, plane, "local"),), False, 6),
        current_session_identity=1,
    )
    candidate.preview(current_session_identity=1)
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    reference = services.kernel.datum_display_data()[0].reference
    view.set_datum_visible(reference, False)
    saved = view.capture_view()
    view.bind_document(loaded)
    assert view.datum_display_count() == 1
    view.restore_view(saved)
    assert view.datum_display_count() == 0


def test_fit_view_includes_datums_without_solid_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    coordinate = {
        "name": "far",
        "parent": {"kind": "world"},
        "origin_mm": [500, 400, 300],
        "x_axis": [1, 0, 0],
        "y_axis": [0, 1, 0],
        "z_axis": [0, 0, 1],
    }
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("datum.coordinate_system.create", 1, coordinate, "local"),), False, 6
        ),
        current_session_identity=1,
    )
    scene = candidate.preview(current_session_identity=1).scene
    assert scene is not None
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.show_interaction_scene(
        scene,
        session_identity=1,
        is_current=lambda: candidate.is_scene_current(scene, current_session_identity=1),
    )
    view.fit_view()
    projected = view.project_world_point((500, 400, 300))
    assert projected is not None
    assert 0 <= projected[0] <= 800 and 0 <= projected[1] <= 600


def test_coordinate_axis_is_selectable_away_from_origin(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    coordinate = {
        "name": "axis",
        "parent": {"kind": "world"},
        "origin_mm": [0, 0, 0],
        "x_axis": [1, 0, 0],
        "y_axis": [0, 1, 0],
        "z_axis": [0, 0, 1],
    }
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("datum.coordinate_system.create", 1, coordinate, "local"),), False, 6
        ),
        current_session_identity=1,
    )
    scene = candidate.preview(current_session_identity=1).scene
    assert scene is not None
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.show_interaction_scene(
        scene,
        session_identity=1,
        is_current=lambda: candidate.is_scene_current(scene, current_session_identity=1),
    )
    view.set_orientation("top")
    target = view.project_world_point((15, 0, 0))
    origin = view.project_world_point((0, 0, 0))
    assert target is not None and origin is not None
    assert ((target[0] - origin[0]) ** 2 + (target[1] - origin[1]) ** 2) ** 0.5 > 12
    assert view.datum_targets_at(*target)[0].name == "axis"


def test_look_at_tilted_workplane_preserves_model_frame(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    plane = RigidFrame.identity().principal_plane("xz")
    view.look_at_workplane(plane)
    ray = view.camera_ray(400, 300)
    assert ray is not None
    assert ray[1] == pytest.approx(tuple(-value for value in plane.normal), abs=1e-6)
    assert plane.origin_mm == (0, 0, 0)
    assert loaded.document.commands == ()
