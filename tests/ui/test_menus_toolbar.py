# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo-5 acceptance: menus/toolbar/QSettings/status-bar behaviour.

Menu titles are pinned verbatim against objects on the real QMenuBar (the
todo-4 lesson: same-source constants would make renames self-consistent
and defeat the probe).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.ui import main_window
from mycad.ui.main_window import MainWindow

#: UI初稿 §3 verbatim.
MENU_TITLES = ("文件", "编辑", "视图", "特征", "草图", "工具", "智能体", "帮助")


def _top_level_menu_labels(win: MainWindow) -> tuple[str, ...]:
    return tuple(action.text() for action in win.menuBar().actions())


def test_application_settings_are_isolated_from_user_configuration(tmp_path: Path) -> None:
    settings = main_window.QSettings(main_window.ORG_NAME, main_window.APP_NAME)
    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()).resolve().is_relative_to(tmp_path.resolve())


def test_menus_in_order(qapp: QApplication) -> None:
    assert _top_level_menu_labels(MainWindow()) == MENU_TITLES


def test_file_lifecycle_actions_enable_dxf_subset_import(qapp: QApplication) -> None:
    win = MainWindow()
    # DXF sketch subset import is live; STEP import and screenshot remain unavailable.
    texts = {action.text(): action.isEnabled() for action in win.menu_file.actions()}
    assert texts["导入"] is True
    assert texts["截图"] is False
    for name in ("新建", "打开", "保存", "另存为", "导出（STEP/STL/DXF）", "退出"):
        assert texts[name] is True
    assert texts["新建二维图"] is False


def test_new_drawing_action_is_available_with_services(qapp: QApplication) -> None:
    win = MainWindow(services=build_app(discoverers=[]))
    assert win.act_new_drawing.isEnabled()


def test_undo_redo_guarded_without_document(qapp: QApplication) -> None:
    win = MainWindow()
    assert win.act_undo.isEnabled() and win.act_redo.isEnabled()
    assert not win.act_delete.isEnabled()
    assert not win.act_select_filter.isEnabled()
    win.request_undo()
    assert "未绑定文档" in win.status_command.text()


def test_navigation_and_selection_actions_change_only_view_state(
    qapp: QApplication,
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=[])
    win = MainWindow(services=services)
    qtbot.addWidget(win)
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 40, "size_y": 30, "size_z": 8},
        "test",
    )
    win.bind_document(loaded)
    document_revision = loaded.document.revision
    command_history = loaded.document.commands
    geometry_revision = services.kernel.geometry_revision

    win.orientation_actions["top"].trigger()
    win.projection_actions["perspective"].trigger()
    win.selection_filter_actions["face"].trigger()
    win.act_show_coordinate_axes.setChecked(False)
    win.act_show_coordinate_axes.trigger()
    win.act_show_xy_grid.trigger()

    assert win.viewport is not None
    assert win.viewport.opts["elevation"] == 90.0
    assert win.viewport.projection_mode() == "perspective"
    assert win.viewport.selection_filter() == "face"
    assert win.viewport.coordinate_axes_visible()
    assert win.viewport.xy_grid_visible()
    assert loaded.document.revision == document_revision
    assert loaded.document.commands == command_history
    assert services.kernel.geometry_revision == geometry_revision


def test_status_fields_map_core_signals(qapp: QApplication) -> None:
    win = MainWindow()
    win.handle_core_signal("post_command", {"command_id": "feature.cylinder", "ordinal": 0})
    assert "feature.cylinder" in win.status_command.text()
    assert "就绪" in win.status_rebuild.text()
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
    assert "就绪" in win.status_rebuild.text()
    assert "已修改" in win.status_dirty.text()


#: 主工具栏保留文件、视图和通用操作；建模入口独立。
TOOLBAR_TEXTS = ("新建", "打开", "保存", "撤销", "重做", "⋯")


def test_toolbar_carries_the_high_frequency_actions(qapp: QApplication) -> None:
    win = MainWindow()
    actions = [action for action in win.main_toolbar.actions() if action.text()]
    assert tuple(action.text() for action in actions) == TOOLBAR_TEXTS
    assert actions == [
        win.act_new,
        win.act_open,
        win.act_save,
        win.act_undo,
        win.act_redo,
        win.act_customize_quick_access,
    ]


