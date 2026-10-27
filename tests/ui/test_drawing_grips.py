# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Paper-space grip previews never mutate model geometry or live drawing state."""

from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.drawing import DrawingSheet, DrawingState, DrawingView
from mycad.core.drawing_codec import apply_drawing_command
from mycad.ui.drawing_tools import move_view, scale_view, set_view_alignment


def state() -> DrawingState:
    sheet = DrawingSheet(uuid4())
    parent = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(90, 140))
    child = DrawingView(
        uuid4(), sheet.sheet_id, parent_id=parent.view_id, direction="top", offset_mm=(0, -60)
    )
    return DrawingState((sheet,), (parent, child))


def test_parent_move_keeps_children_aligned() -> None:
    original = state()
    parent, child = original.views
    changed = apply_drawing_command(
        original, "drawing.view.update", move_view(original, parent.view_id, (110, 150))
    )
    assert changed.effective_anchor(child.view_id) == (110, 90)
    assert original.effective_anchor(child.view_id) == (90, 80)


def test_child_move_is_axis_constrained_and_detach_is_explicit() -> None:
    original = state()
    child = original.views[1]
    moved = apply_drawing_command(
        original, "drawing.view.update", move_view(original, child.view_id, (120, 100))
    )
    assert moved.effective_anchor(child.view_id) == (90, 100)
    detached = apply_drawing_command(
        moved, "drawing.view.update", set_view_alignment(moved, child.view_id, False)
    )
    free = apply_drawing_command(
        detached, "drawing.view.update", move_view(detached, child.view_id, (120, 100))
    )
    assert free.effective_anchor(child.view_id) == (120, 100)
    reattached = apply_drawing_command(
        free, "drawing.view.update", set_view_alignment(free, child.view_id, True)
    )
    assert reattached.effective_anchor(child.view_id) == (90, 100)


def test_scale_override_and_restore() -> None:
    original = state()
    parent, child = original.views
    resized = apply_drawing_command(
        original, "drawing.view.update", scale_view(original, parent.view_id, 0.5)
    )
    assert resized.effective_scale(child.view_id) == 0.5
    overridden = apply_drawing_command(
        resized, "drawing.view.update", scale_view(resized, child.view_id, 2)
    )
    assert overridden.effective_scale(child.view_id) == 2
    restored = apply_drawing_command(
        overridden, "drawing.view.update", scale_view(overridden, child.view_id, None)
    )
    assert restored.effective_scale(child.view_id) == 0.5


def test_canvas_drag_is_preview_until_release_and_one_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from mycad.app import build_app, new_document
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_projection import LineCurve, ProjectedCurve, ProjectionResult
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    initial = state()
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(initial.sheets[0]))
    loaded.bus.execute(
        "drawing.view.create", {"views": [drawing_object_mapping(v) for v in initial.views]}
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    for view in initial.views:
        bench.projections[view.view_id] = ProjectionResult(
            view.view_id, "fixture", 1, (ProjectedCurve("line", LineCurve((0, 0), (20, 0))),)
        )
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.fit_view()
    parent, child = initial.views
    bench.canvas.select_view(parent.view_id)
    start = bench.canvas.grip_position("move")
    end = start + QPoint(35, -15)
    before = len(loaded.document.commands)
    for leave in (False, True):
        QTest.mousePress(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(bench.canvas.viewport(), end)
        if leave:
            window.workspace_tabs.activate("model")
            window.workspace_tabs.activate("drawing")
        else:
            QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert services.kernel.drawing_state == initial
        assert len(loaded.document.commands) == before
        bench.canvas.select_view(parent.view_id)
        start = bench.canvas.grip_position("move")
        end = start + QPoint(35, -15)
    QTest.mousePress(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bench.canvas.viewport(), end)
    assert len(loaded.document.commands) == before
    QTest.mouseRelease(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == before + 1)
    moved = services.kernel.drawing_state
    assert moved.effective_anchor(parent.view_id) != initial.effective_anchor(parent.view_id)
    assert moved.effective_anchor(child.view_id)[0] == moved.effective_anchor(parent.view_id)[0]
    assert window.execution_unit is not None
    qtbot.waitUntil(lambda: window.execution_unit is not None and not window.execution_unit.is_busy)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_state == initial)


def test_delete_view_subtree_is_one_undo(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingAnnotation
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_references import DrawingGeometryReference
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    initial = state()
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(initial.sheets[0]))
    loaded.bus.execute(
        "drawing.view.create", {"views": [drawing_object_mapping(v) for v in initial.views]}
    )
    annotation = DrawingAnnotation(
        uuid4(),
        initial.views[1].view_id,
        "diameter",
        (DrawingGeometryReference("cylindrical_face"),),
        (120, 90),
    )
    loaded.bus.execute("drawing.annotation.create", drawing_object_mapping(annotation))
    initial = replace(initial, annotations=(annotation,))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    bench.canvas.select_view(initial.views[0].view_id)
    bench.preview_delete()
    assert len(services.kernel.drawing_state.views) == 2
    bench.confirm_delete()
    qtbot.waitUntil(lambda: not services.kernel.drawing_state.views)
    assert window.execution_unit is not None
    qtbot.waitUntil(lambda: window.execution_unit is not None and not window.execution_unit.is_busy)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_state == initial)


def test_clear_paper_clears_view_selection(qtbot: QtBot) -> None:
    from mycad.core.drawing_projection import DrawingScene
    from mycad.ui.drawing_canvas import DrawingCanvas

    canvas = DrawingCanvas()
    qtbot.addWidget(canvas)
    canvas.set_scene(DrawingScene(uuid4(), (297, 210), 10, (), ()))
    canvas.select_view(uuid4())
    canvas.clear_scene()
    assert canvas.selected_view is None


def test_external_delete_cancels_pending_delete(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    initial = state()
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(initial.sheets[0]))
    loaded.bus.execute(
        "drawing.view.create", {"views": [drawing_object_mapping(v) for v in initial.views]}
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    bench.canvas.select_view(initial.views[0].view_id)
    bench.preview_delete()
    loaded.bus.execute("drawing.view.delete", {"view_id": str(initial.views[0].view_id)})
    bench.refresh()
    bench.confirm_delete()
    assert not bench.confirm_delete_action.isVisible()
