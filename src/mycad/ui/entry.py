# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``mycad gui`` body.

Lives inside the ui package so the Qt import sits under the
tests/test_scope_audit.py ``src/mycad/ui/`` carve-out, while the CLI
dispatch branch stays Qt-free.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mycad.app import build_app
from mycad.ui.document_session import DocumentSession
from mycad.ui.input_method import prepare_input_method
from mycad.ui.main_window import MainWindow


def run_gui(path: Path | None = None) -> int:
    """Compose services and open the start page without creating a document."""
    if QApplication.instance() is None:
        prepare_input_method()
    qapp = QApplication.instance() or QApplication([])
    services = build_app()
    window = MainWindow(services=services, document_session=DocumentSession())
    window.show_start_page()
    window.show()
    if path is not None:
        QTimer.singleShot(0, partial(window.open_document_path, path.absolute()))
    return qapp.exec()
