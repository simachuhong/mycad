# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Application font management is reachable without a drawing document."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from mycad.ui.font_manager import FontManager
from mycad.ui.font_resources import FontResourcesDialog
from mycad.ui.preferences import CursorSettingsDialog


def test_dialog_lists_fonts_and_previews_selection(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path)
    dialog = FontResourcesDialog(manager=manager)
    assert dialog.font_family.count() == len(manager.families())
    assert dialog.directory.text() == str(tmp_path)
    assert dialog.directory.isReadOnly()
    assert "取消" in dialog.persistence_notice.text()
    assert "操作系统" in dialog.persistence_notice.text()
    if dialog.font_family.count() > 1:
        dialog.font_family.setCurrentIndex(1)
    assert dialog.preview.font().family() == manager.resolve(dialog.selected_style()).family()
    dialog.sample.setText("新示例 ABC")
    assert dialog.preview.text() == "新示例 ABC"


def test_import_refreshes_selected_family_and_shows_failure(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = FontManager(tmp_path)
    families = list(manager.families())
    monkeypatch.setattr(manager, "families", lambda: tuple(families))
    dialog = FontResourcesDialog(manager=manager)
    path = tmp_path / "sample.ttf"

    def choose(*args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("mycad.ui.font_resources.QFileDialog.getOpenFileName", choose)

    def imported(source: Path) -> tuple[str, ...]:
        assert source == path
        families.append("Imported Example")
        return ("Imported Example",)

    monkeypatch.setattr(manager, "import_font", imported)
    dialog.import_button.click()
    assert dialog.font_family.currentText() == "Imported Example"
    assert "已导入" in dialog.status.text()

    def invalid(source: Path) -> tuple[str, ...]:
        raise ValueError("无效字体")

    monkeypatch.setattr(manager, "import_font", invalid)
    dialog.import_button.click()
    assert "无效字体" in dialog.status.text()
    assert dialog.font_family.currentText() == "Imported Example"


def test_system_preferences_opens_font_resources_without_document(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[FontResourcesDialog] = []

    def capture(dialog: FontResourcesDialog) -> int:
        opened.append(dialog)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(FontResourcesDialog, "exec", capture)
    preferences = CursorSettingsDialog("short")
    button = preferences.findChild(QPushButton, "fontResourcesButton")
    assert button is not None
    button.click()
    assert len(opened) == 1
    assert opened[0].parentWidget() is preferences
