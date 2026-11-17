# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bottom console for the CLI and the active drawing's interactive commands.

In non-drawing environments the tab feeds every submitted line to
``mycad.cli.session.execute_line`` (the pure surface over ``CliSession``)
and appends the returned messages to the read-only output pane. In a drawing,
the existing 2D command handler supplies the input and its own history. Document
ownership stays with the GUI: the tab holds its ``LoadedDocument``, seeds
the dispatch with it, and every ``new``/``open`` replacement routed through
``on_replace_doc`` re-enters the todo-8 lifecycle packing on the window.

The ``quit``/``exit`` sentinel is surface-terminated (documented deviation:
the CLI tab reports it in the pane instead of closing the host window).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from mycad.app import AppServices
from mycad.cli.session import QUIT_SENTINEL, LoadedDocument, execute_line
from mycad.ui.drawing2d_command_bar import Drawing2DCommandBar
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit

PROMPT = ">>> "


@dataclass(frozen=True, slots=True)
class _CliExecutionValue:
    """Immutable CLI result data plus the document handle to bind on success."""

    return_code: int
    messages: tuple[str, ...]
    loaded: LoadedDocument | None


class CliTab(QWidget):
    """CLI bottom-tab: input line → pure ``execute_line`` → read-only output."""

    def __init__(
        self,
        *,
        services: AppServices,
        on_replace_doc: Callable[[LoadedDocument | None], None],
        execution_unit: SerializedExecutionUnit | None = None,
        command_guard: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._services = services
        self._on_replace_doc_cb = on_replace_doc
        self._execution_unit = execution_unit
        self._command_guard = command_guard
        self.current: LoadedDocument | None = None
        self.drawing_bar: Drawing2DCommandBar | None = None
        self._drawing_owner: QWidget | None = None
        self._cli_history = ""

        self.output = QPlainTextEdit(self)
        self.output.setObjectName("cliOutput")
        self.output.setReadOnly(True)
        self.input = QLineEdit(self)
        self.input.setObjectName("cliInput")
        self.input.returnPressed.connect(self._dispatch)
        if execution_unit is not None:
            execution_unit.busy_changed.connect(self._on_execution_busy_changed)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.addWidget(self.output)
        self._layout.addWidget(self.input)

    def set_drawing_bar(self, bar: Drawing2DCommandBar | None) -> None:
        """Show the active drawing's command input in the shared console."""
        if bar is self.drawing_bar:
            return
        previous = self.drawing_bar
        if previous is not None:
            previous.history_line.disconnect(self.append_line)
            previous.history_reset.disconnect(self._restore_drawing_history)
            self._layout.removeWidget(previous)
            previous.hide()
            previous.setParent(self._drawing_owner)
            self._drawing_owner = None
        else:
            self._cli_history = self.output.toPlainText()
        self.drawing_bar = bar
        if bar is None:
            self.output.setPlainText(self._cli_history)
            self.output.show()
            self.input.show()
            return
        self._drawing_owner = bar.parentWidget()
        self.input.hide()
        self.output.hide()
        self.output.setPlainText("\n".join(bar.history))
        self._layout.addWidget(bar, 1)
        bar.history_line.connect(self.append_line)
        bar.history_reset.connect(self._restore_drawing_history)
        bar.show()

    def _restore_drawing_history(self) -> None:
        if self.drawing_bar is not None:
            self.output.setPlainText("\n".join(self.drawing_bar.history))

    # ------------------------------------------------------------------
    # Document binding (window lifecycle)
    # ------------------------------------------------------------------

    def set_services(self, services: AppServices) -> None:
        self._services = services

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Track the GUI-owned document that seeds the next dispatch."""
        self.current = loaded

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self) -> None:
        line = self.input.text()
        self.input.clear()
        if self._execution_unit is None:
            self.dispatch_line(line)
        else:
            self.submit_line(line)

    def submit_line(self, line: str) -> bool:
        """Run a GUI-submitted CLI line on the serialized CAD worker."""
        if self._command_guard is not None:
            reason = self._command_guard(line)
            if reason is not None:
                self.append_line(reason)
                return False
        unit = self._execution_unit
        if unit is None:
            self.dispatch_line(line)
            return True
        if unit.is_busy:
            self.append_line("正在执行上一条命令，请稍候")
            return False
        self.append_line(f"{PROMPT}{line}")
        if line.strip() in ("quit", "exit"):
            self.append_line(repr(QUIT_SENTINEL) + " (hint: use File > Close to exit the app)")
            return True

        current = self.current
        services = self._services
        session_id = unit.session_id

        def execute() -> _CliExecutionValue:
            replaced: list[LoadedDocument | None] = []
            return_code, messages = execute_line(
                line,
                loaded=current,
                services=services,
                on_replace_doc=replaced.append,
            )
            loaded = replaced[-1] if replaced else current
            # Pay the cold-tessellation cost on the worker so the queued UI
            # refresh can consume the immutable cached mesh without stalling.
            if loaded is not None:
                services.kernel.viewport_data()
            return _CliExecutionValue(return_code, tuple(messages), loaded)

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                self.append_line(result.error)
                return
            value = result.value
            if not isinstance(value, _CliExecutionValue):
                self.append_line("命令执行失败：返回结果无效")
                return
            if value.loaded is not self.current:
                self.current = value.loaded
                if value.loaded is not None:
                    self._on_replace_doc_cb(value.loaded)
            for message in value.messages:
                self.append_line(message)

        if not unit.submit(
            execute,
            operation="cli-line",
            session_id=session_id,
            on_complete=finish,
        ):
            self.append_line("文档已切换，命令未提交")
            return False
        self.append_line("执行中…")
        return True

    def _on_execution_busy_changed(self, busy: bool) -> None:
        self.input.setEnabled(not busy)

    def dispatch_line(self, line: str) -> tuple[int, list[str]]:
        """Run one line through the same dispatch path the headless CLI uses.

        The rc is the session exit-code contract, or ``QUIT_SENTINEL`` for
        ``quit``/``exit`` — surfaced in the pane, never closing the window.
        """
        if self._command_guard is not None:
            reason = self._command_guard(line)
            if reason is not None:
                self.append_line(reason)
                return 1, [reason]
        self.append_line(f"{PROMPT}{line}")
        if line.strip() in ("quit", "exit"):
            self.append_line(repr(QUIT_SENTINEL) + " (hint: use File > Close to exit the app)")
            return QUIT_SENTINEL, []
        rc, messages = execute_line(
            line,
            loaded=self.current,
            services=self._services,
            on_replace_doc=self._apply_replace,
        )
        for message in messages:
            self.append_line(message)
        return rc, messages

    def _apply_replace(self, loaded: LoadedDocument | None) -> None:  # noqa: ARG002 (contract)
        """Hand the session-built document back to the window (todo 8 pack)."""
        self._on_replace_doc_cb(loaded)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def append_line(self, message: str) -> None:
        self.output.appendPlainText(message)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Keyboard focus lands on the input line whenever the tab is hit."""
        self.input.setFocus()
        super().keyPressEvent(event)
