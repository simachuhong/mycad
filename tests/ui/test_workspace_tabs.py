# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Three permanent workspaces preserve drafts and route commands by active page."""

from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


def test_document_switch_waits_until_result_callback_finishes(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    second = window.new_session_document("part")
    window.activate_session_document(first.loaded.document.document_id)
    unit = window.execution_unit
    assert unit is not None
    entered, release = Event(), Event()
    callback_documents: list[object] = []

    def blocking_work() -> None:
        entered.set()
        assert release.wait(10)

    def busy_changed(busy: bool) -> None:
        if not busy:
            window.activate_session_document(second.loaded.document.document_id)

    def complete(_result: object) -> None:
        callback_documents.append(session.active)

    def result_ready(_result: object) -> None:
        window.activate_session_document(second.loaded.document.document_id)

    unit.busy_changed.connect(busy_changed)
    unit.result_ready.connect(result_ready)
    assert unit.submit(
        blocking_work, operation="test-switch", session_id=unit.session_id, on_complete=complete
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(callback_documents), timeout=10000)
    assert callback_documents == [first]
    qtbot.waitUntil(lambda: session.active is second, timeout=10000)


def test_document_switch_restores_selection_filter_and_menu(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    first = window.new_session_document("part")
    view = window.viewport
    assert view is not None
    window.selection_filter_actions["edge"].trigger()
    second = window.new_session_document("part")
    window.selection_filter_actions["vertex"].trigger()
    window.activate_session_document(first.loaded.document.document_id)
    assert view.selection_filter() == "edge"
    assert window.selection_filter_actions["edge"].isChecked()
    window.activate_session_document(second.loaded.document.document_id)
    assert view.selection_filter() == "vertex"
    assert window.selection_filter_actions["vertex"].isChecked()
    assert not first.loaded.document.commands and not second.loaded.document.commands


def test_drawing_draft_cannot_finish_during_result_handoff(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    draft.canvas.set_tool("直线")
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((10, 0))
    draft.canvas.end_line_chain()
    assert not draft.canvas.has_pending_geometry
    entered, release = Event(), Event()
    observed: list[tuple[bool, int, bool, str]] = []

    def work() -> None:
        entered.set()
        assert release.wait(10)

    def finish_draft(_result: object) -> None:
        draft.finish_sketch()
        observed.append(
            (
                window.active_sketch_dialog() is draft,
                len(draft.canvas.entities),
                draft.result_sketch is None,
                draft.status_label.text(),
            )
        )

    unit.result_ready.connect(finish_draft)
    assert unit.submit(work, operation="test-draft-handoff", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed[0][:3] == (True, 1, True)
    assert "应用正在执行" in observed[0][3]
    unit.result_ready.disconnect(finish_draft)
    loaded = window.loaded_document()
    assert loaded is not None
    draft.finish_sketch()
    qtbot.waitUntil(lambda: bool(loaded.document.commands), timeout=10000)
    assert len(loaded.document.commands) == 1


def test_open_during_worker_operation_reports_rejection(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    original = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    entered, release = Event(), Event()

    def blocking_work() -> None:
        entered.set()
        assert release.wait(10)

    assert unit.submit(blocking_work, operation="test-open", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        window.open_document_path(tmp_path / "other.my3d")
        assert "操作正在执行" in window.status_command.text()
        assert session.active is original and session.documents == (original,)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)


@pytest.mark.parametrize("entry", ["home", "home-drawing", "menu", "menu-standard"])
def test_new_document_waits_while_result_notification_is_in_progress(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.drawing_templates import DrawingTemplateChoiceDialog
    from mycad.ui.new_document_dialog import NewDocumentDialog

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    original = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    observed: list[tuple[tuple[object, ...], str]] = []

    def unexpected_dialog(_self: DrawingTemplateChoiceDialog) -> int:
        pytest.fail("template selection must wait for the original result")

    monkeypatch.setattr(DrawingTemplateChoiceDialog, "exec", unexpected_dialog)

    def unexpected_new_dialog(_self: NewDocumentDialog) -> int:
        pytest.fail("document creation must wait for the original result")

    monkeypatch.setattr(NewDocumentDialog, "exec", unexpected_new_dialog)

    def request_new(_result: object) -> None:
        if entry == "home":
            window.start_page.create_requested.emit("part")
        elif entry == "home-drawing":
            window.start_page.create_requested.emit("drawing")
        elif entry == "menu-standard":
            window.act_new.trigger()
        else:
            window.act_new_drawing.trigger()
        observed.append((session.documents, window.status_command.text()))

    unit.result_ready.connect(request_new)
    assert unit.submit(lambda: None, operation="test-new", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed[0][0] == (original,)
    assert "操作完成后" in observed[0][1]


def test_document_switch_waits_for_followup_worker_started_by_callback(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    second = window.new_session_document("part")
    window.activate_session_document(first.loaded.document.document_id)
    unit = window.execution_unit
    assert unit is not None
    entered, release = Event(), Event()
    queued = False

    def followup() -> None:
        entered.set()
        assert release.wait(10)

    def busy_changed(busy: bool) -> None:
        nonlocal queued
        if not busy and not queued:
            queued = True
            window.activate_session_document(second.loaded.document.document_id)

    def complete(_result: object) -> None:
        assert unit.submit(followup, operation="followup", session_id=unit.session_id)

    unit.busy_changed.connect(busy_changed)
    assert unit.submit(
        lambda: None, operation="first", session_id=unit.session_id, on_complete=complete
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=10000)
        assert session.active is first
    finally:
        release.set()
    qtbot.waitUntil(lambda: session.active is second, timeout=10000)


def test_workspace_switch_does_not_precede_result_callback(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    sketch = window.new_session_document("sketch")
    part = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    seen: list[tuple[object, str]] = []

    def switch(_result: object) -> None:
        window.workspace_tabs.activate("sketch")

    def complete(_result: object) -> None:
        seen.append((session.active, window.active_workspace))

    unit.result_ready.connect(switch)
    assert unit.submit(
        lambda: None, operation="test-workspace", session_id=unit.session_id, on_complete=complete
    )
    qtbot.waitUntil(lambda: bool(seen), timeout=10000)
    assert seen == [(part, "model")]
    window.workspace_tabs.activate("sketch")
    assert session.active is sketch


def test_part_sketch_does_not_start_during_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    observed: list[tuple[bool, str]] = []

    def start_sketch(_result: object) -> None:
        window.act_sketch.trigger()
        observed.append((window.part_sketch_task is not None, window.status_command.text()))

    unit.result_ready.connect(start_sketch)
    assert unit.submit(lambda: None, operation="test-sketch", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed[0][0] is False
    assert "等待当前操作" in observed[0][1]


def test_existing_part_sketch_tool_does_not_change_during_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    observed: list[bool] = []

    def change_tool(_result: object) -> None:
        window.act_part_rectangle.trigger()
        observed.append(task.rectangle_button.isChecked())

    unit.result_ready.connect(change_tool)
    assert unit.submit(lambda: None, operation="test-tool", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [False]
    window.act_part_rectangle.trigger()
    assert task.rectangle_button.isChecked()


def test_part_sketch_button_does_not_change_tool_during_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    observed: list[bool] = []

    def change_tool(_result: object) -> None:
        task.rectangle_button.click()
        observed.append(task.rectangle_button.isChecked())

    unit.result_ready.connect(change_tool)
    assert unit.submit(lambda: None, operation="test-sketch-button", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [False]
    task.rectangle_button.click()
    assert task.rectangle_button.isChecked()


def test_part_sketch_point_does_not_commit_during_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    observed: list[int] = []

    def place_second_point(_result: object) -> None:
        task.place_uv((5, 0))
        observed.append(len(task.session.sketch.entities))

    unit.result_ready.connect(place_second_point)
    assert unit.submit(lambda: None, operation="test-sketch-point", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [0]
    task.place_uv((5, 0))
    assert len(task.session.sketch.entities) == 1


@pytest.mark.parametrize("entry", ["global", "button"])
@pytest.mark.parametrize("operation", ["undo", "redo"])
def test_part_sketch_undo_redo_wait_for_result_notification(
    qtbot: QtBot, entry: str, operation: str
) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    if operation == "redo":
        task.undo()
    observed: list[int] = []

    def undo_on_result(_result: object) -> None:
        if entry == "global":
            (window.request_undo if operation == "undo" else window.request_redo)()
        else:
            (task.undo_button if operation == "undo" else task.redo_button).click()
        observed.append(len(task.session.sketch.entities))

    unit.result_ready.connect(undo_on_result)
    assert unit.submit(lambda: None, operation="test-sketch-undo", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [1 if operation == "undo" else 0]
    (task.undo if operation == "undo" else task.redo)()
    assert len(task.session.sketch.entities) == (0 if operation == "undo" else 1)


@pytest.mark.parametrize("operation", ["delete", "construction"])
def test_part_sketch_entity_edit_waits_for_result_notification(
    qtbot: QtBot, operation: str
) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    original = task.session.sketch
    task.selected_entity_id = original.entities[0].entity_id
    observed: list[Sketch] = []

    def edit_on_result(_result: object) -> None:
        (task.delete_selection if operation == "delete" else task.toggle_selected_construction)()
        observed.append(task.session.sketch)

    unit.result_ready.connect(edit_on_result)
    assert unit.submit(lambda: None, operation="test-sketch-edit", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [original]
    (task.delete_selection if operation == "delete" else task.toggle_selected_construction)()
    assert task.session.sketch != original, task.status_label.text()


@pytest.mark.parametrize("operation", ["preview", "confirm"])
def test_part_sketch_preview_and_confirm_wait_for_result_notification(
    qtbot: QtBot, operation: str
) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    entry = window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    if operation == "confirm":
        task.preview()
        assert task.confirm_button.isEnabled()
    observed: list[tuple[bool, int]] = []

    def act_on_result(_result: object) -> None:
        (task.preview_button if operation == "preview" else task.confirm_button).click()
        observed.append((task.confirm_button.isEnabled(), len(entry.loaded.document.commands)))

    unit.result_ready.connect(act_on_result)
    assert unit.submit(lambda: None, operation="test-sketch-submit", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [(operation == "confirm", 0)]
    assert window.part_sketch_task is task
    if operation == "preview":
        task.preview()
    assert task.confirm_button.isEnabled()
    task.confirm()
    assert len(entry.loaded.document.commands) == 1


def test_part_sketch_trim_click_waits_for_result_notification(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    qtbot.waitExposed(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit, view = window.part_sketch_task, window.execution_unit, window.viewport
    assert task is not None and unit is not None and view is not None
    task.lock_plane()
    for first, second in (((0, 0), (10, 0)), ((5, -5), (5, 5))):
        task.select_tool("line")
        task.place_uv(first)
        task.place_uv(second)
    task.select_tool("trim")
    qtbot.wait(100)
    view.fit_world_points(((-2, -7, 0), (12, 7, 0)))
    point = view.project_world_point((8, 0, 0))
    assert point is not None
    position = QPoint(round(point[0]), round(point[1]))
    original = task.session.sketch
    observed: list[Sketch] = []

    def trim_on_result(_result: object) -> None:
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
        observed.append(task.session.sketch)

    unit.result_ready.connect(trim_on_result)
    assert unit.submit(lambda: None, operation="test-sketch-trim", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [original]
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert task.session.sketch != original, task.status_label.text()


def test_part_sketch_spline_finish_waits_for_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("spline")
    for point in ((0, 0), (1, 2), (3, 2), (4, 0)):
        task.place_uv(point)
    observed: list[int] = []

    def finish_on_result(_result: object) -> None:
        task.finish_spline()
        observed.append(len(task.session.sketch.entities))

    unit.result_ready.connect(finish_on_result)
    assert unit.submit(lambda: None, operation="test-spline", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [0]
    task.finish_spline()
    assert len(task.session.sketch.entities) == 1


def test_part_sketch_plane_lock_waits_for_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    observed: list[bool] = []

    def lock_on_result(_result: object) -> None:
        task.lock_button.click()
        observed.append(task.lock_button.isEnabled())

    unit.result_ready.connect(lock_on_result)
    assert unit.submit(lambda: None, operation="test-plane-lock", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [True]
    task.lock_button.click()
    assert not task.lock_button.isEnabled()


def test_part_sketch_constraint_dialog_waits_for_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    observed: list[bool] = []

    def open_on_result(_result: object) -> None:
        task.constraint_button.click()
        observed.append(task.constraint_dialog is not None)

    unit.result_ready.connect(open_on_result)
    assert unit.submit(lambda: None, operation="test-constraint", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [False]
    task.constraint_button.click()
    assert task.constraint_dialog is not None
    task.constraint_dialog.reject()


def test_part_sketch_constraint_acceptance_waits_for_result_notification(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    entry = window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit = window.part_sketch_task, window.execution_unit
    assert task is not None and unit is not None
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    original = task.session.sketch
    constraint = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(original.entities[0].entity_id, "geometry"),),
        7,
        "mm",
    )
    solved = entry.services.kernel.preview_sketch_constraint(original, constraint)
    assert solved.status == "success"
    rejected: list[bool] = []

    def accept_on_result(_result: object) -> None:
        try:
            task.accept_constraint(original, constraint, solved)
        except ValueError:
            rejected.append(True)
        else:
            rejected.append(False)

    unit.result_ready.connect(accept_on_result)
    assert unit.submit(lambda: None, operation="test-constraint-accept", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(rejected), timeout=10000)
    assert rejected == [True]
    assert task.session.sketch == original
    task.accept_constraint(original, constraint, solved)
    assert task.session.sketch != original


def test_part_sketch_drag_release_during_notification_cancels_preview(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    qtbot.waitExposed(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit, view = window.part_sketch_task, window.execution_unit, window.viewport
    assert task is not None and unit is not None and view is not None
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("line")
    task.place_uv((-5, 0))
    task.place_uv((5, 0))
    task.select_tool("select")
    qtbot.wait(100)
    view.fit_world_points(((-7, -3, 0), (7, 4, 0)))
    start, target = view.project_world_point((-5, 0, 0)), view.project_world_point((-5, 2, 0))
    assert start is not None and target is not None
    start_pos = QPoint(round(start[0]), round(start[1]))
    target_pos = QPoint(round(target[0]), round(target[1]))
    original = task.session.sketch
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start_pos)
    observed: list[Sketch] = []
    previews: list[Sketch] = []

    def release_on_result(_result: object) -> None:
        QTest.mouseMove(view, target_pos)
        previews.append(task.displayed_sketch)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target_pos)
        observed.append(task.session.sketch)

    unit.result_ready.connect(release_on_result)
    assert unit.submit(lambda: None, operation="test-sketch-drag", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [original]
    assert previews == [original]
    assert task.displayed_sketch == original
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start_pos)
    QTest.mouseMove(view, target_pos)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target_pos)
    assert task.session.sketch != original


def test_part_sketch_middle_drag_is_forwarded_during_result_notification(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.act_sketch.trigger()
    task, unit, view = window.part_sketch_task, window.execution_unit, window.viewport
    assert task is not None and unit is not None and view is not None
    task.lock_plane()
    task.select_tool("line")
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    consumed: list[bool] = []

    def move_on_result(_result: object) -> None:
        consumed.append(task.eventFilter(view, event))

    unit.result_ready.connect(move_on_result)
    assert unit.submit(lambda: None, operation="test-middle-drag", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(consumed), timeout=10000)
    assert consumed == [False]


def test_part_sketch_edit_does_not_start_during_result_notification(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    entry = window.new_session_document("part")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    entry.loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    unit, panel = window.execution_unit, window.right_panel
    assert unit is not None and panel is not None
    observed: list[bool] = []

    def edit_sketch(_result: object) -> None:
        panel.part_sketch_edit_requested.emit(sketch.sketch_id)
        observed.append(window.part_sketch_task is not None)

    unit.result_ready.connect(edit_sketch)
    assert unit.submit(lambda: None, operation="test-edit-sketch", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [False]
    panel.part_sketch_edit_requested.emit(sketch.sketch_id)
    assert window.part_sketch_task is not None
    window.part_sketch_task.reject()


@pytest.mark.parametrize("entry", ["datum", "bound-hole"])
def test_modeling_tasks_do_not_start_during_result_notification(qtbot: QtBot, entry: str) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    unit, palette = window.execution_unit, window.command_palette
    assert unit is not None and palette is not None
    observed: list[bool] = []

    def start_task(_result: object) -> None:
        if entry == "datum":
            palette.command_activated.emit("datum.plane.create")
            observed.append(window.datum_task is not None)
        else:
            window.action_catalog.get("ui.feature.bound_hole").trigger()
            observed.append(window.bound_hole_task is not None)

    unit.result_ready.connect(start_task)
    assert unit.submit(lambda: None, operation="test-task", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert observed == [False]


def test_three_pages_keep_identity_and_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    window.show()
    tabs = window.workspace_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["平面草图", "工程图", "3D图"]
    pages = tuple(tabs.widget(i) for i in range(3))
    tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    entity = LineEntity("1234567890ab4cde8f001234567890ab", (0, 0), (10, 0))
    draft.canvas.entities.append(entity)
    draft.canvas.selected_entity_ids.add(entity.entity_id)
    draft.canvas.fit_view()
    scale = draft.canvas.view_scale
    assert window.viewport is not None
    window.viewport.set_orientation("left")
    camera = window.viewport.camera_state()
    before = tuple(draft.canvas.entities)
    tabs.activate("drawing")
    assert window.active_workspace == "drawing"
    tabs.activate("model")
    tabs.activate("sketch")
    assert window.active_sketch_dialog() is draft
    assert tuple(draft.canvas.entities) == before
    assert draft.canvas.selected_entity_ids == {entity.entity_id}
    assert draft.canvas.view_scale == scale
    assert window.viewport.camera_state() == camera
    assert window.viewport.orientation() == "left"
    assert tuple(tabs.widget(i) for i in range(3)) == pages
    loaded = window.loaded_document()
    assert loaded is not None
    assert not loaded.document.commands


def test_switch_hides_floating_drafting_dock(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    window.show()
    window.workspace_tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.parameter_dock.setFloating(True)
    draft.parameter_dock.show()
    draft.canvas.grabMouse()
    window.workspace_tabs.activate("drawing")
    assert QWidget.mouseGrabber() is None
    assert not draft.parameter_dock.isVisible()
    window.workspace_tabs.activate("sketch")
    assert draft.parameter_dock.isFloating()
    assert draft.parameter_dock.isVisible()


def test_drawing_workspace_roundtrip_preserves_layer_ucs_and_command_history(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_layers import SketchLayer

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services, document_type="drawing2d")
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    layers = draft.layer_table.add(SketchLayer("detail"))
    draft.request_layer_update(layers, draft.dimension_layer)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and draft.layer_table == layers, timeout=10000)
    draft.layer_combo.setCurrentText("detail")
    draft.origin_fields["X"].setValue(10)
    bar = draft.drawing_command_bar
    for value in ("L", "2,3", "6,3"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    original = tuple(draft.canvas.entities)
    assert len(original) == 1
    draft.canvas.selected_entity_ids.add(original[0].entity_id)
    commands = tuple(loaded.document.commands)

    window.workspace_tabs.activate("drawing")
    window.workspace_tabs.activate("model")
    window.workspace_tabs.activate("sketch")

    assert window.active_sketch_dialog() is draft
    assert draft.origin_fields["X"].value() == 10
    assert draft.canvas.layer_table == layers
    assert draft.canvas.active_layer_name == "detail"
    assert tuple(draft.canvas.entities) == original
    assert draft.canvas.selected_entity_ids == {original[0].entity_id}
    assert tuple(loaded.document.commands) == commands
    for value in ("", "@1,0", "@2,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = draft.canvas.entities[-1]
    assert isinstance(result, LineEntity)
    assert result.start_mm == (7, 3) and result.end_mm == (9, 3)
    assert result.layer_name == "detail"


def test_drawing2d_does_not_offer_solid_projection(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    window.workspace_tabs.activate("drawing")
    assert not window.drawing_workbench.base_action.isEnabled()
    assert window.workspace_tabs.isTabEnabled(2)
    window.workspace_tabs.activate("model")
    assert window.active_workspace == "model"
    assert not window.drawing_workbench.base_action.isEnabled()


def test_global_undo_does_not_edit_hidden_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    window.bind_document(loaded)
    window.workspace_tabs.activate("sketch")
    draft = window.part_sketch_task
    assert draft is not None
    draft.lock_plane()
    draft.select_tool("line")
    draft.place_uv((0, 0))
    draft.place_uv((10, 0))
    before = draft.session.sketch.entities
    assert before
    window.workspace_tabs.activate("drawing")
    window.request_undo()
    qtbot.waitUntil(lambda: not loaded.document.commands)
    assert draft.session.sketch.entities == before
    draft.reject()


def test_switch_during_execution_does_not_restore_wrong_workspace_actions(qtbot: QtBot) -> None:
    from threading import Event

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    unit = window.execution_unit
    assert unit is not None
    released = Event()
    try:
        assert unit.submit(
            lambda: released.wait(5),
            operation="fixture",
            session_id=window.drawing_workbench.session_id,
            on_complete=lambda _result: None,
        )
        window.workspace_tabs.activate("drawing")
        released.set()
        qtbot.waitUntil(lambda: not unit.is_busy)
        assert not any(action.isEnabled() for action in window.orientation_actions.values())
    finally:
        released.set()
