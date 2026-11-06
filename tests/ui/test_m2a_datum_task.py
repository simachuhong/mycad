# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum tasks preview isolated candidates before an explicit Bus commit."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.spatial_references import SpatialReference
from mycad.ui.datum_task import DatumTaskDialog
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport


def test_empty_part_datum_task_cancel_and_commit(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    before = document_payload(loaded.document)
    dialog = DatumTaskDialog(services, loaded, view, session_identity=7)
    qtbot.addWidget(dialog)
    dialog.name_field.setText("工作坐标")
    dialog.preview()
    assert dialog.confirm_button.isEnabled()
    assert view.datum_display_count() == 1
    assert document_payload(loaded.document) == before
    dialog.reject()
    assert document_payload(loaded.document) == before
    assert view.datum_display_count() == 0
    dialog = DatumTaskDialog(services, loaded, view, session_identity=7)
    qtbot.addWidget(dialog)
    dialog.name_field.setText("工作坐标")
    dialog.preview()
    dialog.confirm()
    assert loaded.document.archive_version == 6
    assert loaded.document.commands[-1].id == "datum.coordinate_system.create"
    assert services.kernel.datum_display_data()[0].name == "工作坐标"


def test_v4_datum_preview_cancel_preserves_redo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    loaded.bus.undo()
    before = document_payload(loaded.document)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=3)
    qtbot.addWidget(task)
    task.preview()
    assert task.confirm_button.isEnabled()
    assert loaded.document.archive_version == 4
    task.reject()
    assert document_payload(loaded.document) == before
    loaded.bus.redo()
    assert loaded.document.commands[-1].id == "feature.cylinder"


