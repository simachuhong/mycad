# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive polyline line and circular segments."""

import math
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import PolylineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_pline_switches_line_arc_and_back_with_tangent(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "10,0", "A", "20,10", "L", "30,10", ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    polyline = editor.canvas.entities[0]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.points_mm == ((0, 0), (10, 0), (20, 10), (30, 10))
    assert polyline.bulges == pytest.approx((0, math.tan(math.pi / 8), 0))
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == []


def test_pline_three_point_arc_and_undo_segment(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "A", "S", "5,5", "10,0", "U", "S", "5,5", "10,0", ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.points_mm == ((0, 0), (10, 0))
    assert result.bulges == pytest.approx((-1,))


def test_pline_arc_close_and_reject_degenerate_endpoint(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "10,0", "A", "20,0"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "无法" in editor.drawing_command_bar.status.text()
    assert editor.canvas.pending_point_count == 2
    for command in ("20,10", "L", "0,10", "C"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed
    assert result.bulges == pytest.approx((0, math.tan(math.pi / 8), 0, 0))


def test_pline_consecutive_arcs_are_tangent_and_undo(qtbot: QtBot) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "10,0", "A", "20,10", "10,20", ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    polyline = editor.canvas.entities[0]
    assert isinstance(polyline, PolylineEntity)
    first, second = polyline_arc_segment(polyline, 1), polyline_arc_segment(polyline, 2)
    assert first.center_mm == pytest.approx((10, 10))
    assert second.center_mm == pytest.approx(first.center_mm)
    assert polyline.bulges == pytest.approx((0, math.tan(math.pi / 8), math.tan(math.pi / 8)))


def test_pline_mouse_and_canvas_keyboard_switch_arc(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    editor.activateWindow()
    editor.snap_check.setChecked(False)
    editor.tool_buttons["多段线"].click()
    canvas = editor.canvas
    for point in ((0, 0), (10, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_A)
    focused = QApplication.focusWidget()
    assert focused is not None
    QTest.keyClick(focused, Qt.Key.Key_Return)
    assert canvas.polyline_arc_mode
    QTest.mouseMove(canvas, canvas.local_to_screen((20, 10)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 10)))
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.bulges[1] == pytest.approx(math.tan(math.pi / 8), abs=0.03)


def test_pline_arc_commit_save_reopen_and_dxf(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "10,0", "A", "20,10", "L", "30,10", ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "pline.my2d"
    save_document(loaded.document, path)
    window.hide()
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    result = reopened.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.bulges == pytest.approx((0, math.tan(math.pi / 8), 0))
    dxf_path = tmp_path / "pline.dxf"
    write_sketch_dxf(reopened.kernel.sketches[0], dxf_path)
    imported = read_sketch_dxf(dxf_path).sketch.entities[0]
    assert isinstance(imported, PolylineEntity)
    assert imported.bulges == pytest.approx(result.bulges)


@pytest.mark.parametrize(
    ("commands", "radius", "sweep"),
    [
        (("R", "15", "10,10"), 15.0, 2 * math.degrees(math.asin(math.sqrt(200) / 30))),
        (("CE", "0,15", "30,15"), 15.0, 90.0),
        (("A", "60", "10,10"), math.sqrt(200), 60.0),
        (("A", "-60", "10,10"), math.sqrt(200), -60.0),
    ],
)
def test_pline_arc_radius_center_and_angle_options(
    qtbot: QtBot, commands: tuple[str, ...], radius: float, sweep: float
) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "A", *commands, ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    arc = polyline_arc_segment(result, 0)
    assert arc.radius_mm == pytest.approx(radius)
    assert arc.sweep_angle_deg == pytest.approx(sweep)


def test_pline_arc_radius_rejects_invalid_input_and_retries(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("PLINE", "0,0", "A", "R", "-1"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.polyline_arc_stage == "radius"
    for command in ("5", "20,0"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.pending_point_count == 1
    for command in ("10,0", ""):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.bulges == pytest.approx((1,))
