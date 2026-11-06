import os
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from mycad import app
from mycad.ui.main_window import MainWindow

out = Path(os.environ['MYCAD_CAPTURE_DIR'])
qt = QApplication([])
services = app.build_app(discoverers=[])
window = MainWindow(services=services)
window.resize(1366, 900)
kind = os.environ['MYCAD_CAPTURE_KIND']
loaded = app.new_workspace_document(services, kind='sketch' if kind == '2d' else 'part')
window.bind_document(loaded)
window.show()

def save(name):
    path = out / name
    ok = window.grab().save(str(path))
    print(f'{name}: {ok}; window={window.width()}x{window.height()}; workspace={window.active_workspace}', flush=True)

def step1():
    if kind == '2d':
        window._on_sketch_start()
        QTimer.singleShot(700, step2)
    else:
        save('current-part-idle.png')
        window.workspace_tabs.activate('drawing')
        QTimer.singleShot(700, step2)

def step2():
    if kind == '2d':
        save('current-2d-drawing.png')
        dialog = window.active_sketch_dialog()
        if dialog:
            dialog.tool_combo.setCurrentText('修剪')
        QTimer.singleShot(700, step3)
    else:
        save('current-engineering-start.png')
        window.workspace_tabs.activate('model')
        window._on_sketch_start()
        QTimer.singleShot(700, step3)

def step3():
    if kind == '2d':
        save('current-2d-modify.png')
        qt.quit()
    else:
        save('current-part-select-plane.png')
        task = window.part_sketch_task
        if task:
            task.lock_plane()
            task.select_tool('rectangle')
            task.place_uv((-1.0, -0.5))
            task.place_uv((1.0, 0.5))
        QTimer.singleShot(700, step4)

def step4():
    save('current-part-sketch.png')
    task = window.part_sketch_task
    if task is not None:
        print('diagnostic: entities=', len(task.session.sketch.entities), 'curves=', window.viewport.draft_sketch_curve_count(), 'projected=', window.viewport.project_world_point((-1.0, -0.5, 0.0)), flush=True)
        task.reject()
    qt.quit()

QTimer.singleShot(1000, step1)
qt.exec()
