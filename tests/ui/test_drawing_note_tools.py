# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Visible annotation tools write text on paper through real canvas gestures."""

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


def test_dimension_menu_and_side_buttons_work_when_secondary_toolbar_hidden(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (LineEntity(str(uuid4()), (0, 0), (40, 0)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    sheet, view = str(uuid4()), str(uuid4())
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    loaded.bus.execute(
        "drawing.view.create",
        {
            "sheet_id": sheet,
            "view_id": view,
            "source": {"kind": "sketch", "sketch_id": sketch.sketch_id},
            "anchor_mm": [80, 100],
        },
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    bench.annotation_toolbar.hide()
    assert bench.dimension_menu.isVisible()
    assert bench.toolbar.widgetForAction(bench.text_action).isVisible()
    bench.dimension_menu.menu().actions()[0].trigger()
    assert bench.canvas.annotation_mode
    assert bench.parameter_dock.isVisible()
    assert bench.settings_tabs.currentWidget() is bench.annotation_page
    canvas = bench.canvas
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(100, -100))
    )
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(100, -120))
    )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(services.kernel.drawing_state.annotations) == 1
    )
    assert bench.output_scene().resolved_annotations[0].value == 40
    QTest.mouseClick(bench.annotations.creation_buttons["vertical"], Qt.MouseButton.LeftButton)
    assert canvas.annotation_mode
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.annotation_mode


def test_text_in_canvas_edit_move_delete_undo_and_pdf(qtbot: QtBot, tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    bench.text_action.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and bench.canvas.note_mode)
    assert bench.canvas.isVisible()
    canvas = bench.canvas
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(80, -100))
    )
    notes = bench.notes
    assert notes.editor.isVisible()
    notes.editor.setPlainText("技术要求：\n去毛刺")
    notes.editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(notes.editor, Qt.Key.Key_Return)
    assert not services.kernel.drawing_state.notes
    QTest.keyClick(notes.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not unit.is_busy and len(services.kernel.drawing_state.notes) == 1)
    note = services.kernel.drawing_state.notes[0]
    assert note.text == "技术要求：\n去毛刺\n"
    QTest.mouseDClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.note_text_position(note.note_id)
    )
    assert notes.editor.isVisible()
    notes.editor.setPlainText("技术要求：\n锐边倒钝 C1")
    notes.editor.moveCursor(QTextCursor.MoveOperation.End)
    QTest.keyClick(notes.editor, Qt.Key.Key_Delete)  # edits the focused text, not the note
    assert len(services.kernel.drawing_state.notes) == 1
    QTest.keyClick(notes.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert services.kernel.drawing_state.notes[0].text == "技术要求：\n锐边倒钝 C1"
    start = canvas.note_text_position(note.note_id)
    end = start + QPoint(30, -15)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), end)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert services.kernel.drawing_state.notes[0].position_mm != note.position_mm
    pdf = tmp_path / "notes.pdf"
    bench.export_to("pdf", pdf)
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert pdf.exists()
    document = QPdfDocument()
    assert document.load(str(pdf)) == QPdfDocument.Error.None_
    assert "技术要求" in document.getAllText(0).text()
    assert "锐边倒钝 C1" in document.getAllText(0).text()
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.note_text_position(note.note_id)
    )
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and not services.kernel.drawing_state.notes)
    loaded.bus.undo()
    bench.refresh()
    assert services.kernel.drawing_state.notes[0].text == "技术要求：\n锐边倒钝 C1"


def test_text_cancel_and_document_switch_preserve_no_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    bench.text_action.trigger()
    qtbot.waitUntil(lambda: bench.canvas.note_mode)
    canvas = bench.canvas
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(60, -80))
    )
    bench.notes.editor.setPlainText("不提交")
    QTest.keyClick(bench.notes.editor, Qt.Key.Key_Escape)
    assert not bench.notes.pending
    assert not services.kernel.drawing_state.notes
    bench.text_action.trigger()
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(60, -80))
    )
    bench.notes.editor.setPlainText("切文档取消")
    window.bind_document(new_document(services, document_type="drawing2d"))
    assert not bench.notes.pending
    assert not bench.notes.editor.isVisible()
    assert not canvas.note_mode
    assert not services.kernel.drawing_state.notes


def test_document_switch_cancels_a_note_drag(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sheet, note = uuid4(), uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    loaded.bus.execute(
        "drawing.note.create",
        {"note_id": str(note), "sheet_id": str(sheet), "text": "说明", "position_mm": [80, 100]},
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    canvas = bench.canvas
    start = canvas.note_text_position(note)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), start + QPoint(30, -10))
    assert bench.notes.pending
    window.bind_document(new_document(services, document_type="drawing2d"))
    assert not bench.notes.pending
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert not services.kernel.drawing_state.notes


def test_new_sheet_preserves_active_text_until_completion(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    unit = window.execution_unit
    assert unit is not None
    bench.text_action.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and bench.canvas.note_mode)
    original_sheet = bench.sheet_id
    canvas = bench.canvas
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(80, -100))
    )
    bench.notes.editor.setPlainText("保留在原图纸")
    bench.sheet_action.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert bench.sheet_id == original_sheet
    assert len(services.kernel.drawing_state.sheets) == 1
    assert bench.notes.editor.isVisible()
    assert bench.notes.editor.toPlainText() == "保留在原图纸"
    QTest.keyClick(bench.notes.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not unit.is_busy and not bench.notes.pending)
    assert services.kernel.drawing_state.notes[0].sheet_id == original_sheet
    bench.sheet_action.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and len(services.kernel.drawing_state.sheets) == 2)
    assert bench.sheet_id != original_sheet
