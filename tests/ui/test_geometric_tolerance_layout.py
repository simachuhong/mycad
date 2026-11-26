# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric frame cells preserve rows, datums and matching bounds."""

from collections.abc import Callable
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtGui import QImage, QPainter, QTextLayout
from pytestqt.qtbot import QtBot

from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow
from mycad.ui.font_manager import FontManager
from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog
from mycad.ui.geometric_tolerance_layout import layout_frame


def _text_response(value: str) -> Callable[..., tuple[str, bool]]:
    def respond(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return value, True

    return respond


def test_multiline_frame_layout_is_visible_and_contains_all_cells(qtbot: QtBot) -> None:
    rows = (
        ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A"), DatumReference("B"))),
        ToleranceRow("flatness", 0.1, 1),
    )
    frame = FeatureControlFrame(uuid4().hex, rows, (0, 0))
    layout = layout_frame(frame, FontManager())
    assert len(layout.rows) == 2
    assert tuple(len(row.cells) for row in layout.rows) == (4, 2)
    assert all(layout.bounds.contains(cell.bounds) for row in layout.rows for cell in row.cells)
    image = QImage(600, 250, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    painter.scale(8, 8)
    layout.draw(painter)
    painter.end()
    assert any(
        image.pixelColor(x, y).red() < 200 for x in range(5, 500, 5) for y in range(5, 200, 5)
    )


def test_frame_displays_negative_zero_as_unsigned_zero(qtbot: QtBot) -> None:
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", -0.0, 2),), (0, 0))
    cell = layout_frame(frame, FontManager()).rows[0].cells[1]
    assert cell.text is not None
    assert cast("tuple[QTextLayout, ...]", vars(cell.text)["_paragraphs"])[0].text() == "0.00"


def test_frame_warns_when_nonzero_tolerance_rounds_to_zero(qtbot: QtBot) -> None:
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 1e-10, 2),), (0, 0))
    cell = layout_frame(frame, FontManager()).rows[0].cells[1]
    assert cell.text is not None
    assert cast("tuple[QTextLayout, ...]", vars(cell.text)["_paragraphs"])[0].text() == "精度不足"


def test_frame_editor_reports_precision_loss(qtbot: QtBot) -> None:
    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    row = dialog.rows[0]
    row.value.setValue(0.001)
    row.precision.setValue(2)
    assert "精度不足" in row.value_notice.text()
    row.precision.setValue(3)
    assert "精度不足" not in row.value_notice.text()


def test_dialog_preview_updates_for_symbol_value_and_second_row(qtbot: QtBot) -> None:
    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    before = dialog.preview.grab().toImage()
    row = dialog.rows[0]
    row.characteristic.setCurrentIndex(row.characteristic.findData("position"))
    row.value.setValue(0.05)
    row.datums[0].setText("A")
    dialog.add_button.click()
    qtbot.wait(20)
    after = dialog.preview.grab().toImage()
    assert before != after
    assert len(dialog.preview.frame.rows) == 2
    assert dialog.preview.frame.rows[0].datums[0].label == "A"