def test_main_window_exposes_datum_command_and_opens_task(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    assert window.command_palette.apply_filter("datum.coordinate_system.create") == 1
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    dialog = window.datum_task
    assert dialog is not None
    assert dialog.isVisible()
    dialog.reject()


def test_main_window_datum_task_uses_viewport_external_command_strip(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1024, 768)
    window.show()
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    bar = window.findChild(QToolBar, "datumCommandBar")
    assert task is not None and bar is not None
    assert bar.isVisible() and bar.isAncestorOf(task) and not task.isWindow()
    assert bar.mapToGlobal(QPoint(0, bar.height())).y() <= window.viewport.mapToGlobal(QPoint()).y()
    for button in (task.confirm_button, task.cancel_button):
        assert button.isVisible()
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
    task.preview()
    assert task.confirm_button.isEnabled()
    assert not loaded.document.commands
    task.cancel_button.click()
    assert window.datum_task is None
    assert not loaded.document.commands
    assert window.viewport.datum_display_count() == 0


def test_datum_strip_has_own_row_in_part_document_session(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.removeToolBarBreak(window.part_sketch_entry_toolbar)
    window.resize(1024, 768)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    bar = window.findChild(QToolBar, "datumCommandBar")
    assert bar is not None and window.datum_task is not None
    qtbot.wait(350)
    assert window.toolBarBreak(bar)
    assert bar.width() >= window.width() - 20
    assert (
        bar.y() >= window.part_sketch_entry_toolbar.y() + window.part_sketch_entry_toolbar.height()
    )
    window.datum_task.reject()
    window.command_palette.command_activated.emit("datum.plane.create")
    replacement = window.findChild(QToolBar, "datumCommandBar")
    assert replacement is not None and window.datum_task is not None
    assert window.toolBarBreak(replacement)
    window.datum_task.reject()


def test_datum_command_strip_disables_actions_while_execution_is_busy(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    assert task is not None
    task.preview()
    assert task.confirm_button.isEnabled()
    assert window.execution_unit is not None
    window.execution_unit.busy_changed.emit(True)
    assert not task.confirm_button.isEnabled()
    assert not task.cancel_button.isEnabled()
    window.execution_unit.busy_changed.emit(False)
    assert task.confirm_button.isEnabled()
    assert task.cancel_button.isEnabled()
    task.reject()


def test_embedded_datum_confirm_commits_current_candidate_once(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    assert task is not None
    task.preview()
    task.origin_fields[0].setValue(4)
    assert not task.confirm_button.isEnabled()
    task.preview()
    task.confirm_button.click()
    assert window.datum_task is None
    assert len(loaded.document.commands) == 1
    assert loaded.document.commands[0].id == "datum.coordinate_system.create"
    task.confirm()
    assert len(loaded.document.commands) == 1


def test_narrow_datum_command_strip_reveals_focused_parameter(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1024, 768)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    assert task is not None
    field = task.angle_fields[-1]
    field.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(field.hasFocus)
    qtbot.wait(30)
    assert field.visibleRegion().boundingRect().width() >= field.width() - 2
    for button in (task.confirm_button, task.cancel_button):
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
    task.reject()


def test_embedded_datum_positioning_cancel_and_source_change(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    assert task is not None
    task.open_positioning()
    positioning = task.position_dialog
    assert positioning is not None and positioning.isVisible()
    positioning.reject()
    assert task.position_dialog is None
    assert task.confirm_button.isEnabled()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    qtbot.waitUntil(lambda: not task.confirm_button.isEnabled())
    task.confirm_button.click()
    assert len(loaded.document.commands) == 1
    task.reject()


def test_starting_another_modeling_command_cancels_datum_candidate(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit("datum.coordinate_system.create")
    task = window.datum_task
    assert task is not None
    task.preview()
    assert window.viewport.datum_display_count() == 1
    window.command_palette.command_activated.emit("feature.box")
    assert window.datum_task is None
    assert window.viewport.datum_display_count() == 0
    assert loaded.document.commands == ()


def test_datum_tree_selection_and_visibility_do_not_preview_history(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    plane = {
        "name": "基准 A",
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
    loaded.document.mark_clean()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    assert window.right_panel is not None and window.viewport is not None
    tree = window.right_panel.structure_tree
    root = tree.topLevelItem(0)
    assert root is not None
    group = root.child(0)
    assert group is not None
    leaf = group.child(0)
    assert leaf is not None and "基准 A" in leaf.text(0)
    selected: list[SpatialReference] = []
    window.right_panel.datum_selection_requested.connect(selected.append)
    tree.itemClicked.emit(leaf, 0)
    assert len(selected) == 1 and selected[0].kind == "datum_plane"
    assert window.viewport.history_preview_ordinal() is None
    tree.setCurrentIndex(QModelIndex())
    window.viewport.resize(800, 600)
    window.viewport.set_orientation("top")
    QTest.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert tree.currentItem() == leaf
    leaf.setCheckState(0, Qt.CheckState.Unchecked)
    assert window.viewport.datum_display_count() == 0
    assert not loaded.document.is_dirty


def test_origin_position_uv_is_converted_into_parent_coordinates(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    parent = {
        "name": "parent",
        "parent": {"kind": "world"},
        "origin_mm": [10, 20, 30],
        "x_axis": [0, 1, 0],
        "y_axis": [-1, 0, 0],
        "z_axis": [0, 0, 1],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("datum.coordinate_system.create", 1, parent, "local"),), False, 6
        ),
        current_session_identity=1,
    )
    candidate.preview(current_session_identity=1)
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.parent_combo.setCurrentIndex(1)
    task.preview()
    screen = view.project_world_point((10, 20, 30))
    assert screen is not None
    assert [item.reference for item in view.datum_targets_at(*screen)] == [
        services.kernel.datum_display_data()[0].reference
    ]
    task.parent_combo.setCurrentIndex(0)
    view.select_datum(services.kernel.datum_display_data()[0].reference)
    assert task.parent_combo.currentIndex() == 1
    task.open_positioning()
    positioning = task.position_dialog
    assert positioning is not None
    positioning.lock_plane()
    positioning.u_field.setValue(10)
    positioning.v_field.setValue(25)
    before = document_payload(loaded.document)
    positioning.adopt()
    assert [field.value() for field in task.origin_fields] == pytest.approx((5, 0, -30))
    assert document_payload(loaded.document) == before
    task.reject()


def test_positioning_pointer_grid_and_numeric_input_have_independent_priority(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    view.setCameraPosition(distance=100)
    task = DatumTaskDialog(services, loaded, view, session_identity=3)
    qtbot.addWidget(task)
    task.open_positioning()
    positioning = task.position_dialog
    assert positioning is not None
    positioning.lock_plane()
    positioning.object_snap.setChecked(False)
    positioning.grid_spacing.setValue(1)
    positioning.grid_snap.setChecked(True)
    assert "隐藏" in positioning.grid_status.text()
    positioning.grid_visible.setChecked(True)
    assert positioning.grid_snap.isChecked()
    assert "隐藏" not in positioning.grid_status.text()
    positioning.grid_visible.setChecked(False)
    assert positioning.grid_snap.isChecked()
    screen = view.project_world_point((2.3, 4.7, 0))
    assert screen is not None
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(*screen),
        QPointF(*screen),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, event)
    assert (positioning.u_field.value(), positioning.v_field.value()) == pytest.approx((2, 5))
    positioning.u_field.setValue(1.23)
    positioning.v_field.setValue(-4.56)
    QApplication.sendEvent(view, event)
    assert (positioning.u_field.value(), positioning.v_field.value()) == pytest.approx(
        (1.23, -4.56)
    )
    positioning.adopt()
    assert [field.value() for field in task.origin_fields] == pytest.approx((1.23, -4.56, 0))
    task.reject()


def test_outer_draft_change_expires_open_positioning(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=3)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    position.u_field.setValue(12)
    task.name_field.setText("changed")
    assert task.position_dialog is None
    position.adopt()
    assert [field.value() for field in task.origin_fields] == [0, 0, 0]
    assert not task.confirm_button.isEnabled()
    task.reject()


def test_typing_unchanged_numeric_zero_prevents_pointer_overwrite(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    view.setCameraPosition(distance=100)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    position.u_field.setFocus()
    position.u_field.selectAll()
    QTest.keyClicks(position.u_field, "0")
    screen = view.project_world_point((4, 7, 0))
    assert screen is not None
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*screen),
            QPointF(*screen),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert position.u_field.value() == 0
    assert position.v_field.value() == 0
    task.reject()


def test_invalid_uv_input_cannot_adopt_old_point(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    position.u_field.setFocus()
    position.u_field.selectAll()
    QTest.keyClicks(position.u_field, "-")
    assert not position.u_field.hasAcceptableInput()
    assert not position.adopt_button.isEnabled()
    position.adopt()
    assert task.position_dialog is position
    assert [field.value() for field in task.origin_fields] == [0, 0, 0]
    task.reject()


def test_invalid_outer_coordinate_input_invalidates_successful_preview(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    assert task.confirm_button.isEnabled()
    field = task.origin_fields[0]
    field.setFocus()
    field.selectAll()
    QTest.keyClicks(field, "-")
    assert not field.hasAcceptableInput()
    assert not task.confirm_button.isEnabled()
    task.preview()
    assert not task.confirm_button.isEnabled()
    task.confirm()
    assert loaded.document.commands == ()
    task.reject()


def test_source_change_immediately_disables_datum_confirmation(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    assert task.confirm_button.isEnabled()
    loaded.bus.execute("feature.box", {"size_x": 3, "size_y": 3, "size_z": 2})
    QApplication.processEvents()
    assert not task.confirm_button.isEnabled()
    task.confirm()
    assert [command.id for command in loaded.document.commands] == ["feature.box"]
    task.reject()


def test_positioning_object_snap_takes_priority_over_grid(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    line = LineEntity(uuid4().hex, (2, 3), (8, 3))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), version=3)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    position.grid_snap.setChecked(True)
    position.grid_spacing.setValue(10)
    screen = view.project_world_point((2, 3, 0))
    assert screen is not None
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*screen),
            QPointF(*screen),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert (position.u_field.value(), position.v_field.value()) == pytest.approx((2, 3))
    assert "vertex" in position.status_label.text()
    assert view.position_marker_points() == ((2, 3, 0),)
    task.reject()
    assert view.position_marker_points() == ()


@pytest.mark.parametrize("kind", ["vertex", "midpoint"])
def test_coordinate_origin_hotspot_snaps_directly_to_3d_box_point(qtbot: QtBot, kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 6})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("isometric")
    view.show()
    qtbot.wait(100)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    assert task.confirm_button.isEnabled()
    origin_screen = view.project_world_point((0, 0, 0))
    assert origin_screen is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, origin_screen)))
    anchors = [a for a in view.interaction_snap_anchors() if a.kind == kind and abs(a.point[2]) > 1]
    anchor = max(anchors, key=lambda a: a.point[0] + a.point[1] + a.point[2])
    screen = view.project_world_point(anchor.point)
    assert screen is not None
    QTest.mouseMove(view, QPoint(*map(round, screen)))
    assert view.position_marker_points() == (anchor.point,)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, screen)))
    task.preview()
    task.confirm()
    assert loaded.document.commands[-1].params["origin_mm"] == pytest.approx(anchor.point)


def test_direct_origin_snap_is_invalidated_when_source_changes(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 6})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    task.start_origin_pick()
    assert not task.confirm_button.isEnabled()
    loaded.bus.execute("feature.box", {"size_x": 4, "size_y": 4, "size_z": 4})
    QApplication.processEvents()
    task.confirm()
    assert [command.id for command in loaded.document.commands] == ["feature.box", "feature.box"]
    assert view.position_marker_points() == ()
    task.reject()


