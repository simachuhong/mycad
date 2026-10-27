# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CAD drafting docks leave the canvas available and retain workspace layout."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.sketch_editor import SketchEditorDialog


def test_parameters_default_right_and_keep_original_controls(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1400, 850)
    editor.show()
    dock = editor.parameter_dock
    assert editor.toolbar_host.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert editor.parameter_tabs.count() == 4
    assert [editor.parameter_tabs.tabText(i) for i in range(4)] == ["绘图", "UCS", "修改", "图形"]
    assert editor.parameter_tabs.isAncestorOf(editor.tool_combo)
    assert editor.parameter_tabs.isAncestorOf(editor.origin_fields["X"])
    assert editor.parameter_tabs.isAncestorOf(editor.numeric_move_button)
    assert editor.tool_panel.maximumWidth() > 285
    assert dock.x() > editor.canvas.x()


def test_floating_parameters_suspend_restore_close_and_reset(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    dock = editor.parameter_dock
    dock.setFloating(True)
    dock.resize(370, 520)
    assert dock.isVisible() and dock.isFloating()
    editor.hide()
    assert not dock.isVisible()
    editor.show()
    assert dock.isVisible() and dock.isFloating()
    dock.close()
    assert dock.isHidden()
    menu = editor.toolbar_menu_button.menu()
    assert menu is not None and dock.toggleViewAction() in menu.actions()
    dock.toggleViewAction().trigger()
    assert dock.isVisible()
    editor.reset_toolbar_layout()
    assert not dock.isFloating()
    assert editor.toolbar_host.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert dock.isVisible()


def test_parameter_layout_roundtrip_with_old_toolbar_state(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    editor.toolbar_host.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, editor.parameter_dock)
    editor.toolbar_host.resizeDocks([editor.parameter_dock], [350], Qt.Orientation.Horizontal)
    editor.parameter_dock.hide()
    state = editor.toolbar_layout_state()
    restored = SketchEditorDialog()
    qtbot.addWidget(restored)
    restored.restore_toolbar_layout(state)
    restored.show()
    assert restored.parameter_dock.isHidden()
    assert (
        restored.toolbar_host.dockWidgetArea(restored.parameter_dock)
        == Qt.DockWidgetArea.LeftDockWidgetArea
    )
    # Legacy settings contain bars but no docks.
    from PySide6.QtWidgets import QMainWindow, QToolBar

    old = QMainWindow()
    qtbot.addWidget(old)
    bar = QToolBar("绘图", old)
    bar.setObjectName("draftingDrawingToolbar")
    old.addToolBar(Qt.ToolBarArea.BottomToolBarArea, bar)
    restored.restore_toolbar_layout(old.saveState())
    assert (
        restored.toolbar_host.toolBarArea(restored.drawing_toolbar)
        == Qt.ToolBarArea.BottomToolBarArea
    )


def populated_editor(qtbot: QtBot, *, committed: bool = True) -> SketchEditorDialog:
    editor = SketchEditorDialog(select_committed_entities=committed)
    qtbot.addWidget(editor)
    editor.resize(1400, 850)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    editor.canvas.entities = [line]
    editor.canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            value=30,
            unit="mm",
            axis="horizontal",
            position_mm=(15, -10),
        )
    ]
    editor.canvas.changed.emit()
    editor.parameter_tabs.setCurrentWidget(editor.navigator)
    return editor


