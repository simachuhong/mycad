# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D cursor rendering and user preferences."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchCanvas


def _move(canvas: SketchCanvas, x: int, y: int) -> None:
    point = QPointF(x, y)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_2d_crosshair_tracks_pointer_and_full_mode_extends_to_edges(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.grid_visible = False
    canvas.show()
    qtbot.waitExposed(canvas)
    _move(canvas, 80, 60)
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor
    assert canvas.crosshair_style == "short"
    short = canvas.grab().toImage()
    assert short.pixelColor(80, 60) != short.pixelColor(110, 60)
    canvas.set_crosshair_style("full")
    full = canvas.grab().toImage()
    assert full.pixelColor(110, 60) != short.pixelColor(110, 60)
    assert full.pixelColor(80, 90) != short.pixelColor(80, 90)
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    hidden = canvas.grab().toImage()
    assert hidden.pixelColor(110, 60) == short.pixelColor(110, 60)
    other = SketchCanvas()
    assert other.cursor().shape() != Qt.CursorShape.BlankCursor


def test_2d_canvas_has_no_fixed_axes_but_other_sketch_keeps_them(qtbot: QtBot) -> None:
    for drawing_2d in (True, False):
        canvas = SketchCanvas(select_committed_entities=drawing_2d)
        qtbot.addWidget(canvas)
        canvas.resize(400, 300)
        canvas.grid_visible = False
        canvas.show()
        qtbot.waitExposed(canvas)
        QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
        image = canvas.grab().toImage()
        origin = canvas.local_to_screen((0.0, 0.0))
        axis_pixel = image.pixelColor(15, origin.y())
        blank_pixel = image.pixelColor(15, origin.y() + 10)
        assert (axis_pixel == blank_pixel) is drawing_2d


def test_system_settings_save_cancel_and_apply_to_new_2d_canvas(
    qtbot: QtBot, tmp_path: Path, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    from mycad.ui.document_session import DocumentSession
    from mycad.ui.preferences import CursorSettingsDialog, drawing_cursor_style

    assert isinstance(monkeypatch, MonkeyPatch)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def user_settings(*_args: object) -> QSettings:
        return settings

    settings.setValue("drawing2d/cursorStyle", "invalid")
    assert drawing_cursor_style(settings) == "short"
    monkeypatch.setattr("mycad.ui.main_window.QSettings", user_settings)
    window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.crosshair_style == "short"
    cursor_entry = editor.canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert cursor_entry is not None and cursor_entry.cursor().shape() == Qt.CursorShape.IBeamCursor
    window.act_new_drawing.trigger()
    second_editor = window.active_sketch_dialog()
    assert second_editor is not None and second_editor is not editor

    def accept(dialog: CursorSettingsDialog) -> int:
        dialog.cursor_style.setCurrentIndex(1)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(CursorSettingsDialog, "exec", accept)
    window.act_options.trigger()
    assert settings.value("drawing2d/cursorStyle") == "full"
    assert second_editor.canvas.crosshair_style == "full"
    assert window.document_session is not None
    for document in window.document_session.documents:
        if document.draft is not None:
            assert document.draft.canvas.crosshair_style == "full"

    def cancel(dialog: CursorSettingsDialog) -> int:
        dialog.cursor_style.setCurrentIndex(0)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(CursorSettingsDialog, "exec", cancel)
    window.act_options.trigger()
    assert settings.value("drawing2d/cursorStyle") == "full"
    assert second_editor.canvas.crosshair_style == "full"
    window.act_new_drawing.trigger()
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.crosshair_style == "full"


def test_crosshair_tracks_moves_consumed_by_dimension_tool(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.canvas.grid_visible = False
    editor.canvas.set_crosshair_style("full")
    editor.dimensions.buttons["radius"].click()
    _move(editor.canvas, 80, 60)
    image = editor.canvas.grab().toImage()
    assert image.pixelColor(110, 60) != image.pixelColor(110, 70)
    _move(editor.canvas, 100, 90)
    moved = editor.canvas.grab().toImage()
    assert moved.pixelColor(130, 90) != image.pixelColor(130, 90)


@pytest.mark.skipif(sys.platform != "linux", reason="isolates QSettings through XDG on Linux")
def test_cursor_preference_survives_application_restart(tmp_path: Path) -> None:
    config = tmp_path / "config"
    env = os.environ.copy()
    env.update(
        {
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "QT_QPA_PLATFORM": "offscreen",
            "QT_IM_MODULE": "compose",
        }
    )
    env.pop("QT_PLUGIN_PATH", None)
    common = """
from PySide6.QtWidgets import QApplication, QDialog
from mycad.app import build_app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.preferences import CursorSettingsDialog
application = QApplication([])
window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
window._ask_session_close_dialog = lambda pending: {
    entry.loaded.document.document_id: 'discard' for entry in pending
}
window.show()
window.act_new_drawing.trigger()
editor = window.active_sketch_dialog()
assert editor is not None
"""
    save = (
        common
        + """
assert editor.canvas.crosshair_style == 'short'
def choose(dialog):
    dialog.cursor_style.setCurrentIndex(1)
    return int(QDialog.DialogCode.Accepted)
CursorSettingsDialog.exec = choose
window.act_options.trigger()
assert editor.canvas.crosshair_style == 'full'
window.close()
"""
    )
    reopen = (
        common
        + """
assert editor.canvas.crosshair_style == 'full'
window.close()
"""
    )
    for script in (save, reopen):
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-4000:]
