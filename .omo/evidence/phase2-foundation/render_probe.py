from pathlib import Path
import json
import tempfile

from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_VERSION, glGetString
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow

out = Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
settings = tempfile.TemporaryDirectory(prefix='mycad-phase2-render-')
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings.name)
QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings.name)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
services = build_app(discoverers=[])
window = MainWindow(services=services)
window.resize(1366, 768)
view = window.viewport
assert view is not None
window.show()
QTest.qWait(400)
assert view.isValid(), 'No real OpenGL context'
view.makeCurrent()
gl = {name: glGetString(key).decode() for name, key in [('vendor',GL_VENDOR), ('renderer',GL_RENDERER), ('version',GL_VERSION)]}
view.doneCurrent()
settings_path = QSettings('MyCAD','MyCAD').fileName()
assert Path(settings_path).is_relative_to(settings.name)
report = {'qt_platform':app.platformName(), 'opengl':gl, 'settings_isolated':True, 'screens':[]}
cases = {
    'empty': [],
    'flange': [
        ('feature.cylinder', {'radius':40.0,'height':8.0,'mode':'new'}),
        ('feature.hole', {'target_face':{'surface':'plane','axis':'+Z','rank':0},'position':{'kind':'center'},'diameter':20.0,'depth':{'kind':'through_all'}}),
        ('feature.hole_pattern', {'base_hole':{'target_face':{'surface':'plane','axis':'+Z','rank':0},'position':{'kind':'center'},'diameter':6.0,'depth':{'kind':'through_all'}},'pattern':{'kind':'polar','radius':25.0,'count':4,'start_angle_deg':0}}),
    ],
    'thin-plate': [('feature.box', {'size_x':120,'size_y':80,'size_z':2})],
    'cylinder': [('feature.cylinder', {'radius':20,'height':40})],
}
for name, commands in cases.items():
    loaded = new_document(services)
    window.bind_document(loaded)
    for cid, params in commands:
        loaded.bus.execute(cid, params, 'render-check')
    view.refresh()
    view.fit_view()
    QTest.qWait(250)
    frame = view.grabFramebuffer()
    assert not frame.isNull()
    pixel = frame.pixelColor(8,8).getRgb()
    assert pixel[:3] == (239,243,247), (name,pixel)
    assert pixel[3] == 255
    frame.save(str(out / f'{name}-viewport.png'))
    if name == 'flange':
        window.grab().save(str(out / 'light-workspace.png'))
        view.highlight_feature(2)
        QTest.qWait(150)
        view.grabFramebuffer().save(str(out / 'flange-selected.png'))
    report['screens'].append({'case':name,'background_rgba':pixel,'size':[frame.width(),frame.height()]})
    loaded.document.mark_clean()
loaded = new_document(services)
window.bind_document(loaded)
loaded.bus.execute('feature.box', {'size_x':10,'size_y':10,'size_z':10}, 'render-check')
view.refresh()
view.highlight_feature(0)
loaded.bus.execute('feature.box', {'size_x':20,'size_y':20,'size_z':20,'mode':'cut'}, 'render-check')
view.refresh()
QTest.qWait(200)
frame=view.grabFramebuffer()
assert not view.items
for x,y in [(8,8),(frame.width()//2,frame.height()//2)]:
    assert frame.pixelColor(x,y).getRgb()==(239,243,247,255)
frame.save(str(out/'complete-cut-empty.png'))
report['empty_cut']={'scene_items':len(view.items),'solid_count':services.kernel.mass_properties().solid_count,'background_only':True}
loaded.document.mark_clean()
window.close()
app.processEvents()
settings.cleanup()
(out/'render-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
