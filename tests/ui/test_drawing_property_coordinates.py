# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Coordinate properties use the same constrained editing path as grips."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_property_coordinate_edits_draft_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )
    coordinate_item = table.item(row, 1)
    assert coordinate_item is not None and "双击" in coordinate_item.toolTip()

    def accept_coordinate() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("12,3")
        dialog.accept()

    QTimer.singleShot(100, accept_coordinate)
    table.itemDoubleClicked.emit(coordinate_item)
    assert editor.canvas.entities[0] == LineEntity(line.entity_id, (0, 0), (12, 3))
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == line


def test_property_coordinate_edits_saved_geometry_and_replays(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )

    def accept_coordinate() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("12,3")
        dialog.accept()

    QTimer.singleShot(100, accept_coordinate)
    table.itemDoubleClicked.emit(table.item(row, 1))
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.saved_handle_drag_active, timeout=15000
    )
    moved = LineEntity(line.entity_id, (0, 0), (12, 3))
    assert services.kernel.sketches[0].entities[0] == moved
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == line
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == moved


def test_property_coordinate_accepting_unchanged_precision_is_noop(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (0.12345678901234567, 3))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )
    position = editor.canvas.history_position

    def accept_unchanged() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.accept()

    QTimer.singleShot(100, accept_unchanged)
    table.itemDoubleClicked.emit(table.item(row, 1))
    assert editor.canvas.entities[0] == line
    assert editor.canvas.history_position == position


def test_property_coordinate_rejects_saved_fixed_point(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )
    before = tuple(loaded.document.commands)

    def accept_coordinate() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("12,3")
        dialog.accept()

    QTimer.singleShot(100, accept_coordinate)
    table.itemDoubleClicked.emit(table.item(row, 1))
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.saved_handle_drag_active, timeout=15000
    )
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches[0].entities[0] == line


@pytest.mark.parametrize("kind", ["circle", "rectangle", "point"])
def test_property_coordinate_supports_other_point_handles(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import CircleEntity, PointEntity, RectangleEntity

    identity = uuid4().hex
    if kind == "circle":
        entity = CircleEntity(identity, (0, 0), 4)
        expected = CircleEntity(identity, (2, 3), 4)
        label = "圆心"
    elif kind == "rectangle":
        entity = RectangleEntity(identity, (0, 0), (10, 10))
        expected = RectangleEntity(identity, (0, 0), (2, 3))
        label = "对角点"
    else:
        entity = PointEntity(identity, (0, 0))
        expected = PointEntity(identity, (2, 3))
        label = "位置"
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {identity}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == label
    )

    def accept_coordinate() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("2,3")
        dialog.accept()

    QTimer.singleShot(100, accept_coordinate)
    table.itemDoubleClicked.emit(table.item(row, 1))
    assert editor.canvas.entities[0] == expected


@pytest.mark.parametrize("action", ["invalid", "cancel"])
def test_property_coordinate_invalid_or_cancel_preserves_draft(qtbot: QtBot, action: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )
    position = editor.canvas.history_position

    def finish_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        if action == "invalid":
            dialog.setTextValue("not-a-coordinate")
            dialog.accept()
        else:
            dialog.reject()

    QTimer.singleShot(100, finish_dialog)
    table.itemDoubleClicked.emit(table.item(row, 1))
    assert editor.canvas.entities[0] == line
    assert editor.canvas.history_position == position


