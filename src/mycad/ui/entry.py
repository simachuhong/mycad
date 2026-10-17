# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``mycad gui`` body.

Lives inside the ui package so the Qt import sits under the
tests/test_scope_audit.py ``src/mycad/ui/`` carve-out, while the CLI
dispatch branch stays Qt-free.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow


def run_gui() -> int:
    """Compose services, seed one fresh document, run the window's loop."""
    qapp = QApplication.instance() or QApplication([])
    services = build_app()
    # Fresh document; kernel reset stays exclusive to mycad.app.new_document.
    _ = new_document(services)
    window = MainWindow()
    window.show()
    return qapp.exec()
