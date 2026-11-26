# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Style edits remain staged and font changes cannot reuse stale file requests."""

from pathlib import Path

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog

from mycad.core.drawing_text import TextStyle, TextStyleTable
from mycad.ui.font_manager import FontManager
from mycad.ui.text_style_dialog import TextStyleDialog


def test_add_rename_current_delete_and_cancel_are_staged(
    qapp: QApplication, tmp_path: Path
) -> None:
    original = TextStyleTable((TextStyle(), TextStyle("used", "已使用")))
    dialog = TextStyleDialog(original, frozenset({"used"}), FontManager(tmp_path))
    dialog.remove_style()
    assert len(dialog.table.styles) == 2
    dialog.styles.setCurrentIndex(dialog.styles.findData("used"))
    dialog.remove_style()
    assert len(dialog.table.styles) == 2
    assert "不能删除" in dialog.message.text()
    dialog.add_style()
    created_id = str(dialog.styles.currentData())
    assert created_id not in {"standard", "used"}
    dialog.name.setText("设计说明")
    assert dialog.save_style()
    assert dialog.table.get(created_id).name == "设计说明"
    dialog.set_current()
    assert dialog.table.current_id == created_id
    dialog.styles.setCurrentIndex(dialog.styles.findData("standard"))
    dialog.remove_style()
    assert {style.style_id for style in dialog.table.styles} == {"used", created_id}
    dialog.reject()
    assert dialog.result() == int(QDialog.DialogCode.Rejected)
    assert original == TextStyleTable((TextStyle(), TextStyle("used", "已使用")))


def test_changed_family_and_style_clear_file_before_font_lookup(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = FontManager(tmp_path)
    families = manager.families()
    assert families
    original = TextStyle(font_family="Missing Original Family", font_file="missing-original.ttf")
    dialog = TextStyleDialog(TextStyleTable((original,)), frozenset(), manager)
    queries: list[TextStyle] = []

    def filename(style: TextStyle) -> str:
        queries.append(style)
        return "chosen-font.ttf"

    monkeypatch.setattr(manager, "font_file", filename)
    dialog.family.setCurrentText(families[0])
    assert dialog.save_style()
    assert queries[-1].font_file == ""
    assert dialog.table.current.font_file == "chosen-font.ttf"
    dialog.font_style.setCurrentText("A different face")
    assert dialog.save_style()
    assert queries[-1].font_file == ""


def test_unchanged_missing_font_request_survives_other_style_edits(
    qapp: QApplication, tmp_path: Path
) -> None:
    original = TextStyle(
        font_family="Missing Original Family",
        font_style="Missing Face",
        font_file="missing-original.ttf",
    )
    dialog = TextStyleDialog(TextStyleTable((original,)), frozenset(), FontManager(tmp_path))
    dialog.name.setText("新名称")
    assert dialog.save_style()
    saved = dialog.table.current
    assert (saved.font_family, saved.font_style, saved.font_file) == (
        original.font_family,
        original.font_style,
        original.font_file,
    )


def test_font_face_choices_follow_selected_native_family(
    qapp: QApplication, tmp_path: Path
) -> None:
    manager = FontManager(tmp_path)
    family = manager.families()[0]
    dialog = TextStyleDialog(TextStyleTable(), frozenset(), manager)
    dialog.family.setCurrentText(family)
    assert [
        dialog.font_style.itemText(index) for index in range(dialog.font_style.count())
    ] == QFontDatabase.styles(family)
    if dialog.font_style.count():
        dialog.font_style.setCurrentIndex(dialog.font_style.count() - 1)
        assert dialog.save_style()
        assert dialog.table.current.font_style == QFontDatabase.styles(family)[-1]
