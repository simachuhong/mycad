from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from mycad.app import build_app
from mycad.ui import main_window
from mycad.core.sketch import LineEntity, SplineEntity

out=Path('.omo/evidence/phase2-g-pointer-spline');out.mkdir(exist_ok=True)
app=QApplication([])
main_window.QSettings=lambda *args: QSettings('/tmp/mycad-pointer-spline-native.ini',QSettings.Format.IniFormat)
main_window.QSettings().clear()
w=main_window.MainWindow(services=build_app(discoverers=()))
w.resize(1400,900);w.show();w.act_new_drawing.trigger();app.processEvents()
d=w.active_sketch_dialog();c=d.canvas
d.auto_relation_check.setChecked(False);d.snap_check.setChecked(False)
def click(p):
 QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=c.local_to_screen(p));app.processEvents()
def hover(p):
 QTest.mouseMove(c,c.local_to_screen(p),delay=20);app.processEvents()
def draw_line(a,b):
 d.tool_buttons['直线'].click();click(a);click(b);QTest.mouseClick(c,Qt.MouseButton.RightButton)
# Repeated trims against two boundaries.
draw_line((-30.,-40.),(-30.,40.));draw_line((30.,-40.),(30.,40.))
draw_line((-60.,0.),(60.,0.));d.tool_buttons['修剪'].click()
click((-45.,0.));click((45.,0.))
assert len(c.entities)==3
assert c.entities[-1].start_mm==(-30.,0.) and c.entities[-1].end_mm==(30.,0.)
print('PASS two ends trimmed by actual clicks',flush=True)
c.replace_draft_entities(())
draw_line((-50.,-30.),(-10.,-30.));d.tool_buttons['选择元素'].click();click((-30.,-30.))
original=c.entities[0]
d.transform_buttons['move'].click()
QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=c.local_to_screen((-30.,-30.)))
hover((-20.,-10.));assert c.entities==[original]
assert c.transform_preview_entities
w.grab().save(str(out/'move-preview.png'))
QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=c.local_to_screen((-20.,-10.)));app.processEvents()
assert c.entities[0].start_mm==(-40.,-10.)
print('PASS native base-point drag/drop move and atomic preview',flush=True)
d.transform_buttons['copy'].click();click((-20.,-10.));hover((20.,10.))
assert len(c.entities)==1
w.grab().save(str(out/'copy-preview.png'))
click((20.,10.));assert len(c.entities)==2
assert c.entities[1].start_mm==(0.,10.)
assert c.entities[0].entity_id!=c.entities[1].entity_id
assert c.undo_last_operation() and len(c.entities)==1
assert c.redo_last_operation() and len(c.entities)==2
print('PASS native copy placement and undo/redo',flush=True)
d.tool_buttons['样条曲线'].click()
for p in ((-50.,10.),(-40.,40.),(-10.,35.),(10.,40.),(30.,25.)):click(p)
QTest.mouseClick(c,Qt.MouseButton.RightButton);app.processEvents()
spline=c.entities[-1];assert isinstance(spline,SplineEntity)
d.tool_buttons['选择元素'].click()
# Editing a spline control point exercises the real optional solver path.
QTest.mousePress(c,Qt.MouseButton.LeftButton,pos=c.local_to_screen((-40.,40.)))
hover((-35.,45.))
QTest.mouseRelease(c,Qt.MouseButton.LeftButton,pos=c.local_to_screen((-35.,45.)));app.processEvents()
updated=c.entities[-1];assert isinstance(updated,SplineEntity)
assert updated.control_points_mm[1]==(-35.,45.),c.message
w.grab().save(str(out/'spline-controls.png'))
print('PASS native spline finish, selection, solver control-point drag',flush=True)
d.finish_button.click()
for _ in range(300):
 app.processEvents()
 if w.active_sketch_dialog() is not None:break
 QTest.qWait(20)
assert w.active_sketch_dialog() is not d
assert len(w.loaded_document().document.commands)==1
w.grab().save(str(out/'committed-spline.png'))
print('PASS committed via Bus and remained visible in next draft',flush=True)
w.active_sketch_dialog().reject();w._ask_save_dialog=lambda:'discard';w.close()
