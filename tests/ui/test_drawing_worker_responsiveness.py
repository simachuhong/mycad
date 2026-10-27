# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Full neutral DTO IPC uses a process while Qt continues to dispatch events."""

from concurrent.futures import Future
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from mycad.app import build_app, create_drawing_worker, new_document
from mycad.core.drawing_projection import DrawingProjectionRequest, ProjectionResult
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit


def test_production_projection_keeps_gui_responsive(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 24, "size_z": 8})
    worker = create_drawing_worker()
    unit = SerializedExecutionUnit()
    unit.set_session(1)
    completed: list[ExecutionResult] = []
    ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.append(perf_counter()))
    future: list[Future[tuple[ProjectionResult, ...]]] = []

    def snapshot_and_submit() -> object:
        snapshot = services.kernel.drawing_snapshot()
        req = DrawingProjectionRequest(uuid4(), snapshot.source_fingerprint, 1)
        future.append(worker.submit(snapshot, (req,)))
        return future[-1].result(timeout=45)

    timer.start()
    qtbot.wait(100)
    try:
        assert unit.submit(
            snapshot_and_submit,
            operation="drawing-projection",
            session_id=1,
            on_complete=completed.append,
        )
        qtbot.waitUntil(lambda: bool(completed), timeout=60000)
        assert completed[0].error is None
        assert len(ticks) > 3
        assert max(b - a for a, b in zip(ticks, ticks[1:], strict=False)) <= 0.25
    finally:
        timer.stop()
        unit.shutdown(wait_for_running=True)
        worker.close()
