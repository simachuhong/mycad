import os
import sys
from uuid import uuid4
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog
from mycad import app
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.formats.providers.dxf_provider import write_sketches_dxf
from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
from mycad.ui.main_window import MainWindow

qt_app = QApplication([])
services = app.build_app(discoverers=())
window = MainWindow(services=services)
window.resize(1400, 900)
window.show()
window.act_new_drawing.trigger()
qt_app.processEvents()
editor = window.active_sketch_dialog()
loaded = window.loaded_document()
assert editor is not None and loaded is not None
sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (80, 0)),))
app.commit_new_sketch(services, loaded, sketch, session_identity=0)
window._sync_drawing_layers()
tools = editor.canvas.geometric_tolerance_tools
assert tools is not None
QInputDialog.getText = lambda *_args, **_kwargs: ('A', True)
GeometricToleranceDialog.exec = lambda _self: int(QDialog.DialogCode.Accepted)
tools.begin_mechanical_datum()
assert tools.handle_command('10,0') and tools.handle_command('30,20')
tools.begin_mechanical_frame()
assert tools.handle_command('60,0') and tools.handle_command('80,20')
qt_app.processEvents()
assert len(services.kernel.drawing_datum_identifiers) == 1
assert len(services.kernel.drawing_tolerance_frames) == 1
window.act_theme_light.trigger()
qt_app.processEvents()
assert window.grab().save('.omo/evidence/tolerance-gui-selfcheck-current/window.png')
assert editor.canvas.grab().save('.omo/evidence/tolerance-gui-selfcheck-current/canvas.png')
window.act_theme_dark.trigger()
qt_app.processEvents()
assert window.grab().save('.omo/evidence/tolerance-gui-selfcheck-current/dark-window.png')
assert editor.canvas.grab().save('.omo/evidence/tolerance-gui-selfcheck-current/dark-canvas.png')
write_sketches_dxf(
    services.kernel.sketches,
    '.omo/evidence/tolerance-gui-selfcheck-current/sample.dxf',
    datum_identifiers=services.kernel.drawing_datum_identifiers,
    tolerance_frames=services.kernel.drawing_tolerance_frames,
)
print('GUI_CAPTURE_OK')
sys.stdout.flush()
os._exit(0)
