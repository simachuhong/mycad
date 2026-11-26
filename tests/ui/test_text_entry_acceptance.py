# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Entry-point and document-lifecycle acceptance for pending text."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.text_style_dialog import TextStyleDialog


def test_menu_toolbar_and_command_bar_share_document(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.text_tools
    assert tools is not None
    toolbar = {action.text(): action for action in editor.drawing_toolbar.actions()}
    assert {"单行文字", "多行文字", "文字样式"} <= set(toolbar)
    for action, value in (
        (window.act_text, "menu TEXT"),
        (window.act_mtext, "menu MTEXT"),
        (toolbar["单行文字"], "toolbar TEXT"),
        (toolbar["多行文字"], "toolbar MTEXT"),
    ):
        before = loaded.document.command_count
        action.trigger()
        assert tools.pending
        tools.place((10, 20))
        tools.editor.setPlainText(value)
        tools.commit()
        assert not tools.pending
        assert loaded.document.command_count == before + 1
        assert services.kernel.drawing_texts[-1].text == value
    opened: list[TextStyleDialog] = []

    def reject(dialog: TextStyleDialog) -> int:
        opened.append(dialog)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(TextStyleDialog, "exec", reject)
    for action in (window.act_text_style, toolbar["文字样式"]):
        action.trigger()
    editor.drawing_command_bar.input.setText("STYLE")
    editor.drawing_command_bar.submit()
    assert len(opened) == 3
    before = loaded.document.command_count
    editor.drawing_command_bar.input.setText('MTEXT 30,40 4 0 "中文 ABC"')
    editor.drawing_command_bar.submit()
    assert loaded.document.command_count == before + 1
    assert services.kernel.drawing_texts[-1].kind == "mtext"
    assert services.kernel.drawing_texts[-1].text == "中文 ABC"
    before = loaded.document.commands
    editor.drawing_command_bar.input.setText('TEXT 10,20 -1 0 "bad"')
    editor.drawing_command_bar.submit()
    assert loaded.document.commands == before
    assert "字高" in editor.canvas.message
    tools.cancel()
    assert not tools.pending


def test_pending_text_blocks_switch_and_close_until_cancelled(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    session = DocumentSession()
    window = MainWindow(services=services, document_session=session)
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    second = window.new_session_document("sketch")
    window.activate_session_document(first.loaded.document.document_id)
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.text_tools is not None
    tools = editor.canvas.text_tools
    assert tools.begin("text")
    tools.place((1, 2))
    tools.editor.setPlainText("尚未提交")
    before = first.loaded.document.commands
    window.request_redo()
    assert tools.pending and tools.editor.toPlainText() == "尚未提交"
    assert "文字" in window.status_command.text()
    window.activate_session_document(second.loaded.document.document_id)
    assert session.active is first
    assert tools.pending and tools.editor.toPlainText() == "尚未提交"
    assert "文字" in window.status_command.text()
    documents_before = session.documents
    window.act_new_drawing.trigger()
    assert session.documents == documents_before
    assert session.active is first and tools.pending
    assert "文字" in window.status_command.text()
    window.act_new.trigger()
    assert session.documents == documents_before and session.active is first
    assert tools.pending and "文字" in window.status_command.text()
    window.close_active_document()
    assert session.active is first and first in session.documents
    assert tools.pending and first.loaded.document.commands == before
    assert "文字" in window.status_command.text()
    tools.cancel()
    window.activate_session_document(second.loaded.document.document_id)
    assert session.active is second


def test_pending_text_blocks_open_before_starting_session_work(
    qtbot: QtBot, tmp_path: Path
) -> None:
    session = DocumentSession()
    window = MainWindow(services=app.build_app(discoverers=()), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.text_tools is not None
    tools = editor.canvas.text_tools
    assert tools.begin("text")
    tools.place((1, 2))
    tools.editor.setPlainText("待确认")
    documents_before = session.documents
    window.open_document_path(tmp_path / "not-opened.my2d")
    assert session.documents == documents_before and session.active is entry
    assert tools.pending and tools.editor.toPlainText() == "待确认"
    assert "文字" in window.status_command.text()
    assert not window.execution_unit or not window.execution_unit.is_busy
