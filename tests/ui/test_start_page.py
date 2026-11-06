# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Start page routes supported document kinds without creating assemblies."""

from functools import partial
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from pytestqt.qtbot import QtBot

from mycad.ui.document_session import SessionDocument
from mycad.ui.start_page import StartPage


def _close_choice(
    choice: str | None, identity: str, _entries: tuple[SessionDocument, ...]
) -> dict[str, str] | None:
    return None if choice is None else {identity: choice}


@pytest.mark.parametrize("signal", ["busy_changed", "result_ready"])
def test_home_waits_for_result_handoff(qtbot: QtBot, signal: str) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    entered, release = Event(), Event()
    completed: list[tuple[object, bool]] = []

    def work() -> None:
        entered.set()
        assert release.wait(10)

    def on_busy_changed(busy: bool) -> None:
        if not busy:
            window.show_start_page()

    def on_result(_result: object) -> None:
        window.show_start_page()

    if signal == "busy_changed":
        unit.busy_changed.connect(on_busy_changed)
    else:
        unit.result_ready.connect(on_result)
    assert unit.submit(
        work,
        operation="test-home-handoff",
        session_id=unit.session_id,
        on_complete=lambda _result: completed.append(
            (session.active, window.workspace_container.isVisible())
        ),
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(completed), timeout=10000)
    assert completed == [(entry, True)]
    window.show_start_page()
    assert window.start_page.isVisible()


@pytest.mark.parametrize("via_tab", [False, True])
def test_document_close_during_idle_notification_preserves_completion(
    qtbot: QtBot, via_tab: bool
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part", placeholder=True)
    unit = window.execution_unit
    assert unit is not None
    entered, release = Event(), Event()
    completed: list[object] = []

    def work() -> None:
        entered.set()
        assert release.wait(10)

    def busy_changed(busy: bool) -> None:
        if not busy:
            if via_tab:
                window.document_tab_bar.tabCloseRequested.emit(0)
            else:
                window.close_active_document()

    def finish(_result: object) -> None:
        completed.append(session.active)

    unit.busy_changed.connect(busy_changed)
    assert unit.submit(work, operation="test-close", session_id=unit.session_id, on_complete=finish)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(completed), timeout=10000)
    assert completed == [entry]
    assert session.active is entry
    window.close_active_document()
    assert not session.documents


