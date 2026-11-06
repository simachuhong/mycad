# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""An empty engineering page exposes a usable source-to-view workflow."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document, new_workspace_document
from mycad.ui.main_window import MainWindow


def test_generate_entry_creates_sheet_and_starts_canvas_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.show()
    window.workspace_tabs.activate("drawing")
    assert bench.start_page.isVisible()
    assert bench.generate_button.isEnabled()
    QTest.mouseClick(bench.generate_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bench.placement is not None)
    assert len(services.kernel.drawing_state.sheets) == 1
    assert bench.canvas.isVisible()
    assert not bench.start_page.isVisible()
    bench.cancel_placement()
    assert bench.start_page.isVisible()


def test_empty_model_explains_source_and_can_navigate_to_sketch(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    assert bench.start_page.isVisible()
    assert not bench.generate_button.isEnabled()
    assert "拉伸" in bench.start_description.text()
    bench.begin_placement()
    assert not services.kernel.drawing_state.sheets
    assert bench.placement is None
    QTest.mouseClick(bench.sketch_button, Qt.MouseButton.LeftButton)
    assert window.active_workspace == "model"
    assert window.part_sketch_task is not None
    window.part_sketch_task.reject()
    window.workspace_tabs.activate("drawing")
    QTest.mouseClick(bench.model_button, Qt.MouseButton.LeftButton)
    assert window.active_workspace == "model"


def test_drawing2d_explains_model_requirement_in_visible_page(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    assert bench.start_page.isVisible()
    assert "独立二维图" in bench.start_description.text()
    assert not bench.generate_button.isEnabled()
    assert bench.open_button.isEnabled()


def test_source_selection_is_disabled_without_document_session(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_workspace_document(services, kind="drawing"))
    assert not window.drawing_workbench.choose_source_button.isEnabled()
    assert "不支持" in window.drawing_workbench.choose_source_button.toolTip()
