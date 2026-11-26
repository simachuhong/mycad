# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Workspace toolbar docking and startup space allocation."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QDrag, QGuiApplication, QWindow
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QStyleOptionToolBar
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.drawing_block_dialogs import BlockManagerDialog
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog
from mycad.ui.theme import apply_theme


def test_xcb_floating_toolbar_redocks_by_dragging_to_edge(qapp: QApplication, qtbot: QtBot) -> None:
    if qapp.platformName() != "xcb":
        pytest.skip("Requires the X11 Qt backend to verify its native docking behavior.")
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1150, 800)
    editor.show()
    qapp.processEvents()
    toolbar, host = editor.collection_toolbar, editor.toolbar_host

    def drag_to(target: QPoint) -> None:
        start = QPoint(10, toolbar.height() // 2)
        source = toolbar.mapToGlobal(start)
        QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
        for index in range(1, 31):
            position = source + (target - source) * (index / 30)
            QTest.mouseMove(toolbar, toolbar.mapFromGlobal(position), 2)
            qapp.processEvents()
        QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=toolbar.mapFromGlobal(target))

    drag_to(toolbar.mapToGlobal(QPoint(160, 150)))
    assert toolbar.isFloating()
    drag_to(host.mapToGlobal(QPoint(500, 20)))
    qtbot.waitUntil(lambda: not toolbar.isFloating(), timeout=2000)
    assert host.toolBarArea(toolbar) == Qt.ToolBarArea.TopToolBarArea


def test_xcb_toolbar_released_just_outside_edge_docks_without_covering_neighbor(
    qapp: QApplication, qtbot: QtBot
) -> None:
    if qapp.platformName() != "xcb":
        pytest.skip("Requires X11 for native toolbar dragging.")
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    host, toolbar, neighbor = editor.toolbar_host, editor.collection_toolbar, editor.modify_toolbar
    host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, neighbor)
    qapp.processEvents()

    def drag_to(target: QPoint) -> None:
        start = QPoint(10, toolbar.height() // 2)
        source = toolbar.mapToGlobal(start)
        QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
        for index in range(1, 31):
            position = source + (target - source) * (index / 30)
            QTest.mouseMove(toolbar, toolbar.mapFromGlobal(position), 2)
            qapp.processEvents()
        QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=toolbar.mapFromGlobal(target))

    drag_to(toolbar.mapToGlobal(QPoint(200, 180)))
    assert toolbar.isFloating()
    drag_to(host.mapToGlobal(QPoint(-5, 200)))
    qtbot.waitUntil(
        lambda: not toolbar.isFloating() and not toolbar.geometry().intersects(neighbor.geometry()),
        timeout=2000,
    )
    assert host.toolBarArea(toolbar) == Qt.ToolBarArea.LeftToolBarArea
    assert host.toolBarArea(neighbor) == Qt.ToolBarArea.LeftToolBarArea
    assert not toolbar.geometry().intersects(neighbor.geometry())


def test_xcb_floating_toolbar_stays_floating_away_from_edges(
    qapp: QApplication, qtbot: QtBot
) -> None:
    if qapp.platformName() != "xcb":
        pytest.skip("Requires X11 for native toolbar dragging.")
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    qapp.processEvents()
    toolbar = editor.collection_toolbar
    start = QPoint(10, toolbar.height() // 2)
    source = toolbar.mapToGlobal(start)
    target = editor.toolbar_host.mapToGlobal(editor.toolbar_host.rect().center())
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    for index in range(1, 31):
        point = source + (target - source) * (index / 30)
        QTest.mouseMove(toolbar, toolbar.mapFromGlobal(point), 2)
        qapp.processEvents()
    QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=toolbar.mapFromGlobal(target))
    qtbot.wait(600)
    assert toolbar.isFloating()


def test_floating_toolbar_uses_system_move_when_available(
    qapp: QApplication, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.collection_toolbar
    start = QPoint(10, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, QPoint(250, 180), 100)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
    assert bar.isFloating()
    requests: list[QWindow] = []

    def system_move(window: QWindow) -> bool:
        requests.append(window)
        return True

    def platform_name() -> str:
        return "wayland"

    monkeypatch.setattr(QGuiApplication, "platformName", platform_name)
    monkeypatch.setattr(QWindow, "startSystemMove", system_move)
    start = QPoint(10, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    assert requests == [bar.windowHandle()]
    assert editor.canvas.updatesEnabled()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=start)

    def unavailable(_window: QWindow) -> bool:
        return False

    monkeypatch.setattr(QWindow, "startSystemMove", unavailable)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    assert not editor.canvas.updatesEnabled()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=start)
    assert editor.canvas.updatesEnabled()


