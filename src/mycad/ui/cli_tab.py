# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo-11 bottom-bar CLI tab: same-source command dispatch (F-AGT-05).

No second parser lives here — the tab feeds every submitted line to
``mycad.cli.session.execute_line`` (the pure surface over ``CliSession``)
and appends the returned messages to the read-only output pane. Document
ownership stays with the GUI: the tab holds its ``LoadedDocument``, seeds
the dispatch with it, and every ``new``/``open`` replacement routed through
``on_replace_doc`` re-enters the todo-8 lifecycle packing on the window.

The ``quit``/``exit`` sentinel is surface-terminated (documented deviation:
the CLI tab reports it in the pane instead of closing the host window).
"""

from __future__ import annotations

from collections.abc import Callable
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

PROMPT = ">>> "


class CliTab(QWidget):
    """CLI bottom-tab: input line → pure ``execute_line`` → read-only output."""

    def __init__(
        self,
        *,
        services: AppServices,
        on_replace_doc: Callable[[LoadedDocument | None], None],
    ) -> None:
        super().__init__()
        self._services = services
        self._on_replace_doc_cb = on_replace_doc
        self.current: LoadedDocument | None = None

        self.output = QPlainTextEdit(self)
        self.output.setObjectName("cliOutput")
        self.output.setReadOnly(True)
        self.input = QLineEdit(self)
        self.input.setObjectName("cliInput")
        self.input.returnPressed.connect(self._dispatch)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.output)
        layout.addWidget(self.input)

    # ------------------------------------------------------------------
    # Document binding (window lifecycle)
    # ------------------------------------------------------------------

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Track the GUI-owned document that seeds the next dispatch."""
        self.current = loaded

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self) -> None:
        line = self.input.text()
        self.input.clear()
        self.dispatch_line(line)

    def dispatch_line(self, line: str) -> tuple[int, list[str]]:
        """Run one line through the same dispatch path the headless CLI uses.

        The rc is the session exit-code contract, or ``QUIT_SENTINEL`` for
        ``quit``/``exit`` — surfaced in the pane, never closing the window.
        """
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
