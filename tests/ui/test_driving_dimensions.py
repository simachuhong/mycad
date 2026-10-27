# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Driving edits stay inline and preserve geometry/history on cancellation."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def drawing(qtbot: QtBot) -> SketchEditorDialog:
    services = build_app(discoverers=())
    editor = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.resize(1400, 850)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (30, 0))]
    editor.canvas.changed.emit()
    return editor


def place(editor: SketchEditorDialog) -> None:
    editor.dimensions.buttons["horizontal"].click()
    for point in ((15, 0), (15, -15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )


def test_new_dimension_drives_inline_by_default_and_cancels_without_history(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    assert editor.dimensions.driving_check.isChecked()
    place(editor)
    assert not editor.canvas.constraints
    assert editor.dimensions.inline_box.isVisible()
    assert editor.dimensions.anchor_combo.isVisible()
    assert editor.dimensions.command_row.indexOf(editor.dimensions.anchor_combo) >= 0
    assert QApplication.activeModalWidget() is None
    editor.dimensions.value_editor.setValue(40)
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    assert not editor.canvas.constraints
    assert not editor.canvas.can_undo
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == (30, 0)


@pytest.mark.parametrize(
    "mode,start,end", [("auto", 0, 40), ("start", 0, 40), ("end", -10, 30), ("symmetric", -5, 35)]
)
def test_anchor_control_drives_geometry_and_preserves_dim_layer(
    qtbot: QtBot, mode: str, start: int, end: int
) -> None:
    editor = drawing(qtbot)
    editor.dimensions.anchor_combo.setCurrentIndex(editor.dimensions.anchor_combo.findData(mode))
    place(editor)
    editor.dimensions.value_editor.setValue(40)
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Return)
    assert len(editor.canvas.constraints) == 1
    dimension = editor.canvas.constraints[0]
    assert dimension.driving
    assert dimension.anchor_mode == mode
    assert dimension.layer_name == "DIM"
    assert not editor.dimensions.inline_box.isVisible()
    qtbot.waitUntil(editor.canvas.hasFocus, timeout=1000)
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((start, 0))
    assert line.end_mm == pytest.approx((end, 0))
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.constraints == [dimension]


def test_reference_can_convert_to_driving_without_replacing_identity(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.dimensions.driving_check.setChecked(False)
    place(editor)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    original = editor.canvas.constraints[0]
    assert not original.driving
    editor.dimensions.edit(editor.dimension_sources()[0], original)
    assert editor.dimensions.value_editor.isReadOnly()
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.value_editor.setValue(40)
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Return)
    revised = editor.canvas.constraints[0]
    assert revised.constraint_id == original.constraint_id
    assert revised.position_mm == original.position_mm
    assert revised.layer_name == "DIM"
    assert revised.driving
    assert revised.value == 40
    editor.dimensions.edit(editor.dimension_sources()[0], revised)
    editor.dimensions.driving_check.setChecked(False)
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Return)
    assert not editor.canvas.constraints[0].driving
    assert editor.canvas.constraints[0].value == pytest.approx(40)


def test_anchor_conflict_highlights_canvas_without_changing_draft(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    line = editor.canvas.entities[0]
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    editor.canvas.constraints = [fixed]
    editor.dimensions.anchor_combo.setCurrentIndex(editor.dimensions.anchor_combo.findData("start"))
    place(editor)
    editor.dimensions.value_editor.setValue(40)
    assert line.entity_id in editor.canvas.dimension_error_entity_ids
    assert "冲突" in editor.dimensions.diagnostics_label.text()
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Return)
    assert editor.canvas.entities == [line]
    assert editor.canvas.constraints == [fixed]
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    assert not editor.canvas.dimension_error_entity_ids


def test_committed_anchor_edit_is_bus_backed_and_survives_reopen(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        axis="horizontal",
        layer_name="DIM",
        position_mm=(15, -15),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.dimensions.edit(services.kernel.sketches[0], dimension)
    editor.dimensions.anchor_combo.setCurrentIndex(editor.dimensions.anchor_combo.findData("end"))
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.value_editor.setValue(40)
    unit = window.execution_unit
    assert unit is not None

    def preview_ready() -> bool:
        original, candidate = editor.dimensions.original, editor.dimensions.candidate
        return (
            not unit.is_busy
            and original is not None
            and candidate is not None
            and editor.dimensions.accepted_preview(original, candidate) is not None
        )

    qtbot.waitUntil(preview_ready, timeout=10000)
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    current = services.kernel.sketches[0]
    assert current.constraints[0].anchor_mode == "end"
    solved = current.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((-10, 0))
    assert solved.end_mm == pytest.approx((30, 0))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 1, timeout=10000)
    assert services.kernel.sketches[0].entities == (line,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    path = tmp_path / "driving.my2d"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches[0] == current


def test_editing_existing_reference_does_not_change_new_dimension_default(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    line = editor.canvas.entities[0]
    reference = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        layer_name="DIM",
    )
    editor.canvas.constraints = [reference]
    editor.dimensions.edit(editor.dimension_sources()[0], reference)
    assert not editor.dimensions.driving_check.isChecked()
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    editor.dimensions.buttons["horizontal"].click()
    assert editor.dimensions.driving_check.isChecked()


def test_preview_dimensions_follow_solved_geometry_and_cancel_restores_measurements(
    qtbot: QtBot,
) -> None:
    editor = drawing(qtbot)
    line = editor.canvas.entities[0]
    reference = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        layer_name="DIM",
        position_mm=(15, 10),
    )
    editor.canvas.constraints = [reference]
    place(editor)
    editor.dimensions.value_editor.setValue(40)
    preview_line = editor.canvas.dimension_entities()[line.entity_id]
    assert isinstance(preview_line, LineEntity)
    assert preview_line.end_mm == pytest.approx((40, 0))
    preview_reference = next(
        d for d in editor.canvas.visible_dimensions() if d.constraint_id == reference.constraint_id
    )
    assert preview_reference.value == pytest.approx(40)
    assert editor.canvas.entities == [line]
    assert editor.canvas.constraints == [reference]
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    assert editor.canvas.dimension_entities()[line.entity_id] == line
    assert editor.canvas.visible_dimensions() == (reference,)
