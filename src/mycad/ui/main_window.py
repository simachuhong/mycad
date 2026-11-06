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
from dataclasses import dataclass, replace
from functools import partial
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, cast, override
from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QPoint,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QKeySequence,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from mycad import app as mycad_app
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import AFFECTED_OBJECTS
from mycad.core.document_kinds import (
    DRAWING2D_COMMAND_IDS,
    NATIVE_ARCHIVE_SUFFIXES,
    DocumentKind,
    DocumentType,
)
from mycad.core.exceptions import InvalidHistoryError, MycadError, ValidationError
from mycad.core.identity import BodyId
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.plan import Plan
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet, ReplayEdit
from mycad.core.signals import SignalName
from mycad.core.sketch import PointEntity, Sketch, SketchSupportFace, WorkPlaneFrame
from mycad.core.sketch_constraints import (
    SketchConstraint,
    SketchConstraintSolveResult,
)
from mycad.core.sketch_edit import mirror_entities, move_entities, rotate_entities
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference
from mycad.core.viewport_protocol import PlanarFaceFrame, ViewportData, ViewportSketchData
from mycad.formats.dxf_preview import DxfOutputPreview, prepare_dxf_output_preview
from mycad.formats.providers.dxf_provider import (
    DXF_PROVIDER,
    DxfExchangeReport,
    DxfSketchImport,
    DxfUnitOverrideRequired,
)
from mycad.formats.registry import UnknownFormatError
from mycad.ui.action_catalog import ActionCatalog
from mycad.ui.bound_hole_task import BoundHoleTask
from mycad.ui.cad_icons import cad_icon, command_icon_name, refresh_button_icons
from mycad.ui.cli_tab import CliTab
from mycad.ui.command_palette import CommandPalette
from mycad.ui.command_reference import CommandReferenceDialog
from mycad.ui.command_strip import install_command_strip
from mycad.ui.datum_task import DatumTaskDialog
from mycad.ui.document_save import DocumentSaveController, SaveResult
from mycad.ui.document_session import DEFAULT_NAMES, DocumentSession, SessionDocument
from mycad.ui.drawing_templates import DrawingTemplateChoiceDialog
from mycad.ui.drawing_workbench import DrawingWorkbench
from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.fillet_toolbar import FilletCommandBar
from mycad.ui.history_repair_task import HistoryRepairTask
from mycad.ui.modeling_handles import DimensionHandle
from mycad.ui.modeling_toolbar import ModelingCommandBar
from mycad.ui.new_document_dialog import NewDocumentDialog
from mycad.ui.part_sketch_workbench import PartSketchWorkbench
from mycad.ui.path_identity import path_identity
from mycad.ui.plan_cards import PlanCards
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.quick_access import QuickAccessController, QuickAccessDialog, QuickAccessStore
from mycad.ui.recent_documents import RecentDocuments
from mycad.ui.ribbon import RibbonGroup, RibbonPage
from mycad.ui.right_panel import HistoryEditDialog, RightPanel
from mycad.ui.sketch_constraint_dialog import SketchConstraintDialog
from mycad.ui.sketch_editor import MixedMoveState, SketchEditorDialog
from mycad.ui.start_page import StartPage
from mycad.ui.theme import ThemeName, apply_theme
from mycad.ui.unsaved_documents_dialog import UnsavedDocumentsDialog
from mycad.ui.viewport import (
    GLViewport,
    ProjectionMode,
    RenderMode,
    SelectionKind,
    SelectionState,
    ViewOrientation,
)
from mycad.ui.workplane_position import WorkplanePositionDialog
from mycad.ui.workspace_console import AiChatPanel, InformationPanel, MessageLabel, WorkspaceConsole
from mycad.ui.workspace_layout import WorkspaceLayoutStore
from mycad.ui.workspace_tabs import WorkspaceId, WorkspaceTabs

if TYPE_CHECKING:
    from mycad.app import AppServices

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
SETTINGS_KEY_THEME = "appearance/theme"
SETTINGS_KEY_TOOLBAR_AREA = "toolbar/preferredArea"
SETTINGS_KEY_DOCUMENT_DIRECTORY = "documents/lastDirectory"
SETTINGS_KEY_COPY_MODE = "drawing2d/copyMode"

APP_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class _DxfUnitPrompt:
    message: str


