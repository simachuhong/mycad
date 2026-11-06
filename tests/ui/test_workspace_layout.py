# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Workspace layout settings migrate safely and stay isolated."""

from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QSettings

from mycad.ui.workspace_layout import WorkspaceLayoutStore


def test_layouts_roundtrip_and_reset_only_selected_environment(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    store = WorkspaceLayoutStore(settings)
    store.save("part", QByteArray(b"part layout"))
    store.save("drawing2d", QByteArray(b"drawing layout"))
    store.save("drawing", QByteArray(b"sheet layout"))
    reopened = WorkspaceLayoutStore(settings)
    assert reopened.load("part") == QByteArray(b"part layout")
    assert reopened.load("drawing2d") == QByteArray(b"drawing layout")
    reopened.reset("part")
    assert reopened.load("part") is None
    assert reopened.load("drawing2d") == QByteArray(b"drawing layout")
    assert reopened.load("drawing") == QByteArray(b"sheet layout")
    with pytest.raises(ValueError):
        reopened.save("../other", QByteArray(b"invalid"))


def test_legacy_migration_is_backed_up_and_never_overwrites_new_value(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    old = QByteArray(b"old state")
    drafting = QByteArray(b"2d toolbar state")
    settings.setValue("mainWindow/state", old)
    settings.setValue("layout/draftingToolbars", drafting)
    settings.setValue("toolbar/locked", True)
    store = WorkspaceLayoutStore(settings)
    store.migrate_legacy()
    assert store.load("part") == old
    assert settings.value("workspace-layout/legacy/mainWindow-state") == old
    assert settings.value("mainWindow/state") == old
    assert settings.value("layout/draftingToolbars") == drafting
    assert store.load_locked("part") is True
    assert settings.value("workspace-layout/legacy/toolbar-locked", type=bool) is True
    store.save("part", QByteArray(b"new state"))
    store.migrate_legacy()
    assert store.load("part") == QByteArray(b"new state")
    assert settings.value("workspace-layout/legacy/mainWindow-state") == old
    store.reset("part")
    store.migrate_legacy()
    assert store.load("part") is None
    assert store.load_locked("part") is None


def test_invalid_legacy_state_is_not_restored_as_layout(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    settings.setValue("mainWindow/state", "invalid")
    store = WorkspaceLayoutStore(settings)
    store.migrate_legacy()
    assert store.load("part") is None
    assert settings.value("workspace-layout/legacy/mainWindow-state") == "invalid"


def test_existing_new_layout_wins_over_legacy_during_first_migration(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    settings.setValue("mainWindow/state", QByteArray(b"old"))
    store = WorkspaceLayoutStore(settings)
    store.save("part", QByteArray(b"already migrated"))
    store.migrate_legacy()
    assert store.load("part") == QByteArray(b"already migrated")
    assert settings.value("workspace-layout/legacy/mainWindow-state") == QByteArray(b"old")


def test_resetting_part_layout_preserves_saved_2d_toolbar_state(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui import main_window

    assert isinstance(qtbot, QtBot)
    settings = main_window.QSettings("MyCAD", "MyCAD")
    state = QByteArray(b"existing 2d layout")
    settings.setValue("layout/draftingToolbars", state)
    window = main_window.MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.act_reset_layout.trigger()
    assert settings.value("layout/draftingToolbars") == state


def test_part_and_engineering_restore_their_own_dock_visibility(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    window.left_dock.hide()
    drawing = window.new_session_document("drawing")
    window.left_dock.show()
    assert window.left_dock.isVisible()
    window.activate_session_document(part.loaded.document.document_id)
    assert not window.left_dock.isVisible()
    window.activate_session_document(drawing.loaded.document.document_id)
    assert window.left_dock.isVisible()


def test_part_layout_survives_restart_and_reset_does_not_clear_drawing(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = build_app(discoverers=[])
    first = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(first)
    first.show()
    first.new_session_document("part")
    first.workspace_layout.save("drawing", QByteArray(b"other environment"))
    first.left_dock.hide()
    first.close()
    second = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(second)
    second.show()
    second.new_session_document("part")
    assert not second.left_dock.isVisible()
    second.act_reset_layout.trigger()
    assert second.workspace_layout.load("drawing") == QByteArray(b"other environment")


def test_numeric_input_focus_does_not_complete_pending_sketch(qtbot: object) -> None:
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("直线")
    draft.canvas.add_coordinate_point((0, 0))
    assert draft.canvas.has_pending_geometry
    draft.u_field.setFocus()
    draft.u_field.selectAll()
    QTest.keyClicks(draft.u_field, "12")
    draft.u_field.interpretText()
    assert draft.u_field.value() == 12
    assert draft.canvas.has_pending_geometry
    assert not draft.canvas.entities
    draft.reject()


def test_command_input_focus_keeps_text_editing_separate_from_drawing(qtbot: object) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("直线")
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((10, 0))
    assert len(draft.canvas.entities) == 1
    field = draft.drawing_command_bar.input
    window.activateWindow()
    field.setFocus()
    qtbot.waitUntil(field.hasFocus)
    QTest.keyClicks(field, "CU123")
    assert field.text() == "CU123"
    assert len(draft.canvas.entities) == 1
    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not field.text()
    assert len(draft.canvas.entities) == 1
    draft.reject()


def test_part_sketch_and_part_keep_separate_dock_layouts(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    window.left_dock.hide()
    window.act_sketch.trigger()
    first = window.part_sketch_task
    assert first is not None
    window.left_dock.show()
    first.reject()
    assert not window.left_dock.isVisible()
    window.act_sketch.trigger()
    second = window.part_sketch_task
    assert second is not None
    assert window.left_dock.isVisible()
    second.reject()


def test_switching_to_part_retains_2d_toolbar_layout_when_reset(qtbot: object) -> None:
    from PySide6.QtCore import Qt
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui import main_window
    from mycad.ui.document_session import DocumentSession

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = main_window.MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    drawing = window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.toolbar_host.addToolBar(Qt.ToolBarArea.BottomToolBarArea, draft.drawing_toolbar)
    saved = draft.toolbar_layout_state()
    window.activate_session_document(part.loaded.document.document_id)
    window.act_reset_layout.trigger()
    settings = main_window.QSettings("MyCAD", "MyCAD")
    assert settings.value("layout/draftingToolbars") == saved
    window.activate_session_document(drawing.loaded.document.document_id)
    assert window.active_sketch_dialog() is draft
    assert draft.toolbar_host.toolBarArea(draft.drawing_toolbar) == Qt.ToolBarArea.BottomToolBarArea


def test_toolbar_lock_is_independent_across_document_environments(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    window.act_lock_toolbar.setChecked(True)
    drawing = window.new_session_document("drawing")
    assert not window.act_lock_toolbar.isChecked()
    window.act_reset_layout.trigger()
    window.activate_session_document(part.loaded.document.document_id)
    assert window.act_lock_toolbar.isChecked()
    window.activate_session_document(drawing.loaded.document.document_id)
    assert not window.act_lock_toolbar.isChecked()


def test_switching_to_an_unopened_workspace_does_not_create_a_document(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    window.workspace_tabs.activate("sketch")
    assert session.documents == (part,)
    assert session.active is part
    assert window.active_workspace == "model"
    assert "新建" in window.status_command.text()


def test_view_switch_does_not_create_an_independent_drawing(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    part = window.new_session_document("part")
    window.act_view_2d.trigger()
    assert session.documents == (part,)
    assert session.active is part
    assert not window.act_view_2d.isChecked()
    drawing = window.new_session_document("sketch")
    window.activate_session_document(part.loaded.document.document_id)
    window.act_view_2d.trigger()
    assert session.active is drawing
    assert session.documents == (part, drawing)


def test_3d_view_switch_without_part_preserves_current_drawing(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    drawing = window.new_session_document("sketch")
    window.act_view_3d.trigger()
    assert session.documents == (drawing,)
    assert session.active is drawing
    assert window.active_workspace == "sketch"
    assert not window.act_view_3d.isChecked()
    assert "新建" in window.status_command.text()


def test_console_preferences_are_separate_and_reset_with_current_environment(
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "console.ini"), QSettings.Format.IniFormat)
    store = WorkspaceLayoutStore(settings)
    assert store.load_console("part") == (False, 0, 240)
    store.save_console("part", True, 2, 320)
    store.save_console("drawing2d", False, 1, 210)
    assert store.load_console("part") == (True, 2, 320)
    assert store.load_console("drawing2d") == (False, 1, 210)
    store.reset("part")
    assert store.load_console("part") == (False, 0, 240)
    assert store.load_console("drawing2d") == (False, 1, 210)
    settings.setValue("workspace-layout/v1-console/part", "broken")
    assert store.load_console("part") == (False, 0, 240)
    assert settings.value("workspace-layout/v1-console/part") == "broken"


def test_main_window_fits_512_by_384_logical_screen(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(512, 384)
    window.show()
    assert window.width() <= 512 and window.height() <= 384


def test_compact_2d_keeps_command_input_and_canvas_usable(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(512, 384)
    window.show()
    window.new_session_document("sketch")
    qtbot.wait(50)
    editor = window.active_sketch_dialog()
    assert editor is not None
    field = editor.drawing_command_bar.input
    assert field.height() >= field.minimumSizeHint().height()
    assert editor.canvas.height() >= 60
    assert window.width() <= 512 and window.height() <= 384


def test_compact_part_keeps_viewport_and_bound_hole_controls_reachable(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(512, 384)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    viewport = window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    assert viewport.width() >= 250 and viewport.height() >= 80
    for button in (task.confirm_button, task.cancel_button):
        assert window.rect().contains(button.mapTo(window, button.rect().center()))
    task.cancel_button.click()


def test_compact_session_part_retains_canvas_after_document_switch(qtbot: object) -> None:
    from PySide6.QtCore import QPoint, QRect
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(512, 384)
    window.show()
    entry = window.new_session_document("part")
    entry.loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    window.act_sketch.trigger()
    sketch = window.part_sketch_task
    assert sketch is not None
    sketch.reject()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task, viewport = window.bound_hole_task, window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    visible = QRect(viewport.mapTo(window, QPoint(0, 0)), viewport.size())
    parent = viewport.parentWidget()
    while parent is not None and parent is not window:
        visible = visible.intersected(QRect(parent.mapTo(window, QPoint(0, 0)), parent.size()))
        parent = parent.parentWidget()
    assert visible.width() >= 250 and visible.height() >= 80
    task.cancel_button.click()


def test_scaled_short_window_keeps_bound_hole_viewport_usable(qtbot: object) -> None:
    from PySide6.QtCore import QPoint, QRect
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(911, 512)
    window.show()
    window.show_start_page()
    assert window.act_expand_compact_ribbon.isEnabled()
    entry = window.new_session_document("part")
    entry.loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    window.act_sketch.trigger()
    sketch = window.part_sketch_task
    assert sketch is not None
    sketch.select_tool("line")
    sketch.reject()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task, viewport = window.bound_hole_task, window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    qtbot.wait(300)
    visible = QRect(viewport.mapTo(window, QPoint(0, 0)), viewport.size())
    parent = viewport.parentWidget()
    while parent is not None and parent is not window:
        visible = visible.intersected(QRect(parent.mapTo(window, QPoint(0, 0)), parent.size()))
        parent = parent.parentWidget()
    assert visible.width() >= 250 and visible.height() >= 80
    task.cancel_button.click()


def test_compact_panels_and_ribbon_can_be_reopened_and_restore(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    window.resize(512, 384)
    window.show()
    qtbot.wait(50)
    assert window.act_expand_compact_ribbon.isEnabled()
    collapsed = window.part_ribbon.maximumHeight()
    window.act_expand_compact_ribbon.trigger()
    assert window.part_ribbon.maximumHeight() > collapsed
    window.act_expand_compact_ribbon.trigger()
    assert window.part_ribbon.maximumHeight() == collapsed
    window.act_toggle_right_dock.setChecked(True)
    window.act_toggle_bottom_dock.setChecked(True)
    assert window.right_dock.isVisible() and window.bottom_dock.isVisible()
    window.resize(1200, 800)
    qtbot.wait(50)
    assert window.right_dock.isVisible() and window.bottom_dock.isVisible()
    assert not window.act_expand_compact_ribbon.isEnabled()


def test_compact_mode_does_not_persist_automatic_panel_hiding(qtbot: object) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = build_app(discoverers=[])
    first = MainWindow(services=services)
    qtbot.addWidget(first)
    first.bind_document(new_document(services))
    first.resize(1200, 800)
    first.show()
    first.act_toggle_right_dock.setChecked(True)
    first.act_toggle_bottom_dock.setChecked(True)
    qtbot.wait(30)
    assert first.right_dock.isVisible() and first.bottom_dock.isVisible()
    first.resize(512, 384)
    qtbot.wait(30)
    assert first.right_dock.isHidden() and first.bottom_dock.isHidden()
    first.store_window_state()
    first.resize(1200, 800)
    qtbot.wait(30)
    assert first.right_dock.isVisible() and first.bottom_dock.isVisible()
    second = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(second)
    second.resize(1200, 800)
    second.show()
    qtbot.wait(30)
    assert second.right_dock.isVisible() and second.bottom_dock.isVisible()


def test_compact_part_sketch_expands_controls_and_collapses_after_cancel(qtbot: object) -> None:
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QScrollArea
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    window.resize(1200, 800)
    window.show()
    window.left_dock.show()
    window.right_dock.show()
    window.bottom_dock.show()
    window.workspace_layout.save("part-sketch", window.saveState())
    window.resize(512, 384)
    qtbot.wait(30)
    collapsed = window.part_ribbon.maximumHeight()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    assert window.part_ribbon.maximumHeight() > collapsed
    qtbot.wait(30)
    assert window.left_dock.isHidden()
    assert window.right_dock.isHidden()
    assert window.bottom_dock.isHidden()
    viewport = window.viewport
    assert viewport is not None
    visible = QRect(viewport.mapTo(window, QPoint(0, 0)), viewport.size())
    parent = viewport.parentWidget()
    while parent is not None and parent is not window:
        visible = visible.intersected(QRect(parent.mapTo(window, QPoint(0, 0)), parent.size()))
        parent = parent.parentWidget()
    assert visible.width() >= 250 and visible.height() >= 80
    scroll = task.parentWidget()
    while scroll is not None and not isinstance(scroll, QScrollArea):
        scroll = scroll.parentWidget()
    assert isinstance(scroll, QScrollArea)
    for control in (task.plane_combo, task.lock_button, task.line_button, task.confirm_button):
        scroll.ensureWidgetVisible(control, 0, 0)
        qtbot.wait(10)
        assert (
            scroll.viewport()
            .rect()
            .contains(control.mapTo(scroll.viewport(), control.rect().center()))
        )
    task.select_tool("line")
    qtbot.wait(100)
    for field in (task.dynamic_input.first_value, task.dynamic_input.second_value):
        scroll.ensureWidgetVisible(field, 0, 0)
        qtbot.wait(10)
        assert (
            scroll.viewport().rect().contains(field.mapTo(scroll.viewport(), field.rect().center()))
        )
    window.resize(683, 600)
    qtbot.wait(30)
    assert window.part_ribbon.maximumHeight() > 150
    window.resize(512, 384)
    qtbot.wait(30)
    assert window.part_ribbon.maximumHeight() == 150
    task.reject()
    assert window.part_ribbon.maximumHeight() == collapsed
