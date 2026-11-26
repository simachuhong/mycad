# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension arrow settings remain independent when editing a style."""

from pytestqt.qtbot import QtBot

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.ui.drawing_dimension_styles import DrawingDimensionStylesDialog


def test_dimension_style_arrows_can_be_changed_independently(qtbot: QtBot) -> None:
    style = DimensionStyle("标准", arrow_first="open", arrow_second="tick")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), "标准"), frozenset())
    qtbot.addWidget(dialog)
    dialog.arrow_first.setCurrentIndex(dialog.arrow_first.findData("filled"))
    dialog.save_button.click()
    assert dialog.table.current.arrow_first == "filled"
    assert dialog.table.current.arrow_second == "tick"
