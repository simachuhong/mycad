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
from pathlib import Path
from typing import TYPE_CHECKING, override

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from mycad import app as mycad_app
from mycad.app import handlers_for
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.exceptions import InvalidHistoryError, ValidationError
from mycad.core.persistence import open_document, save_document
from mycad.core.signals import SignalName
from mycad.formats.registry import UnknownFormatError
from mycad.ui.cli_tab import CliTab
from mycad.ui.command_palette import CommandPalette
from mycad.ui.command_reference import CommandReferenceDialog
from mycad.ui.plan_cards import PlanCards
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.right_panel import RightPanel
from mycad.ui.viewport import GLViewport

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

#: UI draft §4.2 "建模高频" group: toolbar shortcuts that start the very same
#: plan draft the left palette starts (草稿 → 确认 → 执行).
TOOLBAR_MODELING_COMMANDS: tuple[tuple[str, str], ...] = (
    ("拉伸", "feature.extrude"),
    ("旋转", "feature.revolve"),
    ("孔", "feature.hole"),
    ("圆角", "modify.fillet"),
)

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

# 面板刷新订阅集：结构树的数据面（document.commands / named_groups /
# metadata）被这些信号击中时需要整树重建（todo 7 计划 References 明示
# named_group 信号驱动树刷新；post_command/geometry_rebuilt/command_amended
# 同理改变 feature_history 投影）。尾部 document_saved 只动脏标记，不缓存
# 结构，故不在此列。
STRUCTURE_REFRESH_SIGNALS: tuple[SignalName, ...] = (
    "post_command",
    "geometry_rebuilt",
    "command_amended",
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
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
        # resize() before restore_window_state(): a saved layout still wins.
        self.resize(1400, 900)

        self._services = services
        self._loaded: LoadedDocument | None = None
        self._document_path: Path | None = None
        self._bus: CommandBus | None = None
        self.rebuild_hook: Callable[[], None] | None = None
        self.viewport: GLViewport | None = None
        # Strong references to the per-signal adapters: the signal bus holds
        # subscribers weakly, so anything not anchored here would die
        # immediately at subscribe time.
        self._signal_adapters: list[Callable[[Mapping[str, object]], None]] = []

        # Center: services build the real GL viewport (todo 9); the bare
        # shell keeps the placeholder host widget with the same name.
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
        self.bottom_tabs: QTabWidget | None = None
        self.cli_tab: CliTab | None = None
        self.plan_cards: PlanCards | None = None
        # Todo 7: with services the right dock hosts the five fixed tabs;
        # its document binding still happens in ``bind_document``.
        self.right_panel: RightPanel | None = None
        self._registry: CommandRegistry | None = None
        if services is not None:
            self.command_palette = CommandPalette(services.registry)
            self.left_dock.setWidget(self.command_palette)
            self.left_dock.setWindowTitle("命令库")
            self.plan_draft = PlanDraftController(services.registry)
            self._registry = services.registry
            self.act_command_reference.setEnabled(True)
            self.right_panel = RightPanel()
            self.right_dock.setWidget(self.right_panel)
            self.right_dock.setWindowTitle("属性")
            self.command_palette.command_activated.connect(self._on_palette_command)
            # Todo 9: real viewport in the centre; snapshot refresh + 视图 actions.
            self.viewport = GLViewport(viewport_port=services.kernel)
            self.viewport.setObjectName(CENTER_OBJECT_NAME)
            self.setCentralWidget(self.viewport)
            self.rebuild_hook = self.viewport.refresh
            self.act_shaded_wireframe.setEnabled(True)
            self.act_shaded_wireframe.setChecked(True)
            self.act_shaded_wireframe.toggled.connect(self._on_toggle_shading)
            self.act_fit_view.setEnabled(True)
            self.act_fit_view.triggered.connect(self.viewport.fit_view)
            # Todo 11: bottom dock hosts the same-source CLI tab + chat placeholder.
            tabs = QTabWidget()
            tabs.setObjectName("bottomTabs")
            self.cli_tab = CliTab(services=services, on_replace_doc=self._on_cli_document_replace)
            tabs.addTab(self.cli_tab, "CLI")
            # Todo 12: the Chat page is the plan-card confirmation stream.
            self.plan_cards = PlanCards()
            tabs.addTab(self.plan_cards, "Chat")
            self.bottom_tabs = tabs
            self.bottom_dock.setWidget(tabs)
            assert self.plan_cards is not None  # created just above
            self.plan_cards.bind_draft(self.plan_draft)
            self.bottom_dock.setWindowTitle("控制台")
            # Todo 10: 结构树↔视口双向联动。树→视口由用户点击发信号；
            # 视口→树走右栏编程式选中，不再二次发 selection 信号，
            # 因此无回环。
            self.right_panel.structure_selection_changed.connect(self._on_structure_pick)
            self.viewport.feature_picked.connect(self._on_viewport_pick)
        self._populate_toolbar()
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
        # Screenshot/import stay disabled (F-DOC-03 tier); new/open/save/
        # save-as/export go live in todo 8. 退出 was wired at todo 5.
        for action in (self.act_import, self.act_screenshot):
            action.setEnabled(False)
        self.act_new.triggered.connect(self._on_new_document)
        self.act_open.triggered.connect(self._on_open_document)
        self.act_save.triggered.connect(self._on_save_document)
        self.act_save_as.triggered.connect(self._on_save_document_as)
        self.act_export.triggered.connect(self._on_export_document)

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
        # Verb <-> command-id lookup needs the registry: disabled until the
        # services branch below has one.
        self.act_command_reference = self.menu_help.addAction("命令速查…")
        self.act_command_reference.setEnabled(False)
        self.act_command_reference.triggered.connect(self._show_command_reference)
        self.act_about = self.menu_help.addAction("关于")
        self.act_about.triggered.connect(self._show_about)
        self.act_license = self.menu_help.addAction("开源许可说明")
        self.act_license.triggered.connect(self._show_license)

    def _populate_toolbar(self) -> None:
        """给工具栏装按钮（UI 初稿 §4.2）。

        菜单动作复用同一批 QAction 对象——菜单与工具栏共用一份状态，
        勾选/启用不会分叉；建模快捷键走左栏命令库同一条起草路径
        （草稿 → 确认 → 执行），没有 services 时禁用。
        """
        # 首期无图标资源：按 §4.2 的"最小图标集"落成文字按钮。
        self.main_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        for action in (
            self.act_new,
            self.act_open,
            self.act_save,
            self.act_undo,
            self.act_redo,
            self.act_fit_view,
            self.act_shaded_wireframe,
            self.act_view_plans,
        ):
            self.main_toolbar.addAction(action)
        for label, command_id in TOOLBAR_MODELING_COMMANDS:
            action = QAction(label, self)
            action.setToolTip(f"{label}（{command_id}）：起草命令，在 Chat 页确认后执行")
            action.setEnabled(self.plan_draft is not None)
            action.triggered.connect(partial(self._on_toolbar_modeling, command_id))
            self.main_toolbar.addAction(action)

    def _on_toolbar_modeling(self, command_id: str, _checked: bool = False) -> None:
        """工具栏建模按钮：与左栏命令库双击同一条路径。"""
        self._on_palette_command(command_id)

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
            step = self.plan_draft.new_draft(command_id)
        except ValueError as err:
            self.status_command.setText(str(err))
        else:
            # Todo 12: 用 schema 默认值起底参数（validate_params 只补缺省键）。
            try:
                self.plan_draft.set_params(step, {})
            except ValidationError as err:
                self.status_command.setText(f"{command_id} 参数默认值失败：{err}")
            self.status_command.setText(f"草稿：{command_id}")

    def _on_toggle_shading(self, shaded: bool) -> None:
        if self.viewport is not None:
            self.viewport.set_shaded(shaded)

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

    def _show_command_reference(self) -> None:
        """Open the verb <-> command-id lookup table (needs the registry)."""
        if self._registry is None:
            return
        dialog = CommandReferenceDialog(self._registry, self)
        dialog.exec()

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

    def loaded_document(self) -> LoadedDocument | None:
        """当前绑定的 LoadedDocument；测试与后续计划确认流的同源读取入口。"""
        return self._loaded

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Bind the app-provided LoadedDocument and subscribe the status fields.

        The bus holds callbacks weakly, so each subscription goes through a
        ``functools.partial`` adapter that keeps the signal name, and this
        window holds the strong references until unbind.
        """
        self._bus = loaded.bus
        # Replacement semantics: dropping our strong adapter list unsubscribes
        # the previous document—its bus only holds subscribers weakly.
        self._signal_adapters.clear()
        self._loaded = loaded
        events = loaded.document.events
        for name in STATUS_SIGNALS:
            adapter = partial(self.handle_core_signal, name)
            self._signal_adapters.append(adapter)
            events.subscribe(name, adapter)
        if self.right_panel is not None and self._registry is not None:
            self.right_panel.bind_document(loaded, self._registry)
        if self.plan_cards is not None:
            self.plan_cards.bind_document(loaded)
            for name in STRUCTURE_REFRESH_SIGNALS:
                adapter = partial(self._on_structure_signal, name)
                self._signal_adapters.append(adapter)
                events.subscribe(name, adapter)
        if self.viewport is not None:
            self.viewport.bind_document(loaded)
        if self.cli_tab is not None:
            self.cli_tab.bind_document(loaded)

    def _on_structure_pick(self, ordinal: int) -> None:
        """树→视口：用户点击结构叶，视口高亮对应 feature 快照。"""
        if self.viewport is not None:
            self.viewport.highlight_feature(ordinal)

    def _on_viewport_pick(self, ordinal: int) -> None:
        """视口→树：点击拾取到 feature → 树选中同一命令叶；-1 清除。"""
        if self.right_panel is not None:
            self.right_panel.select_feature_ordinal(ordinal if ordinal >= 0 else None)

    def _on_cli_document_replace(self, loaded: LoadedDocument | None) -> None:
        if loaded is None:
            return
        self._replace_document(loaded, None)

    def _on_structure_signal(self, name: str, payload: Mapping[str, object] | None) -> None:
        if self.right_panel is not None:
            self.right_panel.refresh_structure()

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

    # ------------------------------------------------------------------
    # Document lifecycle (todo 8)
    # ------------------------------------------------------------------

    def _on_new_document(self) -> None:
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法新建")
            return
        if not self._confirm_unsaved_changes():
            return
        self._replace_document(mycad_app.new_document(self._services), None)

    def _on_open_document(self) -> None:
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法打开")
            return
        if not self._confirm_unsaved_changes():
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self, "打开存档", "", "MyCAD 存档 (*.mc.json)"
        )
        if not selected:
            return
        path = Path(selected)
        try:
            loaded = open_document(
                path,
                registry=self._services.registry,
                kernel=self._services.kernel,
                handlers=handlers_for(self._services),
            )
        except ValidationError as exc:
            self._show_error(f"存档格式无效：{str(exc)[:200]}")
            return
        except OSError as exc:
            self._show_error(f"无法读取存档：{exc}")
            return
        self._replace_document(loaded, path)

    def _on_save_document(self) -> None:
        if self._loaded is None:
            self.status_command.setText("未绑定文档")
            return
        if self._document_path is None:
            self._on_save_document_as()
            return
        self._store_document(self._document_path)

    def _on_save_document_as(self) -> None:
        if self._loaded is None:
            self.status_command.setText("未绑定文档")
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self, "保存存档", "untitled.mc.json", "MyCAD 存档 (*.mc.json)"
        )
        if not selected:
            return
        path = Path(selected)
        self._store_document(path)
        self._document_path = path

    def _store_document(self, path: Path) -> None:
        if self._loaded is None:
            return
        try:
            save_document(self._loaded.document, path)
        except OSError as exc:
            self._show_error(f"写入失败：{exc}")
            return
        # persistence 不清脏；保存成功后显式 mark_clean（document.py 约定）。
        self._loaded.document.mark_clean()
        self.status_dirty.setText("未修改")

    def _on_export_document(self) -> None:
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法导出")
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出（STEP/STL）",
            "",
            "STEP 文件 (*.step *.stp);;STL 文件 (*.stl)",
        )
        if not selected:
            return
        target = Path(selected)
        try:
            self._services.formats.resolve(target).write(self._services.kernel, target)
        except UnknownFormatError as exc:
            self._show_error(f"不支持的导出格式：{exc}")
            return
        except OSError as exc:
            self._show_error(f"写入失败：{exc}")
            return
        self.status_command.setText(f"已导出：{target}")

    def _confirm_unsaved_changes(self) -> bool:
        """True 放行（无文档/未脏/用户放弃），False 一律不动当前文档。"""
        if self._loaded is None or not self._loaded.document.is_dirty:
            return True
        choice = self._ask_save_dialog()
        if choice == "save":
            self._on_save_document()
            return not self._loaded.document.is_dirty
        return choice == "discard"

    def _ask_save_dialog(self) -> str:
        """三选弹窗：save/discard/cancel；exec 阻塞至用户选择。"""
        box = QMessageBox(self)
        box.setWindowTitle("未保存的修改")
        box.setText("当前文档有未保存的修改。")
        save_button = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("放弃修改", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            return "save"
        if clicked is cancel_button:
            return "cancel"
        return "discard"

    def _show_error(self, message: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("错误")
        box.setText(message)
        box.show()

    def _replace_document(self, loaded: LoadedDocument, path: Path | None) -> None:
        """单文档替换语义（A4）：整面重绑 + 重置草稿 + 记住存档路径。"""
        self._document_path = path
        self.bind_document(loaded)
        if self._services is not None:
            self.plan_draft = PlanDraftController(self._services.registry)
            if self.right_panel is not None:
                self.right_panel.bind_draft(self.plan_draft)
            if self.plan_cards is not None:
                self.plan_cards.bind_draft(self.plan_draft)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_unsaved_changes():
            event.ignore()
            return
        if self.viewport is not None:
            self.viewport.dispose()
        self.store_window_state()
        super().closeEvent(event)
