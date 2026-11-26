# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum move/copy previews track the pointer without changing the document."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("operation", ["move", "copy"])
@pytest.mark.parametrize("attached", [False, True])
def test_datum_transform_preview_follows_pointer_and_cancels(
    qtbot: QtBot, operation: str, attached: bool
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
    frame = FeatureControlFrame("3" * 32, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        "4" * 32,
        "A",
        (10, 10),
        (0, 0),
        layout_mode="shared",
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0))
        if attached
        else None,
    )
    assert tools.execute(
        "drawing.tolerance.batch",
        {
            "add_datums": [datum.to_mapping()],
            "add_frames": [frame.to_mapping()] if attached else [],
        },
    )
    canvas.set_tool("选择元素")
    editor.transform_buttons[operation].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 40)))
    position = QPointF(canvas.local_to_screen((45, 43)))
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        QPointF(canvas.mapToGlobal(position.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    preview = tools.datum_transform_preview
    assert preview is not None
    assert preview.position_mm == pytest.approx((15, 13), abs=0.15)
    assert preview.target_mm == pytest.approx((0, 0) if attached else (5, 3), abs=0.15)
    assert preview.annotation_attachment == datum.annotation_attachment
    assert services.kernel.drawing_datum_identifiers == (datum,)
    projected = tools.display_datum(preview)
    assert projected is not None
    region = tools.datum_screen_bounds(projected).adjusted(-3, -3, 3, 3).toAlignedRect()
    before_cancel = canvas.grab().toImage().copy(region)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert tools.datum_transform_preview is None
    assert services.kernel.drawing_datum_identifiers == (datum,)
    after_cancel = canvas.grab().toImage().copy(region)
    changed_pixels = sum(
        before_cancel.pixel(x, y) != after_cancel.pixel(x, y)
        for x in range(before_cancel.width())
        for y in range(before_cancel.height())
    )
    assert changed_pixels > 10


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_datum_transform_commit_matches_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
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
    datum = DatumIdentifier("6" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    editor.transform_buttons[operation].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 40)))
    end = canvas.local_to_screen((45, 43))
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(end),
        QPointF(canvas.mapToGlobal(end)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    preview = tools.datum_transform_preview
    assert preview is not None

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    result = services.kernel.drawing_datum_identifiers[-1]
    assert result.position_mm == pytest.approx(preview.position_mm)
    assert result.target_mm == pytest.approx(preview.target_mm)
    assert result.leader_offsets == preview.leader_offsets
    assert len(services.kernel.drawing_datum_identifiers) == (2 if operation == "copy" else 1)
    assert tools.datum_transform_preview is None


def test_datum_drag_shows_preview_before_release(qtbot: QtBot) -> None:
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
    datum = DatumIdentifier("5" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    start = tools.datum_screen_bounds(datum).center().toPoint()
    end = start + canvas.local_to_screen((5, 3)) - canvas.local_to_screen((0, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    position = QPointF(end)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        QPointF(canvas.mapToGlobal(end)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    preview = tools.datum_transform_preview
    assert preview is not None and preview.position_mm == pytest.approx((15, 13), abs=0.15)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tools.datum_transform_preview is None
    assert services.kernel.drawing_datum_identifiers[0].position_mm == pytest.approx(
        preview.position_mm, abs=0.15
    )


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_datum_arrow_base_snaps_to_line_with_association(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("7" * 32, (0, 0), (100, 0))
    perpendicular = LineEntity("a" * 32, (60, -30), (60, 30))
    sketch = Sketch("8" * 32, WorkPlaneFrame.xy(), (line, perpendicular))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        "9" * 32,
        "A",
        (20, 20),
        (20, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.2
        ),
        leader_offsets=((0, -10),),
        leader_auto_normal=True,
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    editor.transform_buttons[operation].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    base = canvas.local_to_screen((20, 0))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        pos=base + QPoint(2, 2),
    )
    off_line = canvas.local_to_screen((70, -10))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=off_line)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert tools.transform_action == operation
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((60, 15)))
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert tools.transform_action == operation
    end = canvas.local_to_screen((70, 0)) + QPoint(0, 3)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.datum_transform_preview
    assert preview is not None
    assert preview.target_mm[0] == pytest.approx(70, abs=0.3)
    assert preview.target_mm[1] == pytest.approx(0)
    assert preview.attachment is not None

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    result = services.kernel.drawing_datum_identifiers[-1]
    assert result.target_mm == pytest.approx(preview.target_mm)
    assert result.position_mm == pytest.approx(preview.position_mm)
    assert result.attachment == preview.attachment
    assert result.leader_auto_normal and result.leader_offsets == datum.leader_offsets
    assert result.attachment is not None
    assert result.attachment.parameter == pytest.approx(0.7, abs=0.003)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_transform_created_datum_after_toolbar_selection_with_real_name_dialog(
    qtbot: QtBot, operation: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("b" * 32, (0, 0), (100, 0))
    sketch = Sketch("c" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    names: list[str] = []

    def accept_name() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        names.append(dialog.textValue())
        dialog.accept()

    tools.begin_mechanical_datum()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 0)))
    QTimer.singleShot(50, accept_name)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 20)))
    assert len(services.kernel.drawing_datum_identifiers) == 1, canvas.message
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.attachment is not None
    editor.transform_buttons[operation].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    tip = QPointF(canvas.local_to_screen(datum.target_mm))
    _, triangle = tools.datum_screen_path(datum)
    assert triangle
    farthest = max(
        (triangle.at(index) for index in range(triangle.size())),
        key=lambda p: (p.x() - tip.x()) ** 2 + (p.y() - tip.y()) ** 2,
    )
    assert (farthest.x() - tip.x()) ** 2 + (farthest.y() - tip.y()) ** 2 > 49
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=farthest.toPoint())
    assert tools.transform_arrow_base
    end = canvas.local_to_screen((70, 0)) + QPoint(0, 3)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.datum_transform_preview
    assert preview is not None, canvas.message
    assert preview.target_mm[0] == pytest.approx(70, abs=0.3)
    assert preview.target_mm[1] == pytest.approx(0)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    if operation == "copy":
        QTimer.singleShot(50, accept_name)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert names == (["A", "B"] if operation == "copy" else ["A"])
    items = services.kernel.drawing_datum_identifiers
    assert len(items) == (2 if operation == "copy" else 1), canvas.message
    assert items[-1].target_mm == pytest.approx(preview.target_mm)
    assert items[-1].position_mm == pytest.approx(preview.position_mm)
    assert items[-1].target_mm[1] == pytest.approx(0)
    assert items[-1].attachment == preview.attachment
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_datum_identifiers == (datum,), timeout=10000)


