# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Move and copy selected datums using the actual modification toolbar."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_toolbar_transforms_selected_datum(
    qtbot: QtBot, monkeypatch: MonkeyPatch, operation: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    datum = DatumIdentifier("d" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert tools.selected_id == datum.datum_id

    def choose_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", choose_name)
    assert editor.transform_buttons[operation].isEnabled()
    editor.transform_buttons[operation].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 3)))
    items = services.kernel.drawing_datum_identifiers
    assert len(items) == (1 if operation == "move" else 2)
    assert items[-1].position_mm == pytest.approx((15, 13), abs=0.15)
    assert items[-1].label == ("A" if operation == "move" else "B")
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == items, timeout=10000)


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_toolbar_selects_datum_after_starting_transform(
    qtbot: QtBot, monkeypatch: MonkeyPatch, operation: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier("e" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")

    def choose_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", choose_name)
    editor.transform_buttons[operation].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 3)))
    items = services.kernel.drawing_datum_identifiers
    assert len(items) == (1 if operation == "move" else 2)
    assert items[-1].position_mm == pytest.approx((15, 13), abs=0.15)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_drag_unselected_datum_moves_whole_object(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier("f" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    start = tools.datum_screen_bounds(datum).center().toPoint()
    end = start + canvas.local_to_screen((5, 3)) - canvas.local_to_screen((0, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=30)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == pytest.approx((15, 13), abs=0.15)
    assert moved.target_mm == pytest.approx((5, 3), abs=0.15)