def test_start_page_routes_each_supported_kind(qtbot: QtBot) -> None:
    page = StartPage()
    qtbot.addWidget(page)
    page.show()
    spy = QSignalSpy(page.create_requested)
    for button in (page.drawing_button, page.engineering_button, page.part_button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert [spy.at(index)[0] for index in range(spy.count())] == ["sketch", "drawing", "part"]
    assert not page.assembly_button.isEnabled()
    assert "规划中" in page.assembly_button.text()
    QTest.mouseClick(page.assembly_button, Qt.MouseButton.LeftButton)
    assert spy.count() == 3


def test_start_page_open_action_requests_file_selection(qtbot: QtBot) -> None:
    page = StartPage()
    qtbot.addWidget(page)
    page.show()
    spy = QSignalSpy(page.open_requested)
    QTest.mouseClick(page.open_button, Qt.MouseButton.LeftButton)
    assert spy.count() == 1


def test_start_page_creates_a_part_in_an_empty_session(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()
    assert window.start_page.isVisible()
    assert not session.documents
    QTest.mouseClick(window.start_page.part_button, Qt.MouseButton.LeftButton)
    assert session.active is not None
    assert session.active.kind == "part"
    assert len(session.documents) == 1
    assert not window.start_page.isVisible()
    assert window.active_workspace == "model"


@pytest.mark.parametrize(
    ("button_name", "expected_kind", "workspace"),
    (("drawing_button", "sketch", "sketch"), ("engineering_button", "drawing", "drawing")),
)
def test_start_page_creates_independent_documents(
    qtbot: QtBot, button_name: str, expected_kind: str, workspace: str
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()
    button = getattr(window.start_page, button_name)
    if button_name == "engineering_button":
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog

        def accept_template() -> None:
            dialog = window.findChild(QDialog, "drawingTemplateDialog")
            if dialog is not None:
                dialog.accept()

        QTimer.singleShot(0, accept_template)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert session.active is not None
    assert session.active.kind == expected_kind
    assert len(session.documents) == 1
    assert window.active_workspace == workspace
    assert not window.start_page.isVisible()


def test_return_home_keeps_open_part_sketch_draft(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    window.show_start_page()
    assert window.start_page.isVisible()
    assert session.active is entry
    assert window.part_sketch_task is task
    assert task.has_draft
    QTest.mouseClick(window.start_page.part_button, Qt.MouseButton.LeftButton)
    assert len(session.documents) == 1
    assert window.start_page.isVisible()
    QTest.mouseClick(window.start_page.resume_button, Qt.MouseButton.LeftButton)
    assert not window.start_page.isVisible()
    assert window.part_sketch_task is task and task.has_draft
    task.reject()


def test_drawing_from_home_keeps_part_toolbar_hidden(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()
    QTest.mouseClick(window.start_page.drawing_button, Qt.MouseButton.LeftButton)
    assert window.active_workspace == "sketch"
    assert window.modeling_toolbar.isHidden()
    assert window.part_sketch_entry_toolbar.isHidden()


def test_close_last_document_respects_cancel_then_returns_home(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, None, entry.loaded.document.document_id),
    )
    window.close_active_document()
    assert session.active is entry
    assert not window.start_page.isVisible()
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "discard", entry.loaded.document.document_id),
    )
    window.close_active_document()
    assert not session.documents
    assert session.active is None
    assert window.loaded_document() is None
    assert window.start_page.isVisible()


def test_document_tab_close_button_respects_cancel_and_closes_target(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QTabBar, QWidget

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    second = window.new_session_document("part")
    bar = window.document_tab_bar
    assert bar.tabsClosable()
    button = cast("QWidget | None", bar.tabButton(0, QTabBar.ButtonPosition.RightSide))
    if button is None:
        button = bar.tabButton(0, QTabBar.ButtonPosition.LeftSide)
    assert button is not None
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, None, first.loaded.document.document_id),
    )
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert session.documents == (first, second)
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "discard", first.loaded.document.document_id),
    )
    button = cast("QWidget | None", bar.tabButton(0, QTabBar.ButtonPosition.RightSide))
    if button is None:
        button = bar.tabButton(0, QTabBar.ButtonPosition.LeftSide)
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert session.documents == (second,)
    assert session.active is second
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "discard", second.loaded.document.document_id),
    )
    button = cast("QWidget | None", bar.tabButton(0, QTabBar.ButtonPosition.RightSide))
    if button is None:
        button = bar.tabButton(0, QTabBar.ButtonPosition.LeftSide)
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not session.documents
    assert window.start_page.isVisible()


def test_close_active_document_activates_another_open_document(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    first = window.new_session_document("part")
    second = window.new_session_document("part")
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "discard", second.loaded.document.document_id),
    )
    window.close_active_document()
    assert session.active is first
    assert session.documents == (first,)
    assert window.loaded_document() is first.loaded


@pytest.mark.parametrize("failure", ["cancel", "error"])
def test_close_document_keeps_document_when_save_does_not_succeed(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from PySide6.QtWidgets import QFileDialog

    from mycad.app import build_app
    from mycad.ui import document_save
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "save", entry.loaded.document.document_id),
    )
    path = "" if failure == "cancel" else str(tmp_path / "model.my3d")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (path, "")))
    if failure == "error":

        def fail_save(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(document_save, "save_document", fail_save)
    window.close_active_document()
    assert session.active is entry
    assert session.documents == (entry,)
    assert window.loaded_document() is entry.loaded
    assert entry.needs_save


def test_close_last_drawing_does_not_create_implicit_part(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "discard", entry.loaded.document.document_id),
    )
    window.close_active_document()
    assert not session.documents
    assert window.start_page.isVisible()


