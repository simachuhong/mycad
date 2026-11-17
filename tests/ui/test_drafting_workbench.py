# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Manual-acceptance regressions: embedded drafting and connected line input."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import LineEntity, PolylineEntity
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def editor(qtbot: QtBot) -> SketchEditorDialog:
    draft = SketchEditorDialog(continuous_lines=True)
    qtbot.addWidget(draft)
    draft.canvas.set_snapping_enabled(False)
    draft.canvas.set_auto_inference_enabled(False)
    return draft


def test_line_continues_from_each_previous_endpoint(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    lines = draft.canvas.entities
    assert len(lines) == 3
    assert all(isinstance(line, LineEntity) for line in lines)
    assert isinstance(lines[1], LineEntity)
    assert lines[1].start_mm == (30.0, 0.0)
    assert lines[1].end_mm == (30.0, 20.0)
    QTest.keyClick(draft.canvas, Qt.Key.Key_Return)
    assert not draft.canvas.has_pending_geometry
    assert len(lines) == 3
    assert draft.finish_button.isEnabled()


@pytest.mark.parametrize("closure", ["key", "point", "button"])
def test_line_chain_closes_precisely_and_undo_keeps_earlier_edges(
    qtbot: QtBot, closure: str
) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    if closure == "key":
        QTest.keyClick(draft.canvas, Qt.Key.Key_C)
    elif closure == "point":
        draft.canvas.set_snapping_enabled(True)
        draft.canvas.add_coordinate_point((0.1, 0.1))
    else:
        draft.close_chain_button.click()
    assert len(draft.canvas.entities) == 3
    last = draft.canvas.entities[-1]
    assert isinstance(last, LineEntity)
    assert last.end_mm == (0.0, 0.0)
    assert not draft.canvas.has_pending_geometry
    assert draft.canvas.undo_last_operation()
    assert len(draft.canvas.entities) == 2
    assert draft.canvas.redo_last_operation()
    assert draft.canvas.entities[-1] == last


def test_escape_keeps_lines_and_does_not_close_embedded_editor(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    draft.show()
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    QTest.keyClick(draft.canvas, Qt.Key.Key_Escape)
    QTest.keyClick(draft.canvas, Qt.Key.Key_Escape)
    assert len(draft.canvas.entities) == 2
    assert draft.isVisible()


def test_polyline_clicking_first_point_finishes_closed_path(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    draft.canvas.set_tool("多段线")
    draft.canvas.set_snapping_enabled(True)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.1, 0.1)):
        draft.canvas.add_coordinate_point(point)
    assert len(draft.canvas.entities) == 1
    entity = draft.canvas.entities[0]
    assert isinstance(entity, PolylineEntity)
    assert entity.closed
    assert len(entity.points_mm) == 3


def test_new_drawing_opens_embedded_workbench_with_visible_tools(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    assert not draft.isWindow()
    assert draft.window() is window
    assert draft.isVisible()
    assert draft.tool_buttons["圆"].isVisible()
    draft.tool_buttons["圆"].click()
    assert draft.canvas.tool == "圆"
    assert draft.transform_buttons["move"].isVisible()
    assert "XY" in draft.ucs_label.text()
    draft.cancel_button.click()
    assert window.active_sketch_dialog() is None
    assert window.viewport is not None and window.viewport.isVisible()


def test_part_sketch_is_embedded_and_can_commit_continuous_lines(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_sketch.trigger()
    draft = window.part_sketch_task
    assert draft is not None
    draft.lock_plane()
    draft.select_tool("continuous")
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.place_uv(point)
    draft.select_tool("select")
    draft.preview()
    assert draft.confirm_button.isEnabled(), draft.status_label.text()
    draft.confirm()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1, timeout=10000)
    assert loaded.document.commands[0].id == "sketch.create"
    assert len(services.kernel.sketches[0].entities) == 2


def test_line_undo_reconnects_to_previous_vertex(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    QTest.keyClick(draft.canvas, Qt.Key.Key_U)
    draft.canvas.add_coordinate_point((40.0, 10.0))
    assert len(draft.canvas.entities) == 2
    last = draft.canvas.entities[-1]
    assert isinstance(last, LineEntity)
    assert last.start_mm == (30.0, 0.0)
    assert last.end_mm == (40.0, 10.0)


def test_zero_length_segment_does_not_end_chain(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    assert len(draft.canvas.entities) == 2
    assert draft.canvas.can_close_chain


@pytest.mark.parametrize(
    "plane,labels", [("XY", ("X→", "Y↑")), ("XZ", ("X→", "−Z↑")), ("YZ", ("Y→", "Z↑"))]
)
def test_ucs_labels_follow_actual_workplane(
    qtbot: QtBot, plane: str, labels: tuple[str, str]
) -> None:
    draft = editor(qtbot)
    draft.plane_combo.setCurrentText(plane)
    assert draft.canvas.ucs_plane == plane
    assert all(label in draft.ucs_label.text() for label in labels)
    assert draft.canvas.local_to_screen((10, 0)).x() > draft.canvas.local_to_screen((0, 0)).x()
    assert draft.canvas.local_to_screen((0, 10)).y() < draft.canvas.local_to_screen((0, 0)).y()


def test_document_switch_and_save_cannot_silently_drop_uncommitted_draft(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    window.act_new.trigger()
    assert window.active_sketch_dialog() is draft
    assert draft.isVisible()

    def save_target(*_args: object) -> tuple[str, str]:
        return str(tmp_path / "incomplete.mc.json"), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", save_target)
    window.act_save.trigger()
    qtbot.waitUntil((tmp_path / "incomplete.mc.json").exists)
    loaded = window.loaded_document()
    assert loaded is not None
    assert len(loaded.document.commands) == 1
    assert len(services.kernel.sketches[0].entities) == 2
    assert not loaded.document.is_dirty


def test_main_undo_routes_to_active_draft(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    window.request_undo()
    assert len(draft.canvas.entities) == 1
    window.request_redo()
    assert len(draft.canvas.entities) == 2
    draft.cancel_button.click()


def test_close_key_uses_exact_first_point_even_with_ortho_enabled(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    draft.canvas.set_orthogonal_enabled(True)
    QTest.keyClick(draft.canvas, Qt.Key.Key_C)
    last = draft.canvas.entities[-1]
    assert isinstance(last, LineEntity)
    assert last.end_mm == (0.0, 0.0)


def test_mouse_line_chain_snaps_to_first_point_and_closes(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    draft.resize(1024, 768)
    draft.show()
    draft.canvas.set_snapping_enabled(True)
    qtbot.waitExposed(draft)
    for point in ((-30.0, -20.0), (30.0, -20.0), (30.0, 20.0), (-29.5, -19.5)):
        QTest.mouseClick(
            draft.canvas, Qt.MouseButton.LeftButton, pos=draft.canvas.local_to_screen(point)
        )
    lines = draft.canvas.entities
    assert len(lines) == 3
    assert isinstance(lines[0], LineEntity) and isinstance(lines[-1], LineEntity)
    assert lines[-1].end_mm == lines[0].start_mm
    assert not draft.canvas.has_pending_geometry


def test_undo_first_line_can_redo_and_continue_chain(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((30.0, 0.0))
    assert draft.canvas.undo_last_operation()
    assert len(draft.canvas.entities) == 0
    assert draft.canvas.redo_last_operation()
    draft.canvas.add_coordinate_point((30.0, 20.0))
    assert len(draft.canvas.entities) == 2


def test_undo_closure_restores_chain_endpoint_for_continuation(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    draft.canvas.close_chain()
    assert draft.canvas.undo_last_operation()
    draft.canvas.add_coordinate_point((40.0, 20.0))
    assert len(draft.canvas.entities) == 3
    last = draft.canvas.entities[-1]
    assert isinstance(last, LineEntity)
    assert last.start_mm == (30.0, 20.0)
    assert last.end_mm == (40.0, 20.0)


def test_finish_drawing_keeps_tools_and_committed_geometry_as_snap_context(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first = window.active_sketch_dialog()
    assert first is not None
    first.tool_buttons["矩形"].click()
    first.canvas.add_coordinate_point((0.0, 0.0))
    first.canvas.add_coordinate_point((30.0, 20.0))
    first.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not None, timeout=10000)
    second = window.active_sketch_dialog()
    assert second is not None and second is not first
    assert second.isVisible() and not second.isWindow()
    assert len(second.canvas.background_entities) == 1
    assert second.canvas.entities == []
    second.tool_buttons["圆"].click()
    second.canvas.add_coordinate_point((0.1, 0.1))
    second.canvas.add_coordinate_point((5.0, 0.0))
    second.finish_button.click()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 2, timeout=10000)
    assert len(services.kernel.sketches[1].entities) == 1
    from mycad.core.sketch import CircleEntity

    circle = services.kernel.sketches[1].entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == (0.0, 0.0)
    assert len(services.kernel.sketches[0].entities) == 1


def test_context_projection_respects_origin_plane_and_cannot_be_edited(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import Sketch, WorkPlaneFrame

    draft = editor(qtbot)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (30, 0)),))
    draft.set_context_sketches((source,))
    draft.origin_fields["X"].setValue(10)
    context, _layer = draft.canvas.background_entities[0]
    assert isinstance(context, LineEntity)
    assert context.start_mm == (-10.0, 0.0)
    assert context.end_mm == (20.0, 0.0)
    assert draft.canvas.entities == []
    draft.canvas.set_tool("选择元素")
    draft.show()
    QTest.mouseClick(
        draft.canvas, Qt.MouseButton.LeftButton, pos=draft.canvas.local_to_screen((5, 0))
    )
    assert not draft.canvas.selected_entity_ids
    draft.plane_combo.setCurrentText("YZ")
    assert draft.canvas.background_entities == ()
    original = source.entities[0]
    assert isinstance(original, LineEntity)
    assert original.start_mm == (0.0, 0.0)


def test_document_undo_redo_refreshes_committed_background(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((30, 0))
    draft.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not None, timeout=10000)
    next_draft = window.active_sketch_dialog()
    assert next_draft is not None and len(next_draft.canvas.background_entities) == 1
    window.request_undo()
    qtbot.waitUntil(lambda: not next_draft.canvas.background_entities, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: len(next_draft.canvas.background_entities) == 1, timeout=10000)
    assert next_draft.canvas.entities == []


def test_submit_refusal_restores_embedded_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_sketch.trigger()
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((30, 0))

    def refuse(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(unit, "submit", refuse)
    draft.finish_button.click()
    assert window.active_sketch_dialog() is draft
    assert draft.isVisible() and not draft.isWindow()
    assert len(draft.canvas.entities) == 1
    assert loaded.document.commands == ()
    draft.cancel_button.click()


def test_fit_view_keeps_large_draft_inside_canvas(qtbot: QtBot) -> None:
    draft = editor(qtbot)
    draft.resize(1024, 768)
    draft.show()
    qtbot.waitExposed(draft)
    draft.canvas.add_coordinate_point((1000.0, 1000.0))
    draft.canvas.add_coordinate_point((2000.0, 1500.0))
    draft.canvas.fit_view()
    for point in ((1000.0, 1000.0), (2000.0, 1500.0)):
        screen = draft.canvas.local_to_screen(point)
        assert 10 < screen.x() < draft.canvas.width() - 10
        assert 10 < screen.y() < draft.canvas.height() - 10


def test_changing_to_extend_preselects_under_stationary_pointer(qtbot: QtBot) -> None:
    from PySide6.QtGui import QCursor

    draft = editor(qtbot)
    draft.resize(1000, 740)
    draft.show()
    qtbot.waitExposed(draft)
    draft.tool_buttons["圆弧"].click()
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        draft.canvas.add_coordinate_point(point)
    arc_id = draft.canvas.entities[0].entity_id
    draft.tool_buttons["直线"].click()
    for point in ((5.0, -10.0), (5.0, 10.0)):
        draft.canvas.add_coordinate_point(point)
    draft.canvas.end_line_chain()
    position = draft.canvas.local_to_screen((10.0, 0.0))
    QCursor.setPos(draft.canvas.mapToGlobal(position))
    qtbot.waitUntil(lambda: draft.canvas.mapFromGlobal(QCursor.pos()) == position)
    draft.tool_combo.setCurrentText("延伸")
    assert draft.canvas.hovered_line_edit_target_id == arc_id
