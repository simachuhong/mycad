# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document lifecycle: new / open / save / save-as / export / close guard.

计划 todo 8 验收：
- tmp_path 往返（new→命令→save→reopen 内容一致）；
- 脏态关闭拦截（QMessageBox 保存/放弃/取消三选，monkeypatch 分支）；
- undo（geometry_rebuilt）关拦截仍现；
- 保存成功 is_dirty=False（property）；
- 导出走 formats 既有 provider（STEP/STL）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QFileDialog

from mycad.app import build_app

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from pytestqt.qtbot import QtBot

    from mycad.app import AppServices

from mycad.core.persistence import LoadedDocument
from mycad.ui.main_window import MainWindow

# Teardown 兜底：pytest-qt 关窗时脏态窗口会走真实三选弹窗，offscreen 下
# exec 阻塞可挂死整个进程（faulthandler 栈实证）。本 autouse patch 注册
# 最先、最后还原——单个测试自打的 _ask_save_dialog patch 注册在后、先还
# 原，运行期语义不受影响；qtbot teardown 关窗落到 "discard" 保进程可退。


def _discard(self: MainWindow) -> str:
    return "discard"


@pytest.fixture(autouse=True)
def _autodiscard_close(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


def _loaded_of(window: MainWindow) -> LoadedDocument | None:
    return window.loaded_document()


def _bound(window: MainWindow) -> LoadedDocument:
    loaded = _loaded_of(window)
    assert loaded is not None
    return loaded


def _command_tuples(window: MainWindow) -> list[tuple[str, int, dict[str, object]]]:
    loaded = _loaded_of(window)
    if loaded is None:
        return []
    return [(c.id, c.ordinal, dict(c.params)) for c in loaded.document.commands]


def _new_window(services: AppServices, qtbot: QtBot) -> MainWindow:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    return window


def _patch_save_path(monkeypatch: MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )


def _patch_open_path(monkeypatch: MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )


def _dialog_saying(choice: str) -> object:
    def reply(self: MainWindow) -> str:
        return choice

    return reply


def _patch_dialog(monkeypatch: MonkeyPatch, choice: str) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _dialog_saying(choice))


def test_new_document_resets_state(services: AppServices, qtbot: QtBot) -> None:
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    assert _bound(window).document.commands == ()
    assert not _bound(window).document.is_dirty


def test_save_roundtrip_writes_file(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    target = tmp_path / "flange.mc.json"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")
    assert _bound(window).document.is_dirty
    _patch_save_path(monkeypatch, target)
    window.act_save.triggered.emit()
    assert target.exists()
    assert not _bound(window).document.is_dirty


def test_reopen_document_preserves_history(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    target = tmp_path / "flange.mc.json"
    first = _new_window(services, qtbot)
    first.act_new.triggered.emit()
    assert _loaded_of(first) is not None
    _bound(first).bus.execute("feature.box", {"size_x": 6.0, "size_y": 2.0, "size_z": 3.0}, "test")
    _patch_save_path(monkeypatch, target)
    first.act_save.triggered.emit()

    second = _new_window(services, qtbot)
    _patch_open_path(monkeypatch, target)
    second.act_open.triggered.emit()
    assert _command_tuples(second) == [
        (
            "feature.box",
            0,
            {
                "size_x": 6.0,
                "size_y": 2.0,
                "size_z": 3.0,
                "center": [0.0, 0.0, 0.0],
                "mode": "new",
            },
        )
    ]


def test_open_broken_file_reports_without_crash(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    bad = tmp_path / "bad.mc.json"
    bad.write_text("{\n  broken", encoding="utf-8")
    window = _new_window(services, qtbot)
    _patch_open_path(monkeypatch, bad)
    window.act_open.triggered.emit()
    assert _loaded_of(window) is None


def test_dirty_close_blocked_then_discard_proceeds(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")

    _patch_dialog(monkeypatch, "cancel")
    event_cancel = QCloseEvent()
    window.closeEvent(event_cancel)
    assert not event_cancel.isAccepted()

    _patch_dialog(monkeypatch, "discard")
    event_discard = QCloseEvent()
    window.closeEvent(event_discard)
    assert event_discard.isAccepted()


def test_close_after_save_is_allowed(
    services: AppServices, qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    target = tmp_path / "keep.mc.json"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 4.0, "size_y": 4.0, "size_z": 4.0}, "test")
    _patch_save_path(monkeypatch, target)
    window.act_save.triggered.emit()
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_undo_marks_dirty_and_blocks_close(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from PySide6.QtGui import QCloseEvent

    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 7.0, "size_y": 7.0, "size_z": 7.0}, "test")
    window.request_undo()
    assert _bound(window).document.is_dirty

    _patch_dialog(monkeypatch, "cancel")
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


@pytest.mark.parametrize("suffix", ["step", "stl"])
def test_export_chunk_uses_existing_providers(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    suffix: str,
) -> None:
    target = tmp_path / f"part.{suffix}"
    window = _new_window(services, qtbot)
    window.act_new.triggered.emit()
    assert _loaded_of(window) is not None
    _bound(window).bus.execute("feature.box", {"size_x": 5.0, "size_y": 5.0, "size_z": 5.0}, "test")
    _patch_save_path(monkeypatch, target)
    window.act_export.triggered.emit()
    assert target.exists()
    assert target.stat().st_size > 0


def test_save_without_document_is_noop(
    services: AppServices, qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = _new_window(services, qtbot)
    _patch_save_path(monkeypatch, Path("/tmp/never-mycad.mc.json"))
    window.act_save.triggered.emit()
    assert _loaded_of(window) is None
    assert not Path("/tmp/never-mycad.mc.json").exists()
