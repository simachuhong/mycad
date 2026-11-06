# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Direct canvas placement owns a transient group until Enter."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.drawing import DrawingSheet, DrawingState
from mycad.ui.drawing_tools import ViewPlacement


def test_place_base_then_first_angle_projected_view_without_committing() -> None:
    sheet = DrawingSheet(uuid4())
    state = DrawingState(sheets=(sheet,))
    placement = ViewPlacement(sheet, scale=0.5)
    placement.click((90, 140))
    ghost = placement.preview((92, 70))
    assert ghost is not None and ghost.direction == "top"
    assert ghost.offset_mm == (0, -70)
    placement.click((92, 70))
    placed = placement.finish()
    assert len(placed) == 2
    assert placed[1].parent_id == placed[0].view_id
    assert placed[0].scale == 0.5
    assert not state.views


def test_escape_discards_entire_uncommitted_group() -> None:
    placement = ViewPlacement(DrawingSheet(uuid4()))
    placement.click((90, 100))
    placement.click((160, 103))
    placement.cancel()
    assert placement.finish() == ()


def test_canvas_group_enter_and_undo(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QPointF, Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing_projection import LineCurve, ProjectedCurve, ProjectionResult
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.begin_placement()
    placement = bench.placement
    assert placement is not None
    for identity in (
        placement.base_id,
        *(placement.projected_id(d) for d in ("top", "bottom", "left", "right")),
    ):
        bench.projections[identity] = ProjectionResult(
            identity, "fixture", 1, (ProjectedCurve("line", LineCurve((0, 0), (20, 0))),)
        )
    bench.canvas.placing = True
    for point in (QPointF(90, -140), QPointF(90, -70)):
        QTest.mouseClick(
            bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=bench.canvas.mapFromScene(point)
        )
    assert len(loaded.document.commands) == 2
    assert len(placement.pending) == 2, (placement.pending, bench.hint.text())
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and bench.placement is None)
    assert len(services.kernel.drawing_state.views) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_state.views)
    assert len(loaded.document.commands) == 2


def test_new_document_clears_previous_sheet_canvas(qtbot: QtBot) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window.bind_document(loaded)
    assert window.drawing_workbench.canvas.drawing_scene is not None
    window.bind_document(new_document(services))
    assert window.drawing_workbench.canvas.drawing_scene is None


def test_unnormalized_periodic_spline_is_not_drawn_as_its_control_polygon() -> None:
    from mycad.core.drawing_projection import SplineCurve
    from mycad.ui.drawing_canvas import curve_path

    curve = SplineCurve(((0, 0), (10, 0), (5, 10)), 2, (0, 1, 2, 3), (1, 1, 1, 1), (1, 1, 1), True)
    with pytest.raises(ValueError, match="周期"):
        curve_path(curve)


def test_real_model_projection_is_placed_in_canvas(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QPointF, Qt

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box", {"size_x": 40, "size_y": 24, "size_z": 8, "center": [6, 9, 13]}
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    bench.begin_placement()
    qtbot.waitUntil(lambda: bench.canvas.placing, timeout=60000)
    assert bench.placement is not None
    assert bench.placement.base_id in bench.projections
    bench.canvas.fit_view()
    for point in (QPointF(90, -140), QPointF(90, -70), QPointF(180, -140)):
        pos = bench.canvas.mapFromScene(point)
        QTest.mouseMove(bench.canvas.viewport(), pos)
        QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.views) == 3 and bench.placement is None,
        timeout=10000,
    )
    qtbot.waitUntil(lambda: window.execution_unit is not None and not window.execution_unit.is_busy)
    scene = bench.canvas.drawing_scene
    assert scene is not None and len(scene.views) == 3
    assert not scene.issues
    screenshot = tmp_path / "engineering-workspace.png"
    assert window.grab().save(str(screenshot))
    print(f"Engineering workspace screenshot: {screenshot}")
    window.resize(960, 600)
    qtbot.wait(50)
    narrow = tmp_path / "engineering-narrow.png"
    assert window.grab().save(str(narrow))
    bench.parameter_dock.setFloating(True)
    bench.parameter_dock.show()
    qtbot.wait(50)
    floating = tmp_path / "engineering-floating.png"
    assert window.grab().save(str(floating))
    assert bench.parameter_dock.grab().save(str(tmp_path / "engineering-settings.png"))
    print(f"Narrow/floating screenshots: {narrow}, {floating}")


