# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension labels substitute current measured values without changing them."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow
from mycad.ui.part_sketch_dimensions import draft_dimensions
from mycad.ui.sketch_editor import SketchEditorDialog


def test_draft_label_override_uses_current_numeric_value() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    assert draft_dimensions(sketch)[0].text == "宽 25.00 mm [驱动]"
    updated = replace(sketch, constraints=(replace(dimension, value=30),))
    assert draft_dimensions(updated)[0].text == "宽 30.00 mm [驱动]"


def test_edit_reference_dimension_text_without_changing_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    editor.canvas.entities = [line]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    for text in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(text)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    dimension = editor.canvas.constraints[0]
    original = next(s for s in editor.dimension_sources() if s.constraints)
    editor.dimensions.edit(original, dimension)
    editor.dimensions.text_override.setText("宽 <> mm")
    editor.dimensions.apply_edit()
    assert editor.canvas.constraints[0].text_override == "宽 <> mm"
    assert editor.canvas.constraints[0].value == dimension.value
    assert editor.canvas.entities == [line]


def test_saved_dimension_text_edit_replays_and_undoes(qtbot: QtBot, tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.edit(sketch, dimension)
    editor.dimensions.text_override.setText("宽 <> mm")
    editor.dimensions.apply_edit()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    updated = services.kernel.sketches[0]
    assert updated.constraints[0].text_override == "宽 <> mm"
    assert updated.entities == (line,) and updated.constraints[0].value == 25
    target = tmp_path / "saved-text.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.sketches == (updated,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (updated,)


def test_dimlinear_text_is_set_in_options_not_cli(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (25, 0))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    for text in ("DIMLINEAR", "0,0", "25,0", "T"):
        bar.setText(text)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "x,y" in editor.drawing_command_bar.status.text()
    editor.dimensions.text_override.setText("HELP")
    bar.setText("10,10")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].text_override == "HELP"


def test_dimension_text_option_keeps_supplementary_unicode(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (25, 0))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    value = "🙂" * 200
    bar = editor.drawing_command_bar.input
    for text in ("DIMLINEAR", "0,0", "25,0"):
        bar.setText(text)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.dimensions.text_override.setText(value)
    bar.setText("10,10")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.constraints[0].text_override == value


def test_saved_entity_move_preserves_dimension_text(qtbot: QtBot, tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    moved = replace(line, start_mm=(5, 3), end_mm=(30, 3))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for text in ("MOVE", "0,0", "5,3"):
        bar.setText(text)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    result = services.kernel.sketches
    assert result[0].entities == (moved,)
    assert result[0].constraints[0].text_override == "宽 <> mm"
    target = tmp_path / "move-text.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == result


def test_part_sketch_edit_preserves_dimension_text(qtbot: QtBot) -> None:
    from mycad.ui.part_sketch_workbench import PartSketchWorkbench
    from mycad.ui.viewport import GLViewport

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="part")
    app.commit_new_sketch(services, loaded, sketch, session_identity=4)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    moved = replace(line, start_mm=(3, 4), end_mm=(28, 4))
    task.session.replace_sketch(replace(sketch, entities=(moved,)))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].entities == (moved,)
    assert services.kernel.sketches[0].constraints[0].text_override == "宽 <> mm"
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_manual_dimension_format_change_detaches_style(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        style_name="标准",
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.canvas.changed.emit()
    sketch = next(s for s in editor.dimension_sources() if s.constraints)
    editor.dimensions.edit(sketch, dimension)
    assert editor.dimensions.candidate is not None
    assert editor.dimensions.candidate.style_name == "标准"
    editor.dimensions.precision.setValue(3)
    assert editor.dimensions.candidate is not None
    assert editor.dimensions.candidate.style_name is None
    editor.dimensions.apply_edit()
    assert editor.canvas.constraints[0].precision == 3
    assert editor.canvas.constraints[0].style_name is None


def test_dimlinear_mouse_points_then_text_option(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    editor.activateWindow()
    qtbot.wait(50)
    canvas = editor.canvas
    canvas.entities = [LineEntity(uuid4().hex, (0, 0), (50, 0))]
    canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMLINEAR")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    for point in ((0, 0), (50, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(editor.dimensions.references) == 2
    assert "标注选项" in editor.drawing_command_bar.status.text()
    editor.dimensions.text_override.setText("宽 <> mm")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 20)))
    assert canvas.constraints[0].text_override == "宽 <> mm"


def test_dimlinear_shows_endpoint_snap_while_picking_second_point(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    canvas.entities = [LineEntity(uuid4().hex, (0, 0), (50, 0))]
    canvas.changed.emit()
    editor.dimensions.buttons["horizontal"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    assert len(editor.dimensions.references) == 1
    changes = QSignalSpy(canvas.cursor_changed)
    QTest.mouseMove(canvas, canvas.local_to_screen((50, 0)))
    assert changes.count() > 0
    assert "端点" in changes.at(changes.count() - 1)[2]
    point = canvas.local_to_screen((50, 0))
    image = canvas.grab().toImage()
    assert any(
        (color := image.pixelColor(point.x() + dx, point.y() + dy)).red() > 180
        and color.green() < 100
        and color.blue() < 100
        for dx in range(-7, 8)
        for dy in range(-7, 8)
    )
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert changes.at(changes.count() - 1)[2] == ""


def test_option_text_and_scale_survive_drawing_save_and_dxf(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    assert canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar.input
    bar.setText("DIMLINEAR")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.scale.setValue(2)
    for point in ((0, 0), (25, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    editor.dimensions.text_override.setText("宽 <> mm")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    draft = canvas.constraints[0]
    assert (draft.value, draft.scale, draft.text_override) == (25, 2, "宽 <> mm")
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    loaded = window.loaded_document()
    assert loaded is not None
    target = tmp_path / "dimension-options.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, target)
    sketch = reopened_services.kernel.sketches[0]
    dimension = sketch.constraints[0]
    assert (dimension.value, dimension.scale, dimension.text_override) == (25, 2, "宽 <> mm")
    assert draft_dimensions(sketch)[0].text == "宽 25.00 mm [参考]"
    dxf = tmp_path / "dimension-options.dxf"
    write_sketch_dxf(sketch, dxf)
    imported = read_sketch_dxf(dxf).sketch.constraints[0]
    assert (imported.value, imported.scale, imported.text_override) == (25, 2, "宽 <> mm")
