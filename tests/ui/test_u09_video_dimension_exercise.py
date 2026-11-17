# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise 1 from the user's downloaded AutoCAD 2020 tutorial."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_video_profile_dimensions_select_delete_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    command = editor.drawing_command_bar.input
    for entry in (
        "LINE",
        "0,0",
        "60,0",
        "60,22",
        "38,38",
        "16,38",
        "0,22",
        "0,0",
        "",
        "CIRCLE",
        "18,18",
        "D",
        "18",
        "CIRCLE",
        "42,10",
        "D",
        "10",
    ):
        command.setText(entry)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert sum(isinstance(entity, LineEntity) for entity in canvas.entities) == 6
    circles = [entity for entity in canvas.entities if isinstance(entity, CircleEntity)]
    assert [(circle.center_mm, circle.radius_mm) for circle in circles] == [
        ((18, 18), 9),
        ((42, 10), 5),
    ]
    canvas.fit_view()
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((30, 0), (30, -12)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.constraints) == 1 and canvas.constraints[0].value == pytest.approx(60)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen((30, -12)))
    editor.dimensions.buttons["diameter"].click()
    for point in ((27, 18), (29, 30)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.constraints) == 2 and canvas.constraints[-1].value == pytest.approx(18)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen((29, 30)))
    dimension = canvas.constraints[-1]
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert len(canvas.constraints) == 1
    assert canvas.undo_last_operation() and canvas.constraints[-1] == dimension
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    sketches = services.kernel.sketches
    assert len(sketches) == 1 and len(sketches[0].entities) == 8
    assert sorted(item.value for item in sketches[0].constraints if item.value is not None) == [
        18,
        60,
    ]
    path = tmp_path / "autocad-exercise-1.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.sketches == sketches
