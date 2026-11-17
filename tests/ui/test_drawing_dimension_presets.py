# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension format presets survive application settings reload."""

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad.ui.dimension_presets import DimensionPresetDialog, load_dimension_presets


def test_named_preset_save_cancel_and_reload(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    dialog = DimensionPresetDialog(settings, 2, 1.0)
    qtbot.addWidget(dialog)
    dialog.name.setCurrentText("加工图")
    dialog.precision.setValue(3)
    dialog.scale.setValue(2.0)
    dialog.save_button.click()
    dialog.accept()
    settings.sync()
    reloaded = QSettings(str(path), QSettings.Format.IniFormat)
    assert load_dimension_presets(reloaded)["加工图"] == (3, 2.0)
    cancelled = DimensionPresetDialog(reloaded, 2, 1.0)
    qtbot.addWidget(cancelled)
    cancelled.name.setCurrentText("加工图")
    cancelled.precision.setValue(1)
    cancelled.save_button.click()
    cancelled.reject()
    assert load_dimension_presets(reloaded)["加工图"] == (3, 2.0)


def test_dimstyle_applies_preset_to_new_reference_dimension(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity
    from mycad.ui import dimension_tools
    from mycad.ui.sketch_editor import SketchEditorDialog

    path = tmp_path / "settings.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    class IsolatedDialog(DimensionPresetDialog):
        def __init__(
            self, _settings: QSettings, precision: int, scale: float, parent: QWidget | None = None
        ) -> None:
            super().__init__(settings, precision, scale, parent)

    monkeypatch.setattr(dimension_tools, "DimensionPresetDialog", IsolatedDialog)
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DimensionPresetDialog)
        dialog.name.setCurrentText("加工图")
        dialog.precision.setValue(3)
        dialog.scale.setValue(2.0)
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    bar = editor.drawing_command_bar.input
    for command in ("DIMSTYLE", "DIMLINEAR", "0,0", "20,10", "10,20"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.constraints) == 1
    dimension = editor.canvas.constraints[0]
    assert dimension.precision == 3
    assert dimension.scale == 2.0
    assert not dimension.driving
    sketch = next(s for s in editor.dimension_sources() if s.constraints)
    editor.dimensions.edit(sketch, dimension)
    editor.dimensions.precision.setValue(1)
    editor.dimensions.cancel()
    editor.dimensions.start("linear")
    assert editor.dimensions.precision.value() == 3
    assert editor.dimensions.scale.value() == 2.0
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    document_path = tmp_path / "preset.my2d"
    save_document(loaded.document, document_path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, document_path)
    restored = reopened.kernel.sketches[0].constraints[0]
    assert restored.precision == 3 and restored.scale == 2.0


def test_dimstyle_d_alias_does_not_override_active_chamfer_option(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    assert editor.canvas.set_tool("直线")
    opened: list[bool] = []

    def reject_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DimensionPresetDialog))
        if isinstance(dialog, DimensionPresetDialog):
            dialog.reject()

    QTimer.singleShot(100, reject_dialog)
    bar.setText("D")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == [True]
    bar.setText("CHAMFER")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("D")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "距离" in editor.drawing_command_bar.status.text()


def test_delete_named_preset_keeps_other_presets(qtbot: QtBot, tmp_path: Path) -> None:
    import json

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(
        "drawing2d/dimensionPresets", json.dumps({"A": [2, 1.0], "B": [3, 2.0]})
    )
    dialog = DimensionPresetDialog(settings, 2, 1.0)
    qtbot.addWidget(dialog)
    dialog.name.setCurrentText("A")
    dialog.delete_button.click()
    dialog.accept()
    assert load_dimension_presets(settings) == {"B": (3, 2.0)}
