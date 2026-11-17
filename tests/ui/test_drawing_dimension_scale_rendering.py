# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension scale changes the on-canvas annotation, not its measured value."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.sketch_editor import SketchCanvas


def test_placed_dimension_scale_changes_rendering(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(700, 500)
    canvas.set_grid_visible(False)
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=1,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.show()
    qtbot.waitExposed(canvas)
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    normal = canvas.grab().toImage()
    canvas.constraints = [replace(dimension, scale=2)]
    canvas.update()
    enlarged = canvas.grab().toImage()
    assert enlarged != normal
    assert canvas.constraints[0].value == 60


def test_scaled_dimension_label_can_be_selected_at_visible_edge(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=4,
        text_override="宽度 <> mm",
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    bounds = canvas.dimension_label_rect(dimension, layout.label)
    point = bounds.center()
    point.setX(bounds.right() - 8)
    assert abs(point.x() - layout.label.x()) > 30
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}


def test_stacked_scaled_dimension_label_can_be_selected(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    first = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=5,
    )
    second = replace(first, constraint_id=uuid4().hex)
    canvas.entities = [line]
    canvas.constraints = [first, second]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(second, canvas.dimension_entities())
    assert layout is not None
    center = canvas.dimension_label_rect(second, layout.label).center() + QPointF(0, 90)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center.toPoint())
    assert canvas.selected_constraint_ids == {second.constraint_id}


def test_scaled_arrow_wing_can_be_clicked(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-90, 0), (90, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        180,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=10,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    tip, toward = layout.arrows[0]
    direction = (toward - tip) / (toward - tip).manhattanLength()
    side = QPointF(-direction.y(), direction.x())
    wing = tip + direction * 35 + side * 15
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=wing.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}


def test_scaled_arrow_wing_can_be_crossing_selected(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-90, 0), (90, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        180,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=10,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    tip, toward = layout.arrows[0]
    direction = (toward - tip) / (toward - tip).manhattanLength()
    wing = (tip + direction * 35 + QPointF(-direction.y(), direction.x()) * 15).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=wing + QPoint(12, 12))
    QTest.mouseMove(canvas, wing - QPoint(12, 12))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=wing - QPoint(12, 12))
    assert canvas.selected_constraint_ids == {dimension.constraint_id}


def test_stacked_scaled_dimensions_select_the_visible_label(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    first = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=5,
    )
    second = replace(first, constraint_id=uuid4().hex)
    canvas.entities = [line]
    canvas.constraints = [first, second]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    layout = canvas.dimension_layout(first, canvas.dimension_entities())
    assert layout is not None
    point = canvas.dimension_label_rect(first, layout.label).center().toPoint()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert canvas.selected_constraint_ids == {first.constraint_id}


def test_stacked_dimensions_with_different_scales_do_not_overlap(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(1000, 700)
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    large = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=10,
    )
    small = replace(large, constraint_id=uuid4().hex, scale=1)
    canvas.entities = [line]
    canvas.constraints = [large, small]
    bounds = canvas.dimension_label_rectangles()
    assert not bounds[large.constraint_id].intersects(bounds[small.constraint_id])


def test_parallel_angle_label_without_layout_can_be_selected(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    second = LineEntity(uuid4().hex, (-30, 10), (30, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        0,
        "deg",
        driving=False,
        scale=5,
    )
    canvas.entities = [first, second]
    canvas.constraints = [dimension]
    canvas.set_tool("选择元素")
    canvas.changed.emit()
    assert canvas.dimension_layout(dimension, canvas.dimension_entities()) is None
    bounds = canvas.dimension_label_rectangles()[dimension.constraint_id]
    assert bounds.height() == 90
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=bounds.center().toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}


def test_dimension_text_and_arrows_follow_view_zoom(qtbot: QtBot) -> None:
    import math

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(1000, 700)
    line = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        60,
        "mm",
        driving=False,
        position_mm=(0, 20),
        scale=2,
    )
    canvas.entities = [line]
    canvas.constraints = [dimension]
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    before_label = canvas.dimension_label_rectangles()[dimension.constraint_id]
    before_arrow = canvas.dimension_arrow_segments(layout, dimension.scale)[0]
    before_length = math.hypot(
        (before_arrow[1] - before_arrow[0]).x(), (before_arrow[1] - before_arrow[0]).y()
    )
    canvas.zoom_view_factor(2)
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    after_label = canvas.dimension_label_rectangles()[dimension.constraint_id]
    after_arrow = canvas.dimension_arrow_segments(layout, dimension.scale)[0]
    after_length = math.hypot(
        (after_arrow[1] - after_arrow[0]).x(), (after_arrow[1] - after_arrow[0]).y()
    )
    assert after_label.height() == before_label.height() * 2
    assert (
        abs(after_arrow[1].y() - after_arrow[0].y())
        == abs(before_arrow[1].y() - before_arrow[0].y()) * 2
    )
    assert abs(after_length - before_length * 2) < 1e-8


def test_saved_driving_dimension_scale_preserves_geometry_and_replays(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    line = LineEntity(uuid4().hex, (1, 2), (4, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        position_mm=(5, 10),
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
    before = editor.canvas.dimension_label_rectangles()[dimension.constraint_id].height()
    editor.dimensions.edit(sketch, dimension)
    editor.dimensions.scale.setValue(2)
    qtbot.waitUntil(lambda: editor.dimensions.apply_button.isEnabled(), timeout=10000)
    editor.dimensions.apply_edit()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    changed = services.kernel.sketches[0]
    assert changed.entities == (line,)
    assert changed.constraints[0].value == 5
    assert changed.constraints[0].scale == 2
    after = editor.canvas.dimension_label_rectangles()[dimension.constraint_id].height()
    assert after == before * 2
    target = tmp_path / "driving-scale.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.sketches == (changed,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (changed,)
