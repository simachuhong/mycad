# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Workspace toolbar docking and startup space allocation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


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
