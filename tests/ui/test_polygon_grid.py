# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Regular polygons and grid display stay independent of document geometry."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import PolylineEntity
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("内接圆", ((20.0, 10.0), (10.0, 20.0), (0.0, 10.0), (10.0, 0.0))),
        ("外切圆", ((20.0, 20.0), (0.0, 20.0), (0.0, 0.0), (20.0, 0.0))),
    ],
)
def test_regular_polygon_radius_modes_and_undo(
    qtbot: QtBot, mode: str, expected: tuple[tuple[float, float], ...]
) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    assert "多边形" in editor.tool_buttons
    editor.polygon_sides_field.setValue(4)
    editor.polygon_mode_combo.setCurrentText(mode)
    editor.tool_buttons["多边形"].click()
    canvas = editor.canvas
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    assert not canvas.entities
    canvas.add_coordinate_point((20.0, 10.0), exact_point=True)
    assert len(canvas.entities) == 1
    polygon = canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert polygon.closed
    assert len(polygon.points_mm) == 4
    for actual, wanted in zip(polygon.points_mm, expected, strict=True):
        assert actual == pytest.approx(wanted)
    assert canvas.undo_last_operation()
    assert not canvas.entities
    assert canvas.redo_last_operation()
    assert canvas.entities == [polygon]


def test_polygon_cancels_degenerate_radius_and_respects_layer(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    assert "多边形" in editor.tool_buttons
    editor.tool_buttons["多边形"].click()
    editor.polygon_sides_field.setValue(6)
    canvas = editor.canvas
    canvas.set_layer_table(SketchLayerTable().add(SketchLayer("outline")), "outline")
    canvas.set_construction(True)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert not canvas.entities
    assert canvas.has_pending_geometry
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.has_pending_geometry
    canvas.set_tool("多边形")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    polygon = canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert len(polygon.points_mm) == 6
    assert polygon.layer_name == "outline"
    assert polygon.construction
    assert not canvas.grab().isNull()


def test_grid_renders_dots_instead_of_continuous_lines(qtbot: QtBot) -> None:
    canvas = SketchCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    step = canvas.grid_spacing_mm()
    on_dot = canvas.local_to_screen((step, step))
    between_dots = canvas.local_to_screen((step, step * 1.5))
    image = canvas.grab().toImage()
    assert image.pixelColor(on_dot) != Qt.GlobalColor.white
    assert image.pixelColor(between_dots) == Qt.GlobalColor.white


@pytest.mark.parametrize("floating", [False, True])
def test_grid_toggle_f7_preserves_snap_and_continuation(qtbot: QtBot, floating: bool) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    assert editor.grid_visible_check.isChecked()
    editor.grid_snap_check.setChecked(True)
    editor.snap_check.setChecked(False)
    # Open the Modify page before focusing its angle field, including when floating.
    editor.parameter_tabs.setCurrentIndex(2)
    editor.parameter_dock.setFloating(floating)
    editor.parameter_dock.window().activateWindow()
    editor.angle_field.setFocus()
    qtbot.waitUntil(editor.angle_field.hasFocus)
    QTest.keyClick(editor.angle_field, Qt.Key.Key_F7)
    assert not editor.grid_visible_check.isChecked()
    canvas = editor.canvas
    step = canvas.grid_spacing_mm()
    assert canvas.grab().toImage().pixelColor(canvas.local_to_screen((step, step))) == (
        Qt.GlobalColor.white
    )
    canvas.add_coordinate_point((step + 0.1, step + 0.1))
    canvas.add_coordinate_point((step * 3 + 0.1, step + 0.1))
    line = canvas.entities[0]
    from mycad.core.sketch import LineEntity

    assert isinstance(line, LineEntity)
    assert line.start_mm == (step, step)
    assert line.end_mm == (step * 3, step)
    continued = SketchEditorDialog()
    qtbot.addWidget(continued)
    continued.continue_workspace_from(editor)
    assert not continued.grid_visible_check.isChecked()
    assert continued.grid_snap_check.isChecked()
    QTest.keyClick(editor.angle_field, Qt.Key.Key_F7)
    assert editor.grid_visible_check.isChecked()


def test_polygon_saved_replayed_and_exported_as_closed_polyline(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad.app import build_app, new_document, open_app_document
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.tool_buttons["多边形"].click()
    editor.canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    editor.canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    editor.finish_button.click()
    sketch = editor.result_sketch
    assert sketch is not None
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    loaded.bus.undo()
    loaded.bus.redo()
    path = tmp_path / "polygon.mc.json"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert services.kernel.sketches == (sketch,)
    dxf = tmp_path / "polygon.dxf"
    write_sketch_dxf(sketch, dxf)
    restored = read_sketch_dxf(dxf).sketch.entities[0]
    assert isinstance(restored, PolylineEntity)
    assert restored.closed
    original = sketch.entities[0]
    assert isinstance(original, PolylineEntity)
    for actual, expected in zip(restored.points_mm, original.points_mm, strict=True):
        assert actual == pytest.approx(expected)


def test_f7_from_floating_drawing_toolbar(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    toolbar = editor.drawing_toolbar
    toolbar.setWindowFlags(Qt.WindowType.Tool)
    toolbar.show()
    toolbar.activateWindow()
    button = editor.tool_buttons["多边形"]
    button.setFocus()
    qtbot.waitUntil(button.hasFocus)
    assert toolbar.isFloating()
    QTest.keyClick(button, Qt.Key.Key_F7)
    assert not editor.grid_visible_check.isChecked()
    toolbar.close()
