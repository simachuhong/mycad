# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Recent files preserve metadata and never modify the referenced files."""

from pathlib import Path

from PySide6.QtCore import QSettings

from mycad.ui.recent_documents import RecentDocuments


def test_recent_documents_persist_deduplicate_and_remove(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    first = tmp_path / "first.my3d"
    second = tmp_path / "second.my2d"
    first.write_text("keep", encoding="utf-8")
    records = RecentDocuments(settings)
    records.add(first, "part")
    records.add(second, "drawing")
    records.add(first, "part")
    reread = RecentDocuments(settings)
    assert [record.path for record in reread.items] == [first, second]
    assert [record.kind for record in reread.items] == ["part", "drawing"]
    assert all(record.opened_at for record in reread.items)
    reread.remove(first)
    assert [record.path for record in RecentDocuments(settings).items] == [second]
    reread.clear()
    assert not RecentDocuments(settings).items
    assert first.read_text(encoding="utf-8") == "keep"


def test_recent_documents_deduplicate_equivalent_paths(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    target = tmp_path / "part.my3d"
    target.write_text("keep", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    alias = tmp_path / "folder" / ".." / "part.my3d"
    records = RecentDocuments(settings)
    records.add(target, "part")
    records.add(alias, "part")
    assert len(records.items) == 1
    records.remove(target)
    assert not records.items
    assert target.read_text(encoding="utf-8") == "keep"


def test_recent_documents_deduplicate_symlink_when_available(tmp_path: Path) -> None:
    import pytest

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    target = tmp_path / "part.my3d"
    target.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias.my3d"
    try:
        alias.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    records = RecentDocuments(settings)
    records.add(target, "part")
    records.add(alias, "part")
    assert len(records.items) == 1
    records.remove(target)
    assert not records.items
    assert target.read_text(encoding="utf-8") == "keep"


def test_recent_documents_can_remove_unresolvable_symlink(tmp_path: Path) -> None:
    import pytest

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    loop = tmp_path / "loop.my3d"
    try:
        loop.symlink_to(loop.name)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    records = RecentDocuments(settings)
    records.add(loop, "part")
    assert len(records.items) == 1
    records.remove(loop)
    assert not records.items


def test_recent_documents_can_remove_path_with_invalid_character(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    records = RecentDocuments(settings)
    invalid = tmp_path / "invalid\0file.my3d"
    records.add(invalid, "part")
    assert len(records.items) == 1
    records.remove(invalid)
    assert not records.items


def test_recent_documents_ignore_corrupt_settings(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("recent/documents_v1", "not json")
    assert not RecentDocuments(settings).items


def test_start_page_recent_actions_identify_selected_path(qtbot: object, tmp_path: Path) -> None:
    from PySide6.QtTest import QSignalSpy
    from pytestqt.qtbot import QtBot

    from mycad.ui.recent_documents import RecentDocument
    from mycad.ui.start_page import StartPage

    assert isinstance(qtbot, QtBot)
    page = StartPage()
    qtbot.addWidget(page)
    path = tmp_path / "missing.my3d"
    page.set_recent_documents((RecentDocument(path, "part", "2026-11-04T00:00:00+00:00"),))
    page.recent_list.setCurrentRow(0)
    spy = QSignalSpy(page.recent_open_requested)
    page.recent_open_button.click()
    assert spy.count() == 1 and spy.at(0)[0] == str(path)
    remove = QSignalSpy(page.recent_remove_requested)
    page.recent_remove_button.click()
    assert remove.count() == 1 and remove.at(0)[0] == str(path)


def test_saved_document_appears_in_home_recent_list(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    import pytest
    from PySide6.QtWidgets import QFileDialog
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("part")
    target = tmp_path / "test.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(target.exists)
    assert entry.path == target
    window.show_start_page()
    assert window.start_page.recent_list.count() == 1
    assert str(target) in window.start_page.recent_list.item(0).text()


def test_recent_open_restores_real_document_and_failed_open_preserves_active(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    import pytest
    from PySide6.QtWidgets import QFileDialog
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    target = tmp_path / "model.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(target.exists)
    window.close_active_document()
    assert not session.documents
    window.start_page.recent_open_requested.emit(str(target))
    qtbot.waitUntil(lambda: session.active is not None)
    assert session.active is not None and session.active.kind == "part"
    assert session.active.path == target
    active = session.active
    damaged = tmp_path / "damaged.my2d"
    damaged.write_text("not a document", encoding="utf-8")
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.start_page.recent_open_requested.emit(str(damaged))
    qtbot.waitUntil(lambda: bool(errors))
    assert session.active is active
    assert session.documents == (active,)
    window.start_page.recent_open_requested.emit(str(tmp_path / "missing.my3d"))
    assert len(errors) == 2
    assert session.active is active


def test_locating_a_moved_recent_file_updates_history_after_open(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    import pytest
    from PySide6.QtWidgets import QFileDialog
    from pytestqt.qtbot import QtBot

    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    assert isinstance(qtbot, QtBot)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("part")
    old = tmp_path / "old.my3d"
    moved = tmp_path / "moved.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(old), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(old.exists)
    window.close_active_document()
    old.rename(moved)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(moved), ""))
    )
    window.start_page.recent_locate_requested.emit(str(old))
    qtbot.waitUntil(lambda: session.active is not None)
    assert session.active is not None and session.active.path == moved
    assert [record.path for record in window.recent_documents.items] == [moved]


def test_recent_actions_require_a_selection(qtbot: object, tmp_path: Path) -> None:
    from pytestqt.qtbot import QtBot

    from mycad.ui.recent_documents import RecentDocument
    from mycad.ui.start_page import StartPage

    assert isinstance(qtbot, QtBot)
    page = StartPage()
    qtbot.addWidget(page)
    assert not page.recent_open_button.isEnabled()
    assert not page.recent_remove_button.isEnabled()
    assert not page.recent_clear_button.isEnabled()
    page.set_recent_documents((RecentDocument(tmp_path / "a.my3d", "part", "2026-11-04"),))
    assert page.recent_clear_button.isEnabled()
    assert not page.recent_open_button.isEnabled()
    page.recent_list.setCurrentRow(0)
    assert page.recent_open_button.isEnabled()
    assert page.recent_remove_button.isEnabled()