def test_engineering_template_cancel_creates_no_document(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()

    def cancel() -> None:
        dialog = window.findChild(QDialog, "drawingTemplateDialog")
        if dialog is not None:
            dialog.reject()

    QTimer.singleShot(0, cancel)
    QTest.mouseClick(window.start_page.engineering_button, Qt.MouseButton.LeftButton)
    assert not session.documents
    assert session.active is None
    assert window.start_page.isVisible()


def test_engineering_default_template_creates_sheet_without_model(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()

    def accept() -> None:
        dialog = window.findChild(QDialog, "drawingTemplateDialog")
        if dialog is not None:
            dialog.accept()

    QTimer.singleShot(0, accept)
    QTest.mouseClick(window.start_page.engineering_button, Qt.MouseButton.LeftButton)
    assert session.active is not None and session.active.kind == "drawing"
    entry = session.active
    qtbot.waitUntil(lambda: len(entry.services.kernel.drawing_state.sheets) == 1)
    sheet = entry.services.kernel.drawing_state.sheets[0]
    assert sheet.template is not None and sheet.template.standard.startswith("GB")
    assert len(session.documents) == 1
    assert not entry.services.kernel.document_references
    assert entry.workbench is not None
    assert not entry.workbench.base_action.isEnabled()
    assert "来源" in entry.workbench.start_description.text()


def test_engineering_template_failure_reports_and_can_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import NoReturn

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    from mycad.app import build_app
    from mycad.core.bus import CommandBus
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    original_execute = CommandBus.execute

    def fail_sheet(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("测试图纸创建失败")

    monkeypatch.setattr(CommandBus, "execute", fail_sheet)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()

    def accept() -> None:
        dialog = window.findChild(QDialog, "drawingTemplateDialog")
        if dialog is not None:
            dialog.accept()

    QTimer.singleShot(0, accept)
    QTest.mouseClick(window.start_page.engineering_button, Qt.MouseButton.LeftButton)
    entry = session.active
    assert entry is not None and entry.kind == "drawing" and entry.workbench is not None
    bench = entry.workbench
    qtbot.waitUntil(lambda: "测试图纸创建失败" in bench.hint.text(), timeout=10000)
    assert not entry.loaded.document.commands
    assert not entry.services.kernel.drawing_state.sheets
    assert session.active is entry and session.documents == (entry,)
    monkeypatch.setattr(CommandBus, "execute", original_execute)
    bench.create_sheet()
    qtbot.waitUntil(lambda: len(entry.services.kernel.drawing_state.sheets) == 1, timeout=10000)
    assert len(entry.loaded.document.commands) == 1


def test_home_hides_document_menus_until_a_document_is_active(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show_start_page()
    window.show()
    assert not window.menu_feature.menuAction().isVisible()
    assert window.menu_file.menuAction().isVisible()
    QTest.mouseClick(window.start_page.part_button, Qt.MouseButton.LeftButton)
    assert window.menu_feature.menuAction().isVisible()


def test_closing_home_does_not_save_hidden_workspace_layout(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    first = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(first)
    first.modeling_toolbar.show()
    assert not first.modeling_toolbar.isHidden()
    first.show_start_page()
    first.show()
    first.close()
    second = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(second)
    assert not second.modeling_toolbar.isHidden()


def test_cancel_save_from_home_stays_on_home(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    window.show_start_page()
    monkeypatch.setattr(
        window,
        "_ask_session_close_dialog",
        partial(_close_choice, "save", entry.loaded.document.document_id),
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    window.close_active_document()
    assert session.active is entry
    assert window.start_page.isVisible()


def test_switching_workspace_does_not_create_document_during_part_draft(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    window.workspace_tabs.activate("sketch")
    assert session.documents == (part,)
    assert session.active is part
    assert window.active_workspace == "model"
    assert task.has_draft
    task.reject()


def test_new_drawing_while_worker_busy_does_not_create_document(qtbot: QtBot) -> None:
    from threading import Event

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    part = window.new_session_document("part")
    unit = window.execution_unit
    assert unit is not None
    release = Event()
    try:
        assert unit.submit(
            lambda: release.wait(5),
            operation="test",
            session_id=window.drawing_workbench.session_id,
            on_complete=lambda _result: None,
        )
        window.act_new_drawing.trigger()
        assert session.documents == (part,)
        assert session.active is part
    finally:
        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy)


def test_home_preserves_active_modeling_command_and_blocks_new_document(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.box")
    bar = window.modeling_command_bar
    assert bar is not None and bar.isVisible()
    window.show_start_page()
    assert window.start_page.isVisible() and not bar.isVisible()
    QTest.mouseClick(window.start_page.drawing_button, Qt.MouseButton.LeftButton)
    assert session.documents == (part,)
    assert window.start_page.isVisible()
    window.close_active_document()
    assert session.documents == (part,)
    QTest.mouseClick(window.start_page.resume_button, Qt.MouseButton.LeftButton)
    assert bar.isVisible() and bar.command_id == "feature.box"
    bar.cancel_requested.emit()
