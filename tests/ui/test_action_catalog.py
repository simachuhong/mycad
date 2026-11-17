# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A shared action identity must not fork state between entry points."""

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QToolButton
from pytestqt.qtbot import QtBot

from mycad.ui.action_catalog import ActionCatalog


def test_two_entries_share_action_state(qtbot: QtBot) -> None:
    catalog = ActionCatalog()
    action = QAction("选择")
    action.setCheckable(True)
    catalog.register("select", action)
    first, second = QToolButton(), QToolButton()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    first.setDefaultAction(catalog.get("select"))
    second.setDefaultAction(catalog.get("select"))
    first.click()
    assert second.isChecked()
    action.setEnabled(False)
    assert not first.isEnabled() and not second.isEnabled()


def test_duplicate_identity_cannot_replace_a_different_action(qapp: QApplication) -> None:
    catalog = ActionCatalog()
    original = QAction("原动作")
    catalog.register("save", original)
    catalog.register("save", original)
    with pytest.raises(ValueError):
        catalog.register("save", QAction("其他动作"))
    assert catalog.get("save") is original
    with pytest.raises(KeyError):
        catalog.get("missing")


def test_main_window_catalog_reuses_existing_actions(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    catalog = window.action_catalog
    assert catalog.get("file.save") is window.act_save
    assert catalog.get("edit.undo") is window.act_undo
    assert catalog.get("ui.view.fit") is window.act_fit_view
    assert catalog.get("ui.view.2d") is window.act_view_2d
    box = catalog.get("feature.box")
    assert box in window.modeling_toolbar.actions()
    assert box in window.menu_feature.actions()
    assert catalog.get("part-sketch.rectangle") is window.act_part_rectangle


def test_ribbon_page_change_does_not_create_or_switch_document(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    part = window.new_session_document("part")
    window.part_ribbon.setCurrentIndex(1)
    assert session.documents == (part,)
    assert session.active is part
    assert window.loaded_document() is part.loaded


def test_session_document_actions_follow_open_and_close(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    actions = tuple(
        window.action_catalog.get(identity)
        for identity in (
            "file.close",
            "file.save",
            "file.save-as",
            "file.save-all",
            "file.import",
            "file.export",
            "edit.undo",
            "edit.redo",
        )
    )
    assert all(not action.isEnabled() for action in actions)
    assert not window.action_catalog.get("feature.box").isEnabled()
    part = window.new_session_document("part")
    assert all(action.isEnabled() for action in actions)
    assert window.action_catalog.get("feature.box").isEnabled()
    window.show_start_page()
    assert session.active is part
    assert all(action.isEnabled() for action in actions)
    window.close_active_document()
    assert not session.documents
    assert all(not action.isEnabled() for action in actions)
    assert not window.action_catalog.get("feature.box").isEnabled()
