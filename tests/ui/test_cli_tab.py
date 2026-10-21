# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 11: CLI Tab 与 headless 会话同源（F-AGT-05）。

- 纯函数 execute_line 与 CliSession 打印路径输出逐字一致（差异仅前缀提示符）；
  调用后不泄漏任何 print（纯函数返回 messages）。
- new/open 的替换单点经 on_replace_doc 回调（GUI 生命周期打包入口）。
- 底栏 QTabWidget 承载 "CLI" + "Chat" 两页；CliTab 派发后窗口绑定。
- 已记录偏差：批次状态不跨 execute_line 调用（批次语义属 headless REPL）；
  quit/exit 哨兵在页内呈现、不关窗。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mycad.app import build_app
from mycad.cli.session import QUIT_SENTINEL, CliSession, execute_line
from mycad.core.persistence import LoadedDocument, save_document
from mycad.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from mycad.app import AppServices

CYLINDER_LINE = "cylinder radius=40 height=8 center=[0,0,0] mode=new"


def _discard(self: MainWindow) -> str:
    return "discard"


@pytest.fixture(autouse=True)
def _autodiscard_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


def test_parity_new_matches_headless_stdout(
    services: AppServices,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = CliSession(services)
    rc_cli = session.execute_line("new")
    out = capsys.readouterr().out
    rc_ui, messages = execute_line(
        "new",
        loaded=None,
        services=services,
        on_replace_doc=lambda _loaded: None,
    )
    assert rc_cli == rc_ui == 0
    assert messages == out.splitlines()
    assert messages == ["new document"]


def test_parity_negative_unknown_command(
    services: AppServices,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = CliSession(services)
    rc_cli = session.execute_line("feature.nope")
    err = capsys.readouterr().err
    rc_ui, messages = execute_line(
        "feature.nope",
        loaded=None,
        services=services,
        on_replace_doc=lambda _loaded: None,
    )
    assert rc_cli == rc_ui == 1
    assert messages == err.splitlines()
    # 负向文案与 headless 逐字一致，且不止一行防呆占位。
    assert len(messages) == 1


def test_pure_dispatch_prints_nothing(
    services: AppServices,
    capsys: pytest.CaptureFixture[str],
) -> None:
    execute_line(
        CYLINDER_LINE,
        loaded=None,
        services=services,
        on_replace_doc=lambda _loaded: None,
    )
    out, err = capsys.readouterr().out, capsys.readouterr().err
    assert out == "" and err == ""


def test_lazy_document_routes_through_on_replace_doc(
    services: AppServices,
) -> None:
    seen: list[LoadedDocument | None] = []
    rc, _messages = execute_line(
        CYLINDER_LINE,
        loaded=None,
        services=services,
        on_replace_doc=seen.append,
    )
    assert rc == 0
    assert len(seen) == 1 and seen[0] is not None


def test_batch_not_persisted_across_pure_calls(services: AppServices) -> None:
    execute_line(
        "begin-batch",
        loaded=None,
        services=services,
        on_replace_doc=lambda _loaded: None,
    )
    rc_end, messages = execute_line(
        "end-batch",
        loaded=None,
        services=services,
        on_replace_doc=lambda _loaded: None,
    )
    assert rc_end == 2
    assert messages and "end-batch" in messages[0]


def test_tab_replaces_window_document(
    services: AppServices,
    qtbot: QtBot,
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    assert window.cli_tab is not None
    window.cli_tab.input.setText("new")
    window.cli_tab.input.returnPressed.emit()
    loaded = window.loaded_document()
    assert loaded is not None
    # GUI Tab 自持的文档指针与窗口绑定必须来自同一次替换。
    assert window.cli_tab.current is loaded


def test_bottom_tabs_cli_and_chat(
    services: AppServices,
    qtbot: QtBot,
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    tabs = window.bottom_tabs
    assert tabs is not None
    assert tabs.count() == 2
    assert tabs.tabText(0) == "CLI"
    assert tabs.tabText(1) == "Chat"


def test_quit_sentinel_surfaced_without_close(
    services: AppServices,
    qtbot: QtBot,
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    tab = window.cli_tab
    assert tab is not None
    loaded_before = window.loaded_document()
    rc, _messages = tab.dispatch_line("quit")
    assert rc == QUIT_SENTINEL
    assert tab.current is loaded_before  # document untouched, window stays up


def test_open_via_cli_tab_binds_window(
    services: AppServices,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "cli_open.mc.json"
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    tab = window.cli_tab
    assert tab is not None
    tab.dispatch_line("new")
    loaded_new = window.loaded_document()
    assert loaded_new is not None
    save_document(loaded_new.document, plan)
    rc, _messages = tab.dispatch_line(f"open {plan}")
    assert rc == 0
    reopened = window.loaded_document()
    assert reopened is not None
    assert tab.current is reopened
