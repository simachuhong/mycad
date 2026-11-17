# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deferred two-source tangents in the interactive 2D line command."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.fillet_curves import tangent_on_curves
from mycad.core.sketch import CircleEntity, LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def _submit(editor: SketchEditorDialog, *values: str) -> None:
    for value in values:
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)


@pytest.mark.parametrize("inference", [False, True])
def test_tangent_line_relations_undo_and_redo(qtbot: QtBot, inference: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(inference)
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    _submit(editor, "LINE", "TAN")
    canvas.add_coordinate_point((0, 2), exact_point=True)
    _submit(editor, "TAN")
    canvas.add_coordinate_point((10, 2), exact_point=True)
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], LineEntity)
    result = canvas.entities[-1]
    assert tangent_on_curves(result, circles[0]) and tangent_on_curves(result, circles[1])
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == (
        2 if inference else 0
    )
    assert canvas.undo_last_operation() and canvas.entities == list(circles)
    assert canvas.redo_last_operation() and canvas.entities[-1] == result


def test_tangent_line_escape_and_stale_source_preserve_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first, second = CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    _submit(editor, "LINE", "TAN")
    canvas.add_coordinate_point((0, 2), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.line_tangent_active and canvas.entities == [first, second]
    _submit(editor, "TAN")
    canvas.add_coordinate_point((0, 2), exact_point=True)
    changed = replace(first, radius_mm=3)
    assert canvas.replace_draft_entities((changed, second))
    _submit(editor, "TAN")
    canvas.add_coordinate_point((10, 2), exact_point=True)
    assert canvas.entities == [changed, second] and "变化" in canvas.message


def test_tangent_line_saved_sources_persist_cross_relations_and_undo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    _submit(editor, "LINE", "TAN")
    editor.canvas.add_coordinate_point((0, 2), exact_point=True)
    _submit(editor, "TAN")
    editor.canvas.add_coordinate_point((10, 2), exact_point=True)
    assert len(editor.canvas.entities) == 1 and isinstance(editor.canvas.entities[0], LineEntity)
    line = editor.canvas.entities[0]
    assert len(editor.canvas.pending_cross_tangencies) == 2
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert len(services.kernel.cross_sketch_tangencies) == 2
    path = tmp_path / "two-tangents.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert len(services.kernel.cross_sketch_tangencies) == 2
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert entities[line.entity_id] == line
    assert all(entities[circle.entity_id] == circle for circle in circles)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert not services.kernel.cross_sketch_tangencies
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert line.entity_id not in entities and all(
        entities[circle.entity_id] == circle for circle in circles
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_delete_saved_tangent_line_with_dimension_in_one_transaction(
    qtbot: QtBot, tmp_path: Path, mixed: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["radius"].click()
    for point in ((2, 0), (4, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    _submit(editor, "LINE", "TAN")
    editor.canvas.add_coordinate_point((0, 2), exact_point=True)
    _submit(editor, "TAN")
    editor.canvas.add_coordinate_point((10, 2), exact_point=True)
    line = editor.canvas.entities[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert len(services.kernel.cross_sketch_tangencies) == 2
    canvas = editor.canvas
    editor.tool_combo.setCurrentText("选择元素")
    canvas.selected_entity_ids = {line.entity_id}
    draft_line = LineEntity(uuid4().hex, (30, 0), (40, 0))
    if mixed:
        assert canvas.replace_draft_entities((draft_line,))
        canvas.selected_entity_ids.add(draft_line.entity_id)
    canvas.selected_constraint_ids = {dimension.constraint_id}
    count = len(loaded.document.commands)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    if mixed:
        qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=15000)
        assert not canvas.entities and canvas.undo_last_operation()
        assert canvas.entities == [draft_line] and canvas.redo_last_operation()
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
        )
    else:
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=15000
        )
    assert not services.kernel.cross_sketch_tangencies
    assert all(
        line not in sketch.entities and dimension not in sketch.constraints
        for sketch in services.kernel.sketches
    )
    path = tmp_path / "tangent-dimension-delete.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert not reopened_services.kernel.cross_sketch_tangencies
    reopened.bus.undo()
    assert len(reopened_services.kernel.cross_sketch_tangencies) == 2
    assert any(line in sketch.entities for sketch in reopened_services.kernel.sketches)
    assert any(dimension in sketch.constraints for sketch in reopened_services.kernel.sketches)
    reopened.bus.redo()
    assert not reopened_services.kernel.cross_sketch_tangencies


def test_tangent_line_mixed_sources_preserves_relations_on_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    saved = CircleEntity(uuid4().hex, (0, 0), 2)
    draft = CircleEntity(uuid4().hex, (10, 0), 2)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    canvas.set_background_sketches((source,), WorkPlaneFrame.xy())
    assert canvas.replace_draft_entities((draft,))
    _submit(editor, "LINE", "TAN")
    canvas.add_coordinate_point((0, 2), exact_point=True)
    _submit(editor, "TAN")
    canvas.add_coordinate_point((10, 2), exact_point=True)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[-1], LineEntity)
    line = canvas.entities[-1]
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 1
    assert canvas.pending_cross_tangencies == [(saved.entity_id, line.entity_id)]
    assert canvas.undo_last_operation() and canvas.entities == [draft]
    assert not canvas.pending_cross_tangencies
    assert canvas.redo_last_operation() and canvas.entities[-1] == line
    assert canvas.pending_cross_tangencies == [(saved.entity_id, line.entity_id)]
    assert source.entities == (saved,)


@pytest.mark.parametrize("delete_source", [False, True])
def test_delete_draft_tangent_and_saved_dimension_together(
    qtbot: QtBot, delete_source: bool
) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["radius"].click()
    for point in ((2, 0), (4, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    _submit(editor, "LINE", "TAN")
    editor.canvas.add_coordinate_point((0, 2), exact_point=True)
    _submit(editor, "TAN")
    editor.canvas.add_coordinate_point((10, 2), exact_point=True)
    canvas = editor.canvas
    line = canvas.entities[0]
    assert len(canvas.pending_cross_tangencies) == 2
    editor.tool_combo.setCurrentText("选择元素")
    canvas.selected_entity_ids = {circles[0].entity_id if delete_source else line.entity_id}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=15000)
    assert canvas.entities == ([line] if delete_source else [])
    assert len(canvas.pending_cross_tangencies) == (1 if delete_source else 0)
    assert canvas.undo_last_operation() and canvas.entities == [line]
    assert len(canvas.pending_cross_tangencies) == 2
    assert canvas.redo_last_operation()
    assert len(canvas.pending_cross_tangencies) == (1 if delete_source else 0)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert len(services.kernel.cross_sketch_tangencies) == (1 if delete_source else 0)
    assert all(dimension not in sketch.constraints for sketch in services.kernel.sketches)


def test_tangent_line_mouse_selection_on_canvas(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert canvas.replace_draft_entities(circles)
    canvas.fit_view()
    _submit(editor, "LINE", "TAN")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    _submit(editor, "TAN")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 2)))
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], LineEntity)
    assert tangent_on_curves(canvas.entities[-1], circles[0])
    assert tangent_on_curves(canvas.entities[-1], circles[1])


