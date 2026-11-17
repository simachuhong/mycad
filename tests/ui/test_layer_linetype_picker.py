# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Layer linetypes are chosen through a preview and committed only on confirmation."""

from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QTableWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.layer_panel import DrawingLayerPanel
from mycad.ui.main_window import MainWindow


def test_linetype_dialog_applies_only_confirmed_choice(qtbot: QtBot) -> None:
    layers = SketchLayerTable(
        (SketchLayer("0"), SketchLayer("DIM", linetype="DASHED", color_rgb=(1, 2, 3)))
    )
    panel = DrawingLayerPanel(layers, "0", "DIM", ())
    qtbot.addWidget(panel)
    panel.show()
    updates: list[SketchLayerTable] = []

    def record_update(table: SketchLayerTable, _dimension: str) -> None:
        updates.append(table)

    panel.properties_changed.connect(record_update)
    observed: list[tuple[int, list[str], int]] = []

    def choose(*, accept: bool) -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog):
            return
        choices = dialog.findChild(QTableWidget, "linetypeChoices")
        buttons = dialog.findChild(QDialogButtonBox)
        if choices is None or buttons is None:
            dialog.reject()
            return
        names = [item.text() if (item := choices.item(row, 0)) else "" for row in range(4)]
        previews = sum(
            isinstance(cast("object", choices.cellWidget(row, 1)), QWidget) for row in range(4)
        )
        observed.append((choices.currentRow(), names, previews))
        choices.selectRow(3)
        standard = (
            QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel
        )
        button = cast("object", buttons.button(standard))
        if isinstance(button, QPushButton):
            button.click()
        else:
            dialog.reject()

    button = panel.table.cellWidget(1, 5)
    assert isinstance(button, QPushButton)
    QTimer.singleShot(0, lambda: choose(accept=False))
    button.click()
    assert observed == [(1, ["CONTINUOUS", "DASHED", "DOTTED", "DASHDOT"], 4)]
    assert panel.layer_table.get("DIM").linetype == "DASHED"
    assert not updates

    QTimer.singleShot(0, lambda: choose(accept=True))
    button.click()
    assert panel.layer_table.get("DIM").linetype == "DASHDOT"
    assert panel.layer_table.get("DIM").color_rgb == (1, 2, 3)
    assert panel.layer_table.get("0").linetype == "CONTINUOUS"
    assert len(updates) == 1
    assert updates[0].get("DIM").linetype == "DASHDOT"


def test_selected_linetype_is_undoable_in_drawing_document(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    editor.layer_manager_button.click()
    panel = editor.active_layer_manager
    assert panel is not None

    def select_dotted() -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog):
            return
        choices = dialog.findChild(QTableWidget, "linetypeChoices")
        if choices is not None:
            choices.selectRow(2)
            dialog.accept()
        else:
            dialog.reject()

    button = panel.table.cellWidget(0, 5)
    assert isinstance(button, QPushButton)
    QTimer.singleShot(0, select_dotted)
    button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 1, timeout=10000)
    assert services.kernel.drawing_layers.get("0").linetype == "DOTTED"
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and not loaded.document.commands, timeout=10000)
    assert services.kernel.drawing_layers.get("0").linetype == "CONTINUOUS"
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 1, timeout=10000)
    assert services.kernel.drawing_layers.get("0").linetype == "DOTTED"
