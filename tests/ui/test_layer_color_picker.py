# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The drawing layer manager applies only confirmed color selections."""

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.layer_panel import DrawingLayerPanel


def test_layer_color_picker_applies_selection_and_ignores_cancel(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    layers = SketchLayerTable(
        (SketchLayer("0", color_rgb=(12, 34, 56)), SketchLayer("DIM", color_rgb=(1, 2, 3)))
    )
    panel = DrawingLayerPanel(layers, "0", "DIM", ())
    qtbot.addWidget(panel)
    updates: list[SketchLayerTable] = []

    def record_update(table: SketchLayerTable, _dimension: str) -> None:
        updates.append(table)

    panel.properties_changed.connect(record_update)
    initial_colors: list[tuple[int, int, int]] = []
    selections = iter((QColor(210, 40, 55), QColor()))

    def choose_color(initial: QColor, _parent: QWidget, _title: str) -> QColor:
        initial_colors.append((initial.red(), initial.green(), initial.blue()))
        return next(selections)

    monkeypatch.setattr(QColorDialog, "getColor", choose_color)
    button = panel.table.cellWidget(1, 4)
    assert isinstance(button, QPushButton)
    button.click()
    assert initial_colors == [(1, 2, 3)]
    assert panel.layer_table.get("DIM").color_rgb == (210, 40, 55)
    assert panel.layer_table.get("0").color_rgb == (12, 34, 56)
    assert len(updates) == 1
    assert updates[0].get("DIM").color_rgb == (210, 40, 55)

    button = panel.table.cellWidget(1, 4)
    assert isinstance(button, QPushButton)
    button.click()
    assert initial_colors[-1] == (210, 40, 55)
    assert panel.layer_table.get("DIM").color_rgb == (210, 40, 55)
    assert len(updates) == 1
