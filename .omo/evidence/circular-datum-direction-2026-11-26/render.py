# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Render the reported slanted connector against a horizontal rectangle edge."""
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from mycad import app
from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
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
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    rectangle = RectangleEntity("a" * 32, (0, 0), (80, 25))
    sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    datum = DatumIdentifier(
        "c" * 32, "A", (55, 55), (40, 25), layout_mode="shared", symbol_style="circle",
        attachment=DatumAttachment(sketch.sketch_id, SketchGeometryReference(rectangle.entity_id, "segment", 2), 0.5, 4, "rectangle"),
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    editor.canvas.setFixedSize(1000, 650)
    qapp.processEvents()
    editor.canvas.fit_view()
    qapp.processEvents()
    target = Path(__file__).with_name("canvas.png")
    assert editor.canvas.grab().save(str(target))
    print(target, flush=True)
    window.close()
    qapp.processEvents()