def test_dialog_preview_uses_selected_text_style(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    table = TextStyleTable((TextStyle(), TextStyle("wide", "宽文字", width_factor=3)))
    dialog = GeometricToleranceDialog(text_styles=table)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.rows[0].datums[0].setText("A")
    before = dialog.preview.grab().toImage()
    dialog.text_style.setCurrentIndex(dialog.text_style.findData("wide"))
    qtbot.wait(20)
    assert dialog.preview.grab().toImage() != before


def test_symbol_choices_show_distinct_glyphs(qtbot: QtBot) -> None:
    from PySide6.QtCore import QSize

    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    choices = dialog.rows[0].characteristic
    straight = choices.itemIcon(choices.findData("straightness"))
    position = choices.itemIcon(choices.findData("position"))
    assert not straight.isNull() and not position.isNull()
    assert straight.pixmap(QSize(24, 24)).toImage() != position.pixmap(QSize(24, 24)).toImage()


def test_symbol_palette_selects_feature(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QToolButton

    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    row = dialog.rows[0]

    def choose() -> None:
        palette = QApplication.activeModalWidget()
        assert isinstance(palette, QDialog)
        button = palette.findChild(QToolButton, "symbol_position")
        assert button is not None
        button.click()

    QTimer.singleShot(20, choose)
    row.symbol_palette_button.click()
    assert row.characteristic.currentData() == "position"
    assert dialog.preview.frame.rows[0].characteristic == "position"


def test_editor_fields_follow_frame_order_horizontally(qtbot: QtBot) -> None:
    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1200, 700)
    dialog.show()
    qtbot.waitExposed(dialog)
    row = dialog.rows[0]
    fields = (row.characteristic, row.value, *row.datums)
    x_positions = [field.mapToGlobal(field.rect().center()).x() for field in fields]
    assert x_positions == sorted(x_positions)
    assert len(set(x_positions)) == len(fields)


def test_frame_layout_respects_text_style_width(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.123, 3),), (0, 0))
    manager = FontManager()
    normal = layout_frame(frame, manager, TextStyle(width_factor=1.0))
    wide = layout_frame(frame, manager, TextStyle(width_factor=2.0))
    assert wide.bounds.width() > normal.bounds.width()
    assert wide.bounds.height() == normal.bounds.height()


