# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimensions on differently oriented coplanar sketches remain selectable."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import project_coplanar_entity
from mycad.core.persistence import save_document
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("mode", ["radius", "diameter", "arc_length", "aligned"])
def test_create_invariant_dimension_across_frames(
    qtbot: QtBot, tmp_path: Path, opposite: bool, mode: str
) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    if mode == "aligned":
        view_entity = LineEntity(uuid4().hex, (0, 0), (20, 0))
        hit, expected = (10, 0), 20.0
    elif mode == "arc_length":
        view_entity = ArcEntity(uuid4().hex, (0, 0), 4, 0, 90)
        hit, expected = (2 * math.sqrt(2), 2 * math.sqrt(2)), 2 * math.pi
    else:
        view_entity = CircleEntity(uuid4().hex, (0, 0), 4)
        hit, expected = (4, 0), 8.0 if mode == "diameter" else 4.0
    entity = project_coplanar_entity(view_entity, WorkPlaneFrame.xy(), frame)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (entity,)), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons[mode].click()
    canvas = editor.canvas
    count = len(loaded.document.commands)
    for point in (hit, (10, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    dimension = services.kernel.sketches[0].constraints[0]
    assert dimension.value == pytest.approx(expected)
    assert dimension.position_mm is not None
    assert frame.local_to_world(dimension.position_mm)[:2] == pytest.approx((10, 10), abs=0.2)
    assert dimension.axis == "aligned"
    path = tmp_path / "created-dimension.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == ()
    loaded.bus.redo()
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("mode", ["radius", "aligned"])
def test_create_driving_dimension_across_frames(qtbot: QtBot, opposite: bool, mode: str) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    view = (
        CircleEntity(uuid4().hex, (0, 0), 4)
        if mode == "radius"
        else LineEntity(uuid4().hex, (0, 0), (20, 0))
    )
    entity = project_coplanar_entity(view, WorkPlaneFrame.xy(), frame)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (entity,)), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons[mode].click()
    for point in ((4, 0) if mode == "radius" else (10, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    value = 5 if mode == "radius" else 15
    editor.dimensions.value_editor.setValue(value)
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
    sketch = services.kernel.sketches[0]
    assert sketch.constraints[0].driving and sketch.constraints[0].value == pytest.approx(value)
    changed = sketch.entities[0]
    if isinstance(changed, CircleEntity):
        assert changed.radius_mm == pytest.approx(value)
    else:
        assert isinstance(changed, LineEntity)
        assert math.dist(changed.start_mm, changed.end_mm) == pytest.approx(value)
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (entity,)
    assert not services.kernel.sketches[0].constraints


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("driving", [False, True])
def test_select_delete_radius_dimension_across_frames(
    qtbot: QtBot, tmp_path: Path, opposite: bool, driving: bool
) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    circle = CircleEntity(uuid4().hex, frame.world_to_local((0, 0, 0)), 4)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        4,
        "mm",
        driving=driving,
        position_mm=frame.world_to_local((8, 8, 0)),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (circle,), (dimension,)), session_identity=0
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
        (c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id), None
    )
    assert shown is not None
    assert shown.position_mm == pytest.approx((8, 8))
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None and canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    count = len(loaded.document.commands)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert services.kernel.sketches[0].constraints == ()
    assert services.kernel.sketches[0].entities == (circle,)
    path = tmp_path / "dimension.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == (dimension,)
    loaded.bus.redo()
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].constraints == ()


@pytest.mark.parametrize("opposite", [False, True])
def test_drag_radius_label_across_frames(qtbot: QtBot, opposite: bool) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    circle = CircleEntity(uuid4().hex, frame.world_to_local((0, 0, 0)), 4)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        4,
        "mm",
        driving=False,
        position_mm=frame.world_to_local((8, 8, 0)),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (circle,), (dimension,)), session_identity=0
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
    start = layout.label.toPoint()
    end = canvas.local_to_screen((12, 12))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    changed = services.kernel.sketches[0].constraints[0]
    assert changed.text_position_mm is not None, editor.status_label.text()
    assert frame.local_to_world(changed.text_position_mm)[:2] == pytest.approx((12, 12), abs=0.2)
    assert services.kernel.sketches[0].entities == (circle,)
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("opposite", [False, True])
def test_edit_driving_radius_across_frames(qtbot: QtBot, opposite: bool) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    circle = CircleEntity(uuid4().hex, frame.world_to_local((0, 0, 0)), 4)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        4,
        "mm",
        driving=True,
        position_mm=frame.world_to_local((8, 8, 0)),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (circle,), (dimension,)), session_identity=0
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
    editor.dimensions.value_editor.setValue(5)
    candidate = editor.dimensions.candidate
    original = editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, CircleEntity) and changed.radius_mm == pytest.approx(5)
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (circle,)
    assert services.kernel.sketches[0].constraints == (dimension,)
