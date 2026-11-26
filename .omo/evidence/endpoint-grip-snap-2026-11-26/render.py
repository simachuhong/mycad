# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Render an actual saved-object endpoint drag snapped to a rectangle/arc endpoint."""

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad import app
from mycad.core.sketch import ArcEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.ui import main_window

qapp = QApplication([])
main_window.MainWindow._ask_save_dialog = lambda self: "discard"
main_window.MainWindow._ask_session_close_dialog = lambda self, entries: {
    entry.loaded.document.document_id: "discard" for entry in entries
}
with TemporaryDirectory() as directory:
    main_window.QSettings = lambda organization, application: QSettings(
        str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat
    )
    services = app.build_app(discoverers=())
    window = main_window.MainWindow(services=services)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.setFixedSize(900, 600)
    qapp.processEvents()
    line = LineEntity(uuid4().hex, (0, 0), (20, 15))
    geometry = (
        line,
        RectangleEntity(uuid4().hex, (0, 0), (50, 30)),
        ArcEntity(uuid4().hex, (50, 15), 15, -90, 180),
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), geometry), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas.fit_view()
    assert canvas.set_tool("选择元素")
    canvas.set_snapping_enabled(True)
    canvas.selected_entity_ids = {line.entity_id}
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(line.end_mm))
    near = canvas.local_to_screen((50, 30)) + QPoint(-4, 3)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove, QPointF(near), QPointF(canvas.mapToGlobal(near)),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ),
    )
    deadline = time.monotonic() + 10
    while not canvas.saved_handle_preview and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert canvas.saved_handle_preview
    assert canvas.current_snap_kind == "端点"
    moved = next(item for item, _ in canvas.saved_handle_preview if item.entity_id == line.entity_id)
    assert isinstance(moved, LineEntity) and moved.end_mm == (50, 30)
    qapp.processEvents()
    target = Path(__file__).with_name("canvas.png")
    assert canvas.grab().save(str(target))
    print(target, flush=True)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    window.close()
    qapp.processEvents()
