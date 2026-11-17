# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Measurement tools in the independent 2D toolbar."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.ui.cad_icons import cad_icon
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog
from mycad.ui.theme import ThemeName


@pytest.mark.parametrize(
    ("label", "prompt"),
    [
        ("快速测量", "快速测量"),
        ("距离", "DIST"),
        ("面积", "AREA"),
        ("半径", "半径"),
        ("角度", "角度"),
    ],
)
def test_measurement_toolbar_starts_command(qtbot: QtBot, label: str, prompt: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    button = editor.measure_buttons[label]
    assert not button.icon().isNull()
    button.click()
    assert prompt in editor.drawing_command_bar.status.text()
    assert editor.canvas.tool == "选择元素"
    assert not editor.canvas.entities


def test_measurement_toolbar_preserves_active_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("POLYGON")
    bar.submit()
    bar.input.setText("6")
    editor.measure_buttons["面积"].click()
    assert bar.input.text() == "6"
    assert "完成或取消" in bar.status.text()
    bar.submit()
    assert "中心" in bar.status.text() or "边" in bar.status.text()
    assert editor.measurement_toolbar.allowedAreas() & Qt.ToolBarArea.TopToolBarArea


def test_measurement_toolbar_main_window_and_layout_restore(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.measurement_toolbar.isVisible()
    editor.measure_buttons["距离"].click()
    assert "DIST" in editor.drawing_command_bar.status.text()
    editor.toolbar_host.addToolBar(Qt.ToolBarArea.LeftToolBarArea, editor.measurement_toolbar)
    state = editor.toolbar_layout_state()
    editor.reset_toolbar_layout()
    editor.restore_toolbar_layout(state)
    assert (
        editor.toolbar_host.toolBarArea(editor.measurement_toolbar)
        == Qt.ToolBarArea.LeftToolBarArea
    )


def test_distance_toolbar_measures_canvas_points(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.measure_buttons["距离"].click()
    for point in ((0, 0), (3, 4)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert "距离：5 mm" in editor.drawing_command_bar.status.text()
    assert not editor.canvas.entities


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_measurement_icons_are_distinct_from_drawing_and_dimensions(
    qtbot: QtBot, theme: ThemeName
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    pairs = (
        ("距离", "dim-aligned"),
        ("面积", "draw-rectangle"),
        ("半径", "dim-radius"),
        ("角度", "dim-angle"),
    )
    images: list[QImage] = []
    for label, old_icon in pairs:
        name = editor.measure_buttons[label].property("cadIconName")
        assert isinstance(name, str) and name.startswith("measure-")
        actual = cad_icon(name, theme).pixmap(48, 48).toImage()
        assert actual != cad_icon(old_icon, theme).pixmap(48, 48).toImage()
        images.append(actual)
    assert all(
        image != other for index, image in enumerate(images) for other in images[index + 1 :]
    )
