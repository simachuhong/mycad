# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""GUI test environment: offscreen by default, per-test override allowed.

The env gate lives here (conftest, evaluated before test modules import
Qt) rather than pytest.ini: ini cannot set environment variables without
pulling in the pytest-env dependency, and ``setdefault`` preserves the
override hook the todo-9 Windows-native fallback relies on (plan todo 4
spells out this exact mechanism). An explicit ``qapp`` fixture is not
needed — pytest-qt already provides the session-scoped one.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def sandbox_qsettings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the app's settings factory to use an isolated INI file.

    Without this, the roundtrip test would write real $HOME (org/app both
    ``MyCAD``): layout memory must never leak outside the test sandbox.
    The explicit organization/application constructor uses NativeFormat,
    even after setDefaultFormat(IniFormat), so redirecting only IniFormat
    does not isolate the application's actual settings path. Explicit INI
    construction also avoids the Windows native registry backend.
    """
    from PySide6.QtCore import QSettings

    from mycad.ui import main_window

    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(tmp_path / "settings"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    def isolated_settings(organization: str, application: str) -> QSettings:
        return QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, organization, application
        )

    monkeypatch.setattr(main_window, "QSettings", isolated_settings)


@pytest.fixture(autouse=True)
def discard_unsaved_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close-time ``_ask_save_dialog`` opens a blocking modal (exec) that
    hangs offscreen teardown — patch it to "discard" globally (todo 10/13
    root cause, ledger note). Tests exercising the dialog patch it again
    inside themselves; their patch registration runs after this fixture.
    """
    from mycad.ui.main_window import MainWindow

    def _discard(self: MainWindow) -> str:  # noqa: ARG001 (Qt receiver shape)
        return "discard"

    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)


@pytest.fixture
def choose_new_part(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing lifecycle tests explicitly select Part; chooser tests use the real dialog."""
    from mycad.ui.new_document_dialog import NewDocumentDialog

    def choose(dialog: NewDocumentDialog) -> int:
        dialog.part_button.click()
        dialog.create_button.click()
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr(NewDocumentDialog, "exec", choose)
