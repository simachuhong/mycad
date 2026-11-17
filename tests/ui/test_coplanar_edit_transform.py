# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Committed sketch transforms use the active plane's world-space gesture."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import validate_tangency_component
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("rotate", [False, True])
def test_select_and_transform_coplanar_source(qtbot: QtBot, opposite: bool, rotate: bool) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    line = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((20, 0, 0))
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, (line,)), session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert canvas.selected_entity_ids == {line.entity_id}
    before = len(loaded.document.commands)
    for value in ("ROTATE", "0,0", "90") if rotate else ("MOVE", "0,0", "4,2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == before + 1, editor.status_label.text()
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, LineEntity)
    points = ((0, 0, 0), (0, 20, 0)) if rotate else ((4, 2, 0), (24, 2, 0))
    assert frame.local_to_world(result.start_mm) == pytest.approx(points[0])
    assert frame.local_to_world(result.end_mm) == pytest.approx(points[1])
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (line,)


@pytest.mark.parametrize("opposite", [False, True])
def test_trim_coplanar_source_via_canvas(qtbot: QtBot, tmp_path: Path, opposite: bool) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    target = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((20, 0, 0))
    )
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (
        Sketch(uuid4().hex, frame, (target,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (boundary,)),
    ):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    count = len(loaded.document.commands)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) > count, timeout=10000
    )
    edited = services.kernel.sketches[0].entities[0]
    assert isinstance(edited, LineEntity)
    assert frame.local_to_world(edited.start_mm) == pytest.approx((0, 0, 0))
    assert frame.local_to_world(edited.end_mm) == pytest.approx((10, 0, 0))
    path = tmp_path / "coplanar-trim.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (target,)
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == (edited,)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (edited,)


@pytest.mark.parametrize("opposite", [False, True])
def test_fillet_coplanar_saved_lines_via_canvas(
    qtbot: QtBot, tmp_path: Path, opposite: bool
) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    first = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((10, 0, 0))
    )
    second = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((0, 10, 0))
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (first, second)), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    mixed = canvas.mixed_move
    assert mixed is not None
    a, b = mixed.current_saved[0].entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    assert frame.local_to_world(a.start_mm) == pytest.approx((2, 0, 0))
    assert frame.local_to_world(b.start_mm) == pytest.approx((0, 2, 0))
    assert len(canvas.pending_cross_tangencies) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    result = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 2
    validate_tangency_component(result, relations, result[0].sketch_id)
    path = tmp_path / "coplanar-fillet.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == relations


def test_coplanar_dimension_pick_uses_view_axis(qtbot: QtBot) -> None:
    frame = WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((20, 0, 0))
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, (line,)), session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.dimensions.buttons["horizontal"].click()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    candidate = editor.dimensions.candidate
    assert candidate is not None and candidate.projection_axis == pytest.approx((0, -1))
    assert candidate.value == pytest.approx(20)
    assert not services.kernel.sketches[0].constraints


@pytest.mark.parametrize("opposite", [False, True])
def test_mixed_move_coplanar_source_and_draft(qtbot: QtBot, opposite: bool) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    saved = LineEntity(
        uuid4().hex, frame.world_to_local((0, 0, 0)), frame.world_to_local((20, 0, 0))
    )
    draft = LineEntity(uuid4().hex, (0, 10), (20, 10))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, (saved,)), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    assert canvas.replace_draft_entities((draft,)) and canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((10, 10)),
    )
    assert canvas.selected_entity_ids == {saved.entity_id, draft.entity_id}
    for value in ("MOVE", "0,0", "4,2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    mixed = canvas.mixed_move
    assert mixed is not None
    changed = mixed.current_saved[0].entities[0]
    assert isinstance(changed, LineEntity)
    assert frame.local_to_world(changed.start_mm) == pytest.approx((4, 2, 0))
    assert canvas.undo_last_operation() and canvas.redo_last_operation()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert services.kernel.sketches[0].entities[0] == changed


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("rotate", [False, True])
def test_committed_transform_uses_view_coordinates(
    qtbot: QtBot, opposite: bool, rotate: bool
) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    line = LineEntity(uuid4().hex, frame.world_to_local((1, 0, 0)), frame.world_to_local((2, 0, 0)))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, (line,)), session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    before = len(loaded.document.commands)
    if rotate:
        editor.canvas.committed_rotation_requested.emit((line.entity_id,), (0, 0), 90.0)
    else:
        editor.canvas.committed_move_requested.emit((line.entity_id,), (4, 2))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == before + 1, editor.status_label.text()
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, LineEntity)
    expected = ((0, 1, 0), (0, 2, 0)) if rotate else ((5, 2, 0), (6, 2, 0))
    assert frame.local_to_world(changed.start_mm) == pytest.approx(expected[0])
    assert frame.local_to_world(changed.end_mm) == pytest.approx(expected[1])


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_saved_trim_maps_view_fragments_to_source_frame(
    qtbot: QtBot, opposite: bool, batch: bool
) -> None:
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    line = LineEntity(uuid4().hex, frame.world_to_local((1, 0, 0)), frame.world_to_local((5, 0, 0)))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, (line,)), session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    before = len(loaded.document.commands)
    fragment = LineEntity(line.entity_id, (2, 0), (5, 0))
    if batch:
        editor.canvas.committed_drag_trim_requested.emit(
            ((line.entity_id, (fragment,)),),
            tuple(editor.canvas.entities),
            tuple(editor.canvas.constraints),
            editor.canvas.background_entities,
            loaded.document.revision,
        )
    else:
        editor.canvas.committed_line_edit_requested.emit("修剪", line.entity_id, (fragment,))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == before + 1, editor.status_label.text()
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, LineEntity)
    assert frame.local_to_world(changed.start_mm) == pytest.approx((2, 0, 0))
    assert frame.local_to_world(changed.end_mm) == pytest.approx((5, 0, 0))
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    assert services.kernel.sketches[0].entities == (line,)
