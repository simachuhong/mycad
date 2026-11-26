import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mycad import app
from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.formats.providers.dxf_provider import write_dxf_with_frame_anchors
from mycad.ui.main_window import MainWindow

qt_app = QApplication([])
services = app.build_app(discoverers=())
window = MainWindow(services=services)
window.resize(1400, 900)
window.show()
window.act_new_drawing.trigger()
qt_app.processEvents()
editor, loaded = window.active_sketch_dialog(), window.loaded_document()
assert editor is not None and loaded is not None
line = LineEntity("a" * 32, (-3, -2), (7, -2))
sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (line,))
app.commit_new_sketch(services, loaded, sketch, session_identity=0)
attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5)
frame = FeatureControlFrame(
    "c" * 32, (ToleranceRow("position", 0.1, 2),), (0, 6),
    leader_target_mm=(2, -2), leader_offsets=((2, -3),),
    leader_attachment=attachment, leader_auto_normal=True, leader_auto_route=True,
)
loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [frame.to_mapping()]}, "local")
window._sync_drawing_layers()
qt_app.processEvents()
tools = editor.canvas.geometric_tolerance_tools
assert tools is not None
anchors = tools.legacy_frame_export_anchors((frame,))
skipped = tools.legacy_frame_export_skipped_vertices((frame,), anchors)
bounds = tools.legacy_frame_export_bounds((frame,), anchors)
assert editor.canvas.grab().save(str(Path(__file__).with_name("actual-canvas.png")))
write_dxf_with_frame_anchors(
    services.kernel, Path(__file__).with_name("actual-source.dxf"), anchors, skipped, bounds
)
print("anchors", anchors, "bounds", bounds, "skipped", skipped)
sys.stdout.flush()
os._exit(0)
