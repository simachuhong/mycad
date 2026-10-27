from PySide6.QtCore import QPoint, Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from mycad.ui import main_window
from mycad.app import build_app
app=QApplication([])
main_window.QSettings=lambda *args: QSettings('/tmp/mycad-toolbar-floating-all.ini',QSettings.Format.IniFormat)
main_window.QSettings().clear()
w=main_window.MainWindow(services=build_app(discoverers=()))
w.resize(1400,900)
w.show()
w.act_new_drawing.trigger()
d=w.active_sketch_dialog()
QTest.qWait(300)
for bar in d.drafting_toolbars:
    start=QPoint(5,bar.height()//2)
    print('before',bar.windowTitle(),bar.isFloating(),bar.geometry(),flush=True)
    QTest.mousePress(bar,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(bar,QPoint(160,220),delay=100)
    QTest.mouseRelease(bar,Qt.MouseButton.LeftButton,pos=QPoint(160,220),delay=100)
    QTest.qWait(300)
    print('after',bar.windowTitle(),bar.isFloating(),bar.geometry(),flush=True)
    assert bar.isFloating()
bar=d.drawing_toolbar
bar.grab().save('.omo/evidence/phase2-g-toolbar-workspaces/drawing-floating.png')
w.act_view_3d.trigger()
app.processEvents()
assert all(b.isHidden() for b in d.drafting_toolbars)
w.act_view_2d.trigger()
app.processEvents()
assert all(b.isFloating() and b.isVisible() for b in d.drafting_toolbars)
w.store_window_state()
# Force a second editor via a committed sketch, then check its floating layout.
d.canvas.add_coordinate_point((0.,0.))
d.canvas.add_coordinate_point((20.,0.))
d.canvas.end_line_chain()
d.finish_button.click()
for _ in range(300):
    app.processEvents()
    if w.active_sketch_dialog() is not None:
        break
    QTest.qWait(20)
next_draft=w.active_sketch_dialog()
assert next_draft is not None and next_draft is not d
assert next_draft.drawing_toolbar.isFloating() and next_draft.drawing_toolbar.isVisible()
assert bar.isHidden()
bar=next_draft.drawing_toolbar
# Redock via real handle drag into the host top area.
start=QPoint(5,bar.height()//2)
target=bar.mapFromGlobal(next_draft.toolbar_host.mapToGlobal(QPoint(30,10)))
QTest.mousePress(bar,Qt.MouseButton.LeftButton,pos=start)
QTest.mouseMove(bar,target,delay=150)
QTest.mouseRelease(bar,Qt.MouseButton.LeftButton,pos=target,delay=150)
QTest.qWait(300)
print('redocked',bar.isFloating(),next_draft.toolbar_host.toolBarArea(bar),flush=True)
assert not bar.isFloating()
print('PASS native float, hide/show, committed-draft continuity, native redock',flush=True)
next_draft.reject()
w._ask_save_dialog=lambda:'discard'
w.close()
