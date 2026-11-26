# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Draw a draft rectangle, then place a datum using real canvas mouse events."""

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from mycad import app
from mycad.ui import main_window

qapp = QApplication([])
main_window.MainWindow._ask_save_dialog = lambda self: "discard"
main_window.MainWindow._ask_session_close_dialog = lambda self, entries: {
    entry.loaded.document.document_id: "discard" for entry in entries
}
with TemporaryDirectory() as directory:
    main_window.QSettings = lambda organization, application: QSettings(
        str(Path(directory) / "isolated.ini"), QSettings.Format.IniFormat
    )
    services = app.build_app(discoverers=())
    window = main_window.MainWindow(services=services)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    window.act_default_datum_circle.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.setFixedSize(1000, 650)
    qapp.processEvents()
    assert canvas.set_tool("矩形")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((80, 25), exact_point=True)
    canvas.fit_view()
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    window.act_datum_label.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 25)))
    end = canvas.local_to_screen((50, 40))
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
    QInputDialog.getText = lambda *args, **kwargs: ("A", True)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert len(tools.datums) == 1
    assert tools.datums[0].bar_direction is not None
    assert abs(tools.datums[0].bar_direction[1]) < 1e-9
    qapp.processEvents()
    target = Path(__file__).with_name("draft-canvas.png")
    assert canvas.grab().save(str(target))
    print(target, tools.datums[0].bar_direction, flush=True)
    window.close()
    qapp.processEvents()
