# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Cross-document clipboard remains editable and atomic after repeated paste."""

import base64
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clear_clipboard(qapp: QApplication) -> Iterator[None]:
    yield
    qapp.clipboard().clear()


def test_real_cross_document_mixed_clipboard_repeated_paste_reopens(
    qtbot: QtBot, tmp_path: Path
) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    window = MainWindow(services=app.build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    source = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.text_tools is not None
    tools, canvas = editor.canvas.text_tools, editor.canvas
    source_style = TextStyle("standard", "Technical", "Source Font")
    source.loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((source_style,)).to_mapping(), "local"
    )
    item = DrawingText(uuid4().hex, "Source", (10, 20))
    source.loaded.bus.execute("drawing.text.add", item.to_mapping(), "local")
    image = DrawingRaster(uuid4().hex, base64.b64encode(png).decode("ascii"), (0, 0), 10, 10)
    source.loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local")
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(source.services, source.loaded, sketch, session_identity=0)
    editor.set_context_sketches(source.services.kernel.sketches)
    canvas.set_drawing_rasters(source.services.kernel.drawing_rasters)
    tools.sync(source.services.kernel.drawing_texts, source.services.kernel.drawing_text_styles)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_raster_ids = {image.image_id}
    tools.selected_ids = {item.text_id}
    assert tools.copy(), canvas.message
    target = window.new_session_document("sketch")
    target_editor = window.active_sketch_dialog()
    assert target_editor is not None and target_editor.canvas.text_tools is not None
    target_tools = target_editor.canvas.text_tools
    target_style = TextStyle("standard", "technical", "Target Font")
    target.loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((target_style,)).to_mapping(), "local"
    )
    old = DrawingText(item.text_id, "Existing", (0, 0))
    target.loaded.bus.execute("drawing.text.add", old.to_mapping(), "local")
    target.loaded.bus.execute("drawing.raster.add", image.to_mapping(version=2), "local")
    target_tools.sync(
        target.services.kernel.drawing_texts, target.services.kernel.drawing_text_styles
    )
    for point in ((30, 40), (50, 60)):
        assert target_tools.begin_paste()
        assert target_tools.place_paste(point)
        assert "无法" not in target_editor.canvas.message, target_editor.canvas.message
    kernel = target.services.kernel
    assert len(kernel.drawing_texts) == 3 and kernel.drawing_texts[0] == old
    assert len({text.text_id for text in kernel.drawing_texts}) == 3
    assert len({raster.image_id for raster in kernel.drawing_rasters}) == 3
    assert sum(len(sketch.entities) for sketch in kernel.sketches) == 2
    assert kernel.drawing_text_styles.get("standard") == target_style
    assert all(
        kernel.drawing_text_styles.get(text.style_id).font_family == "Source Font"
        for text in kernel.drawing_texts[1:]
    )
    final = (
        kernel.drawing_texts,
        kernel.drawing_rasters,
        kernel.sketches,
        kernel.drawing_text_styles,
    )
    target.loaded.bus.undo_operation()
    assert len(kernel.drawing_texts) == 2 and len(kernel.drawing_rasters) == 2
    assert sum(len(sketch.entities) for sketch in kernel.sketches) == 1
    target.loaded.bus.redo_operation()
    assert (
        kernel.drawing_texts,
        kernel.drawing_rasters,
        kernel.sketches,
        kernel.drawing_text_styles,
    ) == final
    path = tmp_path / "clipboard.my2d"
    save_document(target.loaded.document, path)
    app.open_app_document(target.services, path)
    assert (
        kernel.drawing_texts,
        kernel.drawing_rasters,
        kernel.sketches,
        kernel.drawing_text_styles,
    ) == final
