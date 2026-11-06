# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""One serialized Qt worker for long GUI-side model operations.

The worker receives plain callables that touch core/geom state only. Results
cross back as frozen DTOs through a queued Qt signal; completion callbacks
therefore run in the owning UI thread. Running OCCT work is never interrupted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

__all__ = ["ExecutionResult", "SerializedExecutionUnit"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Immutable completion envelope; ``value`` contains non-Qt data only."""

    request_id: int
    session_id: int
    operation: str
    value: object | None
    error: str | None
    error_detail: str | None = None


@dataclass(frozen=True, slots=True)
class _ExecutionRequest:
    request_id: int
    session_id: int
    operation: str
    action: Callable[[], object]


class _ExecutionWorker(QObject):
    """Thread-affine receiver for the one-at-a-time request signal."""

    finished = Signal(object)

    @Slot(object)
    def run(self, request: _ExecutionRequest) -> None:
        """Execute one operation and send an immutable result envelope."""
        try:
            result = ExecutionResult(
                request_id=request.request_id,
                session_id=request.session_id,
                operation=request.operation,
                value=request.action(),
                error=None,
            )
        except Exception as exc:
            message = str(exc).split("\n", maxsplit=1)[0]
            result = ExecutionResult(
                request_id=request.request_id,
                session_id=request.session_id,
                operation=request.operation,
                value=None,
                error=f"{type(exc).__name__}: {message}",
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        self.finished.emit(result)


class SerializedExecutionUnit(QObject):
    """A single-thread executor bound to one active document session.

    Only one request may run at a time. A second submission is rejected with
    ``False``; callers can show busy feedback without building a hidden queue.
    Changing the session invalidates any in-flight completion so it cannot
    rebind a newer document. The operation itself is allowed to finish.
    """

    busy_changed = Signal(bool)
    result_ready = Signal(object)
    stale_result_discarded = Signal(int)
    result_delivery_finished = Signal()
    _request_ready = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._thread.setObjectName("MyCAD serialized execution")
        self._worker = _ExecutionWorker()
        self._worker.moveToThread(self._thread)
        self._request_ready.connect(
            self._worker.run,
            Qt.ConnectionType.QueuedConnection,
        )
        self._worker.finished.connect(
            self._receive_result,
            Qt.ConnectionType.QueuedConnection,
        )
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()
        self._session_id = 0
        self._request_id = 0
        self._busy = False
        self._result_delivery_depth = 0
        self._idle_notification_depth = 0
        self._completion_callback_depths: list[int] = []
        self._operation: str | None = None
        self._closed = False
        self._callbacks: dict[int, Callable[[ExecutionResult], None]] = {}

    @property
    def is_busy(self) -> bool:
        """Whether an operation is running on the serialized worker."""
        return self._busy

    @property
    def is_delivering_result(self) -> bool:
        """Whether completion signals and their callback are being delivered."""
        return self._result_delivery_depth > 0

    @property
    def is_notifying_idle(self) -> bool:
        """Whether synchronous listeners are handling the idle notification."""
        return self._idle_notification_depth > 0

    @property
    def is_notifying_result(self) -> bool:
        """Whether result signals, rather than the owning callback, are running."""
        return self.is_delivering_result and not (
            self._completion_callback_depths
            and self._completion_callback_depths[-1] == self._result_delivery_depth
        )

    @property
    def session_id(self) -> int:
        """Current document generation accepted by completion delivery."""
        return self._session_id

    @property
    def operation(self) -> str | None:
        """The running request's label, used to distinguish previews from writes."""
        return self._operation

    def set_session(self, session_id: int) -> None:
        """Advance the bound session; completions from prior IDs are dropped."""
        self._session_id = session_id

    def submit(
        self,
        action: Callable[[], object],
        *,
        operation: str,
        session_id: int,
        on_complete: Callable[[ExecutionResult], None] | None = None,
    ) -> bool:
        """Start work if idle; reject duplicate or post-shutdown requests."""
        if (
            self._busy
            or self._closed
            or self.is_notifying_idle
            or self.is_notifying_result
            or session_id != self._session_id
        ):
            return False
        self._request_id += 1
        request = _ExecutionRequest(
            request_id=self._request_id,
            session_id=session_id,
            operation=operation,
            action=action,
        )
        if on_complete is not None:
            self._callbacks[request.request_id] = on_complete
        self._busy = True
        self._operation = operation
        self.busy_changed.emit(True)
        self._request_ready.emit(request)
        return True

    @Slot(object)
    def _receive_result(self, value: object) -> None:
        """Reset busy state and deliver the result on this object's thread."""
        if not isinstance(value, ExecutionResult):
            return
        self._result_delivery_depth += 1
        try:
            self._busy = False
            self._operation = None
            self._idle_notification_depth += 1
            try:
                self.busy_changed.emit(False)
            finally:
                self._idle_notification_depth -= 1
            callback = self._callbacks.pop(value.request_id, None)
            if value.session_id != self._session_id:
                self.stale_result_discarded.emit(value.session_id)
                return
            self.result_ready.emit(value)
            if callback is not None:
                self._completion_callback_depths.append(self._result_delivery_depth)
                try:
                    callback(value)
                finally:
                    self._completion_callback_depths.pop()
        finally:
            self._result_delivery_depth -= 1
            if self._result_delivery_depth == 0:
                self.result_delivery_finished.emit()

    def shutdown(self, *, wait_for_running: bool = False) -> bool:
        """Stop the worker, optionally waiting for an active operation to finish.

        Normal window-close handling uses the default so the close can be
        rejected while work is active. Object-owner teardown sets
        ``wait_for_running`` to join safely without interrupting OCCT work.
        """
        if self._busy and not wait_for_running:
            return False
        if self._closed:
            return not self._thread.isRunning() or self._thread.wait()
        self._closed = True
        self._thread.quit()
        return self._thread.wait()