def test_floating_toolbar_can_be_docked_without_resetting_other_bars(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    host, bar = editor.toolbar_host, editor.collection_toolbar
    host.addToolBar(Qt.ToolBarArea.BottomToolBarArea, editor.dimension_toolbar)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(10, bar.height() // 2))
    QTest.mouseMove(bar, QPoint(250, 180), 100)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
    assert bar.isFloating()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None
    dock = menu.findChild(QMenu, "dockToolbar-draftingCollectionToolbar")
    assert dock is not None
    next(action for action in dock.actions() if action.text() == "停靠到左侧").trigger()
    assert not bar.isFloating()
    assert host.toolBarArea(bar) == Qt.ToolBarArea.LeftToolBarArea
    assert host.toolBarArea(editor.dimension_toolbar) == Qt.ToolBarArea.BottomToolBarArea
    qtbot.wait(500)
    assert bar.orientation() == Qt.Orientation.Vertical
    assert bar.width() < 200
    central = host.centralWidget()
    assert central is not None
    assert not bar.geometry().intersects(central.geometry())
    editor.set_toolbars_locked(True)
    next(action for action in dock.actions() if action.text() == "停靠到右侧").trigger()
    assert host.toolBarArea(bar) == Qt.ToolBarArea.LeftToolBarArea


def test_docking_toolbar_to_its_current_area_preserves_other_toolbars(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1600, 900)
    editor.show()
    qtbot.wait(400)
    host = editor.toolbar_host
    bar, neighbor = editor.drawing_toolbar, editor.modify_toolbar
    before_bar = bar.geometry()
    before_neighbor = neighbor.geometry()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None
    dock = menu.findChild(QMenu, "dockToolbar-draftingDrawingToolbar")
    assert dock is not None
    next(action for action in dock.actions() if action.text() == "停靠到上方").trigger()
    qtbot.wait(500)
    assert host.toolBarArea(bar) == Qt.ToolBarArea.TopToolBarArea
    assert bar.geometry() == before_bar
    assert neighbor.geometry() == before_neighbor


def test_reset_layout_after_floating_toolbar_clears_stale_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    bar = editor.collection_toolbar
    start = QPoint(10, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, QPoint(250, 180), 100)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
    assert bar.isFloating()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None
    next(action for action in menu.actions() if action.text() == "恢复二维布局").trigger()
    qtbot.wait(500)
    host = editor.toolbar_host
    assert not bar.isFloating()
    assert host.toolBarArea(bar) == Qt.ToolBarArea.TopToolBarArea
    assert bar.orientation() == Qt.Orientation.Horizontal
    central = host.centralWidget()
    assert central is not None
    assert not bar.geometry().intersects(central.geometry())
    for other in editor.drafting_toolbars:
        assert not other.geometry().intersects(central.geometry())


def test_dock_toolbar_immediately_to_right_of_another_toolbar(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1800, 900)
    editor.show()
    qtbot.wait(300)
    host = editor.toolbar_host
    bar, anchor = editor.measurement_toolbar, editor.collection_toolbar
    before_drawing = editor.drawing_toolbar.geometry()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None
    dock = menu.findChild(QMenu, "dockToolbar-draftingMeasurementToolbar")
    assert dock is not None
    adjacent = dock.findChild(QMenu, "dockToolbarAdjacent-draftingMeasurementToolbar")
    assert adjacent is not None
    next(action for action in adjacent.actions() if action.text() == "块与组").trigger()
    qtbot.wait(500)
    assert host.toolBarArea(bar) == host.toolBarArea(anchor)
    assert bar.geometry().top() == anchor.geometry().top()
    assert bar.geometry().left() == anchor.geometry().right() + 1
    assert editor.drawing_toolbar.geometry() == before_drawing
    assert editor.dimension_toolbar.geometry().top() > bar.geometry().bottom()


def test_dock_floating_toolbar_to_right_of_visible_horizontal_toolbar(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1800, 900)
    editor.show()
    bar, anchor = editor.collection_toolbar, editor.drawing_toolbar
    start = QPoint(10, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, QPoint(250, 180), 100)
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
    assert bar.isFloating()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None
    adjacent = menu.findChild(QMenu, "dockToolbarAdjacent-draftingCollectionToolbar")
    assert adjacent is not None
    next(action for action in adjacent.actions() if action.text() == "绘图").trigger()
    qtbot.wait(500)
    assert not bar.isFloating()
    assert bar.geometry().top() == anchor.geometry().top()
    assert bar.geometry().left() == anchor.geometry().right() + 1
    central = editor.toolbar_host.centralWidget()
    assert central is not None
    assert not bar.geometry().intersects(central.geometry())
    editor.set_toolbars_locked(True)
    adjacent.aboutToShow.emit()
    assert not next(action for action in adjacent.actions() if action.text() == "绘图").isEnabled()


def test_toolbar_drag_handle_is_easy_to_grab_in_both_orientations(
    qapp: QApplication, qtbot: QtBot
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    toolbar = editor.collection_toolbar
    try:
        for theme in ("light", "dark"):
            apply_theme(qapp, theme)
            for area in (Qt.ToolBarArea.TopToolBarArea, Qt.ToolBarArea.LeftToolBarArea):
                editor.toolbar_host.addToolBar(area, toolbar)
                option = QStyleOptionToolBar()
                option.initFrom(toolbar)
                assert (
                    toolbar.style().pixelMetric(
                        QStyle.PixelMetric.PM_ToolBarHandleExtent, option, toolbar
                    )
                    >= 14
                )
                assert toolbar.isMovable()
        editor.set_toolbars_locked(True)
        assert not toolbar.isMovable()
        editor.set_toolbars_locked(False)
        assert toolbar.isMovable()
    finally:
        apply_theme(qapp, "light")


def test_collection_toolbar_can_be_dragged_from_wider_handle(
    qapp: QApplication, qtbot: QtBot
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    toolbar = editor.collection_toolbar
    assert not toolbar.isFloating()
    start = QPoint(10, toolbar.height() // 2)
    target = QPoint(250, 180)
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(toolbar, target, 100)
    QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=target)
    assert toolbar.isFloating()
    editor.reset_toolbar_layout()
    assert not toolbar.isFloating()


def test_dragging_toolbar_defers_canvas_repaint_and_restores_it(
    qapp: QApplication, qtbot: QtBot
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    toolbar = editor.collection_toolbar
    start = QPoint(10, toolbar.height() // 2)
    assert canvas.updatesEnabled()
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert not canvas.updatesEnabled()
    QTest.mouseMove(toolbar, QPoint(250, 180), 100)
    QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=QPoint(250, 180))
    assert canvas.updatesEnabled()
    editor.reset_toolbar_layout()
    editor.set_toolbars_locked(True)
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert canvas.updatesEnabled()
    QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=start)
    editor.set_toolbars_locked(False)
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert not canvas.updatesEnabled()
    editor.hide()
    assert canvas.updatesEnabled()


def test_toolbar_drag_repaint_guard_preserves_existing_canvas_state(
    qapp: QApplication, qtbot: QtBot
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas, toolbar = editor.canvas, editor.collection_toolbar
    start = QPoint(10, toolbar.height() // 2)
    QTest.mousePress(editor.group_button, Qt.MouseButton.LeftButton)
    assert canvas.updatesEnabled()
    QTest.mouseRelease(editor.group_button, Qt.MouseButton.LeftButton)
    canvas.setUpdatesEnabled(False)
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert not canvas.updatesEnabled()
    canvas.setUpdatesEnabled(True)
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert not canvas.updatesEnabled()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
    assert canvas.updatesEnabled()
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=start)
    assert not canvas.updatesEnabled()
    QTest.keyClick(toolbar, Qt.Key.Key_Escape)
    assert canvas.updatesEnabled()


def test_toolbar_platform_drag_end_restores_canvas_without_mouse_release(
    qapp: QApplication, qtbot: QtBot
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas, toolbar = editor.canvas, editor.collection_toolbar
    QTest.mousePress(toolbar, Qt.MouseButton.LeftButton, pos=QPoint(10, toolbar.height() // 2))
    assert not canvas.updatesEnabled()
    drag = QDrag(toolbar)
    qapp.processEvents()
    assert not canvas.updatesEnabled()
    drag.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert canvas.updatesEnabled()


def test_old_platform_drag_does_not_end_a_new_toolbar_drag(
    qapp: QApplication, qtbot: QtBot
) -> None:
    apply_theme(qapp, "light")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    first, second, canvas = editor.collection_toolbar, editor.modify_toolbar, editor.canvas
    first_handle = QPoint(10, first.height() // 2)
    second_handle = QPoint(10, second.height() // 2)
    QTest.mousePress(first, Qt.MouseButton.LeftButton, pos=first_handle)
    drag = QDrag(first)
    qapp.processEvents()
    QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=first_handle)
    assert canvas.updatesEnabled()
    QTest.mousePress(second, Qt.MouseButton.LeftButton, pos=second_handle)
    assert not canvas.updatesEnabled()
    drag.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not canvas.updatesEnabled()
    QTest.mouseRelease(second, Qt.MouseButton.LeftButton, pos=second_handle)
    assert canvas.updatesEnabled()


def test_main_toolbar_drag_defers_active_drawing_canvas(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    bar = window.main_toolbar
    start = QPoint(10, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    assert not editor.canvas.updatesEnabled()
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=start)
    assert editor.canvas.updatesEnabled()


def test_drawing_collection_toolbar_is_independent_and_keeps_commands(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    toolbar = editor.collection_toolbar
    assert toolbar in editor.drafting_toolbars and toolbar.isVisible()
    buttons = (
        (editor.group_button, editor.drawing_command_bar.group_requested),
        (editor.ungroup_button, editor.drawing_command_bar.ungroup_requested),
        (editor.group_edit_button, editor.drawing_command_bar.group_edit_requested),
        (editor.block_create_button, editor.drawing_command_bar.block_requested),
        (editor.block_insert_button, editor.drawing_command_bar.block_insert_requested),
        (editor.block_edit_button, editor.drawing_command_bar.block_edit_requested),
        (editor.block_explode_button, editor.drawing_command_bar.block_explode_requested),
        (editor.block_manage_button, editor.block_manage_requested),
    )
    for button, signal in buttons:
        assert button.parentWidget() is toolbar
        spy = QSignalSpy(signal)
        button.click()
        assert spy.count() == 1
    editor.set_compact_layout(True)
    assert all(button.text().strip() != "" for button, _ in buttons)
    assert all(
        button.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly for button, _ in buttons
    )
    editor.toolbar_host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)
    state = editor.toolbar_layout_state()
    editor.reset_toolbar_layout()
    editor.restore_toolbar_layout(state)
    assert editor.toolbar_host.toolBarArea(toolbar) == Qt.ToolBarArea.LeftToolBarArea
    editor.reset_toolbar_layout()
    assert toolbar.isVisible()

    part_editor = SketchEditorDialog()
    qtbot.addWidget(part_editor)
    part_editor.show()
    assert part_editor.collection_toolbar not in part_editor.drafting_toolbars


def test_collection_toolbar_restores_older_layout_and_opens_block_manager(qtbot: QtBot) -> None:
    old_editor = SketchEditorDialog()
    qtbot.addWidget(old_editor)
    old_editor.show()
    old_state = old_editor.toolbar_layout_state()

    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.restore_toolbar_layout(old_state)
    assert editor.collection_toolbar.isVisible()
    opened: list[bool] = []

    def close_manager() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, BlockManagerDialog))
        if dialog is not None:
            dialog.close()

    QTimer.singleShot(0, close_manager)
    editor.block_manage_button.click()
    assert opened == [True]


def test_drafting_toolbars_dock_independently_and_restore(qtbot: QtBot) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    host = draft.toolbar_host
    for bar in draft.drafting_toolbars:
        assert bar.isMovable() and bar.isFloatable()
        assert bar.objectName()
    host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, draft.drawing_toolbar)
    host.addToolBar(Qt.ToolBarArea.BottomToolBarArea, draft.dimension_toolbar)
    draft.modify_toolbar.hide()
    state = draft.toolbar_layout_state()
    next_draft = SketchEditorDialog()
    qtbot.addWidget(next_draft)
    next_draft.restore_toolbar_layout(state)
    next_draft.show()
    assert (
        next_draft.toolbar_host.toolBarArea(next_draft.drawing_toolbar)
        == Qt.ToolBarArea.LeftToolBarArea
    )
    assert (
        next_draft.toolbar_host.toolBarArea(next_draft.dimension_toolbar)
        == Qt.ToolBarArea.BottomToolBarArea
    )
    assert next_draft.modify_toolbar.isHidden()
    next_draft.reset_toolbar_layout()
    assert all(not bar.isHidden() for bar in next_draft.drafting_toolbars)


def test_vertical_modify_toolbar_aligns_chamfer_and_fillet(qtbot: QtBot) -> None:
    draft = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(draft)
    draft.resize(1100, 900)
    draft.toolbar_host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, draft.modify_toolbar)
    draft.show()
    qtbot.waitExposed(draft)
    chamfer = draft.tool_buttons["二维倒角"]
    fillet = draft.tool_buttons["二维圆角"]
    assert chamfer.isVisible() and fillet.isVisible()
    assert chamfer.geometry().center().x() == fillet.geometry().center().x()


def test_bottom_panel_starts_collapsed_even_after_visible_session(qtbot: QtBot) -> None:
    first = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(first)
    first.show()
    first.act_show_cli.trigger()
    assert first.bottom_dock.isVisible()
    first.store_window_state()
    second = MainWindow()
    qtbot.addWidget(second)
    second.show()
    assert second.bottom_dock.isHidden()
    assert not second.act_toggle_bottom_dock.isChecked()


def test_three_dimensional_actions_have_their_own_toolbar(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.modeling_toolbar.show()
    assert window.toolBarBreak(window.modeling_toolbar)
    main_texts = {action.text() for action in window.main_toolbar.actions()}
    model_texts = {action.text() for action in window.modeling_toolbar.actions()}
    assert not {"拉伸", "旋转", "孔", "圆角"} & main_texts
    assert {"拉伸", "旋转", "孔", "圆角"} <= model_texts
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    assert window.modeling_toolbar.isHidden()
    draft.toolbar_host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, draft.drawing_toolbar)
    window.act_view_3d.trigger()
    assert not window.modeling_toolbar.isHidden()
    window.act_view_2d.trigger()
    assert draft.toolbar_host.toolBarArea(draft.drawing_toolbar) == Qt.ToolBarArea.LeftToolBarArea
    draft.reject()


def test_layout_survives_commit_and_window_recreation(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    first = MainWindow(services=services)
    qtbot.addWidget(first)
    first.show()
    first.act_new_drawing.trigger()
    draft = first.active_sketch_dialog()
    assert draft is not None
    draft.toolbar_host.addToolBar(Qt.ToolBarArea.BottomToolBarArea, draft.dimension_toolbar)
    draft.modify_toolbar.hide()
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((20.0, 0.0))
    draft.canvas.end_line_chain()
    draft.finish_button.click()
    qtbot.waitUntil(lambda: first.active_sketch_dialog() is not None, timeout=10000)
    next_draft = first.active_sketch_dialog()
    assert next_draft is not None and next_draft is not draft
    assert next_draft.modify_toolbar.isHidden()
    assert (
        next_draft.toolbar_host.toolBarArea(next_draft.dimension_toolbar)
        == Qt.ToolBarArea.BottomToolBarArea
    )
    first.store_window_state()
    next_draft.reject()
    first.close()
    second = MainWindow(services=services)
    qtbot.addWidget(second)
    second.show()
    second.act_new_drawing.trigger()
    restored = second.active_sketch_dialog()
    assert restored is not None
    assert restored.modify_toolbar.isHidden()
    assert (
        restored.toolbar_host.toolBarArea(restored.dimension_toolbar)
        == Qt.ToolBarArea.BottomToolBarArea
    )
    restored.reject()


def test_lock_applies_to_all_workspaces(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.act_lock_toolbar.setChecked(True)
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    bars = (window.main_toolbar, window.modeling_toolbar, *draft.drafting_toolbars)
    assert all(not bar.isMovable() and not bar.isFloatable() for bar in bars)
    window.act_lock_toolbar.setChecked(False)
    assert all(bar.isMovable() and bar.isFloatable() for bar in bars)
    draft.reject()
