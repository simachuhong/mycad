# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise datum movement through real drawing controls."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.ui.main_window import MainWindow


def test_selected_datum_moves_through_drawing_command_bar(qtbot: QtBot) -> None:
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
    datum = DatumIdentifier("1" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert tools.selected_id == datum.datum_id
    for command in ("MOVE", "0,0", "5,3"):
        editor.drawing_command_bar.input.setText(command)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert services.kernel.drawing_datum_identifiers[0].position_mm == (15, 13)


@pytest.mark.parametrize("attached", [False, True])
def test_selected_datum_moves_as_a_whole_by_dragging(qtbot: QtBot, attached: bool) -> None:
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
    frame = FeatureControlFrame("3" * 32, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        "2" * 32,
        "A",
        (10, 10),
        (0, 0),
        layout_mode="shared",
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0))
        if attached
        else None,
    )
    assert tools.execute is not None
    assert tools.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [frame.to_mapping()] if attached else [],
        },
    )
    canvas.set_tool("选择元素")
    start = tools.datum_screen_bounds(datum).center().toPoint()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
    assert tools.selected_id == datum.datum_id
    end = canvas.local_to_screen((15, 13)) - canvas.local_to_screen((10, 10)) + start
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=30)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.position_mm == pytest.approx((15, 13))
    assert moved.target_mm == pytest.approx((0, 0) if attached else (5, 3))
    assert moved.annotation_attachment == datum.annotation_attachment
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (moved,), timeout=10000)