def test_toolbar_copy_after_moving_attached_datum_uses_arrow_base(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("a" * 32, (0, 0), (120, 0))
    sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        "c" * 32,
        "A",
        (20, 20),
        (20, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 1 / 6
        ),
        layout_mode="shared",
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    editor.transform_buttons["move"].click()
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 0)))
    moved = services.kernel.drawing_datum_identifiers[0]
    assert moved.target_mm == pytest.approx((40, 0), abs=0.2)
    editor.transform_buttons["copy"].click()
    assert tools.transform_action == "copy", canvas.message
    assert tools.transform_arrow_base
    end = canvas.local_to_screen((70, 0)) + QPoint(0, 3)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.datum_transform_preview
    assert preview is not None
    assert preview.target_mm == pytest.approx((70, 0), abs=0.2)

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert len(services.kernel.drawing_datum_identifiers) == 2
    assert services.kernel.drawing_datum_identifiers[-1].target_mm == pytest.approx(
        preview.target_mm
    )


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_toolbar_preselected_datum_uses_arrow_as_base_immediately(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("d" * 32, (0, 0), (100, 0))
    sketch = Sketch("e" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier(
        "f" * 32,
        "A",
        (20, 20),
        (20, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.2
        ),
        layout_mode="shared",
    )
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    editor.transform_buttons[operation].click()
    assert tools.transform_arrow_base
    assert tools.transform_base == pytest.approx((20, 0))
    end = canvas.local_to_screen((70, 0)) + QPoint(0, 3)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.datum_transform_preview
    assert preview is not None and preview.target_mm == pytest.approx((70, 0), abs=0.2)
    assert services.kernel.drawing_datum_identifiers == (datum,)

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    result = services.kernel.drawing_datum_identifiers[-1]
    assert result.target_mm == pytest.approx(preview.target_mm)
    assert result.position_mm == pytest.approx(preview.position_mm)
    assert len(services.kernel.drawing_datum_identifiers) == (2 if operation == "copy" else 1)
