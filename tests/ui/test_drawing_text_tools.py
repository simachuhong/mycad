# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing text uses document commands and real canvas coordinates."""

from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.ui.sketch_editor import SketchCanvas


@pytest.mark.parametrize("command", ["CHAMFER", "FILLET"])
def test_corner_trim_option_takes_priority_over_mtext_alias(qtbot: QtBot, command: str) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.text_tools is not None
    bar = editor.drawing_command_bar
    for value in (command, "T", "N"):
        bar.input.setText(value)
        bar.submit()
    assert not editor.canvas.text_tools.pending
    assert editor.canvas.tool == ("二维倒角" if command == "CHAMFER" else "二维圆角")
    assert not (
        editor.canvas.chamfer_trim if command == "CHAMFER" else editor.canvas.circle_fillet_trim
    )
    editor.canvas.set_tool("选择元素")
    bar.input.setText("T")
    bar.submit()
    assert editor.canvas.text_tools.pending


def test_text_placement_cancel_and_one_commit(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyleTable
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    tools.sync((), TextStyleTable())
    calls: list[tuple[str, dict[str, object]]] = []
    tools.execute = lambda command, params: calls.append((command, params)) is None
    assert tools.begin("text")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 20)))
    tools.editor.setPlainText("中文 ABC")
    QTest.keyClick(tools.editor, Qt.Key.Key_Escape)
    assert not calls
    assert tools.begin("mtext")
    tools.place((10, 20))
    tools.editor.setPlainText("中文 ABC\n第二行")
    QTest.keyClick(tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(calls) == 1
    assert calls[0][0] == "drawing.text.add"
    assert calls[0][1]["text"] == "中文 ABC\n第二行"
    assert calls[0][1]["position_mm"] == [10.0, 20.0]


def test_text_selection_and_transform_use_saved_object(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "ABC", (0, 0))
    tools.sync((item,), TextStyleTable())
    assert tools.hit((1, 1)) is not None
    tools.selected_ids = {item.text_id}
    calls: list[tuple[str, dict[str, object]]] = []
    tools.execute = lambda command, params: calls.append((command, params)) is None
    assert tools.transform("move", (0, 0), (10, 5))
    updates = calls[0][1]["update"]
    assert isinstance(updates, list)
    assert updates[0]["position_mm"] == [10.0, 5.0]


def test_rotated_drawing_text_display_selection_and_operations(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "ABC", (20, 0))
    tools.sync((item,), TextStyleTable())
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    assert tools.hit((1, -21)) == item
    projected = tools.display_text(item)
    assert projected is not None
    assert projected.position_mm == pytest.approx((0, -20))
    assert projected.rotation_deg == pytest.approx(-90)
    bounds = tools.screen_bounds(projected).adjusted(-2, -2, 2, 2)
    tools.select_box(bounds.topLeft(), bounds.bottomRight(), Qt.KeyboardModifier.NoModifier)
    assert tools.selected_ids == {item.text_id}
    tools.selected_ids = {item.text_id}
    calls: list[tuple[str, dict[str, object]]] = []
    tools.execute = lambda command, params: calls.append((command, params)) is None
    assert tools.transform("move", (0, 0), (5, 7))
    updates = calls[-1][1]["update"]
    assert isinstance(updates, list)
    assert updates[0]["position_mm"] == pytest.approx([13, 5])
    assert tools.begin("text")
    tools.place((5, 7))
    tools.editor.setPlainText("new")
    tools.commit()
    assert calls[-1][1]["position_mm"] == pytest.approx([-7, 5])
    off_plane = WorkPlaneFrame((0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    canvas.set_background_sketches((), off_plane)
    assert tools.display_text(item) is None
    assert tools.hit((1, 1)) is None
    tools.select_box(QPointF(0, 0), QPointF(600, 400), Qt.KeyboardModifier.NoModifier)
    assert not tools.selected_ids
    assert not tools.begin("text")


def test_rotated_text_clipboard_places_in_drawing_coordinates(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "ABC", (20, 0))
    tools.sync((item,), TextStyleTable())
    canvas.set_background_sketches((), WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1)))
    tools.selected_ids = {item.text_id}
    calls: list[tuple[str, dict[str, object]]] = []
    tools.execute = lambda command, params: calls.append((command, params)) is None
    try:
        assert tools.copy() and tools.begin_paste()
        assert tools.place_paste((5, 7))
        additions = calls[-1][1]["add"]
        assert isinstance(additions, list)
        assert additions[0]["position_mm"] == pytest.approx([-7, 5])
    finally:
        QApplication.clipboard().clear()


def test_text_move_preserves_unbounded_rotation_in_rotated_plane(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    item = DrawingText(uuid4().hex, "ABC", (20, 0), rotation_deg=390)
    tools.sync((item,), TextStyleTable())
    canvas.set_background_sketches((), WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1)))
    tools.selected_ids = {item.text_id}
    calls: list[tuple[str, dict[str, object]]] = []
    tools.execute = lambda command, params: calls.append((command, params)) is None
    assert tools.transform("move", (0, 0), (5, 7))
    updates = calls[-1][1]["update"]
    assert isinstance(updates, list)
    assert updates[0]["rotation_deg"] == pytest.approx(390)


