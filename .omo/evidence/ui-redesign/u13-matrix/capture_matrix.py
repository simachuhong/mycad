# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QWidget

from mycad import app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow

physical, scale = sys.argv[1:3]
out = Path(__file__).resolve().parent
settings_dir = tempfile.TemporaryDirectory(prefix='mycad-u13-settings-')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
    QSettings.setPath(QSettings.Format.IniFormat, scope, settings_dir.name)
qt = QApplication([])
window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
screen = qt.primaryScreen().availableGeometry()
window.resize(screen.width(), screen.height())
window.show()
QTest.qWait(500)
report = {'physical': physical, 'scale': scale, 'platform': qt.platformName(), 'windows': {}}


def accessible(widget: QWidget) -> bool:
    if not widget.isVisible():
        return False
    parent = widget.parentWidget()
    scroll = None
    while parent is not None:
        if isinstance(parent, QScrollArea):
            scroll = parent
            break
        parent = parent.parentWidget()
    if scroll is not None:
        horizontal = scroll.horizontalScrollBar().value()
        vertical = scroll.verticalScrollBar().value()
        content = scroll.widget()
        if content is None:
            return False
        point = widget.mapTo(content, widget.rect().center())
        scroll.ensureVisible(
            point.x(), point.y(),
            min(max(2, widget.width() // 2), max(2, scroll.viewport().width() // 2 - 1)),
            min(max(2, widget.height() // 2), max(2, scroll.viewport().height() // 2 - 1)),
        )
        qt.processEvents()
        target = widget.mapTo(scroll.viewport(), widget.rect().center())
        result = scroll.viewport().rect().contains(target)
        scroll.horizontalScrollBar().setValue(horizontal)
        scroll.verticalScrollBar().setValue(vertical)
        return result
    target = widget.mapTo(window, widget.rect().center())
    return window.rect().contains(target)


def visible_rect(widget: QWidget) -> QRect:
    result = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()).intersected(window.rect())
    parent = widget.parentWidget()
    while parent is not None and parent is not window:
        result = result.intersected(QRect(parent.mapTo(window, QPoint(0, 0)), parent.size()))
        parent = parent.parentWidget()
    return result


def capture(name: str, controls: dict[str, QWidget]) -> None:
    qt.processEvents()
    QTest.qWait(200)
    path = out / f'{physical}-{scale}-{name}.png'
    checks = {key: accessible(widget) for key, widget in controls.items()}
    report['windows'][name] = {
        'logical_size': [window.width(), window.height()],
        'screen_logical_size': [qt.primaryScreen().availableGeometry().width(), qt.primaryScreen().availableGeometry().height()],
        'device_pixel_ratio': window.devicePixelRatioF(),
        'controls_reachable': checks,
        'visible_sizes': {key: [visible_rect(widget).width(), visible_rect(widget).height()] for key, widget in controls.items()},
        'image': str(path),
    }
    if not window.grab().save(str(path)):
        raise RuntimeError(f'capture failed: {path}')

window.show_start_page()
capture('home', {'2d': window.start_page.drawing_button, 'drawing': window.start_page.engineering_button, 'part': window.start_page.part_button})
part = window.new_session_document('part')
part.loaded.bus.execute('feature.box', {'size_x':40, 'size_y':30, 'size_z':8})
window.viewport.refresh()
capture('part', {'ribbon': window.part_ribbon, 'documents': window.document_tab_bar})
window.act_sketch.trigger()
sketch = window.part_sketch_task
if sketch is None:
    raise RuntimeError('part sketch did not start')
sketch.select_tool('line')
QTest.qWait(200)
capture('part-sketch', {
    'plane': sketch.plane_combo,
    'lock': sketch.lock_button,
    'line': sketch.line_button,
    'finish': sketch.confirm_button,
    'dynamic_first': sketch.dynamic_input.first_value,
    'dynamic_second': sketch.dynamic_input.second_value,
    'viewport': window.viewport,
})
sketch.reject()
window.action_catalog.get('ui.feature.bound_hole').trigger()
task = window.bound_hole_task
if task is None:
    raise RuntimeError('bound hole did not start')
for _ in range(200):
    if task.scene is not None:
        break
    QTest.qWait(100)
if task.scene is None:
    raise RuntimeError('bound hole preview did not finish: ' + task.status_label.text())
capture('bound-hole', {'confirm': task.confirm_button, 'cancel': task.cancel_button, 'preview': task.preview_button, 'viewport': window.viewport})
task.reject()
window.right_panel.select_feature_ordinal(0)
window.right_panel.findChild(type(task.preview_button), 'editHistoryFeature').click()
history = window.history_edit_task
if history is None:
    raise RuntimeError('history edit did not start')
capture('history-edit', {'confirm': history.confirm_button, 'cancel': history.cancel_button, 'parameters': history.parameter_button})
def capture_parameters():
    dialog = history.parameter_dialog
    done = next(button for button in dialog.findChildren(QPushButton) if button.text() == '完成')
    path = out / f'{physical}-{scale}-history-parameters.png'
    screen = qt.primaryScreen().availableGeometry()
    report['windows']['history-parameters'] = {
        'logical_size': [dialog.width(), dialog.height()],
        'screen_logical_size': [screen.width(), screen.height()],
        'device_pixel_ratio': dialog.devicePixelRatioF(),
        'controls_reachable': {'done': done.isVisible() and dialog.rect().contains(done.mapTo(dialog, done.rect().center()))},
        'image': str(path),
    }
    if not dialog.grab().save(str(path)):
        raise RuntimeError(f'capture failed: {path}')
    dialog.accept()
QTimer.singleShot(200, capture_parameters)
history.parameter_button.click()
history.reject()
window.new_session_document('sketch')
editor = window.active_sketch_dialog()
if editor is None:
    raise RuntimeError('2d editor unavailable')
capture('drawing2d', {'canvas': editor.canvas, 'command_input': editor.drawing_command_bar.input, 'document_tabs': window.document_tab_bar})
window.new_session_document('drawing')
capture('drawing', {'canvas_or_start': window.drawing_workbench.pages, 'choose_source': window.drawing_workbench.choose_source_button, 'document_tabs': window.document_tab_bar})
(out / f'{physical}-{scale}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False), flush=True)
qt.exit(0)