def test_render_mode_action_group_changes_only_view_presentation(qapp: QApplication) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 12, "size_z": 14}, "test")
    win = MainWindow(services=services)
    win.bind_document(loaded)
    commands_before = loaded.document.commands
    revision_before = services.kernel.geometry_revision

    for mode, action in win.render_mode_actions.items():
        action.trigger()
        assert action.isChecked()
        assert win.viewport is not None
        assert win.viewport.render_mode() == mode

    assert sum(action.isChecked() for action in win.render_mode_actions.values()) == 1
    assert loaded.document.commands == commands_before
    assert services.kernel.geometry_revision == revision_before


def test_toolbar_modeling_button_starts_a_plan_draft(qapp: QApplication) -> None:
    services = build_app()
    loaded = new_document(services)
    win = MainWindow(services=services)
    win.bind_document(loaded)
    extrude = next(action for action in win.modeling_toolbar.actions() if action.text() == "拉伸")
    assert extrude.isEnabled()
    extrude.trigger()
    assert "单击模型平面" in win.status_command.text()


def test_toolbar_modeling_buttons_disabled_without_services(qapp: QApplication) -> None:
    win = MainWindow()
    modeling = [
        action
        for action in win.modeling_toolbar.actions()
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


def test_theme_selector_persists_without_modifying_document(qapp: QApplication) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    win = MainWindow(services=services)
    win.bind_document(loaded)
    original_commands = loaded.document.commands
    dark_action = getattr(win, "act_theme_dark", None)
    assert isinstance(dark_action, QAction), "the dark theme must be selectable"
    dark_action.trigger()
    assert getattr(win, "current_theme", lambda: "")() == "dark"
    assert loaded.document.commands == original_commands
    assert not loaded.document.is_dirty
    win.store_window_state()

    restored = MainWindow()
    assert getattr(restored, "current_theme", lambda: "")() == "dark"
    light_action = getattr(restored, "act_theme_light", None)
    assert isinstance(light_action, QAction) and not light_action.isChecked()


def test_bottom_panel_is_hidden_until_cli_or_plan_is_requested(qapp: QApplication) -> None:
    win = MainWindow(services=build_app(discoverers=[]))
    assert win.bottom_dock.isHidden()
    assert not win.act_toggle_bottom_dock.isChecked()
    show_cli = getattr(win, "act_show_cli", None)
    assert isinstance(show_cli, QAction), "the CLI needs a discoverable reveal action"
    show_cli.trigger()
    assert not win.bottom_dock.isHidden()
    assert win.bottom_tabs is not None
    assert win.bottom_tabs.currentWidget() is win.cli_tab
    win.bottom_dock.hide()
    win.act_view_plans.trigger()
    assert not win.bottom_dock.isHidden()
    assert win.bottom_tabs.currentWidget() is win.plan_cards
    assert win.plan_cards is not None
    assert win.bottom_tabs.tabText(win.bottom_tabs.indexOf(win.plan_cards)) == "计划"


def test_layout_reset_restores_named_docks_and_default_toolbar_position(
    qapp: QApplication,
) -> None:
    win = MainWindow(services=build_app(discoverers=[]))
    win.addToolBar(Qt.ToolBarArea.BottomToolBarArea, win.main_toolbar)
    win.act_toggle_left_dock.setChecked(False)
    win.act_toggle_right_dock.setChecked(False)
    reset = getattr(win, "act_reset_layout", None)
    assert isinstance(reset, QAction), "a layout-reset action must be available"
    assert reset.shortcut() == QKeySequence("Ctrl+Shift+0")
    reset.trigger()
    assert win.toolBarArea(win.main_toolbar) == Qt.ToolBarArea.TopToolBarArea
    assert not win.left_dock.isHidden() and not win.right_dock.isHidden()
    assert win.bottom_dock.isHidden()
    assert win.act_toggle_left_dock.isChecked()
    assert win.act_toggle_right_dock.isChecked()


def test_compact_window_collapses_command_library_and_restores_it_when_wide(
    qapp: QApplication, qtbot: QtBot
) -> None:
    win = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(win)
    win.show()
    qapp.processEvents()
    win.resize(800, 600)
    qapp.processEvents()
    assert win.left_dock.isHidden()
    assert not win.right_dock.isHidden()
    win.resize(1200, 700)
    qapp.processEvents()
    assert not win.left_dock.isHidden()


def test_toolbar_actions_have_icons_shortcut_hints_and_disabled_reasons(
    qapp: QApplication,
) -> None:
    win = MainWindow(services=build_app(discoverers=[]))
    for action in (win.act_new, win.act_open, win.act_save, win.act_undo, win.act_redo):
        assert not action.icon().isNull()
        assert action.shortcut().toString()
        assert action.shortcut().toString() in action.toolTip()
    assert win.act_import.isEnabled()
    assert "DXF 草图子集" in win.act_import.toolTip()
