# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric constraint badges follow the global drawing preference."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QSettings
from PySide6.QtWidgets import QApplication, QDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.core.sketch import LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.preferences import CursorSettingsDialog
from mycad.ui.sketch_editor import SketchCanvas


def test_visibility_hides_only_geometric_badges(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.grid_visible = False
    line = LineEntity(uuid4().hex, (-30, 10), (30, 10))
    reference = SketchGeometryReference(line.entity_id, "geometry")
    canvas.entities = [line]
    canvas.constraints = [
        SketchConstraint(uuid4().hex, "horizontal", (reference,)),
        SketchConstraint(uuid4().hex, "length", (reference,), 60, "mm", position_mm=(0, 30)),
    ]
    canvas.show()
    qtbot.waitExposed(canvas)
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    with_badge = canvas.grab().toImage()
    canvas.set_constraint_markers_visible(False)
    without_badge = canvas.grab().toImage()
    assert with_badge != without_badge
    assert len(canvas.constraints) == 2
    dimension = canvas.constraints[1]
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    point = layout.label.toPoint()
    assert with_badge.pixelColor(point.x(), point.y()) == without_badge.pixelColor(
        point.x(), point.y()
    )
    canvas.set_constraint_markers_visible(True)
    assert canvas.grab().toImage() == with_badge


def test_settings_apply_to_open_and_new_drawings_and_cancel(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)

    def user_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", user_settings)
    window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first = window.active_sketch_dialog()
    assert first is not None and first.canvas.constraint_markers_visible
    window.act_new_drawing.trigger()
    second = window.active_sketch_dialog()
    assert second is not None

    def accept(dialog: CursorSettingsDialog) -> int:
        dialog.constraint_markers.setChecked(False)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(CursorSettingsDialog, "exec", accept)
    window.act_options.trigger()
    assert not first.canvas.constraint_markers_visible
    assert not second.canvas.constraint_markers_visible
    window.act_new_drawing.trigger()
    third = window.active_sketch_dialog()
    assert third is not None and not third.canvas.constraint_markers_visible

    def cancel(dialog: CursorSettingsDialog) -> int:
        dialog.constraint_markers.setChecked(True)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(CursorSettingsDialog, "exec", cancel)
    window.act_options.trigger()
    assert not third.canvas.constraint_markers_visible
    settings.sync()
    reopened = QSettings(settings.fileName(), QSettings.Format.IniFormat)
    assert reopened.value("drawing2d/constraintMarkersVisible", type=bool) is False


@pytest.mark.skipif(sys.platform != "linux", reason="isolates QSettings through XDG on Linux")
def test_hidden_marker_setting_survives_application_restart(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
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
assert editor.canvas.constraint_markers_visible
def choose(dialog):
    dialog.constraint_markers.setChecked(False)
    return int(QDialog.DialogCode.Accepted)
CursorSettingsDialog.exec = choose
window.act_options.trigger()
assert not editor.canvas.constraint_markers_visible
window.close()
"""
    )
    reopen = (
        common
        + """
assert not editor.canvas.constraint_markers_visible
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