def test_tangent_source_coordinates_clear_command_input_after_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    _submit(editor, "LINE", "TAN", "0,2")
    assert editor.canvas.line_tangent_active
    assert editor.drawing_command_bar.input.text() == ""
    _submit(editor, "TAN", "10,2")
    assert editor.drawing_command_bar.input.text() == ""
    assert len(editor.canvas.entities) == 3 and isinstance(editor.canvas.entities[-1], LineEntity)


def test_recorded_exercise_builds_three_circle_tangent_profile(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    qtbot.waitExposed(editor)
    _build_recorded_exercise(editor)


def _build_recorded_exercise(editor: SketchEditorDialog) -> None:
    from mycad.core.sketch import ArcEntity

    canvas = editor.canvas
    for center, diameter in (
        ("0,0", "40"),
        ("0,0", "18"),
        ("0,65", "54"),
        ("0,65", "24"),
        ("90,45", "60"),
        ("90,45", "34"),
    ):
        _submit(editor, "CIRCLE", center, "D", diameter)
    circles = tuple(item for item in canvas.entities if isinstance(item, CircleEntity))
    assert len(circles) == 6
    canvas.fit_view()
    _submit(editor, "FILLET", "R", "32", "T", "N")
    for point in ((24, 78), (71, 69)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    fillets = [item for item in canvas.entities if isinstance(item, ArcEntity)]
    assert len(fillets) == 1 and fillets[0].radius_mm == pytest.approx(32)
    assert tangent_on_curves(fillets[0], circles[2]) and tangent_on_curves(fillets[0], circles[4])
    _submit(editor, "LINE", "TAN")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((6, -19)))
    _submit(editor, "TAN")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((100, 17)))
    lines = [item for item in canvas.entities if isinstance(item, LineEntity)]
    assert len(lines) == 1
    assert tangent_on_curves(lines[0], circles[0]) and tangent_on_curves(lines[0], circles[4])
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    _submit(editor, "CIRCLE", "TTR")
    for point in ((-23, 78), (-13, -15)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    _submit(editor, "70")
    ttr = [
        item for item in canvas.entities if isinstance(item, CircleEntity) and item.radius_mm == 70
    ]
    assert len(ttr) == 1
    assert tangent_on_curves(ttr[0], circles[0]) and tangent_on_curves(ttr[0], circles[2])
    _submit(editor, "TRIM", "C")
    for point in ((-27, 65), (-20, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    canvas.add_coordinate_point((ttr[0].center_mm[0] + 70, ttr[0].center_mm[1]), exact_point=True)
    arcs = [item for item in canvas.entities if isinstance(item, ArcEntity)]
    assert len(arcs) == 2
    outer = next(item for item in arcs if item.radius_mm == 70)
    assert tangent_on_curves(outer, circles[0]) and tangent_on_curves(outer, circles[2])
    assert len([item for item in canvas.entities if isinstance(item, CircleEntity)]) == 6


@pytest.mark.parametrize("from_curve", [False, True])
def test_tangent_line_connects_circle_and_regular_point(qtbot: QtBot, from_curve: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    if from_curve:
        _submit(editor, "LINE", "TAN", "0,5", "10,0")
    else:
        _submit(editor, "LINE", "10,0", "TAN", "2.5,4.33")
    assert len(editor.canvas.entities) == 2 and isinstance(editor.canvas.entities[-1], LineEntity)
    line = editor.canvas.entities[-1]
    assert tangent_on_curves(line, circle)
    assert (line.end_mm if from_curve else line.start_mm) == pytest.approx((10, 0))
    assert len([item for item in editor.canvas.constraints if item.kind == "tangent"]) == 1
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [circle]


def test_tangent_line_preview_matches_committed_geometry(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((circle,))
    _submit(editor, "LINE", "TAN", "0,5")
    pixel = canvas.local_to_screen((10, 0))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pixel),
            QPointF(canvas.mapToGlobal(pixel)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = canvas.previewed_tangent_line
    assert preview is not None and tangent_on_curves(preview, circle)
    canvas.add_coordinate_point(preview.end_mm, exact_point=True)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].start_mm == pytest.approx(preview.start_mm)
    assert canvas.entities[-1].end_mm == pytest.approx(preview.end_mm)


def test_tangent_to_regular_point_honors_endpoint_snapping(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    existing = LineEntity(uuid4().hex, (10, 0), (12, 0))
    assert canvas.replace_draft_entities((circle, existing))
    canvas.set_snapping_enabled(True)
    _submit(editor, "LINE", "TAN")
    canvas.add_coordinate_point((0, 5), exact_point=True)
    canvas.add_coordinate_point((10.1, 0.1))
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((10, 0))
    assert any(item.kind == "coincident" for item in canvas.constraints)


def test_recorded_exercise_commits_and_survives_save_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.core.sketch import ArcEntity
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    _build_recorded_exercise(editor)
    expected = {entity.entity_id: entity for entity in editor.canvas.entities}
    assert len(expected) == 9
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=20000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    path = tmp_path / "recorded-profile.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=20000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert actual == expected
    assert reopened.canvas.circle_fillet_radius == 32
    sketch = next(item for item in services.kernel.sketches if len(item.entities) == len(expected))
    dxf_path = tmp_path / "recorded-profile.dxf"
    report = write_sketch_dxf(sketch, dxf_path)
    imported = read_sketch_dxf(dxf_path)
    assert report.unit == "mm" and report.entity_count >= len(expected)
    imported_by_id = {entity.entity_id: entity for entity in imported.sketch.entities}
    assert set(imported_by_id) == set(expected)
    for identity, original in expected.items():
        result = imported_by_id[identity]
        if isinstance(original, LineEntity):
            assert isinstance(result, LineEntity)
            assert result.start_mm == pytest.approx(original.start_mm)
            assert result.end_mm == pytest.approx(original.end_mm)
        elif isinstance(original, CircleEntity | ArcEntity):
            assert isinstance(result, type(original))
            assert isinstance(result, CircleEntity | ArcEntity)
            assert result.center_mm == pytest.approx(original.center_mm)
            assert result.radius_mm == pytest.approx(original.radius_mm)
            if isinstance(original, ArcEntity) and isinstance(result, ArcEntity):
                assert result.start_angle_deg == pytest.approx(original.start_angle_deg % 360)
                assert result.sweep_angle_deg == pytest.approx(original.sweep_angle_deg)
    assert report.warnings
    assert all("尺寸/约束" in warning for warning in report.warnings)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert not reopened.canvas.background_entities
    assert reopened.canvas.circle_fillet_radius == 32
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert reopened.canvas.circle_fillet_radius == 0
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert reopened.canvas.circle_fillet_radius == 32
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert {
        entity.entity_id: entity for entity, _ in reopened.canvas.background_entities
    } == expected


def test_tangent_option_escape_returns_to_existing_line_anchor(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    _submit(editor, "LINE", "10,0", "TAN")
    assert editor.canvas.line_tangent_active
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    assert not editor.canvas.line_tangent_active
    assert editor.canvas.tool == "直线"
    assert editor.canvas.pending_last_point == pytest.approx((10, 0))
    assert "取消切点直线" in editor.drawing_command_bar.status.text()
    _submit(editor, "20,0")
    assert len(editor.canvas.entities) == 1
    assert isinstance(editor.canvas.entities[0], LineEntity)
    assert editor.canvas.entities[0].start_mm == pytest.approx((10, 0))


def test_line_tangent_uses_finite_arc_source_and_internal_solution(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = ArcEntity(uuid4().hex, (0, 0), 2, 0, 180)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    _submit(editor, "LINE", "TAN", "0.8,1.8", "TAN", "9.2,-1.8")
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], LineEntity)
    line = canvas.entities[-1]
    assert tangent_on_curves(line, first) and tangent_on_curves(line, second)
    assert line.start_mm[1] > 0 and line.end_mm[1] < 0


def test_drawing_workflow_layer_dimension_reopen_and_dxf(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.formats.providers.dxf_provider import read_sketch_dxf
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("profile"))
    editor.request_layer_update(layers, ".")
    layer_editor = editor
    qtbot.waitUntil(lambda: not unit.is_busy and layer_editor.layer_table == layers, timeout=10000)
    editor.layer_combo.setCurrentText("profile")
    _submit(editor, "LINE", "0,0", "20,0")
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert len(editor.canvas.entities) == 1
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity) and line.layer_name == "profile"
    editor.canvas.selected_entity_ids = {line.entity_id}
    _submit(editor, "SCALE", "0,0", "2")
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity) and line.end_mm == pytest.approx((40, 0))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((20, 0), (20, -10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimensions = [item for item in editor.canvas.constraints if item.axis == "horizontal"]
    assert len(dimensions) == 1 and not dimensions[0].driving
    dimension = dimensions[0]
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    _submit(editor, "CIRCLE", "0,25", "5")
    circle = next(entity for entity in editor.canvas.entities if isinstance(entity, CircleEntity))
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 25), (15, 35)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    editor.dimensions.apply_button.click()
    driving = next(item for item in editor.canvas.constraints if item.kind == "radius")
    assert driving.driving and driving.value == pytest.approx(7)
    changed_circle = next(
        entity for entity in editor.canvas.entities if entity.entity_id == circle.entity_id
    )
    assert isinstance(changed_circle, CircleEntity) and changed_circle.radius_mm == pytest.approx(7)
    assert editor.canvas.undo_last_operation()
    undone_circle = next(
        entity for entity in editor.canvas.entities if entity.entity_id == circle.entity_id
    )
    assert isinstance(undone_circle, CircleEntity) and undone_circle.radius_mm == pytest.approx(5)
    assert editor.canvas.redo_last_operation()
    assert changed_circle in editor.canvas.entities and driving in editor.canvas.constraints
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=20000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    path = tmp_path / "workflow.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=20000
    )
    sketch = next(sketch for sketch in services.kernel.sketches if line in sketch.entities)
    assert dimension in sketch.constraints and driving in sketch.constraints
    assert changed_circle in sketch.entities
    assert sketch.layers.get("profile").name == "profile"
    dxf = tmp_path / "workflow.dxf"
    preview_reports: list[str] = []

    def choose_dxf(*_args: object) -> tuple[str, str]:
        return str(dxf), ""

    def accept_preview(dialog: DxfOutputPreviewDialog) -> int:
        preview_reports.append(dialog.report_label.text())
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_dxf)
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(
        lambda: bool(preview_reports) and dxf.exists() and not unit.is_busy, timeout=20000
    )
    assert "单位 mm" in preview_reports[0] and "未导出" in preview_reports[0]
    imported = read_sketch_dxf(dxf)
    assert any(
        entity.entity_id == line.entity_id and entity.layer_name == "profile"
        for entity in imported.sketch.entities
    )
    assert any(
        item.constraint_id == dimension.constraint_id and not item.driving
        for item in imported.sketch.constraints
    )
    assert any(
        item.constraint_id == driving.constraint_id and item.driving
        for item in imported.sketch.constraints
    )


def test_arc_ttr_builds_recording_r32_with_six_concentric_circles(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    circles = tuple(
        CircleEntity(uuid4().hex, center, radius)
        for center, radius in (
            ((0, 0), 20),
            ((0, 0), 9),
            ((0, 65), 27),
            ((0, 65), 12),
            ((90, 45), 30),
            ((90, 45), 17),
        )
    )
    assert canvas.replace_draft_entities(circles)
    canvas.fit_view()
    _submit(editor, "ARC", "T")
    for point in ((24, 78), (71, 69)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    _submit(editor, "32")
    assert tuple(canvas.entities[:6]) == circles
    assert len(canvas.entities) == 7
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(32)
    assert tangent_on_curves(arc, circles[2]) and tangent_on_curves(arc, circles[4])
    assert (
        len([constraint for constraint in canvas.constraints if constraint.kind == "tangent"]) == 2
    )
    assert canvas.undo_last_operation() and tuple(canvas.entities) == circles
