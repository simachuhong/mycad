# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real ``mycad gui`` entry path: services + document must reach the window.

todo 17 regression: ``run_gui`` built the window without services and threw
the fresh document away, so the shipped shell rendered an empty client area
while every test (which constructs ``MainWindow(services=...)`` directly)
stayed green. This module exercises the entry point itself.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app
from mycad.core.persistence import LoadedDocument
from mycad.ui import entry
from mycad.ui.main_window import MainWindow


class _SpyWindow(MainWindow):
    """MainWindow that records how the entry point wired it."""

    instances: ClassVar[list[_SpyWindow]] = []

    def __init__(self, *, services: AppServices | None = None) -> None:
        super().__init__(services=services)
        self.received_services = services
        self.bound_documents: list[LoadedDocument] = []
        _SpyWindow.instances.append(self)

    def bind_document(self, loaded: LoadedDocument) -> None:
        self.bound_documents.append(loaded)
        super().bind_document(loaded)


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def spy_window(monkeypatch: pytest.MonkeyPatch) -> type[_SpyWindow]:
    monkeypatch.setattr(entry, "MainWindow", _SpyWindow)
    _SpyWindow.instances.clear()
    return _SpyWindow


def _fake_exec(self: QApplication) -> int:
    return 0


@pytest.fixture()
def no_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QApplication, "exec", _fake_exec)


def test_run_gui_wires_services_and_a_fresh_document(
    monkeypatch: pytest.MonkeyPatch,
    services: AppServices,
    spy_window: type[_SpyWindow],
    no_event_loop: None,
    qtbot: QtBot,
) -> None:
    monkeypatch.setattr(entry, "build_app", lambda: services)

    assert entry.run_gui() == 0

    assert len(spy_window.instances) == 1
    window = spy_window.instances[0]
    qtbot.addWidget(window)

    assert window.received_services is services
    assert len(window.bound_documents) == 1
    assert window.loaded_document() is window.bound_documents[0]
    assert window.bound_documents[0].document.commands == ()


def test_run_gui_builds_the_five_zones(
    monkeypatch: pytest.MonkeyPatch,
    services: AppServices,
    spy_window: type[_SpyWindow],
    no_event_loop: None,
    qtbot: QtBot,
) -> None:
    monkeypatch.setattr(entry, "build_app", lambda: services)

    entry.run_gui()

    window = spy_window.instances[0]
    qtbot.addWidget(window)

    assert window.viewport is not None
    assert window.centralWidget() is window.viewport
    assert window.command_palette is not None
    assert window.right_panel is not None
    assert window.bottom_tabs is not None
    assert window.cli_tab is not None
    assert window.plan_cards is not None
    assert window.status_command.text() == "空闲"