def test_rotated_legacy_text_clipboard_preserves_sketch_frame(qtbot: QtBot) -> None:
    import json

    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME, DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    canvas.set_background_sketches((), frame)
    item = DrawingText(uuid4().hex, "ABC", (20, 0))
    sketch = Sketch(uuid4().hex, frame, (LineEntity(uuid4().hex, (0, -20), (2, -20)),))
    mime = QMimeData()
    mime.setData(
        TEXT_CLIPBOARD_MIME,
        json.dumps(
            {
                "format": "mycad-text",
                "version": 1,
                "texts": [item.to_mapping()],
                "styles": TextStyleTable().to_mapping(),
                "sketch": sketch.to_state_mapping(),
            }
        ).encode(),
    )
    QApplication.clipboard().setMimeData(mime)
    pasted: list[tuple[Sketch, tuple[DrawingText, ...]]] = []
    tools.paste_commit = lambda source, texts, _styles, _images, _dims: (
        pasted.append((source, texts)) is None
    )
    try:
        assert tools.begin_paste() and tools.place_paste((5, 7))
        result, texts = pasted[0]
        assert result.frame == frame
        assert isinstance(result.entities[0], LineEntity)
        assert result.entities[0].start_mm == pytest.approx((5, 7))
        assert texts[0].position_mm == pytest.approx((-7, 5))
    finally:
        QApplication.clipboard().clear()


def test_rotated_legacy_text_paste_survives_reopen_and_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    import json
    from pathlib import Path

    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME
    from mycad.ui.main_window import MainWindow

    def skip_paint(*_args: object, **_kwargs: object) -> None:
        pass

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", skip_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.text_tools
    assert tools is not None
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: frame)
    editor.canvas.set_background_sketches((), frame)
    text = DrawingText(uuid4().hex, "ABC", (20, 0))
    sketch = Sketch(uuid4().hex, frame, (LineEntity(uuid4().hex, (0, -20), (2, -20)),))
    mime = QMimeData()
    mime.setData(
        TEXT_CLIPBOARD_MIME,
        json.dumps(
            {
                "format": "mycad-text",
                "version": 1,
                "texts": [text.to_mapping()],
                "styles": TextStyleTable().to_mapping(),
                "sketch": sketch.to_state_mapping(),
            }
        ).encode(),
    )
    QApplication.clipboard().setMimeData(mime)
    try:
        assert tools.begin_paste() and tools.place_paste((5, 7))
        assert len(services.kernel.sketches) == len(services.kernel.drawing_texts) == 1
        stored = services.kernel.sketches[0]
        assert stored.frame == frame
        assert isinstance(stored.entities[0], LineEntity)
        assert stored.entities[0].start_mm == pytest.approx((5, 7))
        assert services.kernel.drawing_texts[0].position_mm == pytest.approx((-7, 5))
        path = cast("Path", tmp_path) / "text-rotated.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.sketches == (stored,)
        assert len(services.kernel.drawing_texts) == 1
        reopened.bus.undo_operation()
        assert services.kernel.sketches == services.kernel.drawing_texts == ()
        reopened.bus.redo_operation()
        assert services.kernel.sketches == (stored,) and len(services.kernel.drawing_texts) == 1
    finally:
        QApplication.clipboard().clear()


