# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo-5 shell + todo-6 left panel: the five-zone main window.

Zones keep the widget-identity contract from todo 4; this module adds the
§3 menu set (seven menus, verbatim titles), toolbar toggling/locking
(§4.1), QSettings layout memory, and the five-field status bar wired to
the core signal union. The left dock hosts the todo-6 registry-driven
palette (with its plan-draft controller) when services are provided;
right/bottom/centre contents remain owned by todos 7 / 9 / 12.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, override

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QWidget,
)

from mycad.core.bus import CommandBus
from mycad.core.exceptions import InvalidHistoryError
from mycad.core.signals import SignalName
from mycad.ui.command_palette import CommandPalette
from mycad.ui.plan_draft import PlanDraftController

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.persistence import LoadedDocument

CENTER_OBJECT_NAME = "viewportHost"
LEFT_DOCK_OBJECT_NAME = "leftPanelDock"
RIGHT_DOCK_OBJECT_NAME = "rightPanelDock"
BOTTOM_DOCK_OBJECT_NAME = "bottomPanelDock"
TOOLBAR_OBJECT_NAME = "mainToolBar"

ORG_NAME = "MyCAD"
APP_NAME = "MyCAD"
SETTINGS_KEY_GEOMETRY = "mainWindow/geometry"
SETTINGS_KEY_STATE = "mainWindow/state"
SETTINGS_KEY_TOOLBAR_LOCKED = "toolbar/locked"

APP_VERSION = "0.1.0"

#: UI draft §3, menu order and titles verbatim — pinned by tests/ui.
MENU_TITLES: tuple[str, ...] = ("文件", "编辑", "视图", "特征", "工具", "智能体", "帮助")

#: The plan todo-5/todo-8 union: signals that count as document changes
#: (dirty marker) and drive the rebuild-status field.
MODIFYING_SIGNALS: frozenset[str] = frozenset(
    {
        "post_command",
        "geometry_rebuilt",
        "command_amended",
        "metadata_changed",
        "named_group_added",
        "named_group_removed",
    }
)

#: Same union, minus the pure-geometry one: those mean "redispatch work of
#: the layers". geometry_rebuilt means the rebuild finished.
PENDING_REBUILD_SIGNALS: frozenset[str] = MODIFYING_SIGNALS - {"geometry_rebuilt"}

#: The exact subscription set: the plan todo-5 union plus document_saved
#: (drives the dirty marker back to clean).
STATUS_SIGNALS: tuple[SignalName, ...] = (
    "post_command",
    "geometry_rebuilt",
    "command_amended",
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
    "document_saved",
)


