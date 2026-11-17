# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Delete acts on selected draft geometry and preserves one-step undo."""

from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.sketch_editor import SketchEditorDialog


def test_delete_selected_geometry_and_dependencies_is_one_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1100, 760)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (-20, 10), (20, 10))
    second = LineEntity(uuid4().hex, (-20, -10), (20, -10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        value=40,
        unit="mm",
    )
    relation = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(second.entity_id, "geometry"),),
        source="inferred",
    )
    canvas.entities = [first, second]
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 10)))
    assert canvas.selected_entity_ids == {first.entity_id}
    canvas.constraints = [dimension, relation]
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.entities == [second]
    assert canvas.constraints == [relation]
    assert not canvas.selected_entity_ids
    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert canvas.entities == [first, second]
    assert canvas.constraints == [dimension, relation]
    QTest.keyClick(canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert canvas.entities == [second]


def test_main_window_ctrl_y_redoes_document_operation(qtbot: QtBot) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 4, "size_y": 4, "size_z": 4})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.setFocus()
    qtbot.waitUntil(window.isActiveWindow, timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    assert window.act_undo.isEnabled()
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not loaded.document.commands and not unit.is_busy, timeout=30000)
    QTest.keyClick(window, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[0].id == "feature.box"


def test_delete_locked_selection_is_atomic_and_empty_selection_is_noop(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_layer_table(
        SketchLayerTable((SketchLayer("0"), SketchLayer("locked", locked=True))), "0"
    )
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    locked = LineEntity(uuid4().hex, (0, 10), (20, 10), layer_name="locked")
    canvas.entities = [first, locked]
    canvas.selected_entity_ids = {first.entity_id, locked.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.entities == [first, locked]
    assert not canvas.can_undo
    assert "锁定" in canvas.message
    canvas.selected_entity_ids.clear()
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not canvas.can_undo


def test_delete_in_numeric_field_does_not_delete_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    canvas.entities = [line]
    canvas.selected_entity_ids = {line.entity_id}
    field = editor.origin_fields["X"]
    field.setFocus()
    field.selectAll()
    QTest.keyClick(field, Qt.Key.Key_Delete)
    assert canvas.entities == [line]
    assert not canvas.can_undo


def test_delete_navigation_constraint_keeps_its_highlighted_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    editor.navigator.selection_requested.emit(
        frozenset[str](), frozenset({dimension.constraint_id})
    )
    assert not canvas.selected_entity_ids
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.entities == [line]
    assert not canvas.constraints
    assert canvas.undo_last_operation()
    assert canvas.constraints == [dimension]
    editor.navigator.selection_requested.emit(frozenset({line.entity_id}), frozenset[str]())
    editor.parameter_tabs.setCurrentWidget(editor.navigator)
    editor.navigator.tree.setFocus()
    QTest.keyClick(editor.navigator.tree, Qt.Key.Key_Delete)
    assert not canvas.entities
    assert not canvas.constraints
