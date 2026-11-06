import json
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.viewport import GLViewport

out = Path('/media/sima/Data/projects/MyCAD/.omo/evidence/m2a-design-review-2026-11-03')
app = QApplication([])
services = build_app(discoverers=[])
loaded = new_document(services)
loaded.bus.execute('feature.box', {'size_x': 40, 'size_y': 25, 'size_z': 12}, 'camera-smoke')
view = GLViewport(viewport_port=services.kernel)
view.resize(960, 720)
view.bind_document(loaded)
view.show()
QTest.qWaitForWindowExposed(view)
app.processEvents()
view.fit_view()
view.set_orientation('top')
QTest.mousePress(view, Qt.MouseButton.MiddleButton, pos=QPoint(480, 360))
view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(440, 480), QPointF(440, 480),
    Qt.MouseButton.NoButton, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier))
QTest.mouseRelease(view, Qt.MouseButton.MiddleButton, pos=QPoint(440, 480))
app.processEvents()
image = view.grabFramebuffer()
assert view.isValid() and not image.isNull()
assert image.save(str(out / 'free-orbit-native-gl.png'))
assert view.viewMatrix().row(2).z() < 0  # moved through the north pole to the underside
assert abs(view.viewMatrix().row(0).z()) > 0.1
result = {'native_gl_valid': view.isValid(), 'camera_world_direction': view.viewMatrix().row(2).toTuple(),
          'image': str(out / 'free-orbit-native-gl.png'), 'history_commands': len(loaded.document.commands)}
(out / 'camera-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
view.close()
