# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The 2D BREAKATPOINT command's direct canvas interaction."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("preselected", (False, True))
def test_break_at_point_draft_command(qtbot: QtBot, preselected: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    if preselected:
        canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "单点打断"
    if not preselected:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    bar.setText("4,3")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2
    first, second = canvas.entities
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == second.start_mm == (4, 0)
    assert canvas.undo_last_operation()
    assert canvas.entities == [line]


def test_break_at_point_saved_command(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    bar.setText("4,3")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.sketches[0].entities) == 2, canvas.message
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_break_at_point_button_escape(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.tool_buttons["单点打断"].click()
    assert editor.canvas.tool == "单点打断"
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert editor.canvas.tool == "选择元素"
    assert editor.canvas.entities == [line]


@pytest.mark.parametrize("finish", ("command_enter", "canvas_enter", "right_click"))
def test_break_at_point_finish_and_repeat(qtbot: QtBot, finish: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    if finish == "command_enter":
        QTest.keyClick(bar, Qt.Key.Key_Return)
    elif finish == "canvas_enter":
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    else:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.tool == "选择元素"
    assert canvas.entities == [line]
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "单点打断"


@pytest.mark.parametrize("state", ("hidden", "frozen", "locked"))
def test_break_at_point_rechecks_layer_after_selection(qtbot: QtBot, state: str) -> None:
    from dataclasses import replace

    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = SketchLayerTable().add(SketchLayer("A"))
    canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="A")
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    layer = layers.get("A")
    layer = replace(layer, **{"visible": False} if state == "hidden" else {state: True})
    canvas.set_layer_table(layers.replace(layer), "0")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert canvas.entities == [line]
    assert "图层" in canvas.message


def test_break_at_point_rejects_constrained_draft(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [constraint]
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((4, 0), exact_point=True)
    assert editor.canvas.entities == [line]
    assert editor.canvas.constraints == [constraint]


def test_break_at_point_saved_arc_roundtrip(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {arc.entity_id}
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("0,8")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    after = services.kernel.sketches
    assert len(after[0].entities) == 2, canvas.message
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "break-at-point.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == after


def test_break_at_point_saved_polyline_with_draft(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    target = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {target.entity_id}
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("5,-8")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    assert canvas.entities == [draft]
    staged = canvas.mixed_move
    assert staged is not None and len(staged.current_saved[0].entities) == 2
    assert canvas.undo_last_operation()
    assert canvas.mixed_move is None
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    result = services.kernel.sketches
    assert len(result) == 2 and len(result[0].entities) == 2
    path = tmp_path / "mixed-break.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == result


def test_break_at_point_rejects_saved_constrained_target(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("4,0")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (sketch,)
    assert "失败" in window.status_command.text()
    assert "constraints" in window.status_command.text()


def test_break_at_point_reports_removed_inferred_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas = editor.canvas
    canvas.entities = [line, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((8, 0), exact_point=True)
    assert not canvas.constraints
    assert "移除" in canvas.message and "关系" in canvas.message
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


def test_break_at_point_rebinds_unique_inferred_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas = editor.canvas
    canvas.entities = [line, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert len(canvas.constraints) == 1
    assert canvas.constraints[0].references[0].entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


def test_break_at_point_rebinds_confirmed_polyline_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(path.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas = editor.canvas
    canvas.entities = [path, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {path.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert len(canvas.entities) == 3, canvas.message
    assert canvas.constraints[0].references[0].entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


def test_break_at_point_saved_confirmed_tangency_roundtrip(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(path.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {path.entity_id}
    bar = editor.drawing_command_bar.input
    bar.setText("BREAKATPOINT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("4,0")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    after = services.kernel.sketches
    assert len(after[0].entities) == 3, window.status_command.text()
    assert after[0].constraints[0].references[0].entity_id == after[0].entities[1].entity_id
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    assert services.kernel.sketches == after
    output = tmp_path / "confirmed-tangent-break.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.sketches == after


def test_break_at_point_confirmed_tangency_with_draft(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(path.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {path.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    staged = canvas.mixed_move
    assert staged is not None
    updated = staged.current_saved[0]
    assert updated.constraints[0].references[0].entity_id == updated.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches[0] == updated


def test_break_at_point_saved_object_tangency_roundtrip(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, path.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {path.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches
    assert len(result[0].entities) == 2, window.status_command.text()
    rebound = services.kernel.cross_sketch_tangencies
    assert rebound[0].relation_id == relation.relation_id
    assert rebound[0].first.entity_id == result[0].entities[1].entity_id
    loaded.bus.undo()
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo()
    assert services.kernel.sketches == result
    assert services.kernel.cross_sketch_tangencies == rebound
    output = tmp_path / "break-tangent-objects.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.cross_sketch_tangencies == rebound
    assert restored.kernel.sketches == result


def test_break_at_point_pending_tangency_follows_line_fragment(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = SketchGeometryReference(circle.entity_id, "geometry")
    draft = SketchGeometryReference(line.entity_id, "geometry")
    canvas.entities = [line]
    canvas.pending_cross_tangencies = [(source, draft)]
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert len(canvas.pending_cross_tangencies) == 1
    rebound = canvas.pending_cross_tangencies[0][1]
    assert isinstance(rebound, SketchGeometryReference)
    assert rebound.entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [(source, draft)]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_break_at_point_pending_tangent_at_split_is_reported(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),))
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    pair = (
        SketchGeometryReference(circle.entity_id, "geometry"),
        SketchGeometryReference(line.entity_id, "geometry"),
    )
    canvas.entities = [line]
    canvas.pending_cross_tangencies = [pair]
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((8, 0), exact_point=True)
    assert not canvas.pending_cross_tangencies
    assert "移除" in canvas.pending_tangency_removal_notice
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [pair]


def test_break_at_point_pending_arc_endpoint_follows_fragment(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (-7, 0), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    source = SketchGeometryReference(circle.entity_id, "geometry")
    endpoint = DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "end")
    canvas.entities = [arc]
    canvas.pending_cross_tangencies = [(source, endpoint)]
    canvas.selected_entity_ids = {arc.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((0, 5), exact_point=True)
    assert len(canvas.pending_cross_tangencies) == 1
    rebound = canvas.pending_cross_tangencies[0][1]
    assert isinstance(rebound, DraftConnectedEndpoint)
    assert rebound.reference.entity_id == canvas.entities[1].entity_id and rebound.endpoint == "end"
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [(source, endpoint)]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].second_endpoint == "end"
    output = tmp_path / "pending-arc-break.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.cross_sketch_tangencies == relations


def test_break_at_point_saved_line_tangency_follows_new_fragment(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(services.kernel.sketches[0].entities) == 2, window.status_command.text()
    rebound = services.kernel.cross_sketch_tangencies[0]
    result = services.kernel.sketches
    assert rebound.relation_id == relation.relation_id
    assert rebound.first.entity_id == services.kernel.sketches[0].entities[1].entity_id
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    output = tmp_path / "line-break-tangency.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.cross_sketch_tangencies == (rebound,)
    assert restored.kernel.sketches == result


def test_break_at_point_saved_line_at_contact_rejects_ambiguity(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((8, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert "无法唯一确定" in window.status_command.text()


def test_break_at_point_local_line_tangency_roundtrip(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches
    assert len(result[0].entities) == 3, window.status_command.text()
    assert result[0].constraints[0].references[0].entity_id == result[0].entities[1].entity_id
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    output = tmp_path / "local-line-break.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.sketches == result


def test_break_at_point_local_tangency_failure_reports_reason(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("BREAKATPOINT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("8,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert services.kernel.sketches == (sketch,)
    assert "无法保留相切关系" in bar.status.text()
    assert "图元未修改" in editor.status_label.text()


@pytest.mark.parametrize("constrained", (False, True))
def test_break_at_point_saved_async_reports_result(qtbot: QtBot, constrained: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line,), constraints=(constraint,) if constrained else ()
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("BREAKATPOINT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("4,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert ("失败" if constrained else "已单点打断") in bar.status.text()
    assert len(services.kernel.sketches[0].entities) == (1 if constrained else 2)


def test_break_at_point_mixed_failure_reports_reason(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("BREAKATPOINT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("4,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert "失败" in bar.status.text()
    assert services.kernel.sketches == (sketch,)
    assert canvas.entities == [draft] and canvas.mixed_move is None


def test_break_at_point_stale_source_reports_reason(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("BREAKATPOINT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    canvas.source_context_revision = -1
    bar.input.setText("4,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert services.kernel.sketches == (sketch,)
    assert "文档已变化" in bar.status.text()


def test_break_at_point_local_line_tangency_with_draft(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (20, 0), (30, 0)),))
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    staged = canvas.mixed_move
    assert staged is not None
    revised = staged.current_saved[0]
    assert revised.constraints[0].references[0].entity_id == revised.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches[0] == revised


def test_break_at_point_local_line_tangency_in_draft(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas = editor.canvas
    canvas.entities = [line, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {line.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert len(canvas.entities) == 3, canvas.message
    assert canvas.constraints[0].references[0].entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


def test_break_at_point_polyline_inferred_tangency_follows_fragment(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(path.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas = editor.canvas
    canvas.entities = [path, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {path.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((4, 0), exact_point=True)
    assert len(canvas.constraints) == 1
    assert canvas.constraints[0].references[0].entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


@pytest.mark.parametrize("ambiguous", (False, True))
def test_break_at_point_polyline_inferred_arc_contact(qtbot: QtBot, ambiguous: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1, 0))
    circle = CircleEntity(uuid4().hex, (5, -7), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(path.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas = editor.canvas
    canvas.entities = [path, circle]
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {path.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point(
        (5, -5) if ambiguous else (1.464466094, -3.535533906), exact_point=True
    )
    if ambiguous:
        assert not canvas.constraints
        assert "移除" in canvas.message
    else:
        assert len(canvas.constraints) == 1
        assert canvas.constraints[0].references[0].entity_id == canvas.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.constraints == [constraint]


@pytest.mark.parametrize("local", (False, True))
def test_break_at_point_saved_arc_tangency_roundtrip(
    qtbot: QtBot, tmp_path: Path, local: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    circle = CircleEntity(uuid4().hex, (0, 7), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(arc.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    first = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (arc, circle) if local else (arc,),
        constraints=(constraint,) if local else (),
    )
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    if not local:
        second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, second, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, arc.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "external",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    editor.set_context_sketches(original)
    canvas = editor.canvas
    canvas.selected_entity_ids = {arc.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((5, 5), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches
    assert len(result[0].entities) == (3 if local else 2), window.status_command.text()
    suffix_id = result[0].entities[1].entity_id
    if local:
        assert result[0].constraints[0].references[0].entity_id == suffix_id
    else:
        assert services.kernel.cross_sketch_tangencies[0].first.entity_id == suffix_id
    loaded.bus.undo()
    assert services.kernel.sketches == original
    loaded.bus.redo()
    output = tmp_path / "arc-tangent-break.my2d"
    save_document(loaded.document, output)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, output)
    assert restored.kernel.sketches == result
    assert restored.kernel.cross_sketch_tangencies == services.kernel.cross_sketch_tangencies


def test_break_at_point_local_arc_tangency_with_draft(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    circle = CircleEntity(uuid4().hex, (0, 7), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(arc.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (20, 0), (30, 0)),))
    canvas.selected_entity_ids = {arc.entity_id}
    assert canvas.set_tool("单点打断")
    canvas.add_coordinate_point((5, 5), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    staged = canvas.mixed_move
    assert staged is not None
    revised = staged.current_saved[0]
    assert revised.constraints[0].references[0].entity_id == revised.entities[1].entity_id
    assert canvas.undo_last_operation()
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches[0] == revised
