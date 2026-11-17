# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deleting dimensions and tangent sources must remain one replayable action."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize(
    ("with_draft", "with_pending"), [(False, False), (True, False), (True, True)]
)
@pytest.mark.parametrize("use_erase", [False, True])
def test_delete_tangent_source_and_dimension_in_one_action(
    qtbot: QtBot, tmp_path: Path, with_draft: bool, with_pending: bool, use_erase: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    draft_id = ""
    if with_draft:
        draft_entity = (
            CircleEntity(uuid4().hex, (5, 2), 2)
            if with_pending
            else LineEntity(uuid4().hex, (20, 0), (25, 0))
        )
        draft_id = draft_entity.entity_id
        assert canvas.replace_draft_entities((draft_entity,))
        if with_pending:
            canvas.pending_cross_tangencies = [(line.entity_id, draft_id)]
    assert canvas.set_tool("选择元素")
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((9, 0)),
    )
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    count = len(loaded.document.commands)
    if use_erase:
        editor.drawing_command_bar.input.setText("ERASE")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if with_draft:
        assert canvas.mixed_move is not None, editor.status_label.text()
        assert not canvas.pending_cross_tangencies
        assert canvas.undo_last_operation()
        if with_pending:
            assert canvas.pending_cross_tangencies == [(line.entity_id, draft_id)]
        assert canvas.redo_last_operation()
        assert not canvas.pending_cross_tangencies
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
    else:
        assert len(loaded.document.commands) == count + 1, editor.status_label.text()
    assert services.kernel.sketches[0].entities == ()
    assert services.kernel.sketches[1].entities == (circle,)
    assert services.kernel.sketches[1].constraints == ()
    assert services.kernel.cross_sketch_tangencies == ()
    after = services.kernel.sketches
    if with_draft:
        loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches == before
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo()
    if with_draft:
        loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "delete-tangent-dimension.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == after
    assert reopened_services.kernel.cross_sketch_tangencies == ()


def test_delete_pending_draft_target_and_saved_dimension(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (-5, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    draft = CircleEntity(uuid4().hex, (5, 2), 2)
    keep = LineEntity(uuid4().hex, (20, 0), (25, 0))
    assert canvas.replace_draft_entities((draft, keep))
    canvas.pending_cross_tangencies = [(line.entity_id, draft.entity_id)]
    assert canvas.set_tool("选择元素")
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((7, 2)),
    )
    assert canvas.selected_entity_ids == {draft.entity_id}
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    assert canvas.entities == [keep] and not canvas.pending_cross_tangencies
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [(line.entity_id, draft.entity_id)]
    assert canvas.redo_last_operation()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert services.kernel.sketches[0].entities == (line, circle)
    assert not services.kernel.sketches[0].constraints
    assert services.kernel.sketches[1].entities == (keep,)
    assert not services.kernel.cross_sketch_tangencies
    after = services.kernel.sketches
    path = tmp_path / "delete-pending-target.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches == (saved,)
    loaded.bus.redo()
    loaded.bus.redo()
    assert services.kernel.sketches == after
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == after
