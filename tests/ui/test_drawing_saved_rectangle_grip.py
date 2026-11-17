# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved rectangle corners can be edited with grips."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


def test_saved_rectangle_corner_drag_undo_redo_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert canvas.selected_entity_ids == {rectangle.entity_id}
    assert canvas.control_point_at((10, 5)) is not None
    before = services.kernel.sketches
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 8)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, 8)))
    qtbot.waitUntil(
        lambda: (
            services.kernel.sketches != before
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=15000,
    )
    moved = services.kernel.sketches[0].entities[0]
    assert isinstance(moved, RectangleEntity)
    assert moved.entity_id == rectangle.entity_id
    assert moved.first_corner_mm == pytest.approx((-10, -5), abs=0.15)
    assert moved.opposite_corner_mm == pytest.approx((12, 8), abs=0.15)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == before
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == moved
    file_path = tmp_path / "rectangle-grip.my2d"
    save_document(loaded.document, file_path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, file_path)
    assert reopened.kernel.sketches[0].entities[0] == moved


@pytest.mark.parametrize(
    ("index", "target", "first", "opposite"),
    [
        (0, (-12.0, -8.0), (-12.0, -8.0), (10.0, 5.0)),
        (1, (12.0, -8.0), (-10.0, -8.0), (12.0, 5.0)),
        (3, (-12.0, 8.0), (-12.0, -5.0), (10.0, 8.0)),
    ],
)
def test_other_rectangle_corners_keep_opposite_corner(
    index: int,
    target: tuple[float, float],
    first: tuple[float, float],
    opposite: tuple[float, float],
) -> None:
    services = app.build_app(discoverers=[])
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    result = services.kernel.preview_sketch_drag(
        sketch, SketchGeometryReference(rectangle.entity_id, "vertex", index), target
    )
    assert result.status == "success" and result.sketch is not None
    moved = result.sketch.entities[0]
    assert isinstance(moved, RectangleEntity)
    assert moved.first_corner_mm == pytest.approx(first)
    assert moved.opposite_corner_mm == pytest.approx(opposite)


def test_saved_rectangle_fixed_corner_cannot_be_dragged(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-10, -5), (10, 5))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(rectangle.entity_id, "vertex", 2),)
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (fixed,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    before = tuple(loaded.document.commands)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 8)))
    qtbot.waitUntil(lambda: "固定" in canvas.message, timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, 8)))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches[0].entities == (rectangle,)
    assert services.kernel.sketches[0].constraints == (fixed,)


def test_saved_rectangle_grip_keeps_cross_object_tangency(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, -10)))
    assert canvas.selected_entity_ids == {rectangle.entity_id}
    before = services.kernel.sketches
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 2)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    qtbot.waitUntil(
        lambda: (
            services.kernel.sketches != before
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=15000,
    )
    changed_rectangle = services.kernel.sketches[0].entities[0]
    changed_circle = services.kernel.sketches[1].entities[0]
    assert isinstance(changed_rectangle, RectangleEntity)
    assert isinstance(changed_circle, CircleEntity)
    assert changed_rectangle.first_corner_mm[1] == pytest.approx(2, abs=0.15)
    assert changed_circle.center_mm[1] == pytest.approx(changed_rectangle.first_corner_mm[1] + 2)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == before
