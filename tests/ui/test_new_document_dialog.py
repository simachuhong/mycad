# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The common New entry chooses document type before replacing state."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("kind", ["drawing2d", "part"])
def test_common_new_dialog_routes_selected_document(qtbot: QtBot, kind: str) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()

    def select_type() -> None:
        dialog = window.new_document_dialog
        assert dialog is not None
        assert not dialog.assembly_button.isEnabled()
        button = dialog.drawing_button if kind == "drawing2d" else dialog.part_button
        assert not button.icon().isNull()
        button.click()
        dialog.create_button.click()

    QTimer.singleShot(0, select_type)
    window.act_new.trigger()
    loaded = window.loaded_document()
    assert loaded is not None and loaded.document.document_type == kind
    draft = window.active_sketch_dialog()
    if kind == "drawing2d":
        assert (
            draft is not None
            and window.workspace_tabs.content("sketch") is draft
            and window.active_workspace == "sketch"
        )
        draft.reject()
    else:
        assert (
            draft is None
            and window.workspace_tabs.content("model") is window.viewport
            and window.active_workspace == "model"
        )
    assert window.new_document_dialog is None


def test_cancel_type_dialog_preserves_document(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, confirmed_by="local"
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    before = tuple(loaded.document.commands)

    def cancel() -> None:
        dialog = window.new_document_dialog
        assert dialog is not None
        dialog.cancel_button.click()

    QTimer.singleShot(0, cancel)
    window.act_new.trigger()
    assert window.loaded_document() is loaded
    assert loaded.document.commands == before
