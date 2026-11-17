# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Video-style CIRCLE TTR interactions."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_ttr_two_picks_and_radius_create_one_undoable_circle(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    circle = canvas.entities[-1]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == pytest.approx((5, math.sqrt(11)))
    assert canvas.undo_last_operation() and canvas.entities == [first, second]
    assert canvas.redo_last_operation() and canvas.entities[-1] == circle


def test_ttr_invalid_radius_and_escape_leave_sources_unchanged(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.circle_ttr_radius_pending and canvas.entities == list(circles)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.circle_ttr_active and not canvas.has_active_edit_gesture
    assert canvas.entities == list(circles)


def test_ttr_infers_local_tangencies_and_undo_restores_them(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and not canvas.constraints
    assert canvas.redo_last_operation()
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2


def test_ttr_respects_disabled_automatic_relations(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert (
        len(canvas.entities) == 3 and not canvas.constraints and not canvas.pending_cross_tangencies
    )


def test_ttr_enter_reuses_last_successful_radius(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    command = editor.drawing_command_bar.input
    for radius in ("4", ""):
        for value in ("CIRCLE", "TTR"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        for point in ((1.7, 1.1), (8.3, 1.1)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
        command.setText(radius)
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert len(canvas.entities) == 3
        result = canvas.entities[-1]
        assert isinstance(result, CircleEntity) and result.radius_mm == 4
        assert canvas.undo_last_operation()


def test_ttr_reference_dimensions_create_the_enclosing_circle(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 900)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 27), CircleEntity(uuid4().hex, (0, -65), 20))
    assert canvas.replace_draft_entities(circles)
    canvas.fit_view()
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-23, 13), (-13, -80)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("70")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    result = canvas.entities[-1]
    assert isinstance(result, CircleEntity) and result.radius_mm == 70
    for source in circles:
        assert math.dist(result.center_mm, source.center_mm) == pytest.approx(70 - source.radius_mm)


def test_ttr_rejects_source_change_before_radius(qtbot: QtBot) -> None:
    from dataclasses import replace

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    changed = replace(first, radius_mm=3)
    assert canvas.replace_draft_entities((changed, second))
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [changed, second]
    assert "变化" in editor.drawing_command_bar.status.text()


def test_ttr_saved_sources_survive_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for value in ("CIRCLE", "TTR"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    assert len(editor.canvas.pending_cross_tangencies) == 2
    result = editor.canvas.entities[0]
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    path = tmp_path / "circle-ttr.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    assert path.is_file()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy)
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = tuple(entity for entity, _layer in reopened.canvas.background_entities)
    assert all(circle in entities for circle in circles) and result in entities
    assert len(services.kernel.cross_sketch_tangencies) == 2


@pytest.mark.parametrize("video_case", [False, True])
def test_tangent_arc_saved_sources_commit_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, video_case: bool
) -> None:
    from mycad import app
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (
        (((0, 0), 20), ((0, 0), 9), ((0, 65), 27), ((0, 65), 12), ((90, 45), 30), ((90, 45), 17))
        if video_case
        else (((-15, 0), 5), ((15, 0), 5))
    )
    sources = tuple(CircleEntity(uuid4().hex, center, radius) for center, radius in circles)
    assert editor.canvas.replace_draft_entities(sources)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.fit_view()
    editor.dynamic_input_check.setChecked(video_case)
    bar = editor.drawing_command_bar.input
    for value in ("ARC", "TTR"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    picks = ((24, 78), (71, 69)) if video_case else ((-15, 5), (15, 5))
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if video_case:
        from PySide6.QtWidgets import QLineEdit

        QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen(picks[-1]))
        editor.canvas.setFocus()
        QTest.keyClick(editor.canvas, Qt.Key.Key_3)
        entry = editor.canvas.findChild(QLineEdit, "drawingCursorEntry")
        assert entry is not None and entry.isVisible()
        QTest.keyClicks(entry, "2")
        QTest.mouseClick(editor.canvas, Qt.MouseButton.RightButton)
    else:
        bar.setText("12")
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    arc = editor.canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == pytest.approx(32 if video_case else 12)
    tangent_sources = (sources[2], sources[4]) if video_case else (sources[0], sources[1])
    assert all(tangent_on_curves(source, arc) for source in tangent_sources)
    assert len(editor.canvas.pending_cross_tangencies) == 2
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    dxf = tmp_path / "arc-ttr.dxf"
    reports: list[str] = []

    def choose_dxf(*_args: object) -> tuple[str, str]:
        return str(dxf), ""

    def accept_preview(dialog: DxfOutputPreviewDialog) -> int:
        reports.append(dialog.report_label.text())
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_dxf)
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(lambda: dxf.exists() and not unit.is_busy, timeout=20000)
    assert reports and "对象相切关系未导出" in reports[0]
    imported = read_sketch_dxf(dxf)
    assert all(source in imported.sketch.entities for source in sources)
    exported_arc = next(
        entity for entity in imported.sketch.entities if isinstance(entity, ArcEntity)
    )
    assert exported_arc.entity_id == arc.entity_id
    assert exported_arc.center_mm == pytest.approx(arc.center_mm)
    assert exported_arc.radius_mm == pytest.approx(arc.radius_mm)
    assert exported_arc.start_angle_deg % 360 == pytest.approx(arc.start_angle_deg % 360)
    assert exported_arc.sweep_angle_deg == pytest.approx(arc.sweep_angle_deg)
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "arc-ttr.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    assert any(arc in sketch.entities for sketch in services.kernel.sketches)
    reopened.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 2