def test_frame_layout_scales_cells_with_text_height(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.123, 3, True, "M", (DatumReference("A", modifier="L"),)),),
        (0, 0),
    )
    manager = FontManager()
    normal = layout_frame(frame, manager, TextStyle(height_mm=3.5))
    large = layout_frame(frame, manager, TextStyle(height_mm=7))
    assert large.bounds.width() == pytest.approx(normal.bounds.width() * 2)
    assert large.bounds.height() == pytest.approx(normal.bounds.height() * 2)
    assert all(large.bounds.contains(cell.bounds) for row in large.rows for cell in row.cells)
    image = QImage(600, 250, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    painter.scale(4, 4)
    large.draw(painter)
    painter.end()
    assert any(
        image.pixelColor(x, y).red() < 200 for x in range(5, 500, 5) for y in range(5, 200, 5)
    )


def test_modifier_text_fits_circle_with_wide_style(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle

    frame = FeatureControlFrame(
        uuid4().hex,
        (
            ToleranceRow(
                "position", 0.1, 1, modifier="M", datums=(DatumReference("A", modifier="L"),)
            ),
        ),
        (0, 0),
    )
    layout = layout_frame(frame, FontManager(), TextStyle(height_mm=7, width_factor=8))
    cells = [cell for cell in layout.rows[0].cells if cell.modifier_text is not None]
    assert len(cells) == 2
    for cell in cells:
        assert cell.modifier_text is not None
        assert cell.modifier_text.bounds.width() * cell.modifier_scale <= 2.3 * layout.scale
        assert cell.modifier_text.bounds.height() * cell.modifier_scale <= 2.3 * layout.scale


def test_dialog_creates_multiple_rows_with_datum_order(qtbot: QtBot) -> None:
    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    first = dialog.rows[0]
    first.characteristic.setCurrentIndex(first.characteristic.findData("position"))
    first.value.setValue(0.05)
    first.diameter.setChecked(True)
    first.modifier.setCurrentIndex(first.modifier.findData("M"))
    first.datums[0].setText("A")
    first.datums[1].setText("B")
    dialog.add_button.click()
    dialog.rows[1].characteristic.setCurrentIndex(
        dialog.rows[1].characteristic.findData("flatness")
    )
    dialog.rows[1].value.setValue(0.1)
    rows = dialog.values()
    assert len(rows) == 2
    assert rows[0] == ToleranceRow(
        "position", 0.05, 2, True, "M", (DatumReference("A"), DatumReference("B"))
    )
    assert rows[1].characteristic == "flatness"


def test_frame_dialog_reports_substituted_font(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    manager = FontManager()

    def substitution(_style: TextStyle) -> str:
        return "替代字体"

    monkeypatch.setattr(manager, "substitution", substitution)
    table = TextStyleTable((TextStyle(), TextStyle("missing", "图纸字体", font_family="Missing")))
    dialog = GeometricToleranceDialog(text_styles=table, font_manager=manager)
    qtbot.addWidget(dialog)
    dialog.text_style.setCurrentIndex(dialog.text_style.findData("missing"))
    assert "Missing" in dialog.font_warning.text()
    assert "替代字体" in dialog.font_warning.text()


def test_unresolved_datum_reference_requires_explicit_relink(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier, DatumReference, ToleranceRow
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    original = ToleranceRow("position", 0.1, 1, datums=(DatumReference("A"),))
    dialog = GeometricToleranceDialog((original,), (datum,))
    qtbot.addWidget(dialog)
    row = dialog.rows[0]
    assert "未关联" in row.datum_statuses[0].text()
    assert dialog.values()[0].datums == (DatumReference("A"),)
    row.datum_link_buttons[0].click()
    assert "已关联" in row.datum_statuses[0].text()
    assert dialog.values()[0].datums == (DatumReference("A", datum.datum_id),)
    row.datums[0].setText("B")
    assert "未关联" in row.datum_statuses[0].text()
    assert not row.datum_link_buttons[0].isEnabled()
    assert "创建同名基准" in row.datum_link_buttons[0].toolTip()
    assert dialog.values()[0].datums == (DatumReference("B"),)


@pytest.mark.parametrize("value", (1e-10, 1e12))
def test_editing_other_properties_preserves_unrepresentable_tolerance_value(
    qtbot: QtBot, value: float
) -> None:
    row = ToleranceRow("position", value, 2)
    dialog = GeometricToleranceDialog((row,))
    qtbot.addWidget(dialog)
    editor = dialog.rows[0]
    editor.precision.setValue(3)
    assert dialog.values()[0].value == value
    assert "原始值" in editor.value_notice.text()
    editor.value.setValue(0.5)
    assert dialog.values()[0].value == 0.5
    assert not editor.value_notice.text()


def test_typing_displayed_rounded_value_intentionally_replaces_retained_value(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = GeometricToleranceDialog((ToleranceRow("position", 1e-10, 2),))
    qtbot.addWidget(dialog)
    dialog.show()
    editor = dialog.rows[0]
    line = editor.value.lineEdit()
    line.setFocus()
    line.selectAll()
    QTest.keyClicks(line, "0")
    QTest.keyClick(line, Qt.Key.Key_Enter)
    assert dialog.values()[0].value == 0
    assert not editor.value_notice.text()


def test_exact_tolerance_input_accepts_scientific_and_rejects_invalid(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    dialog = GeometricToleranceDialog()
    qtbot.addWidget(dialog)
    editor = dialog.rows[0]
    monkeypatch.setattr(QInputDialog, "getText", _text_response("1e-12"))
    editor.exact_value_button.click()
    assert dialog.values()[0].value == 1e-12
    assert "1e-12" in editor.value_notice.text()
    monkeypatch.setattr(QInputDialog, "getText", _text_response("nan"))
    editor.exact_value_button.click()
    assert editor.value.precise_value() == 1e-12
    assert "有限" in editor.value_notice.text()
    with pytest.raises(ValueError, match="有限"):
        dialog.values()


@pytest.mark.parametrize("text", ("1e309", "-1", "not-a-number", "1e-400"))
def test_exact_tolerance_input_rejects_invalid_without_mutation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    from PySide6.QtWidgets import QInputDialog

    dialog = GeometricToleranceDialog((ToleranceRow("position", 0.1, 2),))
    qtbot.addWidget(dialog)
    editor = dialog.rows[0]
    monkeypatch.setattr(QInputDialog, "getText", _text_response(text))
    editor.exact_value_button.click()
    assert editor.value.precise_value() == 0.1
    assert editor.value_notice.text()
    with pytest.raises(ValueError):
        dialog.values()


def test_invalid_exact_input_blocks_dialog_acceptance_until_corrected(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog

    dialog = GeometricToleranceDialog((ToleranceRow("position", 0.1, 2),))
    qtbot.addWidget(dialog)
    row = dialog.rows[0]
    monkeypatch.setattr(QInputDialog, "getText", _text_response("nan"))
    row.exact_value_button.click()
    dialog.accept()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert "有限" in dialog.message.text()
    row.value.setValue(0.2)
    dialog.accept()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog.values()[0].value == 0.2