def test_coordinate_origin_can_snap_to_world_origin(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.origin_fields[0].setValue(20)
    task.preview()
    task.start_origin_pick()
    screen = view.project_world_point((0, 0, 0))
    assert screen is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, screen)))
    task.preview()
    task.confirm()
    assert loaded.document.commands[-1].params["origin_mm"] == [0, 0, 0]


def test_origin_hotspot_drag_adopts_exact_3d_point(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 6})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("isometric")
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    origin = view.project_world_point((0, 0, 0))
    target = view.project_world_point((10, 5, 3))
    assert origin is not None and target is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, origin)))
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*target),
            QPointF(*target),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, target)))
    task.preview()
    task.confirm()
    assert loaded.document.commands[-1].params["origin_mm"] == pytest.approx((10, 5, 3))


def test_snap_keeps_exact_point_when_adopted_and_committed(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    x = 2.123456789
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (x, 3), (8, 3)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), version=3)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    screen = view.project_world_point((x, 3, 0))
    assert screen is not None
    QApplication.sendEvent(
        view,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*screen),
            QPointF(*screen),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    position.adopt()
    task.preview()
    task.confirm()
    origin = loaded.document.commands[-1].params["origin_mm"]
    assert isinstance(origin, list)
    assert origin[0] == x


def test_locked_plane_ignores_tree_selection_until_explicit_unlock(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    position.lock_plane()
    assert not position.plane_combo.isEnabled()
    assert position.adopt_button.isEnabled()
    position.lock_button.click()
    assert position.plane_combo.isEnabled()
    assert not position.adopt_button.isEnabled()
    task.reject()


def test_hidden_body_stays_hidden_in_candidate_and_snap(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    snapshot = services.kernel.viewport_data()[-1]
    body = snapshot.body_origins[0].body_id
    assert view.set_body_visible(body, False)
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.preview()
    assert not view.mesh_visible()
    assert not any(anchor.body_id is not None for anchor in view.interaction_snap_anchors())
    task.reject()


def test_datum_task_does_not_preview_or_commit_while_worker_busy(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    busy = [True]
    task = DatumTaskDialog(
        services, loaded, view, session_identity=1, can_execute=lambda: not busy[0]
    )
    qtbot.addWidget(task)
    task.preview()
    assert not task.confirm_button.isEnabled()
    busy[0] = False
    task.preview()
    assert task.confirm_button.isEnabled()
    busy[0] = True
    task.confirm()
    assert not task.confirm_button.isEnabled()
    assert loaded.document.commands == ()
    task.reject()


def test_workplane_can_be_selected_from_existing_datum_in_viewport(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    plane = {
        "name": "工作面",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xz",
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
    task = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(task)
    task.open_positioning()
    position = task.position_dialog
    assert position is not None
    view.select_datum(services.kernel.datum_display_data()[0].reference)
    assert position.plane_combo.currentText() == "工作面"
    assert task.parent_combo.currentIndex() == 0
    task.reject()


def test_datum_gui_chain_survives_undo_redo_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    coordinate = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(coordinate)
    coordinate.name_field.setText("CS")
    coordinate.origin_fields[0].setValue(10)
    coordinate.angle_fields[2].setValue(90)
    coordinate.preview()
    coordinate.confirm()
    principal = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(principal)
    principal.kind_combo.setCurrentIndex(1)
    principal.name_field.setText("base")
    principal.parent_combo.setCurrentIndex(1)
    principal.plane_combo.setCurrentText("XZ")
    principal.preview()
    principal.confirm()
    offset = DatumTaskDialog(services, loaded, view, session_identity=1)
    qtbot.addWidget(offset)
    offset.kind_combo.setCurrentIndex(2)
    offset.name_field.setText("offset")
    offset.offset_field.setValue(-20)
    offset.preview()
    offset.confirm()
    datums = services.kernel.datum_display_data()
    assert [datum.name for datum in datums] == ["CS", "base", "offset"]
    assert datums[-1].frame.origin_mm == pytest.approx((30, 0, 0))
    loaded.bus.undo()
    assert len(services.kernel.datum_display_data()) == 2
    loaded.bus.redo()
    assert services.kernel.datum_display_data() == datums
    path = tmp_path / "datums.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    reopened = app.open_app_document(reopened_services, path)
    assert reopened.document.commands == loaded.document.commands
    assert reopened_services.kernel.datum_display_data() == datums