def test_main_window_text_history_and_cli(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.text_tools
    assert tools is not None
    before = loaded.document.command_count
    editor.drawing_command_bar.input.setText('TEXT 10,20 3.5 0 "中文 ABC"')
    editor.drawing_command_bar.submit()
    assert tools.texts, f"{tools.warning.text()} | {editor.canvas.message}"
    assert loaded.document.command_count == before + 1
    assert tools.texts[0].text == "中文 ABC"
    loaded.bus.undo_operation()
    tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
    assert not tools.texts
    loaded.bus.redo_operation()
    tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
    assert tools.texts[0].text == "中文 ABC"


def test_mixed_saved_text_and_geometry_move_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    text = DrawingText(uuid4().hex, "ABC", (0, 10))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    tools = editor.canvas.text_tools
    assert tools is not None
    tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    editor.canvas.begin_transform("move")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 5))
    )
    qtbot.waitUntil(lambda: not window.execution_unit or not window.execution_unit.is_busy)
    assert services.kernel.drawing_texts[0].position_mm == (5, 15)
    loaded.bus.undo_operation()
    assert services.kernel.sketches[0].entities[0] == line
    assert services.kernel.drawing_texts == (text,)


def test_pending_inline_text_blocks_save_and_keeps_edit(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.text_tools is not None
    tools = editor.canvas.text_tools
    tools.begin("text")
    tools.place((0, 0))
    tools.editor.setPlainText("尚未提交")
    window.act_save.trigger()
    assert tools.editor.toPlainText() == "尚未提交"
    assert tools.pending
    assert "文字尚未提交" in window.status_command.text()
    from mycad.core.sketch import LineEntity

    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (10, 0))]
    editor.finish_sketch()
    assert editor.result_sketch is None
    assert tools.pending
    window.request_undo()
    assert tools.pending


def test_text_preview_and_degenerate_transform_remain_editable(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    tools = DrawingTextTools(canvas)
    text = DrawingText(uuid4().hex, "ABC", (0, 0))
    tools.sync((text,), TextStyleTable())
    tools.selected_ids = {text.text_id}
    tools.edit_selected()
    assert tools.editor.toPlainText() == "ABC"
    canvas.grab()  # Includes an unchanged text preview before any keystroke.
    tools.cancel()
    assert not tools.transform("scale", (0, 0), (0, 0))
    assert "positive" in canvas.message
    assert not tools.transform("mirror", (0, 0), (0, 0))
    assert "distinct" in canvas.message


def test_mixed_text_and_draft_undo_routes_one_document_operation(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.text_tools
    assert tools is not None
    text = DrawingText(uuid4().hex, "ABC", (0, 10))
    assert tools.execute is not None
    tools.execute("drawing.text.add", text.to_mapping())
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    editor.canvas.entities = [line]
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    editor.canvas.begin_transform("move")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 5))
    )
    qtbot.waitUntil(lambda: not window.execution_unit or not window.execution_unit.is_busy)
    assert services.kernel.drawing_texts[0].position_mm == (5, 15)
    assert editor.canvas.entities[0] != line
    window.request_undo()
    qtbot.waitUntil(lambda: not window.execution_unit or not window.execution_unit.is_busy)
    assert services.kernel.drawing_texts == (text,)
    assert editor.canvas.entities == [line]


def test_multiselect_properties_change_only_edited_fields(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.ui.drawing_text_tools import DrawingTextTools

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    texts = (
        DrawingText(uuid4().hex, "A", (0, 10), rotation_deg=30),
        DrawingText(uuid4().hex, "B", (20, 30), style_id="other", rotation_deg=60),
    )
    tools.sync(texts, TextStyleTable((TextStyle(), TextStyle("other", "其他"))))
    tools.selected_ids = {item.text_id for item in texts}
    tools.refresh_selection()
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    tools.height.setValue(5)
    tools.apply_properties()
    raw = calls[0]["update"]
    assert isinstance(raw, list)
    changed = tuple(DrawingText.from_mapping(value) for value in cast("list[object]", raw))
    assert tuple(item.position_mm for item in changed) == ((0, 10), (20, 30))
    assert tuple(item.style_id for item in changed) == ("standard", "other")
    assert tuple(item.rotation_deg for item in changed) == (30, 60)
    assert all(item.height_mm == 5 for item in changed)