def test_changed_model_pauses_uncommitted_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 5})
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    bench.begin_placement()
    placement = bench.placement
    assert placement is not None
    placement.click((90, 140))
    bench.canvas.placing = True
    loaded.bus.execute("feature.box", {"size_x": 30, "size_y": 10, "size_z": 5})
    bench.refresh()
    assert bench.placement is placement and len(placement.pending) == 1
    assert not bench.canvas.placing
    assert "更新预览" in bench.hint.text()
    bench.cancel_placement()


def test_pending_engineering_group_blocks_document_replacement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    loaded.document.mark_clean()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    bench.begin_placement()
    assert bench.placement is not None
    bench.placement.click((90, 140))
    assert not window.close()
    assert "工程图" in window.status_command.text()
    bench.cancel_placement()


def test_opened_sheet_fits_on_first_activation_only(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QRectF

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping

    sheet_id = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet_id)})
    loaded.bus.execute(
        "drawing.view.create", drawing_object_mapping(DrawingView(uuid4(), sheet_id))
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    monkeypatch.setattr(window.drawing_workbench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    qtbot.wait(50)
    canvas = window.drawing_workbench.canvas
    paper = canvas.mapFromScene(QRectF(0, -210, 297, 210)).boundingRect()
    assert paper.height() > canvas.viewport().height() * 0.8
    canvas.scale(1.7, 1.7)
    transform = canvas.transform()
    window.workspace_tabs.activate("model")
    window.workspace_tabs.activate("drawing")
    qtbot.wait(50)
    assert canvas.transform() == transform


@pytest.mark.parametrize("remove", ["undo", "delete"])
def test_removing_placement_sheet_cancels_draft_and_allows_undo_redo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, remove: str
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    survivor, target = uuid4(), uuid4()
    for identity in (survivor, target):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(identity)})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    bench.sheet_id = target
    bench.begin_placement()
    assert bench.placement is not None
    bench.placement.click((80, 80))
    if remove == "undo":
        loaded.bus.undo()
    else:
        loaded.bus.execute("drawing.sheet.delete", {"sheet_id": str(target)})
    bench.refresh()
    assert bench.sheet_id == survivor
    assert bench.placement is None
    assert not bench.canvas.placing
    assert "图纸" in bench.hint.text() and "取消" in bench.hint.text()
    if remove == "undo":
        loaded.bus.redo()
    else:
        loaded.bus.undo()
    bench.refresh()
    assert services.kernel.drawing_state.sheet(target).sheet_id == target
    assert bench.placement is None  # Restoring the sheet must not resurrect an unsubmitted draft.
    bench.sheet_id = target
    bench.begin_placement()
    assert bench.placement is not None
    bench.cancel_placement()


@pytest.mark.parametrize("draft_kind", ["view", "note"])
@pytest.mark.parametrize("target_kind", ["sheet", "view"])
def test_switching_sheet_preserves_unsubmitted_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, draft_kind: str, target_kind: str
) -> None:
    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    first, second = uuid4(), uuid4()
    for identity in (first, second):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(identity)})
    if target_kind == "view":
        loaded.bus.execute(
            "drawing.view.create", drawing_object_mapping(DrawingView(uuid4(), second))
        )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    assert bench.sheet_id == first
    if draft_kind == "view":
        bench.begin_placement()
        assert bench.placement is not None
        bench.placement.click((80, 80))
    else:
        bench.notes.begin()
        bench.notes.click((80.0, 80.0))
        bench.notes.editor.setPlainText("尚未提交的文字")
    first_item = bench.tree.topLevelItem(0)
    assert first_item is not None
    bench.tree.itemClicked.emit(first_item, 0)
    assert bench.sheet_id == first
    if draft_kind == "view":
        assert bench.placement is not None
    else:
        assert bench.notes.pending
    second_item = bench.tree.topLevelItem(1)
    assert second_item is not None
    target = second_item if target_kind == "sheet" else second_item.child(0)
    assert target is not None
    bench.tree.setCurrentItem(target)
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == first
    assert bench.tree.currentItem() is first_item
    assert "完成或取消" in bench.hint.text()
    if draft_kind == "view":
        assert bench.placement is not None and bench.placement.pending
        bench.cancel_placement()
    else:
        assert bench.notes.pending and bench.notes.editor.toPlainText() == "尚未提交的文字"
        bench.notes.cancel()
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == second