@dataclass(frozen=True, slots=True)
class _SketchConstraintPreview:
    solve_result: SketchConstraintSolveResult
    viewport: ViewportData | None = None
    sketches: tuple[ViewportSketchData, ...] = ()


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

    _core_event_queued = Signal(int, str, object)

    def __init__(
        self,
        *,
        services: AppServices | None = None,
        document_session: DocumentSession | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("MyCAD")
        self._compact_policy_ready = False
        self._compact_layout_active = False
        self._compact_policy_change = False
        self._compact_left_was_visible = True
        self._small_screen_active = False
        self._small_bottom_was_visible = False
        self._small_right_was_visible = False
        self._small_policy_change = False
        # resize() before restore_window_state(): a saved layout still wins.
        self.resize(1400, 900)
        self.setMinimumSize(480, 360)

        self._services = services
        self.document_session = document_session
        self._session_binding = False
        self._workspace_transition = False
        self._pending_document_activation: str | None = None
        self.document_selector: QComboBox | None = None
        self.document_saver: DocumentSaveController | None = None
        self._session_close_approved = False
        self._session_close_waiting = False
        self.execution_unit: SerializedExecutionUnit | None = None
        self._session_id = 0
        self._busy_action_states: dict[QAction, bool] = {}
        self._loaded: LoadedDocument | None = None
        self._sketch_dialog: SketchEditorDialog | None = None
        self.part_sketch_task: PartSketchWorkbench | None = None
        self._preferred_part_sketch: tuple[LoadedDocument, str] | None = None
        self._preferred_part_region: tuple[LoadedDocument, str, tuple[str, ...]] | None = None
        self.datum_task: DatumTaskDialog | None = None
        self.bound_hole_task: BoundHoleTask | None = None
        self.history_repair_task: HistoryRepairTask | None = None
        self.history_edit_task: HistoryEditDialog | None = None
        self._after_sketch_commit: Callable[[], None] | None = None
        self._after_sketch_failure: Callable[[], None] | None = None
        self.new_document_dialog: NewDocumentDialog | None = None
        self._sketch_dock_visibility: tuple[bool, bool] | None = None
        self._drafting_toolbar_state: QByteArray | None = None
        self._modeling_toolbar_was_visible = False
        self._sketch_constraint_dialog: SketchConstraintDialog | None = None
        self._sketch_constraint_preview_revision: int | None = None
        self._document_path: Path | None = None
        self._bus: CommandBus | None = None
        self._active_modeling_command: str | None = None
        self._active_selection_kind: SelectionKind | None = None
        self._active_selection_role: str | None = None
        self._active_placement_kind: str | None = None
        self._sphere_position_dialog: WorkplanePositionDialog | None = None
        self._previous_selection_filter: SelectionKind | None = None
        self._fillet_edge_selectors: tuple[dict[str, object], ...] = ()
        self._fillet_radius_value: float | None = 1.0
        self._fillet_last_successful_radius = 1.0
        self._fillet_preview_generation = 0
        self._fillet_preview_valid = False
        self._fillet_preview_document_revision: int | None = None
        self._fillet_preview_pending = False
        self._fillet_commit_inflight = False
        self._modeling_face_selector: dict[str, object] | None = None
        self._modeling_edge_selectors: tuple[dict[str, object], ...] = ()
        self._modeling_body_selectors: tuple[dict[str, object], ...] = ()
        self._modeling_body_names: tuple[str, ...] = ()
        self._modeling_placement_ready = False
        self._modeling_preview_generation = 0
        self._modeling_preview_valid = False
        self._modeling_preview_document_revision: int | None = None
        self._modeling_preview_pending = False
        self._modeling_commit_inflight = False
        self._modeling_params: dict[str, object] = {}
        self._modeling_face_frame: PlanarFaceFrame | None = None
        self._modeling_params_valid = False
        self._modeling_source_revision = 0
        self._extrude_input_valid = True
        self.fillet_command_bar: FilletCommandBar | None = None
        self.modeling_command_bar: ModelingCommandBar | None = None
        self._part_only_actions: list[QAction] = []
        self._fillet_preview_timer = QTimer(self)
        self._fillet_preview_timer.setSingleShot(True)
        self._fillet_preview_timer.setInterval(200)
        self._fillet_preview_timer.timeout.connect(self._request_fillet_preview)
        self._modeling_preview_timer = QTimer(self)
        self._modeling_preview_timer.setSingleShot(True)
        self._modeling_preview_timer.setInterval(200)
        self._modeling_preview_timer.timeout.connect(self._request_modeling_preview)
        self._theme_name: ThemeName = "light"
        self.rebuild_hook: Callable[[], None] | None = None
        self.viewport: GLViewport | None = None
        # Strong references to the per-signal adapters: the signal bus holds
        # subscribers weakly, so anything not anchored here would die
        # immediately at subscribe time.
        self._signal_adapters: list[Callable[[Mapping[str, object]], None]] = []
        self._core_event_queued.connect(self._dispatch_core_event)

        # Center: services build the real GL viewport (todo 9); the bare
        # shell keeps the placeholder host widget with the same name.
        center = QWidget()
        center.setObjectName(CENTER_OBJECT_NAME)
        self.workspace_tabs = WorkspaceTabs()
        self.workspace_tabs.setObjectName(CENTER_OBJECT_NAME)
        self.workspace_tabs.set_content("model", center)
        self.start_page = StartPage()
        self.recent_documents = RecentDocuments(QSettings(ORG_NAME, APP_NAME))
        self.start_page.set_recent_documents(self.recent_documents.items)
        self.workspace_container = QWidget(self)
        workspace_layout = QVBoxLayout(self.workspace_container)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self.document_tab_bar = QTabBar(self.workspace_container)
        self.document_tab_bar.setExpanding(False)
        self.document_tab_bar.setUsesScrollButtons(True)
        self.document_tab_bar.setTabsClosable(True)
        self.document_tab_bar.currentChanged.connect(self._on_document_tab_changed)
        self.document_tab_bar.tabCloseRequested.connect(self._on_document_tab_close_requested)
        self.document_tab_bar.setVisible(document_session is not None)
        workspace_layout.addWidget(self.document_tab_bar)
        workspace_layout.addWidget(self.workspace_tabs)
        if document_session is not None:
            self.workspace_tabs.tabBar().hide()
        self._central_pages = QStackedWidget(self)
        self._central_pages.setObjectName(CENTER_OBJECT_NAME)
        self._central_pages.addWidget(self.workspace_container)
        self._central_pages.addWidget(self.start_page)
        self._home_visibility: dict[QWidget, bool] | None = None
        self._home_menu_visibility: dict[QAction, bool] = {}
        self.setCentralWidget(self._central_pages)
        self.start_page.create_requested.connect(self._create_from_start_page)
        self.start_page.open_requested.connect(self._on_open_document)
        self.start_page.resume_requested.connect(self._resume_active_document)
        self.start_page.recent_open_requested.connect(self._open_recent_document)
        self.start_page.recent_locate_requested.connect(self._locate_recent_document)
        self.start_page.recent_remove_requested.connect(self._remove_recent_document)
        self.start_page.recent_clear_requested.connect(self._clear_recent_documents)

        self.main_toolbar = QToolBar("main")
        self.main_toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        # UI draft §10: movable, dockable to all four edges.
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setFloatable(True)
        self.main_toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        self.addToolBar(self.main_toolbar)
        self.modeling_toolbar = QToolBar("三维建模", self)
        self.modeling_toolbar.setObjectName("modelingToolsToolbar")
        self.modeling_toolbar.setMovable(True)
        self.modeling_toolbar.setFloatable(True)
        self.modeling_toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        self.modeling_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.modeling_toolbar.setIconSize(QSize(24, 24))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(self.modeling_toolbar)
        self.part_sketch_entry_toolbar = QToolBar("零件功能区", self)
        self.part_sketch_entry_toolbar.setObjectName("partRibbonToolbar")
        self.part_sketch_entry_toolbar.setMovable(False)
        self.part_sketch_entry_toolbar.setFloatable(False)
        self.part_ribbon = QTabWidget(self.part_sketch_entry_toolbar)
        self.part_ribbon.setObjectName("partRibbon")
        self.part_ribbon.setDocumentMode(True)
        self.part_ribbon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._ribbon_model_page = RibbonPage(self.part_ribbon)
        self._ribbon_model_layout = self._ribbon_model_page.content_layout
        self._ribbon_sketch_stack = QStackedWidget(self.part_ribbon)
        self._ribbon_sketch_entry = RibbonPage(self._ribbon_sketch_stack)
        self._ribbon_entry_layout = self._ribbon_sketch_entry.content_layout
        self._ribbon_sketch_stack.addWidget(self._ribbon_sketch_entry)
        self._ribbon_inspect_page = RibbonPage(self.part_ribbon)
        self._ribbon_tools_page = RibbonPage(self.part_ribbon)
        self._ribbon_view_page = RibbonPage(self.part_ribbon)
        self.part_ribbon.addTab(self._ribbon_model_page, "主页")
        self.part_ribbon.addTab(self._ribbon_sketch_stack, "草图")
        self.part_ribbon.addTab(self._ribbon_inspect_page, "检查")
        self.part_ribbon.addTab(self._ribbon_tools_page, "工具")
        self.part_ribbon.addTab(self._ribbon_view_page, "视图")
        self.part_sketch_entry_toolbar.addWidget(self.part_ribbon)
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(self.part_sketch_entry_toolbar)

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
        self.status_command = MessageLabel("空闲")
        self.status_command.setObjectName("statusCommand")
        self.status_command.setMinimumWidth(60)
        self.status_command.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_camera = QLabel("无视图")
        self.status_camera.setObjectName("statusCamera")
        self.status_camera.setToolTip("中键旋转；Shift+中键平移；滚轮缩放；左键选择/框选。")
        self.status_selection = QLabel("选择 0")
        self.status_unit = QLabel("mm")
        self.status_rebuild = QLabel("重建状态：就绪")
        self.status_dirty = QLabel("未修改")
        for label in (
            self.status_command,
            self.status_camera,
            self.status_selection,
            self.status_unit,
            self.status_rebuild,
            self.status_dirty,
        ):
            self.status_bar.addPermanentWidget(label, 1 if label is self.status_command else 0)

        self.action_catalog = ActionCatalog()
        self._build_menus()
        for action_id, action in (
            ("file.home", self.act_home),
            ("file.new", self.act_new),
            ("file.new-drawing", self.act_new_drawing),
            ("file.close", self.act_close_document),
            ("file.open", self.act_open),
            ("file.save", self.act_save),
            ("file.save-as", self.act_save_as),
            ("file.save-all", self.act_save_all),
            ("file.import", self.act_import),
            ("file.export", self.act_export),
            ("edit.undo", self.act_undo),
            ("edit.redo", self.act_redo),
            ("edit.delete", self.act_delete),
            ("ui.view.fit", self.act_fit_view),
            ("ui.view.current-model", self.act_return_current_model),
            ("ui.view.selection-filter", self.act_select_filter),
            ("part-sketch.create", self.act_sketch),
            ("part-sketch.constraints", self.act_sketch_constraints),
        ):
            self.action_catalog.register(action_id, action)
        if services is not None:
            self.execution_unit = SerializedExecutionUnit(self)
            execution_unit = self.execution_unit

            def join_executor(_object: QObject | None = None) -> None:
                execution_unit.shutdown(wait_for_running=True)

            self.destroyed.connect(join_executor)
            self.execution_unit.busy_changed.connect(self._on_execution_busy_changed)
            self.execution_unit.result_delivery_finished.connect(
                self._on_execution_delivery_finished
            )
        # Todo 6: with services the left dock hosts the command palette and
        # its plan-draft controller; the todo-4 zero-arg form keeps the
        # dock empty.
        self.plan_draft: PlanDraftController | None = None
        self.command_palette: CommandPalette | None = None
        self.left_tabs: QTabWidget | None = None
        self.bottom_tabs: WorkspaceConsole | None = None
        self.information_tab = InformationPanel()
        self.ai_chat = AiChatPanel()
        self.status_command.text_changed.connect(self.information_tab.append_message)
        if self.execution_unit is not None:
            self.execution_unit.result_ready.connect(self._record_execution_error)
        self.cli_tab: CliTab | None = None
        self.plan_cards: PlanCards | None = None
        # Todo 7: with services the right dock hosts the five fixed tabs;
        # its document binding still happens in ``bind_document``.
        self.right_panel: RightPanel | None = None
        self._registry: CommandRegistry | None = None
        if services is not None:
            self.command_palette = CommandPalette(services.registry)
            self.plan_draft = PlanDraftController(services.registry)
            self._registry = services.registry
            self.act_command_reference.setEnabled(True)
            self.right_panel = RightPanel()
            self.left_tabs = QTabWidget(self.left_dock)
            self.left_tabs.addTab(self.right_panel.take_structure_tab(), "模型")
            self.left_tabs.addTab(self.command_palette, "命令")
            self.left_dock.setWidget(self.left_tabs)
            self.left_dock.setWindowTitle("路径查找器")
            self.right_dock.setWidget(self.right_panel)
            self.right_dock.setWindowTitle("属性")
            self.command_palette.command_activated.connect(self._on_palette_command)
            # Todo 9: real viewport in the centre; snapshot refresh + 视图 actions.
            viewport = GLViewport(viewport_port=services.kernel)
            viewport.set_orientation("isometric")
            viewport.setObjectName(CENTER_OBJECT_NAME)
            self.viewport = viewport
            self.workspace_tabs.set_content("model", viewport)
            self.rebuild_hook = viewport.refresh
            for action in self.render_mode_actions.values():
                action.setEnabled(True)
            for action in self.selection_filter_actions.values():
                action.setEnabled(True)
            for action in self.orientation_actions.values():
                action.setEnabled(True)
            for action in self.projection_actions.values():
                action.setEnabled(True)
            self.act_select_filter.setEnabled(True)
            self.act_standard_orientation.setEnabled(True)
            self.projection_menu.menuAction().setEnabled(True)
            self.act_show_coordinate_axes.setEnabled(True)
            self.act_show_xy_grid.setEnabled(True)
            viewport.selection_changed.connect(self._on_selection_changed)
            viewport.camera_changed.connect(self._sync_camera_status)
            self._sync_camera_status()
            viewport.current_snapshot_changed.connect(self._on_current_snapshot_changed)
            self.right_panel.body_selection_requested.connect(self._on_body_pick)
            self.right_panel.datum_selection_requested.connect(viewport.select_datum)
            self.right_panel.datum_visibility_requested.connect(viewport.set_datum_visible)
            viewport.datum_selection_changed.connect(self.right_panel.select_datum_reference)
            self.right_panel.body_visibility_requested.connect(self._on_body_visibility_requested)
            self.right_panel.show_all_bodies_requested.connect(viewport.show_all_bodies)
            viewport.body_display_changed.connect(self._sync_body_display)
            viewport.context_menu_requested.connect(self._on_viewport_context_requested)
            viewport.fillet_commit_requested.connect(self._commit_fillet_group)
            viewport.modeling_commit_requested.connect(self._commit_modeling_operation)
            viewport.radius_edit_requested.connect(self._begin_fillet_radius_edit)
            fillet_bar = FilletCommandBar(self)
            fillet_bar.hide()
            self.fillet_command_bar = fillet_bar
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, fillet_bar)
            fillet_bar.radius_changed.connect(self._on_fillet_radius_changed)
            fillet_bar.radius_accepted.connect(self._accept_fillet_radius)
            fillet_bar.commit_requested.connect(self._commit_fillet_group)
            fillet_bar.cancel_requested.connect(self._cancel_active_modeling_tool)
            fillet_bar.clear_selection_requested.connect(self._clear_fillet_selection)
            fillet_bar.select_source_requested.connect(self._select_source_model)
            modeling_bar = ModelingCommandBar(self)
            modeling_bar.hide()
            self.modeling_command_bar = modeling_bar
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, modeling_bar)
            modeling_bar.parameters_changed.connect(self._on_modeling_parameters_changed)
            modeling_bar.commit_requested.connect(self._commit_modeling_operation)
            modeling_bar.cancel_requested.connect(self._cancel_active_modeling_tool)
            modeling_bar.select_source_requested.connect(self._select_source_model)
            modeling_bar.position_requested.connect(self._open_sphere_positioning)
            modeling_bar.distance_accepted.connect(self._accept_extrude_distance)
            modeling_bar.distance_input_validity_changed.connect(self._on_extrude_input_validity)
            modeling_bar.dimension_changed.connect(self._sync_dimension_handle)
            viewport.extrude_manipulator.distance_changed.connect(self._on_dimension_value)
            viewport.extrude_manipulator.input_validity_changed.connect(
                self._on_extrude_input_validity
            )
            viewport.extrude_manipulator.toolbar_input_requested.connect(
                self._focus_dimension_input
            )
            viewport.extrude_manipulator.hint_changed.connect(self.status_command.setText)
            viewport.workplane_point_picked.connect(self._on_workplane_point_picked)
            viewport.workplane_point_rejected.connect(self._on_workplane_point_rejected)
            viewport.escape_pressed.connect(self._cancel_active_modeling_tool)
            self.act_fit_view.setEnabled(True)
            self.act_fit_view.triggered.connect(self._on_fit_view)
            tabs = WorkspaceConsole()
            tabs.addTab(self.information_tab, "信息")
            self.cli_tab = CliTab(
                services=services,
                on_replace_doc=self._on_cli_document_replace,
                command_guard=self._guard_cli_command,
                execution_unit=self.execution_unit,
            )
            tabs.addTab(self.cli_tab, "CLI")
            tabs.addTab(self.ai_chat, "AI 对话")
            self.plan_cards = PlanCards()
            if self.execution_unit is not None:
                self.plan_cards.configure_execution(
                    self.execution_unit,
                    session_id=lambda: self._session_id,
                    prepare_geometry=services.kernel.viewport_data,
                    preview_builder=partial(mycad_app.preview_command, services),
                    show_candidate_preview=viewport.show_candidate_preview,
                    clear_candidate_preview=viewport.clear_candidate_preview,
                )
            tabs.addTab(self.plan_cards, "计划")
            self.bottom_tabs = tabs
            self.bottom_dock.setWidget(tabs)
            tabs.set_expanded(False)
            tabs.expanded_changed.connect(self._resize_console)
            self.act_show_ai.setEnabled(True)
            self.act_show_information.setEnabled(True)
            self.act_clear_chat.setEnabled(True)
            self.act_show_cli.setEnabled(True)
            self.act_view_plans.setEnabled(True)
            assert self.plan_cards is not None  # created just above
            self.plan_cards.bind_draft(self.plan_draft)
            self.plan_cards.plan_done.connect(self._on_fillet_plan_done)
            self.plan_cards.plan_failed.connect(self._on_fillet_plan_failed)
            if self.execution_unit is not None:
                self.execution_unit.busy_changed.connect(self._on_fillet_execution_busy_changed)
                self.execution_unit.busy_changed.connect(self._on_modeling_execution_busy_changed)
            self.bottom_dock.setWindowTitle("信息与命令")
            # P2-05: a tree click previews a historical state; a viewport
            # hit selects the current model without inventing a source row.
            self.right_panel.structure_selection_changed.connect(self._on_structure_pick)
            self.right_panel.history_edit_requested.connect(self._on_history_edit_requested)
            self.right_panel.history_candidate_preview_requested.connect(
                self._preview_history_candidate
            )
            self.right_panel.history_candidate_commit_requested.connect(
                self._commit_history_candidate
            )
            self.right_panel.history_candidate_discard_requested.connect(
                self._discard_history_candidate
            )
            self.right_panel.history_candidate_repair_requested.connect(self._start_history_repair)
            self.right_panel.history_candidate_open_requested.connect(self._start_history_edit)
            self.right_panel.part_sketch_edit_requested.connect(self._on_part_sketch_edit_requested)
            self.viewport.current_entity_picked.connect(self._on_current_entity_pick)
            self.viewport.history_preview_changed.connect(self._on_history_preview_changed)
        self.drawing_workbench = DrawingWorkbench(services, self.execution_unit)
        self.drawing_workbench.source_selection_available = self.document_session is not None
        self.workspace_tabs.set_content("drawing", self.drawing_workbench)
        self.drawing_workbench.message.connect(
            partial(self._on_owned_engineering_message, self.drawing_workbench)
        )
        self.drawing_workbench.sketch_requested.connect(
            lambda: self.workspace_tabs.activate("sketch")
        )
        self.drawing_workbench.model_requested.connect(self._show_3d_workspace)
        self.drawing_workbench.open_requested.connect(self._on_open_document)
        self.drawing_workbench.new_requested.connect(self._on_new_document)
        self.drawing_workbench.choose_source_requested.connect(self._choose_engineering_source)
        drawing_workbench = self.drawing_workbench
        self.destroyed.connect(lambda: drawing_workbench.shutdown())
        self.workspace_tabs.workspace_changed.connect(self._on_workspace_changed)
        self._populate_toolbar()
        self._register_plugin_actions()
        if self.command_palette is not None:
            self.command_palette.set_action_catalog(self.action_catalog)
        self.resizeDocks(
            [self.left_dock, self.right_dock],
            [194, 278],
            Qt.Orientation.Horizontal,
        )
        self.workspace_layout = WorkspaceLayoutStore(QSettings(ORG_NAME, APP_NAME))
        self.workspace_layout.migrate_legacy()
        self._setup_quick_access()
        self._console_environment: str | None = None
        self._restoring_console = False
        if self.bottom_tabs is not None:
            self.bottom_tabs.expanded_changed.connect(self._console_state_changed)
            self.bottom_tabs.currentChanged.connect(self._console_state_changed)
        self._set_workspace_environment("home" if self.document_session is not None else "part")
        self.restore_window_state()
        if self.document_session is not None:
            self.document_saver = DocumentSaveController(
                self.document_session,
                prepare=self._prepare_session_document,
                choose_path=self._choose_session_save_path,
                changed=self._session_save_changed,
                report=self._report_session_save,
            )
            document_menu = self.menuBar().addMenu("文档")
            actions: tuple[tuple[str, Callable[[], object]], ...] = (
                ("新建工程图", lambda: self._create_from_start_page("drawing")),
                ("将当前二维图用于建模", self._use_current_sketch_for_model),
                ("将内部草图分离为独立二维文档", self.separate_internal_sketch),
                ("选择工程图来源", self._choose_engineering_source),
                ("查看来源状态", self._show_reference_status),
                ("更新来源引用", self._update_document_reference),
                ("解除来源关联", self._detach_document_reference),
            )
            for label, callback in actions:
                document_menu.addAction(label).triggered.connect(callback)

    # ------------------------------------------------------------------
    # Menus (UI draft §3)
    # ------------------------------------------------------------------

    @staticmethod
    def _set_action_shortcut(
        action: QAction, shortcut: QKeySequence, *, explanation: str | None = None
    ) -> None:
        action.setShortcut(shortcut)
        hint = shortcut.toString(QKeySequence.SequenceFormat.NativeText)
        tooltip = explanation or action.text()
        if hint:
            tooltip = f"{tooltip} · {hint}"
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)

    def _build_menus(self) -> None:
        self.menu_file = self.menuBar().addMenu("文件")
        self.act_home = self.menu_file.addAction("返回首页")
        self.act_home.triggered.connect(self.show_start_page)
        self.act_new = self.menu_file.addAction("新建")
        self.act_new_drawing = self.menu_file.addAction("新建二维图")
        self.act_close_document = self.menu_file.addAction("关闭文档")
        self.act_close_document.triggered.connect(self.close_active_document)
        self.act_open = self.menu_file.addAction("打开")
        self.act_save = self.menu_file.addAction("保存")
        self.act_save_as = self.menu_file.addAction("另存为")
        self.act_save_all = self.menu_file.addAction("全部保存")
        self.act_save_all.setEnabled(self.document_session is not None)
        self.act_save_all.triggered.connect(self._on_save_all_documents)
        self._set_action_shortcut(self.act_save_all, QKeySequence("Ctrl+Alt+S"))
        self.act_import = self.menu_file.addAction("导入")
        self.act_export = self.menu_file.addAction("导出（STEP/STL/DXF）")
        self.act_screenshot = self.menu_file.addAction("截图")
        self.act_quit = self.menu_file.addAction("退出")
        self._set_action_shortcut(self.act_new, QKeySequence(QKeySequence.StandardKey.New))
        self._set_action_shortcut(self.act_open, QKeySequence(QKeySequence.StandardKey.Open))
        self._set_action_shortcut(self.act_save, QKeySequence(QKeySequence.StandardKey.Save))
        self._set_action_shortcut(self.act_save_as, QKeySequence(QKeySequence.StandardKey.SaveAs))
        self.act_quit.triggered.connect(self.close)
        # DXF import is limited to preview-confirmed sketch linework; STEP
        # solid import and independent screenshot export remain unavailable.
        self.act_import.setToolTip("导入 DXF 草图子集；先预览交换报告，再确认写入历史。")
        self.act_screenshot.setToolTip("独立截图导出尚未实现；可使用系统截图工具。")
        self.act_screenshot.setEnabled(False)
        self.act_new.triggered.connect(self._on_new_document)
        self.act_new_drawing.setEnabled(self._services is not None)
        self.act_new_drawing.setToolTip("创建独立二维绘图文档；存档会记录文档类型。")
        self.act_new_drawing.triggered.connect(self._on_new_drawing_document)
        self.act_open.triggered.connect(self._on_open_document)
        self.act_save.triggered.connect(self._on_save_document)
        self.act_save_as.triggered.connect(self._on_save_document_as)
        self.act_import.triggered.connect(self._on_import_dxf_sketch)
        self.act_export.triggered.connect(self._on_export_document)

        self.menu_edit = self.menuBar().addMenu("编辑")
        self.act_undo = self.menu_edit.addAction("撤销")
        self._set_action_shortcut(self.act_undo, QKeySequence(QKeySequence.StandardKey.Undo))
        self.act_undo.triggered.connect(self.request_undo)
        self.act_redo = self.menu_edit.addAction("重做")
        self._set_action_shortcut(self.act_redo, QKeySequence(QKeySequence.StandardKey.Redo))
        self.act_redo.triggered.connect(self.request_redo)
        self.act_delete = self.menu_edit.addAction("删除")
        self.selection_filter_menu: QMenu = self.menu_edit.addMenu("选择过滤器")
        self.act_select_filter = self.selection_filter_menu.menuAction()
        self.selection_filter_group = QActionGroup(self)
        self.selection_filter_group.setExclusive(True)
        filter_labels: tuple[tuple[SelectionKind, str], ...] = (
            ("body", "实体"),
            ("face", "面"),
            ("edge", "边"),
            ("vertex", "顶点"),
        )
        self.selection_filter_actions: dict[SelectionKind, QAction] = {}
        for kind, label in filter_labels:
            action = self.selection_filter_menu.addAction(label)
            action.setCheckable(True)
            action.setEnabled(False)
            action.setToolTip(f"后续视口点击只选择{label}；当前模型不变")
            self.selection_filter_group.addAction(action)
            action.triggered.connect(partial(self._on_selection_filter_selected, kind))
            self.selection_filter_actions[kind] = action
        self.selection_filter_actions["body"].setChecked(True)
        self.act_delete.setEnabled(False)
        self.act_select_filter.setEnabled(False)
        self.act_delete.setToolTip("当前版本不支持直接删除实体；可撤销或编辑历史特征。")
        self.act_select_filter.setToolTip("选择实体、面、边或顶点；只改变视口状态。")

        self.menu_view = self.menuBar().addMenu("视图")
        self.render_mode_menu = self.menu_view.addMenu("渲染模式")
        self.render_mode_group = QActionGroup(self)
        self.render_mode_group.setExclusive(True)
        mode_labels: tuple[tuple[RenderMode, str], ...] = (
            ("shaded", "着色"),
            ("shaded-edges", "着色边线"),
            ("engineering-wireframe", "工程线框"),
            ("mesh-diagnostic", "网格诊断"),
        )
        self.render_mode_actions: dict[RenderMode, QAction] = {}
        for mode, label in mode_labels:
            action = self.render_mode_menu.addAction(label)
            action.setCheckable(True)
            action.setEnabled(False)
            action.setToolTip(f"仅改变视口显示方式：{label}")
            self.render_mode_group.addAction(action)
            action.triggered.connect(partial(self._on_render_mode_selected, mode))
            self.render_mode_actions[mode] = action
        self.act_shaded_wireframe = self.render_mode_actions["shaded-edges"]
        self.act_shaded_wireframe.setChecked(True)
        self.act_fit_view = self.menu_view.addAction("适应窗口")
        self._set_action_shortcut(
            self.act_fit_view, QKeySequence("F"), explanation="将当前模型完整显示在画布中"
        )
        self.act_fit_view.setEnabled(False)
        self.act_return_current_model = self.menu_view.addAction("返回当前模型")
        self.act_return_current_model.setToolTip("退出历史预览并返回当前模型。")
        self.act_return_current_model.setEnabled(False)
        self.act_return_current_model.triggered.connect(self._return_current_model)
        self.orientation_menu: QMenu = self.menu_view.addMenu("标准方向")
        self.act_standard_orientation = self.orientation_menu.menuAction()
        self.orientation_group = QActionGroup(self)
        self.orientation_group.setExclusive(True)
        orientation_labels: tuple[tuple[ViewOrientation, str], ...] = (
            ("front", "前视"),
            ("back", "后视"),
            ("left", "左视"),
            ("right", "右视"),
            ("top", "俯视"),
            ("bottom", "仰视"),
            ("isometric", "等轴测"),
        )
        self.orientation_actions: dict[ViewOrientation, QAction] = {}
        for orientation, label in orientation_labels:
            action = self.orientation_menu.addAction(label)
            action.setCheckable(True)
            action.setEnabled(False)
            self.orientation_group.addAction(action)
            action.triggered.connect(partial(self._on_orientation_selected, orientation))
            self.orientation_actions[orientation] = action
        self.orientation_actions["isometric"].setChecked(True)
        self.act_standard_orientation.setEnabled(False)
        self.projection_menu: QMenu = self.menu_view.addMenu("投影方式")
        self.projection_group = QActionGroup(self)
        self.projection_group.setExclusive(True)
        projection_labels: tuple[tuple[ProjectionMode, str], ...] = (
            ("orthographic", "正交"),
            ("perspective", "透视"),
        )
        self.projection_actions: dict[ProjectionMode, QAction] = {}
        for mode, label in projection_labels:
            action = self.projection_menu.addAction(label)
            action.setCheckable(True)
            action.setEnabled(False)
            self.projection_group.addAction(action)
            action.triggered.connect(partial(self._on_projection_selected, mode))
            self.projection_actions[mode] = action
        self.projection_actions["orthographic"].setChecked(True)
        self.projection_menu.menuAction().setEnabled(False)
        self.act_show_coordinate_axes = self.menu_view.addAction("全局 XYZ 坐标")
        self.act_show_coordinate_axes.setCheckable(True)
        self.act_show_coordinate_axes.setChecked(True)
        self.act_show_coordinate_axes.setEnabled(False)
        self.act_show_coordinate_axes.toggled.connect(self._on_coordinate_axes_toggled)
        self.act_show_xy_grid = self.menu_view.addAction("XY 工作网格")
        self.act_show_xy_grid.setCheckable(True)
        self.act_show_xy_grid.setEnabled(False)
        self.act_show_xy_grid.toggled.connect(self._on_xy_grid_toggled)
        self.menu_view.addSeparator()
        self.menu_appearance = self.menu_view.addMenu("外观主题")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        self.act_theme_light = self.menu_appearance.addAction("明亮")
        self.act_theme_dark = self.menu_appearance.addAction("暗色")
        for action in (self.act_theme_light, self.act_theme_dark):
            action.setCheckable(True)
            self.theme_action_group.addAction(action)
        self.act_theme_light.triggered.connect(partial(self._on_theme_action, "light"))
        self.act_theme_dark.triggered.connect(partial(self._on_theme_action, "dark"))
        self.act_theme_light.setChecked(True)
        self.menu_view.addSeparator()
        self.act_show_cli = self.menu_view.addAction("打开命令行面板")
        self._set_action_shortcut(
            self.act_show_cli,
            QKeySequence("Ctrl+Shift+L"),
            explanation="显示底部命令行",
        )
        self.act_show_cli.triggered.connect(self._show_cli_panel)
        self.act_show_cli.setEnabled(False)
        self.act_show_cli.setToolTip("需要可用的应用服务；创建或打开文档后可显示 CLI。")
        self.act_reset_layout = self.menu_view.addAction("重置当前环境布局")
        self._set_action_shortcut(
            self.act_reset_layout,
            QKeySequence("Ctrl+Shift+0"),
            explanation="恢复命令库、结构属性和顶部工具栏默认布局",
        )
        self.act_reset_layout.triggered.connect(self._reset_layout)
        self.menu_view.addSeparator()
        self.menu_view.addAction(self.modeling_toolbar.toggleViewAction())
        self.act_toggle_toolbar = self.menu_view.addAction("显示/隐藏工具栏")
        self.act_toggle_toolbar.setCheckable(True)
        self.act_toggle_toolbar.setChecked(True)
        self.act_toggle_toolbar.toggled.connect(self.main_toolbar.setVisible)
        self.act_lock_toolbar = self.menu_view.addAction("锁定工具栏")
        self.act_lock_toolbar.setCheckable(True)
        self.act_lock_toolbar.toggled.connect(self._apply_toolbar_lock)
        self.menu_view.addSeparator()
        self.act_toggle_left_dock = self.menu_view.addAction("路径查找器面板")
        self.act_toggle_left_dock.setCheckable(True)
        self.act_toggle_left_dock.setChecked(True)
        self.act_toggle_left_dock.toggled.connect(self._on_left_dock_toggled)
        self.act_toggle_right_dock = self.menu_view.addAction("结构与属性面板")
        self.act_toggle_right_dock.setCheckable(True)
        self.act_toggle_right_dock.setChecked(True)
        self.act_toggle_right_dock.toggled.connect(self.right_dock.setVisible)
        self.act_toggle_right_dock.toggled.connect(self._on_small_right_toggled)
        self.act_toggle_bottom_dock = self.menu_view.addAction("信息与命令面板")
        self.act_toggle_bottom_dock.setCheckable(True)
        self.act_toggle_bottom_dock.setChecked(False)
        self.act_toggle_bottom_dock.toggled.connect(self.bottom_dock.setVisible)
        self.act_toggle_bottom_dock.toggled.connect(self._on_small_bottom_toggled)
        self.act_expand_compact_ribbon = self.menu_view.addAction("展开零件功能区")
        self.act_expand_compact_ribbon.setCheckable(True)
        self.act_expand_compact_ribbon.setChecked(True)
        self.act_expand_compact_ribbon.setEnabled(False)
        self.act_expand_compact_ribbon.toggled.connect(self._set_compact_ribbon_expanded)
        self.bottom_dock.hide()
        self.bottom_dock.visibilityChanged.connect(self.act_toggle_bottom_dock.setChecked)
        self.act_show_information = self.menu_view.addAction("信息提示")
        self.act_show_information.setEnabled(False)
        self.act_show_information.triggered.connect(self._show_information_panel)

        self.menu_feature = self.menuBar().addMenu("特征")
        self.act_open_palette = self.menu_feature.addAction("打开左栏命令库")
        self.act_open_palette.triggered.connect(self._open_left_palette)
        self.act_sketch = self.menu_feature.addAction("创建草图")
        self.act_sketch.setEnabled(self._services is not None)
        self.act_sketch.setToolTip("在选定工作平面上绘制 2D 草图；完成后写入一条可撤销命令。")
        self.act_sketch.triggered.connect(self._on_sketch_start)
        self.menu_part_sketch = self.menuBar().addMenu("草图")
        self.menu_part_sketch.addAction(self.act_sketch)
        for tool, label in (
            ("point", "点"),
            ("line", "直线"),
            ("continuous", "连续线"),
            ("rectangle", "矩形"),
            ("circle", "圆"),
            ("arc", "圆弧"),
            ("spline", "样条"),
            ("trim", "修剪"),
            ("extend", "延伸"),
            ("offset", "偏移"),
            ("mirror", "镜像"),
        ):
            action = self.menu_part_sketch.addAction(label)
            self.action_catalog.register(f"part-sketch.{tool}", action)
            action.setEnabled(self._services is not None)
            action.triggered.connect(partial(self._start_part_sketch_tool, tool))
            if tool == "rectangle":
                self.act_part_rectangle = action
        self.act_sketch_constraints = self.menu_feature.addAction("草图约束")
        self.act_sketch_constraints.setEnabled(self._services is not None)
        self.act_sketch_constraints.setToolTip("为已有草图预览并确认参数化约束。")
        self.act_sketch_constraints.triggered.connect(self._on_sketch_constraints)

        self.menu_tools = self.menuBar().addMenu("工具")
        self.act_options = self.menu_tools.addAction("选项")
        self.act_options.triggered.connect(self._show_options)
        self.act_units = self.menu_tools.addAction("单位")
        self.act_units.triggered.connect(self._show_units)
        self.act_measure = self.menu_tools.addAction("测量")
        self.act_measure.setEnabled(False)
        self.act_measure.triggered.connect(self._show_measure_panel)
        self.act_rebuild = self.menu_tools.addAction("重建")
        self.act_rebuild.triggered.connect(self.request_rebuild)
        self.act_check_shortcuts = self.menu_tools.addAction("检查快捷键冲突")
        self.act_check_shortcuts.triggered.connect(self._show_shortcut_conflicts)

        self.menu_agent = self.menuBar().addMenu("智能体")
        self.act_view_plans = self.menu_agent.addAction("查看待确认计划")
        self._set_action_shortcut(
            self.act_view_plans,
            QKeySequence("Ctrl+Shift+P"),
            explanation="打开当前计划确认卡片",
        )
        self.act_view_plans.triggered.connect(self._show_plan_cards)
        self.act_view_plans.setEnabled(False)
        self.act_view_plans.setToolTip("需要可用的计划执行器；创建或打开文档后可查看计划。")
        self.act_show_ai = self.menu_agent.addAction("AI 对话")
        self.act_show_ai.setEnabled(False)
        self.act_show_ai.triggered.connect(self._show_ai_panel)
        self.act_clear_chat = self.menu_agent.addAction("清空对话")
        self.act_clear_chat.triggered.connect(lambda: self.ai_chat.clear())
        self.act_clear_chat.setEnabled(False)
        self.act_clear_chat.setToolTip("清空 AI 对话记录与输入草稿。")

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
        self.main_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.main_toolbar.setIconSize(QSize(20, 20))
        self.application_button = QToolButton(self.main_toolbar)
        self.application_button.setObjectName("applicationMenuButton")
        self.application_button.setText("文件")
        self.application_button.setMenu(self.menu_file)
        self.application_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.main_toolbar.addWidget(self.application_button)
        self.main_toolbar.addSeparator()
        self._action_icon_names: dict[QAction, str] = {}
        self.act_view_2d = self.menu_view.addAction("二维绘图")
        self.act_view_3d = self.menu_view.addAction("三维视图")
        self.act_view_2d.setCheckable(True)
        self.act_view_3d.setCheckable(True)
        self.act_view_3d.setChecked(True)
        self.act_view_2d.triggered.connect(self._show_drawing2d_workspace)
        self.act_view_3d.triggered.connect(self._show_3d_workspace)
        self.action_catalog.register("ui.view.2d", self.act_view_2d)
        self.action_catalog.register("ui.view.3d", self.act_view_3d)
        groups = (
            ((self.act_new, "new"), (self.act_open, "open"), (self.act_save, "save")),
            ((self.act_undo, "undo"), (self.act_redo, "redo")),
        )
        for group in groups:
            for action, name in group:
                self._action_icon_names[action] = name
                self.main_toolbar.addAction(action)
            self.main_toolbar.addSeparator()
        self.menu_feature.addSeparator()
        for label, command_id in (
            ("长方体", "feature.box"),
            ("圆柱体", "feature.cylinder"),
            ("球体", "feature.sphere"),
            ("拉伸", "feature.extrude"),
            ("旋转", "feature.revolve"),
            ("孔", "feature.hole"),
            ("孔阵列", "feature.hole_pattern"),
            ("圆角", "modify.fillet"),
            ("差集", "modify.boolean_cut"),
            ("交集", "modify.boolean_intersect"),
            ("实体布尔", "modify.boolean_bodies"),
            ("实体变换", "modify.body_transform"),
            ("实体阵列", "modify.body_pattern"),
        ):
            action = QAction(label, self)
            self.action_catalog.register(command_id, action)
            shortcut_text = {
                "feature.extrude": "Ctrl+Shift+E",
                "feature.revolve": "Ctrl+Shift+R",
                "feature.hole": "Ctrl+Shift+H",
                "modify.fillet": "Ctrl+Shift+F",
            }.get(command_id, "")
            self._action_icon_names[action] = command_icon_name(command_id)
            self._set_action_shortcut(
                action,
                QKeySequence(shortcut_text),
                explanation=f"{label}（{command_id}）：选取几何并设置参数，预览后应用执行",
            )
            action.setEnabled(self.plan_draft is not None)
            self._part_only_actions.append(action)
            if self.plan_draft is None:
                action.setToolTip(f"{label} 需要可用的应用服务和计划执行器。")
            action.triggered.connect(partial(self._on_toolbar_modeling, command_id))
            self.menu_feature.addAction(action)
            self.modeling_toolbar.addAction(action)

        self.act_bound_hole = QAction("绑定面孔", self)
        self._action_icon_names[self.act_bound_hole] = command_icon_name("feature.hole")
        self.act_bound_hole.setToolTip("绑定盒体面或圆柱端面；旧存档将在确认时升级。")
        self.act_bound_hole.setEnabled(self._services is not None)
        self.act_bound_hole.triggered.connect(self._start_bound_hole_task)
        self.action_catalog.register("ui.feature.bound_hole", self.act_bound_hole)
        self._part_only_actions.append(self.act_bound_hole)
        self.menu_feature.addAction(self.act_bound_hole)

        self._action_icon_names.update(
            zip(
                self.menu_part_sketch.actions(),
                (
                    "sketch",
                    "draw-point",
                    "draw-line",
                    "draw-polyline",
                    "draw-rectangle",
                    "draw-circle",
                    "draw-arc",
                    "draw-spline",
                    "draw-trim",
                    "draw-extend",
                    "edit-offset",
                    "edit-mirror",
                ),
                strict=True,
            )
        )
        self._build_part_ribbon()
        self._action_icon_names.update(self._menu_icon_names())
        self._refresh_action_icons()

    def _build_part_ribbon(self) -> None:
        catalog = self.action_catalog
        home = self._ribbon_model_layout
        home.addWidget(RibbonGroup("选择", (self.act_select_filter,), ()))
        home.addWidget(RibbonGroup("草图", (self.act_sketch,), (self.act_sketch_constraints,)))
        home.addWidget(
            RibbonGroup(
                "基础体",
                (),
                tuple(
                    catalog.get(key)
                    for key in ("feature.box", "feature.cylinder", "feature.sphere")
                ),
            )
        )
        home.addWidget(
            RibbonGroup(
                "特征",
                tuple(
                    catalog.get(key)
                    for key in ("feature.extrude", "feature.revolve", "feature.hole")
                ),
                (catalog.get("feature.hole_pattern"), self.act_bound_hole),
            )
        )
        home.addWidget(
            RibbonGroup(
                "修改与阵列",
                (),
                tuple(
                    catalog.get(key)
                    for key in (
                        "modify.fillet",
                        "modify.boolean_cut",
                        "modify.boolean_intersect",
                        "modify.boolean_bodies",
                        "modify.body_transform",
                        "modify.body_pattern",
                    )
                ),
            )
        )
        home.addStretch()
        sketch_actions = [
            action for action in self.menu_part_sketch.actions() if not action.isSeparator()
        ]
        self._ribbon_entry_layout.addWidget(RibbonGroup("草图", sketch_actions[:1], ()))
        self._ribbon_entry_layout.addWidget(RibbonGroup("绘制", (), sketch_actions[1:]))
        self._ribbon_entry_layout.addStretch()
        self._ribbon_inspect_page.content_layout.addWidget(
            RibbonGroup("测量", (self.act_measure,), ())
        )
        self._ribbon_inspect_page.content_layout.addStretch()
        self._ribbon_tools_page.content_layout.addWidget(
            RibbonGroup("设置", (self.act_options,), (self.act_units, self.act_rebuild))
        )
        self._ribbon_tools_page.content_layout.addStretch()
        self._ribbon_view_page.content_layout.addWidget(
            RibbonGroup(
                "视图",
                (self.act_fit_view,),
                (
                    self.act_standard_orientation,
                    self.render_mode_menu.menuAction(),
                    self.act_show_coordinate_axes,
                    self.act_show_xy_grid,
                ),
            )
        )
        self._ribbon_view_page.content_layout.addStretch()

    def _menu_icon_names(self) -> dict[QAction, str]:
        icons = {
            self.act_save_as: "save-as",
            self.act_import: "import",
            self.act_export: "export",
            self.act_screenshot: "camera",
            self.act_quit: "exit",
            self.act_delete: "delete",
            self.act_select_filter: "filter",
            self.render_mode_menu.menuAction(): "shaded-edges",
            self.act_standard_orientation: "view-isometric",
            self.projection_menu.menuAction(): "perspective",
            self.act_show_coordinate_axes: "axes",
            self.act_show_xy_grid: "grid",
            self.menu_appearance.menuAction(): "appearance",
            self.act_theme_light: "light",
            self.act_theme_dark: "dark",
            self.act_show_cli: "console",
            self.act_reset_layout: "layout",
            self.act_toggle_toolbar: "panel-top",
            self.act_lock_toolbar: "lock",
            self.act_toggle_left_dock: "panel-left",
            self.act_toggle_right_dock: "panel-right",
            self.act_toggle_bottom_dock: "panel-bottom",
            self.act_open_palette: "features",
            self.act_options: "settings",
            self.act_units: "units",
            self.act_measure: "measure",
            self.act_rebuild: "rebuild",
            self.act_clear_chat: "delete",
            self.act_shortcuts: "keyboard",
            self.act_command_reference: "reference",
            self.act_about: "info",
            self.act_license: "license",
        }
        icons.update(
            {
                action: ("box" if kind == "body" else kind)
                for kind, action in self.selection_filter_actions.items()
            }
        )
        render_icons = {
            "shaded": "shaded",
            "shaded-edges": "shaded-edges",
            "engineering-wireframe": "wireframe",
            "mesh-diagnostic": "mesh",
        }
        icons.update(
            {action: render_icons[mode] for mode, action in self.render_mode_actions.items()}
        )
        icons.update(
            {
                action: f"view-{orientation}"
                for orientation, action in self.orientation_actions.items()
            }
        )
        icons.update({action: mode for mode, action in self.projection_actions.items()})
        return icons

    def _refresh_action_icons(self) -> None:
        for action, name in self._action_icon_names.items():
            action.setIcon(cad_icon(name, self._theme_name))
            action.setIconVisibleInMenu(True)

    def _on_toolbar_modeling(self, command_id: str, _checked: bool = False) -> None:
        """工具栏建模按钮：与左栏命令库双击同一条路径。"""
        self._on_palette_command(command_id)

    def _apply_toolbar_lock(self, locked: bool) -> None:
        """锁定工具栏：锁定后既不可拖动也不可悬浮."""
        for bar in (self.main_toolbar, self.modeling_toolbar):
            bar.setMovable(not locked)
            bar.setFloatable(not locked)
        if self._sketch_dialog is not None:
            self._sketch_dialog.set_toolbars_locked(locked)

    def _open_left_palette(self) -> None:
        if self.left_tabs is not None and self.command_palette is not None:
            self.left_tabs.setCurrentWidget(self.command_palette)
        self.left_dock.show()
        self.left_dock.raise_()

    def _on_part_sketch_edit_requested(self, sketch_id: str) -> None:
        if self._services is None or self._loaded is None or self.viewport is None:
            return
        if self.part_sketch_task is not None:
            self.status_command.setText("请先完成或取消当前零件草图。")
            self.part_sketch_task.raise_()
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("几何工作线程忙碌，请稍后编辑草图。")
            return
        sketches = [item for item in self._services.kernel.sketches if item.sketch_id == sketch_id]
        if len(sketches) != 1:
            self.status_command.setText("无法唯一定位草图，请检查模型历史。")
            return
        self._end_modeling_tool(cancel_editor=True)
        self._show_3d_workspace()
        self.viewport.show_current_model()
        loaded = self._loaded
        task = PartSketchWorkbench(
            self._services,
            self._loaded,
            self.viewport,
            session_identity=self._session_id,
            current_session=lambda: self._session_id,
            can_execute=lambda: (
                self.execution_unit is None
                or not (self.execution_unit.is_busy or self.execution_unit.is_notifying_result)
            ),
            existing_sketch=sketches[0],
            parent=self,
        )
        self.part_sketch_task = task

        def finished(result: int) -> None:
            if self.part_sketch_task is task:
                self.part_sketch_task = None
            self._refresh_document_choice()
            if result == QDialog.DialogCode.Accepted and self._loaded is loaded:
                self._select_completed_part_sketch(task, loaded)

        task.finished.connect(finished)
        self._show_part_sketch_command_bar(task)

    def _show_part_sketch_command_bar(self, task: PartSketchWorkbench) -> None:
        """Place the active controls on the resident sketch ribbon page."""
        if self._small_screen_active:
            self.act_expand_compact_ribbon.setChecked(True)
        self._set_workspace_environment("part-sketch")
        self.workspace_layout.save("part", self._layout_state_for_persistence())
        self.workspace_layout.save_locked("part", self.act_lock_toolbar.isChecked())
        task.setWindowFlags(Qt.WindowType.Widget)
        scroll = QScrollArea(self._ribbon_sketch_stack)
        scroll.setWidgetResizable(True)
        scroll.setWidget(task)
        self._ribbon_sketch_stack.addWidget(scroll)
        self._ribbon_sketch_stack.setCurrentWidget(scroll)
        self.part_ribbon.setCurrentIndex(1)

        def remove_bar(_result: int) -> None:
            if self._small_screen_active:
                self.act_expand_compact_ribbon.setChecked(False)
            self._set_workspace_environment("part")
            if self._home_visibility is None:
                self.workspace_layout.save("part-sketch", self._layout_state_for_persistence())
                self.workspace_layout.save_locked("part-sketch", self.act_lock_toolbar.isChecked())
            self._ribbon_sketch_stack.setCurrentWidget(self._ribbon_sketch_entry)
            self._ribbon_sketch_stack.removeWidget(scroll)
            scroll.takeWidget()
            task.setParent(self)
            scroll.deleteLater()
            if self._home_visibility is None:
                state = self.workspace_layout.load("part")
                if state is not None:
                    self._restore_layout_for_small_screen(state)
                self.act_lock_toolbar.setChecked(self.workspace_layout.load_locked("part") or False)

        task.finished.connect(remove_bar)
        task.show()
        state = self.workspace_layout.load("part-sketch")
        if state is not None:
            self._restore_layout_for_small_screen(state)
        self.act_lock_toolbar.setChecked(self.workspace_layout.load_locked("part-sketch") or False)

    def _select_completed_part_sketch(
        self, task: PartSketchWorkbench, loaded: LoadedDocument
    ) -> None:
        sketch_id = task.session.sketch.sketch_id
        self._preferred_part_sketch = (loaded, sketch_id)
        self._preferred_part_region = (
            (loaded, sketch_id, task.selected_region_ids)
            if task.selected_region_ids is not None
            else None
        )
        command = next(
            (
                item
                for item in loaded.document.commands
                if item.id == "sketch.create" and item.params.get("sketch_id") == sketch_id
            ),
            None,
        )
        if command is not None and self.right_panel is not None:
            self.right_panel.select_feature_ordinal(command.ordinal)
        self.status_command.setText("草图已提交；可启动拉伸。")

    def _start_part_sketch_tool(self, tool: str, _checked: bool = False) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("几何工作线程忙碌，请等待当前操作完成后切换草图工具。")
            return
        if self._loaded is None or self._loaded.document.document_type != "part":
            self.status_command.setText("请先激活三维零件。")
            return
        self._on_sketch_start()
        if self.part_sketch_task is not None:
            self.part_sketch_task.select_tool(tool)

    def _on_sketch_start(self, _checked: bool = False) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("几何工作线程忙碌，请等待当前操作完成后开始草图。")
            return
        if not self._cancel_history_edit():
            return
        if not self._cancel_history_repair():
            return
        if not self._cancel_bound_hole():
            return
        if self.datum_task is not None:
            self.datum_task.reject()
        if self._services is None or self._loaded is None:
            self.status_command.setText("创建或打开文档后才能开始草图。")
            return
        if self._loaded.document.document_type == "part":
            if self.part_sketch_task is not None:
                self.part_sketch_task.show()
                self.part_sketch_task.raise_()
                return
            if self.viewport is None:
                return
            attached_frame: WorkPlaneFrame | None = None
            support_face: SketchSupportFace | None = None
            selection = self.viewport.selection()
            if selection is not None and selection.kind == "face":
                if len(selection.topology_ids) != 1:
                    self.status_command.setText("附着草图需要只选择一个平面。")
                    return
                try:
                    descriptor = mycad_app.interactive_selectors(
                        self._services, "face", selection.topology_ids
                    )[0]
                    if descriptor.get("surface") != "plane":
                        self.status_command.setText("草图只能附着到平面；请重新选择模型面。")
                        return
                    face_frame = mycad_app.interactive_face_frame(
                        self._services, selection.topology_ids[0]
                    )
                    attached_frame = WorkPlaneFrame.from_planar_face(
                        face_frame.origin, face_frame.normal
                    )
                    support_face = SketchSupportFace.from_mapping(descriptor)
                except (MycadError, ValueError) as err:
                    self.status_command.setText(f"无法将草图附着到所选面：{str(err)[:180]}")
                    return
            self._end_modeling_tool(cancel_editor=True)
            self._show_3d_workspace()
            loaded = self._loaded
            task = PartSketchWorkbench(
                self._services,
                self._loaded,
                self.viewport,
                session_identity=self._session_id,
                current_session=lambda: self._session_id,
                can_execute=lambda: (
                    self.execution_unit is None
                    or not (self.execution_unit.is_busy or self.execution_unit.is_notifying_result)
                ),
                attached_frame=attached_frame,
                support_face=support_face,
                parent=self,
            )
            self.part_sketch_task = task

            def part_finished(result: int) -> None:
                if self.part_sketch_task is task:
                    self.part_sketch_task = None
                self._refresh_document_choice()
                if result == QDialog.DialogCode.Accepted and self._loaded is loaded:
                    self._select_completed_part_sketch(task, loaded)

            task.finished.connect(part_finished)
            self._show_part_sketch_command_bar(task)
            return
        if self._sketch_dialog is not None:
            self._show_sketch_workbench(self._sketch_dialog)
            return
        dialog = SketchEditorDialog(
            self,
            can_finish=lambda: (
                self.execution_unit is not None
                and not (self.execution_unit.is_busy or self.execution_unit.is_notifying_result)
            ),
            drag_preview=self._services.kernel.preview_sketch_drag,
            continuous_lines=True,
            select_committed_entities=self._loaded.document.document_type == "drawing2d",
            constraint_preview=self._services.kernel.preview_sketch_constraint,
            constraint_update_preview=self._services.kernel.preview_sketch_constraint_update,
        )
        dialog.toolbar_host.statusBar().hide()
        dialog.status_label.text_changed.connect(partial(self._on_drafting_message, dialog, False))
        dialog.status_label.transient_changed.connect(
            partial(self._on_drafting_message, dialog, True)
        )
        dialog.document_layer_mode = True
        dialog.document_undo_requested.connect(self.request_undo)
        dialog.document_redo_requested.connect(self.request_redo)

        def committed_move(ids: object, delta: object) -> None:
            self._on_drawing_move(dialog, self._session_id, ids, delta)

        dialog.canvas.committed_move_requested.connect(committed_move)

        def committed_delete(ids: object) -> None:
            self._on_drawing_move(dialog, self._session_id, ids, (0.0, 0.0), erase=True)

        dialog.canvas.committed_delete_requested.connect(committed_delete)

        def committed_rotation(ids: object, center: object, angle: object) -> None:
            if not isinstance(angle, int | float) or not isfinite(angle):
                return
            self._on_drawing_move(dialog, self._session_id, ids, center, angle=float(angle))

        dialog.canvas.committed_rotation_requested.connect(committed_rotation)

        def committed_mirror(ids: object, start: object, end: object) -> None:
            if not isinstance(end, tuple):
                return
            raw_end = cast("tuple[object, ...]", end)
            if len(raw_end) != 2 or not all(
                isinstance(value, int | float) and isfinite(value) for value in raw_end
            ):
                return
            self._on_drawing_move(
                dialog, self._session_id, ids, start, mirror_end=cast("tuple[float, float]", end)
            )

        dialog.canvas.committed_mirror_requested.connect(committed_mirror)

        def store_copy_mode(mode: int) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_COPY_MODE, mode)

        dialog.canvas.copy_mode_changed.connect(store_copy_mode)

        def layer_changed(payload: object) -> None:
            self._on_drawing_layer_update(dialog, self._session_id, payload)

        dialog.layer_change_requested.connect(layer_changed)
        dialog.set_document_layers(
            self._services.kernel.drawing_layers, self._services.kernel.dimension_layer
        )
        dialog.view_3d_requested.connect(self._show_3d_workspace)

        def dimension_committed(sketch: Sketch, constraint: SketchConstraint) -> None:
            self._on_canvas_dimension_commit(dialog, self._session_id, sketch, constraint)

        def dimension_preview(
            sketch: Sketch, constraint: SketchConstraint, generation: int
        ) -> None:
            self._on_canvas_dimension_preview(
                dialog, self._session_id, sketch, constraint, generation
            )

        dialog.dimensions.committed_requested.connect(dimension_committed)
        dialog.dimensions.preview_requested.connect(dimension_preview)
        dialog.restore_toolbar_layout(self._drafting_toolbar_state)
        dialog.set_toolbars_locked(self.act_lock_toolbar.isChecked())
        self._sketch_dialog = dialog
        dialog.plane_combo.currentTextChanged.connect(self._sync_camera_status)
        dialog.set_context_sketches(self._services.kernel.sketches)

        def finished(result: int) -> None:
            self._on_sketch_editor_finished(dialog, self._session_id, result)

        dialog.finished.connect(finished)
        dialog.canvas.changed.connect(self._refresh_document_choice)
        self._show_sketch_workbench(dialog)
        self.status_command.setText("二维绘图：主工作区内编辑；完成草图提交，取消草稿不写入。")

    @property
    def active_workspace(self) -> WorkspaceId:
        return self.workspace_tabs.active_workspace

    def _on_engineering_message(self, text: str) -> None:
        if self.active_workspace == "drawing":
            self.status_command.setText(text)

    def _on_owned_engineering_message(self, bench: DrawingWorkbench, text: str) -> None:
        if bench is self.drawing_workbench:
            self._on_engineering_message(text)

    def _on_workspace_changed(self, previous: str, current: str) -> None:
        if (
            (
                self.bound_hole_task is not None
                or self.history_repair_task is not None
                or self.history_edit_task is not None
            )
            and previous == "model"
            and current != "model"
            and not self._session_binding
            and not self._workspace_transition
        ):
            self._workspace_transition = True
            try:
                self.workspace_tabs.activate("model")
            finally:
                self._workspace_transition = False
            label = (
                "绑定孔"
                if self.bound_hole_task is not None
                else "历史修复"
                if self.history_repair_task is not None
                else "历史编辑"
            )
            self.status_command.setText(f"请先完成或取消{label}，再切换工作区。")
            return
        if (
            self.document_session is not None
            and not self._session_binding
            and not self._workspace_transition
        ):
            draft_blocked = (
                (self.part_sketch_task is not None and self.part_sketch_task.has_draft)
                or self._active_modeling_command is not None
                or self.datum_task is not None
                or self.bound_hole_task is not None
                or self.history_repair_task is not None
                or self.history_edit_task is not None
            )
            busy = self.execution_unit is not None and (
                self.execution_unit.is_busy or self.execution_unit.is_notifying_result
            )
            if draft_blocked or busy:
                self._workspace_transition = True
                try:
                    self.workspace_tabs.activate(cast("WorkspaceId", previous))
                finally:
                    self._workspace_transition = False
                self.status_command.setText(
                    "请先完成或取消当前命令，再切换文档。"
                    if draft_blocked
                    else "操作完成后才能切换文档。"
                )
                return
            kind: DocumentKind = (
                "part" if current == "model" else "drawing" if current == "drawing" else "sketch"
            )
            entry = self.document_session.latest(kind)
            if entry is None:
                self._workspace_transition = True
                try:
                    self.workspace_tabs.activate(cast("WorkspaceId", previous))
                finally:
                    self._workspace_transition = False
                self.status_command.setText("该工作区尚无文档，请从首页或文件菜单新建。")
                return
            self.activate_session_document(entry.loaded.document.document_id)
            return
        if self.document_session is None:
            environment = (
                "drawing"
                if current == "drawing"
                else "drawing2d"
                if current == "sketch"
                else "part-sketch"
                if self.part_sketch_task is not None
                else "part"
            )
            self._set_workspace_environment(environment)
        self.part_sketch_entry_toolbar.setVisible(current == "model")
        if previous == "model" and current != "model" and self._sketch_dock_visibility is None:
            self._modeling_toolbar_was_visible = not self.modeling_toolbar.isHidden()
            self._sketch_dock_visibility = (self.left_dock.isVisible(), self.right_dock.isVisible())
        if current == "model":
            if self._sketch_dock_visibility is not None:
                left, right = self._sketch_dock_visibility
                self._sketch_dock_visibility = None
                self.left_dock.setVisible(left)
                self.right_dock.setVisible(right)
                self.modeling_toolbar.setVisible(self._modeling_toolbar_was_visible)
        else:
            self.left_dock.hide()
            self.right_dock.hide()
            self.modeling_toolbar.hide()
        self._sync_workspace_actions()
        self.act_view_2d.setChecked(current == "sketch")
        self.act_view_3d.setChecked(current == "model")
        if current == "sketch" and not self._session_binding:
            self._on_sketch_start()
        elif current == "drawing":
            if (
                self.bottom_tabs is not None
                and self.bottom_dock.isHidden()
                and not self._small_screen_active
            ):
                self.bottom_tabs.set_expanded(False)
                self.act_toggle_bottom_dock.setChecked(True)
            self.drawing_workbench.refresh()
            self.status_command.setText(self.drawing_workbench.hint.text())
        self._sync_camera_status()

    def _sync_workspace_actions(self) -> None:
        for action in (
            *self.orientation_actions.values(),
            *self.projection_actions.values(),
            *self.render_mode_actions.values(),
        ):
            action.setEnabled(self.active_workspace == "model" and self._loaded is not None)
        for action in self._part_only_actions:
            action.setEnabled(
                self.active_workspace == "model"
                and self._loaded is not None
                and self._loaded.document.document_type == "part"
            )

    def _show_drawing2d_workspace(self, _checked: bool = False) -> None:
        if self.document_session is None and (
            self._loaded is None or self._loaded.document.document_type != "drawing2d"
        ):
            self.status_command.setText("请先新建或打开二维图文档。")
            self.act_view_2d.setChecked(self.active_workspace == "sketch")
            return
        self.workspace_tabs.activate("sketch")
        self.act_view_2d.setChecked(self.active_workspace == "sketch")
        self.act_view_3d.setChecked(self.active_workspace == "model")

    def _show_3d_workspace(self, _checked: bool = False) -> None:
        self.workspace_tabs.activate("model")
        self.act_view_2d.setChecked(self.active_workspace == "sketch")
        self.act_view_3d.setChecked(self.active_workspace == "model")
        if self.active_workspace != "model":
            return
        self.status_command.setText("三维视图显示已提交模型；其他工作区草稿已保留。")
        if self.viewport is not None:
            self.viewport.setFocus()
        self._sync_camera_status()

    def _show_sketch_workbench(self, dialog: SketchEditorDialog) -> None:
        copy_mode = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_COPY_MODE, 0)
        dialog.canvas.set_copy_mode(1 if copy_mode in (1, "1") else 0)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        self.workspace_tabs.set_content("sketch", dialog)
        self._workspace_transition = True
        try:
            self.workspace_tabs.activate("sketch")
        finally:
            self._workspace_transition = False
        dialog.show()
        dialog.canvas.setFocus()
        dialog.set_compact_layout(self._small_screen_active)
        if (
            self.bottom_tabs is not None
            and self.bottom_dock.isHidden()
            and not self._small_screen_active
        ):
            self.bottom_tabs.set_expanded(False)
            self.act_toggle_bottom_dock.setChecked(True)
        self.status_command.setText(dialog.status_label.text())
        self._sync_camera_status()
        if self.document_session is not None and self.document_session.active is not None:
            self.document_session.active.draft = dialog
            self._refresh_document_choice()

    def _hide_sketch_workbench(self, dialog: SketchEditorDialog) -> None:
        self._drafting_toolbar_state = dialog.toolbar_layout_state()
        if self.workspace_tabs.content("sketch") is dialog:
            self.workspace_tabs.set_content("sketch", None)
        if self.active_workspace == "sketch":
            self._workspace_transition = True
            try:
                self.workspace_tabs.activate("model")
            finally:
                self._workspace_transition = False
        self._sync_camera_status()

    def _sync_drawing_layers(self) -> None:
        editor, services = self._sketch_dialog, self._services
        if editor is not None and services is not None:
            editor.set_context_sketches(services.kernel.sketches)
            editor.set_document_layers(
                services.kernel.drawing_layers, services.kernel.dimension_layer
            )

    def _on_drawing_move(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        ids: object,
        delta: object,
        *,
        angle: float | None = None,
        mirror_end: tuple[float, float] | None = None,
        erase: bool = False,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        if angle is not None and abs((angle + 180.0) % 360.0 - 180.0) <= 1e-10:
            editor.status_label.setText("旋转角度为零；图元未修改。")
            return
        if not isinstance(ids, tuple) or not isinstance(delta, tuple):
            return
        raw_ids = cast("tuple[object, ...]", ids)
        raw_delta = cast("tuple[object, ...]", delta)
        if (
            len(raw_delta) != 2
            or not all(isinstance(item, str) for item in raw_ids)
            or not all(isinstance(item, int | float) for item in raw_delta)
        ):
            return
        selected = cast("tuple[str, ...]", raw_ids)
        displacement = cast("tuple[float, float]", raw_delta)
        action = (
            "删除"
            if erase
            else "镜像"
            if mirror_end is not None
            else "旋转"
            if angle is not None
            else "移动"
        )
        draft_ids = tuple(
            entity.entity_id for entity in editor.canvas.entities if entity.entity_id in selected
        )
        if draft_ids or editor.canvas.mixed_move is not None:
            self._stage_drawing_mixed_move(
                editor, session_id, selected, displacement, angle=angle, mirror_end=mirror_end
            )
            return
        committed_ids = set(selected)
        sketches = tuple(
            sketch
            for sketch in services.kernel.sketches
            if any(entity.entity_id in committed_ids for entity in sketch.entities)
        )
        if not sketches or not committed_ids.issubset(
            entity.entity_id for sketch in sketches for entity in sketch.entities
        ):
            editor.status_label.setText("选择的图元已变化；所选对象保持不变。")
            return
        revisions: list[dict[str, object]] = []
        includes_points = False
        for sketch in sketches:
            sketch_ids = tuple(
                entity.entity_id for entity in sketch.entities if entity.entity_id in committed_ids
            )
            if erase and any(
                any(ref.entity_id in sketch_ids for ref in constraint.references)
                and (
                    editor.canvas.annotation_layer(constraint).locked
                    or not editor.canvas.annotation_layer(constraint).displayed
                )
                for constraint in sketch.constraints
            ):
                editor.status_label.setText("相关约束位于已锁定或隐藏图层；图元未修改。")
                return
            if erase:
                changed = tuple(
                    entity for entity in sketch.entities if entity.entity_id not in sketch_ids
                )
            elif mirror_end is not None:
                start = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                end = sketch.frame.world_to_local(editor.current_frame().local_to_world(mirror_end))
                changed = mirror_entities(sketch.entities, sketch_ids, start, end)
            elif angle is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                changed = rotate_entities(sketch.entities, sketch_ids, center, angle)
            else:
                changed = move_entities(sketch.entities, sketch_ids, displacement)
            if changed == sketch.entities:
                continue
            constraints = tuple(
                constraint
                for constraint in sketch.constraints
                if not erase
                or all(ref.entity_id not in sketch_ids for ref in constraint.references)
            )
            revised = replace(sketch, entities=changed, constraints=constraints)
            includes_points = includes_points or any(
                isinstance(entity, PointEntity) for entity in revised.entities
            )
            frozen = revised.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": frozen["entities"],
                    "constraints": frozen["constraints"],
                }
            )
        if not revisions:
            editor.status_label.setText(f"{action}未改变图元。")
            return
        editor.setEnabled(False)

        def update() -> object:
            candidate = mycad_app.create_replay_candidate(
                services, loaded, session_identity=session_id
            )
            candidate.stage(
                ReplayChangeSet(
                    (),
                    (
                        ReplayAppend(
                            "drawing.sketch.revise" if len(revisions) > 1 else "sketch.revise",
                            1 if len(revisions) > 1 else 2 if includes_points else 1,
                            {"revisions": revisions} if len(revisions) > 1 else revisions[0],
                            "local",
                        ),
                    ),
                    False,
                    6 if loaded.document.archive_version < 6 else None,
                ),
                current_session_identity=session_id,
            )
            preview = candidate.preview(current_session_identity=session_id)
            if preview.state != "succeeded":
                raise ValueError(str(preview.failure or "草图修订预览失败"))
            return candidate.commit(
                candidate.authorize_commit(current_session_identity=session_id),
                current_session_identity=session_id,
            )

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if self._loaded is not loaded or self._session_id != session_id:
                return
            self._sync_drawing_layers()
            if result.error is not None:
                editor.status_label.setText(f"{action}失败：{result.error}")
                return
            editor.layer_history_boundaries[len(loaded.document.commands)] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            editor.status_label.setText(f"已{action}所选对象；可撤销。")

        if not unit.submit(
            update, operation="drawing-move", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            editor.status_label.setText(f"几何工作线程忙碌，{action}未应用。")

    def _stage_drawing_mixed_move(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        selected: tuple[str, ...],
        displacement: tuple[float, float],
        *,
        angle: float | None = None,
        mirror_end: tuple[float, float] | None = None,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        canvas = editor.canvas
        previous = canvas.mixed_move
        original_draft = (
            previous.original_draft
            if previous is not None
            else Sketch(
                editor.draft_sketch_id,
                editor.current_frame(),
                tuple(canvas.entities),
                constraints=tuple(canvas.constraints),
                layers=canvas.layer_table,
            )
        )
        original_saved = previous.original_saved if previous else services.kernel.sketches
        current_saved = previous.current_saved if previous else original_saved
        if previous is not None and editor.current_frame() != previous.original_draft.frame:
            editor.status_label.setText("工作平面已变化；请先撤销或取消暂存变换。")
            return
        if previous is not None and loaded.document.revision != previous.source_revision:
            editor.status_label.setText("文档已变化；暂存变换未提交，请撤销后重试。")
            return
        draft_ids = tuple(
            entity.entity_id for entity in canvas.entities if entity.entity_id in selected
        )
        saved_ids = set(selected) - set(draft_ids)
        if not saved_ids or not saved_ids.issubset(
            entity.entity_id for sketch in current_saved for entity in sketch.entities
        ):
            editor.status_label.setText("选择的已提交图元已变化；变换未应用。")
            return
        draft_entities = tuple(canvas.entities)
        if draft_ids:
            if mirror_end is not None:
                draft_entities = mirror_entities(
                    draft_entities, draft_ids, displacement, mirror_end
                )
            elif angle is not None:
                draft_entities = rotate_entities(draft_entities, draft_ids, displacement, angle)
            else:
                draft_entities = move_entities(draft_entities, draft_ids, displacement)
        revised_saved: list[Sketch] = []
        for sketch in current_saved:
            ids = tuple(
                entity.entity_id for entity in sketch.entities if entity.entity_id in saved_ids
            )
            if ids and mirror_end is not None:
                start = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                end = sketch.frame.world_to_local(editor.current_frame().local_to_world(mirror_end))
                changed = mirror_entities(sketch.entities, ids, start, end)
            elif ids and angle is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                changed = rotate_entities(sketch.entities, ids, center, angle)
            elif ids:
                changed = move_entities(sketch.entities, ids, displacement)
            else:
                changed = sketch.entities
            revised_saved.append(replace(sketch, entities=changed))
        if tuple(revised_saved) == tuple(current_saved):
            if draft_entities == tuple(canvas.entities):
                editor.status_label.setText("变换未改变图元。")
            else:
                canvas.replace_draft_entities(draft_entities)
            return
        background = canvas.background_entities
        overlay_source = tuple(entity for entity, _layer in background)
        if mirror_end is not None:
            overlay = mirror_entities(overlay_source, tuple(saved_ids), displacement, mirror_end)
        elif angle is not None:
            overlay = rotate_entities(overlay_source, tuple(saved_ids), displacement, angle)
        else:
            overlay = move_entities(overlay_source, tuple(saved_ids), displacement)
        proposed = MixedMoveState(
            previous.transaction_id if previous else uuid4().hex,
            previous.source_revision if previous else loaded.document.revision,
            original_draft,
            tuple(original_saved),
            tuple(revised_saved),
            previous.base_background if previous else background,
            tuple(
                (entity, layer) for entity, (_old, layer) in zip(overlay, background, strict=True)
            ),
        )
        draft = replace(
            original_draft,
            entities=draft_entities,
            constraints=tuple(canvas.constraints),
            layers=canvas.layer_table,
        )
        steps = (*canvas.mixed_move_timeline(), (proposed.current_saved, draft))
        editor.setEnabled(False)

        def preview() -> object:
            candidate = mycad_app.stage_mixed_drawing_timeline(
                services, loaded, original_draft, original_saved, steps, session_identity=session_id
            )
            result = candidate.preview(current_session_identity=session_id)
            candidate.cancel()
            if result.state != "succeeded":
                raise ValueError(str(result.failure or "混合变换预览失败"))
            return None

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._sketch_dialog is not editor
            ):
                return
            if result.error is not None:
                editor.status_label.setText(f"混合变换失败：{result.error}")
                return
            if loaded.document.revision != proposed.source_revision:
                editor.status_label.setText("文档已变化；混合变换未应用。")
                return
            canvas.apply_mixed_move(proposed, draft_entities)

        if not unit.submit(
            preview, operation="drawing-mixed-move", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            editor.status_label.setText("几何工作线程忙碌，变换未应用。")

    def _on_drawing_layer_update(
        self, editor: SketchEditorDialog, session_id: int, payload: object
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            loaded is None
            or services is None
            or unit is None
            or session_id != self._session_id
            or not isinstance(payload, dict)
        ):
            return
        data = cast("dict[str, object]", payload)
        params = data.get("params")
        if not isinstance(params, dict):
            return
        params = cast("dict[str, object]", params)
        migrate_draft = data.get("migrate_draft") is True
        commands = tuple(loaded.document.commands)
        editor.setEnabled(False)
        panel = editor.active_layer_manager
        if panel is not None:
            panel.setEnabled(False)

        def update() -> object:
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or tuple(loaded.document.commands) != commands
            ):
                raise ValueError("图纸已改变，本次图层修改未应用")
            return loaded.bus.execute("drawing.layers.set", params, confirmed_by="local")

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if panel is not None:
                panel.setEnabled(True)
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._sketch_dialog is not editor
            ):
                return
            self._sync_drawing_layers()
            if result.error is not None:
                editor.status_label.setText(f"图层修改失败：{result.error}")
                return
            editor.layer_history_boundaries[len(loaded.document.commands)] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            if migrate_draft:
                editor.apply_draft_dim_migration()
            if self.viewport is not None:
                self.viewport.refresh()
            editor.status_label.setText("图纸图层已更新；草稿和已提交对象同步，可撤销。")

        if not unit.submit(
            update, operation="drawing-layer-update", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            if panel is not None:
                panel.setEnabled(True)
            self._sync_drawing_layers()
            editor.status_label.setText("几何工作线程忙碌，请稍后修改图层。")

    def _on_canvas_dimension_preview(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        sketch: Sketch,
        constraint: SketchConstraint,
        generation: int,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        commands = tuple(loaded.document.commands)
        source_archive_version = loaded.document.archive_version
        updating = any(c.constraint_id == constraint.constraint_id for c in sketch.constraints)

        def solve() -> _SketchConstraintPreview:
            result = (
                services.kernel.preview_sketch_constraint_update(sketch, constraint)
                if updating
                else services.kernel.preview_sketch_constraint(sketch, constraint)
            )
            if result.status != "success":
                return _SketchConstraintPreview(result)
            snapshot, sketches = mycad_app.preview_command_with_sketches(
                services,
                commands,
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                result.command_params(sketch, constraint),
                source_archive_version=source_archive_version,
            )
            return _SketchConstraintPreview(result, snapshot, sketches)

        def finish(value: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            preview = value.value
            if tuple(loaded.document.commands) != commands:
                result = SketchConstraintSolveResult(
                    "failed", None, None, message="模型已改变，请重新拾取尺寸"
                )
            elif value.error is not None or not isinstance(preview, _SketchConstraintPreview):
                result = SketchConstraintSolveResult(
                    "failed", None, None, message=f"驱动预览失败：{value.error}"
                )
            else:
                result = preview.solve_result
            editor.dimensions.complete_preview(generation, sketch, constraint, result)

        if not unit.submit(
            solve, operation="canvas-dimension-preview", session_id=session_id, on_complete=finish
        ):
            editor.dimensions.complete_preview(
                generation,
                sketch,
                constraint,
                SketchConstraintSolveResult(
                    "failed", None, None, message="几何工作线程忙碌，请重新预览"
                ),
            )

    def _on_canvas_dimension_commit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        sketch: Sketch,
        constraint: SketchConstraint,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            editor.dimensions.complete_commit(
                sketch,
                constraint,
                SketchConstraintSolveResult("failed", None, None, message="草图所属文档已切换"),
            )
            return
        commands = tuple(loaded.document.commands)
        updating = any(c.constraint_id == constraint.constraint_id for c in sketch.constraints)

        def submit() -> SketchConstraintSolveResult:
            if (
                session_id != self._session_id
                or loaded is not self._loaded
                or editor.dimensions.candidate != constraint
                or tuple(loaded.document.commands) != commands
                or next(
                    (s for s in services.kernel.sketches if s.sketch_id == sketch.sketch_id), None
                )
                != sketch
            ):
                return SketchConstraintSolveResult(
                    "failed", None, None, message="模型或尺寸已改变，操作已取消"
                )
            result = (
                services.kernel.preview_sketch_constraint_update(sketch, constraint)
                if updating
                else services.kernel.preview_sketch_constraint(sketch, constraint)
            )
            if result.status != "success":
                return result
            if (
                session_id != self._session_id
                or loaded is not self._loaded
                or editor.dimensions.candidate != constraint
                or tuple(loaded.document.commands) != commands
            ):
                return SketchConstraintSolveResult(
                    "failed", None, None, message="尺寸求解期间操作已取消或文档已切换"
                )
            # An explicit placement/apply gesture authorizes this one replayable command.
            loaded.bus.execute(
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                result.command_params(sketch, constraint),
                confirmed_by="local",
            )
            return result

        def finish(value: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            result = value.value
            if value.error is not None or not isinstance(result, SketchConstraintSolveResult):
                result = SketchConstraintSolveResult(
                    "failed", None, None, message=f"尺寸提交失败：{value.error}"
                )
            if result.status == "success":
                editor.set_context_sketches(services.kernel.sketches)
                if self.viewport is not None:
                    self.viewport.refresh()
            editor.dimensions.complete_commit(sketch, constraint, result)
            self.status_command.setText(
                "尺寸已写入命令历史；可撤销、重做和保存重放。"
                if result.status == "success"
                else result.message or "尺寸提交失败"
            )

        if not unit.submit(
            submit, operation="canvas-dimension-commit", session_id=session_id, on_complete=finish
        ):
            editor.dimensions.complete_commit(
                sketch,
                constraint,
                SketchConstraintSolveResult(
                    "failed", None, None, message="几何工作线程忙碌，请重试"
                ),
            )

    def _on_sketch_constraints(
        self, _checked: bool = False, *, dimensions_only: bool = False
    ) -> None:
        if dimensions_only:
            self._on_sketch_start()
            if self._sketch_dialog is not None:
                self._sketch_dialog.dimensions.start("smart")
            return
        if self._services is None or self._loaded is None:
            self.status_command.setText("创建或打开文档后才能编辑草图约束。")
            return
        if self._sketch_constraint_dialog is not None:
            self._sketch_constraint_dialog.raise_()
            self._sketch_constraint_dialog.activateWindow()
            return
        sketches = self._services.kernel.sketches
        if not sketches:
            self.status_command.setText("当前文档还没有草图；先使用“草图”创建草图。")
            return
        self._cancel_active_modeling_tool()
        dialog = SketchConstraintDialog(
            sketches,
            self._services.kernel.preview_sketch_constraint,
            self,
            asynchronous_preview=True,
            preview_update=self._services.kernel.preview_sketch_constraint_update,
        )
        if dimensions_only:
            dialog.configure_dimensions()
        self._sketch_constraint_dialog = dialog
        if self._sketch_dialog is not None:
            dialog.solved_preview.connect(self._sketch_dialog.show_dimension_preview)
        session_id = self._session_id
        dialog.preview_requested.connect(
            partial(self._on_sketch_constraint_preview, dialog, session_id)
        )
        dialog.preview_invalidated.connect(self._clear_sketch_constraint_preview)
        dialog.commit_requested.connect(
            partial(self._on_sketch_constraint_commit, dialog, session_id)
        )
        dialog.finished.connect(partial(self._on_sketch_constraint_dialog_finished, dialog))
        dialog.exec()

    def _clear_sketch_constraint_preview(self) -> None:
        self._sketch_constraint_preview_revision = None
        if self._sketch_dialog is not None:
            self._sketch_dialog.clear_dimension_preview()
        if self.viewport is not None:
            self.viewport.clear_candidate_preview()

    def _on_sketch_constraint_preview(
        self,
        dialog: SketchConstraintDialog,
        session_id: int,
        sketch: Sketch,
        constraint: SketchConstraint,
        generation: int,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit

        def fail(message: str) -> None:
            dialog.complete_preview(
                generation,
                sketch,
                constraint,
                SketchConstraintSolveResult("failed", None, None, message=message),
            )

        if loaded is None or services is None or unit is None or session_id != self._session_id:
            fail("草图所属文档已切换，请重新打开约束编辑。")
            return
        commands = tuple(loaded.document.commands)
        source_archive_version = loaded.document.archive_version

        def build_preview() -> _SketchConstraintPreview:
            updating = any(
                item.constraint_id == constraint.constraint_id for item in sketch.constraints
            )
            solved = (
                services.kernel.preview_sketch_constraint_update(sketch, constraint)
                if updating
                else services.kernel.preview_sketch_constraint(sketch, constraint)
            )
            if solved.status != "success":
                # A failed solve may locate inputs, but never display its partial solution.
                if solved.conflicting_constraint_ids:
                    snapshots = services.kernel.viewport_data()
                    return _SketchConstraintPreview(
                        solved,
                        snapshots[-1] if snapshots else None,
                        services.kernel.sketch_display_data(),
                    )
                return _SketchConstraintPreview(solved)
            snapshot, sketches = mycad_app.preview_command_with_sketches(
                services,
                commands,
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                solved.command_params(sketch, constraint),
                source_archive_version=source_archive_version,
            )
            return _SketchConstraintPreview(solved, snapshot, sketches)

        def finish_preview(result: ExecutionResult) -> None:
            if (
                self._sketch_constraint_dialog is not dialog
                or session_id != self._session_id
                or loaded is not self._loaded
            ):
                return
            if tuple(loaded.document.commands) != commands:
                fail("模型已改变，预览已过期；请重新打开约束编辑。")
                return
            value = result.value
            if result.error is not None or not isinstance(value, _SketchConstraintPreview):
                fail(f"预览重建失败：{result.error or '几何服务返回无效结果'}")
                return
            accepted = dialog.complete_preview(generation, sketch, constraint, value.solve_result)
            if accepted and value.solve_result.status == "success":
                self._sketch_constraint_preview_revision = loaded.document.revision
            if accepted and value.viewport is not None and self.viewport is not None:
                affected = {
                    identity
                    for change in value.solve_result.branch_changes
                    for identity in change.entity_ids
                }
                conflict_ids = set(value.solve_result.conflicting_constraint_ids)
                conflicting_entities = {
                    reference.entity_id
                    for item in (*sketch.constraints, constraint)
                    if item.constraint_id in conflict_ids
                    for reference in item.references
                }
                preview_sketches = tuple(
                    replace(
                        item,
                        curves=tuple(
                            replace(curve, layer=replace(curve.layer, color_rgb=(200, 45, 45)))
                            if item.sketch_id == sketch.sketch_id
                            and curve.entity_id in conflicting_entities
                            else replace(
                                curve, layer=replace(curve.layer, color_rgb=(230, 126, 34))
                            )
                            if item.sketch_id == sketch.sketch_id and curve.entity_id in affected
                            else curve
                            for curve in item.curves
                        ),
                    )
                    for item in value.sketches
                )
                self.viewport.show_candidate_preview(
                    value.viewport, preserve_view=True, sketches=preview_sketches
                )

        if not unit.submit(
            build_preview,
            operation="sketch-constraint-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            fail("几何工作线程忙碌，请稍后重新预览。")

    def _on_sketch_constraint_dialog_finished(
        self, dialog: SketchConstraintDialog, _result: int
    ) -> None:
        if self._sketch_constraint_dialog is dialog:
            self._sketch_constraint_dialog = None
            self._clear_sketch_constraint_preview()

    def _on_sketch_constraint_commit(
        self,
        dialog: SketchConstraintDialog,
        session_id: int,
        sketch: Sketch,
        constraint: SketchConstraint,
        result: SketchConstraintSolveResult,
    ) -> None:
        loaded = self._loaded
        unit = self.execution_unit
        if loaded is None or unit is None or session_id != self._session_id:
            dialog.submission_failed("草图所属文档已切换")
            return
        if result.status != "success":
            dialog.submission_failed("当前预览不再有效")
            return
        if self._sketch_constraint_preview_revision != loaded.document.revision:
            self._clear_sketch_constraint_preview()
            dialog.submission_failed("模型已改变，必须重新预览后才能确认", invalidate_preview=True)
            return

        def submit_constraint() -> object:
            updating = any(
                item.constraint_id == constraint.constraint_id for item in sketch.constraints
            )
            return loaded.bus.execute(
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                result.command_params(sketch, constraint),
                confirmed_by="local",
            )

        def finish_submission(result_value: ExecutionResult) -> None:
            if result_value.error is not None:
                dialog.submission_failed(str(result_value.error))
                return
            if self.viewport is not None:
                self.viewport.refresh()
            if self._sketch_dialog is not None and self._services is not None:
                self._sync_drawing_layers()
            self.status_command.setText("草图约束已写入命令历史；可撤销、重做和保存重放。")
            dialog.accept()

        if not unit.submit(
            submit_constraint,
            operation="sketch-constraint-add",
            session_id=session_id,
            on_complete=finish_submission,
        ):
            dialog.submission_failed("应用工作线程忙碌，请稍后重试")

    def _on_sketch_editor_finished(
        self, dialog: SketchEditorDialog, session_id: int, result: int
    ) -> None:
        if dialog is not self._sketch_dialog:
            return
        mixed = dialog.canvas.mixed_move
        mixed_valid = dialog.canvas.mixed_move_is_valid
        timeline = (
            dialog.canvas.mixed_move_timeline()
            if mixed is not None and result == QDialog.DialogCode.Accepted
            else ()
        )
        after_commit = self._after_sketch_commit
        self._after_sketch_commit = None
        after_failure = self._after_sketch_failure
        self._after_sketch_failure = None
        if self._sketch_dialog is dialog:
            self._sketch_dialog = None
        if self.document_session is not None and self.document_session.active is not None:
            self.document_session.active.draft = None
        self._hide_sketch_workbench(dialog)
        sketch = dialog.result_sketch
        if result != QDialog.DialogCode.Accepted or sketch is None:
            self.status_command.setText("草图已取消；文档历史未改变。")
            return
        loaded = self._loaded
        unit = self.execution_unit
        services = self._services
        if loaded is None or unit is None or services is None or session_id != self._session_id:
            self.status_command.setText("草图所属文档已切换，草图未提交。")
            return

        def submit_sketch() -> object:
            if mixed is not None:
                if not mixed_valid:
                    raise ValueError("暂存变换已失效，请先撤销或取消。")
                if loaded.document.revision != mixed.source_revision:
                    raise ValueError("文档已变化；暂存变换尚未提交，请撤销或取消后重试。")
                if sketch.frame != mixed.original_draft.frame:
                    raise ValueError("工作平面已变化；暂存变换尚未提交，请撤销或取消后重试。")
                candidate = mycad_app.stage_mixed_drawing_timeline(
                    services,
                    loaded,
                    mixed.original_draft,
                    mixed.original_saved,
                    timeline,
                    session_identity=session_id,
                )
                preview = candidate.preview(current_session_identity=session_id)
                if preview.state != "succeeded":
                    raise ValueError(str(preview.failure or "暂存变换预览失败"))
                return candidate.commit(
                    candidate.authorize_commit(current_session_identity=session_id),
                    current_session_identity=session_id,
                )
            return mycad_app.commit_new_sketch(
                services, loaded, sketch, session_identity=session_id
            )

        def finish_submission(result_value: ExecutionResult) -> None:
            if result_value.error is not None:
                self.status_command.setText(f"草图提交失败：{result_value.error}")
                if self._loaded is loaded and self._session_id == session_id:
                    self._sketch_dialog = dialog
                    dialog.result_sketch = None
                    dialog.setResult(QDialog.DialogCode.Rejected)
                    self._show_sketch_workbench(dialog)
                    self._sync_drawing_layers()
                    dialog.status_label.setText(
                        f"草图提交失败：{result_value.error}。草稿已保留，可修正后重试或取消。"
                    )
                if after_failure is not None:
                    after_failure()
                return
            if self.viewport is not None:
                self.viewport.refresh()
            self.status_command.setText("草图已提交为一条命令；可撤销、重做和保存重放。")
            if loaded.document.document_type == "drawing2d":
                self._on_sketch_start()
                if self._sketch_dialog is not None:
                    self._sketch_dialog.continue_workspace_from(dialog)
            if after_commit is not None:
                after_commit()

        if not unit.submit(
            submit_sketch,
            operation="sketch-create",
            session_id=session_id,
            on_complete=finish_submission,
        ):
            self._sketch_dialog = dialog
            dialog.result_sketch = None
            dialog.setResult(QDialog.DialogCode.Rejected)
            self._show_sketch_workbench(dialog)
            dialog.status_label.setText("应用工作线程忙碌，草图尚未提交；请稍后重试。")
            self.status_command.setText(dialog.status_label.text())
            if after_failure is not None:
                after_failure()

    def _cancel_bound_hole(self) -> bool:
        task = self.bound_hole_task
        if task is None:
            return True
        task.reject()
        return self.bound_hole_task is None

    def _cancel_history_edit(self) -> bool:
        task = self.history_edit_task
        if task is None:
            return True
        task.reject()
        return self.history_edit_task is None

    def _cancel_history_repair(self) -> bool:
        task = self.history_repair_task
        if task is None:
            return True
        task.reject()
        return self.history_repair_task is None

    def _start_bound_hole_task(self) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("请等待当前操作完成后再创建绑定孔。")
            return
        if not self._cancel_history_edit():
            return
        if not self._cancel_history_repair():
            return
        services, loaded, viewport, unit = (
            self._services,
            self._loaded,
            self.viewport,
            self.execution_unit,
        )
        if services is None or loaded is None or viewport is None or unit is None:
            self.status_command.setText("请先创建或打开零件。")
            return
        if loaded.document.document_type != "part":
            self.status_command.setText("绑定面孔只能用于三维零件。")
            return
        if unit.is_busy or self._has_unsubmitted_geometry():
            self.status_command.setText("请先完成当前操作或草稿，再创建绑定孔。")
            return
        if self.bound_hole_task is not None:
            return
        if self.datum_task is not None:
            self.datum_task.reject()
        self._end_modeling_tool(cancel_editor=True)
        self._show_3d_workspace()
        task = BoundHoleTask(
            services,
            loaded,
            viewport,
            unit,
            session_identity=self._session_id,
            current_session=lambda: self._session_id,
            parent=self,
        )
        self.bound_hole_task = task
        task.setWindowFlags(Qt.WindowType.Widget)
        bar = QToolBar("绑定孔命令", self)
        bar.setObjectName("boundHoleCommandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        install_command_strip(bar, task, (task.confirm_button, task.cancel_button))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

        def task_finished(_result: int) -> None:
            if self.bound_hole_task is task:
                self.bound_hole_task = None
            self.removeToolBarBreak(bar)
            self.removeToolBar(bar)
            bar.setObjectName("")
            bar.deleteLater()

        task.finished.connect(task_finished)
        bar.show()
        task.show()
        task.start()

    def _start_datum_task(self, command_id: str) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("正在执行几何操作，请稍后再创建基准。")
            return
        if not self._cancel_history_edit():
            return
        if not self._cancel_history_repair():
            return
        if not self._cancel_bound_hole():
            return
        if self._services is None or self._loaded is None or self.viewport is None:
            self.status_command.setText("请先创建或打开零件。")
            return
        if self._loaded.document.document_type != "part":
            self.status_command.setText("基准只能在零件文档中创建。")
            return
        if self.datum_task is not None:
            self.datum_task.reject()
        self._end_modeling_tool(cancel_editor=True)
        self._show_3d_workspace()
        task = DatumTaskDialog(
            self._services,
            self._loaded,
            self.viewport,
            session_identity=self._session_id,
            current_session=lambda: self._session_id,
            can_execute=lambda: self.execution_unit is None or not self.execution_unit.is_busy,
            embedded=True,
            parent=self,
        )
        self.datum_task = task
        task.setWindowFlags(Qt.WindowType.Widget)
        bar = QToolBar("基准命令", self)
        bar.setObjectName("datumCommandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        install_command_strip(bar, task, (task.confirm_button, task.cancel_button))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        if command_id == "datum.plane.create":
            task.kind_combo.setCurrentIndex(1)

        def task_finished(_result: int) -> None:
            if self.datum_task is task:
                self.datum_task = None
            self.removeToolBarBreak(bar)
            self.removeToolBar(bar)
            bar.setObjectName("")
            bar.deleteLater()

        task.finished.connect(task_finished)
        bar.show()
        task.show()

    def _on_palette_command(self, command_id: str) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("请等待当前操作完成后再启动命令。")
            return
        if not self._cancel_history_edit():
            return
        if not self._cancel_history_repair():
            return
        if not self._cancel_bound_hole():
            return
        if self.part_sketch_task is not None:
            self.status_command.setText("请先完成或取消当前零件草图。")
            self.part_sketch_task.status_label.setText("请先完成或取消草图，再启动其他命令。")
            return
        if command_id in ("datum.coordinate_system.create", "datum.plane.create"):
            self._start_datum_task(command_id)
            return
        if self.datum_task is not None:
            self.datum_task.reject()
        if command_id == "drawing.layers.set":
            self._end_modeling_tool(cancel_editor=True)
            self._on_sketch_start()
            if self._sketch_dialog is not None:
                self._sketch_dialog.open_layer_manager()
            return
        if self.plan_draft is None or self.plan_cards is None:
            return
        if (
            self._loaded is not None
            and self._loaded.document.document_type == "drawing2d"
            and command_id not in DRAWING2D_COMMAND_IDS
        ):
            self.status_command.setText(f"二维图不支持命令 {command_id!r}。")
            return
        self._end_modeling_tool(cancel_editor=True)
        try:
            step = self.plan_draft.new_draft(command_id)
        except ValueError as err:
            self.status_command.setText(str(err))
            return
        self._active_modeling_command = command_id
        self._active_selection_role = None
        self._previous_selection_filter = (
            self.viewport.selection_filter() if self.viewport is not None else None
        )
        placement_kind_by_command = {
            "feature.box": "solid",
            "feature.cylinder": "solid",
            "feature.revolve": "profile",
            "modify.boolean_cut": "tool",
            "modify.boolean_intersect": "tool",
        }
        placement_kind = placement_kind_by_command.get(command_id)
        self._active_placement_kind = placement_kind
        pick_kind_by_command: dict[str, SelectionKind] = {
            "feature.extrude": "face",
            "feature.hole": "face",
            "feature.hole_pattern": "face",
            "modify.fillet": "edge",
            "modify.chamfer": "edge",
            "modify.boolean_bodies": "body",
            "modify.body_transform": "body",
            "modify.body_pattern": "body",
        }
        required_kind = pick_kind_by_command.get(command_id)
        self._active_selection_kind = required_kind
        if self.viewport is not None:
            self.viewport.set_modeling_context_active(True)
            self.viewport.set_placement_context_active(placement_kind is not None)
            self.viewport.set_face_origin_snap_enabled(command_id == "feature.hole")

        if command_id == "modify.fillet":
            self._start_fillet_interaction()
            return

        if command_id in {
            "feature.box",
            "feature.cylinder",
            "feature.sphere",
            "feature.extrude",
            "feature.revolve",
            "feature.hole",
            "feature.hole_pattern",
            "modify.boolean_cut",
            "modify.boolean_intersect",
            "modify.boolean_bodies",
            "modify.body_transform",
            "modify.body_pattern",
            "modify.chamfer",
        }:
            self._modeling_face_selector = None
            self._modeling_edge_selectors = ()
            self._modeling_body_selectors = ()
            self._modeling_body_names = ()
            self._modeling_face_frame = None
            self._modeling_params_valid = False
            self._modeling_source_revision += 1
            self._extrude_input_valid = True
            self._modeling_placement_ready = False
            self._modeling_params = {}
            self._modeling_preview_generation += 1
            self._modeling_preview_valid = False
            self._modeling_preview_pending = False
            self._modeling_commit_inflight = False
            if placement_kind is not None:
                prompt = "单击 XY 工作平面设置位置；再次单击可重定位。"
            else:
                prompt = (
                    "单击模型边选择倒角对象；再次单击可移除选中边。"
                    if required_kind == "edge"
                    else "先选目标实体，再按 Ctrl 追加刀具体。"
                    if command_id == "modify.boolean_bodies"
                    else "选择一个实体作为操作对象。"
                    if command_id in {"modify.body_transform", "modify.body_pattern"}
                    else "单击模型平面选择目标；可继续旋转视图。"
                )
                if self.viewport is not None:
                    current = self.viewport.selection()
                    if current is None or current.kind != required_kind:
                        self._set_viewport_selection_filter(required_kind or "face")
                    else:
                        self._set_viewport_selection_filter(required_kind or "face", preserve=True)
            bar = self.modeling_command_bar
            if bar is None:
                self._end_modeling_tool()
                self.status_command.setText("建模命令不可用：命令栏尚未创建。")
                return
            sketches = (
                self._services.kernel.sketches
                if self._services is not None
                and command_id in {"feature.extrude", "feature.revolve", "feature.hole"}
                else ()
            )
            sketch_ids = tuple(sketch.sketch_id for sketch in sketches)
            bar.configure(command_id, prompt, sketch_ids=sketch_ids, sketches=sketches)
            bar.set_busy(False)
            bar.set_preview_valid(False)
            if (
                command_id in {"feature.box", "feature.cylinder", "feature.sphere"}
                and self._services is not None
                and self._services.kernel.body_ids
            ):
                mode = bar.findChild(QComboBox, "mode")
                if mode is not None:
                    mode.setCurrentIndex(mode.findData("add"))
            if (
                command_id in {"feature.extrude", "feature.revolve"}
                and self._preferred_part_sketch is not None
            ):
                preferred_document, preferred_id = self._preferred_part_sketch
                if preferred_document is self._loaded and preferred_id in sketch_ids:
                    region = self._preferred_part_region
                    if (
                        region is not None
                        and region[0] is self._loaded
                        and region[1] == preferred_id
                    ):
                        bar.set_selected_sketch_region(preferred_id, region[2])
                    source_name = (
                        "extrudeSource" if command_id == "feature.extrude" else "revolveSource"
                    )
                    source = bar.findChild(QComboBox, source_name)
                    picker = bar.findChild(QComboBox, "sketchProfile")
                    if source is not None and picker is not None:
                        source.setCurrentIndex(source.findData("sketch"))
                        picker.setCurrentIndex(picker.findData(preferred_id))
            bar.show()
            bar.raise_()
            if command_id == "feature.sphere":
                bar.set_selection_status("球心为世界 XYZ；添加保留已有实体，替换会删除已有实体。")
                self._on_modeling_parameters_changed(bar.values())
            if self.viewport is not None:
                self.viewport.set_placement_context_active(placement_kind is not None)
                self.viewport.setFocus(Qt.FocusReason.OtherFocusReason)
            command_label = (
                self._services.registry.get(command_id).label_zh
                if self._services is not None
                else command_id
            )
            if placement_kind is not None:
                self.status_command.setText(f"{command_label}：{prompt}")
            else:
                self.status_command.setText(f"{command_label}：{prompt}")
                if self.viewport is not None:
                    current = self.viewport.selection()
                    if current is not None and current.kind == required_kind:
                        self._fill_active_modeling_selection(current)
            return

        if placement_kind is not None:
            initial_params: Mapping[str, object] = (
                {
                    "size_x": 20.0,
                    "size_y": 20.0,
                    "size_z": 10.0,
                    "center": [0.0, 0.0, 0.0],
                }
                if placement_kind == "box"
                else {
                    "profile": {"type": "circle", "radius": 5.0, "center": [0.0, 0.0]},
                    "distance": 10.0,
                    "mode": "new",
                }
            )
            label = "长方体" if placement_kind == "box" else "拉伸截面"
            prompt = f"{label}：请在视口中单击 XY 工作平面设置放置点；右键打开参数面板。"
            dialog = self.plan_cards.open_parameter_editor(
                step,
                execute_on_apply=True,
                discard_on_cancel=True,
                wait_for_selection=True,
                selection_prompt=prompt,
                overlay_host=self.viewport,
                initial_params=initial_params,
            )
            self._connect_modeling_editor(command_id, dialog)
            self.status_command.setText(prompt)
            return

        if required_kind is None:
            dialog = self.plan_cards.open_parameter_editor(
                step,
                execute_on_apply=True,
                discard_on_cancel=True,
                overlay_host=self.viewport,
            )
            self._connect_modeling_editor(command_id, dialog)
            label = (
                self._services.registry.get(command_id).label_zh
                if self._services is not None
                else command_id
            )
            self.status_command.setText(f"{label}：设置参数，预览后点击“应用并执行”")
            return

        pick_labels: dict[SelectionKind, str] = {"face": "面", "edge": "边"}
        pick_label = pick_labels[required_kind]
        if self.viewport is not None:
            current = self.viewport.selection()
            if current is None or current.kind != required_kind:
                self._set_viewport_selection_filter(required_kind)
            else:
                self._set_viewport_selection_filter(required_kind, preserve=True)
        command_label = (
            self._services.registry.get(step.id).label_zh if self._services is not None else step.id
        )
        prompt = (
            f"{command_label}：请在模型上选择一个{pick_label}；选中后出现参数面板，右键可唤回。"
        )
        dialog = self.plan_cards.open_parameter_editor(
            step,
            execute_on_apply=True,
            discard_on_cancel=True,
            wait_for_selection=True,
            selection_prompt=prompt,
            overlay_host=self.viewport,
        )
        self._connect_modeling_editor(command_id, dialog)
        self.status_command.setText(prompt)
        if self.viewport is not None:
            current = self.viewport.selection()
            if current is not None and current.kind == required_kind:
                self._fill_active_modeling_selection(current)

    def _start_fillet_interaction(self) -> None:
        """Start the compact, continuous source-edge fillet workflow."""
        viewport = self.viewport
        bar = self.fillet_command_bar
        loaded = self._loaded
        if viewport is None or bar is None or loaded is None or self.plan_draft is None:
            self._end_modeling_tool()
            self.status_command.setText("圆角不可用：视口、文档或命令计划尚未就绪。")
            return
        self._fillet_edge_selectors = ()
        self._fillet_preview_generation += 1
        self._fillet_preview_valid = False
        self._fillet_preview_pending = False
        self._fillet_commit_inflight = False
        self._fillet_radius_value = self._fillet_last_successful_radius
        bar.set_radius(self._fillet_radius_value)
        bar.set_selection_count(0)
        bar.set_preview_valid(False)
        bar.set_busy(False)
        bar.show()
        bar.raise_()
        viewport.set_fillet_interaction_active(True)
        viewport.set_fillet_radius_input_valid(True)
        current = viewport.selection()
        if current is None or current.kind != "edge":
            self._set_viewport_selection_filter("edge")
            current = None
        else:
            self._set_viewport_selection_filter("edge", preserve=True)
        self.status_command.setText(
            "圆角：单击边加入，重复单击移除；中键旋转，Enter 或短右键完成。"
        )
        if current is not None:
            self._on_fillet_selection_changed(current)

    def _on_fillet_selection_changed(self, selection: SelectionState | None) -> None:
        """Map current edge identities to replayable selectors and refresh preview."""
        if self._fillet_commit_inflight or self._active_modeling_command != "modify.fillet":
            return
        bar = self.fillet_command_bar
        viewport = self.viewport
        services = self._services
        if bar is None or viewport is None or services is None:
            return
        if selection is None or selection.kind != "edge":
            self._fillet_edge_selectors = ()
        else:
            try:
                self._fillet_edge_selectors = mycad_app.interactive_selectors(
                    services,
                    "edge",
                    selection.topology_ids,
                )
            except (MycadError, ValueError) as err:
                self._fillet_edge_selectors = ()
                self.status_command.setText(f"选边无法用于圆角：{str(err)[:160]}")
                bar.setToolTip(str(err))
        bar.set_selection_count(len(self._fillet_edge_selectors))
        viewport.extrude_manipulator.clear()
        frame = viewport.selected_edge_frame()
        if (
            frame is not None
            and self._fillet_radius_value is not None
            and self._fillet_edge_selectors
        ):
            viewport.configure_dimension_handle(
                DimensionHandle("fillet_radius", "圆角半径", frame), self._fillet_radius_value
            )
        self._invalidate_fillet_preview()
        if not self._fillet_edge_selectors:
            self.status_command.setText("圆角：选择一条或多条边。")
            return
        self.status_command.setText(
            f"圆角：已选 {len(self._fillet_edge_selectors)} 条边，正在更新预览…"
        )
        self._fillet_preview_timer.start()

    def _on_fillet_radius_changed(self, text: str) -> None:
        """Accept live numeric edits and debounce the isolated geometry preview."""
        try:
            radius = float(text)
        except ValueError:
            radius = 0.0
        if not isfinite(radius) or radius <= 0.0:
            self._fillet_radius_value = None
            if self.viewport is not None:
                self.viewport.set_fillet_radius_input_valid(False)
            self._invalidate_fillet_preview()
            self.status_command.setText("请输入大于 0 的圆角半径（mm）。")
            return
        self._fillet_radius_value = radius
        if self.viewport is not None:
            self.viewport.set_fillet_radius_input_valid(True)
            self.viewport.extrude_manipulator.set_distance(radius)
        self._invalidate_fillet_preview(keep_candidate=True)
        if self._fillet_edge_selectors:
            self.status_command.setText("圆角：正在更新预览…")
            if not self._fillet_preview_timer.isActive():
                self._fillet_preview_timer.start(120)

    def _accept_fillet_radius(self) -> None:
        """Accept a valid edit and return keyboard focus to the viewport."""
        bar = self.fillet_command_bar
        if bar is None:
            return
        text = bar.radius_text()
        try:
            radius = float(text)
        except ValueError:
            radius = 0.0
        if not isfinite(radius) or radius <= 0.0:
            self.status_command.setText("请输入大于 0 的圆角半径（mm）。")
            return
        bar.set_radius(radius)
        self._on_fillet_radius_changed(bar.radius_text())
        if self.viewport is not None:
            self.viewport.setFocus(Qt.FocusReason.OtherFocusReason)

    def _begin_fillet_radius_edit(self, initial_text: str) -> None:
        """Let viewport typing edit the same non-obstructing command-bar field."""
        if self._active_modeling_command != "modify.fillet" or self.fillet_command_bar is None:
            return
        self.fillet_command_bar.begin_edit(initial_text or None)
        self.fillet_command_bar.radius_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _clear_fillet_selection(self) -> None:
        if self.viewport is not None and self._active_modeling_command == "modify.fillet":
            self.viewport.clear_selection()

    def _select_source_model(self) -> None:
        """Return to the source scene before selecting more source topology."""
        if self._active_modeling_command == "modify.fillet":
            self._invalidate_fillet_preview()
        else:
            self._invalidate_modeling_preview()
        self.status_command.setText("已返回源模型；选择对象后重新生成预览。")

    def _invalidate_fillet_preview(self, *, keep_candidate: bool = False) -> None:
        """Remove any result tied to old inputs and block confirmation immediately."""
        self._fillet_preview_generation += 1
        self._fillet_preview_valid = False
        self._fillet_preview_document_revision = None
        if not keep_candidate:
            self._fillet_preview_timer.stop()
        if self.fillet_command_bar is not None:
            self.fillet_command_bar.set_preview_valid(False)
        if self.viewport is not None and not keep_candidate:
            self.viewport.clear_candidate_preview()

    def _request_fillet_preview(self) -> None:
        """Submit only the latest edge/radius pair to the isolated preview builder."""
        if self._active_modeling_command != "modify.fillet":
            return
        if not self._fillet_edge_selectors or self._fillet_radius_value is None:
            return
        services = self._services
        loaded = self._loaded
        unit = self.execution_unit
        draft = self.plan_draft
        if services is None or loaded is None or unit is None or draft is None:
            self.status_command.setText("圆角预览不可用：几何执行服务尚未就绪。")
            return
        if unit.is_busy:
            self._fillet_preview_pending = True
            self.status_command.setText("圆角：正在等待几何工作线程空闲，当前不能确认。")
            return
        self._fillet_preview_pending = False
        step = draft.plan().steps[0]
        params: dict[str, object] = {
            "edges": list(self._fillet_edge_selectors),
            "radius": self._fillet_radius_value,
        }
        try:
            validated = draft.set_params(step, params)
        except (MycadError, ValueError) as err:
            self.status_command.setText(f"圆角参数无效：{str(err)[:160]}")
            return
        commands = tuple(loaded.document.commands)
        document_revision = loaded.document.revision
        session_id = self._session_id
        generation = self._fillet_preview_generation
        self.status_command.setText("圆角：正在生成预览…")
        source_archive_version = loaded.document.archive_version

        def build_preview() -> ViewportData:
            return mycad_app.preview_command(
                services,
                commands,
                "modify.fillet",
                validated,
                source_archive_version=source_archive_version,
            )

        def finish_preview(result: ExecutionResult) -> None:
            if (
                session_id != self._session_id
                or loaded is not self._loaded
                or self._active_modeling_command != "modify.fillet"
            ):
                return
            if loaded.document.revision != document_revision:
                self.status_command.setText("圆角预览已过期：模型已改变，请重新选择。")
                return
            value = result.value
            if generation != self._fillet_preview_generation:
                return
            if result.error is not None or not isinstance(value, ViewportData):
                if self.viewport is not None:
                    self.viewport.clear_candidate_preview()
                detail = result.error or "几何服务返回了无效预览。"
                self.status_command.setText("当前半径无法生成圆角，请减小半径或调整选边。")
                self.status_command.setToolTip(detail)
                return
            if self.viewport is not None:
                self.viewport.show_candidate_preview(value, preserve_view=True)
            self._fillet_preview_document_revision = document_revision
            self._fillet_preview_valid = True
            if self.fillet_command_bar is not None:
                self.fillet_command_bar.set_preview_valid(True)
            self.status_command.setToolTip("")
            self.status_command.setText(
                f"圆角预览已更新：{len(self._fillet_edge_selectors)} 条边，R {self._fillet_radius_value:g} mm；按 Enter 或短右键完成。"
            )

        if not unit.submit(
            build_preview,
            operation="fillet-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            self._fillet_preview_pending = True
            self.status_command.setText("圆角：几何工作线程忙碌，完成后将更新最新预览。")

    def _commit_fillet_group(self) -> None:
        """Explicitly confirm exactly the current, still-valid one-step draft."""
        if (
            self._active_modeling_command != "modify.fillet"
            or self._fillet_commit_inflight
            or not self._fillet_preview_valid
        ):
            if self._active_modeling_command == "modify.fillet":
                self.status_command.setText("圆角预览尚未就绪或已过期，完成操作未提交。")
            return
        if (
            self._loaded is None
            or self._fillet_preview_document_revision != self._loaded.document.revision
        ):
            self._invalidate_fillet_preview()
            self.status_command.setText("预览已过期：文档已改变，请重新选择或修改参数后预览。")
            return
        if self.execution_unit is None or self.execution_unit.is_busy or self.plan_cards is None:
            self.status_command.setText("圆角预览更新中，完成后再确认。")
            return
        self._fillet_commit_inflight = True
        self._fillet_preview_valid = False
        self._fillet_preview_timer.stop()
        if self.viewport is not None:
            self.viewport.set_modeling_interaction_locked(True)
        if self.fillet_command_bar is not None:
            self.fillet_command_bar.set_preview_valid(False)
            self.fillet_command_bar.set_busy(True)
        self.status_command.setText("圆角：正在提交此组…")
        self.plan_cards.execute_plan()

    def _on_fillet_plan_done(self, command_count: int) -> None:
        if self._active_modeling_command != "modify.fillet":
            if not self._modeling_commit_inflight:
                return
            command_id = self._active_modeling_command
            self._modeling_commit_inflight = False
            if self.viewport is not None:
                self.viewport.set_modeling_interaction_locked(False)
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_busy(False)
            body_summary = self._body_operation_summary(self._modeling_params)
            body_count = len(self._services.kernel.body_ids) if self._services is not None else 0
            self._end_modeling_tool()
            self.status_command.setText(
                f"已完成建模操作：{body_summary}；当前模型共 {body_count} 个实体。"
                if body_summary
                else f"已完成建模操作：{command_id}（{command_count} 条命令）。"
            )
            return
        if not self._fillet_commit_inflight:
            return
        self._fillet_commit_inflight = False
        self._fillet_last_successful_radius = self._fillet_radius_value or 1.0
        self._fillet_edge_selectors = ()
        self._fillet_preview_pending = False
        if self.fillet_command_bar is not None:
            self.fillet_command_bar.set_busy(False)
            self.fillet_command_bar.set_radius(self._fillet_last_successful_radius)
            self.fillet_command_bar.set_selection_count(0)
            self.fillet_command_bar.set_preview_valid(False)
        if self.viewport is not None:
            self.viewport.set_modeling_interaction_locked(False)
            self.viewport.clear_candidate_preview()
            self.viewport.clear_selection()
            self.viewport.setFocus(Qt.FocusReason.OtherFocusReason)
            QTimer.singleShot(0, self.viewport.refresh)
        if self.plan_draft is not None:
            self.plan_draft.new_draft("modify.fillet")
        self.status_command.setText(
            f"已完成本组圆角（{command_count} 条命令）；可继续选边，Esc 退出。"
        )

    def _on_fillet_plan_failed(self, message: str) -> None:
        if self._active_modeling_command != "modify.fillet":
            if not self._modeling_commit_inflight:
                return
            self._modeling_commit_inflight = False
            if self.viewport is not None:
                self.viewport.set_modeling_interaction_locked(False)
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_busy(False)
            self.status_command.setText(f"应用失败，参数与选择已保留：{message[:140]}")
            self.status_command.setToolTip(message)
            if self.plan_draft is not None and self._active_modeling_command is not None:
                command_id = self._active_modeling_command
                try:
                    step = self.plan_draft.new_draft(command_id)
                    self._modeling_params = self.plan_draft.set_params(
                        step, dict(self._modeling_params)
                    )
                    self._modeling_preview_valid = False
                    self._modeling_preview_timer.start(0)
                except (MycadError, ValueError) as err:
                    self.status_command.setText(f"应用失败；无法恢复当前草稿：{str(err)[:140]}")
            return
        if not self._fillet_commit_inflight:
            return
        self._fillet_commit_inflight = False
        if self.viewport is not None:
            self.viewport.set_modeling_interaction_locked(False)
        if self.fillet_command_bar is not None:
            self.fillet_command_bar.set_busy(False)
        self.status_command.setText(f"圆角提交失败；已保留选边和参数：{message[:140]}")
        self.status_command.setToolTip(message)
        if self.plan_draft is not None and self._fillet_edge_selectors:
            self.plan_draft.new_draft("modify.fillet")
            self._fillet_preview_valid = False
            self._fillet_preview_timer.start(0)

    def _on_fillet_execution_busy_changed(self, busy: bool) -> None:
        if not busy and self._fillet_preview_pending and not self._fillet_commit_inflight:
            self._fillet_preview_timer.start(0)

    def _focus_dimension_input(self, text: str) -> None:
        if self._active_modeling_command == "modify.fillet":
            self._begin_fillet_radius_edit(text)
        elif self.modeling_command_bar is not None:
            self.modeling_command_bar.focus_dimension(text)

    def _on_dimension_value(self, value: float) -> None:
        if self._active_modeling_command == "modify.fillet":
            if self.fillet_command_bar is not None:
                self.fillet_command_bar.set_radius(value)
            self._on_fillet_radius_changed(str(value))
        elif self.modeling_command_bar is not None:
            self.modeling_command_bar.set_dimension_value(value)

    def _sync_dimension_handle(self) -> None:
        bar, viewport = self.modeling_command_bar, self.viewport
        if viewport is None or bar is None or self._active_modeling_command is None:
            return
        if self._active_modeling_command == "modify.fillet":
            return
        if self._active_modeling_command == "modify.chamfer":
            viewport.extrude_manipulator.clear()
            return
        if self._active_modeling_command in {"feature.extrude", "feature.revolve"}:
            profile = self._modeling_params.get("profile")
            if (
                isinstance(profile, Mapping)
                and cast("Mapping[str, object]", profile).get("type") == "sketch"
            ):
                viewport.extrude_manipulator.clear()
                return
        if self._active_selection_kind == "face" and self._modeling_face_selector is None:
            return
        if self._active_placement_kind is not None and not self._modeling_placement_ready:
            return
        dimension = bar.dimension(self._modeling_face_frame)
        if dimension is not None:
            viewport.configure_dimension_handle(*dimension)

    def _accept_extrude_distance(self) -> None:
        if self.viewport is not None:
            self.viewport.extrude_manipulator.finish_gesture()
            self.viewport.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_extrude_input_validity(self, valid: bool) -> None:
        if self._active_modeling_command == "modify.fillet":
            if not valid:
                self._on_fillet_radius_changed("")
            return
        if self._active_modeling_command is None or self._modeling_commit_inflight:
            return
        self._extrude_input_valid = valid
        if not valid:
            self._invalidate_modeling_preview()
            self.status_command.setText("尺寸输入尚未完成；当前输入不可确认。")
        elif self.modeling_command_bar is not None:
            self._on_modeling_parameters_changed(self.modeling_command_bar.values())

    def _body_operation_summary(self, params: Mapping[str, object]) -> str:
        names = self._modeling_body_names
        if not names:
            return ""
        command_id = self._active_modeling_command
        if command_id == "modify.boolean_bodies" and len(names) == 2:
            operation = {"union": "并集", "difference": "差集", "intersection": "交集"}.get(
                str(params.get("operation")), "布尔"
            )
            tool_mode = "保留刀具体" if params.get("keep_tool") else "消耗刀具体"
            return f"{operation} · 目标：{names[0]} / 刀具：{names[1]} · {tool_mode}"
        if command_id == "modify.body_pattern":
            return f"阵列种子：{names[0]} · 保留种子，数量含种子"
        if command_id == "modify.body_transform":
            transform = params.get("transform")
            operation = (
                cast("Mapping[str, object]", transform).get("operation")
                if isinstance(transform, Mapping)
                else None
            )
            action = {"move": "移动", "rotate": "旋转", "mirror": "镜像", "copy": "复制"}.get(
                str(operation), "变换"
            )
            return f"{action}来源：{names[0]} · {'保留源体' if operation == 'copy' else '更新源体'}"
        return ""

    def _on_modeling_parameters_changed(self, value: object) -> None:
        """Validate the command-bar values and schedule the latest scratch preview."""
        command_id = self._active_modeling_command
        bar = self.modeling_command_bar
        draft = self.plan_draft
        if (
            command_id is None
            or command_id == "modify.fillet"
            or self._modeling_commit_inflight
            or bar is None
            or draft is None
            or not isinstance(value, Mapping)
        ):
            return
        self._modeling_params_valid = False
        self._invalidate_modeling_preview(keep_candidate=True)
        params = dict(cast("Mapping[str, object]", value))
        to_face_mode = False
        if command_id in {"feature.extrude", "feature.revolve"}:
            profile_value = params.get("profile")
            profile_type = (
                cast("Mapping[str, object]", profile_value).get("type")
                if isinstance(profile_value, Mapping)
                else None
            )
            face_mode = command_id == "feature.extrude" and profile_type == "face"
            sketch_mode = profile_type == "sketch"
            to_face_mode = (
                command_id == "feature.extrude"
                and sketch_mode
                and params.get("extent_mode") == "to_face"
            )
            new_selection_kind: SelectionKind | None = "face" if face_mode or to_face_mode else None
            new_selection_role = (
                "face_extrusion" if face_mode else "sketch_to_face" if to_face_mode else None
            )
            new_placement_kind = None if face_mode or sketch_mode else "profile"
            selection_kind_changed = self._active_selection_kind != new_selection_kind
            placement_kind_changed = self._active_placement_kind != new_placement_kind
            switching = (
                selection_kind_changed
                or self._active_selection_role != new_selection_role
                or placement_kind_changed
            )
            initializing_selection_role = (
                switching
                and self._active_selection_role is None
                and not selection_kind_changed
                and not placement_kind_changed
            )
            self._active_selection_kind = new_selection_kind
            self._active_selection_role = new_selection_role
            self._active_placement_kind = new_placement_kind
            if self.viewport is not None:
                self.viewport.set_placement_context_active(new_placement_kind is not None)
            if switching:
                self._modeling_source_revision += 1
                if self.viewport is not None:
                    self.viewport.extrude_manipulator.clear()
                    self.viewport.clear_candidate_preview()
                if not initializing_selection_role:
                    self._modeling_placement_ready = False
                    self._modeling_face_selector = None
                    self._modeling_face_frame = None
                if face_mode or to_face_mode:
                    self._set_viewport_selection_filter(
                        "face", preserve=initializing_selection_role
                    )
                elif sketch_mode and self.viewport is not None:
                    self.viewport.set_selection_filter("body")
                prompt = (
                    "单击选择到面终止平面"
                    if to_face_mode
                    else "单击选择目标平面"
                    if face_mode
                    else "选择已提交草图"
                    if sketch_mode
                    else "单击 XY 工作平面放置截面"
                )
                bar.set_selection_status(prompt)
            if sketch_mode:
                profile = cast("Mapping[str, object]", profile_value)
                sketch_id = profile.get("sketch_id")
                available_sketch_ids: set[str] = (
                    {sketch.sketch_id for sketch in self._services.kernel.sketches}
                    if self._services is not None
                    else set()
                )
                if not isinstance(sketch_id, str) or sketch_id not in available_sketch_ids:
                    self.status_command.setText("请选择一张已提交的闭合草图。")
                    return
        if command_id == "modify.chamfer":
            if not self._modeling_edge_selectors:
                self.status_command.setText("请先在模型上选择一条或多条边。")
                bar.set_selection_status("请选择模型边")
                return
            params["edges"] = list(self._modeling_edge_selectors)
        if command_id in {
            "modify.boolean_bodies",
            "modify.body_transform",
            "modify.body_pattern",
        }:
            if self._active_selection_kind != "body":
                self.status_command.setText("当前操作需要实体选择上下文。")
                return
            required_bodies = 2 if command_id == "modify.boolean_bodies" else 1
            if len(self._modeling_body_selectors) != required_bodies:
                self.status_command.setText(
                    f"此操作需要选择 {required_bodies} 个不同实体；当前已选 {len(self._modeling_body_selectors)} 个。"
                )
                bar.set_selection_status(
                    "先选目标体，再按 Ctrl 选择刀具体"
                    if command_id == "modify.boolean_bodies"
                    else "请选择一个实体"
                )
                return
            if command_id == "modify.boolean_bodies":
                params["target_body"] = self._modeling_body_selectors[0]
                params["tool_body"] = self._modeling_body_selectors[1]
            elif command_id == "modify.body_transform":
                params["body"] = self._modeling_body_selectors[0]
            else:
                params["seed_body"] = self._modeling_body_selectors[0]
            bar.set_selection_status(self._body_operation_summary(params))
        if command_id == "feature.hole":
            profile_value = params.get("profile")
            if self.viewport is not None:
                self.viewport.set_face_origin_snap_enabled(
                    not isinstance(profile_value, Mapping)
                    or cast("Mapping[str, object]", profile_value).get("type") != "sketch"
                )
            if isinstance(profile_value, Mapping):
                hole_profile = cast("Mapping[str, object]", profile_value)
                if hole_profile.get("type") == "sketch":
                    sketch_id = hole_profile.get("sketch_id")
                    hole_sketch_ids: set[str] = (
                        {sketch.sketch_id for sketch in self._services.kernel.sketches}
                        if self._services is not None
                        else set()
                    )
                    if not isinstance(sketch_id, str) or sketch_id not in hole_sketch_ids:
                        self.status_command.setText("请选择包含圆孔的已提交草图。")
                        return
        if self._active_placement_kind is not None:
            if not self._modeling_placement_ready:
                self.status_command.setText("请先在 XY 工作平面单击放置点。")
                return
        elif self._active_selection_kind == "face":
            selector = self._modeling_face_selector
            if selector is None:
                self.status_command.setText(
                    "请先选择到面终止平面。"
                    if self._active_selection_role == "sketch_to_face"
                    else "请先在模型上选择一个平面。"
                )
                return
            if command_id == "feature.extrude":
                if self._active_selection_role == "sketch_to_face":
                    params["target_face"] = selector
                else:
                    params["profile"] = {"type": "face", "target_face": selector}
            elif command_id == "feature.hole":
                params["target_face"] = selector
                profile_value = params.get("profile")
                sketch_hole = (
                    isinstance(profile_value, Mapping)
                    and cast("Mapping[str, object]", profile_value).get("type") == "sketch"
                )
                if not sketch_hole and self._modeling_face_frame is not None:
                    params["position"] = {
                        "kind": "point",
                        "point": list(self._modeling_face_frame.origin),
                    }
            elif command_id == "feature.hole_pattern":
                base_hole = params.get("base_hole")
                if not isinstance(base_hole, dict):
                    self.status_command.setText("孔阵列参数结构无效。")
                    return
                base_hole["target_face"] = selector
                use_face_center = bar.hole_pattern_uses_face_center()
                bar.set_selection_status(
                    "已选平面 · 面形心定位" if use_face_center else "已选平面 · 点击处定位"
                )
                if not use_face_center and self._modeling_face_frame is not None:
                    base_hole["position"] = {
                        "kind": "point",
                        "point": list(self._modeling_face_frame.origin),
                    }
        try:
            step = draft.plan().steps[0]
            self._modeling_params = draft.set_params(step, params)
        except (MycadError, ValueError, IndexError) as err:
            self._invalidate_modeling_preview()
            self.status_command.setText(f"参数无效：{str(err)[:180]}")
            return
        self._sync_dimension_handle()
        if (
            not self._extrude_input_valid
            or not bar.input_valid()
            or (
                command_id == "feature.extrude" and not to_face_mode and bar.extrude_distance() == 0
            )
        ):
            self._invalidate_modeling_preview()
            self.status_command.setText("请输入有效尺寸；当前输入不能确认。")
            return
        self._modeling_params_valid = True
        self.status_command.setText("参数已更新，正在准备模型预览…")
        if not self._modeling_preview_timer.isActive():
            self._modeling_preview_timer.start(120)

    def _invalidate_modeling_preview(self, *, keep_candidate: bool = False) -> None:
        """Expire any candidate tied to a previous selection or parameter value."""
        self._modeling_preview_generation += 1
        self._modeling_preview_valid = False
        self._modeling_preview_document_revision = None
        if not keep_candidate:
            self._modeling_preview_timer.stop()
        if self.modeling_command_bar is not None:
            self.modeling_command_bar.set_preview_valid(False)
        if self.viewport is not None and not keep_candidate:
            self.viewport.clear_candidate_preview()

    def _request_modeling_preview(self) -> None:
        """Build an isolated candidate from the current command-bar draft."""
        command_id = self._active_modeling_command
        if command_id is None or command_id == "modify.fillet" or not self._modeling_params_valid:
            return
        if self.viewport is not None and (
            not self._extrude_input_valid
            or not self.viewport.extrude_manipulator.input_valid
            or (
                self.modeling_command_bar is not None
                and not self.modeling_command_bar.input_valid()
            )
            or (
                self._modeling_params.get("distance") == 0
                and self._modeling_params.get("extent_mode") != "to_face"
            )
        ):
            return
        if self._active_placement_kind is not None and not self._modeling_placement_ready:
            return
        if self._active_selection_kind == "face" and self._modeling_face_selector is None:
            return
        if self._active_selection_kind == "edge" and not self._modeling_edge_selectors:
            return
        if self._active_selection_kind == "body" and not self._modeling_body_selectors:
            return
        services = self._services
        loaded = self._loaded
        unit = self.execution_unit
        draft = self.plan_draft
        if services is None or loaded is None or unit is None or draft is None:
            self.status_command.setText("预览不可用：几何执行服务尚未就绪。")
            return
        if unit.is_busy:
            self._modeling_preview_pending = True
            self.status_command.setText("正在等待几何工作线程空闲，当前不能确认。")
            return
        self._modeling_preview_pending = False
        generation = self._modeling_preview_generation
        session_id = self._session_id
        commands = tuple(loaded.document.commands)
        document_revision = loaded.document.revision
        params = dict(self._modeling_params)
        self.status_command.setText("正在生成模型预览…")
        source_archive_version = loaded.document.archive_version

        def build_preview() -> ViewportData:
            return mycad_app.preview_command(
                services,
                commands,
                command_id,
                params,
                source_archive_version=source_archive_version,
            )

        def finish_preview(result: ExecutionResult) -> None:
            if (
                session_id != self._session_id
                or loaded is not self._loaded
                or self._active_modeling_command != command_id
            ):
                return
            if loaded.document.revision != document_revision:
                self.status_command.setText("预览已过期：模型已改变，请重新选择。")
                return
            value = result.value
            if generation != self._modeling_preview_generation:
                return
            if self._sphere_position_dialog is not None:
                return
            if result.error is not None or not isinstance(value, ViewportData):
                if self.viewport is not None:
                    self.viewport.clear_candidate_preview()
                detail = result.error or "几何服务返回了无效预览。"
                self.status_command.setText(f"预览失败：{str(detail)[:180]}；可修改参数后重试。")
                self.status_command.setToolTip(str(detail))
                return
            if self.viewport is not None:
                self.viewport.show_candidate_preview(value, preserve_view=True)
            self._modeling_preview_document_revision = document_revision
            self._modeling_preview_valid = True
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_preview_valid(True)
            self.status_command.setToolTip("")
            body_summary = self._body_operation_summary(self._modeling_params)
            body_count = len(set(value.triangle_body_ids))
            self.status_command.setText(
                f"{body_summary}；预览当前模型共 {body_count} 个实体，确认后应用。"
                if body_summary
                else "模型预览已更新；确认后写入命令历史。"
            )

        if not unit.submit(
            build_preview,
            operation=f"{command_id}-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            self._modeling_preview_pending = True
            self.status_command.setText("几何工作线程忙碌，空闲后将更新最新预览。")

    def _commit_modeling_operation(self) -> None:
        """Commit one current non-fillet draft only after its preview succeeds."""
        command_id = self._active_modeling_command
        if command_id is None or command_id == "modify.fillet":
            return
        if self._sphere_position_dialog is not None:
            self.status_command.setText("请先完成或取消球心定位。")
            return
        if not self._extrude_input_valid or (
            self.modeling_command_bar is not None and not self.modeling_command_bar.input_valid()
        ):
            self.status_command.setText("尺寸输入尚未完成，不能提交。")
            return
        if self._modeling_commit_inflight or not self._modeling_preview_valid:
            self.status_command.setText("当前预览尚未就绪或已过期，操作未提交。")
            return
        if (
            self._loaded is None
            or self._modeling_preview_document_revision != self._loaded.document.revision
        ):
            self._invalidate_modeling_preview()
            self.status_command.setText("预览已过期：文档已改变，请重新选择或修改参数后预览。")
            return
        if self.execution_unit is None or self.execution_unit.is_busy or self.plan_cards is None:
            self.status_command.setText("预览更新中，请稍后确认。")
            return
        self._modeling_commit_inflight = True
        self._modeling_preview_valid = False
        self._modeling_preview_timer.stop()
        if self.viewport is not None:
            self.viewport.set_modeling_interaction_locked(True)
        if self.modeling_command_bar is not None:
            self.modeling_command_bar.set_preview_valid(False)
            self.modeling_command_bar.set_busy(True)
        self.status_command.setText("正在应用当前建模操作…")
        self.plan_cards.execute_plan()

    def _on_modeling_execution_busy_changed(self, busy: bool) -> None:
        if not busy and self._modeling_preview_pending and not self._modeling_commit_inflight:
            self._modeling_preview_timer.start(0)

    def _connect_modeling_editor(self, command_id: str, dialog: QDialog) -> None:
        def on_finished(result: int) -> None:
            self._on_modeling_editor_finished(command_id, result)

        dialog.finished.connect(on_finished)

    def _open_sphere_positioning(self) -> None:
        viewport, services, loaded, bar = (
            self.viewport,
            self._services,
            self._loaded,
            self.modeling_command_bar,
        )
        if (
            self._active_modeling_command != "feature.sphere"
            or viewport is None
            or services is None
            or loaded is None
            or bar is None
            or not self._modeling_preview_valid
        ):
            return
        generation, session, revision = (
            self._modeling_preview_generation,
            self._session_id,
            loaded.document.revision,
        )
        planes: list[tuple[str, WorkPlaneFrame, SpatialReference | None]] = [
            (f"世界 {name.upper()}", RigidFrame.identity().principal_plane(name), None)
            for name in ("xy", "xz", "yz")
        ]
        hidden = viewport.hidden_datum_references()
        for datum in services.kernel.datum_display_data():
            if isinstance(datum.frame, WorkPlaneFrame) and datum.reference not in hidden:
                planes.append((datum.name, datum.frame, datum.reference))
        if self._sphere_position_dialog is not None:
            self._sphere_position_dialog.reject()
        viewport.clear_candidate_preview()
        dialog = WorkplanePositionDialog(
            planes,
            viewport,
            bar.set_placement_point,
            lambda: (
                self._active_modeling_command == "feature.sphere"
                and self._loaded is loaded
                and self._session_id == session
                and loaded.document.revision == revision
                and self._modeling_preview_generation == generation
                and self._modeling_preview_valid
            ),
            self,
        )
        self._sphere_position_dialog = dialog
        bar.set_preview_valid(False)

        def finished(_result: int) -> None:
            if self._sphere_position_dialog is dialog:
                self._sphere_position_dialog = None
            if (
                self._active_modeling_command == "feature.sphere"
                and self._loaded is loaded
                and self._session_id == session
                and loaded.document.revision == revision
            ):
                self._on_modeling_parameters_changed(bar.values())

        dialog.finished.connect(finished)
        dialog.show()

    def _on_workplane_point_picked(self, value: object, _position: QPoint) -> None:
        if (
            self._active_placement_kind is None
            or self.modeling_command_bar is None
            or not isinstance(value, tuple)
        ):
            return
        x, y, z = cast("tuple[float, float, float]", value)
        self._modeling_source_revision += 1
        self._modeling_placement_ready = True
        self.modeling_command_bar.set_placement_point((x, y, z))
        self._sync_dimension_handle()
        command_id = self._active_modeling_command or "建模命令"
        label = (
            self._services.registry.get(command_id).label_zh
            if self._services is not None and command_id != "建模命令"
            else command_id
        )
        self.modeling_command_bar.set_selection_status(f"位置 X{x:.2f} Y{y:.2f}")
        self.status_command.setText(f"{label}放置点：X {x:.2f} mm，Y {y:.2f} mm；正在更新预览。")

    def _on_workplane_point_rejected(self) -> None:
        self.status_command.setText("当前视角无法与 XY 工作平面相交；请调整视角后再单击。")

    def _set_viewport_selection_filter(
        self, kind: SelectionKind, *, preserve: bool = False
    ) -> None:
        viewport = self.viewport
        if viewport is None:
            return
        current = viewport.selection()
        if not preserve and current is not None:
            viewport.clear_selection()
        viewport.set_selection_filter(kind)
        action = self.selection_filter_actions.get(kind)
        if action is not None:
            action.setChecked(True)

    def _fill_active_modeling_selection(self, selection: SelectionState) -> None:
        command_id = self._active_modeling_command
        expected_kind = self._active_selection_kind
        services = self._services
        if command_id is None or expected_kind is None or services is None:
            return
        if command_id == "modify.chamfer":
            self._modeling_source_revision += 1
            self._modeling_params_valid = False
            self._modeling_edge_selectors = ()
            self._invalidate_modeling_preview()
            if selection.kind != "edge" or not selection.topology_ids:
                self.status_command.setText("倒角需要选择一条或多条模型边。")
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status("请选择模型边")
                return
            try:
                self._modeling_edge_selectors = tuple(
                    mycad_app.interactive_selectors(
                        services,
                        "edge",
                        selection.topology_ids,
                    )
                )
            except (MycadError, ValueError) as err:
                self.status_command.setText(f"选边无法用于倒角：{str(err)[:180]}")
                return
            if not self._modeling_edge_selectors:
                self.status_command.setText("倒角需要选择一条或多条模型边。")
                return
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_selection_status(
                    f"已选 {len(self._modeling_edge_selectors)} 条边 · 等距倒角"
                )
                self._on_modeling_parameters_changed(self.modeling_command_bar.values())
            return
        if command_id in {
            "modify.boolean_bodies",
            "modify.body_transform",
            "modify.body_pattern",
        }:
            self._modeling_source_revision += 1
            self._modeling_params_valid = False
            self._modeling_body_selectors = ()
            self._modeling_body_names = ()
            self._invalidate_modeling_preview()
            if selection.kind != "body":
                self.status_command.setText("当前操作需要选择模型实体。")
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status("请选择模型实体")
                return
            required_count = 2 if command_id == "modify.boolean_bodies" else 1
            if len(selection.body_ids) != required_count:
                self.status_command.setText(
                    f"当前操作需要恰好选择 {required_count} 个实体；请调整选择后继续。"
                )
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status(
                        "先选择目标体，再按 Ctrl 追加刀具体"
                        if command_id == "modify.boolean_bodies"
                        else "请选择一个实体"
                    )
                return
            if selection.geometry_revision != services.kernel.geometry_revision:
                self.status_command.setText("实体选择已过期；模型发生变化，请重新选择。")
                return
            try:
                self._modeling_body_selectors = mycad_app.interactive_body_selectors(
                    services,
                    selection.body_ids,
                )
                if self.right_panel is not None:
                    self._modeling_body_names = tuple(
                        self.right_panel.body_name(identity) for identity in selection.body_ids
                    )
            except (MycadError, ValueError) as err:
                self.status_command.setText(f"实体选择无法用于当前操作：{str(err)[:180]}")
                return
            if self.modeling_command_bar is not None:
                selection_labels = {
                    "modify.boolean_bodies": "已选目标体和刀具体",
                    "modify.body_transform": "已选变换实体",
                    "modify.body_pattern": "已选阵列种子",
                }
                self.modeling_command_bar.set_selection_status(selection_labels[command_id])
                self._on_modeling_parameters_changed(self.modeling_command_bar.values())
            return
        if command_id not in {"feature.extrude", "feature.hole", "feature.hole_pattern"}:
            return
        self._modeling_source_revision += 1
        self._modeling_params_valid = False
        self._modeling_face_selector = None
        self._invalidate_modeling_preview()
        self._modeling_face_frame = None
        if self.viewport is not None:
            self.viewport.extrude_manipulator.clear()
        if selection.kind != expected_kind:
            self.status_command.setText("此操作需要选择模型平面，请切换到面选择。")
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_selection_status("请选择一个平面")
            return
        if len(selection.topology_ids) != 1:
            self.status_command.setText("此操作需要一个目标面；请只选择单个面。")
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_selection_status("请只选择一个面")
            return
        try:
            selectors = mycad_app.interactive_selectors(
                services,
                selection.kind,
                selection.topology_ids,
            )
        except (MycadError, ValueError) as err:
            self.status_command.setText(f"选择无法用于命令：{str(err)[:180]}")
            return
        if selectors[0].get("surface") != "plane":
            self.status_command.setText("请选择平面；当前操作不支持曲面。")
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_selection_status("曲面不适用，请重选平面")
            return
        self._modeling_face_selector = selectors[0]
        self._extrude_input_valid = True
        if self.viewport is not None:
            try:
                frame = mycad_app.interactive_face_frame(services, selection.topology_ids[0])
            except (MycadError, ValueError) as err:
                self._modeling_face_selector = None
                self.status_command.setText(f"无法确定平面方向：{err}")
                return
            hole_profile = (
                self.modeling_command_bar.values().get("profile")
                if command_id == "feature.hole" and self.modeling_command_bar is not None
                else None
            )
            self._modeling_face_frame = self.viewport.picked_face_frame(
                frame,
                snap_world_origin=command_id == "feature.hole"
                and (
                    not isinstance(hole_profile, Mapping)
                    or cast("Mapping[str, object]", hole_profile).get("type") != "sketch"
                ),
            )
        if self.modeling_command_bar is not None:
            self.modeling_command_bar.set_selection_status(
                "已选终止平面 · 预览到面范围"
                if self._active_selection_role == "sketch_to_face"
                else "完整面 · 正值外拉 / 负值内推"
                if command_id == "feature.extrude"
                else "已选平面 · 孔轴对齐世界原点"
                if command_id == "feature.hole"
                and self.viewport is not None
                and self.viewport.face_origin_snapped()
                else "已选平面 · 点击处定位"
            )
            self._on_modeling_parameters_changed(self.modeling_command_bar.values())

    def _on_viewport_context_requested(self, position: QPoint) -> None:
        if self._active_modeling_command is not None and self.plan_cards is not None:
            self.plan_cards.show_parameter_editor_at(position)

    def _on_modeling_editor_finished(self, command_id: str, result: int) -> None:
        if command_id != self._active_modeling_command:
            return
        if result == QDialog.DialogCode.Accepted:
            self.status_command.setText(f"已提交：{command_id}（正在生成模型）")
            self._end_modeling_tool()
        else:
            self.status_command.setText(f"已取消：{command_id}")
            self._end_modeling_tool()

    def _cancel_active_modeling_tool(self) -> None:
        if self._active_modeling_command is None:
            return
        if self._fillet_commit_inflight or self._modeling_commit_inflight:
            self.status_command.setText("建模操作正在提交；请等待完成后再退出。")
            return
        command_id = self._active_modeling_command
        self._end_modeling_tool(cancel_editor=True)
        if self.plan_cards is not None:
            self.plan_cards.cancel_parameter_editor()
        self.status_command.setText(f"已取消：{command_id}")

    def _end_modeling_tool(self, *, cancel_editor: bool = False) -> None:
        command_id = self._active_modeling_command
        self._active_modeling_command = None
        if self._sphere_position_dialog is not None:
            self._sphere_position_dialog.reject()
        self._active_selection_kind = None
        self._active_selection_role = None
        self._active_placement_kind = None
        if command_id == "modify.fillet":
            self._fillet_preview_timer.stop()
            self._fillet_preview_generation += 1
            self._fillet_preview_valid = False
            self._fillet_preview_pending = False
            self._fillet_commit_inflight = False
            self._fillet_edge_selectors = ()
            if self.fillet_command_bar is not None:
                self.fillet_command_bar.set_busy(False)
                self.fillet_command_bar.hide()
        elif command_id is not None:
            self._modeling_preview_timer.stop()
            self._modeling_preview_generation += 1
            self._modeling_preview_valid = False
            self._modeling_preview_pending = False
            self._modeling_commit_inflight = False
            self._modeling_face_selector = None
            self._modeling_edge_selectors = ()
            self._modeling_body_selectors = ()
            self._modeling_body_names = ()
            self._modeling_placement_ready = False
            self._modeling_params = {}
            if self.modeling_command_bar is not None:
                self.modeling_command_bar.set_preview_valid(False)
                self.modeling_command_bar.set_busy(False)
                self.modeling_command_bar.hide()
        viewport = self.viewport
        if viewport is not None:
            viewport.set_modeling_context_active(False)
            viewport.set_fillet_interaction_active(False)
            viewport.set_placement_context_active(False)
            viewport.clear_candidate_preview()
            previous_filter = self._previous_selection_filter
            if previous_filter is not None:
                viewport.set_selection_filter(previous_filter)
                action = self.selection_filter_actions.get(previous_filter)
                if action is not None:
                    action.setChecked(True)
        self._previous_selection_filter = None
        if cancel_editor and self.plan_cards is not None and command_id is not None:
            self.plan_cards.cancel_parameter_editor()
        if (
            cancel_editor
            and command_id is not None
            and self.plan_draft is not None
            and self.plan_draft.plan().status == "draft"
        ):
            self.plan_draft.replace_plan(Plan(steps=[]))

    def _on_body_visibility_requested(self, identity: object, visible: bool) -> None:
        if self.viewport is not None and isinstance(identity, BodyId):
            self.viewport.set_body_visible(identity, visible)
            self._sync_body_display()

    def _on_current_snapshot_changed(self, snapshot: object) -> None:
        if self.viewport is not None and self.right_panel is not None:
            self.right_panel.set_current_snapshot(
                snapshot, state_ids=self.viewport.history_state_ids()
            )

    def _sync_body_display(self) -> None:
        if self.viewport is not None and self.right_panel is not None:
            self.right_panel.set_body_display(
                self.viewport.hidden_body_ids(),
                editable=self.viewport.body_visibility_editable(),
                hint=self.viewport.body_display_hint(),
            )
            self.right_panel.set_datum_visibility(self.viewport.hidden_datum_references())

    def _on_render_mode_selected(self, mode: RenderMode, _checked: bool = False) -> None:
        if self.viewport is not None:
            self.viewport.set_render_mode(mode)

    def _on_orientation_selected(
        self, orientation: ViewOrientation, _checked: bool = False
    ) -> None:
        if self.viewport is not None:
            self.viewport.set_orientation(orientation)

    def _on_projection_selected(self, mode: ProjectionMode, _checked: bool = False) -> None:
        if self.viewport is not None:
            self.viewport.set_projection_mode(mode)

    def _on_selection_filter_selected(self, kind: SelectionKind, _checked: bool = False) -> None:
        if self.viewport is not None:
            self.viewport.set_selection_filter(kind)

    def _on_coordinate_axes_toggled(self, visible: bool) -> None:
        if self.viewport is not None:
            self.viewport.set_coordinate_axes_visible(visible)

    def _on_fit_view(self) -> None:
        if self.active_workspace == "drawing":
            self.drawing_workbench.canvas.fit_view()
            return
        if self._sketch_dialog is not None and self.active_workspace == "sketch":
            self._sketch_dialog.canvas.fit_view()
        elif self.viewport is not None:
            self.viewport.fit_view()

    def _sync_camera_status(self) -> None:
        if self.active_workspace == "drawing":
            self.status_camera.setText("工程图 · 纸张 mm")
            return
        if self._sketch_dialog is not None and self.active_workspace == "sketch":
            self.status_camera.setText(
                f"二维 · {self._sketch_dialog.plane_combo.currentText()} · UCS"
            )
            return
        view = self.viewport
        if view is None:
            return
        orientation = view.orientation()
        label = "自由" if orientation is None else self.orientation_actions[orientation].text()
        projection = "正交" if view.projection_mode() == "orthographic" else "透视"
        self.status_camera.setText(f"{label} · {projection}")
        self.orientation_group.setExclusive(False)
        for name, action in self.orientation_actions.items():
            action.setChecked(name == orientation)
        self.orientation_group.setExclusive(True)
        self.projection_actions[view.projection_mode()].setChecked(True)

    def _on_xy_grid_toggled(self, visible: bool) -> None:
        if self.viewport is not None:
            self.viewport.set_xy_grid_visible(visible)

    def _on_selection_changed(self, selection: object) -> None:
        if selection is not None and not isinstance(selection, SelectionState):
            return
        if self.right_panel is not None:
            self.right_panel.set_view_selection(selection)
        if selection is None:
            self.status_selection.setText("选择 0")
            if self._active_modeling_command == "modify.fillet":
                self._on_fillet_selection_changed(None)
            elif self._active_selection_kind == "face":
                if self.viewport is not None:
                    self.viewport.extrude_manipulator.clear()
                self._modeling_face_selector = None
                self._invalidate_modeling_preview()
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status("单击选择目标平面")
            elif self._active_selection_kind == "edge":
                self._modeling_edge_selectors = ()
                self._invalidate_modeling_preview()
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status("单击选择模型边")
            elif self._active_selection_kind == "body":
                self._modeling_body_selectors = ()
                self._modeling_body_names = ()
                self._invalidate_modeling_preview()
                if self.modeling_command_bar is not None:
                    self.modeling_command_bar.set_selection_status("请选择模型实体")
            return
        labels: dict[SelectionKind, str] = {
            "body": "实体",
            "face": "面",
            "edge": "边",
            "vertex": "顶点",
        }
        count = len(selection.body_ids) if selection.kind == "body" else len(selection.topology_ids)
        self.status_selection.setText(f"选择 {labels[selection.kind]} {count}")
        if self._active_modeling_command == "modify.fillet":
            self._on_fillet_selection_changed(selection)
            return
        if self._active_modeling_command == "modify.chamfer":
            self._fill_active_modeling_selection(selection)
            return
        self._fill_active_modeling_selection(selection)

    def _on_drafting_message(self, dialog: SketchEditorDialog, transient: bool, text: str) -> None:
        if dialog is not self._sketch_dialog or self.active_workspace != "sketch":
            return
        if transient:
            self.status_command.set_transient_text(text)
        else:
            self.status_command.setText(text)

    def _resize_console(self, expanded: bool) -> None:
        if self.bottom_tabs is None:
            return
        height = self.bottom_tabs.expanded_height if expanded else self.bottom_tabs.height()
        if self.bottom_dock.isFloating():
            self.bottom_dock.resize(self.bottom_dock.width(), height + 24)
        else:
            self.resizeDocks([self.bottom_dock], [height + 24], Qt.Orientation.Vertical)
        # A tab press completes its own focus change after this signal. Restore
        # an in-progress dimension edit on the next event-loop turn so Enter
        # and Esc still reach the canvas, including across floating windows.
        QTimer.singleShot(0, self, self._restore_dimension_input_focus)

    def _restore_dimension_input_focus(self) -> None:
        draft = self._sketch_dialog
        if draft is None or self.active_workspace != "sketch":
            return
        dimensions = draft.dimensions
        if dimensions.candidate is None and dimensions.mode is None:
            return
        target = dimensions.value_editor if dimensions.value_editor.isVisible() else draft.canvas
        target.window().activateWindow()
        target.setFocus()

    def _show_console_page(self, page: QWidget | None) -> None:
        if self.bottom_tabs is None or page is None:
            return
        self.act_toggle_bottom_dock.setChecked(True)
        self.bottom_dock.show()
        self.bottom_tabs.show_page(page)
        self.bottom_dock.raise_()

    def _show_measure_panel(self) -> None:
        if self.right_panel is None or self._loaded is None:
            return
        self.right_dock.show()
        self.right_panel.tabs.setCurrentIndex(self.right_panel.tabs.count() - 1)
        self.right_dock.raise_()

    def _record_execution_error(self, result: object) -> None:
        if not isinstance(result, ExecutionResult) or result.error is None:
            return
        self.status_command.setText(result.error)
        if result.error_detail is not None:
            self.information_tab.append_message(result.error_detail)

    def _show_information_panel(self) -> None:
        self._show_console_page(self.information_tab)

    def _show_ai_panel(self) -> None:
        self._show_console_page(self.ai_chat)
        self.ai_chat.input.setFocus()

    def _show_plan_cards(self) -> None:
        self._show_console_page(self.plan_cards)

    def _show_cli_panel(self) -> None:
        self._show_console_page(self.cli_tab)
        if self.cli_tab is not None:
            self.cli_tab.input.setFocus()

    def _reset_layout(self) -> None:
        """Restore the named five-zone layout without changing document state."""
        self.quick_access.reset()
        if self._console_environment is not None and self.bottom_tabs is not None:
            self.workspace_layout.reset_console(self._console_environment)
            self._restoring_console = True
            try:
                self.bottom_tabs.restore_state((False, 0, 240))
            finally:
                self._restoring_console = False
        if self.document_session is not None and self.document_session.active is not None:
            self.workspace_layout.reset(
                self._active_layout_environment(self.document_session.active.kind)
            )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.main_toolbar)
        self.removeToolBarBreak(self.modeling_toolbar)
        self.removeToolBar(self.modeling_toolbar)
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.modeling_toolbar)
        self._modeling_toolbar_was_visible = False
        self.modeling_toolbar.hide()
        if self._sketch_dialog is not None and self.active_workspace == "sketch":
            self._sketch_dialog.reset_toolbar_layout()
            self._drafting_toolbar_state = None
        self._arrange_command_toolbars()
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setFloatable(True)
        self.act_lock_toolbar.setChecked(False)
        self.act_toggle_toolbar.setChecked(True)
        self.act_toggle_left_dock.setChecked(True)
        self.act_toggle_right_dock.setChecked(True)
        if self.bottom_tabs is not None:
            self.bottom_tabs.set_expanded(False)
        self.act_toggle_bottom_dock.setChecked(
            self._sketch_dialog is not None and self.active_workspace == "sketch"
        )
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry().size()
        self.resize(min(1400, available.width()), min(900, available.height()))
        self.resizeDocks(
            [self.left_dock, self.right_dock],
            [194, 278],
            Qt.Orientation.Horizontal,
        )
        self.store_window_state()

    def current_theme(self) -> ThemeName:
        """Return the theme currently applied to the application."""
        return self._theme_name

    def _apply_theme_setting(self, theme: ThemeName, *, persist: bool) -> None:
        self._theme_name = theme
        self.act_theme_light.setChecked(theme == "light")
        self.act_theme_dark.setChecked(theme == "dark")
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self._refresh_action_icons()
        if self.command_palette is not None:
            self.command_palette.set_icon_theme(theme)
        if self.right_panel is not None:
            self.right_panel.set_icon_theme(theme)
        if self.viewport is not None:
            self.viewport.set_theme(theme)
        refresh_button_icons(self, theme)
        if persist:
            settings = QSettings(ORG_NAME, APP_NAME)
            settings.setValue(SETTINGS_KEY_THEME, theme)
            settings.sync()

    def _on_theme_action(self, theme: ThemeName, _checked: bool = False) -> None:
        self._apply_theme_setting(theme, persist=True)

    def _on_left_dock_toggled(self, visible: bool) -> None:
        if self._compact_layout_active and not self._compact_policy_change:
            self._compact_left_was_visible = visible
        self.left_dock.setVisible(visible)

    def _on_small_bottom_toggled(self, visible: bool) -> None:
        if self._small_screen_active and not self._small_policy_change:
            self._small_bottom_was_visible = visible

    def _on_small_right_toggled(self, visible: bool) -> None:
        if self._small_screen_active and not self._small_policy_change:
            self._small_right_was_visible = visible

    def _enforce_small_screen_policy(self) -> None:
        if not self._small_screen_active:
            return
        self._small_policy_change = True
        self._compact_policy_change = True
        try:
            self.left_dock.hide()
            self.right_dock.hide()
            self.bottom_dock.hide()
        finally:
            self._compact_policy_change = False
            self._small_policy_change = False

    def _restore_layout_for_small_screen(self, state: QByteArray) -> None:
        """Restore saved layout without treating temporary visibility as a user choice."""
        if not self._small_screen_active:
            self.restoreState(state)
            return
        self._small_policy_change = True
        self._compact_policy_change = True
        try:
            self.restoreState(state)
        finally:
            self._compact_policy_change = False
            self._small_policy_change = False
        self._enforce_small_screen_policy()

    def _layout_state_for_persistence(self) -> QByteArray:
        """Save user panel choices instead of temporary small-screen hiding."""
        if not self._small_screen_active or self._home_visibility is not None:
            return self.saveState()
        panels = (
            (
                self.left_dock,
                self._compact_left_was_visible if self.active_workspace == "model" else False,
            ),
            (
                self.right_dock,
                self._small_right_was_visible if self.active_workspace == "model" else False,
            ),
            (self.bottom_dock, self._small_bottom_was_visible),
        )
        previous = tuple((panel, not panel.isHidden()) for panel, _visible in panels)
        updates_enabled = self.updatesEnabled()
        compact_policy_change = self._compact_policy_change
        small_policy_change = self._small_policy_change
        self._compact_policy_change = True
        self._small_policy_change = True
        self.setUpdatesEnabled(False)
        try:
            for panel, visible in panels:
                panel.setVisible(visible)
            return self.saveState()
        finally:
            for panel, visible in previous:
                panel.setVisible(visible)
            self.setUpdatesEnabled(updates_enabled)
            self._small_policy_change = small_policy_change
            self._compact_policy_change = compact_policy_change

    def _set_compact_ribbon_expanded(self, expanded: bool) -> None:
        if (
            self._small_screen_active
            and self.height() < 600
            and expanded
            and self.part_sketch_task is not None
        ):
            self.part_ribbon.setMaximumHeight(150)
        elif not self._small_screen_active or expanded:
            self.part_ribbon.setMaximumHeight(16_777_215)
        else:
            self.part_ribbon.setMaximumHeight(self.part_ribbon.tabBar().sizeHint().height() + 4)

    def _apply_small_screen_policy(self) -> None:
        small = self.width() < 700 or self.height() < 600
        if small == self._small_screen_active:
            return
        self._small_screen_active = small
        if small:
            self.act_expand_compact_ribbon.setEnabled(True)
            self.act_expand_compact_ribbon.setChecked(False)
            self._small_bottom_was_visible = not self.bottom_dock.isHidden()
            self._small_right_was_visible = not self.right_dock.isHidden()
            self._small_policy_change = True
            self.act_toggle_bottom_dock.setChecked(False)
            self.act_toggle_right_dock.setChecked(False)
            self._small_policy_change = False
        else:
            self._small_policy_change = True
            if self._small_bottom_was_visible:
                self.act_toggle_bottom_dock.setChecked(True)
            if self._small_right_was_visible:
                self.act_toggle_right_dock.setChecked(True)
            self._small_policy_change = False
        if not small:
            self.act_expand_compact_ribbon.setChecked(True)
            self.act_expand_compact_ribbon.setEnabled(False)
            self._set_compact_ribbon_expanded(True)
        if self._sketch_dialog is not None:
            self._sketch_dialog.set_compact_layout(small)

    def _apply_compact_layout_policy(self) -> None:
        self._apply_small_screen_policy()
        compact = self.width() < 1000
        if compact and not self._compact_layout_active:
            self._compact_left_was_visible = not self.left_dock.isHidden()
            self._compact_layout_active = True
            self._compact_policy_change = True
            self.act_toggle_left_dock.setChecked(False)
            self._compact_policy_change = False
        elif not compact and self._compact_layout_active:
            self._compact_layout_active = False
            if self._compact_left_was_visible:
                self._compact_policy_change = True
                self.act_toggle_left_dock.setChecked(True)
                self._compact_policy_change = False

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._compact_policy_ready:
            self._apply_compact_layout_policy()
            if self._small_screen_active and self.act_expand_compact_ribbon.isChecked():
                self._set_compact_ribbon_expanded(True)

    def _show_options(self) -> None:
        QMessageBox.information(
            self,
            "选项",
            "窗口布局记忆保存在 QSettings（org=MyCAD, app=MyCAD）。",
        )

    def _show_units(self) -> None:
        QMessageBox.information(self, "单位", "单位：mm（只读）。")

    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "快捷键",
            "新建 Ctrl+N · 打开 Ctrl+O · 保存 Ctrl+S · 撤销 Ctrl+Z · 重做 Ctrl+Y\n"
            "适应窗口 F · 打开 CLI Ctrl+Shift+L · 查看计划 Ctrl+Shift+P\n"
            "重置布局 Ctrl+Shift+0 · 拉伸 Ctrl+Shift+E · 旋转 Ctrl+Shift+R · "
            "孔 Ctrl+Shift+H · 圆角 Ctrl+Shift+F",
        )

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

    def active_sketch_dialog(self) -> SketchEditorDialog | None:
        """当前仍打开的草图编辑器；未打开时返回 ``None``。"""
        return self._sketch_dialog

    def active_sketch_constraint_dialog(self) -> SketchConstraintDialog | None:
        """当前仍打开的草图约束编辑器；未打开时返回 ``None``。"""
        return self._sketch_constraint_dialog

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Bind the app-provided LoadedDocument and subscribe the status fields.

        The bus holds callbacks weakly, so each subscription goes through a
        ``functools.partial`` adapter that keeps the signal name, and this
        window holds the strong references until unbind.
        """
        if (
            self.document_session is not None
            and not self._session_binding
            and self._services is not None
        ):
            entry = self.document_session.find(loaded.document.document_id)
            if entry is None:
                entry = SessionDocument(self._services, loaded, placeholder=True)
                self.document_session.add(entry)
            self.activate_session_document(loaded.document.document_id)
            return
        if self.history_edit_task is not None:
            self.history_edit_task.reject()
        if self.history_repair_task is not None:
            self.history_repair_task.reject()
        if self.bound_hole_task is not None:
            self.bound_hole_task.reject()
        if self.datum_task is not None:
            self.datum_task.reject()
        if self._sketch_dialog is not None:
            self._sketch_dialog.reject()
        if self._active_modeling_command is not None:
            self._end_modeling_tool(cancel_editor=True)
        self._bus = loaded.bus
        self._fillet_last_successful_radius = 1.0
        self._fillet_radius_value = 1.0
        self._session_id += 1
        if self.execution_unit is not None:
            self.execution_unit.set_session(self._session_id)
        # Replacement semantics: dropping our strong adapter list unsubscribes
        # the previous document—its bus only holds subscribers weakly.
        self._signal_adapters.clear()
        self._loaded = loaded
        self.act_measure.setEnabled(
            self._services is not None and loaded.document.document_kind == "part"
        )
        if self.command_palette is not None:
            self.command_palette.set_document_type(loaded.document.document_type)
        for action in self._part_only_actions:
            action.setEnabled(
                loaded.document.document_type == "part" and self.plan_draft is not None
            )
        self.status_dirty.setText("已修改" if loaded.document.is_dirty else "未修改")
        events = loaded.document.events
        for name in dict.fromkeys((*STATUS_SIGNALS, *STRUCTURE_REFRESH_SIGNALS)):
            adapter = partial(self._queue_core_event, self._session_id, name)
            self._signal_adapters.append(adapter)
            events.subscribe(name, adapter)
        if self.right_panel is not None and self._registry is not None:
            self.right_panel.bind_document(
                loaded,
                self._registry,
                kernel=None if self._services is None else self._services.kernel,
            )
        if self.plan_cards is not None:
            self.plan_cards.bind_document(loaded)
        if self.viewport is not None:
            self.viewport.bind_document(loaded)
        if self.cli_tab is not None:
            self.cli_tab.bind_document(loaded)
        self.drawing_workbench.bind_document(loaded, self._session_id)
        if self.document_session is None:
            self._set_workspace_environment(
                "drawing2d" if loaded.document.document_type == "drawing2d" else "part"
            )
        self.workspace_tabs.setTabEnabled(2, True)
        self.workspace_tabs.activate(
            "sketch" if loaded.document.document_type == "drawing2d" else "model"
        )

    def show_start_page(self) -> None:
        """Show the start page without closing any open document."""
        if (
            self.history_edit_task is not None
            or self.history_repair_task is not None
            or self.bound_hole_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再返回首页。")
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成后才能返回首页。")
            return
        self._set_workspace_environment("home")
        if self._home_visibility is None:
            panels: tuple[QWidget, ...] = (
                self.main_toolbar,
                self.modeling_toolbar,
                self.part_sketch_entry_toolbar,
                self.left_dock,
                self.right_dock,
                self.bottom_dock,
                *(
                    widget
                    for widget in (
                        self.fillet_command_bar,
                        self.modeling_command_bar,
                        self.datum_task,
                    )
                    if widget is not None
                ),
            )
            self._home_visibility = {panel: not panel.isHidden() for panel in panels}
            for panel in panels:
                panel.hide()
            self._home_menu_visibility = {
                action: action.isVisible()
                for action in self.menuBar().actions()
                if action not in (self.menu_file.menuAction(), self.menu_help.menuAction())
            }
            for action in self._home_menu_visibility:
                action.setVisible(False)
        self.start_page.set_recent_documents(self.recent_documents.items)
        self.start_page.resume_button.setVisible(
            self.document_session is not None and self.document_session.active is not None
        )
        self._central_pages.setCurrentWidget(self.start_page)

    def _record_recent_document(self, path: Path, kind: DocumentKind) -> None:
        self.recent_documents.add(path, kind)
        self.start_page.set_recent_documents(self.recent_documents.items)

    def _remove_recent_document(self, path: str) -> None:
        self.recent_documents.remove(Path(path))
        self.start_page.set_recent_documents(self.recent_documents.items)

    def _clear_recent_documents(self) -> None:
        self.recent_documents.clear()
        self.start_page.set_recent_documents(self.recent_documents.items)

    def _open_recent_document(self, path: str) -> None:
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再打开文档。")
            return
        target = Path(path)
        if not target.is_file():
            self._show_error("文件不存在；可使用‘定位文件’或‘移除记录’。")
            return
        self.open_document_path(target)

    def _locate_recent_document(self, old_path: str) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "定位最近文档",
            str(Path(old_path).parent),
            "MyCAD 存档 (*.my2d *.my3d *.mc.json);;所有文件 (*)",
        )
        if selected:
            self.open_document_path(Path(selected).absolute(), old_recent_path=Path(old_path))

    def _resume_active_document(self) -> None:
        if self.document_session is not None and self.document_session.active is not None:
            self.activate_session_document(self.document_session.active.loaded.document.document_id)

    def _show_session_workspace(self) -> None:
        self._central_pages.setCurrentWidget(self.workspace_container)
        if self._home_visibility is not None:
            for panel, visible in self._home_visibility.items():
                panel.setVisible(visible)
            self._home_visibility = None
            for action, visible in self._home_menu_visibility.items():
                action.setVisible(visible)
            self._home_menu_visibility.clear()

    def _create_from_start_page(self, kind: str) -> None:
        if kind not in ("sketch", "drawing", "part"):
            return
        if self.document_session is None or self._services is None:
            return
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再创建文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再创建文档。")
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成后才能创建文档。")
            return
        template: str | None = None
        if kind == "drawing":
            dialog = DrawingTemplateChoiceDialog(self)
            result = dialog.exec()
            selected = dialog.selector.currentData()
            if result != QDialog.DialogCode.Accepted or not isinstance(selected, str):
                dialog.deleteLater()
                return
            template = selected
            dialog.deleteLater()
        self.new_session_document(kind)
        if template is not None:
            selector = self.drawing_workbench.templates.selector
            selector.setCurrentIndex(selector.findData(template))
            self.drawing_workbench.create_sheet()

    def close_active_document(self) -> None:
        """Close the active session document after its existing save guards."""
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再关闭文档。")
            return
        session = self.document_session
        if session is None or session.active is None:
            return
        entry = session.active
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再关闭文档。")
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成前无法关闭文档。")
            return
        if self._has_unsubmitted_geometry(include_sketch=False):
            return
        if not entry.needs_save:
            self._finish_close_document(entry)
            return
        choices = self._ask_session_close_dialog((entry,))
        if choices is None:
            return
        choice = choices.get(entry.loaded.document.document_id)
        if choice == "discard":
            self._finish_close_document(entry)
        elif choice == "save" and self.document_saver is not None:
            self.document_saver.save_many(
                (entry,),
                on_complete=lambda success: self._finish_close_document(entry) if success else None,
            )

    def _finish_close_document(self, entry: SessionDocument) -> None:
        session = self.document_session
        if session is None or session.active is not entry:
            return
        if self.part_sketch_task is not None:
            self.part_sketch_task.reject()
        if self._sketch_dialog is not None:
            self._sketch_dialog.reject()
            self._sketch_dialog = None
        identity = entry.loaded.document.document_id
        session.remove(identity)
        if session.documents:
            self.activate_session_document(session.documents[-1].loaded.document.document_id)
            return
        self._signal_adapters.clear()
        self._session_id += 1
        if self.execution_unit is not None:
            self.execution_unit.set_session(self._session_id)
        self._loaded = None
        self.act_measure.setEnabled(False)
        self._bus = None
        self._document_path = None
        self._refresh_document_choice()
        self.show_start_page()

    def new_session_document(
        self, kind: DocumentKind, *, placeholder: bool = False
    ) -> SessionDocument:
        session, services = self.document_session, self._services
        if session is None or services is None:
            raise RuntimeError("No document session")
        services = mycad_app.fork_app_services(services)
        entry = SessionDocument(
            services, mycad_app.new_workspace_document(services, kind=kind), placeholder=placeholder
        )
        session.add(entry)
        self.activate_session_document(entry.loaded.document.document_id)
        return entry

    def _on_document_tab_changed(self, index: int) -> None:
        identity = self.document_tab_bar.tabData(index)
        if isinstance(identity, str):
            self.activate_session_document(identity)

    def _on_document_tab_close_requested(self, index: int) -> None:
        identity = self.document_tab_bar.tabData(index)
        session = self.document_session
        if not isinstance(identity, str) or session is None:
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成前无法关闭文档。")
            return
        if session.active is None or session.active.loaded.document.document_id != identity:
            self.activate_session_document(identity)
        if session.active is not None and session.active.loaded.document.document_id == identity:
            self.close_active_document()

    def _on_document_choice(self, _index: int) -> None:
        if self.document_selector is not None:
            identity = self.document_selector.currentData()
            if isinstance(identity, str):
                self.activate_session_document(identity)

    def _refresh_document_choice(self) -> None:
        session, selector = self.document_session, self.document_selector
        if session is None:
            return
        previous_block = self.document_tab_bar.blockSignals(True)
        while self.document_tab_bar.count():
            self.document_tab_bar.removeTab(0)
        for document in session.documents:
            index = self.document_tab_bar.addTab(
                document.label + (" *" if document.needs_save else "")
            )
            self.document_tab_bar.setTabData(index, document.loaded.document.document_id)
        if session.active is not None:
            for index, document in enumerate(session.documents):
                if document is session.active:
                    self.document_tab_bar.setCurrentIndex(index)
                    break
        self.document_tab_bar.blockSignals(previous_block)
        if selector is not None:
            selector.blockSignals(True)
            selector.clear()
            for entry in session.documents:
                selector.addItem(
                    entry.label + (" *" if entry.needs_save else ""),
                    entry.loaded.document.document_id,
                )
            if session.active is not None:
                selector.setCurrentIndex(
                    selector.findData(session.active.loaded.document.document_id)
                )
            selector.blockSignals(False)
        entry = session.active
        if entry is not None:
            entry.draft = self._sketch_dialog
            self._show_document_path(entry.path)
            self.status_dirty.setText("已修改" if entry.needs_save else "未修改")
            internal = (
                "内部草图 — " if self.active_workspace == "sketch" and entry.kind == "part" else ""
            )
            self.setWindowTitle(
                f"{internal}{entry.label}{' *' if entry.needs_save else ''} — MyCAD"
            )
            if selector is not None:
                selector.setToolTip("\n".join(entry.reference_messages) or "当前编辑文档")

    @staticmethod
    def _layout_environment(kind: DocumentKind) -> str:
        return "drawing2d" if kind == "sketch" else kind

    def _active_layout_environment(self, kind: DocumentKind) -> str:
        if kind == "part" and self.part_sketch_task is not None:
            return "part-sketch"
        return self._layout_environment(kind)

    def activate_session_document(self, identity: str) -> None:
        session = self.document_session
        if session is None:
            return
        entry = session.find(identity)
        if entry is None:
            return
        if entry is not session.active and (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再切换文档。")
            self._refresh_document_choice()
            return
        if entry is not session.active and self.part_sketch_task is not None:
            if self.part_sketch_task.has_draft:
                self.status_command.setText("零件草图尚未完成；请先完成或取消草图再切换文档。")
                self._refresh_document_choice()
                return
            self.part_sketch_task.reject()
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self._pending_document_activation = identity
            self._refresh_document_choice()
            self.status_command.setText("文档切换将在当前操作完成后进行。")
            return
        self._show_session_workspace()
        if entry is session.active and self._loaded is entry.loaded:
            workspace: WorkspaceId = (
                "model"
                if entry.kind == "part"
                else "drawing"
                if entry.kind == "drawing"
                else "sketch"
            )
            self._workspace_transition = True
            try:
                self.workspace_tabs.activate(workspace)
            finally:
                self._workspace_transition = False
            if workspace == "sketch":
                self._on_sketch_start()
            self._refresh_document_choice()
            self._set_workspace_environment(self._active_layout_environment(entry.kind))
            self._enforce_small_screen_policy()
            return
        previous = session.active
        if previous is not None:
            environment = self._layout_environment(previous.kind)
            self.workspace_layout.save(environment, self._layout_state_for_persistence())
            self.workspace_layout.save_locked(environment, self.act_lock_toolbar.isChecked())
            if previous.loaded is self._loaded:
                previous.draft = self._sketch_dialog
                if self._sketch_dialog is not None:
                    self._drafting_toolbar_state = self._sketch_dialog.toolbar_layout_state()
                previous.plan_draft = self.plan_draft
            if self.viewport is not None:
                previous.view_state = self.viewport.capture_view()
        self._sketch_dialog = None
        self.workspace_tabs.set_content("sketch", None)
        session.activate(identity)
        self._services = entry.services
        self._document_path = entry.path
        self._session_binding = True
        try:
            if entry.plan_draft is None:
                entry.plan_draft = PlanDraftController(entry.services.registry)
            self.plan_draft = entry.plan_draft
            if self.right_panel is not None:
                self.right_panel.bind_draft(self.plan_draft)
            if self.plan_cards is not None:
                self.plan_cards.bind_draft(self.plan_draft)
            if entry.workbench is None:
                if previous is None:
                    entry.workbench = self.drawing_workbench
                    entry.workbench.services = entry.services
                else:
                    bench = DrawingWorkbench(entry.services, self.execution_unit)
                    bench.source_selection_available = True
                    bench.message.connect(partial(self._on_owned_engineering_message, bench))
                    bench.sketch_requested.connect(lambda: self.workspace_tabs.activate("sketch"))
                    bench.model_requested.connect(self._show_3d_workspace)
                    bench.open_requested.connect(self._on_open_document)
                    bench.new_requested.connect(self._on_new_document)
                    bench.choose_source_requested.connect(self._choose_engineering_source)
                    self.destroyed.connect(lambda: bench.shutdown())
                    entry.workbench = bench
            self.drawing_workbench = entry.workbench
            self.workspace_tabs.set_content("drawing", self.drawing_workbench)
            if self.viewport is not None:
                self.viewport.set_viewport_port(entry.services.kernel)
            if self.cli_tab is not None:
                self.cli_tab.set_services(entry.services)
            if (
                self.plan_cards is not None
                and self.execution_unit is not None
                and self.viewport is not None
            ):
                self.plan_cards.configure_execution(
                    self.execution_unit,
                    session_id=lambda: self._session_id,
                    prepare_geometry=entry.services.kernel.viewport_data,
                    preview_builder=partial(mycad_app.preview_command, entry.services),
                    show_candidate_preview=self.viewport.show_candidate_preview,
                    clear_candidate_preview=self.viewport.clear_candidate_preview,
                )
            self.bind_document(entry.loaded)
            self._sketch_dialog = entry.draft
            workspace = (
                "model"
                if entry.kind == "part"
                else "drawing"
                if entry.kind == "drawing"
                else "sketch"
            )
            if entry.draft is not None:
                self.workspace_tabs.set_content("sketch", entry.draft)
            self.workspace_tabs.activate(workspace)
            if workspace == "sketch":
                self._on_sketch_start()
            if self.viewport is not None and entry.view_state is not None:
                self.viewport.restore_view(entry.view_state)
        finally:
            self._session_binding = False
        if self.left_tabs is not None:
            self.left_tabs.setTabVisible(0, entry.kind == "part")
        layout_state = self.workspace_layout.load(self._layout_environment(entry.kind))
        if layout_state is not None:
            self.restoreState(layout_state)
        self.act_lock_toolbar.setChecked(
            self.workspace_layout.load_locked(self._layout_environment(entry.kind)) or False
        )
        self._set_workspace_environment(self._active_layout_environment(entry.kind))
        self._enforce_small_screen_policy()
        self._refresh_document_choice()

    def _queue_core_event(
        self, session_id: int, name: SignalName, payload: Mapping[str, object]
    ) -> None:
        """Queue signal payloads so worker callbacks never touch Qt widgets."""
        self._core_event_queued.emit(session_id, name, dict(payload))

    @Slot(int, str, object)
    def _dispatch_core_event(self, session_id: int, name: str, value: object) -> None:
        """Apply only current-session core events from the UI thread."""
        if session_id != self._session_id or not isinstance(value, Mapping):
            return
        payload = cast("Mapping[str, object]", value)
        self.handle_core_signal(cast("SignalName", name), payload)
        if name in MODIFYING_SIGNALS:
            if self.right_panel is not None:
                self.right_panel.invalidate_measurement()
            if self._active_modeling_command == "modify.fillet":
                if not self._fillet_commit_inflight:
                    self._fillet_preview_pending = False
                    self._invalidate_fillet_preview()
            elif self._active_modeling_command is not None and not self._modeling_commit_inflight:
                self._modeling_preview_pending = False
                self._invalidate_modeling_preview()
        if name in STRUCTURE_REFRESH_SIGNALS:
            self._on_structure_signal(name, payload)
            self.drawing_workbench.refresh()
        self._refresh_document_choice()

    def attach_session_source(self, source_id: str, *, object_id: str = "") -> None:
        session, unit = self.document_session, self.execution_unit
        if session is None or session.active is None or unit is None or unit.is_busy:
            return
        if self._has_unsubmitted_geometry():
            return
        source, target = session.find(source_id), session.active
        if source is None or source is target:
            self._show_error("来源文档无效，文档不能引用自身。")
            return
        params = mycad_app.reference_parameters(
            source.loaded.document,
            object_id=object_id,
            path=str(source.path) if source.path else "",
        )
        self._submit_reference_operation(target, "reference.attach", params)

    def _submit_reference_operation(
        self, entry: SessionDocument, command: str, params: Mapping[str, object]
    ) -> None:
        unit = self.execution_unit
        if unit is None:
            return

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                self._show_error(result.error)
                return
            if command in ("reference.attach", "reference.update"):
                file_id, locator = params.get("file_id"), params.get("path")
                if isinstance(file_id, str) and isinstance(locator, str) and locator:
                    entry.reference_locations[file_id] = locator
                entry.reference_messages = ()
            if self.document_session is not None and self.document_session.active is entry:
                self.drawing_workbench.refresh()
                self._sync_drawing_layers()
                if self.viewport is not None:
                    self.viewport.refresh()
            self._refresh_document_choice()
            self.status_command.setText("来源关联已写入当前文档；可撤销、保存和重放。")

        unit.submit(
            lambda: entry.loaded.bus.execute(command, params, "local"),
            operation=command,
            session_id=self._session_id,
            on_complete=finish,
        )

    def separate_internal_sketch(self) -> None:
        session, unit = self.document_session, self.execution_unit
        if session is None or session.active is None or unit is None or unit.is_busy:
            return
        owner = session.active
        if owner.kind != "part":
            self.status_command.setText("先激活三维零件，再分离已完成的内部草图。")
            return
        linked = {
            r.reference_id for r in owner.services.kernel.document_references if r.kind == "sketch"
        }
        sketches = [s for s in owner.services.kernel.sketches if s.sketch_id not in linked]
        if not sketches:
            self.status_command.setText("没有可分离的内部草图；关联草图需先解除来源关联。")
            return
        names = [s.sketch_id for s in sketches]
        chosen, accepted = (
            (names[0], True)
            if len(names) == 1
            else QInputDialog.getItem(self, "分离内部草图", "选择已完成的草图", names, 0, False)
        )
        if not accepted:
            return

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                self._show_error(result.error)
                return
            services, loaded = cast("tuple[AppServices, LoadedDocument]", result.value)
            entry = SessionDocument(services, loaded)
            session.add(entry)
            self.activate_session_document(loaded.document.document_id)
            self.status_command.setText("已分离为独立二维文档，请保存为 .my2d；原模型保持原草图。")

        unit.submit(
            lambda: mycad_app.separate_internal_sketch(owner.services, chosen),
            operation="separate-internal-sketch",
            session_id=self._session_id,
            on_complete=finish,
        )

    def _show_reference_status(self) -> None:
        session, unit = self.document_session, self.execution_unit
        if session is None or session.active is None or unit is None or unit.is_busy:
            return
        entry = session.active

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                self._show_error(result.error)
                return
            entry.reference_messages = cast("tuple[str, ...]", result.value)
            self._refresh_document_choice()
            if session.active is entry:
                self.status_command.setText(
                    "\n".join(entry.reference_messages) or "当前文档没有来源关联。"
                )

        unit.submit(
            lambda: mycad_app.reference_association_status(
                entry.services, entry.loaded, entry.path, locations=entry.reference_locations
            ),
            operation="inspect-reference-status",
            session_id=self._session_id,
            on_complete=finish,
        )

    def _use_current_sketch_for_model(self) -> None:
        session = self.document_session
        if session is None or session.active is None or session.active.kind != "sketch":
            self.status_command.setText("先激活独立平面草图文档，再使用“用于建模”。")
            return
        source = session.active

        def prepared(success: bool) -> None:
            if not success:
                return
            sketches = source.services.kernel.sketches
            if not sketches:
                self._show_error("来源文档中还没有已完成的草图。")
                return
            names = [f"草图 {i + 1} · {s.sketch_id[:8]}" for i, s in enumerate(sketches)]
            chosen, accepted = (
                (names[0], True)
                if len(names) == 1
                else QInputDialog.getItem(self, "用于建模", "选择来源草图", names, 0, False)
            )
            if not accepted:
                return
            self.new_session_document("part")
            self.attach_session_source(
                source.loaded.document.document_id,
                object_id=sketches[names.index(chosen)].sketch_id,
            )

        self._prepare_session_document(source, prepared)

    def _choose_engineering_source(self) -> None:
        session = self.document_session
        if session is None or session.active is None or session.active.kind != "drawing":
            self.status_command.setText("先激活工程图文档，再选择来源。")
            return
        if self._has_unsubmitted_geometry():
            return
        target = session.active
        sources = [e for e in session.documents if e is not target and e.kind in ("part", "sketch")]
        if not sources:
            self._show_error("请先创建或打开来源零件或独立平面草图。")
            return
        names = [e.label + f" · {i + 1}" for i, e in enumerate(sources)]
        chosen, accepted = QInputDialog.getItem(self, "工程图来源", "选择来源文档", names, 0, False)
        if not accepted:
            return
        source = sources[names.index(chosen)]
        object_id = ""
        if source.kind == "sketch":
            sketches = source.services.kernel.sketches
            if not sketches:
                self._show_error("来源二维文档中没有已完成的草图。")
                return
            sketch_names = [f"草图 {i + 1} · {s.sketch_id[:8]}" for i, s in enumerate(sketches)]
            name, ok = (
                (sketch_names[0], True)
                if len(sketch_names) == 1
                else QInputDialog.getItem(self, "草图来源", "选择草图", sketch_names, 0, False)
            )
            if not ok:
                return
            object_id = sketches[sketch_names.index(name)].sketch_id
        self.attach_session_source(source.loaded.document.document_id, object_id=object_id)

    def _choose_active_reference(self) -> tuple[SessionDocument, str] | None:
        session = self.document_session
        if session is None or session.active is None:
            return None
        entry = session.active
        refs = entry.services.kernel.document_references
        if not refs:
            self._show_error("当前文档没有来源关联。")
            return None
        labels = [
            f"{r.kind} · {Path(r.path).name if r.path else r.file_id[:8]} · {i + 1}"
            for i, r in enumerate(refs)
        ]
        label, ok = (
            (labels[0], True)
            if len(labels) == 1
            else QInputDialog.getItem(self, "来源关联", "选择关联", labels, 0, False)
        )
        return (entry, refs[labels.index(label)].reference_id) if ok else None

    def _detach_document_reference(self) -> None:
        if self._has_unsubmitted_geometry():
            return
        chosen = self._choose_active_reference()
        if chosen is not None:
            entry, identity = chosen
            self._submit_reference_operation(entry, "reference.detach", {"reference_id": identity})

    def _update_document_reference(self) -> None:
        if self._has_unsubmitted_geometry():
            return
        chosen = self._choose_active_reference()
        session = self.document_session
        if chosen is None or session is None:
            return
        entry, identity = chosen
        reference = next(
            r for r in entry.services.kernel.document_references if r.reference_id == identity
        )
        source = next(
            (e for e in session.documents if e.loaded.document.file_id == reference.file_id), None
        )
        if source is None:
            location = entry.reference_locations.get(reference.file_id, reference.path)
            default = (
                (entry.path.parent / location)
                if entry.path is not None and location
                else Path(location)
            )
            selected, _filter = QFileDialog.getOpenFileName(
                self, "定位来源文档", str(default), "MyCAD 来源 (*.my2d *.my3d)"
            )
            if not selected:
                return
            unit = self.execution_unit
            if unit is None:
                return

            def read_source() -> dict[str, object]:
                candidates = mycad_app.open_session_documents(entry.services, Path(selected))
                _services, loaded = candidates[0]
                if loaded.document.file_id != reference.file_id:
                    raise ValidationError("来源文件身份不匹配；不能按文件名替换关联。")
                return mycad_app.reference_parameters(
                    loaded.document,
                    object_id=reference.object_id,
                    path=selected,
                    reference_id=identity,
                )

            def finish_source(result: ExecutionResult) -> None:
                if result.error is not None:
                    self._show_error(result.error)
                elif isinstance(result.value, dict):
                    self._submit_reference_operation(
                        entry, "reference.update", cast("dict[str, object]", result.value)
                    )

            unit.submit(
                read_source,
                operation="read-reference-source",
                session_id=self._session_id,
                on_complete=finish_source,
            )
            return
        params = mycad_app.reference_parameters(
            source.loaded.document,
            object_id=reference.object_id,
            path=str(source.path) if source.path else "",
            reference_id=identity,
        )
        self._submit_reference_operation(entry, "reference.update", params)

    def _on_structure_pick(self, ordinal: int) -> None:
        """Load a clicked historical mesh on the serialized worker, then render it."""
        if (
            self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再查看历史状态。")
            return
        viewport = self.viewport
        if viewport is None:
            return
        state_id = viewport.history_state_id_for_ordinal(ordinal)
        if state_id is None:
            return
        unit = self.execution_unit
        services = self._services
        if unit is None or services is None:
            viewport.preview_history_feature(ordinal)
            return

        def load_history_mesh() -> ViewportData | None:
            return services.kernel.historical_viewport_data(state_id)

        def finish_history_preview(result: ExecutionResult) -> None:
            if result.error is not None:
                self.status_command.setText(f"历史预览失败：{result.error[:200]}")
                return
            value = result.value
            if not isinstance(value, ViewportData):
                self.status_command.setText("历史预览失败：返回结果无效")
                return
            if not viewport.preview_history_snapshot(state_id, value):
                self.status_command.setText("历史状态已失效，请重新选择")

        if not unit.submit(
            load_history_mesh,
            operation="history-preview",
            session_id=self._session_id,
            on_complete=finish_history_preview,
        ):
            self.status_command.setText("当前有操作正在执行，历史预览稍后可重试")

    def _register_plugin_actions(self) -> None:
        services = self._services
        if services is None:
            return
        for contribution in services.plugins.command_contributions():
            spec = contribution.spec
            if self.action_catalog.find(spec.id) is not None:
                continue
            action = QAction(spec.label_zh, self)
            action.setIcon(cad_icon(command_icon_name(spec.id), self._theme_name))
            if spec.id not in AFFECTED_OBJECTS:
                action.setEnabled(False)
                action.setToolTip(f"插件命令 {spec.id} 当前不支持在桌面计划中执行。")
            else:
                action.setToolTip(f"插件命令 {spec.id}")
                action.triggered.connect(partial(self._on_toolbar_modeling, spec.id))
                self._part_only_actions.append(action)
            self.action_catalog.register(spec.id, action)

    def shortcut_conflicts(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Report collisions among enabled window/application shortcuts without changing them."""
        grouped: dict[str, list[str]] = {}
        for action in self.findChildren(QAction):
            if not action.isEnabled() or not action.isVisible():
                continue
            if action.shortcutContext() not in (
                Qt.ShortcutContext.WindowShortcut,
                Qt.ShortcutContext.ApplicationShortcut,
            ):
                continue
            for shortcut in action.shortcuts():
                key = shortcut.toString(QKeySequence.SequenceFormat.PortableText)
                if key:
                    grouped.setdefault(key, []).append(action.text() or "未命名动作")
        return tuple(
            (key, tuple(names)) for key, names in sorted(grouped.items()) if len(names) > 1
        )

    def _show_shortcut_conflicts(self) -> None:
        conflicts = self.shortcut_conflicts()
        message = (
            "\n".join(f"{key}：{'、'.join(names)}" for key, names in conflicts)
            if conflicts
            else "当前启用的窗口及应用快捷键没有发现冲突。"
        )
        QMessageBox.information(self, "快捷键冲突", message)

    def _setup_quick_access(self) -> None:
        defaults = ("file.new", "file.open", "file.save", "edit.undo", "edit.redo")
        default_actions = {self.action_catalog.get(identity) for identity in defaults}
        for action in tuple(self.main_toolbar.actions()):
            if action in default_actions or action.isSeparator():
                self.main_toolbar.removeAction(action)
        self.act_customize_quick_access = QAction("⋯", self)
        self.act_customize_quick_access.setToolTip("自定义当前环境的快速访问")
        self.act_customize_quick_access.triggered.connect(self._configure_quick_access)
        self.main_toolbar.addAction(self.act_customize_quick_access)
        self.quick_access = QuickAccessController(
            self.main_toolbar,
            self.action_catalog,
            QuickAccessStore(QSettings(ORG_NAME, APP_NAME)),
            defaults=defaults,
            before=self.act_customize_quick_access,
        )
        self.quick_access.set_environment("home" if self.document_session is not None else "part")

    def _configure_quick_access(self) -> None:
        dialog = QuickAccessDialog(self.action_catalog, self.quick_access.identities, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.quick_access.set_actions(dialog.identities())
        dialog.deleteLater()

    def _console_state_changed(self, _value: object = None) -> None:
        tabs, environment = self.bottom_tabs, self._console_environment
        if tabs is None or environment is None or self._restoring_console:
            return
        expanded, page, height = tabs.capture_state()
        self.workspace_layout.save_console(environment, expanded, page, height)

    def _set_workspace_environment(self, environment: str) -> None:
        self.quick_access.set_environment(environment)
        if self._console_environment == environment:
            return
        self._console_state_changed()
        self._console_environment = environment
        if self.bottom_tabs is None:
            return
        self._restoring_console = True
        try:
            self.bottom_tabs.restore_state(self.workspace_layout.load_console(environment))
        finally:
            self._restoring_console = False

    def _start_history_edit(self, value: object, ordinal: int) -> None:
        if not isinstance(value, HistoryEditDialog):
            return
        dialog = value
        unit = self.execution_unit
        if (
            unit is None
            or self.history_edit_task is not None
            or self._active_modeling_command is not None
            or self.datum_task is not None
            or self._has_unsubmitted_geometry()
        ):
            self.status_command.setText("请先完成或取消当前命令，再编辑历史。")
            dialog.reject()
            return
        self.history_edit_task = dialog
        dialog.set_cancel_guard(lambda: not unit.is_busy)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        bar = QToolBar("历史编辑", self)
        bar.setObjectName("historyEditCommandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        install_command_strip(bar, dialog, (dialog.confirm_button, dialog.cancel_button))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        dialog.impact_label.setText(f"编辑 #{ordinal}；修改参数并预览候选。")

        def busy_changed(busy: bool) -> None:
            if not busy and dialog.cancel_requested:
                dialog.reject()

        unit.busy_changed.connect(busy_changed)

        def finished(_result: int) -> None:
            unit.busy_changed.disconnect(busy_changed)
            if self.history_edit_task is dialog:
                self.history_edit_task = None
            self.removeToolBarBreak(bar)
            self.removeToolBar(bar)
            bar.setObjectName("")
            bar.deleteLater()

        dialog.finished.connect(finished)
        bar.show()
        dialog.show()

    def _preview_history_candidate(
        self, raw_dialog: object, ordinal: int, params: object, reason: str
    ) -> None:
        if not isinstance(raw_dialog, HistoryEditDialog):
            return
        dialog = raw_dialog
        services, loaded, unit = self._services, self._loaded, self.execution_unit
        session_id = self._session_id
        if services is None or loaded is None or unit is None or not isinstance(params, Mapping):
            dialog.candidate_preview_finished(None, "候选预览不可用。")
            return
        if self._has_unsubmitted_geometry(include_history=False):
            dialog.candidate_preview_finished(None, "请先完成或取消当前草稿，再编辑历史。")
            return
        normalized = cast("Mapping[str, object]", params)
        created: list[mycad_app.ReplayCandidateSession] = []

        def preview() -> tuple[
            mycad_app.ReplayCandidateSession | None,
            str,
            ViewportData | None,
            tuple[ViewportSketchData, ...],
            bool,
        ]:
            candidate = mycad_app.create_replay_candidate(
                services, loaded, session_identity=session_id
            )
            created.append(candidate)
            try:
                candidate.stage(
                    ReplayChangeSet(
                        (ReplayEdit(ordinal, normalized, "gui-local", reason),), (), False
                    ),
                    current_session_identity=session_id,
                )
                result = candidate.preview(current_session_identity=session_id)
                if result.state == "succeeded":
                    return (
                        candidate,
                        "候选重放成功，可确认重建。",
                        result.viewport,
                        result.sketches,
                        False,
                    )
                failure = result.failure
                message = (
                    f"候选重放失败：#{failure.ordinal} {failure.command_id}：{failure.reason}"
                    if failure is not None
                    else "候选已失效，请重新预览。"
                )
                if (
                    failure is not None
                    and failure.command_id == "feature.hole"
                    and failure.command_version == 3
                    and failure.parameter_path == "target_face"
                    and result.failure_scene is not None
                ):
                    command = next(
                        (
                            item
                            for item in result.proposal.commands
                            if item.ordinal == failure.ordinal
                        ),
                        None,
                    )
                    target = command.params.get("target_face") if command is not None else None
                    if (
                        isinstance(target, Mapping)
                        and cast("Mapping[str, object]", target).get("kind") == "bound_face"
                    ):
                        return candidate, message, None, (), True
                candidate.cancel()
                return None, message, None, (), False
            except Exception:
                candidate.cancel()
                raise

        def stale_result(stale_session: int) -> None:
            if stale_session != session_id:
                return
            unit.stale_result_discarded.disconnect(stale_result)
            for candidate in created:
                if candidate.state not in ("cancelled", "committed"):
                    candidate.cancel()
            if dialog.isVisible():
                dialog.candidate_preview_finished(None, "文档已切换，候选预览已取消。")

        unit.stale_result_discarded.connect(stale_result)

        def finish(result: ExecutionResult) -> None:
            unit.stale_result_discarded.disconnect(stale_result)
            value = result.value
            if result.error is not None:
                if dialog.isVisible():
                    dialog.candidate_preview_finished(None, f"候选重放失败：{result.error}")
                return
            if not isinstance(value, tuple):
                if dialog.isVisible():
                    dialog.candidate_preview_finished(None, "候选结果无效。")
                return
            pair = cast("tuple[object, ...]", value)
            if len(pair) != 5:
                if dialog.isVisible():
                    dialog.candidate_preview_finished(None, "候选结果无效。")
                return
            candidate, message, snapshot, sketches, repairable = pair
            if not isinstance(message, str) or not isinstance(repairable, bool):
                return
            if not isinstance(candidate, mycad_app.ReplayCandidateSession):
                if dialog.isVisible():
                    dialog.candidate_preview_finished(None, message)
                return
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or not dialog.isVisible()
                or not dialog.candidate_preview_finished(candidate, message, repairable=repairable)
            ):
                candidate.cancel()
                return
            if isinstance(snapshot, ViewportData) and isinstance(sketches, tuple):
                viewport_sketches = cast("tuple[ViewportSketchData, ...]", sketches)
                if self.viewport is not None:
                    self.viewport.show_candidate_preview(
                        snapshot, preserve_view=True, sketches=viewport_sketches
                    )

        if not unit.submit(
            preview,
            operation="history-candidate-preview",
            session_id=session_id,
            on_complete=finish,
        ):
            unit.stale_result_discarded.disconnect(stale_result)
            dialog.candidate_preview_finished(None, "当前有操作正在执行，请稍后重试。")

    def _start_history_repair(
        self, value: object, ordinal: int, params: object, reason: str
    ) -> None:
        services, loaded, viewport, unit = (
            self._services,
            self._loaded,
            self.viewport,
            self.execution_unit,
        )
        if not isinstance(value, mycad_app.ReplayCandidateSession):
            return
        candidate = value
        proposal = candidate.proposal
        preview = candidate.latest_preview
        failure = preview.failure if preview is not None else None
        failed_command = (
            next((item for item in proposal.commands if item.ordinal == failure.ordinal), None)
            if proposal is not None and failure is not None
            else None
        )
        target = failed_command.params.get("target_face") if failed_command is not None else None
        if (
            services is None
            or loaded is None
            or viewport is None
            or unit is None
            or not isinstance(params, Mapping)
            or proposal is None
            or proposal.document_id != loaded.document.document_id
            or proposal.session_identity != self._session_id
            or self.history_repair_task is not None
            or self.history_edit_task is not None
            or failure is None
            or failure.command_id != "feature.hole"
            or failure.command_version != 3
            or failure.parameter_path != "target_face"
            or not isinstance(target, Mapping)
            or cast("Mapping[str, object]", target).get("kind") != "bound_face"
        ):
            candidate.cancel()
            self.status_command.setText("失效修复候选不可用，请重新预览。")
            return
        try:
            task = HistoryRepairTask(
                candidate,
                loaded,
                viewport,
                unit,
                ordinal=ordinal,
                params=cast("Mapping[str, object]", params),
                reason=reason,
                session_identity=self._session_id,
                current_session=lambda: self._session_id,
                parent=self,
            )
        except (MycadError, ValueError) as exc:
            candidate.cancel()
            self.status_command.setText(f"无法开始失效修复：{exc}")
            return
        self.history_repair_task = task
        task.setWindowFlags(Qt.WindowType.Widget)
        bar = QToolBar("历史修复", self)
        bar.setObjectName("historyRepairCommandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        install_command_strip(bar, task, (task.confirm_button, task.cancel_button))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

        def task_finished(_result: int) -> None:
            if self.history_repair_task is task:
                self.history_repair_task = None
            self.removeToolBarBreak(bar)
            self.removeToolBar(bar)
            bar.setObjectName("")
            bar.deleteLater()

        task.finished.connect(task_finished)
        bar.show()
        task.show()

    def _discard_history_candidate(self, value: object) -> None:
        if isinstance(value, mycad_app.ReplayCandidateSession):
            value.cancel()
            if self.viewport is not None:
                self.viewport.clear_candidate_preview()

    def _commit_history_candidate(self, value: object, ordinal: int) -> None:
        if not isinstance(value, mycad_app.ReplayCandidateSession):
            return
        candidate = value
        if self.viewport is not None:
            self.viewport.clear_candidate_preview()
        unit, loaded, session_id = self.execution_unit, self._loaded, self._session_id
        proposal = candidate.proposal
        if (
            unit is None
            or loaded is None
            or proposal is None
            or proposal.session_identity != session_id
            or proposal.document_id != loaded.document.document_id
        ):
            candidate.cancel()
            self.status_command.setText("历史候选已失效，请重新预览。")
            return

        def commit() -> None:
            candidate.commit(
                candidate.authorize_commit(current_session_identity=session_id),
                current_session_identity=session_id,
            )

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                candidate.cancel()
                self.status_command.setText(f"历史编辑失败：{result.error[:240]}")
                return
            self.status_command.setText(f"已更新历史命令 #{ordinal}；模型与下游命令已重建")
            if self.rebuild_hook is not None:
                self.request_rebuild()

        if not unit.submit(
            commit, operation="history-candidate-commit", session_id=session_id, on_complete=finish
        ):
            candidate.cancel()
            self.status_command.setText("当前有操作正在执行，历史候选未提交。")

    def _on_history_edit_requested(
        self, ordinal: int, params: object, actor: str, reason: str
    ) -> None:
        """Run a confirmed history edit through the serialized document worker."""

        loaded = self._loaded
        unit = self.execution_unit
        if loaded is None or unit is None or not isinstance(params, Mapping):
            self.status_command.setText("历史编辑失败：当前文档或规范化参数不可用")
            return
        normalized = cast("Mapping[str, object]", params)

        def edit_and_replay() -> None:
            loaded.bus.edit_and_replay(ordinal, normalized, actor, reason)

        def finish_edit(result: ExecutionResult) -> None:
            if result.error is not None:
                self.status_command.setText(f"历史编辑失败：{result.error[:240]}")
                return
            self.status_command.setText(f"已更新历史命令 #{ordinal}；模型与下游命令已重建")
            if self.rebuild_hook is not None:
                self.request_rebuild()

        if not unit.submit(
            edit_and_replay,
            operation="history-edit",
            session_id=self._session_id,
            on_complete=finish_edit,
        ):
            self.status_command.setText("当前有操作正在执行，历史编辑未提交")

    def _on_current_entity_pick(self, selected: bool) -> None:
        """Current-result selection has no inferred feature-source ordinal."""
        if self.right_panel is not None:
            self.right_panel.select_feature_ordinal(None)
        self.status_selection.setText("当前模型已选中" if selected else "选择 0")

    def _on_body_pick(self, identity: object) -> None:
        if not isinstance(identity, BodyId) or self.viewport is None:
            return
        if identity in self.viewport.hidden_body_ids():
            self.status_command.setText("此实体已隐藏；请先勾选显示后再选择。")
            if self.right_panel is not None:
                self.right_panel.set_view_selection(self.viewport.selection())
            return
        if self._active_modeling_command is not None:
            self.status_command.setText(
                "请在视口选择当前命令所需的面或边；Esc 退出命令后可选实体。"
            )
            if self.right_panel is not None:
                self.right_panel.set_view_selection(self.viewport.selection())
            return
        self._set_viewport_selection_filter("body")
        self.viewport.select_body(identity)

    def _on_history_preview_changed(self, active: bool) -> None:
        """Keep the preview exit action, status and tree in the same state."""
        self.act_return_current_model.setEnabled(active)
        if self.right_panel is not None:
            self.right_panel.set_view_selection(None)
        if active and self.viewport is not None:
            ordinal = self.viewport.history_preview_ordinal()
            suffix = "" if ordinal is None else f" #{ordinal}"
            self.status_selection.setText(f"历史预览{suffix}")
        else:
            self.status_selection.setText("选择 0")
            if self.right_panel is not None:
                self.right_panel.select_feature_ordinal(None)

    def _return_current_model(self) -> None:
        if (
            self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再返回当前模型。")
            return
        if self.viewport is not None:
            self.viewport.show_current_model()

    def _guard_cli_command(self, line: str) -> str | None:
        command = line.strip()
        if self.document_session is not None and command.split(maxsplit=1)[:1] in (
            ["new"],
            ["open"],
            ["save"],
        ):
            return "多文档模式请使用文件菜单新建、打开或保存，以保留每份文档的路径与修改状态。"
        if (
            not command
            or command.startswith("#")
            or command.split()[0] in {"help", "history", "quit", "exit"}
        ):
            return None
        if self._has_unsubmitted_geometry():
            return (
                "草图尚未提交：请先完成或取消草稿，再执行 CLI 写入命令；help / history 仍可使用。"
            )
        return None

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
            running = self.execution_unit is not None and self.execution_unit.is_busy
            self.status_rebuild.setText("重建状态：执行中" if running else "重建状态：就绪")
        if name == "document_saved":
            self.status_dirty.setText("未修改")
        elif name in MODIFYING_SIGNALS:
            self.status_dirty.setText("已修改")

    def request_rebuild(self) -> None:
        """Rebuild action slot; todo 9 sets ``_rebuild_hook`` on the viewport."""
        unit = self.execution_unit
        services = self._services
        if unit is None or services is None or self.rebuild_hook is None:
            if self.rebuild_hook is not None:
                self.rebuild_hook()
            return

        def prepare_mesh() -> None:
            services.kernel.viewport_data()

        def finish_refresh(result: ExecutionResult) -> None:
            self._finish_worker_action(result, "重建")
            if result.error is None and self.rebuild_hook is not None:
                self.rebuild_hook()

        unit.submit(
            prepare_mesh,
            operation="viewport-refresh",
            session_id=self._session_id,
            on_complete=finish_refresh,
        )

    def _on_execution_busy_changed(self, busy: bool) -> None:
        """Show busy feedback and keep Qt interactions out of worker time."""
        if self.datum_task is not None:
            self.datum_task.setEnabled(not busy)
        if self._sketch_dialog is not None:
            self._sketch_dialog.setEnabled(not busy)
        if self.right_panel is not None:
            self.right_panel.set_measurement_busy(busy)
        if self.viewport is not None:
            self.viewport.set_execution_busy(busy)
        if busy:
            self._busy_action_states = {}
            interactive_actions: set[QAction] = set()
            if self.bound_hole_task is not None:
                bound_bar = self.findChild(QToolBar, "boundHoleCommandBar")
                if bound_bar is not None:
                    interactive_actions.update(bound_bar.actions())
                    interactive_actions.update(bound_bar.findChildren(QAction))
                    interactive_actions.add(bound_bar.toggleViewAction())
            if self.history_repair_task is not None:
                repair_bar = self.findChild(QToolBar, "historyRepairCommandBar")
                if repair_bar is not None:
                    interactive_actions.update(repair_bar.actions())
                    interactive_actions.update(repair_bar.findChildren(QAction))
                    interactive_actions.add(repair_bar.toggleViewAction())
            if self.history_edit_task is not None:
                edit_bar = self.findChild(QToolBar, "historyEditCommandBar")
                if edit_bar is not None:
                    interactive_actions.update(edit_bar.actions())
                    interactive_actions.update(edit_bar.findChildren(QAction))
                    interactive_actions.add(edit_bar.toggleViewAction())
            if (
                self.execution_unit is not None
                and self.execution_unit.operation is not None
                and self.execution_unit.operation.endswith("-preview")
                and self._active_modeling_command is not None
            ):
                if self.modeling_command_bar is not None:
                    interactive_actions.update(self.modeling_command_bar.actions())
                if self.fillet_command_bar is not None:
                    interactive_actions.update(self.fillet_command_bar.actions())
                interactive_actions.update(self.orientation_actions.values())
                interactive_actions.update(self.projection_actions.values())
                interactive_actions.update(self.render_mode_actions.values())
                interactive_actions.add(self.act_fit_view)
                interactive_actions.update(
                    (
                        self.menu_view.menuAction(),
                        self.act_standard_orientation,
                        self.projection_menu.menuAction(),
                        self.render_mode_menu.menuAction(),
                    )
                )
            for action in self.findChildren(QAction):
                if action is self.act_quit or action in interactive_actions:
                    continue
                self._busy_action_states[action] = action.isEnabled()
                action.setEnabled(False)
            self.status_rebuild.setText("重建状态：执行中")
            return
        for action, enabled in self._busy_action_states.items():
            if isValid(action):
                action.setEnabled(enabled)
        self._busy_action_states.clear()
        self._sync_workspace_actions()
        self.status_rebuild.setText("重建状态：就绪")
        if self._sketch_dialog is not None and self._services is not None:
            self._sync_drawing_layers()
        if self.execution_unit is None or not self.execution_unit.is_delivering_result:
            self._on_execution_delivery_finished()

    def _on_execution_delivery_finished(self) -> None:
        if self.execution_unit is not None and self.execution_unit.is_busy:
            return
        if self._pending_document_activation is not None:
            identity = self._pending_document_activation
            self._pending_document_activation = None
            QTimer.singleShot(0, partial(self.activate_session_document, identity))
        if self._session_close_waiting:
            QTimer.singleShot(0, self.close)

    def _finish_worker_action(self, result: ExecutionResult, label: str) -> None:
        if result.error is not None:
            self.status_command.setText(f"{label}失败：{result.error}")
        elif self._sketch_dialog is not None and self._services is not None:
            self._sync_drawing_layers()

    def request_undo(self) -> None:
        if (
            self.active_workspace == "sketch"
            and self.execution_unit is not None
            and (self.execution_unit.is_busy or self.execution_unit.is_delivering_result)
        ):
            self.status_command.setText("请等待当前操作完成后再撤销。")
            return
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再撤销。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再撤销。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再撤销。")
            return
        if self.part_sketch_task is not None and self.active_workspace == "model":
            self.part_sketch_task.undo()
            return
        draft = self._sketch_dialog
        if (
            draft is not None
            and self.active_workspace == "sketch"
            and (
                draft.canvas.active_transform is not None
                or (draft.canvas.tool == "二维圆角" and draft.canvas.has_active_edit_gesture)
            )
        ):
            self.status_command.setText("请先完成或取消当前二维操作，再撤销。")
            return
        layer_undo = (
            draft is not None
            and self._loaded is not None
            and draft.layer_history_boundaries.get(len(self._loaded.document.commands))
            == draft.canvas.history_position
            and not draft.canvas.has_pending_geometry
            and not draft.canvas.has_active_edit_gesture
            and bool(self._loaded.document.commands)
            and self._loaded.document.commands[-1].id
            in {"drawing.layers.set", "sketch.revise", "drawing.sketch.revise"}
        )
        boundary = (
            (len(self._loaded.document.commands), draft.canvas.history_position)
            if layer_undo and draft is not None and self._loaded is not None
            else None
        )
        if (
            not layer_undo
            and draft is not None
            and self.active_workspace == "sketch"
            and (
                draft.canvas.entities
                or draft.canvas.has_pending_geometry
                or draft.canvas.can_undo
                or draft.canvas.can_redo
            )
        ):
            draft.canvas.undo_last_operation()
            return
        if self._bus is None:
            self.status_command.setText("未绑定文档，无法撤销")
            return
        unit = self.execution_unit
        services = self._services
        if unit is not None and services is not None:
            bus = self._bus

            def undo() -> None:
                bus.undo_operation()
                services.kernel.viewport_data()

            def finished(result: ExecutionResult) -> None:
                if (
                    result.error is None
                    and boundary is not None
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.layer_history_redo.append(boundary)
                self._finish_worker_action(result, "撤销")

            unit.submit(
                undo,
                operation="undo",
                session_id=self._session_id,
                on_complete=finished,
            )
            return
        try:
            self._bus.undo_operation()
        except InvalidHistoryError as err:
            self.status_command.setText(f"撤销失败：{err}")

    def request_redo(self) -> None:
        if (
            self.active_workspace == "sketch"
            and self.execution_unit is not None
            and (self.execution_unit.is_busy or self.execution_unit.is_delivering_result)
        ):
            self.status_command.setText("请等待当前操作完成后再重做。")
            return
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再重做。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再重做。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再重做。")
            return
        if self.part_sketch_task is not None and self.active_workspace == "model":
            self.part_sketch_task.redo()
            return
        draft = self._sketch_dialog
        if (
            draft is not None
            and self.active_workspace == "sketch"
            and (
                draft.canvas.active_transform is not None
                or (draft.canvas.tool == "二维圆角" and draft.canvas.has_active_edit_gesture)
            )
        ):
            self.status_command.setText("请先完成或取消当前二维操作，再重做。")
            return
        layer_redo = (
            draft is not None
            and self._loaded is not None
            and bool(draft.layer_history_redo)
            and draft.layer_history_redo[-1]
            == (len(self._loaded.document.commands) + 1, draft.canvas.history_position)
            and not draft.canvas.has_pending_geometry
            and not draft.canvas.has_active_edit_gesture
        )
        if (
            not layer_redo
            and draft is not None
            and self.active_workspace == "sketch"
            and (
                draft.canvas.entities
                or draft.canvas.has_pending_geometry
                or draft.canvas.can_undo
                or draft.canvas.can_redo
            )
        ):
            draft.canvas.redo_last_operation()
            return
        if self._bus is None:
            self.status_command.setText("未绑定文档，无法重做")
            return
        unit = self.execution_unit
        services = self._services
        if unit is not None and services is not None:
            bus = self._bus

            def redo() -> None:
                bus.redo_operation()
                services.kernel.viewport_data()

            def finished(result: ExecutionResult) -> None:
                if (
                    result.error is None
                    and layer_redo
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.layer_history_redo.pop()
                self._finish_worker_action(result, "重做")

            unit.submit(
                redo,
                operation="redo",
                session_id=self._session_id,
                on_complete=finished,
            )
            return
        try:
            self._bus.redo_operation()
        except InvalidHistoryError as err:
            self.status_command.setText(f"重做失败：{err}")

    # ------------------------------------------------------------------
    # Layout memory (UI draft §4.1)
    # ------------------------------------------------------------------

    def _arrange_command_toolbars(self) -> None:
        """Reserve a separate row for the active command, below main actions."""
        bars = (self.fillet_command_bar, self.modeling_command_bar)
        for bar in bars:
            if bar is not None:
                self.removeToolBarBreak(bar)
                self.removeToolBar(bar)
        if self.toolBarArea(self.main_toolbar) == Qt.ToolBarArea.TopToolBarArea:
            self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        for bar in bars:
            if bar is None:
                continue
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
            active = self._active_modeling_command
            bar.setVisible(
                active == "modify.fillet"
                if bar is self.fillet_command_bar
                else active is not None and active != "modify.fillet"
            )

    def restore_window_state(self) -> None:
        settings = QSettings(ORG_NAME, APP_NAME)
        theme_value = settings.value(SETTINGS_KEY_THEME, "light")
        theme: ThemeName = (
            cast("ThemeName", theme_value)
            if isinstance(theme_value, str) and theme_value in {"light", "dark"}
            else "light"
        )
        self._apply_theme_setting(theme, persist=False)
        geometry = settings.value(SETTINGS_KEY_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value(SETTINGS_KEY_STATE)
        restored_state = False
        if state is not None:
            restored_state = self.restoreState(state)
        self.removeToolBarBreak(self.part_sketch_entry_toolbar)
        self.insertToolBarBreak(self.part_sketch_entry_toolbar)
        # Separate preference survives old versions writing their saved dock layout.
        area_value = settings.value(
            SETTINGS_KEY_TOOLBAR_AREA, Qt.ToolBarArea.TopToolBarArea.value, type=int
        )
        areas = {
            area.value: area
            for area in (
                Qt.ToolBarArea.TopToolBarArea,
                Qt.ToolBarArea.BottomToolBarArea,
                Qt.ToolBarArea.LeftToolBarArea,
                Qt.ToolBarArea.RightToolBarArea,
            )
        }
        preferred_area = (
            areas.get(area_value, Qt.ToolBarArea.TopToolBarArea)
            if isinstance(area_value, int)
            else Qt.ToolBarArea.TopToolBarArea
        )
        if self.toolBarArea(self.main_toolbar) != preferred_area:
            self.addToolBar(preferred_area, self.main_toolbar)
        # Reparenting restored command bars before the first show can corrupt
        # Qt's dock layout. The restored state already includes their placement.
        if not restored_state:
            self._arrange_command_toolbars()
        locked = settings.value(SETTINGS_KEY_TOOLBAR_LOCKED, False)
        if isinstance(locked, bool) and locked:
            self.act_lock_toolbar.setChecked(True)
        self.act_toggle_toolbar.setChecked(not self.main_toolbar.isHidden())
        self.act_toggle_left_dock.setChecked(not self.left_dock.isHidden())
        self.act_toggle_right_dock.setChecked(not self.right_dock.isHidden())
        # Preserve new per-environment console choices; old layouts still start collapsed.
        if (
            self.bottom_tabs is None
            or self._console_environment is None
            or not self.workspace_layout.has_console(self._console_environment)
        ):
            self.bottom_dock.hide()
        self.act_toggle_bottom_dock.setChecked(not self.bottom_dock.isHidden())
        drafting_state = settings.value("layout/draftingToolbars")
        self._drafting_toolbar_state = (
            drafting_state if isinstance(drafting_state, QByteArray) else None
        )
        self._modeling_toolbar_was_visible = bool(
            settings.value("toolbar/modelingVisible", False, type=bool)
        )
        self.modeling_toolbar.setVisible(self._modeling_toolbar_was_visible)
        self._compact_policy_ready = True
        self._apply_compact_layout_policy()

    def store_window_state(self) -> None:
        self._console_state_changed()
        if self.document_session is not None and self.document_session.active is not None:
            environment = self._active_layout_environment(self.document_session.active.kind)
            self.workspace_layout.save(environment, self._layout_state_for_persistence())
            self.workspace_layout.save_locked(environment, self.act_lock_toolbar.isChecked())
        settings = QSettings(ORG_NAME, APP_NAME)
        settings.setValue(SETTINGS_KEY_GEOMETRY, self.saveGeometry())
        settings.setValue(SETTINGS_KEY_STATE, self._layout_state_for_persistence())
        if self._sketch_dialog is not None:
            self._drafting_toolbar_state = self._sketch_dialog.toolbar_layout_state()
        if self._drafting_toolbar_state is not None:
            settings.setValue("layout/draftingToolbars", self._drafting_toolbar_state)
        else:
            settings.remove("layout/draftingToolbars")
        in_drawing = self._sketch_dialog is not None and self.active_workspace == "sketch"
        settings.setValue(
            "toolbar/modelingVisible",
            self._modeling_toolbar_was_visible
            if in_drawing
            else not self.modeling_toolbar.isHidden(),
        )
        area = self.toolBarArea(self.main_toolbar)
        if area != Qt.ToolBarArea.NoToolBarArea:
            settings.setValue(SETTINGS_KEY_TOOLBAR_AREA, area.value)
        settings.setValue(SETTINGS_KEY_TOOLBAR_LOCKED, self.act_lock_toolbar.isChecked())
        settings.setValue(SETTINGS_KEY_THEME, self._theme_name)
        settings.sync()

    # ------------------------------------------------------------------
    # Document lifecycle (todo 8)
    # ------------------------------------------------------------------

    def _on_new_document(self) -> None:
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再创建文档。")
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成后才能创建文档。")
            return
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法新建")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再创建文档。")
            return
        if self.document_session is None and self._has_unsubmitted_geometry():
            return
        if self.new_document_dialog is not None:
            self.new_document_dialog.raise_()
            return
        initial = self._loaded.document.document_type if self._loaded is not None else "part"
        dialog = NewDocumentDialog(self, initial=initial)
        self.new_document_dialog = dialog
        result = dialog.exec()
        self.new_document_dialog = None
        if result == QDialog.DialogCode.Accepted:
            if self.document_session is not None:
                self.new_session_document(dialog.document_kind)
            else:
                self._create_document(dialog.document_type)
        dialog.deleteLater()

    def _on_new_drawing_document(self) -> None:
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再创建文档。")
            return
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作完成后才能创建文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再创建文档。")
            return
        if self.document_session is not None:
            self.new_session_document("sketch")
            return
        previous = self._loaded
        self._create_document("drawing2d")
        if self._loaded is not previous:
            self._on_sketch_start()

    def _create_document(self, document_type: DocumentType) -> None:
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法新建")
            return
        if not self._confirm_unsaved_changes(
            on_saved=partial(self._create_document, document_type)
        ):
            return
        self._replace_document(
            mycad_app.new_document(self._services, document_type=document_type), None
        )

    def _on_import_dxf_sketch(self) -> None:
        if self._services is None or self._loaded is None:
            self.status_command.setText("请先打开或新建文档，再导入 DXF 草图。")
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self, "导入 DXF 草图", "", "DXF 草图 (*.dxf)"
        )
        if selected:
            self._queue_dxf_sketch_import(Path(selected), unit_override=None)

    def _queue_dxf_sketch_import(self, path: Path, *, unit_override: str | None) -> None:
        loaded = self._loaded
        unit = self.execution_unit
        services = self._services
        if loaded is None or unit is None or services is None:
            self.status_command.setText("当前文档不可用，DXF 未导入。")
            return
        session_id = self._session_id

        def read_sketch() -> DxfSketchImport | _DxfUnitPrompt:
            try:
                return DXF_PROVIDER.read_sketch(path, unit_override=unit_override)
            except DxfUnitOverrideRequired as exc:
                return _DxfUnitPrompt(str(exc))

        def finish_read(result: ExecutionResult) -> None:
            if result.error is not None:
                self._show_error(f"无法读取 DXF 草图：{result.error[:240]}")
                return
            if isinstance(result.value, _DxfUnitPrompt):
                units = ("mm", "cm", "m", "inch", "ft", "mil", "micron")
                selected_unit, accepted = QInputDialog.getItem(
                    self,
                    "DXF 单位未声明",
                    f"{result.value.message}\n请选择文件中的长度单位：",
                    list(units),
                    0,
                    False,
                )
                if accepted and selected_unit:
                    self._queue_dxf_sketch_import(path, unit_override=selected_unit)
                else:
                    self.status_command.setText("DXF 未声明单位；导入已取消，文档历史未改变。")
                return
            if not isinstance(result.value, DxfSketchImport):
                self._show_error("无法读取 DXF 草图：返回结果无效。")
                return
            imported = result.value
            if not imported.sketch.entities:
                self._show_error(f"DXF 中没有可导入的支持图元：{imported.report}")
                return
            existing_sketch_ids = {
                command.params.get("sketch_id")
                for command in loaded.document.commands
                if command.id == "sketch.create"
            }
            report = imported.report
            sketch = imported.sketch
            if sketch.sketch_id in existing_sketch_ids:
                sketch = Sketch(
                    uuid4().hex,
                    sketch.frame,
                    sketch.entities,
                    constraints=sketch.constraints,
                    layers=sketch.layers,
                    support_face=sketch.support_face,
                )
                report = DxfExchangeReport(
                    report.action,
                    report.dxf_version,
                    report.unit,
                    report.entity_count,
                    (*report.warnings, "草图身份与当前文档重复，已分配新的 MyCAD 草图身份"),
                )
            preview = (
                f"{report}\n\n将把 {len(sketch.entities)} 个支持图元作为一张 XY 草图追加到当前文档。"
                f"\n恢复关联尺寸 {len(sketch.constraints)} 个。"
                "\n确认前不会修改命令历史或模型。"
            )
            choice = QMessageBox.question(
                self,
                "导入 DXF 草图预览",
                preview,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                self.status_command.setText("DXF 草图导入已取消；文档历史未改变。")
                return

            def submit_sketch() -> object:
                return mycad_app.commit_new_sketch(
                    services, loaded, sketch, session_identity=session_id
                )

            def finish_submit(submit_result: ExecutionResult) -> None:
                if submit_result.error is not None:
                    self._show_error(f"DXF 草图提交失败：{submit_result.error[:240]}")
                    return
                if self.viewport is not None:
                    self.viewport.refresh()
                self.status_command.setText(
                    f"DXF 草图已导入并写入命令历史：{len(sketch.entities)} 个图元，"
                    f"{len(sketch.constraints)} 个关联尺寸；可撤销、重做和保存重放。"
                )

            if not unit.submit(
                submit_sketch,
                operation="dxf-sketch-import-commit",
                session_id=session_id,
                on_complete=finish_submit,
            ):
                self.status_command.setText("应用工作线程忙碌，DXF 草图尚未提交；请稍后重试。")

        if not unit.submit(
            read_sketch,
            operation="dxf-sketch-import-preview",
            session_id=session_id,
            on_complete=finish_read,
        ):
            self.status_command.setText("应用工作线程忙碌，DXF 尚未读取；请稍后重试。")

    def _on_open_document(self) -> None:
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再打开文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再打开文档。")
            return
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法打开")
            return
        if self.document_session is None and not self._confirm_unsaved_changes(
            on_saved=self._on_open_document
        ):
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "打开存档",
            str(self._document_directory()),
            "MyCAD 存档 (*.my2d *.my3d *.mc.json);;"
            "二维图 (*.my2d);;三维零件 (*.my3d);;旧版存档 (*.mc.json);;所有文件 (*)",
        )
        if not selected:
            return
        self.open_document_path(Path(selected).absolute())

    def open_document_path(self, path: Path, *, old_recent_path: Path | None = None) -> None:
        if (
            self._active_modeling_command is not None
            or self.datum_task is not None
            or self.bound_hole_task is not None
            or self.history_repair_task is not None
            or self.history_edit_task is not None
        ):
            self.status_command.setText("请先完成或取消当前命令，再打开文档。")
            return
        if self._services is None:
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再打开文档。")
            return
        if self.document_session is not None:
            unit, session, services = self.execution_unit, self.document_session, self._services
            if unit is None:
                return
            existing = next(
                (
                    d
                    for d in session.documents
                    if d.path is not None and path_identity(d.path) == path_identity(path)
                ),
                None,
            )
            if existing is not None:
                self.activate_session_document(existing.loaded.document.document_id)
                if old_recent_path is not None and old_recent_path != path:
                    self.recent_documents.remove(old_recent_path)
                self._record_recent_document(path, existing.kind)
                return

            def open_candidates() -> mycad_app.SessionOpenResult:
                return mycad_app.open_session_bundle(services, path)

            def finish_candidates(result: ExecutionResult) -> None:
                if result.error is not None:
                    self._show_error(result.error)
                    return
                bundle = cast("mycad_app.SessionOpenResult", result.value)
                candidates, migrated = bundle.documents, bundle.migrated
                entries = tuple(
                    SessionDocument(
                        srv,
                        loaded,
                        None if migrated else path,
                        reference_messages=bundle.reference_messages,
                    )
                    for srv, loaded in candidates
                )
                known = {e.loaded.document.file_id: e for e in session.documents}
                if any(e.loaded.document.file_id in known for e in entries):
                    found = next(
                        known[e.loaded.document.file_id]
                        for e in entries
                        if e.loaded.document.file_id in known
                    )
                    self.activate_session_document(found.loaded.document.document_id)
                    if old_recent_path is not None and old_recent_path != path:
                        self.recent_documents.remove(old_recent_path)
                    self._record_recent_document(path, found.kind)
                    return
                added: list[str] = []
                try:
                    for entry in entries:
                        if entry.path is not None:
                            session.check_path(entry, entry.path)
                    for entry in entries:
                        session.add(entry)
                        added.append(entry.loaded.document.document_id)
                except ValidationError as exc:
                    for identity in reversed(added):
                        session.remove(identity)
                    self._show_error(str(exc))
                    return
                if entries:
                    self.activate_session_document(entries[-1].loaded.document.document_id)
                    if old_recent_path is not None and old_recent_path != path:
                        self.recent_documents.remove(old_recent_path)
                    if not migrated:
                        self._record_recent_document(path, entries[-1].kind)
                if migrated:
                    self.status_command.setText(
                        "旧档已迁移为独立待保存文档；原文件保持不变。请使用“全部保存”命名新文件。"
                    )
                elif bundle.reference_messages:
                    self.status_command.setText("\n".join(bundle.reference_messages))

            if not unit.submit(
                open_candidates,
                operation="open-session-document",
                session_id=self._session_id,
                on_complete=finish_candidates,
            ):
                self.status_command.setText("操作正在执行，请稍候再打开文档")
            return

        unit = self.execution_unit
        services = self._services
        if unit is not None:
            session_id = self._session_id

            def open_document() -> LoadedDocument:
                loaded = mycad_app.open_app_document(services, path)
                services.kernel.viewport_data()
                return loaded

            def finish_open(result: ExecutionResult) -> None:
                if result.error is not None:
                    self._show_error(f"无法打开存档：{result.error[:200]}")
                    return
                if isinstance(result.value, LoadedDocument):
                    self._replace_document(result.value, path)
                else:
                    self._show_error("无法打开存档：返回结果无效")

            if not unit.submit(
                open_document,
                operation="open-document",
                session_id=session_id,
                on_complete=finish_open,
            ):
                self.status_command.setText("操作正在执行，请稍候再打开文档")
            return
        try:
            loaded = mycad_app.open_app_document(self._services, path)
        except ValidationError as exc:
            self._show_error(f"存档格式无效：{exc}")
            return
        except MycadError as exc:
            self._show_error(f"无法重建存档：{exc}")
            return
        except OSError as exc:
            self._show_error(f"无法读取存档：{exc}")
            return
        self._replace_document(loaded, path)

    def _on_save_document(self) -> None:
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再保存文档。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再保存文档。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再保存文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再保存文档。")
            return
        if self.document_saver is not None and self.document_session is not None:
            if self.document_session.active is not None:
                self.document_saver.save_one(self.document_session.active)
            return
        self._save_document()

    def _on_save_document_as(self) -> None:
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再保存文档。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再保存文档。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再保存文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再保存文档。")
            return
        if self.document_saver is not None and self.document_session is not None:
            if self.document_session.active is not None:
                self.document_saver.save_one(self.document_session.active, save_as=True)
            return
        self._save_document(save_as=True)

    def _on_save_all_documents(self) -> None:
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再保存文档。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再保存文档。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再保存文档。")
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再保存文档。")
            return
        if self.document_saver is not None and self.document_session is not None:
            self._refresh_document_choice()
            self.document_saver.save_many(
                tuple(d for d in self.document_session.documents if d.needs_save)
            )

    def _session_save_changed(self) -> None:
        session = self.document_session
        if session is not None and session.active is not None:
            if self._loaded is not session.active.loaded:
                if self._sketch_dialog is not None:
                    self.workspace_tabs.set_content("sketch", None)
                    self._sketch_dialog = None
                session.active.draft = None
                self.activate_session_document(session.active.loaded.document.document_id)
            self._document_path = session.active.path
        self._refresh_document_choice()

    def _report_session_save(self, results: tuple[SaveResult, ...]) -> None:
        if self.document_session is not None:
            for result in results:
                entry = self.document_session.find(result.document_id)
                if result.status == "saved" and entry is not None and entry.path is not None:
                    self._record_recent_document(entry.path, entry.kind)
        labels = {"saved": "已保存", "failed": "失败", "pending": "尚未保存", "cancelled": "已取消"}
        self.status_command.setText(
            "；".join(
                f"{r.label}：{labels[r.status]}{(' — ' + r.error) if r.error else ''}"
                for r in results
            )
            or "所有文档均已保存。"
        )

    def _choose_session_save_path(self, entry: SessionDocument) -> Path | None:
        if self.document_session is not None and self.document_session.active is not entry:
            self.activate_session_document(entry.loaded.document.document_id)
        if self.document_session is not None and (
            self.document_session.active is not entry or self._loaded is not entry.loaded
        ):
            return None
        return self._choose_document_save_path()

    def _prepare_session_document(
        self, entry: SessionDocument, complete: Callable[[bool], None]
    ) -> None:
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            complete(False)
            return
        if self.document_session is not None and self.document_session.active is not entry:
            self.activate_session_document(entry.loaded.document.document_id)
        if self.document_session is not None and (
            self.document_session.active is not entry or self._loaded is not entry.loaded
        ):
            complete(False)
            return
        if self._has_unsubmitted_geometry(include_sketch=False):
            self._show_error(self.status_command.text())
            complete(False)
            return
        draft = self._sketch_dialog
        if draft is None or not (draft.canvas.entities or draft.canvas.has_pending_geometry):
            complete(True)
            return
        self._after_sketch_commit = lambda: complete(True)
        self._after_sketch_failure = lambda: complete(False)
        draft.finish_sketch()
        self._after_sketch_commit = None
        self._after_sketch_failure = None
        if self._sketch_dialog is draft and (
            self.execution_unit is None or not self.execution_unit.is_busy
        ):
            self._show_error(draft.status_label.text())
            complete(False)

    def _ask_session_close_dialog(
        self, entries: tuple[SessionDocument, ...]
    ) -> dict[str, str] | None:
        dialog = UnsavedDocumentsDialog(entries, self)
        result = dialog.exec()
        choices = dialog.choices if result == QDialog.DialogCode.Accepted else None
        dialog.deleteLater()
        return choices

    def _save_document(
        self, *, save_as: bool = False, on_saved: Callable[[], object] | None = None
    ) -> bool:
        """Save immediately, or resume after the active sketch commits successfully."""
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            self.status_command.setText("操作正在执行，请稍候再保存文档。")
            return False
        if self._has_unsubmitted_geometry(include_sketch=False):
            return False
        if self._loaded is None:
            self.status_command.setText("未绑定文档")
            return False
        path = self._document_path
        if save_as or path is None:
            path = self._choose_document_save_path()
        if path is None:
            return False

        def store() -> bool:
            if not self._store_document(path):
                return False
            self._document_path = path
            return True

        draft = self._sketch_dialog
        if draft is not None and self._has_unsubmitted_sketch():

            def after_commit() -> None:
                if store() and on_saved is not None:
                    on_saved()

            self._after_sketch_commit = after_commit
            draft.finish_sketch()
            self._after_sketch_commit = None
            if self._sketch_dialog is draft:
                self._show_error(draft.status_label.text())
            return False
        return store()

    def _choose_document_save_path(self) -> Path | None:
        if self._loaded is None:
            return None
        drawing2d = self._loaded.document.document_type == "drawing2d"
        suffix = ".my2d" if drawing2d else ".my3d"
        default_name = "untitled-drawing.my2d" if drawing2d else "untitled.my3d"
        if self.document_session is not None and self.document_session.active is not None:
            default_name = DEFAULT_NAMES[self.document_session.active.kind]
        default_path = self._document_path or self._document_directory() / default_name
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存存档",
            str(default_path),
            ("MyCAD 二维图 (*.my2d)" if drawing2d else "MyCAD 三维零件 (*.my3d)")
            + ";;旧版存档 (*.mc.json)",
        )
        if not selected:
            return None
        path = Path(selected).absolute()
        if path.suffix.lower() == ".masm":
            self._show_error(".masm 为装配图预留；当前请保存为二维图或三维零件。")
            return None
        if (
            self.document_session is not None
            and path.suffix.lower() in (".my2d", ".my3d")
            and path.suffix.lower() != suffix
        ):
            self._show_error(f"当前文档应保存为 {suffix}；请更正文件后缀。")
            return None
        if not path.name.lower().endswith(NATIVE_ARCHIVE_SUFFIXES):
            extension = ".mc.json" if "*.mc.json" in _selected_filter else suffix
            path = path.with_name(path.name + extension)
            # Qt confirmed only the entered name, not this completed target.
            if (
                path.exists()
                and QMessageBox.question(
                    self,
                    "覆盖存档",
                    f"文件已存在：{path}\n是否覆盖？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return None
        return path

    def _document_directory(self) -> Path:
        if self._document_path is not None and self._document_path.parent.is_dir():
            return self._document_path.parent
        saved = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_DOCUMENT_DIRECTORY, "")
        if isinstance(saved, str) and saved and Path(saved).is_dir():
            return Path(saved).absolute()
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        return Path(documents) if documents and Path(documents).is_dir() else Path.home()

    def _show_document_path(self, path: Path | None) -> None:
        self.setWindowFilePath(str(path) if path is not None else "")
        self.setWindowTitle(f"{path.name} — MyCAD" if path is not None else "MyCAD")
        self.status_dirty.setToolTip(str(path) if path is not None else "尚未保存")
        if path is not None:
            QSettings(ORG_NAME, APP_NAME).setValue(
                SETTINGS_KEY_DOCUMENT_DIRECTORY, str(path.parent)
            )

    def _store_document(self, path: Path) -> bool:
        if self._has_unsubmitted_geometry():
            return False
        if self._loaded is None:
            return False
        try:
            save_document(
                self._loaded.document,
                path,
                plugin_identities=(
                    mycad_app.archive_plugin_identities(self._services)
                    if self._services is not None
                    else {}
                ),
            )
        except OSError as exc:
            self._show_error(f"写入失败：{exc}")
            return False
        # persistence 不清脏；保存成功后显式 mark_clean（document.py 约定）。
        self._loaded.document.mark_clean()
        self.status_dirty.setText("未修改")
        self._show_document_path(path)
        self.status_command.setText(f"已保存：{path}")
        return True

    def _on_export_document(self) -> None:
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再导出文档。")
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再导出文档。")
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再导出文档。")
            return
        if self.active_workspace == "drawing":
            self.drawing_workbench.choose_export("pdf")
            return
        if self._services is None:
            self.status_command.setText("未组合应用服务，无法导出")
            return
        drawing2d = self._loaded is not None and self._loaded.document.document_type == "drawing2d"
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出 DXF 草图" if drawing2d else "导出（STEP/STL/DXF）",
            "",
            "DXF 草图 (*.dxf)"
            if drawing2d
            else "STEP 文件 (*.step *.stp);;STL 文件 (*.stl);;DXF 草图 (*.dxf)",
        )
        if not selected:
            return
        target = Path(selected)
        if drawing2d and target.suffix.lower() != ".dxf":
            self._show_error("独立二维图只支持导出 DXF。")
            return
        try:
            provider = self._services.formats.resolve(target)
            if cast("object", provider) is DXF_PROVIDER:
                self._queue_dxf_output_preview(target)
                return
            report = provider.write(self._services.kernel, target)
        except UnknownFormatError as exc:
            self._show_error(f"不支持的导出格式：{exc}")
            return
        except MycadError as exc:
            self._show_error(f"导出失败：{exc}")
            return
        except OSError as exc:
            self._show_error(f"写入失败：{exc}")
            return
        suffix = f"；{report}" if report is not None else ""
        self.status_command.setText(f"已导出：{target}{suffix}")

    def _queue_dxf_output_preview(self, target: Path) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None:
            self.status_command.setText("当前文档不可用，DXF 未导出。")
            return
        session_id, revision = self._session_id, loaded.document.revision

        def is_current() -> bool:
            return (
                self._loaded is loaded
                and self._session_id == session_id
                and loaded.document.revision == revision
            )

        def finish_preview(result: ExecutionResult) -> None:
            if not is_current():
                self.status_command.setText("DXF 输出预览已过期，请从当前文档重新导出。")
                return
            preview = result.value
            if result.error is not None or not isinstance(preview, DxfOutputPreview):
                self._show_error(f"DXF 输出预览失败：{result.error or '返回结果无效'}")
                return
            try:
                dialog = DxfOutputPreviewDialog(preview, target.name, self)
            except ValueError as exc:
                self._show_error(str(exc))
                return
            accepted = dialog.exec() == int(dialog.DialogCode.Accepted)
            dialog.deleteLater()
            if not accepted:
                self.status_command.setText("DXF 导出已取消；目标文件未改变。")
                return
            if not is_current():
                self.status_command.setText("DXF 输出预览已过期，请从当前文档重新导出。")
                return
            try:
                preview.write(target)
            except OSError as exc:
                self._show_error(f"DXF 写入失败，原文件未改变：{exc}")
                return
            self.status_command.setText(f"已导出：{target}；{preview.report}")

        if unit.submit(
            lambda: prepare_dxf_output_preview(services.kernel),
            operation="dxf-output-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            self.status_command.setText("正在生成 DXF 输出预览…")
        else:
            self.status_command.setText("应用工作线程忙碌，DXF 尚未导出；请稍后重试。")

    def _has_unsubmitted_geometry(
        self, *, include_sketch: bool = True, include_history: bool = True
    ) -> bool:
        if include_history and self.history_edit_task is not None:
            self.status_command.setText("历史编辑尚未确认，请先完成或取消当前命令。")
            return True
        if self.history_repair_task is not None:
            self.status_command.setText("历史修复尚未确认，请先完成或取消当前命令。")
            return True
        if self.bound_hole_task is not None:
            self.status_command.setText("绑定孔尚未确认，请先完成或取消当前命令。")
            return True
        if include_sketch and self._has_unsubmitted_sketch():
            return True
        if self.drawing_workbench.notes.pending:
            self.status_command.setText(
                "工程图文字尚未提交：Ctrl+Enter 完成或 Esc 取消，再保存或切换文档。"
            )
            return True
        if self.drawing_workbench.annotations.pending:
            self.status_command.setText("工程图标注尚未提交：请在图中单击放置或按 Esc 取消。")
            return True
        if self.drawing_workbench.has_pending_view_edit:
            self.status_command.setText("工程图视图操作尚未确认：请先完成或按 Esc 取消。")
            return True
        placement = self.drawing_workbench.placement
        if placement is not None and placement.pending:
            self.status_command.setText(
                "工程图视图组尚未提交：请在画布按 Enter 完成或 Esc 取消，再保存或切换文档。"
            )
            return True
        return False

    def _has_unsubmitted_sketch(self) -> bool:
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("零件草图尚未提交，请先完成或取消草图。")
            self.part_sketch_task.status_label.setText(self.status_command.text())
            return True
        draft = self._sketch_dialog
        if draft is None:
            return False
        if not (draft.canvas.entities or draft.canvas.has_pending_geometry):
            return False
        self.status_command.setText(
            "草图尚未提交：请先完成草图或取消草稿，再保存、切换或关闭文档。"
        )
        draft.status_label.setText(self.status_command.text())
        return True

    def _confirm_unsaved_changes(self, *, on_saved: Callable[[], object] | None = None) -> bool:
        """放行或保留当前文档；异步保存成功后通过 on_saved 继续原操作。"""
        if self._has_unsubmitted_geometry(include_sketch=False):
            return False
        has_draft = self._has_unsubmitted_sketch()
        if not has_draft and (self._loaded is None or not self._loaded.document.is_dirty):
            return True
        choice = self._ask_save_dialog()
        if choice == "save":
            return self._save_document(on_saved=on_saved)
        if choice == "discard" and has_draft and self._sketch_dialog is not None:
            self._sketch_dialog.reject()
        return choice == "discard"

    def _ask_save_dialog(self) -> str:
        """三选弹窗：save/discard/cancel；exec 阻塞至用户选择。"""
        box = QMessageBox(self)
        box.setWindowTitle("未保存的修改")
        box.setText("当前文档或草图有未保存的修改。保存将先提交已完成的草图。")
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
        summary = message if len(message) <= 200 else message[:200] + "…"
        self.status_command.setText(summary)
        self.information_tab.append_message(message)
        box = QMessageBox(self)
        box.setObjectName("errorMessage")
        box.setWindowTitle("错误")
        box.setText(summary)
        box.show()

    def _replace_document(self, loaded: LoadedDocument, path: Path | None) -> None:
        """单文档替换语义（A4）：整面重绑 + 重置草稿 + 记住存档路径。"""
        self._document_path = path
        self.bind_document(loaded)
        self._show_document_path(path)
        if self._services is not None:
            self.plan_draft = PlanDraftController(self._services.registry)
            if self.right_panel is not None:
                self.right_panel.bind_draft(self.plan_draft)
            if self.plan_cards is not None:
                self.plan_cards.bind_draft(self.plan_draft)
        if loaded.document.document_type == "drawing2d":
            self._on_sketch_start()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.execution_unit is not None and self.execution_unit.is_notifying_result:
            self._session_close_waiting = True
            self.status_command.setText("操作结果处理完成后关闭窗口。")
            event.ignore()
            return
        if self.history_edit_task is not None:
            self.status_command.setText("请先完成或取消历史编辑，再关闭窗口。")
            event.ignore()
            return
        if self.history_repair_task is not None:
            self.status_command.setText("请先完成或取消历史修复，再关闭窗口。")
            event.ignore()
            return
        if self.bound_hole_task is not None:
            self.status_command.setText("请先完成或取消绑定孔，再关闭窗口。")
            event.ignore()
            return
        if self.part_sketch_task is not None and self.part_sketch_task.has_draft:
            self.status_command.setText("请先完成或取消零件草图，再关闭窗口。")
            event.ignore()
            return
        if self.part_sketch_task is not None:
            self.part_sketch_task.reject()
        if self.execution_unit is not None and self.execution_unit.is_busy:
            self.status_command.setText("操作完成前无法关闭窗口")
            self._session_close_waiting = self._session_close_approved
            event.ignore()
            return
        self._session_close_waiting = False
        if self.document_session is not None and not self._session_close_approved:
            self._refresh_document_choice()
            pending = tuple(e for e in self.document_session.documents if e.needs_save)
            if pending:
                choices = self._ask_session_close_dialog(pending)
                if choices is None or any(
                    choices.get(e.loaded.document.document_id) not in ("save", "discard")
                    for e in pending
                ):
                    event.ignore()
                    return
                selected = tuple(
                    e for e in pending if choices[e.loaded.document.document_id] == "save"
                )
                if selected and self.document_saver is not None:

                    def finished(success: bool) -> None:
                        if success:
                            self._session_close_approved = True
                            QTimer.singleShot(0, self.close)

                    self.document_saver.save_many(selected, on_complete=finished)
                    event.ignore()
                    return
            self._session_close_approved = True
        if self.document_session is None and not self._confirm_unsaved_changes(on_saved=self.close):
            event.ignore()
            return
        if self.datum_task is not None:
            self.datum_task.reject()
        if self.bound_hole_task is not None:
            self.bound_hole_task.reject()
        if self.execution_unit is not None:
            self.execution_unit.shutdown()
        self.drawing_workbench.shutdown()
        if self.document_session is not None:
            for entry in self.document_session.documents:
                if entry.workbench is not None and entry.workbench is not self.drawing_workbench:
                    entry.workbench.shutdown()
        if self.viewport is not None:
            self.viewport.dispose()
        if self._home_visibility is not None:
            self._show_session_workspace()
        self.store_window_state()
        super().closeEvent(event)
