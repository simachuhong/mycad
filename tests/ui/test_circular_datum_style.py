# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Round datum identifiers are editable and drawn as circles with a bar."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.formats.dxf_preview import prepare_dxf_output_preview
from mycad.ui.main_window import MainWindow


def test_selected_datum_can_change_to_circular_style(
    qtbot: QtBot, monkeypatch: MonkeyPatch
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
    datum = DatumIdentifier("a" * 32, "A", (10, 20), (10, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )

    def choose(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "圆圈", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    window.act_datum_symbol_style.trigger()
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.symbol_style == "circle"
    bounds = tools.datum_screen_bounds(changed)
    assert bounds.width() == bounds.height()
    connector, bar = tools.circular_datum_screen_geometry(changed)
    assert len(connector) == len(bar) == 2
    assert canvas.grab().toImage().width() > 0
    snapshots = tools.graphic_datum_export_snapshots((changed,))
    output = prepare_dxf_output_preview(
        services.kernel, tolerance_graphics=True, graphic_datum_snapshots=snapshots
    )
    assert b"CIRCLE" in output.dxf_bytes and b"HATCH" in output.dxf_bytes
    tools.selected_id = None
    tools.selected_ids.clear()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=bar[0].toPoint())
    assert tools.selected_id == datum.datum_id

    def choose_rectangle(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "矩形", True

    monkeypatch.setattr(QInputDialog, "getItem", choose_rectangle)
    window.act_datum_symbol_style.trigger()
    assert services.kernel.drawing_datum_identifiers[0].symbol_style == "rectangle"
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (changed,), timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_circular_datum_toolbar_transform_keeps_style(
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
    datum = DatumIdentifier(
        "b" * 32, "A", (10, 20), (10, 0), layout_mode="shared", symbol_style="circle"
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    editor.transform_buttons[operation].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 0)))
    result = services.kernel.drawing_datum_identifiers[-1]
    assert result.symbol_style == "circle"
    assert result.target_mm == pytest.approx((30, 0), abs=0.2)
    assert len(services.kernel.drawing_datum_identifiers) == (2 if operation == "copy" else 1)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_circular_datum_keeps_frame_attachment(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
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
    frame = FeatureControlFrame("c" * 32, (ToleranceRow("position", 0.1, 2),), (10, 0))
    datum = DatumIdentifier(
        "d" * 32,
        "A",
        (10, 20),
        (10, 0),
        layout_mode="shared",
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
    )
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )

    def choose(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "圆圈", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    window.act_datum_symbol_style.trigger()
    changed = services.kernel.drawing_datum_identifiers[0]
    assert changed.symbol_style == "circle"
    assert changed.annotation_attachment == datum.annotation_attachment
    connector, bar = tools.circular_datum_screen_geometry(changed)
    assert connector[-1] == canvas.local_to_screen_precise((10, 0))
    assert (bar[0] + bar[1]) / 2 == connector[-1]