def test_switching_sheet_preserves_unsubmitted_annotation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_projection import LineCurve
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    first, second = uuid4(), uuid4()
    for identity in (first, second):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(identity)})
    view = DrawingView(uuid4(), first)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.updates.sync(
        bench.session_id, services.kernel.drawing_source_fingerprint, {view.view_id: view.basis}
    )
    batch = bench.updates.begin()
    assert batch is not None
    bench.updates.finish(batch, (services.kernel.project_drawing(batch.requests[0]),))
    bench.annotations.begin("aligned")
    for curve in bench.projections[view.view_id].curves:
        if isinstance(curve.geometry, LineCurve) and curve.source is not None:
            bench.annotations.choose(view.view_id, curve.curve_id, (80.0, 80.0))
            if bench.annotations.draft is not None:
                break
    pending = bench.annotations.draft
    assert pending is not None
    target = bench.tree.topLevelItem(1)
    assert target is not None
    bench.tree.setCurrentItem(target)
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == first and bench.annotations.draft == pending
    assert "完成或取消" in bench.hint.text()
    bench.annotations.cancel()
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == second


def test_selecting_view_on_current_sheet_keeps_note_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.notes.begin()
    bench.notes.click((80.0, 80.0))
    bench.notes.editor.setPlainText("文字草稿")
    parent = bench.tree.topLevelItem(0)
    assert parent is not None
    item = parent.child(0)
    assert item is not None
    bench.tree.itemClicked.emit(item, 0)
    assert bench.sheet_id == sheet and bench.canvas.selected_view == view.view_id
    assert bench.notes.pending and bench.notes.editor.toPlainText() == "文字草稿"


def test_switching_sheet_preserves_pending_view_deletion(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    first, second = uuid4(), uuid4()
    for identity in (first, second):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(identity)})
    view = DrawingView(uuid4(), first)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.select_view(view.view_id)
    bench.preview_delete()
    assert bench.confirm_delete_action.isVisible()
    target = bench.tree.topLevelItem(1)
    assert target is not None
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == first and bench.confirm_delete_action.isVisible()
    assert "完成或取消" in bench.hint.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    assert not bench.confirm_delete_action.isVisible()
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == second


def test_switching_sheet_preserves_view_move_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    first, second = uuid4(), uuid4()
    for identity in (first, second):
        loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(identity)})
    view = DrawingView(uuid4(), first)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    original = loaded.document.commands
    bench.canvas.view_dragged.emit(view.view_id, "move", (90.0, 100.0), False)
    target = bench.tree.topLevelItem(1)
    assert target is not None
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == first and loaded.document.commands == original
    assert "完成或取消" in bench.hint.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    bench.tree.itemClicked.emit(target, 0)
    assert bench.sheet_id == second and loaded.document.commands == original


@pytest.mark.parametrize("operation", ["move", "delete"])
def test_pending_view_edit_blocks_window_close(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    loaded.document.mark_clean()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.select_view(view.view_id)
    if operation == "move":
        bench.canvas.view_dragged.emit(view.view_id, "move", (90.0, 100.0), False)
    else:
        bench.preview_delete()
    target = tmp_path / "not-saved.mc.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_args: (str(target), ""))
    )
    assert window.act_save.isEnabled()
    window.act_save.trigger()
    assert not target.exists()
    assert "工程图" in window.status_command.text()
    assert not window.close()
    assert "工程图" in window.status_command.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    assert window.close()