def leaf(editor: SketchEditorDialog, identity: str) -> QTreeWidgetItem:
    from mycad.ui.sketch_navigation import ID_ROLE

    tree = editor.navigator.tree

    def find(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
        if item.data(0, ID_ROLE) == identity:
            return item
        for i in range(item.childCount()):
            child = item.child(i)
            assert child is not None
            result = find(child)
            if result is not None:
                return result
        return None

    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        assert item is not None
        result = find(item)
        if result is not None:
            return result
    raise AssertionError(identity)


def test_navigation_selection_is_bidirectional_and_history_free(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    line = editor.canvas.entities[0]
    assert editor.parameter_tabs.indexOf(editor.navigator) == 3
    assert editor.drafting_docks == (editor.parameter_dock,)
    tree = editor.navigator.tree
    tree.setCurrentItem(leaf(editor, line.entity_id))
    assert editor.canvas.selected_entity_ids == {line.entity_id}
    assert editor.canvas.tool == "选择元素"
    assert not editor.canvas.can_undo
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.changed.emit()
    assert not leaf(editor, line.entity_id).isSelected()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((15, 0))
    )
    assert leaf(editor, line.entity_id).isSelected()
    extra = LineEntity(uuid4().hex, (0, 20), (30, 20))
    assert editor.canvas.replace_draft_entities((line, extra))
    assert leaf(editor, extra.entity_id)
    assert editor.canvas.undo_last_operation()
    root = tree.topLevelItem(0)
    assert root is not None
    entities = root.child(0)
    assert entities is not None and entities.childCount() == 1
    assert leaf(editor, line.entity_id)


def test_navigation_constraints_highlight_and_open_inline_editor(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    constraint = editor.canvas.constraints[0]
    tree = editor.navigator.tree
    original = editor.canvas.grab().toImage()
    item = leaf(editor, constraint.constraint_id)
    tree.setCurrentItem(item)
    assert editor.canvas.selected_constraint_ids == {constraint.constraint_id}
    assert editor.canvas.selected_entity_ids == {editor.canvas.entities[0].entity_id}
    assert editor.canvas.grab().toImage() != original
    tree.itemDoubleClicked.emit(item, 0)
    assert editor.dimensions.candidate == constraint
    assert editor.dimensions.inline_box.isVisible()
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    assert editor.canvas.constraints == [constraint]
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.selected_constraint_ids


def test_navigation_does_not_cancel_pending_geometry_or_dimension_edit(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    editor.canvas.add_coordinate_point((80, 50))
    item = leaf(editor, editor.canvas.entities[0].entity_id)
    editor.navigator.tree.setCurrentItem(item)
    assert editor.canvas.has_pending_geometry
    assert not editor.canvas.selected_entity_ids
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    editor.dimensions.edit(editor.dimension_sources()[0], editor.canvas.constraints[0])
    editor.navigator.tree.clearSelection()
    editor.navigator.tree.setCurrentItem(item)
    assert editor.dimensions.inline_box.isVisible()
    assert editor.dimensions.candidate == editor.canvas.constraints[0]


def test_navigation_keeps_groups_and_selection_when_contents_update(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    tree = editor.navigator.tree
    root = tree.topLevelItem(0)
    assert root is not None
    group = root.child(1)
    assert group is not None
    group.setExpanded(False)
    line = editor.canvas.entities[0]
    tree.setCurrentItem(leaf(editor, line.entity_id))
    editor.canvas.entities.append(LineEntity(uuid4().hex, (0, 20), (30, 20)))
    editor.canvas.changed.emit()
    next_root = tree.topLevelItem(0)
    assert next_root is not None
    next_group = next_root.child(1)
    assert next_group is not None and not next_group.isExpanded()
    assert leaf(editor, line.entity_id).isSelected()


@pytest.mark.parametrize("mode", ["hidden", "frozen", "offplane", "reference"])
def test_navigation_respects_canvas_visibility_and_reference_scope(qtbot: QtBot, mode: str) -> None:
    editor = populated_editor(qtbot, committed=mode != "reference")
    line = LineEntity(uuid4().hex, (0, 20), (30, 20), layer_name="Other")
    layer = SketchLayer("Other", visible=mode != "hidden", frozen=mode == "frozen")
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xz() if mode == "offplane" else WorkPlaneFrame.xy(),
        (line,),
        layers=SketchLayerTable().add(layer),
    )
    editor.set_context_sketches((sketch,))
    item = leaf(editor, line.entity_id)
    assert not item.flags() & Qt.ItemFlag.ItemIsSelectable
    assert not editor.canvas.can_undo
    assert not editor.canvas.selected_entity_ids


def test_unified_floating_dock_suspend_and_restore(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    for dock in editor.drafting_docks:
        dock.setFloating(True)
    editor.hide()
    assert all(not d.isVisible() for d in editor.drafting_docks)
    editor.show()
    assert editor.parameter_tabs.currentWidget() is editor.navigator
    assert editor.parameter_dock.isVisible() and editor.parameter_dock.isFloating()
    editor.reset_toolbar_layout()
    assert all(d.isVisible() and not d.isFloating() for d in editor.drafting_docks)


def test_docks_survive_commit_3d_switch_and_window_recreation(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.parameter_dock.setFloating(True)
    editor.parameter_dock.resize(360, 500)
    editor.parameter_tabs.setCurrentWidget(editor.navigator)
    window.act_view_3d.trigger()
    assert all(not dock.isVisible() for dock in editor.drafting_docks)
    window.act_view_2d.trigger()
    assert editor.parameter_dock.isFloating() and editor.parameter_dock.isVisible()
    assert editor.parameter_tabs.currentWidget() is editor.navigator
    editor.canvas.add_coordinate_point((0, 0))
    editor.canvas.add_coordinate_point((20, 0))
    editor.canvas.end_line_chain()
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() not in (None, editor), timeout=10000)
    next_editor = window.active_sketch_dialog()
    assert next_editor is not None
    assert next_editor.parameter_dock.isFloating() and next_editor.parameter_dock.isVisible()
    assert next_editor.parameter_tabs.indexOf(next_editor.navigator) == 3
    window.store_window_state()
    next_editor.reject()
    window.close()
    second = MainWindow(services=services)
    qtbot.addWidget(second)
    second.show()
    second.act_new_drawing.trigger()
    restored = second.active_sketch_dialog()
    assert restored is not None
    assert restored.parameter_dock.isFloating() and restored.parameter_dock.isVisible()
    assert restored.parameter_tabs.indexOf(restored.navigator) == 3
    restored.reject()


def test_visible_dim_layer_remains_navigable_when_geometry_layer_is_hidden(qtbot: QtBot) -> None:
    from dataclasses import replace

    editor = populated_editor(qtbot)
    dimension = replace(editor.canvas.constraints[0], layer_name="DIM")
    editor.canvas.constraints = [dimension]
    table = editor.layer_table.replace(SketchLayer("0", visible=False))
    editor.canvas.set_layer_table(table, "DIM")
    editor.canvas.changed.emit()
    item = leaf(editor, dimension.constraint_id)
    assert item.flags() & Qt.ItemFlag.ItemIsSelectable
    editor.navigator.tree.setCurrentItem(item)
    assert editor.canvas.selected_constraint_ids == {dimension.constraint_id}
    assert not editor.canvas.selected_entity_ids
    editor.navigator.tree.itemDoubleClicked.emit(item, 0)
    assert editor.dimensions.inline_box.isVisible()


def test_navigation_multiselects_draft_and_committed_without_history(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    other = LineEntity(uuid4().hex, (0, 20), (30, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    editor.set_context_sketches((sketch,))
    tree = editor.navigator.tree
    first = leaf(editor, editor.canvas.entities[0].entity_id)
    second = leaf(editor, other.entity_id)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(first).center()
    )
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tree.visualItemRect(second).center(),
    )
    assert editor.canvas.selected_entity_ids == {
        editor.canvas.entities[0].entity_id,
        other.entity_id,
    }
    assert not editor.canvas.can_undo
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(first).center()
    )
    assert editor.canvas.selected_entity_ids == {editor.canvas.entities[0].entity_id}
    editor.transform_buttons["copy"].click()
    assert editor.canvas.has_active_edit_gesture
    tree.clearSelection()
    tree.setCurrentItem(first)
    assert editor.canvas.has_active_edit_gesture
    assert editor.canvas.selected_entity_ids == {editor.canvas.entities[0].entity_id}


def test_canvas_dimension_edit_selects_matching_navigation_node(qtbot: QtBot) -> None:
    editor = populated_editor(qtbot)
    dimension = editor.canvas.constraints[0]
    editor.dimensions.edit(editor.dimension_sources()[0], dimension)
    assert leaf(editor, dimension.constraint_id).isSelected()
    assert editor.canvas.selected_constraint_ids == {dimension.constraint_id}
    assert not editor.canvas.can_undo


@pytest.mark.parametrize("floating", [False, True])
def test_blocked_navigation_keeps_inline_keyboard_escape(qtbot: QtBot, floating: bool) -> None:
    from PySide6.QtWidgets import QApplication

    editor = populated_editor(qtbot)
    editor.canvas.continuous_lines = True
    extra = LineEntity(uuid4().hex, (0, 20), (30, 20))
    editor.canvas.entities.append(extra)
    editor.canvas.changed.emit()
    editor.parameter_dock.setFloating(floating)
    editor.dimensions.edit(editor.dimension_sources()[0], editor.canvas.constraints[0])
    qtbot.waitUntil(editor.dimensions.value_editor.hasFocus)
    tree = editor.navigator.tree
    item = leaf(editor, extra.entity_id)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center()
    )
    qtbot.waitUntil(editor.dimensions.value_editor.hasFocus, timeout=500)
    focus = QApplication.focusWidget()
    assert focus is not None
    QTest.keyClick(focus, Qt.Key.Key_Escape)
    assert editor.dimensions.candidate is None
    assert not editor.dimensions.inline_box.isVisible()
    assert len(editor.canvas.constraints) == 1


def test_navigation_refresh_preserves_keyboard_current_item(qtbot: QtBot) -> None:
    from mycad.ui.sketch_navigation import ID_ROLE

    editor = populated_editor(qtbot)
    second = LineEntity(uuid4().hex, (0, 20), (30, 20))
    third = LineEntity(uuid4().hex, (0, 40), (30, 40))
    editor.canvas.entities.append(second)
    editor.canvas.changed.emit()
    tree = editor.navigator.tree
    tree.setFocus()
    tree.setCurrentItem(leaf(editor, second.entity_id), 1)
    editor.canvas.entities.append(third)
    editor.canvas.changed.emit()
    current = tree.currentItem()
    assert current is not None and current.data(0, ID_ROLE) == second.entity_id
    assert tree.currentColumn() == 1
    QTest.keyClick(tree, Qt.Key.Key_Down)
    assert editor.canvas.selected_entity_ids == {third.entity_id}


def test_main_layout_reset_keeps_drawing_navigation_and_parameters(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.parameter_dock.setFloating(True)
    editor.parameter_dock.hide()
    window.act_reset_layout.trigger()
    assert not editor.parameter_dock.isFloating()
    assert editor.parameter_dock.isVisible()
    assert window.left_dock.isHidden() and window.right_dock.isHidden()
    window.act_view_3d.trigger()
    assert window.left_dock.isVisible() and window.right_dock.isVisible()
    window.act_view_2d.trigger()
    assert window.left_dock.isHidden() and window.right_dock.isHidden()
    editor.reject()


def test_canvas_has_no_wide_footer_and_controls_remain_available(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1400, 850)
    editor.show()
    qtbot.wait(20)
    assert len(editor.drafting_docks) == 1
    assert editor.tool_panel.isAncestorOf(editor.u_field)
    assert editor.tool_panel.isAncestorOf(editor.coordinate_add_button)
    assert editor.tool_panel.isAncestorOf(editor.end_chain_button)
    assert editor.parameter_tabs.isAncestorOf(editor.undo_entity_button)
    assert editor.drawing_toolbar.isAncestorOf(editor.finish_button)
    assert editor.canvas.mapTo(editor, editor.canvas.rect().bottomLeft()).y() > editor.height() - 45
    editor.parameter_dock.hide()
    assert editor.finish_button.isVisible() and editor.cancel_button.isVisible()


def test_old_navigation_dock_state_does_not_reserve_left_space(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QMainWindow, QWidget

    old = QMainWindow()
    qtbot.addWidget(old)
    old.setCentralWidget(QWidget())
    navigation = QDockWidget("图形导航", old)
    navigation.setObjectName("draftingNavigationDock")
    navigation.setWidget(QWidget())
    old.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, navigation)
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.restore_toolbar_layout(old.saveState())
    editor.show()
    assert len(editor.drafting_docks) == 1
    assert editor.canvas.mapTo(editor, editor.canvas.rect().topLeft()).x() < 20