def test_property_coordinate_rejects_locked_layer(qtbot: QtBot) -> None:
    from mycad.core.sketch import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("locked"))
    editor.set_document_layers(layers, "DIM")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="locked")
    assert editor.canvas.replace_draft_entities((line,))
    editor.set_document_layers(layers.replace(SketchLayer("locked", locked=True)), "DIM")
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "终点"
    )
    position = editor.canvas.history_position
    table.itemDoubleClicked.emit(table.item(row, 1))
    assert "锁定" in editor.status_label.text()
    assert editor.canvas.entities[0] == line
    assert editor.canvas.history_position == position


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_property_edits_chosen_vertex(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import PolylineEntity, SplineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    identity = uuid4().hex
    points = ((0, 0), (5, 0), (10, 0), (15, 0))
    entity = (
        PolylineEntity(identity, points, False)
        if kind == "polyline"
        else SplineEntity(identity, points)
    )
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {identity}
    editor.canvas.changed.emit()
    editor.property_vertex_index.setValue(2)
    editor.property_vertex_coordinate.setText("5,2")
    QTest.keyClick(editor.property_vertex_coordinate, Qt.Key.Key_Return)
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity | SplineEntity)
    result_points = (
        result.points_mm if isinstance(result, PolylineEntity) else result.control_points_mm
    )
    assert result_points[1] == (5, 2)
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == entity


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_property_vertex_selection_follows_canvas_and_highlights(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import PolylineEntity, SplineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 750)
    editor.show()
    points = ((0, 0), (15, 0), (30, 0), (45, 5))
    identity = uuid4().hex
    entity = (
        PolylineEntity(identity, points, False)
        if kind == "polyline"
        else SplineEntity(identity, points)
    )
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {identity}
    editor.canvas.changed.emit()
    editor.parameter_tabs.setCurrentIndex(
        editor.parameter_tabs.indexOf(editor.properties_table.parentWidget())
    )
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(points[2]))
    assert editor.property_vertex_index.value() == 3
    assert editor.property_vertex_coordinate.text() == "30.0,0.0"
    assert canvas.active_property_vertex == (identity, 2)
    QTest.keyClick(editor.property_vertex_index, Qt.Key.Key_Down)
    assert canvas.active_property_vertex == (identity, 1)
    image = canvas.grab().toImage()
    active = canvas.local_to_screen(points[1])
    inactive = canvas.local_to_screen(points[2])
    assert image.pixelColor(active) != image.pixelColor(inactive)
    canvas.selected_entity_ids.clear()
    canvas.changed.emit()
    assert canvas.active_property_vertex is None


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_vertex_editor_is_visible_and_usable_on_properties_page(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import PolylineEntity, SplineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 750)
    editor.show()
    identity = uuid4().hex
    points = ((0, 0), (5, 0), (10, 0), (15, 0))
    entity = (
        PolylineEntity(identity, points, False)
        if kind == "polyline"
        else SplineEntity(identity, points)
    )
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {identity}
    editor.canvas.changed.emit()
    editor.parameter_tabs.setCurrentIndex(
        editor.parameter_tabs.indexOf(editor.properties_table.parentWidget())
    )
    assert editor.property_vertex_controls.isVisible()
    assert editor.property_vertex_coordinate.isVisible()
    editor.property_vertex_index.setValue(2)
    QTest.mouseClick(editor.property_vertex_coordinate, Qt.MouseButton.LeftButton)
    QTest.keyClick(
        editor.property_vertex_coordinate, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
    )
    QTest.keyClicks(editor.property_vertex_coordinate, "5,2")
    QTest.keyClick(editor.property_vertex_coordinate, Qt.Key.Key_Return)
    assert QApplication.activeModalWidget() is None
    changed = editor.canvas.entities[0]
    assert isinstance(changed, PolylineEntity | SplineEntity)
    changed_points = (
        changed.points_mm if isinstance(changed, PolylineEntity) else changed.control_points_mm
    )
    assert changed_points == (points[0], (5, 2), *points[2:])
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == entity
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.entities[0] == changed


def test_property_vertex_can_be_edited_inline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    entity = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (10, 0)), False)
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {entity.entity_id}
    editor.canvas.changed.emit()
    editor.property_vertex_index.setValue(2)
    editor.property_vertex_coordinate.setText("5,2")
    QTest.keyClick(editor.property_vertex_coordinate, Qt.Key.Key_Return)
    changed = editor.canvas.entities[0]
    assert isinstance(changed, PolylineEntity)
    assert changed.points_mm[1] == (5, 2)
    assert QApplication.activeModalWidget() is None
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == entity


def test_inline_vertex_follows_selection_and_preserves_unfinished_input(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, SplineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (10, 0)), False)
    spline = SplineEntity(uuid4().hex, ((0, 1), (2, 1), (4, 1), (6, 1)))
    assert editor.canvas.replace_draft_entities((polyline, spline))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {polyline.entity_id}
    editor.canvas.changed.emit()
    editor.property_vertex_index.setValue(2)
    editor.property_vertex_coordinate.setText("5,")
    editor.canvas.changed.emit()
    assert editor.property_vertex_coordinate.text() == "5,"
    editor.canvas.selected_entity_ids = {spline.entity_id}
    editor.canvas.changed.emit()
    assert editor.property_vertex_label.text() == "控制点"
    assert editor.property_vertex_index.value() == 1
    assert editor.property_vertex_coordinate.text() == "0.0,1.0"
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.changed.emit()
    assert editor.property_vertex_controls.isHidden()


def test_property_edits_saved_polyline_vertex_and_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    original = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (10, 0)), False)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (original,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {original.entity_id}
    editor.canvas.changed.emit()

    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen((5, 0)),
    )
    assert editor.property_vertex_index.value() == 2
    editor.property_vertex_coordinate.setText("5,2")
    QTest.keyClick(editor.property_vertex_coordinate, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.saved_handle_drag_active, timeout=15000
    )
    updated = services.kernel.sketches[0].entities[0]
    assert isinstance(updated, PolylineEntity)
    assert updated.points_mm[1] == (5, 2)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == original


def test_property_length_edits_draft_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 2), (4, 6))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    row = next(
        i
        for i in range(table.rowCount())
        if (item := table.item(i, 0)) is not None and item.text() == "长度"
    )
    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText("10")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert QApplication.activeModalWidget() is None
    assert editor.canvas.entities[0] == LineEntity(line.entity_id, (1, 2), (7, 10))
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == line


