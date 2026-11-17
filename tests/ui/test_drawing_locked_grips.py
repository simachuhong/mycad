# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Selection grips follow the drawing layer's lock state."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import (
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("locked", [False, True])
def test_selected_line_grips_are_hidden_on_locked_layer(
    qtbot: QtBot, saved: bool, locked: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    layers = SketchLayerTable().add(SketchLayer("对象", locked=locked))
    canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (5, 5), (15, 5), layer_name="对象")
    if saved:
        canvas.set_background_sketches(
            (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers),),
            WorkPlaneFrame.xy(),
        )
    else:
        canvas.entities = [line]
    canvas.selected_entity_ids = {line.entity_id}
    point = canvas.local_to_screen(line.start_mm)
    image = canvas.grab().toImage()
    ratio = image.devicePixelRatio()
    pixel = image.pixelColor(round((point.x() + 2) * ratio), round((point.y() + 2) * ratio))
    assert (pixel == QColor(225, 250, 250)) is not locked


@pytest.mark.parametrize("bulge", [0.0, 0.5])
@pytest.mark.parametrize("locked", [False, True])
def test_saved_polyline_grips_follow_lock_state(qtbot: QtBot, locked: bool, bulge: float) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    layers = SketchLayerTable().add(SketchLayer("对象", locked=locked))
    canvas.set_layer_table(layers, "0")
    path = PolylineEntity(uuid4().hex, ((5, 5), (15, 5)), bulges=(bulge,), layer_name="对象")
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path,), layers=layers),), WorkPlaneFrame.xy()
    )
    canvas.selected_entity_ids = {path.entity_id}
    point = canvas.local_to_screen(path.points_mm[0])
    image = canvas.grab().toImage()
    ratio = image.devicePixelRatio()
    pixel = image.pixelColor(round((point.x() + 2) * ratio), round((point.y() + 2) * ratio))
    assert (pixel == QColor(225, 250, 250)) is not locked


@pytest.mark.parametrize("locked", [False, True])
def test_saved_rectangle_grips_follow_lock_state(qtbot: QtBot, locked: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    layers = SketchLayerTable().add(SketchLayer("对象", locked=locked))
    canvas.set_layer_table(layers, "0")
    rectangle = RectangleEntity(uuid4().hex, (5, 5), (15, 15), layer_name="对象")
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), layers=layers),),
        WorkPlaneFrame.xy(),
    )
    canvas.selected_entity_ids = {rectangle.entity_id}
    point = canvas.local_to_screen(rectangle.first_corner_mm)
    image = canvas.grab().toImage()
    ratio = image.devicePixelRatio()
    pixel = image.pixelColor(round((point.x() + 2) * ratio), round((point.y() + 2) * ratio))
    assert (pixel == QColor(225, 250, 250)) is not locked


@pytest.mark.parametrize("kind", ["point", "spline"])
@pytest.mark.parametrize("locked", [False, True])
def test_saved_point_and_spline_grips_follow_lock_state(
    qtbot: QtBot, locked: bool, kind: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_grid_visible(False)
    layers = SketchLayerTable().add(SketchLayer("对象", locked=locked))
    canvas.set_layer_table(layers, "0")
    entity = (
        PointEntity(uuid4().hex, (5, 5), layer_name="对象")
        if kind == "point"
        else SplineEntity(uuid4().hex, ((5, 5), (15, 5), (25, 5), (35, 5)), layer_name="对象")
    )
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,), layers=layers),), WorkPlaneFrame.xy()
    )
    canvas.selected_entity_ids = {entity.entity_id}
    point = canvas.local_to_screen((5, 5))
    image = canvas.grab().toImage()
    ratio = image.devicePixelRatio()
    pixel = image.pixelColor(round((point.x() + 2) * ratio), round((point.y() + 2) * ratio))
    assert (pixel == QColor(225, 250, 250)) is not locked


@pytest.mark.parametrize("saved", [False, True])
def test_clicking_locked_endpoint_selects_object_without_starting_drag(
    qtbot: QtBot, saved: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    layers = SketchLayerTable().add(SketchLayer("对象", locked=True))
    canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (5, 5), (15, 5), layer_name="对象")
    if saved:
        canvas.set_background_sketches(
            (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers),),
            WorkPlaneFrame.xy(),
        )
    else:
        canvas.entities = [line]
    canvas.set_tool("选择元素")
    if saved:
        canvas.selected_entity_ids = {line.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(line.start_mm))
    assert canvas.selected_entity_ids == {line.entity_id}
    assert "锁定" not in canvas.message
