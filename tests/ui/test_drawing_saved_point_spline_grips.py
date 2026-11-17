# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved point and spline control grips use the document history."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import DraftTangentPair
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    CircleEntity,
    LineEntity,
    PointEntity,
    Sketch,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("kind", ["point", "spline"])
def test_saved_point_and_spline_grip_drag_replays(qtbot: QtBot, tmp_path: Path, kind: str) -> None:
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
    entity = (
        PointEntity(uuid4().hex, (0, 5))
        if kind == "point"
        else SplineEntity(uuid4().hex, ((-10, 0), (0, 0), (10, 0), (20, 0)))
    )
    start = (0.0, 5.0) if kind == "point" else (0.0, 0.0)
    target = (2.0, 8.0) if kind == "point" else (0.0, 3.0)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    selection = start if kind == "point" else (5.0, 0.0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(selection))
    assert canvas.selected_entity_ids == {entity.entity_id}
    assert canvas.control_point_at(start) is not None
    before = services.kernel.sketches
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(start))
    QTest.mouseMove(canvas, canvas.local_to_screen(target))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    qtbot.waitUntil(
        lambda: (
            services.kernel.sketches != before
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=15000,
    )
    moved = services.kernel.sketches[0].entities[0]
    assert moved.entity_id == entity.entity_id
    if kind == "point":
        assert isinstance(moved, PointEntity)
        assert moved.position_mm == pytest.approx(target, abs=0.15)
    else:
        assert isinstance(moved, SplineEntity)
        assert moved.control_points_mm[1] == pytest.approx(target, abs=0.15)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == before
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == moved
    file_path = tmp_path / f"{kind}-grip.my2d"
    save_document(loaded.document, file_path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, file_path)
    assert reopened.kernel.sketches[0].entities[0] == moved


@pytest.mark.parametrize("kind", ["point", "spline"])
def test_saved_point_and_spline_fixed_control_rejects_drag(qtbot: QtBot, kind: str) -> None:
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
    entity = (
        PointEntity(uuid4().hex, (0, 5))
        if kind == "point"
        else SplineEntity(uuid4().hex, ((-10, 0), (0, 0), (10, 0), (20, 0)))
    )
    start = (0.0, 5.0) if kind == "point" else (0.0, 0.0)
    target = (2.0, 8.0) if kind == "point" else (0.0, 3.0)
    reference = SketchGeometryReference(entity.entity_id, "vertex", 0 if kind == "point" else 1)
    fixed = SketchConstraint(uuid4().hex, "fixed", (reference,))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,), (fixed,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    selection = start if kind == "point" else (5.0, 0.0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(selection))
    assert canvas.selected_entity_ids == {entity.entity_id}
    before = tuple(loaded.document.commands)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(start))
    QTest.mouseMove(canvas, canvas.local_to_screen(target))
    qtbot.waitUntil(lambda: "固定" in canvas.message, timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches[0].entities == (entity,)
    assert services.kernel.sketches[0].constraints == (fixed,)


@pytest.mark.parametrize("kind", ["point", "spline"])
@pytest.mark.parametrize("same_record", [True, False])
def test_saved_point_and_spline_grips_preserve_pending_tangency(
    qtbot: QtBot, tmp_path: Path, kind: str, same_record: bool
) -> None:
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
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    entity = (
        PointEntity(uuid4().hex, (30, 5))
        if kind == "point"
        else SplineEntity(uuid4().hex, ((20, 0), (30, 0), (40, 0), (50, 0)))
    )
    start = (30.0, 5.0) if kind == "point" else (30.0, 0.0)
    target = (32.0, 8.0) if kind == "point" else (30.0, 3.0)
    groups = ((line, entity),) if same_record else ((line,), (entity,))
    for entities in groups:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert canvas.replace_draft_entities((circle,))
    pairs: list[DraftTangentPair] = [(line.entity_id, circle.entity_id)]
    canvas.pending_cross_tangencies = pairs.copy()
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    selection = start if kind == "point" else (35.0, 0.0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(selection))
    assert canvas.selected_entity_ids == {entity.entity_id}
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(start))
    QTest.mouseMove(canvas, canvas.local_to_screen(target))
    qtbot.waitUntil(
        lambda: bool(canvas.saved_handle_preview) or "不支持" in canvas.message, timeout=15000
    )
    assert canvas.saved_handle_preview, canvas.message
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=15000)
    moved = next(
        item for item, _layer in canvas.background_entities if item.entity_id == entity.entity_id
    )
    if kind == "point":
        assert isinstance(moved, PointEntity) and moved.position_mm == pytest.approx(
            target, abs=0.15
        )
    else:
        assert isinstance(moved, SplineEntity)
        assert moved.control_points_mm[1] == pytest.approx(target, abs=0.15)
    assert canvas.pending_cross_tangencies == pairs
    assert canvas.undo_last_operation() and canvas.mixed_move is None
    assert canvas.redo_last_operation() and canvas.mixed_move is not None
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert any(moved in sketch.entities for sketch in services.kernel.sketches)
    file_path = tmp_path / f"{kind}-pending-grip.my2d"
    save_document(loaded.document, file_path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, file_path)
    assert len(reopened.kernel.cross_sketch_tangencies) == 1
    assert any(moved in sketch.entities for sketch in reopened.kernel.sketches)
