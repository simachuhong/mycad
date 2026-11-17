# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Directional annotations use their owning sketch's axes on screen."""

import math
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchCanvas


def test_explicit_projection_axis_controls_dimension_layout(qtbot: QtBot) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        16 * q,
        "mm",
        driving=False,
        axis="horizontal",
        projection_axis=(q, q),
        position_mm=(5, 12),
    )
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),), WorkPlaneFrame.xy()
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    start, end = layout.lines[2]
    dx, dy = end.x() - start.x(), end.y() - start.y()
    assert (dx * q - dy * q) / math.hypot(dx, dy) == pytest.approx(1, abs=0.01)


def test_edit_explicit_axis_dimension_replays(qtbot: QtBot) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        16 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
        position_mm=(5, 12),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    shown = next(
        c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id
    )
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None and canvas.set_tool("选择元素")
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    editor.dimensions.value_editor.setValue(12)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    count = len(loaded.document.commands)
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "sketch.constraint.update"
    assert loaded.document.commands[-1].version == 4
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, LineEntity)
    assert (
        (changed.end_mm[0] - changed.start_mm[0]) + (changed.end_mm[1] - changed.start_mm[1])
    ) * q == pytest.approx(12)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_move_source_with_explicit_axis_dimension_uses_new_revision(qtbot: QtBot) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        16 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
        position_mm=(5, 12),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}
    count = len(loaded.document.commands)
    for value in ("MOVE", "0,0", "2,3"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "sketch.revise"
    assert loaded.document.commands[-1].version == 5
    moved = services.kernel.sketches[0].entities[0]
    assert isinstance(moved, LineEntity) and moved.start_mm == pytest.approx((2, 3))
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("axis", ["horizontal", "vertical", "ordinate_x", "ordinate_y"])
def test_directional_dimension_draws_in_source_axes(
    qtbot: QtBot, opposite: bool, axis: str
) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (0, 0, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10 if axis.endswith("x") or axis == "horizontal" else 6,
        "mm",
        driving=False,
        axis=axis,
        position_mm=(5, 12),
    )
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, frame, (line,), (dimension,)),), WorkPlaneFrame.xy()
    )
    shown = next(
        (c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id), None
    )
    assert shown is not None
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None
    if axis.startswith("ordinate"):
        start, end = layout.lines[0]
        expected = frame.v_axis if axis == "ordinate_x" else frame.u_axis
    else:
        start, end = layout.lines[2]
        expected = frame.u_axis if axis == "horizontal" else frame.v_axis
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = math.hypot(dx, dy)
    assert length > 1
    assert abs((dx * expected[0] - dy * expected[1]) / length) == pytest.approx(1, abs=0.01)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("placed", [False, True])
def test_angle_dimension_sweep_tracks_reflected_frame(
    qtbot: QtBot, opposite: bool, placed: bool
) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (0, 0, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        position_mm=(6, 6) if placed else None,
    )
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, frame, (first, second), (dimension,)),), WorkPlaneFrame.xy()
    )
    shown = next(
        c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id
    )
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None
    start, end = layout.lines[-1]
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = math.hypot(dx, dy)
    assert (dx * frame.v_axis[0] - dy * frame.v_axis[1]) / length == pytest.approx(1, abs=0.01)


@pytest.mark.parametrize("opposite", [False, True])
def test_edit_directional_dimension_uses_source_axis(qtbot: QtBot, opposite: bool) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (0, 0, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    line = LineEntity(uuid4().hex, (0, 0), (10, 6))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=True,
        axis="horizontal",
        position_mm=(5, 12),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (line,), (dimension,)), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    shown = next(
        c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id
    )
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None and canvas.set_tool("选择元素")
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    editor.dimensions.value_editor.setValue(12)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = canvas.dimension_preview
    assert preview is not None
    shown_line = preview.entities[0]
    assert isinstance(shown_line, LineEntity)
    solved = editor.dimensions.accepted_preview(original, candidate)
    assert solved is not None and solved.sketch is not None
    local_line = solved.sketch.entities[0]
    assert isinstance(local_line, LineEntity)
    assert shown_line.start_mm == pytest.approx(frame.local_to_world(local_line.start_mm)[:2])
    assert shown_line.end_mm == pytest.approx(frame.local_to_world(local_line.end_mm)[:2])
    count = len(loaded.document.commands)
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, LineEntity)
    assert abs(changed.end_mm[0] - changed.start_mm[0]) == pytest.approx(12)
    assert services.kernel.sketches[0].constraints[0].axis == "horizontal"
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (line,)
