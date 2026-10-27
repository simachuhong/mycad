# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Async results publish only for the currently desired view/source/session."""

from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.drawing_projection import ProjectionResult, ViewBasis
from mycad.ui.drawing_updates import ProjectionUpdates


def test_stale_same_session_result_is_discarded() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "old", {identity: ViewBasis()})
    old = updates.begin()
    assert old is not None
    updates.sync(1, "new", {identity: ViewBasis()})
    result = ProjectionResult(identity, "old", old.requests[0].generation, ())
    assert updates.finish(old, (result,)) == 0
    assert not updates.results
    assert updates.status(identity) == "stale"
    latest = updates.begin()
    assert latest is not None and latest.requests[0].source_fingerprint == "new"
    assert updates.status(identity) == "updating"
    assert (
        updates.finish(
            latest, (ProjectionResult(identity, "new", latest.requests[0].generation, ()),)
        )
        == 1
    )
    assert updates.status(identity) == "clean"


def test_layout_only_sync_does_not_reproject() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    bases = {identity: ViewBasis()}
    updates.sync(1, "source", bases)
    batch = updates.begin()
    assert batch is not None
    result = ProjectionResult(identity, "source", batch.requests[0].generation, ())
    updates.finish(batch, (result,))
    updates.sync(1, "source", bases)
    assert updates.begin() is None
    assert updates.results[identity] is result


def test_deleted_view_and_replaced_session_never_receive_results() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "source", {identity: ViewBasis()})
    batch = updates.begin()
    assert batch is not None
    updates.sync(1, "source", {})
    assert (
        updates.finish(
            batch, (ProjectionResult(identity, "source", batch.requests[0].generation, ()),)
        )
        == 0
    )
    updates.sync(2, "source", {identity: ViewBasis()})
    assert (
        updates.finish(
            batch, (ProjectionResult(identity, "source", batch.requests[0].generation, ()),)
        )
        == 0
    )
    assert not updates.results


def test_failure_preserves_last_result_and_requires_retry() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "old", {identity: ViewBasis()})
    first = updates.begin()
    assert first is not None
    old = ProjectionResult(identity, "old", first.requests[0].generation, ())
    updates.finish(first, (old,))
    updates.sync(1, "new", {identity: ViewBasis()})
    second = updates.begin()
    assert second is not None
    updates.finish(second, (), error="worker failed")
    assert updates.results[identity] is old
    assert updates.status(identity) == "failed"
    assert updates.begin() is None
    updates.retry()
    assert updates.begin() is not None


def test_cancellation_ignores_completion_without_claiming_process_stopped() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "source", {identity: ViewBasis()})
    batch = updates.begin()
    assert batch is not None
    updates.cancel()
    assert (
        updates.finish(
            batch, (ProjectionResult(identity, "source", batch.requests[0].generation, ()),)
        )
        == 0
    )
    assert updates.status(identity) == "stale"
    assert updates.begin() is None
    updates.retry()
    assert updates.begin() is not None


def test_cancel_includes_queued_snapshot_and_latest_request() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "source", {identity: ViewBasis()})
    updates.cancel()
    assert updates.begin() is None
    updates.retry()
    running = updates.begin()
    assert running is not None
    updates.sync(1, "new", {identity: ViewBasis()})
    updates.cancel()
    updates.finish(running, ())
    assert updates.begin() is None


def test_diagnostic_result_keeps_previous_geometry() -> None:
    updates = ProjectionUpdates()
    identity = uuid4()
    updates.sync(1, "old", {identity: ViewBasis()})
    first = updates.begin()
    assert first is not None
    old = ProjectionResult(identity, "old", first.requests[0].generation, ())
    updates.finish(first, (old,))
    updates.sync(1, "new", {identity: ViewBasis()})
    second = updates.begin()
    assert second is not None
    incomplete = ProjectionResult(
        identity, "new", second.requests[0].generation, (), ("unsupported curve",)
    )
    assert updates.finish(second, (incomplete,)) == 0
    assert updates.results[identity] is old
    assert updates.status(identity) == "failed"


def test_workbench_coalesces_model_changes_and_recovers_worker(
    qtbot: "QtBot", monkeypatch: "pytest.MonkeyPatch"
) -> None:
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    from mycad import app
    from mycad.core.drawing import DrawingSheet, DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_projection import DrawingProjectionRequest, DrawingSourceSnapshot
    from mycad.ui.main_window import MainWindow

    class Worker(app.DrawingProjectionWorker):
        def __init__(self) -> None:
            self.calls: list[tuple[DrawingProjectionRequest, ...]] = []
            self.futures: list[Future[tuple[ProjectionResult, ...]]] = []
            self.restarts = 0

        def submit(
            self, snapshot: DrawingSourceSnapshot, requests: tuple[DrawingProjectionRequest, ...]
        ) -> Future[tuple[ProjectionResult, ...]]:
            assert all(r.source_fingerprint == snapshot.source_fingerprint for r in requests)
            self.calls.append(requests)
            future: Future[tuple[ProjectionResult, ...]] = Future()
            self.futures.append(future)
            return future

        def restart(self) -> None:
            self.restarts += 1

        def close(self) -> None:
            pass

        def succeed(self, index: int) -> None:
            self.futures[index].set_result(
                tuple(
                    ProjectionResult(r.view_id, r.source_fingerprint, r.generation, ())
                    for r in self.calls[index]
                )
            )

    worker = Worker()
    monkeypatch.setattr(app, "create_drawing_worker", lambda: worker)
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 30, "size_y": 20, "size_z": 10})
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(sheet))
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    qtbot.waitUntil(lambda: len(worker.calls) == 1)
    for length in (31, 32):
        loaded.bus.execute("feature.box", {"size_x": length, "size_y": 20, "size_z": 10})
        bench.refresh()
    worker.succeed(0)
    qtbot.waitUntil(lambda: len(worker.calls) == 2)
    assert not bench.projections
    assert worker.calls[1][0].source_fingerprint == services.kernel.drawing_source_fingerprint
    worker.succeed(1)
    qtbot.waitUntil(lambda: bench.updates.status(view.view_id) == "clean")
    old = bench.projections[view.view_id]
    loaded.bus.execute("drawing.view.update", {"view_id": str(view.view_id), "scale": 0.5})
    bench.refresh()
    assert len(worker.calls) == 2
    loaded.bus.execute("feature.box", {"size_x": 33, "size_y": 20, "size_z": 10})
    bench.refresh()
    qtbot.waitUntil(lambda: len(worker.calls) == 3)
    worker.futures[2].set_exception(BrokenProcessPool("fixture worker exited"))
    qtbot.waitUntil(lambda: bench.updates.status(view.view_id) == "failed")
    assert bench.projections[view.view_id] is old
    assert worker.restarts == 1
    bench.update_requested()
    qtbot.waitUntil(lambda: len(worker.calls) == 4)
    loaded.bus.execute("drawing.view.delete", {"view_id": str(view.view_id)})
    bench.refresh()
    worker.succeed(3)
    qtbot.waitUntil(lambda: view.view_id not in bench.projections)
    assert not bench.updates.has_pending