@pytest.mark.parametrize("driving", [False, True])
def test_property_length_saved_respects_driving_dimension(
    qtbot: QtBot, driving: bool, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (1, 2), (4, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        driving=driving,
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    row = next(
        i
        for i in range(table.rowCount())
        if (item := table.item(i, 0)) is not None and item.text() == "长度"
    )

    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText("10")
    QTest.keyClick(field, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.saved_handle_drag_active, timeout=15000
    )
    changed = services.kernel.sketches[0]
    if driving:
        assert changed.entities[0] == line
        assert changed.constraints[0] == dimension
        assert "约束" in editor.property_feedback_label.text()
        assert "未修改" in editor.property_feedback_label.text()
        assert field.text() == "5.0"
    else:
        assert changed.entities[0] == LineEntity(line.entity_id, (1, 2), (7, 10)), (
            editor.canvas.message
        )
        assert changed.constraints[0].value == pytest.approx(10)
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.sketches[0].entities[0] == line
        assert services.kernel.sketches[0].constraints[0].value == 5
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.sketches[0] == changed
        path = tmp_path / "length-property.my2d"
        save_document(loaded.document, path)
        reopened_services = app.build_app(discoverers=())
        app.open_app_document(reopened_services, path)
        assert reopened_services.kernel.sketches[0] == changed


@pytest.mark.parametrize("value", ["0", "-2", "nan", "text", "1e309"])
def test_property_length_rejects_invalid_values(qtbot: QtBot, value: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(i, 0) for i in range(table.rowCount())]
    row = next(i for i, item in enumerate(labels) if item is not None and item.text() == "长度")
    position = editor.canvas.history_position

    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText(value)
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert editor.canvas.entities == [line]
    assert editor.canvas.history_position == position
    assert "长度" in editor.status_label.text()


def test_property_length_rejects_locked_reference_dimension(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import SketchLayer
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, drag_preview=services.kernel.preview_sketch_drag
    )
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("locked", locked=True))
    editor.set_document_layers(layers, "DIM")
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
        layer_name="locked",
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(i, 0) for i in range(table.rowCount())]
    row = next(i for i, item in enumerate(labels) if item is not None and item.text() == "长度")
    history = editor.canvas.history_position

    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText("10")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert editor.canvas.entities == [line]
    assert editor.canvas.constraints == [dimension]
    assert editor.canvas.history_position == history
    assert "锁" in editor.status_label.text()


@pytest.mark.parametrize("kind", ["coordinate", "radius"])
def test_numeric_properties_edit_in_place(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    entity = (
        LineEntity(uuid4().hex, (0, 0), (10, 0))
        if kind == "coordinate"
        else CircleEntity(uuid4().hex, (0, 0), 5)
    )
    assert editor.canvas.replace_draft_entities((entity,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {entity.entity_id}
    editor.canvas.changed.emit()
    label = "终点" if kind == "coordinate" else "半径"
    table = editor.properties_table
    labels = [table.item(i, 0) for i in range(table.rowCount())]
    row = next(i for i, item in enumerate(labels) if item is not None and item.text() == label)
    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText("12,3" if kind == "coordinate" else "8")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert QApplication.activeModalWidget() is None
    expected = (
        LineEntity(entity.entity_id, (0, 0), (12, 3))
        if kind == "coordinate"
        else CircleEntity(entity.entity_id, (0, 0), 8)
    )
    assert editor.canvas.entities == [expected]
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [entity]


def test_inline_length_rebinds_after_small_change_and_accepts_another(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table

    def length_field() -> QLineEdit:
        labels = [table.item(i, 0) for i in range(table.rowCount())]
        row = next(i for i, item in enumerate(labels) if item is not None and item.text() == "长度")
        field = table.cellWidget(row, 1)
        assert isinstance(field, QLineEdit)
        return field

    field = length_field()
    field.setFocus()
    field.selectAll()
    QTest.keyClicks(field, "5.000001")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert isinstance(editor.canvas.entities[0], LineEntity)
    assert editor.canvas.entities[0].end_mm == pytest.approx((5.000001, 0))
    field = length_field()
    field.setText("7")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert isinstance(editor.canvas.entities[0], LineEntity)
    assert editor.canvas.entities[0].end_mm == pytest.approx((7, 0))


@pytest.mark.parametrize("kind", ["coordinate", "radius"])
def test_numeric_properties_edit_saved_objects_in_place(qtbot: QtBot, kind: str) -> None:
    from mycad import app
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    entity = (
        LineEntity(uuid4().hex, (0, 0), (10, 0))
        if kind == "coordinate"
        else CircleEntity(uuid4().hex, (0, 0), 5)
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {entity.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    label = "终点" if kind == "coordinate" else "半径"
    labels = [table.item(i, 0) for i in range(table.rowCount())]
    row = next(i for i, item in enumerate(labels) if item is not None and item.text() == label)
    field = table.cellWidget(row, 1)
    assert isinstance(field, QLineEdit)
    field.setText("12,3" if kind == "coordinate" else "8")
    QTest.keyClick(field, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and not editor.canvas.saved_handle_drag_active
        ),
        timeout=15000,
    )
    expected = (
        LineEntity(entity.entity_id, (0, 0), (12, 3))
        if kind == "coordinate"
        else CircleEntity(entity.entity_id, (0, 0), 8)
    )
    assert services.kernel.sketches[0].entities == (expected,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities == (entity,)