@pytest.mark.parametrize("operation", ["move", "delete"])
def test_pending_view_edit_blocks_switch_to_another_view(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtCore import Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    first, second = DrawingView(uuid4(), sheet), DrawingView(uuid4(), sheet)
    for view in (first, second):
        loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.select_view(first.view_id)
    if operation == "move":
        bench.canvas.view_dragged.emit(first.view_id, "move", (90.0, 100.0), False)
    else:
        bench.preview_delete()
    sheet_item = bench.tree.topLevelItem(0)
    assert sheet_item is not None
    target = sheet_item.child(1)
    assert target is not None
    bench.tree.setCurrentItem(target)
    bench.tree.itemClicked.emit(target, 0)
    assert bench.canvas.selected_view == first.view_id
    assert bench.tree.currentItem() is sheet_item.child(0)
    assert "完成或取消" in bench.hint.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    bench.tree.itemClicked.emit(target, 0)
    assert bench.canvas.selected_view == second.view_id


def test_pending_view_deletion_blocks_selecting_another_canvas_view(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPointF, Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingNote, DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    first = DrawingView(uuid4(), sheet, anchor_mm=(60, 100))
    second = DrawingView(uuid4(), sheet, anchor_mm=(180, 100))
    for view in (first, second):
        loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    note = DrawingNote(uuid4(), sheet, "说明", (130, 140))
    loaded.bus.execute("drawing.note.create", drawing_object_mapping(note))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.updates.sync(
        bench.session_id,
        services.kernel.drawing_source_fingerprint,
        {view.view_id: view.basis for view in (first, second)},
    )
    batch = bench.updates.begin()
    assert batch is not None
    bench.updates.finish(
        batch, tuple(services.kernel.project_drawing(req) for req in batch.requests)
    )
    bench.refresh()
    bench.canvas.fit_view()
    bench.canvas.select_view(first.view_id)
    bench.preview_delete()
    note_point = bench.canvas.note_text_position(note.note_id)
    QTest.mouseDClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=note_point)
    assert bench.canvas.selected_view == first.view_id and bench.canvas.selected_note is None
    assert not bench.notes.pending
    point = bench.canvas.mapFromScene(QPointF(180, -100))
    QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert bench.canvas.selected_view == first.view_id
    assert bench.confirm_delete_action.isVisible()
    assert "完成或取消" in bench.hint.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert bench.canvas.selected_view == second.view_id


@pytest.mark.parametrize("action", ["sheet", "text", "dimension", "placement", "settings"])
@pytest.mark.parametrize("operation", ["move", "delete"])
def test_pending_view_edit_blocks_starting_another_command(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str, operation: str
) -> None:
    from PySide6.QtCore import Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.select_view(view.view_id)
    if operation == "move":
        bench.canvas.view_dragged.emit(view.view_id, "move", (90.0, 100.0), False)
    else:
        bench.preview_delete()
    before = loaded.document.commands
    if action == "sheet":
        bench.create_sheet()
    elif action == "text":
        bench.begin_text()
    elif action == "dimension":
        bench.annotations.begin("aligned")
    elif action == "placement":
        bench.begin_placement()
    else:
        bench.apply_sheet_settings()
    assert bench.has_pending_view_edit
    if operation == "delete":
        assert bench.confirm_delete_action.isVisible()
    assert bench.canvas.selected_view == view.view_id
    assert not bench.notes.pending and not bench.canvas.annotation_mode and bench.placement is None
    assert loaded.document.commands == before
    assert "完成或取消" in bench.hint.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)


@pytest.mark.parametrize(
    "action", ["sheet", "text", "placement", "settings", "delete", "dimension"]
)
def test_unsubmitted_dimension_blocks_other_operations(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_projection import LineCurve
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.updates.sync(
        bench.session_id, services.kernel.drawing_source_fingerprint, {view.view_id: view.basis}
    )
    batch = bench.updates.begin()
    assert batch is not None
    bench.updates.finish(batch, (services.kernel.project_drawing(batch.requests[0]),))
    bench.canvas.select_view(view.view_id)
    bench.annotations.begin("aligned")
    for curve in bench.projections[view.view_id].curves:
        if isinstance(curve.geometry, LineCurve) and curve.source is not None:
            bench.annotations.choose(view.view_id, curve.curve_id, (80.0, 80.0))
            if bench.annotations.draft is not None:
                break
    draft = bench.annotations.draft
    assert draft is not None
    history = len(loaded.document.commands)
    operations = {
        "sheet": bench.create_sheet,
        "text": bench.begin_text,
        "placement": bench.begin_placement,
        "settings": bench.apply_sheet_settings,
        "delete": bench.preview_delete,
        "dimension": lambda: bench.annotations.begin("horizontal"),
    }
    operations[action]()
    assert bench.annotations.draft == draft
    assert len(loaded.document.commands) == history
    assert bench.placement is None and not bench.notes.pending
    assert not bench.confirm_delete_action.isVisible()
    assert "完成或取消" in bench.hint.text()


@pytest.mark.parametrize("action", ["sheet", "dimension"])
def test_active_view_placement_blocks_other_operations(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.begin_placement()
    placement = bench.placement
    assert placement is not None
    history = len(loaded.document.commands)
    if action == "sheet":
        bench.create_sheet()
    else:
        bench.annotations.begin("aligned")
    assert bench.placement is placement
    assert len(loaded.document.commands) == history
    assert not bench.canvas.annotation_mode
    assert "完成或取消" in bench.hint.text()
