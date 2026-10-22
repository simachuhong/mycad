# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo-5 acceptance: menus/toolbar/QSettings/status-bar behaviour.

Menu titles are pinned verbatim against objects on the real QMenuBar (the
todo-4 lesson: same-source constants would make renames self-consistent
and defeat the probe).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow

#: UI初稿 §3 verbatim.
MENU_TITLES = ("文件", "编辑", "视图", "特征", "工具", "智能体", "帮助")


def _top_level_menu_labels(win: MainWindow) -> tuple[str, ...]:
    return tuple(action.text() for action in win.menuBar().actions())


def test_seven_menus_in_order(qapp: QApplication) -> None:
    assert _top_level_menu_labels(MainWindow()) == MENU_TITLES


def test_file_lifecycle_actions_disabled_except_quit(qapp: QApplication) -> None:
    win = MainWindow()
    # todo 8 起：新建/打开/保存/另存为/导出转活；导入/截图保持禁（F-DOC-03）。
    texts = {action.text(): action.isEnabled() for action in win.menu_file.actions()}
    for name in ("导入", "截图"):
        assert name in texts and texts[name] is False
    for name in ("新建", "打开", "保存", "另存为", "导出（STEP/STL）", "退出"):
        assert texts[name] is True


def test_undo_redo_guarded_without_document(qapp: QApplication) -> None:
    win = MainWindow()
    assert win.act_undo.isEnabled() and win.act_redo.isEnabled()
    assert not win.act_delete.isEnabled()
    assert not win.act_select_filter.isEnabled()
    win.request_undo()
    assert "未绑定文档" in win.status_command.text()


def test_status_fields_map_core_signals(qapp: QApplication) -> None:
    win = MainWindow()
    win.handle_core_signal("post_command", {"command_id": "feature.cylinder", "ordinal": 0})
    assert "feature.cylinder" in win.status_command.text()
    assert "重建中" in win.status_rebuild.text()
    assert "已修改" in win.status_dirty.text()
    win.handle_core_signal("geometry_rebuilt", {})
    assert "就绪" in win.status_rebuild.text()
    win.handle_core_signal("document_saved", {})
    assert "未修改" in win.status_dirty.text()


def test_dock_and_toolbar_toggles(qapp: QApplication) -> None:
    win = MainWindow()
    win.act_toggle_toolbar.setChecked(False)
    assert win.main_toolbar.isHidden()
    win.act_toggle_toolbar.setChecked(True)
    assert not win.main_toolbar.isHidden()
    win.act_toggle_left_dock.setChecked(False)
    assert win.left_dock.isHidden()


def test_lock_toolbar_disables_moving_and_floating(qapp: QApplication) -> None:
    win = MainWindow()
    assert win.main_toolbar.isMovable() and win.main_toolbar.isFloatable()
    win.act_lock_toolbar.setChecked(True)
    assert not win.main_toolbar.isMovable()
    assert not win.main_toolbar.isFloatable()
    win.act_lock_toolbar.setChecked(False)
    assert win.main_toolbar.isMovable() and win.main_toolbar.isFloatable()


def test_layout_roundtrip_through_qsettings(qapp: QApplication) -> None:
    win1 = MainWindow()
    win1.addToolBar(Qt.ToolBarArea.BottomToolBarArea, win1.main_toolbar)
    win1.act_toggle_left_dock.setChecked(False)
    win1.act_lock_toolbar.setChecked(True)
    win1.close()
    win2 = MainWindow()
    assert win2.toolBarArea(win2.main_toolbar) == Qt.ToolBarArea.BottomToolBarArea
    assert not win2.left_dock.toggleViewAction().isChecked()
    assert win2.act_lock_toolbar.isChecked()
    assert not win2.main_toolbar.isMovable()


def test_window_requests_the_default_size(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无存档布局时请求 1400x900。离屏平台的虚拟屏只有 800x800，会把窗口夹到
    798x774，因此这里断言"请求值"而非实际像素（真实显示器的实测见证据文件）。"""
    requested: list[tuple[int, int]] = []
    original = MainWindow.resize

    def spy(self: MainWindow, width: int, height: int) -> None:
        requested.append((width, height))
        original(self, width, height)

    monkeypatch.setattr(MainWindow, "resize", spy)
    MainWindow()
    assert (1400, 900) in requested


def test_real_bus_probe_flips_status_fields(qapp: QApplication) -> None:
    services = build_app()
    loaded = new_document(services)
    win = MainWindow(services=services)
    win.bind_document(loaded)
    loaded.document.events.emit("post_command", {"command_id": "feature.cylinder", "ordinal": 0})
    assert "feature.cylinder" in win.status_command.text()
    assert "重建中" in win.status_rebuild.text()
    assert "已修改" in win.status_dirty.text()


#: UI 初稿 §4.2 首期落地的 12 个按钮（文字按钮，无图标资源）。
TOOLBAR_TEXTS = (
    "新建",
    "打开",
    "保存",
    "撤销",
    "重做",
    "适应窗口",
    "着色/线框",
    "查看待确认计划",
    "拉伸",
    "旋转",
    "孔",
    "圆角",
)


def test_toolbar_carries_the_high_frequency_actions(qapp: QApplication) -> None:
    win = MainWindow()
    actions = win.main_toolbar.actions()
    assert tuple(action.text() for action in actions) == TOOLBAR_TEXTS
    # 菜单与工具栏共用同一批 QAction 对象：勾选/启用状态不会分叉。
    assert actions[0] is win.act_new
    assert actions[5] is win.act_fit_view
    assert actions[6] is win.act_shaded_wireframe


def test_toolbar_modeling_button_starts_a_plan_draft(qapp: QApplication) -> None:
    services = build_app()
    loaded = new_document(services)
    win = MainWindow(services=services)
    win.bind_document(loaded)
    extrude = next(action for action in win.main_toolbar.actions() if action.text() == "拉伸")
    assert extrude.isEnabled()
    extrude.trigger()
    assert "草稿：feature.extrude" in win.status_command.text()


def test_toolbar_modeling_buttons_disabled_without_services(qapp: QApplication) -> None:
    win = MainWindow()
    modeling = [
        action
        for action in win.main_toolbar.actions()
        if action.text() in {"拉伸", "旋转", "孔", "圆角"}
    ]
    assert len(modeling) == 4
    assert all(not action.isEnabled() for action in modeling)


def test_rebuild_hook_invoked_through_menu(qapp: QApplication) -> None:
    win = MainWindow()
    calls: list[bool] = []

    def hook() -> None:
        calls.append(True)

    win.rebuild_hook = hook
    win.act_rebuild.trigger()
    assert calls == [True]