class MainWindow(QMainWindow):
    """Shell shell: toolbar + viewportHost centre + three docks + status bar.

    Dock features keep their Qt defaults (closable/movable/floatable) —
    UI初稿 §2 requires docks to be floatable and closable, and the save/
    restore behaviour of that default set is asserted in tests/ui.
    """

    def __init__(self, *, services: AppServices | None = None) -> None:
        super().__init__()
        self.setWindowTitle("MyCAD")

        self._services = services
        self._bus: CommandBus | None = None
        self.rebuild_hook: Callable[[], None] | None = None
        # Strong references to the per-signal adapters: the signal bus holds
        # subscribers weakly, so anything not anchored here would die
        # immediately at subscribe time.
        self._signal_adapters: list[Callable[[Mapping[str, object]], None]] = []

        # Center: real viewport replaces this host in todo 9; five-region
        # layout stores an empty host widget (placeholder).
        center = QWidget()
        center.setObjectName(CENTER_OBJECT_NAME)
        self.setCentralWidget(center)

        self.main_toolbar = QToolBar("main")
        self.main_toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        # UI draft §10: movable, dockable to all four edges.
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setFloatable(True)
        self.main_toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        self.addToolBar(self.main_toolbar)

        self.left_dock = QDockWidget()
        self.left_dock.setObjectName(LEFT_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        self.right_dock = QDockWidget()
        self.right_dock.setObjectName(RIGHT_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)

        self.bottom_dock = QDockWidget()
        self.bottom_dock.setObjectName(BOTTOM_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

        # Resident single-line status bar (UI draft §2/§8), five permanent
        # fields from left to right.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_command = QLabel("空闲")
        self.status_selection = QLabel("选择 0")
        self.status_unit = QLabel("mm")
        self.status_rebuild = QLabel("重建状态：就绪")
        self.status_dirty = QLabel("未修改")
        for label in (
            self.status_command,
            self.status_selection,
            self.status_unit,
            self.status_rebuild,
            self.status_dirty,
        ):
            self.status_bar.addPermanentWidget(label)

        self._build_menus()
        # Todo 6: with services the left dock hosts the command palette and
        # its plan-draft controller; the todo-4 zero-arg form keeps the
        # dock empty.
        self.plan_draft: PlanDraftController | None = None
        self.command_palette: CommandPalette | None = None
        if services is not None:
            self.command_palette = CommandPalette(services.registry)
            self.left_dock.setWidget(self.command_palette)
            self.left_dock.setWindowTitle("命令库")
            self.plan_draft = PlanDraftController(services.registry)
            self.command_palette.command_activated.connect(self._on_palette_command)
        self.restore_window_state()

    # ------------------------------------------------------------------
    # Menus (UI draft §3)
    # ------------------------------------------------------------------

    def _build_menus(self) -> None:
        self.menu_file = self.menuBar().addMenu("文件")
        self.act_new = self.menu_file.addAction("新建")
        self.act_open = self.menu_file.addAction("打开")
        self.act_save = self.menu_file.addAction("保存")
        self.act_save_as = self.menu_file.addAction("另存为")
        self.act_import = self.menu_file.addAction("导入")
        self.act_export = self.menu_file.addAction("导出（STEP/STL）")
        self.act_screenshot = self.menu_file.addAction("截图")
        self.act_quit = self.menu_file.addAction("退出")
        self.act_quit.triggered.connect(self.close)
        # Document lifecycle actions are todo 8; screenshot/import are the
        # F-DOC-03 disabled tiers. Only 退出 is live at todo 5.
        for action in (
            self.act_new,
            self.act_open,
            self.act_save,
            self.act_save_as,
            self.act_import,
            self.act_export,
            self.act_screenshot,
        ):
            action.setEnabled(False)

        self.menu_edit = self.menuBar().addMenu("编辑")
        self.act_undo = self.menu_edit.addAction("撤销")
        self.act_undo.triggered.connect(self.request_undo)
        self.act_redo = self.menu_edit.addAction("重做")
        self.act_redo.triggered.connect(self.request_redo)
        self.act_delete = self.menu_edit.addAction("删除")
        self.act_select_filter = self.menu_edit.addAction("选择过滤器")
        self.act_delete.setEnabled(False)
        self.act_select_filter.setEnabled(False)

        self.menu_view = self.menuBar().addMenu("视图")
        self.act_shaded_wireframe = self.menu_view.addAction("着色/线框")
        self.act_shaded_wireframe.setCheckable(True)
        self.act_shaded_wireframe.setEnabled(False)  # todo 9 realises the slots.
        self.act_fit_view = self.menu_view.addAction("适应窗口")
        self.act_fit_view.setEnabled(False)
        self.act_standard_orientation = self.menu_view.addAction("标准方向（正视/等轴等）")
        self.act_standard_orientation.setEnabled(False)
        self.menu_view.addSeparator()
        self.act_toggle_toolbar = self.menu_view.addAction("显示/隐藏工具栏")
        self.act_toggle_toolbar.setCheckable(True)
        self.act_toggle_toolbar.setChecked(True)
        self.act_toggle_toolbar.toggled.connect(self.main_toolbar.setVisible)
        self.act_lock_toolbar = self.menu_view.addAction("锁定工具栏")
        self.act_lock_toolbar.setCheckable(True)
        self.act_lock_toolbar.toggled.connect(self._apply_toolbar_lock)
        self.menu_view.addSeparator()
        self.act_toggle_left_dock = self.menu_view.addAction("显示/隐藏左栏")
        self.act_toggle_left_dock.setCheckable(True)
        self.act_toggle_left_dock.setChecked(True)
        self.act_toggle_left_dock.toggled.connect(self.left_dock.setVisible)
        self.act_toggle_right_dock = self.menu_view.addAction("显示/隐藏右栏")
        self.act_toggle_right_dock.setCheckable(True)
        self.act_toggle_right_dock.setChecked(True)
        self.act_toggle_right_dock.toggled.connect(self.right_dock.setVisible)
        self.act_toggle_bottom_dock = self.menu_view.addAction("显示/隐藏底栏")
        self.act_toggle_bottom_dock.setCheckable(True)
        self.act_toggle_bottom_dock.setChecked(True)
        self.act_toggle_bottom_dock.toggled.connect(self.bottom_dock.setVisible)

        self.menu_feature = self.menuBar().addMenu("特征")
        self.act_open_palette = self.menu_feature.addAction("打开左栏命令库")
        self.act_open_palette.triggered.connect(self._open_left_palette)

        self.menu_tools = self.menuBar().addMenu("工具")
        self.act_options = self.menu_tools.addAction("选项")
        self.act_options.triggered.connect(self._show_options)
        self.act_units = self.menu_tools.addAction("单位")
        self.act_units.triggered.connect(self._show_units)
        self.act_measure = self.menu_tools.addAction("测量")
        self.act_measure.setEnabled(False)
        self.act_rebuild = self.menu_tools.addAction("重建")
        self.act_rebuild.triggered.connect(self.request_rebuild)

        self.menu_agent = self.menuBar().addMenu("智能体")
        self.act_view_plans = self.menu_agent.addAction("查看待确认计划")
        self.act_view_plans.triggered.connect(self._show_plan_cards)
        self.act_clear_chat = self.menu_agent.addAction("清空对话")
        # Cards/streams are the todo-12 artefacts; placeholder until then.
        self.act_clear_chat.setEnabled(False)

        self.menu_help = self.menuBar().addMenu("帮助")
        self.act_shortcuts = self.menu_help.addAction("快捷键")
        self.act_shortcuts.triggered.connect(self._show_shortcuts)
        self.act_about = self.menu_help.addAction("关于")
        self.act_about.triggered.connect(self._show_about)
        self.act_license = self.menu_help.addAction("开源许可说明")
        self.act_license.triggered.connect(self._show_license)

    def _apply_toolbar_lock(self, locked: bool) -> None:
        """锁定工具栏：锁定后既不可拖动也不可悬浮."""
        self.main_toolbar.setMovable(not locked)
        self.main_toolbar.setFloatable(not locked)

    def _open_left_palette(self) -> None:
        self.left_dock.show()
        self.left_dock.raise_()

    def _on_palette_command(self, command_id: str) -> None:
        if self.plan_draft is None:
            return
        try:
            self.plan_draft.new_draft(command_id)
        except ValueError as err:
            self.status_command.setText(str(err))
        else:
            self.status_command.setText(f"草稿：{command_id}")

    def _show_plan_cards(self) -> None:
        self.bottom_dock.show()
        self.bottom_dock.raise_()

    def _show_options(self) -> None:
        QMessageBox.information(
            self,
            "选项",
            "窗口布局记忆保存在 QSettings（org=MyCAD, app=MyCAD）。",
        )

    def _show_units(self) -> None:
        QMessageBox.information(self, "单位", "单位：mm（只读）。")

    def _show_shortcuts(self) -> None:
        QMessageBox.information(self, "快捷键", "暂无快捷键覆盖（计划不做全覆盖）。")

    def _show_about(self) -> None:
        QMessageBox.about(self, "关于", f"MyCAD v{APP_VERSION}")

    def _show_license(self) -> None:
        QMessageBox.information(
            self,
            "开源许可说明",
            "MyCAD 以 Apache-2.0 释出；第三方依赖条目见仓库 NOTICE 文件。",
        )

    # ------------------------------------------------------------------
    # Document binding and core-signal wiring
    # ------------------------------------------------------------------

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Bind the app-provided LoadedDocument and subscribe the status fields.

        The bus holds callbacks weakly, so each subscription goes through a
        ``functools.partial`` adapter that keeps the signal name, and this
        window holds the strong references until unbind.
        """
        self._bus = loaded.bus
        events = loaded.document.events
        for name in STATUS_SIGNALS:
            adapter = partial(self.handle_core_signal, name)
            self._signal_adapters.append(adapter)
            events.subscribe(name, adapter)

    def handle_core_signal(self, name: str, payload: Mapping[str, object]) -> None:
        """Map one signal name + payload onto the five status fields."""
        if name == "post_command":
            command_id = payload.get("command_id", "?")
            ordinal = payload.get("ordinal", "?")
            self.status_command.setText(f"当前：{command_id}（#{ordinal}）")
        if name == "geometry_rebuilt":
            self.status_rebuild.setText("重建状态：就绪")
        elif name in PENDING_REBUILD_SIGNALS:
            self.status_rebuild.setText("重建状态：重建中")
        if name == "document_saved":
            self.status_dirty.setText("未修改")
        elif name in MODIFYING_SIGNALS:
            self.status_dirty.setText("已修改")

    def request_rebuild(self) -> None:
        """Rebuild action slot; todo 9 sets ``_rebuild_hook`` on the viewport."""
        if self.rebuild_hook is not None:
            self.rebuild_hook()

    def request_undo(self) -> None:
        if self._bus is None:
            self.status_command.setText("未绑定文档，无法撤销")
            return
        try:
            self._bus.undo()
        except InvalidHistoryError as err:
            self.status_command.setText(f"撤销失败：{err}")

    def request_redo(self) -> None:
        if self._bus is None:
            self.status_command.setText("未绑定文档，无法重做")
            return
        try:
            self._bus.redo()
        except InvalidHistoryError as err:
            self.status_command.setText(f"重做失败：{err}")

    # ------------------------------------------------------------------
    # Layout memory (UI draft §4.1)
    # ------------------------------------------------------------------

    def restore_window_state(self) -> None:
        settings = QSettings(ORG_NAME, APP_NAME)
        geometry = settings.value(SETTINGS_KEY_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value(SETTINGS_KEY_STATE)
        if state is not None:
            self.restoreState(state)
        locked = settings.value(SETTINGS_KEY_TOOLBAR_LOCKED, False)
        if isinstance(locked, bool) and locked:
            self.act_lock_toolbar.setChecked(True)

    def store_window_state(self) -> None:
        settings = QSettings(ORG_NAME, APP_NAME)
        settings.setValue(SETTINGS_KEY_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTINGS_KEY_STATE, self.saveState())
        settings.setValue(SETTINGS_KEY_TOOLBAR_LOCKED, self.act_lock_toolbar.isChecked())
        settings.sync()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self.store_window_state()
        super().closeEvent(event)
