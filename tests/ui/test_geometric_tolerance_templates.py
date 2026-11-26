# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reusable tolerance rows do not carry identity across drawings."""

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad.core.geometric_tolerance import DatumReference, ToleranceRow


def test_template_storage_persists_rows_without_drawing_identity(tmp_path: Path) -> None:
    from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore

    path = str(tmp_path / "templates.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    store = ToleranceTemplateStore(settings)
    rows = (
        ToleranceRow("position", 0.1, 3, True, "M", (DatumReference("A", uuid4().hex, "L"),)),
        ToleranceRow("flatness", 0.02, 2),
    )
    store.save("定位", rows)
    reopened = ToleranceTemplateStore(QSettings(path, QSettings.Format.IniFormat))
    assert reopened.names() == ("定位",)
    loaded = reopened.get("定位")
    assert loaded[0] == ToleranceRow(
        "position", 0.1, 3, True, "M", (DatumReference("A", None, "L"),)
    )
    assert loaded[1] == rows[1]
    reopened.delete("定位")
    assert store.names() == ()


def test_template_storage_rejects_duplicate_and_damaged_settings(tmp_path: Path) -> None:
    from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore

    settings = QSettings(str(tmp_path / "templates.ini"), QSettings.Format.IniFormat)
    store = ToleranceTemplateStore(settings)
    rows = (ToleranceRow("flatness", 0.1, 2),)
    store.save("样板", rows)
    with pytest.raises(ValueError, match="名称"):
        store.save("样板", rows)
    assert store.get("样板") == rows
    settings.setValue("drawing2d/toleranceTemplates", "invalid")
    with pytest.raises(ValueError, match="损坏"):
        store.save("新样板", rows)
    assert settings.value("drawing2d/toleranceTemplates") == "invalid"


def test_template_storage_survives_process_restart(tmp_path: Path) -> None:
    from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore

    path = tmp_path / "templates.ini"
    store = ToleranceTemplateStore(QSettings(str(path), QSettings.Format.IniFormat))
    store.save("跨进程", (ToleranceRow("flatness", 0.05, 2),))
    program = (
        "import sys; from PySide6.QtCore import QSettings; "
        "from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore; "
        "s = ToleranceTemplateStore(QSettings(sys.argv[1], QSettings.Format.IniFormat)); "
        "print(s.names() == ('跨进程',), s.get(s.names()[0])[0].value)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(path)],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.stdout.strip() == "True 0.05"


def test_template_name_dialog_has_room_for_title(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
    from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore

    store = ToleranceTemplateStore(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    dialog = GeometricToleranceDialog(template_store=store)
    qtbot.addWidget(dialog)
    dialog.show()
    widths: list[int] = []

    def inspect() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, QInputDialog)
        widths.append(modal.width())
        modal.reject()

    QTimer.singleShot(50, inspect)
    QTest.mouseClick(dialog.save_template_button, Qt.MouseButton.LeftButton)
    assert widths and widths[0] >= 320


def test_dialog_saves_and_applies_template_with_explicit_datum_link(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
    from mycad.ui.geometric_tolerance_templates import ToleranceTemplateStore

    store = ToleranceTemplateStore(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (1, 1))
    source = ToleranceRow("position", 0.123, 3, True, "M", (DatumReference("A", datum.datum_id),))
    dialog = GeometricToleranceDialog((source,), (datum,), template_store=store)
    qtbot.addWidget(dialog)
    dialog.show()

    def name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "定位", True

    def no(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.No

    def yes(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QInputDialog, "getText", name)
    QTest.mouseClick(dialog.save_template_button, Qt.MouseButton.LeftButton)
    assert store.names() == ("定位",)
    dialog.rows[0].value.setValue(0.5)
    monkeypatch.setattr(QMessageBox, "question", no)
    QTest.mouseClick(dialog.apply_template_button, Qt.MouseButton.LeftButton)
    assert dialog.values()[0].value == 0.5
    monkeypatch.setattr(QMessageBox, "question", yes)
    QTest.mouseClick(dialog.apply_template_button, Qt.MouseButton.LeftButton)
    assert dialog.values()[0].datums == (DatumReference("A"),)
    assert dialog.rows[0].datum_statuses[0].text() == "未关联"
    QTest.mouseClick(dialog.rows[0].datum_link_buttons[0], Qt.MouseButton.LeftButton)
    assert dialog.values()[0].datums == (DatumReference("A", datum.datum_id),)
    QTest.mouseClick(dialog.delete_template_button, Qt.MouseButton.LeftButton)
    assert store.names() == ()
