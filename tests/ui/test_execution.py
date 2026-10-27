# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Serialized GUI execution stays off the UI thread and rejects stale work."""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError
from threading import get_ident
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread
from PySide6.QtGui import QCloseEvent
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.persistence import save_document
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pathlib import Path


def test_executor_runs_work_off_thread_and_delivers_frozen_result_on_ui_thread(
    qtbot: QtBot,
) -> None:
    unit = SerializedExecutionUnit()
    session_id = 4
    unit.set_session(session_id)
    entered = threading.Event()
    release = threading.Event()
    completed: list[tuple[ExecutionResult, int]] = []
    ui_thread = get_ident()

    def action() -> tuple[str, ...]:
        entered.set()
        assert release.wait(5.0)
        return ("finished",)

    assert unit.submit(
        action,
        operation="test-operation",
        session_id=session_id,
        on_complete=lambda result: completed.append((result, get_ident())),
    )
    assert unit.is_busy
    assert not unit.submit(
        lambda: None,
        operation="duplicate",
        session_id=session_id,
    )
    qtbot.waitUntil(entered.is_set)
    release.set()
    qtbot.waitUntil(lambda: bool(completed))

    result, callback_thread = completed[0]
    assert result.operation == "test-operation"
    assert result.value == ("finished",)
    assert callback_thread == ui_thread
    assert not unit.is_busy
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("operation", "changed")
    assert unit.shutdown()


def test_executor_discards_completion_from_previous_document_session(qtbot: QtBot) -> None:
    unit = SerializedExecutionUnit()
    unit.set_session(1)
    entered = threading.Event()
    release = threading.Event()
    delivered: list[ExecutionResult] = []
    ready: list[ExecutionResult] = []
    discarded: list[int] = []
    unit.result_ready.connect(ready.append)
    unit.stale_result_discarded.connect(discarded.append)

    def action() -> str:
        entered.set()
        assert release.wait(5.0)
        return "old result"

    assert unit.submit(
        action,
        operation="old-session",
        session_id=1,
        on_complete=delivered.append,
    )
    qtbot.waitUntil(entered.is_set)
    unit.set_session(2)
    release.set()
    qtbot.waitUntil(lambda: bool(discarded))

    assert delivered == []
    assert ready == []
    assert discarded == [1]
    assert not unit.is_busy
    assert unit.shutdown()


def test_cli_geometry_submission_uses_worker_and_refreshes_bound_viewport(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    tab = window.cli_tab
    viewport = window.viewport
    assert tab is not None and viewport is not None

    assert tab.submit_line("box size_x=10 size_y=10 size_z=10")
    assert not tab.input.isEnabled()
    qtbot.waitUntil(lambda: window.loaded_document() is not None)
    qtbot.waitUntil(lambda: viewport.snapshot_count() == 1)

    loaded = window.loaded_document()
    assert loaded is not None
    assert len(loaded.document.commands) == 1
    assert tab.current is loaded
    assert tab.input.isEnabled()
    assert window.status_dirty.text() == "已修改"

    assert tab.submit_line("cylinder radius=1 height=2 mode=add")
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2)
    qtbot.waitUntil(lambda: viewport.snapshot_count() == 2)
    assert window.status_command.text().startswith("当前：feature.cylinder")

    window.request_undo()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1)
    qtbot.waitUntil(lambda: viewport.snapshot_count() == 1)

    archive = tmp_path / "worker-open.mc.json"
    save_document(loaded.document, archive)
    assert tab.submit_line(f"open {archive}")
    qtbot.waitUntil(lambda: window.loaded_document() is not loaded)
    qtbot.waitUntil(lambda: viewport.snapshot_count() == 1)
    reopened = window.loaded_document()
    assert reopened is not None
    assert tab.current is reopened
    window.close()


def test_history_preview_mesh_is_loaded_off_the_ui_thread(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    window.bind_document(loaded)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    viewport = window.viewport
    unit = window.execution_unit
    assert viewport is not None and unit is not None
    qtbot.waitUntil(lambda: viewport.snapshot_count() == 1)

    worker_threads: list[int] = []
    original = services.kernel.historical_viewport_data

    def tracked_history_read(state_id: str) -> object:
        worker_threads.append(get_ident())
        return original(state_id)

    monkeypatch.setattr(services.kernel, "historical_viewport_data", tracked_history_read)
    ui_thread = get_ident()
    assert window.right_panel is not None
    window.right_panel.structure_selection_changed.emit(0)

    assert unit.is_busy
    qtbot.waitUntil(lambda: viewport.history_preview_ordinal() == 0)
    assert worker_threads and worker_threads[0] != ui_thread


def test_close_is_deferred_until_running_geometry_job_finishes(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    unit = window.execution_unit
    assert unit is not None
    entered = threading.Event()
    release = threading.Event()

    def action() -> str:
        entered.set()
        assert release.wait(5.0)
        return "committed"

    try:
        assert unit.submit(
            action,
            operation="close-semantics",
            session_id=unit.session_id,
        )
        qtbot.waitUntil(entered.is_set)
        busy_close = QCloseEvent()
        window.closeEvent(busy_close)
        assert not busy_close.isAccepted()
        assert "操作完成前无法关闭" in window.status_command.text()

        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy)
        idle_close = QCloseEvent()
        window.closeEvent(idle_close)
        assert idle_close.isAccepted()
    finally:
        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy)
        unit.shutdown()


def test_destroyed_window_joins_active_worker_before_releasing_qthread(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    unit = window.execution_unit
    assert unit is not None
    entered = threading.Event()
    release = threading.Event()
    action_finished = threading.Event()
    thread_finished = threading.Event()
    worker_thread = unit.findChild(QThread, "MyCAD serialized execution")
    assert worker_thread is not None
    worker_thread.finished.connect(thread_finished.set, Qt.ConnectionType.DirectConnection)

    def action() -> str:
        entered.set()
        assert release.wait(5.0)
        action_finished.set()
        return "completed before owner teardown"

    assert unit.submit(action, operation="owner-destroy", session_id=unit.session_id)
    qtbot.waitUntil(entered.is_set)
    release_timer = threading.Timer(0.05, release.set)
    release_timer.start()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    release_timer.join()

    assert action_finished.is_set()
    assert thread_finished.is_set()
