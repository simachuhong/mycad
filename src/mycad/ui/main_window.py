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

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from functools import partial
from math import atan2, cos, degrees, hypot, isfinite, radians, remainder, sin
from pathlib import Path
from typing import TYPE_CHECKING, cast, override
from uuid import uuid4
from weakref import WeakValueDictionary

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
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
from mycad.core.associative_array import (
    ArrayBasePoint,
    ArrayEntityRef,
    ArrayExtraOutput,
    ArrayMember,
    ArrayReplacement,
    AssociativeRectArray,
    array_member_rotation_anchor,
    erase_drawing_entities,
    has_interleaved_array_dependencies,
    has_internal_replacements,
    propagate_array_changes,
    strip_erased_member_dimensions,
)
from mycad.core.bus import CommandBus
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    DraftTangentPair,
    RectangleTransformEvidence,
    draft_tangent_reference,
    project_coplanar_entity,
    project_coplanar_rotation,
    project_coplanar_vector,
    project_polyline_entity,
    project_tangent_entity,
    rebind_committed_tangencies,
    rebind_committed_tangencies_for_edit,
    rebind_retained_local_tangencies,
    rebind_unchanged_user_polyline_constraints,
    resolve_tangency_component,
    split_transform_evidence,
    unique_split_arc_relation_fragment,
    unique_split_line_relation_fragment,
)
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.document import AFFECTED_OBJECTS
from mycad.core.document_kinds import (
    DRAWING2D_COMMAND_IDS,
    NATIVE_ARCHIVE_SUFFIXES,
    DocumentKind,
    DocumentType,
)
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import (
    DrawingText,
    TextStyleTable,
    mirror_text,
    move_text,
    rotate_text,
    scale_text,
    text_style_geometry_signature,
)
from mycad.core.exceptions import InvalidHistoryError, MycadError, ValidationError
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.core.identity import BodyId
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.plan import Plan
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet, ReplayEdit
from mycad.core.signals import SignalName
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SketchSupportFace,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_edit import (
    copy_entities,
    mirror_entities,
    move_entities,
    rotate_entities,
    scale_entities,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable, merge_layer_tables
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference
from mycad.core.text_interchange import reconcile_text_style_ids
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
from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog, tangent_preview_summary
from mycad.ui.datum_task import DatumTaskDialog
from mycad.ui.dimension_tools import DEFAULT_NEW_DRAWING_DIMENSION_SCALE
from mycad.ui.document_save import DocumentSaveController, SaveResult
from mycad.ui.document_session import DEFAULT_NAMES, DocumentSession, SessionDocument
from mycad.ui.drawing_clipboard import (
    DRAWING_CLIPBOARD_MIME,
    DRAWING_MIXED_CLIPBOARD_MIME,
    DRAWING_RASTER_GROUP_MIME,
    reconcile_clipboard_styles,
)
from mycad.ui.drawing_dimension_styles import DrawingDimensionStylesDialog
from mycad.ui.drawing_templates import DrawingTemplateChoiceDialog
from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME, DrawingTextTools
from mycad.ui.drawing_workbench import DrawingWorkbench
from mycad.ui.dxf_import_identity import remap_colliding_curves, remap_datum_labels
from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.fillet_toolbar import FilletCommandBar
from mycad.ui.geometric_tolerance_tools import TOLERANCE_CLIPBOARD_MIME
from mycad.ui.history_repair_task import HistoryRepairTask
from mycad.ui.modeling_handles import DimensionHandle
from mycad.ui.modeling_toolbar import ModelingCommandBar
from mycad.ui.new_document_dialog import NewDocumentDialog
from mycad.ui.part_sketch_workbench import PartSketchWorkbench
from mycad.ui.path_identity import path_identity
from mycad.ui.plan_cards import PlanCards
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.preferences import (
    CONSTRAINT_MARKERS_KEY,
    CURSOR_STYLE_KEY,
    DATUM_SYMBOL_STYLE_KEY,
    CursorSettingsDialog,
    default_datum_symbol_style,
    drawing_constraint_markers_visible,
    drawing_cursor_style,
)
from mycad.ui.quick_access import QuickAccessController, QuickAccessDialog, QuickAccessStore
from mycad.ui.recent_documents import RecentDocuments
from mycad.ui.ribbon import RibbonGroup, RibbonPage
from mycad.ui.right_panel import HistoryEditDialog, RightPanel
from mycad.ui.sketch_constraint_dialog import SketchConstraintDialog
from mycad.ui.sketch_editor import (
    MixedMoveState,
    SavedHandlePreview,
    SketchCanvas,
    SketchEditorDialog,
    rebind_pending_saved_sources,
)
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
from mycad.ui.workspace_console import (
    AiChatPanel,
    InformationPanel,
    MessageLabel,
    WorkspaceConsole,
    drawing_message,
)
from mycad.ui.workspace_layout import WorkspaceLayoutStore
from mycad.ui.workspace_tabs import WorkspaceId, WorkspaceTabs

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
    from mycad.core.drawing_groups import DrawingObjectRef
    from mycad.ui.drawing_block_editor import DrawingBlockEditorDialog
    from mycad.ui.drawing_collection_session import (
        DrawingCollectionAffinePreview,
        DrawingCollectionCheckpoint,
        DrawingCollectionMirrorPreview,
        DrawingCollectionPastePreview,
        DrawingCollectionSession,
        DrawingCollectionTransformPreview,
    )

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
SETTINGS_KEY_EDGE_MODE = "drawing2d/edgeMode"
SETTINGS_KEY_OFFSET_GAP_TYPE = "drawing2d/offsetGapType"
SETTINGS_KEY_CORNER_TRIM = "drawing2d/cornerTrim"
SETTINGS_KEY_TRIM_STANDARD = "drawing2d/trimStandard"
SETTINGS_KEY_PROJECTION_MODE = "drawing2d/projectionMode"

APP_VERSION = "0.1.0"


def _dimensions_have_unselected_tolerance_attachment(
    sketches: Sequence[Sketch],
    frames: Sequence[FeatureControlFrame],
    datums: Sequence[DatumIdentifier],
    dimension_ids: set[str],
    selected_annotations: set[str],
) -> bool:
    selected_dimensions = {
        (sketch.sketch_id, constraint.constraint_id)
        for sketch in sketches
        for constraint in sketch.constraints
        if constraint.constraint_id in dimension_ids
    }
    for annotation in (*frames, *datums):
        if isinstance(annotation, FeatureControlFrame):
            identity, attachment = annotation.frame_id, annotation.leader_annotation_attachment
        else:
            identity, attachment = annotation.datum_id, annotation.annotation_attachment
        if (
            identity not in selected_annotations
            and attachment is not None
            and attachment.kind == "sketch_dimension"
            and (attachment.sketch_id, attachment.object_id) in selected_dimensions
        ):
            return True
    return False


def _staged_committed_tangencies(
    original: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    steps: Sequence[tuple[tuple[Sketch, ...], tuple[RectangleTransformEvidence, ...]]],
) -> tuple[CrossSketchTangency, ...]:
    previous = original
    for saved, transforms in steps:
        surviving = {
            (sketch.sketch_id, entity.entity_id) for sketch in saved for entity in sketch.entities
        }
        relevant_transforms = tuple(
            item
            for item in transforms
            if item.reference.sketch_id in {sketch.sketch_id for sketch in saved}
        )
        rectangle_proofs, polyline_proofs, line_proofs = split_transform_evidence(
            previous, relevant_transforms
        )
        relations = rebind_committed_tangencies(
            previous,
            saved,
            tuple(
                relation
                for relation in relations
                if all(
                    (ref.sketch_id, ref.entity_id) in surviving
                    for ref in (relation.first, relation.second)
                )
            ),
            rectangle_proofs,
            polyline_proofs,
            line_proofs,
            allow_extended_segments=True,
            allow_extended_arcs=True,
            allow_retained_tangent_arcs=True,
            allow_retained_tangent_lines=True,
            allow_retained_tangent_fragments=True,
        )
        previous = saved
    return relations


@dataclass(frozen=True, slots=True)
class _DxfUnitPrompt:
    message: str


@dataclass(frozen=True, slots=True)
class _SketchConstraintPreview:
    solve_result: SketchConstraintSolveResult
    viewport: ViewportData | None = None
    sketches: tuple[ViewportSketchData, ...] = ()
    linked_sketches: tuple[Sketch, ...] = ()


@dataclass(frozen=True, slots=True)
class _MixedHandleContext:
    previous: MixedMoveState | None
    original_saved: tuple[Sketch, ...]
    current_saved: tuple[Sketch, ...]
    original_draft: Sketch
    draft: Sketch
    background: tuple[tuple[SketchEntity, SketchLayer], ...]
    pairs: tuple[DraftTangentPair, ...]
    history: tuple[tuple[tuple[Sketch, ...], Sketch, tuple[DraftTangentPair, ...]], ...]
    history_position: int
    arrays: tuple[AssociativeRectArray, ...]
    array_history: tuple[tuple[AssociativeRectArray, ...], ...]
    transform_history: tuple[tuple[RectangleTransformEvidence, ...], ...]


@dataclass(frozen=True, slots=True)
class _DraftTangencyPreview:
    relation: CrossSketchTangency
    context: _MixedHandleContext
    state: MixedMoveState
    solved_draft: Sketch
    pair: DraftTangentPair
    revision: int


@dataclass(frozen=True, slots=True)
class _CollectionTangencyPreview:
    relation: CrossSketchTangency
    session: DrawingCollectionSession
    checkpoint: DrawingCollectionCheckpoint
    operation: ReplayAppend


@dataclass
class _PreparedSketchSave:
    entry: SessionDocument
    loaded: LoadedDocument
    draft: SketchEditorDialog
    checkpoint: str
    source_revision: int
    prepared_revision: int
    checkpoint_restored: bool = False
    collection_restored: bool = False


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
        self._offset_default_distance = -1.0
        self._chamfer_method_angle = False
        self._busy_action_states: dict[QAction, bool] = {}
        self._loaded: LoadedDocument | None = None
        self._collection_clipboard_documents: WeakValueDictionary[str, LoadedDocument] = (
            WeakValueDictionary()
        )
        self._sketch_dialog: SketchEditorDialog | None = None
        self._block_editor: DrawingBlockEditorDialog | None = None
        self._mixed_history_pending = False
        self.part_sketch_task: PartSketchWorkbench | None = None
        self._preferred_part_sketch: tuple[LoadedDocument, str] | None = None
        self._preferred_part_region: tuple[LoadedDocument, str, tuple[str, ...]] | None = None
        self.datum_task: DatumTaskDialog | None = None
        self.bound_hole_task: BoundHoleTask | None = None
        self.history_repair_task: HistoryRepairTask | None = None
        self.history_edit_task: HistoryEditDialog | None = None
        self._history_display_candidate: mycad_app.ReplayCandidateSession | None = None
        self._history_display_snapshot: ViewportData | None = None
        self._pending_history_discards: list[mycad_app.ReplayCandidateSession] = []
        self._history_discard_timer = QTimer(self)
        self._history_discard_timer.setSingleShot(True)
        self._history_discard_timer.timeout.connect(self._flush_history_discards)
        self._after_sketch_commit: Callable[[], None] | None = None
        self._prepared_sketch_save: _PreparedSketchSave | None = None
        self._after_sketch_failure: Callable[[], None] | None = None
        self.new_document_dialog: NewDocumentDialog | None = None
        self._sketch_dock_visibility: tuple[bool, bool] | None = None
        self._drafting_toolbar_state: QByteArray | None = None
        self._modeling_toolbar_was_visible = False
        self._sketch_constraint_dialog: SketchConstraintDialog | None = None
        self._sketch_constraint_preview_revision: int | None = None
        self._cross_tangency_dialog: CrossSketchTangencyDialog | None = None
        self._cross_tangency_preview: (
            tuple[CrossSketchTangency, tuple[Sketch, ...], tuple[Sketch, ...], int]
            | _DraftTangencyPreview
            | _CollectionTangencyPreview
            | None
        ) = None
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
            ("edit.copy", self.act_copy),
            ("edit.paste", self.act_paste),
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
            viewport.selection_filter_changed.connect(self._sync_selection_filter_action)
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
        self._sync_session_document_actions()
        if self.document_session is not None:
            self._sync_workspace_actions()
        QApplication.clipboard().dataChanged.connect(self._sync_drawing_clipboard_actions)
        if self.document_session is not None:
            self.document_saver = DocumentSaveController(
                self.document_session,
                prepare=self._prepare_session_document,
                choose_path=self._choose_session_save_path,
                changed=self._session_save_changed,
                report=self._report_session_save,
                settle=self._settle_session_save,
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
        redo_shortcut = QKeySequence("Ctrl+Y")
        self._set_action_shortcut(self.act_redo, redo_shortcut)
        platform_redo = QKeySequence(QKeySequence.StandardKey.Redo)
        if platform_redo != redo_shortcut:
            self.act_redo.setShortcuts([redo_shortcut, platform_redo])
        self.act_redo.triggered.connect(self.request_redo)
        self.act_copy = self.menu_edit.addAction("复制")
        self._set_action_shortcut(self.act_copy, QKeySequence(QKeySequence.StandardKey.Copy))
        self.act_copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_copy.triggered.connect(self._copy_drawing_selection)
        self.act_paste = self.menu_edit.addAction("粘贴")
        self._set_action_shortcut(self.act_paste, QKeySequence(QKeySequence.StandardKey.Paste))
        self.act_paste.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_paste.triggered.connect(self._paste_drawing_selection)
        self.menu_edit.aboutToShow.connect(self._sync_drawing_clipboard_actions)
        self.act_copy.setEnabled(False)
        self.act_paste.setEnabled(False)
        self.act_delete = self.menu_edit.addAction("删除")
        self.act_delete.triggered.connect(self._delete_drawing_selection)
        self.drawing_group_menu = self.menu_edit.addMenu("二维组")
        self.act_drawing_group = self.drawing_group_menu.addAction("编组")
        self.act_drawing_ungroup = self.drawing_group_menu.addAction("解组")
        self.act_drawing_group_edit = self.drawing_group_menu.addAction("组管理")
        self.act_drawing_group.triggered.connect(lambda: self._run_drawing_group_menu("group"))
        self.act_drawing_ungroup.triggered.connect(lambda: self._run_drawing_group_menu("ungroup"))
        self.act_drawing_group_edit.triggered.connect(lambda: self._run_drawing_group_menu("edit"))
        self.drawing_group_menu.setEnabled(False)
        self.menu_edit.aboutToShow.connect(self._sync_drawing_group_menu)
        self.drawing_block_menu = self.menu_edit.addMenu("二维块")
        self.act_drawing_block_create = self.drawing_block_menu.addAction("创建块")
        self.act_drawing_block_insert = self.drawing_block_menu.addAction("插入块")
        self.act_drawing_block_explode = self.drawing_block_menu.addAction("分解块")
        self.act_drawing_block_edit = self.drawing_block_menu.addAction("编辑块定义")
        self.act_drawing_block_manage = self.drawing_block_menu.addAction("管理块定义")
        self.act_drawing_block_library = self.drawing_block_menu.addAction("块库")
        self.act_drawing_block_create.triggered.connect(
            lambda: self._run_drawing_block_menu("create")
        )
        self.act_drawing_block_insert.triggered.connect(
            lambda: self._run_drawing_block_menu("insert")
        )
        self.act_drawing_block_explode.triggered.connect(
            lambda: self._run_drawing_block_menu("explode")
        )
        self.act_drawing_block_edit.triggered.connect(lambda: self._run_drawing_block_menu("edit"))
        self.act_drawing_block_manage.triggered.connect(
            lambda: self._run_drawing_block_menu("manage")
        )
        self.act_drawing_block_library.triggered.connect(
            lambda: self._run_drawing_block_menu("library")
        )
        self.drawing_block_menu.setEnabled(False)
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
        self.act_cross_sketch_tangency = self.menu_feature.addAction("对象相切")
        self.act_cross_sketch_tangency.setEnabled(self._services is not None)
        self.act_cross_sketch_tangency.triggered.connect(self._on_cross_sketch_tangency)
        self.act_manage_tangencies = self.menu_feature.addAction("相切选项")
        self.act_manage_tangencies.setEnabled(self._services is not None)
        self.act_manage_tangencies.setToolTip("通过列表预览对象相切并查看可用关系。")
        self.act_manage_tangencies.triggered.connect(
            lambda: self._on_cross_sketch_tangency(force_dialog=True)
        )
        self.act_remove_associative_array = self.menu_feature.addAction("解除矩形阵列关联")
        self.act_remove_associative_array.setEnabled(self._services is not None)
        self.act_remove_associative_array.triggered.connect(self._remove_selected_associative_array)
        self.act_edit_associative_array = self.menu_feature.addAction("修改矩形阵列间距")
        self.act_edit_associative_array.setEnabled(self._services is not None)
        self.act_edit_associative_array.triggered.connect(self._edit_selected_associative_array)
        self.act_resize_associative_array = self.menu_feature.addAction("修改矩形阵列数量")
        self.act_resize_associative_array.setEnabled(self._services is not None)
        self.act_resize_associative_array.triggered.connect(self._resize_selected_associative_array)
        self.act_rotate_associative_array = self.menu_feature.addAction("修改矩形阵列方向")
        self.act_rotate_associative_array.setEnabled(self._services is not None)
        self.act_rotate_associative_array.triggered.connect(self._rotate_selected_associative_array)
        self.act_base_associative_array = self.menu_feature.addAction("修改矩形阵列基点")
        self.act_base_associative_array.setEnabled(self._services is not None)
        self.act_base_associative_array.triggered.connect(self._base_selected_associative_array)
        self.act_offset_associative_member = self.menu_feature.addAction("修改阵列成员位置偏移")
        self.act_offset_associative_member.setEnabled(self._services is not None)
        self.act_offset_associative_member.triggered.connect(
            self._offset_selected_associative_member
        )
        self.act_rotate_associative_member = self.menu_feature.addAction("旋转阵列成员")
        self.act_rotate_associative_member.setEnabled(self._services is not None)
        self.act_rotate_associative_member.triggered.connect(self._rotate_associative_member)
        self.act_replace_associative_member = self.menu_feature.addAction("替换阵列成员")
        self.act_replace_associative_member.setEnabled(self._services is not None)
        self.act_replace_associative_member.triggered.connect(self._replace_associative_member)
        self.act_replace_associative_cell = self.menu_feature.addAction("替换阵列单元")
        self.act_replace_associative_cell.setEnabled(self._services is not None)
        self.act_replace_associative_cell.triggered.connect(self._replace_associative_cell_members)
        self.act_reset_associative_offsets = self.menu_feature.addAction("重置阵列成员位置偏移")
        self.act_reset_associative_offsets.setEnabled(self._services is not None)
        self.act_reset_associative_offsets.triggered.connect(self._reset_associative_offsets)
        self.act_reset_associative_overrides = self.menu_feature.addAction("重置阵列成员覆盖")
        self.act_reset_associative_overrides.setEnabled(self._services is not None)
        self.act_reset_associative_overrides.triggered.connect(self._reset_associative_overrides)

        self.menu_tools = self.menuBar().addMenu("工具")
        self.act_options = self.menu_tools.addAction("系统设置…")
        self.act_options.triggered.connect(self._show_options)
        self.act_units = self.menu_tools.addAction("单位")
        self.act_units.triggered.connect(self._show_units)
        self.act_text = self.menu_tools.addAction("单行文字 TEXT")
        self.act_mtext = self.menu_tools.addAction("多行文字 MTEXT")
        self.act_text_style = self.menu_tools.addAction("文字样式 STYLE…")
        self.act_text.triggered.connect(lambda: self._start_drawing_text("text"))
        self.act_mtext.triggered.connect(lambda: self._start_drawing_text("mtext"))
        self.act_text_style.triggered.connect(lambda: self._start_drawing_text("style"))
        self.act_drawing_dimension_styles = self.menu_tools.addAction("标注样式…")
        self.act_drawing_dimension_styles.setEnabled(False)
        self.act_drawing_dimension_styles.triggered.connect(self._show_drawing_dimension_styles)
        self.act_geometric_tolerance = self.menu_tools.addAction("形位公差…")
        self.act_datum_label = self.menu_tools.addAction("基准标识…")
        self.act_datum_symbol_style = self.menu_tools.addAction("基准标识样式…")
        self.menu_default_datum_style = self.menu_tools.addMenu("新建基准默认样式")
        default_group = QActionGroup(self)
        self.act_default_datum_rectangle = self.menu_default_datum_style.addAction(
            "矩形（设置为默认）"
        )
        self.act_default_datum_circle = self.menu_default_datum_style.addAction(
            "圆圈（设置为默认）"
        )
        for action in (self.act_default_datum_rectangle, self.act_default_datum_circle):
            action.setCheckable(True)
            default_group.addAction(action)
        self.act_default_datum_rectangle.triggered.connect(
            lambda: self._set_default_datum_style("rectangle")
        )
        self.act_default_datum_circle.triggered.connect(
            lambda: self._set_default_datum_style("circle")
        )
        self.menu_default_datum_style.aboutToShow.connect(self._sync_default_datum_style)
        self._sync_default_datum_style()
        self.act_datum_text_style = self.menu_tools.addAction("基准文字样式…")
        self.act_datum_arrow_style = self.menu_tools.addAction("基准主引线箭头样式…")
        self.act_geometric_tolerance.setEnabled(False)
        self.act_datum_label.setEnabled(False)
        self.act_datum_symbol_style.setEnabled(False)
        self.act_datum_text_style.setEnabled(False)
        self.act_datum_arrow_style.setEnabled(False)
        self.act_geometric_tolerance.triggered.connect(self._start_geometric_tolerance)
        self.act_datum_label.triggered.connect(self._start_datum_label)
        self.act_datum_symbol_style.triggered.connect(self._edit_datum_symbol_style)
        self.act_datum_text_style.triggered.connect(self._edit_datum_text_style)
        self.act_datum_arrow_style.triggered.connect(self._edit_datum_arrow_style)
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
            self.act_geometric_tolerance: "geometric-tolerance",
            self.act_datum_label: "datum-identifier",
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
        preparation = self._prepared_sketch_save
        if preparation is not None and preparation.loaded is self._loaded:
            self.status_command.setText("保存恢复尚未完成；原草稿已保留，请先处理保存错误。")
            return
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
            if self._sketch_dialog.canvas.select_committed_entities:
                self._sketch_dialog.canvas.set_crosshair_style(
                    drawing_cursor_style(QSettings(ORG_NAME, APP_NAME))
                )
                self._sketch_dialog.canvas.set_constraint_markers_visible(
                    drawing_constraint_markers_visible(QSettings(ORG_NAME, APP_NAME))
                )
            self._show_sketch_workbench(self._sketch_dialog)
            return
        sketch_document = self._loaded.document
        dialog = SketchEditorDialog(
            self,
            can_finish=lambda: (
                self.execution_unit is not None
                and not (self.execution_unit.is_busy or self.execution_unit.is_notifying_result)
            ),
            drag_preview=self._services.kernel.preview_sketch_drag,
            continuous_lines=True,
            select_committed_entities=self._loaded.document.document_type == "drawing2d",
            document_metadata=(lambda: sketch_document.metadata)
            if sketch_document.document_type == "drawing2d"
            else None,
            constraint_preview=self._services.kernel.preview_sketch_constraint,
            constraint_update_preview=self._services.kernel.preview_sketch_constraint_update,
            measure_planar_region=self._services.kernel.measure_planar_region,
            offset_closed_path=self._services.kernel.offset_closed_path,
            offset_spline=self._services.kernel.offset_spline,
            offset_ellipse=self._services.kernel.offset_ellipse,
            offset_spline_path=self._services.kernel.offset_spline_path,
        )
        if self._loaded.document.document_type == "drawing2d":
            dialog.canvas.set_drawing_theme(self._theme_name)
            dialog.canvas.set_crosshair_style(drawing_cursor_style(QSettings(ORG_NAME, APP_NAME)))
            dialog.canvas.set_constraint_markers_visible(
                drawing_constraint_markers_visible(QSettings(ORG_NAME, APP_NAME))
            )
            radius_document = self._loaded
            radius_services = self._services
            dialog.canvas.drawing_dimension_styles = radius_services.kernel.drawing_dimension_styles
            dialog.dimensions.set_drawing_style_manager(
                lambda: self._open_drawing_dimension_styles(dialog)
            )
            if any(
                command.id == "drawing.dimension_styles.set" or "clipboard_styles" in command.params
                for command in radius_document.document.commands
            ):
                dialog.dimensions.set_drawing_style(
                    radius_services.kernel.drawing_dimension_styles.current
                )
            dialog.canvas.circle_fillet_radius = radius_services.kernel.drawing_fillet_radius
            dialog.canvas.sync_chamfer_values(radius_services.kernel.drawing_chamfer_values)

            def persist_fillet_radius(radius: float) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；圆角半径未修改。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；圆角半径未修改。")
                try:
                    radius_document.bus.execute(
                        "drawing.fillet_radius.set", {"radius": radius}, "local", version=1
                    )
                except MycadError as exc:
                    raise ValueError(f"圆角半径保存失败：{exc}") from exc
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()

            dialog.canvas.persist_fillet_radius = persist_fillet_radius

            def persist_chamfer_values(values: tuple[float, float, float, float]) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；倒角参数未修改。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；倒角参数未修改。")
                try:
                    radius_document.bus.execute(
                        "drawing.chamfer_values.set",
                        dict(
                            zip(
                                ("distance_first", "distance_second", "angle_length", "angle"),
                                values,
                                strict=True,
                            )
                        ),
                        "local",
                        version=1,
                    )
                except MycadError as exc:
                    raise ValueError(f"倒角参数保存失败：{exc}") from exc
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()

            dialog.canvas.persist_chamfer_values = persist_chamfer_values

            def import_clipboard_layers(
                layers: SketchLayerTable,
                styles: DimensionStyleTable | None,
                text_styles: TextStyleTable | None,
            ) -> Callable[[bool], None]:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；剪贴板图层未导入。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；请稍后粘贴。")
                checkpoint = radius_document.bus.create_save_checkpoint()
                position = dialog.canvas.history_position
                source_revision = radius_document.document.revision
                try:
                    params: dict[str, object] = {
                        "layers": layers.to_mapping(),
                        "dimension_layer": radius_services.kernel.dimension_layer,
                        "assignments": [],
                    }
                    command = "drawing.layers.set"
                    if styles is not None and (
                        styles != radius_services.kernel.drawing_dimension_styles
                        or (
                            text_styles is not None
                            and text_styles != radius_services.kernel.drawing_text_styles
                        )
                    ):
                        command = "drawing.clipboard.prepare"
                        params["clipboard_styles"] = styles.to_mapping()
                        if (
                            text_styles is not None
                            and text_styles != radius_services.kernel.drawing_text_styles
                        ):
                            params["clipboard_text_styles"] = text_styles.to_mapping()
                    if (
                        command == "drawing.clipboard.prepare"
                        and radius_document.document.archive_version < 8
                    ):
                        candidate = mycad_app.create_replay_candidate(
                            radius_services, radius_document, session_identity=self._session_id
                        )
                        candidate.stage(
                            ReplayChangeSet(
                                (),
                                (
                                    ReplayAppend(
                                        command,
                                        radius_services.registry.get(command).version,
                                        params,
                                        "local",
                                    ),
                                ),
                                False,
                                8,
                            ),
                            current_session_identity=self._session_id,
                        )
                        preview = candidate.preview(current_session_identity=self._session_id)
                        if preview.state != "succeeded":
                            raise ValueError(str(preview.failure or "剪贴板图层及样式预览失败"))
                        candidate.commit(
                            candidate.authorize_commit(current_session_identity=self._session_id),
                            current_session_identity=self._session_id,
                        )
                    else:
                        radius_document.bus.execute(
                            command,
                            params,
                            "local",
                            version=radius_services.registry.get(command).version,
                        )
                except (MycadError, ValueError) as exc:
                    radius_document.bus.release_save_checkpoint(checkpoint)
                    raise ValueError(f"无法导入剪贴板图层：{exc}") from exc
                revision = radius_document.document.revision
                dialog.canvas.acknowledge_fillet_setting_revision(source_revision, revision)
                self._sync_drawing_layers()

                def finish(accepted: bool) -> None:
                    if accepted:
                        dialog.canvas.rebase_mixed_layers(radius_services.kernel.sketches, layers)
                        radius_document.bus.release_save_checkpoint(checkpoint)
                        count = radius_document.document.command_count
                        dialog.layer_history_boundaries[count] = dialog.canvas.history_position
                        dialog.mixed_draft_history[count] = (
                            position,
                            dialog.canvas.history_position,
                            radius_document.document.commands[-1].instance_id,
                        )
                        dialog.layer_history_redo.clear()
                        dialog.canvas.discard_redo_history()
                    else:
                        radius_document.bus.restore_save_checkpoint(
                            checkpoint, expected_revision=revision
                        )
                        dialog.canvas.acknowledge_fillet_setting_revision(
                            revision, radius_document.document.revision
                        )
                        self._sync_drawing_layers()

                return finish

            dialog.canvas.import_clipboard_layers = import_clipboard_layers

            def stage_rasters(action: str, rasters: tuple[DrawingRaster, ...]) -> bool:
                if action != "add":
                    self._reject_group_member_edit(
                        dialog, {("raster", raster.image_id) for raster in rasters}
                    )
                session = dialog.canvas.collection_session
                if session is None:
                    return False
                params: dict[str, object] = (
                    {"action": action, "image_ids": [item.image_id for item in rasters]}
                    if action == "remove"
                    else {
                        "action": action,
                        "images": [item.to_mapping(version=2) for item in rasters],
                    }
                )
                if not dialog.canvas.stage_collection_operation(
                    ReplayAppend("drawing.raster.batch", 2, params, "local")
                ):
                    raise ValueError(dialog.canvas.message)
                return True

            def commit_clipboard_raster(raster: DrawingRaster) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；图片未粘贴。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；请稍后粘贴。")
                if stage_rasters("add", (raster,)):
                    return
                mixed = dialog.canvas.mixed_move
                if mixed is not None and (
                    not dialog.canvas.mixed_move_is_valid
                    or mixed.source_revision != radius_document.document.revision
                ):
                    raise ValueError("暂存编辑已过期；请先撤销后再粘贴图片。")
                previous_revision = radius_document.document.revision
                try:
                    radius_document.bus.execute(
                        "drawing.raster.add", raster.to_mapping(version=2), "local", version=3
                    )
                except MycadError as exc:
                    raise ValueError(f"无法粘贴图片：{exc}") from exc
                if mixed is not None:
                    dialog.canvas.rebind_restored_source(
                        previous_revision, radius_document.document.revision
                    )
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()
                self._sync_drawing_layers()

            dialog.canvas.commit_clipboard_raster = commit_clipboard_raster

            def commit_mixed_clipboard(
                sketch: Sketch,
                images: tuple[DrawingRaster, ...],
                styles: DimensionStyleTable | None,
                text_styles: TextStyleTable | None,
            ) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；对象未粘贴。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；请稍后粘贴。")
                if (
                    dialog.canvas.mixed_move is not None
                    or dialog.canvas.pending_cross_tangencies
                    or dialog.canvas.pending_associative_arrays
                ):
                    raise ValueError("请先完成或撤销当前暂存关联编辑。")
                names = {entity.layer_name for entity in sketch.entities}
                names.update(image.layer_name for image in images)
                names.update(c.layer_name for c in sketch.constraints if c.layer_name is not None)
                for name in names:
                    try:
                        layer = radius_services.kernel.drawing_layers.get(name)
                    except KeyError:
                        layer = sketch.layers.get(name)
                    if layer.locked or not layer.displayed:
                        raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
                params = sketch.to_state_mapping()
                params["raster_batch"] = {
                    "action": "add",
                    "images": [image.to_mapping(version=2) for image in images],
                }
                if styles is not None and (
                    styles != radius_services.kernel.drawing_dimension_styles
                    or (
                        text_styles is not None
                        and text_styles != radius_services.kernel.drawing_text_styles
                    )
                ):
                    params["clipboard_styles"] = styles.to_mapping()
                    if (
                        text_styles is not None
                        and text_styles != radius_services.kernel.drawing_text_styles
                    ):
                        params["clipboard_text_styles"] = text_styles.to_mapping()
                version = (
                    57
                    if any(
                        isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids
                        for entity in sketch.entities
                    )
                    else 56
                )
                try:
                    if radius_document.document.archive_version < 8:
                        candidate = mycad_app.create_replay_candidate(
                            radius_services, radius_document, session_identity=self._session_id
                        )
                        candidate.stage(
                            ReplayChangeSet(
                                (),
                                (ReplayAppend("sketch.create", version, params, "local"),),
                                False,
                                8,
                            ),
                            current_session_identity=self._session_id,
                        )
                        preview = candidate.preview(current_session_identity=self._session_id)
                        if preview.state != "succeeded":
                            raise ValueError(str(preview.failure or "剪贴板对象预览失败"))
                        candidate.commit(
                            candidate.authorize_commit(current_session_identity=self._session_id),
                            current_session_identity=self._session_id,
                        )
                    else:
                        radius_document.bus.execute(
                            "sketch.create", params, "local", version=version
                        )
                except (MycadError, ValueError) as exc:
                    raise ValueError(f"无法粘贴对象：{exc}") from exc
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()
                self._sync_drawing_layers()

            dialog.canvas.commit_mixed_clipboard = commit_mixed_clipboard

            def ensure_raster_source_current(action: str) -> None:
                revision = dialog.canvas.source_context_revision
                if (
                    action != "add"
                    and revision is not None
                    and revision != radius_document.document.revision
                ):
                    self._sync_drawing_layers()
                    raise ValueError("图纸已变化，请重新选择图片。")

            def commit_raster_edit(action: str, raster: DrawingRaster) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；图片未修改。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；请稍后重试。")
                if dialog.canvas.mixed_move is not None:
                    raise ValueError("请先完成或撤销当前暂存编辑。")
                ensure_raster_source_current(action)
                layer = dialog.canvas.layer_table.get(raster.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("图片所在图层已锁定或隐藏。")
                if stage_rasters(action, (raster,)):
                    return
                params = (
                    {"image_id": raster.image_id}
                    if action == "remove"
                    else raster.to_mapping(version=2)
                )
                try:
                    radius_document.bus.execute(
                        f"drawing.raster.{action}",
                        params,
                        "local",
                        version=2 if action == "remove" else 3,
                    )
                except MycadError as exc:
                    raise ValueError(f"无法修改图片：{exc}") from exc
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()
                self._sync_drawing_layers()

            dialog.canvas.commit_raster_edit = commit_raster_edit

            def commit_raster_batch(action: str, rasters: tuple[DrawingRaster, ...]) -> None:
                if self._loaded is not radius_document or self._services is not radius_services:
                    raise ValueError("图纸已切换；图片未修改。")
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    raise ValueError("应用正在执行其他命令；请稍后重试。")
                if dialog.canvas.mixed_move is not None:
                    raise ValueError("请先完成或撤销当前暂存编辑。")
                ensure_raster_source_current(action)
                if not rasters:
                    raise ValueError("没有选择图片。")
                for raster in rasters:
                    layer = dialog.canvas.layer_table.get(raster.layer_name)
                    if layer.locked or not layer.displayed:
                        raise ValueError("图片所在图层已锁定或隐藏。")
                if stage_rasters(action, rasters):
                    return
                params = (
                    {"action": action, "image_ids": [item.image_id for item in rasters]}
                    if action == "remove"
                    else {
                        "action": action,
                        "images": [item.to_mapping(version=2) for item in rasters],
                    }
                )
                try:
                    radius_document.bus.execute("drawing.raster.batch", params, "local", version=2)
                except MycadError as exc:
                    raise ValueError(f"无法修改图片：{exc}") from exc
                dialog.layer_history_boundaries[radius_document.document.command_count] = (
                    dialog.canvas.history_position
                )
                dialog.layer_history_redo.clear()
                dialog.canvas.discard_redo_history()
                self._sync_drawing_layers()

            dialog.canvas.commit_raster_batch = commit_raster_batch

            def commit_mixed_draft_transform(
                entities: tuple[SketchEntity, ...], images: tuple[DrawingRaster, ...], action: str
            ) -> str | None:
                canvas = dialog.canvas
                if self._loaded is not radius_document or self._services is not radius_services:
                    canvas.message = "图纸已切换；对象未修改。"
                    canvas.changed.emit()
                    return None
                unit = self.execution_unit
                if unit is not None and (unit.is_busy or unit.is_notifying_result):
                    canvas.message = "应用正在执行其他命令；请稍后重试。"
                    canvas.changed.emit()
                    return None
                preserves_pending = action == "add" and canvas.draft_copy_preserves_sources(
                    entities
                )
                if canvas.mixed_move or (
                    (canvas.pending_cross_tangencies or canvas.pending_associative_arrays)
                    and not preserves_pending
                ):
                    canvas.message = "请先完成或撤销当前暂存关联编辑。"
                    canvas.changed.emit()
                    return None
                if canvas.source_context_revision != radius_document.document.revision:
                    canvas.message = "图纸已变化；请重新选择对象。"
                    canvas.changed.emit()
                    return None
                for image in images:
                    layer = canvas.layer_table.get(image.layer_name)
                    if layer.locked or not layer.displayed:
                        canvas.message = "图片所在图层隐藏或锁定。"
                        canvas.changed.emit()
                        return None
                checkpoint = radius_document.bus.create_save_checkpoint()
                before = canvas.history_position
                previous_layer_redo = list(dialog.layer_history_redo)
                try:
                    radius_document.bus.execute(
                        "drawing.raster.batch",
                        (
                            {"action": action, "image_ids": [image.image_id for image in images]}
                            if action == "remove"
                            else {
                                "action": action,
                                "images": [image.to_mapping(version=2) for image in images],
                            }
                        ),
                        "local",
                        version=2,
                    )
                except MycadError as exc:
                    radius_document.bus.release_save_checkpoint(checkpoint)
                    canvas.message = f"变换失败：{exc}"
                    canvas.changed.emit()
                    return None
                revision = radius_document.document.revision
                try:
                    applied = canvas.replace_draft_entities_atomically(
                        entities,
                        remove_dependent_constraints=action == "remove",
                        allow_satisfied_tangency=(
                            action == "update" and canvas.selected_user_tangencies_transformable()
                        ),
                    )
                    failure = canvas.message
                except Exception as exc:
                    applied = False
                    failure = f"草稿更新失败：{exc}"
                if not applied:
                    dialog.layer_history_redo[:] = previous_layer_redo
                    radius_document.bus.restore_save_checkpoint(
                        checkpoint, expected_revision=revision
                    )
                    canvas.cancel_transform()
                    self._sync_drawing_layers()
                    canvas.message = f"{failure}；操作已回滚。"
                    canvas.changed.emit()
                    return None
                radius_document.bus.release_save_checkpoint(checkpoint)
                count = radius_document.document.command_count
                dialog.layer_history_boundaries[count] = canvas.history_position
                dialog.mixed_draft_history[count] = (
                    before,
                    canvas.history_position,
                    radius_document.document.commands[-1].instance_id,
                )
                dialog.layer_history_redo.clear()
                self._sync_drawing_layers()
                return radius_document.document.commands[-1].instance_id

            dialog.canvas.commit_mixed_draft_transform = commit_mixed_draft_transform
        dialog.toolbar_host.statusBar().hide()
        dialog.status_label.text_changed.connect(partial(self._on_drafting_message, dialog, False))
        dialog.status_label.transient_changed.connect(
            partial(self._on_drafting_message, dialog, True)
        )
        dialog.document_layer_mode = True
        source_document = self._loaded.document
        array_services = self._services
        dialog.canvas.source_revision_provider = lambda: source_document.revision
        dialog.canvas.associative_arrays_provider = lambda: array_services.kernel.associative_arrays
        dialog.canvas.associative_sketches_provider = lambda: array_services.kernel.sketches
        dialog.canvas.associative_tangencies_provider = lambda: (
            array_services.kernel.cross_sketch_tangencies
        )

        def array_spacing_commit(
            token: object, array: object, row: object, column: object, revision: object
        ) -> None:
            self._on_array_spacing_grip_commit(
                dialog, self._session_id, token, array, row, column, revision
            )

        dialog.canvas.array_spacing_commit_requested.connect(array_spacing_commit)

        def array_count_commit(
            token: object, array: object, resized: object, revision: object
        ) -> None:
            self._on_array_count_grip_commit(
                dialog, self._session_id, token, array, resized, revision
            )

        dialog.canvas.array_count_commit_requested.connect(array_count_commit)

        def array_move_commit(
            token: object, array: object, displacement: object, revision: object
        ) -> None:
            self._on_array_move_grip_commit(
                dialog, self._session_id, token, array, displacement, revision
            )

        dialog.canvas.array_move_commit_requested.connect(array_move_commit)
        dialog.canvas.source_revision_invalidated.connect(
            lambda: self._sync_drawing_layers() if self._sketch_dialog is dialog else None
        )
        dialog.document_undo_requested.connect(self.request_undo)
        dialog.document_redo_requested.connect(self.request_redo)

        def committed_move(ids: object, delta: object) -> None:
            self._on_drawing_move(dialog, self._session_id, ids, delta)

        dialog.canvas.committed_move_requested.connect(committed_move)

        def committed_mixed_copy(ids: object, delta: object) -> None:
            self._on_drawing_move(dialog, self._session_id, ids, delta, copy_source=True)

        dialog.canvas.committed_mixed_copy_requested.connect(committed_mixed_copy)

        def committed_mixed_copy_array(ids: object, delta: object, count: int) -> None:
            self._on_drawing_move(
                dialog, self._session_id, ids, delta, copy_source=True, copy_count=count
            )

        dialog.canvas.committed_mixed_copy_array_requested.connect(committed_mixed_copy_array)

        def saved_handle_preview(
            token: object, reference: object, point: object, revision: object
        ) -> None:
            self._on_saved_handle_preview(
                dialog, self._session_id, token, reference, point, revision
            )

        def saved_handle_commit(token: object, preview: object, revision: object) -> None:
            self._on_saved_handle_commit(dialog, self._session_id, token, preview, revision)

        dialog.canvas.saved_handle_preview_requested.connect(saved_handle_preview)
        dialog.canvas.saved_handle_commit_requested.connect(saved_handle_commit)

        def saved_handle_cancelled() -> None:
            if (
                self.execution_unit is not None
                and self.execution_unit.is_busy
                and self.execution_unit.operation in ("saved-handle-preview", "saved-handle-commit")
            ):
                dialog.setEnabled(False)

        dialog.canvas.saved_handle_cancelled.connect(saved_handle_cancelled)
        dialog.canvas.mixed_handle_drag_enabled = True

        def committed_delete(ids: object) -> None:
            self._on_drawing_move(dialog, self._session_id, ids, (0.0, 0.0), erase=True)

        dialog.canvas.committed_delete_requested.connect(committed_delete)

        def committed_dimension_delete(ids: object) -> None:
            self._on_delete_drawing_dimensions(dialog, self._session_id, ids)

        dialog.canvas.committed_dimension_delete_requested.connect(committed_dimension_delete)

        def committed_line_edit(mode: object, identity: object, edited: object) -> None:
            self._on_saved_line_edit(dialog, self._session_id, mode, identity, edited)

        dialog.canvas.committed_line_edit_requested.connect(committed_line_edit)

        def selected_tangency_objects() -> None:
            if self._sketch_dialog is dialog:
                self._on_cross_sketch_tangency()

        dialog.canvas.object_tangency_selection_ready.connect(selected_tangency_objects)

        def open_tangency_options() -> None:
            if self._sketch_dialog is dialog:
                self._on_cross_sketch_tangency(force_dialog=True)

        dialog.canvas.object_tangency_options_requested.connect(open_tangency_options)

        def undo_saved_line_edit(identity: str, position: int, revision: int) -> None:
            self._undo_saved_line_edit(dialog, self._session_id, identity, position, revision)

        dialog.canvas.saved_line_edit_undo_requested.connect(undo_saved_line_edit)

        def undo_saved_mixed_copy(identity: str, position: int, revision: int) -> None:
            self._undo_saved_line_edit(
                dialog, self._session_id, identity, position, revision, mixed_copy=True
            )

        dialog.canvas.saved_mixed_copy_undo_requested.connect(undo_saved_mixed_copy)

        def committed_drag_trim(
            events: object, draft: object, constraints: object, background: object, revision: object
        ) -> None:
            self._on_saved_drag_trim(
                dialog, self._session_id, events, draft, constraints, background, revision
            )

        dialog.canvas.committed_drag_trim_requested.connect(committed_drag_trim)

        def committed_rotation(ids: object, center: object, angle: object) -> None:
            if not isinstance(angle, int | float) or not isfinite(angle):
                return
            self._on_drawing_move(dialog, self._session_id, ids, center, angle=float(angle))

        dialog.canvas.committed_rotation_requested.connect(committed_rotation)

        def committed_rotation_copy(ids: object, center: object, angle: object) -> None:
            if not isinstance(angle, int | float) or not isfinite(angle):
                return
            self._on_drawing_move(
                dialog, self._session_id, ids, center, angle=float(angle), copy_source=True
            )

        dialog.canvas.committed_rotation_copy_requested.connect(committed_rotation_copy)

        def committed_scale(ids: object, center: object, factor: object) -> None:
            if (
                not isinstance(factor, int | float)
                or isinstance(factor, bool)
                or not isfinite(factor)
                or factor <= 0
            ):
                return
            self._on_drawing_move(dialog, self._session_id, ids, center, scale=float(factor))

        dialog.canvas.committed_scale_requested.connect(committed_scale)

        def committed_scale_copy(ids: object, center: object, factor: object) -> None:
            if (
                not isinstance(factor, int | float)
                or isinstance(factor, bool)
                or not isfinite(factor)
                or factor <= 0
            ):
                return
            self._on_drawing_move(
                dialog, self._session_id, ids, center, scale=float(factor), copy_source=True
            )

        dialog.canvas.committed_scale_copy_requested.connect(committed_scale_copy)

        def committed_mirror(
            ids: object, start: object, end: object, *, copy_source: bool = False
        ) -> None:
            if not isinstance(end, tuple):
                return
            raw_end = cast("tuple[object, ...]", end)
            if len(raw_end) != 2 or not all(
                isinstance(value, int | float) and isfinite(value) for value in raw_end
            ):
                return
            self._on_drawing_move(
                dialog,
                self._session_id,
                ids,
                start,
                mirror_end=cast("tuple[float, float]", end),
                copy_source=copy_source,
            )

        dialog.canvas.committed_mirror_requested.connect(committed_mirror)

        def committed_mirror_copy(ids: object, start: object, end: object) -> None:
            committed_mirror(ids, start, end, copy_source=True)

        dialog.canvas.committed_mirror_copy_requested.connect(committed_mirror_copy)

        def store_copy_mode(mode: int) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_COPY_MODE, mode)

        dialog.canvas.copy_mode_changed.connect(store_copy_mode)

        def store_offset_distance(value: float) -> None:
            self._offset_default_distance = value

        dialog.canvas.offset_default_distance_changed.connect(store_offset_distance)

        def store_offset_gap_type(value: int) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_OFFSET_GAP_TYPE, value)

        dialog.canvas.offset_gap_type_changed.connect(store_offset_gap_type)

        def store_corner_trim(trim: bool) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_CORNER_TRIM, int(trim))
            if self.document_session is not None:
                for entry in self.document_session.documents:
                    if entry.draft is not None and entry.draft is not dialog:
                        entry.draft.canvas.set_corner_trim(trim, notify=False)

        dialog.canvas.corner_trim_changed.connect(store_corner_trim)

        def store_chamfer_method(angle_method: bool) -> None:
            self._chamfer_method_angle = angle_method
            if self.document_session is not None:
                for entry in self.document_session.documents:
                    if entry.draft is not None and entry.draft is not dialog:
                        entry.draft.canvas.set_chamfer_method(angle_method, notify=False)

        dialog.canvas.chamfer_method_changed.connect(store_chamfer_method)

        def store_edge_mode(extend: bool) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_EDGE_MODE, int(extend))

        dialog.canvas.line_edge_mode_changed.connect(store_edge_mode)

        def store_trim_mode(standard: bool) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_TRIM_STANDARD, int(standard))

        dialog.canvas.line_standard_mode_changed.connect(store_trim_mode)

        def store_projection_mode(mode: int) -> None:
            QSettings(ORG_NAME, APP_NAME).setValue(SETTINGS_KEY_PROJECTION_MODE, mode)

        dialog.canvas.line_projection_mode_changed.connect(store_projection_mode)

        def layer_changed(payload: object) -> None:
            self._on_drawing_layer_update(dialog, self._session_id, payload)

        dialog.layer_change_requested.connect(layer_changed)

        def assign_layer(raw_ids: object, layer_name: str) -> None:
            if self._sketch_dialog is dialog:
                self._on_drawing_assign_layer(dialog, self._session_id, raw_ids, layer_name)

        dialog.assign_selection_layer_requested.connect(assign_layer)

        def assign_construction(raw_ids: object, construction: bool) -> None:
            if self._sketch_dialog is dialog:
                self._on_drawing_assign_construction(
                    dialog, self._session_id, raw_ids, construction
                )

        dialog.assign_selection_construction_requested.connect(assign_construction)

        def activate_drawing_console() -> None:
            if (
                self._sketch_dialog is dialog
                and self.active_workspace == "sketch"
                and self.cli_tab is not None
                and self.cli_tab.drawing_bar is dialog.drawing_command_bar
            ):
                self._show_console_page(self.cli_tab)

        dialog.drawing_command_bar.activate_requested.connect(activate_drawing_console)

        def show_drawing_options(panel: str) -> None:
            if panel == "options" and self._sketch_dialog is dialog:
                self._show_options()

        dialog.drawing_command_bar.panel_requested.connect(show_drawing_options)
        dialog.drawing_command_bar.group_requested.connect(
            lambda: self._create_drawing_group(dialog)
        )
        dialog.drawing_command_bar.ungroup_requested.connect(
            lambda: self._remove_drawing_group(dialog)
        )
        dialog.drawing_command_bar.group_edit_requested.connect(
            lambda: self._edit_drawing_group(dialog)
        )
        dialog.drawing_command_bar.block_requested.connect(
            lambda: self._create_drawing_block(dialog)
        )
        dialog.drawing_command_bar.block_insert_requested.connect(
            lambda: self._insert_drawing_block(dialog)
        )
        dialog.drawing_command_bar.block_explode_requested.connect(
            lambda: self._explode_drawing_block(dialog)
        )
        dialog.drawing_command_bar.block_edit_requested.connect(
            lambda: self._edit_drawing_block(dialog)
        )
        dialog.block_manage_requested.connect(lambda: self._run_drawing_block_menu("manage"))
        dialog.block_library_requested.connect(lambda: self._run_drawing_block_menu("library"))
        dialog.block_write_requested.connect(lambda: self._run_drawing_block_menu("write"))
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
        dialog.protect_canvas_during_toolbar_drag((self.main_toolbar, self.modeling_toolbar))
        self._sketch_dialog = dialog
        if dialog.canvas.select_committed_entities:
            self._bind_drawing_text_tools(dialog)
            self._bind_geometric_tolerance_tools(dialog)
            dialog.dimensions.independent_edit_guard = lambda ref: (
                self._require_independent_dimension_edit(dialog, ref)
            )
            dialog.canvas.ensure_group_operation = lambda identity: self._ensure_group_operation(
                dialog, identity
            )
            dialog.canvas.offset_group_guard = lambda identity: self._offset_group_member_allowed(
                dialog, identity
            )
            dialog.canvas.delete_collection_selection = lambda: self._delete_collection_selection(
                dialog
            )
            dialog.canvas.group_selection_provider = lambda: self._effective_group_selection(dialog)
            dialog.canvas.collection_transform_preview_provider = lambda copy_source, delta: (
                self._preview_collection_transform(dialog, delta, copy_source=copy_source)
            )
            dialog.canvas.collection_affine_preview_provider = lambda kind, center, value, copy: (
                self._preview_collection_affine(dialog, kind, center, value, copy_source=copy)
            )
            dialog.canvas.collection_mirror_preview_provider = lambda copy_source, start, end: (
                self._preview_collection_mirror(dialog, start, end, copy_source=copy_source)
            )
            dialog.canvas.group_clipboard_guard = lambda: self._group_clipboard_requires_support(
                dialog
            )
            dialog.canvas.capture_collection_clipboard = lambda include_dimensions=False: (
                self._capture_collection_clipboard(
                    dialog, include_internal_dimensions=include_dimensions
                )
            )
            dialog.canvas.begin_collection_paste = lambda: self._begin_collection_paste(dialog)
            dialog.canvas.collection_paste_preview_provider = lambda payload, delta: (
                self._preview_collection_paste(dialog, payload, delta)
            )
            dialog.canvas.commit_collection_paste = lambda payload, delta: (
                self._commit_collection_paste(dialog, payload, delta)
            )
        dialog.canvas.changed.connect(self._sync_drawing_clipboard_actions)
        dialog.plane_combo.currentTextChanged.connect(self._sync_camera_status)
        dialog.set_context_sketches(self._services.kernel.sketches)
        dialog.canvas.set_drawing_rasters(self._services.kernel.drawing_rasters)

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
        if current != "sketch" and self.cli_tab is not None:
            self.cli_tab.set_drawing_bar(None)
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

    def _drawing_clipboard_canvas(self) -> SketchCanvas | None:
        editor = self.active_sketch_dialog()
        if (
            editor is None
            or self.active_workspace != "sketch"
            or not editor.canvas.select_committed_entities
        ):
            return None
        return editor.canvas

    def _sync_drawing_clipboard_actions(self) -> None:
        canvas = self._drawing_clipboard_canvas()
        ready = (
            canvas is not None
            and not canvas.has_active_edit_gesture
            and not canvas.has_pending_geometry
        )
        self.act_copy.setEnabled(
            bool(
                ready
                and canvas is not None
                and (
                    canvas.selected_entity_ids
                    or canvas.selected_raster_id
                    or (canvas.text_tools is not None and canvas.text_tools.selected_ids)
                    or (
                        canvas.geometric_tolerance_tools is not None
                        and canvas.geometric_tolerance_tools.selected_id is not None
                    )
                )
            )
        )
        self.act_delete.setToolTip(
            "删除所选二维对象" if canvas is not None else "当前版本不支持直接删除实体。"
        )
        self.act_delete.setEnabled(
            bool(
                ready
                and canvas is not None
                and (
                    canvas.selected_entity_ids
                    or canvas.selected_constraint_ids
                    or canvas.selected_raster_id
                    or (canvas.text_tools is not None and canvas.text_tools.selected_ids)
                    or (
                        canvas.geometric_tolerance_tools is not None
                        and canvas.geometric_tolerance_tools.selected_id is not None
                    )
                )
            )
        )
        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        self.act_paste.setEnabled(
            bool(
                ready
                and mime is not None
                and (
                    mime.hasFormat(TEXT_CLIPBOARD_MIME)
                    or mime.hasFormat(TOLERANCE_CLIPBOARD_MIME)
                    or mime.hasFormat(DRAWING_CLIPBOARD_MIME)
                    or mime.hasFormat(DRAWING_MIXED_CLIPBOARD_MIME)
                    or mime.hasFormat(DRAWING_RASTER_GROUP_MIME)
                    or mime.hasImage()
                )
            )
        )

    def _delete_drawing_selection(self) -> None:
        canvas = self._drawing_clipboard_canvas()
        if canvas is not None:
            canvas.delete_selected()
            canvas.setFocus()

    def _copy_drawing_selection(self) -> None:
        canvas = self._drawing_clipboard_canvas()
        if canvas is not None:
            canvas.copy_to_clipboard()
            canvas.setFocus()

    def _paste_drawing_selection(self) -> None:
        canvas = self._drawing_clipboard_canvas()
        if canvas is not None:
            canvas.begin_clipboard_paste()
            canvas.setFocus()

    def _sync_workspace_actions(self) -> None:
        self._sync_drawing_clipboard_actions()
        for action in (self.act_text, self.act_mtext, self.act_text_style):
            action.setEnabled(
                self.active_workspace == "sketch"
                and self._loaded is not None
                and self._loaded.document.document_kind == "sketch"
            )
        self.act_drawing_dimension_styles.setEnabled(
            self.active_workspace == "sketch"
            and self._loaded is not None
            and self._loaded.document.document_type == "drawing2d"
        )
        for action in (
            self.act_geometric_tolerance,
            self.act_datum_label,
            self.act_datum_symbol_style,
            self.act_datum_text_style,
            self.act_datum_arrow_style,
        ):
            action.setEnabled(
                self.active_workspace == "sketch"
                and self._loaded is not None
                and self._loaded.document.document_type == "drawing2d"
            )
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

    def _sync_session_document_actions(self) -> None:
        """Keep all shared entries consistent with the active session document."""
        if self.document_session is None:
            return
        available = self._loaded is not None and self.document_session.active is not None
        for action in (
            self.act_close_document,
            self.act_save,
            self.act_save_as,
            self.act_save_all,
            self.act_import,
            self.act_export,
            self.act_undo,
            self.act_redo,
        ):
            action.setEnabled(available)

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
        if dialog.canvas.select_committed_entities and self._services is not None:
            dialog.canvas.circle_fillet_radius = self._services.kernel.drawing_fillet_radius
            dialog.canvas.sync_chamfer_values(self._services.kernel.drawing_chamfer_values)
            dialog.canvas.set_chamfer_method(self._chamfer_method_angle, notify=False)
        dialog.canvas.set_offset_default_distance(self._offset_default_distance)
        corner_trim = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_CORNER_TRIM, 1)
        dialog.canvas.set_corner_trim(corner_trim not in (0, "0"), notify=False)
        gap_type = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_OFFSET_GAP_TYPE, 0)
        dialog.canvas.set_offset_gap_type(
            int(gap_type) if gap_type in (0, 1, 2, "0", "1", "2") else 0
        )
        copy_mode = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_COPY_MODE, 0)
        dialog.canvas.set_copy_mode(1 if copy_mode in (1, "1") else 0)
        edge_mode = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_EDGE_MODE, 0)
        dialog.canvas.set_line_edit_edge_mode(edge_mode in (1, "1"))
        standard = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_TRIM_STANDARD, 0)
        dialog.canvas.set_line_edit_standard_mode(standard in (1, "1"))
        projection = QSettings(ORG_NAME, APP_NAME).value(SETTINGS_KEY_PROJECTION_MODE, 1)
        dialog.canvas.set_line_edit_projection_mode(
            int(projection) if projection in (0, 1, 2, "0", "1", "2") else 1
        )
        dialog.setWindowFlags(Qt.WindowType.Widget)
        self.workspace_tabs.set_content("sketch", dialog)
        self._workspace_transition = True
        try:
            self.workspace_tabs.activate("sketch")
        finally:
            self._workspace_transition = False
        dialog.show()
        if dialog.canvas.select_committed_entities and self.cli_tab is not None:
            self.cli_tab.set_drawing_bar(dialog.drawing_command_bar)
            self._show_console_page(self.cli_tab)
        dialog.refresh_document_properties()
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
        if self.cli_tab is not None and self.cli_tab.drawing_bar is dialog.drawing_command_bar:
            self.cli_tab.set_drawing_bar(None)
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
        preparation = self._prepared_sketch_save
        if preparation is not None and preparation.draft is editor:
            return
        if editor is not None and services is not None:
            if editor.canvas.collection_session is not None:
                try:
                    self._apply_collection_snapshot(
                        editor, editor.canvas.collection_session.snapshot
                    )
                except ValidationError as exc:
                    editor.status_label.setText(str(exc))
                return
            if editor.canvas.select_committed_entities:
                editor.canvas.drawing_dimension_styles = services.kernel.drawing_dimension_styles
                editor.canvas.circle_fillet_radius = services.kernel.drawing_fillet_radius
                editor.canvas.sync_chamfer_values(services.kernel.drawing_chamfer_values)
                if editor.dimensions.drawing_style_active:
                    has_styles = self._loaded is not None and any(
                        command.id == "drawing.dimension_styles.set"
                        or "clipboard_styles" in command.params
                        for command in self._loaded.document.commands
                    )
                    editor.dimensions.set_drawing_style(
                        services.kernel.drawing_dimension_styles.current if has_styles else None
                    )
            # Context changes can add or remove layers. Keep both sets available
            # while navigation and the canvas refresh against the new sketches.
            # The final document table is installed after the context update.
            editor.canvas.document_layer_table = merge_layer_tables(
                editor.layer_table, services.kernel.drawing_layers
            )
            editor.set_context_sketches(services.kernel.sketches)
            editor.canvas.set_drawing_rasters(services.kernel.drawing_rasters)
            editor.set_document_layers(
                services.kernel.drawing_layers, services.kernel.dimension_layer
            )
            if editor.canvas.text_tools is not None:
                editor.canvas.text_tools.sync(
                    services.kernel.drawing_texts, services.kernel.drawing_text_styles
                )
            editor.canvas.set_drawing_blocks(
                services.kernel.drawing_block_definitions,
                services.kernel.drawing_block_instances,
                services.kernel.drawing_text_styles,
            )
            if editor.canvas.geometric_tolerance_tools is not None:
                editor.canvas.geometric_tolerance_tools.sync(
                    services.kernel.drawing_tolerance_frames,
                    services.kernel.drawing_datum_identifiers,
                    services.kernel.drawing_reference_dimensions,
                )

    def _bind_geometric_tolerance_tools(self, editor: SketchEditorDialog) -> None:
        from mycad.ui.geometric_tolerance_tools import GeometricToleranceTools

        loaded, services = self._loaded, self._services
        if loaded is None or services is None:
            return
        tools = GeometricToleranceTools(editor.canvas, editor)
        tools.default_datum_symbol_style = lambda: default_datum_symbol_style(
            QSettings(ORG_NAME, APP_NAME)
        )
        token = next(
            (
                key
                for key, document in self._collection_clipboard_documents.items()
                if document is loaded
            ),
            None,
        )
        if token is None:
            token = uuid4().hex
            self._collection_clipboard_documents[token] = loaded
        tools.set_collection_clipboard_source(token)
        editor.canvas.geometric_tolerance_tools = tools
        tools.sync(
            services.kernel.drawing_tolerance_frames,
            services.kernel.drawing_datum_identifiers,
            services.kernel.drawing_reference_dimensions,
        )

        def execute(command: str, params: dict[str, object]) -> bool:
            unit = self.execution_unit
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；形位公差未修改。")
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后修改形位公差。")
            changed: set[tuple[str, str]] = set()
            fields = (
                (
                    ("update_frames", "tolerance", "frame_id"),
                    ("update_datums", "datum", "datum_id"),
                    ("remove_frames", "tolerance", ""),
                    ("remove_datums", "datum", ""),
                )
                if command == "drawing.tolerance.batch"
                else (
                    ("update", "reference_dimension", "dimension_id"),
                    ("remove", "reference_dimension", ""),
                )
                if command == "drawing.reference_dimensions.batch"
                else ()
            )
            for field, kind, identity_field in fields:
                raw_items = params.get(field, ())
                if not isinstance(raw_items, list | tuple):
                    continue
                for raw in cast("Sequence[object]", raw_items):
                    value = (
                        cast("Mapping[str, object]", raw).get(identity_field)
                        if identity_field and isinstance(raw, Mapping)
                        else raw
                        if not identity_field
                        else None
                    )
                    if isinstance(value, str):
                        changed.add((kind, value))
            self._reject_group_member_edit(editor, changed)
            if editor.canvas.collection_session is not None:
                operation = ReplayAppend(
                    command, services.registry.get(command).version, params, "local"
                )
                if not editor.canvas.stage_collection_operation(operation):
                    raise ValueError(editor.canvas.message)
                return True
            try:
                loaded.bus.execute(command, params, "local")
            except (KeyError, MycadError) as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        def commit_mixed_tolerances(
            sketch: Sketch,
            frames: tuple[FeatureControlFrame, ...],
            datums: tuple[DatumIdentifier, ...],
            references: tuple[DetachedDimension, ...],
            texts: tuple[DrawingText, ...],
            rasters: tuple[DrawingRaster, ...],
            styles: DimensionStyleTable | None,
            text_styles: TextStyleTable | None,
            preserve_external: bool,
        ) -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；混合标注未粘贴。")
            unit = self.execution_unit
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后粘贴。")
            if editor.canvas.collection_session is not None:
                raise ValueError("请先完成或取消当前暂存，再粘贴混合对象。")
            used_sketch_layers = {item.layer_name for item in sketch.entities} | {
                item.layer_name for item in sketch.constraints if item.layer_name is not None
            }
            for name in used_sketch_layers:
                try:
                    layer = services.kernel.drawing_layers.get(name)
                except KeyError:
                    layer = sketch.layers.get(name)
                if layer.locked or not layer.displayed:
                    raise ValueError("目标图层已锁定或隐藏，不能粘贴。")
            for item in (*frames, *datums, *references, *texts):
                try:
                    layer = services.kernel.drawing_layers.get(item.layer_name)
                except KeyError:
                    layer = sketch.layers.get(item.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("目标标注或文字图层已锁定或隐藏，不能粘贴。")
            for raster in rasters:
                try:
                    layer = services.kernel.drawing_layers.get(raster.layer_name)
                except KeyError:
                    layer = sketch.layers.get(raster.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("目标图片图层已锁定或隐藏，不能粘贴。")
            try:
                mycad_app.commit_new_sketch(
                    services,
                    loaded,
                    sketch,
                    session_identity=self._session_id,
                    imported_styles=styles,
                    imported_text_styles=text_styles,
                    imported_texts=texts,
                    imported_rasters=rasters,
                    imported_tolerance_frames=frames,
                    imported_datums=datums,
                    imported_reference_dimensions=references,
                    preserve_existing_datum_refs=preserve_external,
                    persistent_batch=True,
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        def commit_mixed_tolerance_move(
            entity_ids: tuple[str, ...],
            frame_ids: tuple[str, ...],
            datum_ids: tuple[str, ...],
            reference_ids: tuple[str, ...],
            text_ids: tuple[str, ...],
            raster_ids: tuple[str, ...],
            delta: tuple[float, float],
            revision: int,
            *,
            copy_source: bool = False,
        ) -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
                or loaded.document.revision != revision
            ):
                raise ValueError("图纸或选择已变化，请重新开始移动。")
            unit = self.execution_unit
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后移动。")
            if editor.canvas.collection_session is not None:
                if (
                    set(entity_ids) != editor.canvas.selected_entity_ids
                    or set(text_ids)
                    != (
                        editor.canvas.text_tools.selected_ids if editor.canvas.text_tools else set()
                    )
                    or set(raster_ids) != editor.canvas.selected_raster_ids
                    or {*frame_ids, *datum_ids, *reference_ids} != tools.selected_ids
                ):
                    raise ValueError("选择已变化，请重新开始移动。")
                annotations = (
                    *(("tolerance", item) for item in frame_ids),
                    *(("datum", item) for item in datum_ids),
                    *(("reference_dimension", item) for item in reference_ids),
                )
                if not self._move_collection_geometry(
                    editor, entity_ids, delta, copy_source=copy_source, annotation_seeds=annotations
                ):
                    raise ValueError(editor.status_label.text())
                return True
            if copy_source:
                raise ValueError("当前图纸无法暂存组复制。")
            try:
                mycad_app.move_tolerance_selection(
                    services,
                    loaded,
                    entity_ids,
                    frame_ids,
                    datum_ids,
                    reference_ids,
                    delta,
                    session_identity=self._session_id,
                    text_ids=text_ids,
                    raster_ids=raster_ids,
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        def commit_mixed_tolerance_delete(
            frame_ids: tuple[str, ...],
            datum_ids: tuple[str, ...],
            reference_ids: tuple[str, ...],
            text_ids: tuple[str, ...],
            raster_ids: tuple[str, ...],
        ) -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；标注未删除。")
            unit = self.execution_unit
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后删除标注。")
            try:
                mycad_app.delete_tolerance_selection(
                    services,
                    loaded,
                    frame_ids,
                    datum_ids,
                    reference_ids,
                    session_identity=self._session_id,
                    text_ids=text_ids,
                    raster_ids=raster_ids,
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        def commit_geometry_tolerance_delete() -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                editor.status_label.setText("图纸已切换；对象未删除。")
                return True
            if editor.canvas.has_pending_geometry or editor.canvas.has_active_edit_gesture:
                editor.status_label.setText("请先完成或取消当前操作，再删除所选对象。")
                return True
            self._on_drawing_move(
                editor,
                self._session_id,
                tuple(sorted(editor.canvas.selected_entity_ids)),
                (0.0, 0.0),
                erase=True,
            )
            return True

        def commit_identity_repair() -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；标注身份未修复。")
            unit = self.execution_unit
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后修复标注身份。")
            try:
                mycad_app.repair_tolerance_annotation_identities(
                    services, loaded, session_identity=self._session_id
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        def commit_curve_identity_upgrade() -> bool:
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；曲线点身份未升级。")
            unit = self.execution_unit
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后升级曲线点身份。")
            try:
                mycad_app.upgrade_selected_curve_identities(
                    services,
                    loaded,
                    tuple(sorted(editor.canvas.selected_entity_ids)),
                    session_identity=self._session_id,
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            return True

        tools.commit_curve_identity_upgrade = commit_curve_identity_upgrade
        tools.commit_identity_repair = commit_identity_repair
        tools.commit_geometry_delete = commit_geometry_tolerance_delete
        tools.commit_delete = commit_mixed_tolerance_delete
        tools.source_revision = lambda: loaded.document.revision

        def source_subject(
            kind: str, identity: str
        ) -> FeatureControlFrame | DatumIdentifier | DetachedDimension | None:
            if self._loaded is not loaded or self._services is not services:
                return None
            if kind == "frame":
                return next(
                    (
                        item
                        for item in services.kernel.drawing_tolerance_frames
                        if item.frame_id == identity
                    ),
                    None,
                )
            if kind == "datum":
                return next(
                    (
                        item
                        for item in services.kernel.drawing_datum_identifiers
                        if item.datum_id == identity
                    ),
                    None,
                )
            if kind == "reference":
                return next(
                    (
                        item
                        for item in services.kernel.drawing_reference_dimensions
                        if item.dimension_id == identity
                    ),
                    None,
                )
            return None

        tools.source_subject = source_subject

        def source_layer_editable(name: str) -> bool:
            if self._loaded is not loaded or self._services is not services:
                return False
            try:
                layer = services.kernel.drawing_layers.get(name)
            except KeyError:
                return False
            return layer.displayed and not layer.locked

        tools.source_layer_editable = source_layer_editable

        def source_text(identity: str) -> DrawingText | None:
            if self._loaded is not loaded or self._services is not services:
                return None
            return next(
                (item for item in services.kernel.drawing_texts if item.text_id == identity), None
            )

        tools.source_text = source_text

        def source_raster(identity: str) -> DrawingRaster | None:
            if self._loaded is not loaded or self._services is not services:
                return None
            return next(
                (item for item in services.kernel.drawing_rasters if item.image_id == identity),
                None,
            )

        tools.source_raster = source_raster
        tools.commit_move = commit_mixed_tolerance_move
        tools.commit_collection_copy = partial(commit_mixed_tolerance_move, copy_source=True)
        tools.commit_mixed = commit_mixed_tolerances
        tools.execute = execute
        tools.attachment_resolved = services.kernel.datum_attachment_resolved
        first_dimension_action = next(iter(editor.dimension_toolbar.actions()), None)
        if first_dimension_action is None:
            editor.dimension_toolbar.addAction(self.act_geometric_tolerance)
            editor.dimension_toolbar.addAction(self.act_datum_label)
        else:
            editor.dimension_toolbar.insertAction(
                first_dimension_action, self.act_geometric_tolerance
            )
            editor.dimension_toolbar.insertAction(first_dimension_action, self.act_datum_label)
            editor.dimension_toolbar.insertSeparator(first_dimension_action)
        for action in (self.act_geometric_tolerance, self.act_datum_label):
            button = editor.dimension_toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        maintenance = QMenu("基准操作", editor)
        maintenance.addAction(self.act_datum_symbol_style)
        maintenance.addMenu(self.menu_default_datum_style)
        maintenance.addAction(self.act_datum_text_style)
        maintenance.addAction(self.act_datum_arrow_style)
        extension_action = maintenance.addAction("编辑表面延伸线…")
        extension_action.triggered.connect(tools.edit_surface_extension)
        surface_action = maintenance.addAction("添加或重设表面指示…")
        surface_action.triggered.connect(tools.begin_surface_indication_edit)
        edge_action = maintenance.addAction("切换为边线指示")
        edge_action.triggered.connect(tools.remove_surface_indication)
        detach_action = maintenance.addAction("解除基准附着")
        detach_action.triggered.connect(tools.detach_selected_datum)
        detach_frame_action = maintenance.addAction("解除公差框附着")
        detach_frame_action.triggered.connect(tools.detach_selected_frame)
        reattach_action = maintenance.addAction("重新关联基准")
        reattach_action.triggered.connect(tools.begin_reattach)
        repair_action = maintenance.addAction("修复标注身份")
        repair_action.triggered.connect(tools.repair_annotation_ids)
        curve_upgrade_action = maintenance.addAction("升级曲线点身份")
        curve_upgrade_action.triggered.connect(tools.upgrade_curve_identities)
        editor.dimension_toolbar.addAction(maintenance.menuAction())

    def _apply_collection_snapshot(self, editor: SketchEditorDialog, snapshot: object) -> None:
        from mycad.core.drawing_collection_state import DrawingCollectionSnapshot

        if not isinstance(snapshot, DrawingCollectionSnapshot):
            return
        if (
            snapshot.layers != editor.layer_table
            or snapshot.dimension_layer != editor.dimension_layer
        ):
            editor.set_document_layers(snapshot.layers, snapshot.dimension_layer)
        editor.canvas.drawing_dimension_styles = snapshot.dimension_styles
        if editor.dimensions.drawing_style_active:
            editor.dimensions.set_drawing_style(snapshot.dimension_styles.current)
        editor.set_context_sketches(
            tuple(
                sketch for sketch in snapshot.sketches if sketch.sketch_id != editor.draft_sketch_id
            )
        )
        editor.canvas.set_drawing_rasters(snapshot.rasters)
        if editor.canvas.text_tools is not None:
            editor.canvas.text_tools.sync(snapshot.texts, snapshot.text_styles)
        editor.canvas.set_drawing_blocks(
            snapshot.block_definitions, snapshot.block_instances, snapshot.text_styles
        )
        if editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.sync(
                snapshot.frames, snapshot.datums, snapshot.reference_dimensions
            )

    def _bind_drawing_text_tools(self, editor: SketchEditorDialog) -> None:

        loaded, services = self._loaded, self._services
        if loaded is None or services is None:
            return
        tools = DrawingTextTools(editor.canvas, editor)
        tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
        editor.canvas.set_drawing_blocks(
            services.kernel.drawing_block_definitions,
            services.kernel.drawing_block_instances,
            services.kernel.drawing_text_styles,
        )
        editor.parameter_tabs.addTab(tools.panel, "文字")

        def sync_collection(snapshot: object) -> None:
            self._apply_collection_snapshot(editor, snapshot)

        editor.canvas.collection_snapshot_changed.connect(sync_collection)

        def execute(command: str, params: dict[str, object]) -> bool:
            unit = self.execution_unit
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；文字未修改。")
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后修改文字。")
            changed_ids: set[str] = set()
            identity = params.get("text_id")
            if command in {"drawing.text.update", "drawing.text.remove"} and isinstance(
                identity, str
            ):
                changed_ids.add(identity)
            if command == "drawing.text.batch":
                raw_updates = params.get("update", ())
                raw_removals = params.get("remove", ())
                if isinstance(raw_updates, list | tuple):
                    for raw in cast("Sequence[object]", raw_updates):
                        if isinstance(raw, Mapping):
                            value = cast("Mapping[str, object]", raw).get("text_id")
                            if isinstance(value, str):
                                changed_ids.add(value)
                if isinstance(raw_removals, list | tuple):
                    changed_ids.update(
                        item
                        for item in cast("Sequence[object]", raw_removals)
                        if isinstance(item, str)
                    )
            self._reject_group_member_edit(editor, {("text", item) for item in changed_ids})
            if editor.canvas.collection_session is not None:
                operation = ReplayAppend(
                    command, services.registry.get(command).version, params, "local"
                )
                if not editor.canvas.stage_collection_operation(operation):
                    raise ValueError(editor.canvas.message)
                return True
            try:
                if command == "drawing.text_styles.set":
                    updated_styles = TextStyleTable.from_mapping(params)
                    original_styles = services.kernel.drawing_text_styles
                    datum_tools = editor.canvas.geometric_tolerance_tools
                    updates: list[dict[str, object]] = []
                    for datum in services.kernel.drawing_datum_identifiers:
                        if datum.box_size_mm is None or datum.text_style_id is None:
                            continue
                        before = original_styles.get(datum.text_style_id)
                        after = updated_styles.get(datum.text_style_id)
                        if text_style_geometry_signature(before) != text_style_geometry_signature(
                            after
                        ):
                            if datum_tools is None:
                                raise ValueError("当前图纸无法更新基准框。")
                            updates.append(
                                datum_tools.relayout_recorded_datum(
                                    datum, updated_styles
                                ).to_mapping()
                            )
                    if updates:
                        params = {**params, "datum_updates": updates}
                loaded.bus.execute(command, params, "local")
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            self._sync_drawing_clipboard_actions()
            return True

        tools.execute = execute

        def paste_commit(
            sketch: Sketch,
            texts: tuple[DrawingText, ...],
            styles: TextStyleTable,
            images: tuple[DrawingRaster, ...],
            dimension_styles: DimensionStyleTable | None,
        ) -> bool:
            unit = self.execution_unit
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
            ):
                raise ValueError("图纸已切换；剪贴板对象未提交。")
            if unit is not None and (unit.is_busy or unit.is_notifying_result):
                raise ValueError("应用正在执行命令；请稍后粘贴。")
            if editor.canvas.collection_session is not None:
                raise ValueError("请先完成或取消当前暂存，再粘贴混合对象。")
            try:
                mycad_app.commit_new_sketch(
                    services,
                    loaded,
                    sketch,
                    session_identity=self._session_id,
                    imported_styles=dimension_styles,
                    imported_texts=texts,
                    imported_text_styles=styles,
                    imported_rasters=images,
                    persistent_batch=True,
                )
            except MycadError as exc:
                raise ValueError(str(exc)) from exc
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
            self._refresh_document_choice()
            self._sync_drawing_clipboard_actions()
            return True

        tools.paste_commit = paste_commit
        for label, kind in (("单行文字", "text"), ("多行文字", "mtext"), ("文字样式", "style")):
            action = editor.drawing_toolbar.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=kind: self._start_drawing_text(value)
            )

    def _start_drawing_text(self, kind: str) -> None:
        editor = self.active_sketch_dialog()
        if editor is None or editor.canvas.text_tools is None:
            return
        tools = editor.canvas.text_tools
        editor.parameter_tabs.setCurrentWidget(tools.panel)
        if kind == "style":
            tools.open_styles()
        else:
            tools.begin("mtext" if kind == "mtext" else "text")

    def _show_drawing_dimension_styles(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None:
            editor.dimensions.open_format_presets()

    def _start_geometric_tolerance(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.begin_mechanical_frame()

    def _start_datum_label(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.begin_mechanical_datum()

    def _edit_datum_text_style(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.edit_datum_text_style()

    def _edit_datum_symbol_style(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.edit_datum_symbol_style()

    def _set_default_datum_style(self, style: str) -> None:
        if style not in ("rectangle", "circle"):
            return
        QSettings(ORG_NAME, APP_NAME).setValue(DATUM_SYMBOL_STYLE_KEY, style)
        self._sync_default_datum_style()

    def _sync_default_datum_style(self) -> None:
        style = default_datum_symbol_style(QSettings(ORG_NAME, APP_NAME))
        self.act_default_datum_rectangle.setChecked(style == "rectangle")
        self.act_default_datum_circle.setChecked(style == "circle")

    def _edit_datum_arrow_style(self) -> None:
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            editor.canvas.geometric_tolerance_tools.edit_datum_arrow_style()

    def _open_drawing_dimension_styles(self, editor: SketchEditorDialog) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            loaded is None
            or services is None
            or editor is not self._sketch_dialog
            or loaded.document.document_type != "drawing2d"
        ):
            editor.status_label.setText("当前没有可编辑的独立二维图纸。")
            return
        if (
            (unit is not None and (unit.is_busy or unit.is_notifying_result))
            or editor.canvas.has_pending_geometry
            or editor.canvas.has_active_edit_gesture
            or editor.canvas.mixed_move is not None
            or bool(editor.canvas.pending_cross_tangencies)
            or bool(editor.canvas.pending_associative_arrays)
        ):
            editor.status_label.setText("请先完成或取消当前操作，再设置标注样式。")
            return
        old = services.kernel.drawing_dimension_styles
        used = frozenset(
            constraint.style_name
            for constraints in (
                *(sketch.constraints for sketch in services.kernel.sketches),
                tuple(editor.canvas.constraints),
            )
            for constraint in constraints
            if constraint.style_name is not None
        )
        had_styles = any(
            command.id == "drawing.dimension_styles.set" or "clipboard_styles" in command.params
            for command in loaded.document.commands
        )
        initial = old
        if not had_styles and not used:
            initial = DimensionStyleTable(
                (DimensionStyle("标准", scale=DEFAULT_NEW_DRAWING_DIMENSION_SCALE),), "标准"
            )
        style_dialog = DrawingDimensionStylesDialog(
            initial, used, editor, text_styles=services.kernel.drawing_text_styles
        )

        def open_local_presets() -> None:
            style_dialog.reject()
            editor.dimensions.open_local_format_presets()

        style_dialog.local_presets_button.clicked.connect(open_local_presets)
        if style_dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        if self._loaded is not loaded or self._services is not services:
            editor.status_label.setText("图纸已切换；标注样式未修改。")
            return
        table = style_dialog.table
        for constraint in editor.canvas.constraints:
            if constraint.style_name is None:
                continue
            try:
                if old.get(constraint.style_name) != table.get(constraint.style_name):
                    editor.status_label.setText("草稿尺寸使用了待修改样式，请先完成草图。")
                    return
            except KeyError:
                editor.status_label.setText("草稿尺寸仍使用待删除样式，请先完成草图。")
                return
        if table != old or not had_styles:
            try:
                if loaded.document.archive_version < 6:
                    candidate = mycad_app.create_replay_candidate(
                        services, loaded, session_identity=self._session_id
                    )
                    candidate.stage(
                        ReplayChangeSet(
                            (),
                            (
                                ReplayAppend(
                                    "drawing.dimension_styles.set",
                                    10,
                                    table.to_mapping(),
                                    "local",
                                ),
                            ),
                            False,
                            6,
                        ),
                        current_session_identity=self._session_id,
                    )
                    preview = candidate.preview(current_session_identity=self._session_id)
                    if preview.state != "succeeded":
                        raise ValueError(str(preview.failure or "标注样式预览失败"))
                    candidate.commit(
                        candidate.authorize_commit(current_session_identity=self._session_id),
                        current_session_identity=self._session_id,
                    )
                else:
                    loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
            except (MycadError, ValueError) as exc:
                editor.status_label.setText(f"标注样式未修改：{exc}")
                return
            editor.layer_history_boundaries[loaded.document.command_count] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            self._sync_drawing_layers()
        editor.dimensions.set_drawing_style(table.current)
        editor.status_label.setText(f"当前图纸标注样式：{table.current_name}。")

    def _on_array_spacing_grip_commit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_token: object,
        raw_array: object,
        raw_row: object,
        raw_column: object,
        raw_revision: object,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            not isinstance(raw_token, str)
            or not isinstance(raw_array, AssociativeRectArray)
            or not isinstance(raw_row, int | float)
            or not isinstance(raw_column, int | float)
            or not isinstance(raw_revision, int)
        ):
            return
        token, array, revision = raw_token, raw_array, raw_revision
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            editor.canvas.finish_array_spacing_commit(token, "文档已关闭。")
            return

        def commit() -> object:
            if (
                self._loaded is not loaded
                or self._sketch_dialog is not editor
                or self._session_id != session_id
                or loaded.document.revision != revision
                or not editor.canvas.array_spacing_commit_is_current(token, revision)
                or array not in services.kernel.associative_arrays
            ):
                raise ValidationError("文档或阵列已变化，请重新拖动。")
            return loaded.bus.execute(
                "drawing.array.update",
                {"array_id": array.array_id, "row_spacing": raw_row, "column_spacing": raw_column},
                confirmed_by="local",
                version=1,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            editor.canvas.finish_array_spacing_commit(token, result.error)
            if result.error is None:
                self._sync_drawing_layers()
                editor.layer_history_boundaries[len(loaded.document.commands)] = (
                    editor.canvas.history_position
                )
                editor.layer_history_redo.clear()
                editor.canvas.discard_redo_history()

        if not unit.submit(
            commit, operation="array-spacing-grip", session_id=session_id, on_complete=finish
        ):
            editor.canvas.finish_array_spacing_commit(token, "几何工作线程忙碌，请重试。")

    def _on_array_count_grip_commit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_token: object,
        raw_array: object,
        raw_resized: object,
        raw_revision: object,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            not isinstance(raw_token, str)
            or not isinstance(raw_array, AssociativeRectArray)
            or not isinstance(raw_resized, AssociativeRectArray)
            or not isinstance(raw_revision, int)
        ):
            return
        token, array, resized, revision = raw_token, raw_array, raw_resized, raw_revision
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            editor.canvas.finish_array_spacing_commit(token, "文档已关闭。")
            return

        def commit() -> object:
            if (
                self._loaded is not loaded
                or self._sketch_dialog is not editor
                or self._session_id != session_id
                or loaded.document.revision != revision
                or not editor.canvas.array_spacing_commit_is_current(token, revision)
                or array not in services.kernel.associative_arrays
            ):
                raise ValidationError("文档或阵列已变化，请重新拖动。")
            return loaded.bus.execute(
                "drawing.array.resize",
                {"array": resized.to_mapping()},
                confirmed_by="local",
                version=16
                if mycad_app.revisions_require_attachment_protection(
                    services,
                    tuple(
                        {"sketch_id": ref.sketch_id}
                        for ref in (
                            *array.sources,
                            *(member.target for member in array.members),
                            *(member.target for member in resized.members),
                            *(output.target for output in array.extra_outputs),
                        )
                    ),
                )
                else 15
                if any(output.rotation_deg != 0 for output in resized.extra_outputs)
                else 14
                if any(output.offset_mm != (0, 0) for output in resized.extra_outputs)
                else 13
                if resized.extra_outputs != array.extra_outputs
                else 12
                if resized.extra_outputs
                else 11
                if any(
                    member.replacement is not None and member.replacement.anchor_source is not None
                    for member in resized.members
                )
                else 10
                if has_interleaved_array_dependencies(
                    tuple(
                        resized if item.array_id == resized.array_id else item
                        for item in services.kernel.associative_arrays
                    )
                )
                else 9
                if has_internal_replacements(resized)
                else 8
                if any(member.replacement is not None for member in resized.members)
                else 7
                if any(member.erased_neighbors is not None for member in resized.members)
                else 6
                if any(member.erased_index is not None for member in resized.members)
                else 5
                if any(member.rotation_deg != 0 for member in resized.members)
                else 4
                if any(member.offset_mm != (0, 0) for member in resized.members)
                else 3
                if resized.base_point is not None
                else 2
                if resized.angle_deg != 0
                else 1,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            editor.canvas.finish_array_spacing_commit(token, result.error)
            if result.error is None:
                self._sync_drawing_layers()
                editor.layer_history_boundaries[len(loaded.document.commands)] = (
                    editor.canvas.history_position
                )
                editor.layer_history_redo.clear()
                editor.canvas.discard_redo_history()

        if not unit.submit(
            commit, operation="array-count-grip", session_id=session_id, on_complete=finish
        ):
            editor.canvas.finish_array_spacing_commit(token, "几何工作线程忙碌，请重试。")

    def _on_array_move_grip_commit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_token: object,
        raw_array: object,
        raw_displacement: object,
        raw_revision: object,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            not isinstance(raw_token, str)
            or not isinstance(raw_array, AssociativeRectArray)
            or not isinstance(raw_displacement, tuple)
            or not isinstance(raw_revision, int)
        ):
            return
        values = cast("tuple[object, ...]", raw_displacement)
        if len(values) != 2 or any(not isinstance(value, int | float) for value in values):
            return
        token, array, revision = raw_token, raw_array, raw_revision
        displacement = cast("tuple[float, float]", values)
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            editor.canvas.finish_array_spacing_commit(token, "文档已关闭。")
            return

        def commit() -> object:
            if (
                self._loaded is not loaded
                or self._sketch_dialog is not editor
                or self._session_id != session_id
                or loaded.document.revision != revision
                or not editor.canvas.array_spacing_commit_is_current(token, revision)
                or array not in services.kernel.associative_arrays
            ):
                raise ValidationError("文档或阵列已变化，请重新拖动。")
            return loaded.bus.execute(
                "drawing.array.move",
                {"array_id": array.array_id, "displacement": list(displacement)},
                confirmed_by="local",
                version=3
                if set(array.sources)
                & {
                    output.target
                    for item in services.kernel.associative_arrays
                    for output in item.extra_outputs
                }
                else 2,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            editor.canvas.finish_array_spacing_commit(token, result.error)
            if result.error is None:
                self._sync_drawing_layers()
                editor.layer_history_boundaries[len(loaded.document.commands)] = (
                    editor.canvas.history_position
                )
                editor.layer_history_redo.clear()
                editor.canvas.discard_redo_history()

        if not unit.submit(
            commit, operation="array-move-grip", session_id=session_id, on_complete=finish
        ):
            editor.canvas.finish_array_spacing_commit(token, "几何工作线程忙碌，请重试。")

    def _sync_drawing_group_menu(self) -> None:
        editor = self._sketch_dialog
        enabled = editor is not None and editor.canvas.select_committed_entities
        self.drawing_group_menu.setEnabled(enabled)
        self.drawing_block_menu.setEnabled(enabled)

    @staticmethod
    def _require_collection_action_ready(editor: SketchEditorDialog) -> None:
        canvas = editor.canvas
        if (
            canvas.has_pending_geometry
            or canvas.has_active_edit_gesture
            or (canvas.text_tools is not None and canvas.text_tools.pending)
            or (
                canvas.geometric_tolerance_tools is not None
                and canvas.geometric_tolerance_tools.pending
            )
        ):
            raise ValidationError("请先完成或取消当前绘图、文字或标注操作。")

    def _run_drawing_block_menu(self, action: str) -> None:
        editor = self._sketch_dialog
        if editor is None or not editor.canvas.select_committed_entities:
            return
        if action == "create":
            self._create_drawing_block(editor)
        elif action == "insert":
            self._insert_drawing_block(editor)
        elif action == "explode":
            self._explode_drawing_block(editor)
        elif action == "edit":
            self._edit_drawing_block(editor)
        elif action == "manage":
            self._manage_drawing_blocks(editor)
        elif action == "library":
            editor.drawing_command_bar.remember_collection_command("blocklib")
            self._open_block_library(editor)
        elif action == "write":
            editor.drawing_command_bar.remember_collection_command("wblock")
            selected = editor.canvas.selected_block_instance_ids
            if len(selected) == 1:
                view = self._collection_view(editor)
                instance = next(
                    (item for item in view.block_instances if item.instance_id in selected), None
                )
                if instance is not None:
                    self._save_definition_to_library(editor, instance.definition_id)
                    return
            self._manage_drawing_blocks(editor)

    def _manage_drawing_blocks(self, editor: SketchEditorDialog) -> None:
        from mycad.core.drawing_blocks import validate_block_definition_edit
        from mycad.ui.drawing_block_dialogs import BlockManagerDialog

        def remove(identity: str) -> None:
            self._require_collection_action_ready(editor)
            view = self._collection_view(editor)
            if any(item.definition_id == identity for item in view.block_instances):
                raise ValidationError("块定义仍被实例引用，无法删除。")
            definition = next(
                (item for item in view.block_definitions if item.definition_id == identity), None
            )
            if definition is None:
                raise ValidationError("块定义已变化，请重新选择。")
            validate_block_definition_edit(definition, (), view.layers, view.text_styles)
            session = self._ensure_collection_session(editor)
            current = session.snapshot
            if definition not in current.block_definitions or any(
                item.definition_id == identity for item in current.block_instances
            ):
                raise ValidationError("块定义或实例已变化，请重新选择。")
            validate_block_definition_edit(definition, (), current.layers, current.text_styles)
            if not editor.canvas.stage_collection_operation(
                ReplayAppend("drawing.block.remove", 1, {"definition_id": identity}, "local")
            ):
                raise ValidationError(editor.canvas.message)

        def rename(identity: str, name: str) -> None:
            self._require_collection_action_ready(editor)
            view = self._collection_view(editor)
            definition = next(
                (item for item in view.block_definitions if item.definition_id == identity), None
            )
            if definition is None:
                raise ValidationError("块定义已变化，请重新选择。")
            if not name:
                raise ValidationError("请输入块定义名称。")
            if any(
                item.definition_id != identity and item.name.casefold() == name.casefold()
                for item in view.block_definitions
            ):
                raise ValidationError("块定义名称已存在。")
            if definition.name == name:
                raise ValidationError("块定义名称没有变化。")
            updated = replace(definition, name=name)
            affected = tuple(
                item for item in view.block_instances if item.definition_id == identity
            )
            validate_block_definition_edit(definition, affected, view.layers, view.text_styles)
            validate_block_definition_edit(updated, affected, view.layers, view.text_styles)
            session = self._ensure_collection_session(editor)
            current = session.snapshot
            if definition not in current.block_definitions:
                raise ValidationError("块定义已变化，请重新选择。")
            affected = tuple(
                item for item in current.block_instances if item.definition_id == identity
            )
            validate_block_definition_edit(
                definition, affected, current.layers, current.text_styles
            )
            validate_block_definition_edit(updated, affected, current.layers, current.text_styles)
            if not editor.canvas.stage_collection_operation(
                ReplayAppend("drawing.block.update", 1, updated.to_mapping(), "local")
            ):
                raise ValidationError(editor.canvas.message)

        try:
            self._require_collection_action_ready(editor)
            BlockManagerDialog(
                lambda: self._collection_view(editor),
                remove,
                rename,
                editor,
                save_to_library=lambda identity: self._save_definition_to_library(editor, identity),
            ).exec()
        except ValidationError as exc:
            editor.status_label.setText(str(exc))

    def _block_library_store(self):
        """Build configured roots without putting filesystem paths into documents."""
        from mycad.libraries.block_store import BlockLibraryStore
        from mycad.ui.block_library_settings import library_roots

        root_path = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
            / "block-library"
        )
        root_path.mkdir(parents=True, exist_ok=True)
        cache = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "block-library"
        )
        roots = library_roots(QSettings(ORG_NAME, APP_NAME), root_path)
        return BlockLibraryStore(roots, cache), roots

    def _save_definition_to_library(self, editor: SketchEditorDialog, identity: str) -> None:
        from mycad.core.block_library import AssetMetadata, capture_block_asset
        from mycad.ui.block_library_dialog import BlockLibrarySaveDialog

        view = self._collection_view(editor)
        definition = next(
            (item for item in view.block_definitions if item.definition_id == identity), None
        )
        if definition is None:
            raise ValidationError("块定义已变化，请重新选择。")
        loaded, session_id = self._loaded, self._session_id
        store, roots = self._block_library_store()
        local = next((root for root in roots if not root.read_only), None)
        if local is None:
            raise ValidationError("没有可写入的本地块库。")

        def save(name: str, description: str, tags: tuple[str, ...], category: str) -> str:
            self._require_collection_action_ready(editor)
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._collection_view(editor) != view
            ):
                raise ValidationError("图纸已变化，请重新选择块。")
            asset = capture_block_asset(
                view, identity, AssetMetadata(name, description, tags), asset_id=uuid4().hex
            )
            receipt = store.save(local.root_id, category, asset, expected_digest=None)
            return str(local.path / receipt.relative_path)

        preview_asset = capture_block_asset(
            view, identity, AssetMetadata(definition.name, "", ()), asset_id=uuid4().hex
        )
        dialog = BlockLibrarySaveDialog(definition.name, save, editor, preview_asset=preview_asset)
        dialog.exec()
        dialog.deleteLater()

    def _open_block_library(self, editor: SketchEditorDialog) -> None:
        from mycad.core.block_library_import import AssetIssue, BlockPlacement
        from mycad.ui.block_library_controller import BlockLibraryController
        from mycad.ui.block_library_dialog import (
            IMPORT_DEFINITION,
            INSERT_BLOCK,
            BlockLibraryDialog,
        )
        from mycad.ui.drawing_block_dialogs import PICK_POINT, BlockInsertDialog

        try:
            self._require_collection_action_ready(editor)
            session = self._ensure_collection_session(editor)
            store, roots = self._block_library_store()

            def stage(operation: ReplayAppend) -> None:
                if not editor.canvas.stage_collection_operation(operation):
                    raise ValidationError(editor.canvas.message)

            def configure_shared(add: bool, path: Path):
                from mycad.ui.block_library_settings import (
                    add_shared_directory,
                    remove_shared_directory,
                )

                settings = QSettings(ORG_NAME, APP_NAME)
                (add_shared_directory if add else remove_shared_directory)(settings, path)
                return self._block_library_store()

            dialog = BlockLibraryDialog(store, roots, editor, configure_shared=configure_shared)
            choice = dialog.exec()
            selected_store = dialog.store
            entry = dialog.selected_entry()
            dialog.deleteLater()
            if choice not in (IMPORT_DEFINITION, INSERT_BLOCK) or entry is None:
                return
            controller = BlockLibraryController(
                selected_store,
                lambda: session.snapshot,
                session.checkpoint,
                stage,
                session.preview_operation,
            )

            def proceed() -> None:
                try:
                    if self._sketch_dialog is not editor:
                        raise ValidationError("图纸已切换，请重新选择块。")

                    def accept_issues(issues: tuple[AssetIssue, ...]) -> bool:
                        if not issues:
                            return True
                        result = QMessageBox.question(
                            editor,
                            "块库导入提示",
                            "\n".join(issue.message for issue in issues) + "\n是否继续？",
                            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                            QMessageBox.StandardButton.Cancel,
                        )
                        return result == QMessageBox.StandardButton.Ok

                    if choice == IMPORT_DEFINITION:
                        preview = controller.prepare_import(entry, None)
                        if not accept_issues(preview.prepared.issues):
                            controller.cancel_import()
                            return
                        controller.confirm_import(preview)
                        editor.canvas.message = (
                            "块定义已存在，可使用插入块。"
                            if preview.prepared.operation is None
                            else "已导入块定义；可撤销或完成草稿提交。"
                        )
                        editor.status_label.setText(editor.canvas.message)
                        return
                    placement = BlockInsertDialog(
                        (entry.asset.definition,), editor, allow_library=False
                    )

                    def show_placement() -> None:
                        result = placement.exec()
                        if result == PICK_POINT:
                            from mycad.core.drawing_collection_preview import (
                                collection_preview_payload,
                            )

                            frame = self._block_point_frame(editor)
                            rotation, scale = (
                                placement.rotation_field.value(),
                                placement.scale_field.precise_value(),
                            )
                            layer = editor.canvas.active_layer_name
                            initial = (placement.x_field.value(), placement.y_field.value())
                            preview = controller.prepare_import(
                                entry, BlockPlacement(initial, rotation, scale, layer)
                            )
                            if not accept_issues(preview.prepared.issues):
                                controller.cancel_import()
                                return
                            position = initial

                            def update_preview(point: tuple[float, float]):
                                nonlocal preview, position
                                if editor.current_frame() != frame:
                                    raise ValidationError("工作平面已变化，请重新拾取块插入点。")
                                drawing_point = WorkPlaneFrame.xy().world_to_local(
                                    frame.local_to_world(point)
                                )
                                if drawing_point != position:
                                    preview = controller.reposition_preview(
                                        preview,
                                        BlockPlacement(drawing_point, rotation, scale, layer),
                                    )
                                    position = drawing_point
                                return collection_preview_payload(
                                    preview.snapshot, preview.candidate
                                )

                            def pick(point: tuple[float, float]) -> None:
                                try:
                                    update_preview(point)
                                    controller.confirm_import(preview)
                                    editor.canvas.message = "已插入块；可撤销或完成草稿提交。"
                                    editor.status_label.setText(editor.canvas.message)
                                except (KeyError, ValueError, ValidationError) as exc:
                                    editor.canvas.message = str(exc)
                                    editor.status_label.setText(editor.canvas.message)

                            editor.canvas.begin_block_point_capture(
                                pick,
                                "指定块插入点；单击、Enter 或右键确认，Esc 取消。",
                                preview=update_preview,
                                cancel=controller.cancel_import,
                            )
                            return
                        if result != QDialog.DialogCode.Accepted:
                            controller.cancel_import()
                            return
                        selected = BlockPlacement(
                            (placement.x_field.value(), placement.y_field.value()),
                            placement.rotation_field.value(),
                            placement.scale_field.precise_value(),
                            editor.canvas.active_layer_name,
                        )
                        preview = controller.prepare_import(entry, selected)
                        if not accept_issues(preview.prepared.issues):
                            controller.cancel_import()
                            return
                        controller.confirm_import(preview)
                        editor.canvas.message = "已插入块；可撤销或完成草稿提交。"
                        editor.status_label.setText(editor.canvas.message)

                    show_placement()
                except (OSError, KeyError, ValueError, ValidationError) as exc:
                    if isValid(editor):
                        editor.canvas.message = str(exc)
                        editor.status_label.setText(editor.canvas.message)

            QTimer.singleShot(0, proceed)
        except (OSError, KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(editor.canvas.message)

    def active_block_editor(self) -> DrawingBlockEditorDialog | None:
        return self._block_editor if self._block_editor and self._block_editor.isVisible() else None

    def _close_block_editor(self, loaded: LoadedDocument | None = None) -> bool:
        editor = self.active_block_editor()
        if editor is None or (loaded is not None and not editor.session.belongs_to(loaded)):
            return True
        return editor.close()

    def _edit_drawing_block(self, editor: SketchEditorDialog) -> None:
        from mycad.ui.drawing_block_editor import (
            DrawingBlockEditorDialog,
            DrawingBlockEditorSession,
        )

        editor.drawing_command_bar.remember_collection_command("bedit")

        loaded, services = self._loaded, self._services
        if loaded is None or services is None or editor is not self._sketch_dialog:
            return
        unit = self.execution_unit

        def worker_available() -> bool:
            return unit is None or not (
                unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result
            )

        if not worker_available():
            editor.status_label.setText("几何工作线程忙碌，请稍后编辑块定义。")
            return
        if self.active_block_editor() is not None:
            editor.status_label.setText("已有打开的块编辑会话。")
            return
        canvas = editor.canvas

        def draft_in_progress() -> bool:
            current = self._sketch_dialog
            if current is None:
                return False
            canvas = current.canvas
            return bool(
                canvas.collection_session is not None
                or canvas.mixed_move is not None
                or canvas.entities
                or canvas.constraints
                or canvas.pending_cross_tangencies
                or canvas.pending_associative_arrays
                or canvas.has_pending_geometry
                or canvas.has_active_edit_gesture
                or (canvas.text_tools is not None and canvas.text_tools.pending)
                or (
                    canvas.geometric_tolerance_tools is not None
                    and canvas.geometric_tolerance_tools.pending
                )
            )

        if draft_in_progress():
            editor.status_label.setText("请先完成或取消当前草稿，再编辑块定义。")
            return
        identity = self._session_id
        selected = canvas.selected_block_instance_ids
        if len(selected) > 1:
            editor.status_label.setText("请只选择一个块实例，或取消选择后按名称选择定义。")
            return
        if selected:
            instance = next(
                (
                    item
                    for item in services.kernel.drawing_block_instances
                    if item.instance_id in selected
                ),
                None,
            )
            if instance is None:
                editor.status_label.setText("所选块实例不存在。")
                return
            definition_id = instance.definition_id
        else:
            definitions = services.kernel.drawing_block_definitions
            if not definitions:
                editor.status_label.setText("当前图纸没有块定义。")
                return
            names = [item.name for item in definitions]
            chosen, accepted = QInputDialog.getItem(
                editor, "编辑块定义", "选择要编辑的块：", names, 0, False
            )
            if not accepted:
                return
            if chosen not in names:
                editor.status_label.setText("所选块定义已变化。")
                return
            definition = definitions[names.index(chosen)]
            if (
                self._loaded is not loaded
                or self._services is not services
                or self._sketch_dialog is not editor
                or self._session_id != identity
                or definition not in services.kernel.drawing_block_definitions
            ):
                editor.status_label.setText("图纸或所选块定义已变化，请重新选择。")
                return
            if self.active_block_editor() is not None:
                editor.status_label.setText("已有打开的块编辑会话。")
                return
            if draft_in_progress():
                editor.status_label.setText("请先完成或取消当前草稿，再编辑块定义。")
                return
            definition_id = definition.definition_id
        if not worker_available():
            editor.status_label.setText("几何工作线程忙碌，请稍后编辑块定义。")
            return
        session = DrawingBlockEditorSession(
            services,
            loaded,
            definition_id,
            is_current_document=lambda: (
                self._loaded is loaded
                and self._services is services
                and self._session_id == identity
            ),
            can_write=worker_available,
            source_has_draft=draft_in_progress,
        )
        block_editor = DrawingBlockEditorDialog(
            session, services.kernel.drawing_layers, services.kernel.drawing_text_styles, self
        )
        self._block_editor = block_editor

        def saved() -> None:
            if self._loaded is loaded and self._services is services:
                current = self._sketch_dialog
                if current is not None:
                    current.canvas.set_source_context_revision(loaded.document.revision)
                self._sync_drawing_layers()
                self._refresh_document_choice()

        block_editor.saved.connect(saved)

        def closed(_result: int) -> None:
            if self._block_editor is block_editor:
                self._block_editor = None

        block_editor.finished.connect(closed)
        block_editor.show()

    def _explode_drawing_block(self, editor: SketchEditorDialog) -> None:
        from mycad.core.drawing_block_transactions import prepare_block_explode

        editor.drawing_command_bar.remember_collection_command("explode")
        try:
            self._require_collection_action_ready(editor)
            selected = editor.canvas.selected_block_instance_ids
            if len(selected) != 1:
                raise ValidationError("请选中一个块实例进行分解。")
            instance_id = next(iter(selected))
            view = self._collection_view(editor)
            operation = prepare_block_explode(view, instance_id)
            session = self._ensure_collection_session(editor)
            if session.snapshot != view:
                operation = prepare_block_explode(session.snapshot, instance_id)
            if not editor.canvas.stage_collection_operation(operation):
                raise ValidationError(editor.canvas.message)
            editor.canvas.selected_block_instance_ids.clear()
            editor.canvas.message = "已暂存块分解；可撤销或完成草稿提交。"
            editor.status_label.setText(editor.canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(editor.canvas.message)

    @staticmethod
    def _block_point_frame(editor: SketchEditorDialog) -> WorkPlaneFrame:
        from mycad.core.cross_sketch_tangency import project_coplanar_rotation

        frame = editor.current_frame()
        try:
            project_coplanar_rotation(0, frame, WorkPlaneFrame.xy())
        except ValueError as exc:
            raise ValidationError("画布拾取块位置要求工作平面与图纸平面共面。") from exc
        return frame

    def _create_drawing_block(self, editor: SketchEditorDialog) -> None:
        from mycad.core.drawing_block_transactions import prepare_block_create
        from mycad.ui.drawing_block_dialogs import PICK_POINT, BlockCreateDialog

        if not editor.canvas.select_committed_entities:
            editor.status_label.setText("块仅支持独立二维草图文档。")
            return
        try:
            self._require_collection_action_ready(editor)
            editor.drawing_command_bar.remember_collection_command("block")
            view = self._collection_view(editor)
            seeds = self._selected_group_refs(editor, view)
            if not seeds:
                editor.drawing_command_bar.begin_block_selection()
                editor.status_label.setText(editor.canvas.message)
                return
            dialog = BlockCreateDialog(editor)
            loaded, identity, source_session = (
                self._loaded,
                self._session_id,
                editor.canvas.collection_session,
            )
            creation_layer = editor.canvas.active_layer_name

            def require_current_view() -> None:
                self._require_collection_action_ready(editor)
                if (
                    self._loaded is not loaded
                    or self._session_id != identity
                    or self._sketch_dialog is not editor
                    or editor.canvas.collection_session is not source_session
                    or self._collection_view(editor) != view
                    or self._selected_group_refs(editor, view) != seeds
                    or editor.canvas.active_layer_name != creation_layer
                ):
                    raise ValidationError("图纸或块来源已变化，请重新选择。")

            prepared: ReplayAppend | None = None

            def validate_creation() -> str | None:
                nonlocal prepared
                prepared = None
                try:
                    require_current_view()
                    prepared = prepare_block_create(
                        view,
                        seeds,
                        dialog.name_field.text().strip(),
                        (dialog.base_x.value(), dialog.base_y.value()),
                        convert_sources=bool(dialog.source_mode.currentData()),
                        layer_name=creation_layer,
                    )
                except (KeyError, ValueError, ValidationError) as exc:
                    message = str(exc)
                    if "块定义仅支持几何和文字" in message:
                        message += " 请取消选择尺寸、公差、基准、图片或块实例后重试。"
                        message += " 如果这些对象属于组，请先关闭组选择或调整组成员。"
                    elif "尺寸或约束关联" in message:
                        message += " 可选择“保留源对象”创建块。"
                    return message
                return None

            dialog.validate_creation = validate_creation

            def show_dialog() -> None:
                try:
                    result = dialog.exec()
                    if result in (PICK_POINT, QDialog.DialogCode.Accepted):
                        require_current_view()
                    if result == PICK_POINT:
                        point_frame = self._block_point_frame(editor)

                        def accept_point(point: tuple[float, float]) -> None:
                            try:
                                require_current_view()
                                if editor.current_frame() != point_frame:
                                    raise ValidationError("工作平面已变化，请重新拾取块基点。")
                                drawing_point = WorkPlaneFrame.xy().world_to_local(
                                    point_frame.local_to_world(point)
                                )
                                dialog.base_x.setValue(drawing_point[0])
                                dialog.base_y.setValue(drawing_point[1])
                                show_dialog()
                            except (KeyError, ValueError, ValidationError) as exc:
                                editor.canvas.message = str(exc)
                                editor.status_label.setText(editor.canvas.message)

                        editor.canvas.begin_block_point_capture(
                            accept_point, "请在画布指定块基点。"
                        )
                        return
                    if result != QDialog.DialogCode.Accepted:
                        editor.canvas.message = "BLOCK：已取消创建块。"
                        editor.status_label.setText(editor.canvas.message)
                        editor.drawing_command_bar.status.setText(editor.canvas.message)
                        return
                    convert = bool(dialog.source_mode.currentData())
                    operation = prepared or prepare_block_create(
                        view,
                        seeds,
                        dialog.name_field.text().strip(),
                        (dialog.base_x.value(), dialog.base_y.value()),
                        convert_sources=convert,
                        layer_name=creation_layer,
                    )
                    session = self._ensure_collection_session(editor)
                    before = session.snapshot
                    if before != view:
                        operation = prepare_block_create(
                            before,
                            seeds,
                            dialog.name_field.text().strip(),
                            (dialog.base_x.value(), dialog.base_y.value()),
                            convert_sources=convert,
                            layer_name=creation_layer,
                        )
                    if not editor.canvas.stage_collection_operation(operation):
                        raise ValidationError(editor.canvas.message)
                    if convert:
                        existing = {item.instance_id for item in before.block_instances}
                        created = [
                            item
                            for item in session.snapshot.block_instances
                            if item.instance_id not in existing
                        ]
                        if len(created) == 1:
                            editor.canvas.selected_entity_ids.clear()
                            editor.canvas.selected_constraint_ids.clear()
                            editor.canvas.selected_raster_ids.clear()
                            if editor.canvas.text_tools is not None:
                                editor.canvas.text_tools.selected_ids.clear()
                            editor.canvas.selected_block_instance_ids = {created[0].instance_id}
                    editor.canvas.message = "BLOCK：已暂存块定义；可撤销或完成草稿提交。"
                    editor.status_label.setText(editor.canvas.message)
                    editor.drawing_command_bar.status.setText(editor.canvas.message)
                except (KeyError, ValueError, ValidationError) as exc:
                    editor.canvas.message = str(exc)
                    editor.status_label.setText(editor.canvas.message)
                    editor.drawing_command_bar.status.setText(editor.canvas.message)

            show_dialog()
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(editor.canvas.message)

    def _insert_drawing_block(self, editor: SketchEditorDialog) -> None:
        from mycad.core.drawing_blocks import BlockInstance, validate_block_instance
        from mycad.ui.drawing_block_dialogs import OPEN_BLOCK_LIBRARY, PICK_POINT, BlockInsertDialog

        editor.drawing_command_bar.remember_collection_command("insert")
        if not editor.canvas.select_committed_entities:
            editor.status_label.setText("块仅支持独立二维草图文档。")
            return
        try:
            self._require_collection_action_ready(editor)
            view = self._collection_view(editor)
            if not view.block_definitions:
                self._open_block_library(editor)
                return
            dialog = BlockInsertDialog(view.block_definitions, editor)
            loaded, identity, source_session = (
                self._loaded,
                self._session_id,
                editor.canvas.collection_session,
            )
            insertion_layer = editor.canvas.active_layer_name

            def require_current_view() -> None:
                self._require_collection_action_ready(editor)
                if (
                    self._loaded is not loaded
                    or self._session_id != identity
                    or self._sketch_dialog is not editor
                    or editor.canvas.collection_session is not source_session
                    or self._collection_view(editor) != view
                    or editor.canvas.active_layer_name != insertion_layer
                ):
                    raise ValidationError("图纸或块定义已变化，请重新选择。")

            def show_dialog() -> None:
                try:
                    result = dialog.exec()
                    if result == OPEN_BLOCK_LIBRARY:
                        QTimer.singleShot(0, lambda: self._open_block_library(editor))
                        return
                    if result in (PICK_POINT, QDialog.DialogCode.Accepted):
                        require_current_view()
                    if result == PICK_POINT:
                        point_frame = self._block_point_frame(editor)

                        def accept_point(point: tuple[float, float]) -> None:
                            try:
                                require_current_view()
                                if editor.current_frame() != point_frame:
                                    raise ValidationError("工作平面已变化，请重新拾取块插入点。")
                                drawing_point = WorkPlaneFrame.xy().world_to_local(
                                    point_frame.local_to_world(point)
                                )
                                dialog.x_field.setValue(drawing_point[0])
                                dialog.y_field.setValue(drawing_point[1])
                                show_dialog()
                            except (KeyError, ValueError, ValidationError) as exc:
                                editor.canvas.message = str(exc)
                                editor.status_label.setText(editor.canvas.message)

                        editor.canvas.begin_block_point_capture(
                            accept_point, "请在画布指定块插入点。"
                        )
                        return
                    if result != QDialog.DialogCode.Accepted:
                        return
                    identity = dialog.definition_field.currentData()
                    if not isinstance(identity, str):
                        raise ValidationError("请选择块定义。")
                    definition = next(
                        (item for item in view.block_definitions if item.definition_id == identity),
                        None,
                    )
                    if definition is None:
                        raise ValidationError("块定义已变化，请重新选择。")
                    instance = BlockInstance(
                        uuid4().hex,
                        identity,
                        (dialog.x_field.value(), dialog.y_field.value()),
                        dialog.rotation_field.value(),
                        dialog.scale_field.precise_value(),
                        insertion_layer,
                    )
                    validate_block_instance(definition, instance, view.layers, view.text_styles)
                    session = self._ensure_collection_session(editor)
                    current = session.snapshot
                    if definition not in current.block_definitions:
                        raise ValidationError("块定义已变化，请重新选择。")
                    if current != view:
                        validate_block_instance(
                            definition, instance, current.layers, current.text_styles
                        )
                    if not editor.canvas.stage_collection_operation(
                        ReplayAppend(
                            "drawing.block_instance.insert", 1, instance.to_mapping(), "local"
                        )
                    ):
                        raise ValidationError(editor.canvas.message)
                    editor.canvas.message = "已暂存块实例；可撤销或完成草稿提交。"
                    editor.status_label.setText(editor.canvas.message)
                except (KeyError, ValueError, ValidationError) as exc:
                    editor.canvas.message = str(exc)
                    editor.status_label.setText(editor.canvas.message)

            show_dialog()
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(editor.canvas.message)

    def _run_drawing_group_menu(self, action: str) -> None:
        editor = self._sketch_dialog
        if editor is None or not editor.canvas.select_committed_entities:
            return
        if action == "group":
            self._create_drawing_group(editor)
        elif action == "ungroup":
            self._remove_drawing_group(editor)
        elif action == "edit":
            self._edit_drawing_group(editor)

    def _collection_view(self, editor: SketchEditorDialog) -> DrawingCollectionSnapshot:
        services = self._services
        if services is None or editor is not self._sketch_dialog:
            raise ValidationError("当前二维文档不可用。")
        if editor.canvas.collection_session is not None:
            return editor.canvas.collection_session.snapshot
        snapshot = mycad_app.drawing_collection_snapshot(services)
        draft = Sketch(
            editor.draft_sketch_id,
            editor.current_frame(),
            tuple(editor.canvas.entities),
            tuple(editor.canvas.constraints),
            editor.layer_table,
        )
        return replace(snapshot, sketches=(*snapshot.sketches, draft))

    def _effective_group_selection(self, editor: SketchEditorDialog) -> frozenset[DrawingObjectRef]:
        from mycad.core.drawing_groups import expand_group_selection

        services = self._services
        if services is None or editor is not self._sketch_dialog:
            return frozenset()
        try:
            if editor.canvas.collection_session is None and not services.kernel.drawing_groups:
                return frozenset()
            snapshot = self._collection_view(editor)
            if not snapshot.groups:
                return frozenset()
            return expand_group_selection(
                self._selected_group_refs(editor, snapshot), snapshot.groups
            )
        except (KeyError, ValueError, ValidationError):
            return frozenset()

    def _group_clipboard_requires_support(self, editor: SketchEditorDialog) -> bool:
        try:
            if editor.canvas.selected_block_instance_ids:
                return True
            if (
                editor.canvas.collection_session is None
                and self._services is not None
                and not self._services.kernel.drawing_groups
            ):
                return False
            snapshot = self._collection_view(editor)
            if not snapshot.groups:
                return False
            direct = frozenset(self._selected_group_refs(editor, snapshot))
            return any(
                bool(direct.intersection(group.members))
                and (group.selectable or set(group.members).issubset(direct))
                for group in snapshot.groups
            )
        except (KeyError, ValueError, ValidationError):
            return True

    def _capture_collection_clipboard(
        self, editor: SketchEditorDialog, *, include_internal_dimensions: bool = False
    ) -> tuple[bytes, bool]:
        from mycad.core.drawing_collection_clipboard import (
            capture_collection_clipboard,
            encode_collection_clipboard,
        )
        from mycad.core.drawing_groups import DrawingObjectRef, expand_group_selection

        snapshot = self._collection_view(editor)
        seeds = self._selected_group_refs(editor, snapshot)
        direct_selection = frozenset(seeds)
        if include_internal_dimensions:
            selected_geometry = {ref for ref in seeds if ref.kind == "geometry"}
            extra = tuple(
                DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                for sketch in snapshot.sketches
                for constraint in sketch.constraints
                if constraint.kind in DIMENSION_KINDS
                and constraint.references
                and all(
                    DrawingObjectRef("geometry", ref.entity_id, sketch.sketch_id)
                    in selected_geometry
                    for ref in constraint.references
                )
            )
            seeds = tuple(dict.fromkeys((*seeds, *extra)))
        selected = (
            frozenset(seeds)
            if include_internal_dimensions
            else expand_group_selection(seeds, snapshot.groups)
        )
        omitted = any(
            sum(
                DrawingObjectRef("geometry", ref.entity_id, ref.sketch_id) in selected
                for ref in (relation.first, relation.second)
            )
            == 1
            for relation in snapshot.cross_tangencies
        ) or any(
            any(
                DrawingObjectRef("geometry", ref.entity_id, sketch.sketch_id) in selected
                for ref in constraint.references
            )
            and (
                not all(
                    DrawingObjectRef("geometry", ref.entity_id, sketch.sketch_id) in selected
                    for ref in constraint.references
                )
                or (
                    constraint.kind in DIMENSION_KINDS
                    and DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                    not in selected
                )
            )
            for sketch in snapshot.sketches
            for constraint in sketch.constraints
        )
        tools = editor.canvas.geometric_tolerance_tools
        payload = capture_collection_clipboard(
            snapshot,
            seeds,
            expand_selection=not include_internal_dimensions,
            source_token=tools.clipboard_source if tools is not None else None,
        )
        if include_internal_dimensions:
            payload = replace(
                payload,
                groups=tuple(
                    group
                    for group in payload.groups
                    if set(group.members).issubset(direct_selection)
                ),
            )
        return encode_collection_clipboard(payload), omitted

    def _begin_collection_paste(self, editor: SketchEditorDialog) -> bool:
        try:
            self._ensure_collection_session(editor)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.status_label.setText(str(exc))
            return False
        return True

    def _commit_collection_paste(
        self,
        editor: SketchEditorDialog,
        payload: DrawingCollectionClipboard,
        delta: tuple[float, float],
    ) -> bool:
        from mycad.core.cross_sketch_tangency import project_coplanar_vector
        from mycad.core.drawing_collection_clipboard import prepare_collection_paste

        session = editor.canvas.collection_session
        if session is None:
            return False
        try:
            drawing_delta = project_coplanar_vector(
                delta, editor.current_frame(), WorkPlaneFrame.xy()
            )
            preview = editor.canvas.collection_paste_preview
            if (
                preview is not None
                and preview.checkpoint == session.checkpoint()
                and preview.frame == editor.current_frame()
                and preview.displacement == delta
                and preview.source == payload
            ):
                operation = preview.operation
            else:
                tools = editor.canvas.geometric_tolerance_tools
                operation = prepare_collection_paste(
                    payload,
                    session.snapshot,
                    drawing_delta,
                    datum_relayout=tools.relayout_recorded_datum if tools is not None else None,
                    preserve_external=bool(
                        payload.source_token is not None
                        and tools is not None
                        and payload.source_token == tools.clipboard_source
                    ),
                )
            if not editor.canvas.stage_collection_operation(operation):
                raise ValidationError(editor.canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(str(exc))
            return False
        return True

    def _preview_collection_paste(
        self,
        editor: SketchEditorDialog,
        payload: DrawingCollectionClipboard,
        delta: tuple[float, float],
    ) -> DrawingCollectionPastePreview:
        from mycad.core.cross_sketch_tangency import project_coplanar_vector
        from mycad.core.drawing_collection_clipboard import prepare_collection_paste
        from mycad.core.drawing_collection_preview import collection_preview_payload
        from mycad.ui.drawing_collection_session import DrawingCollectionPastePreview

        session = editor.canvas.collection_session
        if session is None:
            raise ValidationError("二维暂存会话不可用。")
        before = session.snapshot
        drawing_delta = project_coplanar_vector(delta, editor.current_frame(), WorkPlaneFrame.xy())
        tools = editor.canvas.geometric_tolerance_tools
        operation = prepare_collection_paste(
            payload,
            before,
            drawing_delta,
            datum_relayout=tools.relayout_recorded_datum if tools is not None else None,
            preserve_external=bool(
                payload.source_token is not None
                and tools is not None
                and payload.source_token == tools.clipboard_source
            ),
        )
        return DrawingCollectionPastePreview(
            session.checkpoint(),
            editor.current_frame(),
            delta,
            payload,
            operation,
            collection_preview_payload(before, session.preview_operation(operation)),
        )

    def _reject_group_member_edit(
        self, editor: SketchEditorDialog, changed: set[tuple[str, str]]
    ) -> None:
        if not changed:
            return
        session = editor.canvas.collection_session
        if session is not None:
            try:
                groups = session.snapshot.groups
            except ValidationError as exc:
                raise ValueError(str(exc)) from exc
        elif self._services is not None:
            groups = self._services.kernel.drawing_groups
        else:
            return
        if any(
            group.selectable
            and any((member.kind, member.object_id) in changed for member in group.members)
            for group in groups
        ):
            raise ValueError("组选择已启用；请先关闭组选择再编辑单个成员。")

    def _offset_group_member_allowed(
        self, editor: SketchEditorDialog, identity: str | DrawingObjectRef
    ) -> bool:
        if not isinstance(identity, str):
            session = editor.canvas.collection_session
            try:
                groups = (
                    session.snapshot.groups
                    if session is not None
                    else self._services.kernel.drawing_groups
                    if self._services is not None
                    else ()
                )
            except ValidationError:
                return False
            return not any(group.selectable and identity in group.members for group in groups)
        try:
            self._reject_group_member_edit(editor, {("geometry", identity)})
        except ValueError:
            return False
        return True

    def _require_independent_dimension_edit(
        self, editor: SketchEditorDialog, reference: DrawingObjectRef
    ) -> None:
        session = editor.canvas.collection_session
        if session is not None:
            groups = session.snapshot.groups
        elif self._services is not None:
            groups = self._services.kernel.drawing_groups
        else:
            raise ValidationError("当前二维文档不可用。")
        if any(group.selectable and reference in group.members for group in groups):
            raise ValidationError("组选择已启用；请先关闭组选择再编辑单个尺寸。")

    def _ensure_group_operation(
        self, editor: SketchEditorDialog, geometry_id: str | None = None
    ) -> bool:
        """Bring a saved selectable group's operation into the draft timeline."""
        canvas = editor.canvas
        services = self._services
        if canvas.collection_session is not None or services is None:
            return True
        selections: dict[str, set[str]] = {
            "geometry": canvas.selected_entity_ids | ({geometry_id} if geometry_id else set()),
            "dimension": canvas.selected_constraint_ids,
            "raster": canvas.selected_raster_ids,
            "block_instance": canvas.selected_block_instance_ids,
            "text": canvas.text_tools.selected_ids if canvas.text_tools is not None else set(),
        }
        annotations: set[str] = (
            canvas.geometric_tolerance_tools.selected_ids
            if canvas.geometric_tolerance_tools is not None
            else set()
        )
        selections.update(dict.fromkeys(("tolerance", "datum", "reference_dimension"), annotations))
        if not canvas.selected_block_instance_ids and not any(
            group.selectable
            and any(
                member.object_id in selections.get(member.kind, set()) for member in group.members
            )
            for group in services.kernel.drawing_groups
        ):
            return True
        try:
            self._ensure_collection_session(editor)
        except (KeyError, ValueError, ValidationError) as exc:
            canvas.message = str(exc)
            editor.status_label.setText(str(exc))
            return False
        return True

    def _ensure_collection_session(
        self, editor: SketchEditorDialog, *, allow_offset_completion: bool = False
    ) -> DrawingCollectionSession:
        from mycad.ui.drawing_collection_session import DrawingCollectionSession

        canvas = editor.canvas
        loaded, services = self._loaded, self._services
        if loaded is None or services is None or editor is not self._sketch_dialog:
            raise ValidationError("当前二维文档不可用。")
        if canvas.has_pending_geometry or (
            canvas.has_active_edit_gesture
            and not (allow_offset_completion and canvas.active_transform == "offset")
        ):
            raise ValidationError("请先完成当前绘图或编辑操作。")
        if (
            canvas.collection_session is None
            and canvas.source_context_revision is not None
            and canvas.source_context_revision != loaded.document.revision
        ):
            raise ValidationError("文档已变化；请刷新后重新选择对象。")
        session = canvas.collection_session
        if session is not None:
            return session
        draft = Sketch(
            editor.draft_sketch_id,
            editor.current_frame(),
            tuple(canvas.entities),
            constraints=tuple(canvas.constraints),
            layers=editor.layer_table,
        )
        session = DrawingCollectionSession(
            services,
            loaded,
            ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
            session_identity=self._session_id,
            session_identity_provider=lambda: self._session_id,
        )
        try:
            canvas.attach_collection_session(session, editor.draft_sketch_id)
        except Exception:
            session.cancel()
            raise
        return session

    @staticmethod
    def _selected_group_refs(
        editor: SketchEditorDialog,
        snapshot: DrawingCollectionSnapshot,
        *,
        excluded_constraint_ids: frozenset[str] = frozenset(),
    ) -> tuple[DrawingObjectRef, ...]:
        from mycad.core.drawing_groups import DrawingObjectRef

        canvas = editor.canvas
        catalog = [
            DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
            for sketch in snapshot.sketches
            for entity in sketch.entities
        ]
        catalog.extend(
            DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
            for sketch in snapshot.sketches
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
        )
        catalog.extend(DrawingObjectRef("text", item.text_id) for item in snapshot.texts)
        catalog.extend(DrawingObjectRef("raster", item.image_id) for item in snapshot.rasters)
        catalog.extend(
            DrawingObjectRef("block_instance", item.instance_id)
            for item in snapshot.block_instances
        )
        catalog.extend(DrawingObjectRef("tolerance", item.frame_id) for item in snapshot.frames)
        catalog.extend(DrawingObjectRef("datum", item.datum_id) for item in snapshot.datums)
        catalog.extend(
            DrawingObjectRef("reference_dimension", item.dimension_id)
            for item in snapshot.reference_dimensions
        )
        requested = [
            *(("geometry", identity) for identity in sorted(canvas.selected_entity_ids)),
            *(
                ("dimension", identity)
                for identity in sorted(canvas.selected_constraint_ids - excluded_constraint_ids)
            ),
            *(("raster", identity) for identity in sorted(canvas.selected_raster_ids)),
            *(
                ("block_instance", identity)
                for identity in sorted(canvas.selected_block_instance_ids)
            ),
            *(
                ("text", identity)
                for identity in sorted(
                    canvas.text_tools.selected_ids if canvas.text_tools is not None else ()
                )
            ),
        ]
        annotation_ids = (
            canvas.geometric_tolerance_tools.selected_ids
            if canvas.geometric_tolerance_tools is not None
            else ()
        )
        requested.extend(("annotation", identity) for identity in sorted(annotation_ids))
        members: list[DrawingObjectRef] = []
        for kind, identity in requested:
            if kind in {"geometry", "dimension"}:
                direct_refs = (
                    canvas.selected_geometry_refs
                    if kind == "geometry"
                    else canvas.selected_dimension_refs
                )
                picked = {ref for ref in direct_refs if ref.object_id == identity}
                if picked:
                    if not picked.issubset(catalog):
                        raise ValidationError("所选对象来源已变化；请重新选择。")
                    members.extend(sorted(picked, key=lambda item: item.sketch_id or ""))
                    continue
            matches = [
                item
                for item in catalog
                if item.object_id == identity
                and (
                    item.kind == kind
                    or kind == "annotation"
                    and item.kind in {"tolerance", "datum", "reference_dimension"}
                )
            ]
            if len(matches) != 1:
                raise ValidationError("所选对象不存在或身份不唯一。")
            if matches[0] not in members:
                members.append(matches[0])
        return tuple(members)

    def _create_drawing_group(self, editor: SketchEditorDialog) -> None:
        """Start an anonymous group from the current direct selection."""
        from mycad.core.drawing_groups import DrawingGroup
        from mycad.core.drawing_object_refs import validate_new_group_array_members

        canvas = editor.canvas
        try:
            self._require_collection_action_ready(editor)
        except ValidationError as exc:
            canvas.message = str(exc)
            editor.status_label.setText(canvas.message)
            return
        editor.drawing_command_bar.remember_collection_command("group")
        if not (
            canvas.selected_entity_ids
            or canvas.selected_constraint_ids
            or canvas.selected_raster_ids
            or canvas.selected_block_instance_ids
            or (canvas.text_tools is not None and canvas.text_tools.selected_ids)
            or (
                canvas.geometric_tolerance_tools is not None
                and canvas.geometric_tolerance_tools.selected_ids
            )
        ):
            editor.drawing_command_bar.begin_group_selection()
            editor.status_label.setText(canvas.message)
            return
        try:
            view = self._collection_view(editor)
            members = self._selected_group_refs(editor, view)
            validate_new_group_array_members(members, view.associative_arrays)
            session = self._ensure_collection_session(editor)
            snapshot = session.snapshot
            members = self._selected_group_refs(editor, snapshot)
            validate_new_group_array_members(members, snapshot.associative_arrays)
            group = DrawingGroup(uuid4().hex, tuple(members))
            if not canvas.stage_collection_operation(
                ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
            ):
                raise ValidationError(canvas.message)
            canvas.message = f"GROUP：已暂存匿名组（{len(members)} 个对象）；可撤销或完成草稿提交。"
            editor.status_label.setText(canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            canvas.message = str(exc)
            editor.status_label.setText(canvas.message)

    def _edit_drawing_group(self, editor: SketchEditorDialog) -> None:
        from mycad.core.drawing_groups import DrawingGroupTable, DrawingObjectRef
        from mycad.core.drawing_object_refs import validate_new_group_array_members
        from mycad.ui.drawing_collections import DrawingGroupEditor

        editor.drawing_command_bar.remember_collection_command("groupedit")
        try:
            self._require_collection_action_ready(editor)
            if (
                editor.canvas.collection_session is None
                and self._services is not None
                and not self._services.kernel.drawing_groups
            ):
                raise ValidationError("当前图纸没有组。")
            canvas = editor.canvas
            session = canvas.collection_session
            loaded = self._loaded
            if loaded is None:
                raise ValidationError("当前二维文档不可用。")
            revision = loaded.document.revision
            snapshot = self._collection_view(editor)
            checkpoint = session.checkpoint() if session is not None else None

            def validate_dialog_state() -> None:
                self._require_collection_action_ready(editor)
                if (
                    self._loaded is not loaded
                    or loaded.document.revision != revision
                    or canvas.collection_session is not session
                    or (
                        session is not None
                        and session.checkpoint() != checkpoint
                        or session is None
                        and self._collection_view(editor) != snapshot
                    )
                ):
                    raise ValidationError("组暂存状态已变化，请重新编辑。")

            groups = snapshot.groups
            if not groups:
                raise ValidationError("当前图纸没有组。")
            target = groups[0]
            if len(groups) > 1:
                labels = [f"{group.name or '匿名组'} ({group.group_id})" for group in groups]
                chosen, accepted = QInputDialog.getItem(
                    editor, "组管理", "选择要编辑的组：", labels, 0, False
                )
                if not accepted:
                    return
                if chosen not in labels:
                    raise ValidationError("所选组已变化。")
                target = groups[labels.index(chosen)]
            validate_dialog_state()
            selection = self._selected_group_refs(editor, snapshot)
            geometry_names = {
                "PointEntity": "点",
                "LineEntity": "直线",
                "PolylineEntity": "多段线",
                "CircleEntity": "圆",
                "ArcEntity": "圆弧",
                "EllipseEntity": "椭圆",
                "RectangleEntity": "矩形",
                "SplineEntity": "样条",
            }
            member_labels = {
                DrawingObjectRef(
                    "geometry", entity.entity_id, sketch.sketch_id
                ): geometry_names.get(type(entity).__name__, "几何对象")
                for sketch in snapshot.sketches
                for entity in sketch.entities
            }
            dialog = DrawingGroupEditor(target, selection, editor, member_labels=member_labels)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            validate_dialog_state()
            if frozenset(self._selected_group_refs(editor, snapshot)) != frozenset(selection):
                raise ValidationError("组选择已变化，请重新编辑。")
            updated = None
            if dialog.has_members:
                updated = dialog.updated_group()
                if updated == target:
                    return
                DrawingGroupTable(groups).update(updated)
                validate_new_group_array_members(
                    tuple(member for member in updated.members if member not in target.members),
                    snapshot.associative_arrays,
                )
                operation = ReplayAppend("drawing.group.update", 1, updated.to_mapping(), "local")
            else:
                operation = ReplayAppend(
                    "drawing.group.remove", 1, {"group_id": target.group_id}, "local"
                )
            session = self._ensure_collection_session(editor)
            if target not in session.snapshot.groups:
                raise ValidationError("组暂存状态已变化，请重新编辑。")
            if updated is not None:
                DrawingGroupTable(session.snapshot.groups).update(updated)
                validate_new_group_array_members(
                    tuple(member for member in updated.members if member not in target.members),
                    session.snapshot.associative_arrays,
                )
            if not editor.canvas.stage_collection_operation(operation):
                raise ValidationError(editor.canvas.message)
            editor.canvas.message = (
                "已暂存组修改；可撤销或完成草稿提交。"
                if dialog.has_members
                else "组已无成员，已暂存解组；成员对象保留。"
            )
            editor.status_label.setText(editor.canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(editor.canvas.message)

    def _remove_drawing_group(self, editor: SketchEditorDialog) -> None:
        """Remove an unambiguous directly selected group in the active session."""
        editor.drawing_command_bar.remember_collection_command("ungroup")
        canvas = editor.canvas
        try:
            self._require_collection_action_ready(editor)
            if (
                canvas.collection_session is None
                and self._services is not None
                and not self._services.kernel.drawing_groups
            ):
                raise ValidationError("当前图纸没有组。")
            session = canvas.collection_session
            loaded = self._loaded
            if loaded is None:
                raise ValidationError("当前二维文档不可用。")
            revision = loaded.document.revision
            snapshot = self._collection_view(editor)
            checkpoint = session.checkpoint() if session is not None else None
            selected = frozenset(self._selected_group_refs(editor, snapshot))
            groups = tuple(
                group for group in snapshot.groups if selected.intersection(group.members)
            )
            if not groups:
                raise ValidationError("所选对象不属于任何组。")
            target = groups[0]
            if len(groups) > 1:
                labels = [f"{group.name or '匿名组'} ({group.group_id})" for group in groups]
                chosen, accepted = QInputDialog.getItem(
                    editor, "解组", "选择要解散的组：", labels, 0, False
                )
                if not accepted:
                    return
                if chosen not in labels:
                    raise ValidationError("所选组已变化。")
                target = groups[labels.index(chosen)]
            if (
                self._loaded is not loaded
                or loaded.document.revision != revision
                or canvas.collection_session is not session
                or (
                    session is not None
                    and session.checkpoint() != checkpoint
                    or session is None
                    and self._collection_view(editor) != snapshot
                )
                or frozenset(self._selected_group_refs(editor, snapshot)) != selected
            ):
                raise ValidationError("组暂存状态已变化，请重新选择。")
            self._require_collection_action_ready(editor)
            session = self._ensure_collection_session(editor)
            if target not in session.snapshot.groups:
                raise ValidationError("组暂存状态已变化，请重新选择。")
            if not canvas.stage_collection_operation(
                ReplayAppend("drawing.group.remove", 1, {"group_id": target.group_id}, "local")
            ):
                raise ValidationError(canvas.message)
            canvas.message = "已暂存解组；成员对象保留。"
            editor.status_label.setText(canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            canvas.message = str(exc)
            editor.status_label.setText(canvas.message)

    def _affine_collection_selection(
        self,
        editor: SketchEditorDialog,
        center: tuple[float, float],
        *,
        angle: float | None = None,
        factor: float | None = None,
        mirror_end: tuple[float, float] | None = None,
        copy_source: bool = False,
    ) -> bool:
        from mycad.core.drawing_transactions import (
            prepare_collection_mirror,
            prepare_collection_mirror_copy,
            prepare_collection_rotation,
            prepare_collection_scale,
        )
        from mycad.ui.drawing_collection_session import (
            DrawingCollectionAffinePreview,
            DrawingCollectionMirrorPreview,
        )

        session = editor.canvas.collection_session
        if session is None:
            return False
        try:
            snapshot = session.snapshot
            seeds = self._selected_group_refs(editor, snapshot)
            if mirror_end is not None:
                cached = editor.canvas.collection_commit_preview
                if (
                    isinstance(cached, DrawingCollectionMirrorPreview)
                    and cached.checkpoint == session.checkpoint()
                    and cached.seeds == frozenset(seeds)
                    and cached.frame == editor.current_frame()
                    and cached.start == center
                    and cached.end == mirror_end
                    and cached.copy_source == copy_source
                ):
                    operation = cached.operation
                else:
                    prepare_mirror = (
                        prepare_collection_mirror_copy if copy_source else prepare_collection_mirror
                    )
                    operation = prepare_mirror(
                        snapshot, seeds, editor.current_frame(), center, mirror_end
                    )
            else:
                if angle is not None:
                    kind, value = "rotate", angle
                elif factor is not None:
                    kind, value = "scale", factor
                else:
                    raise ValidationError("缺少组变换参数。")
                cached = editor.canvas.collection_commit_preview
                if (
                    isinstance(cached, DrawingCollectionAffinePreview)
                    and cached.checkpoint == session.checkpoint()
                    and cached.seeds == frozenset(seeds)
                    and cached.frame == editor.current_frame()
                    and cached.kind == kind
                    and cached.center == center
                    and cached.value == value
                    and cached.copy_source == copy_source
                ):
                    operation = cached.operation
                elif copy_source:
                    operation = session.prepare_affine_copy(
                        seeds, editor.current_frame(), center, kind, value
                    )
                elif kind == "rotate":
                    operation = prepare_collection_rotation(
                        snapshot, seeds, editor.current_frame(), center, value
                    )
                else:
                    operation = prepare_collection_scale(
                        snapshot, seeds, editor.current_frame(), center, value
                    )
            if not editor.canvas.stage_collection_operation(operation):
                raise ValidationError(editor.canvas.message)
            previous_inferred = {
                (sketch.sketch_id, constraint.constraint_id)
                for sketch in snapshot.sketches
                for constraint in sketch.constraints
                if constraint.source == "inferred"
            }
            remaining_inferred = {
                (sketch.sketch_id, constraint.constraint_id)
                for sketch in session.snapshot.sketches
                for constraint in sketch.constraints
                if constraint.source == "inferred"
            }
            removed_inferred = len(previous_inferred - remaining_inferred)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(str(exc))
            return False
        message = "已暂存组变换；可一次撤销。"
        if removed_inferred:
            message += f" 已移除 {removed_inferred} 条失效的自动关系。"
        editor.canvas.message = message
        editor.status_label.setText(editor.canvas.message)
        return True

    def _delete_collection_selection(self, editor: SketchEditorDialog) -> bool:
        from mycad.core.drawing_transactions import prepare_collection_delete

        session = editor.canvas.collection_session
        if session is None:
            return False
        try:
            snapshot = session.snapshot
            extra_constraints: list[tuple[str, str]] = []
            for identity in editor.canvas.selected_constraint_ids:
                dimension_refs = {
                    ref
                    for ref in editor.canvas.selected_dimension_refs
                    if ref.object_id == identity
                }
                if dimension_refs:
                    for ref in dimension_refs:
                        if not any(
                            sketch.sketch_id == ref.sketch_id
                            and any(
                                constraint.constraint_id == ref.object_id
                                and constraint.kind in DIMENSION_KINDS
                                for constraint in sketch.constraints
                            )
                            for sketch in snapshot.sketches
                        ):
                            raise ValidationError("所选尺寸不存在或身份已变化。")
                    continue
                matches = [
                    (sketch, constraint)
                    for sketch in snapshot.sketches
                    for constraint in sketch.constraints
                    if constraint.constraint_id == identity
                ]
                if len(matches) != 1:
                    raise ValidationError("所选约束不存在或身份不唯一。")
                sketch, constraint = matches[0]
                if constraint.kind not in DIMENSION_KINDS:
                    if sketch.sketch_id != editor.draft_sketch_id and constraint.kind != "tangent":
                        raise ValidationError("已保存草图中的此类约束暂不支持删除。")
                    extra_constraints.append((sketch.sketch_id, identity))
            seeds = self._selected_group_refs(
                editor,
                snapshot,
                excluded_constraint_ids=frozenset(identity for _, identity in extra_constraints),
            )
            operation = prepare_collection_delete(
                snapshot, seeds, extra_constraints=tuple(sorted(extra_constraints))
            )
            if not editor.canvas.stage_collection_operation(operation):
                raise ValidationError(editor.canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            editor.canvas.message = str(exc)
            editor.status_label.setText(str(exc))
            return False
        editor.status_label.setText("已暂存组删除；可一次撤销。")
        return True

    def _preview_collection_mirror(
        self,
        editor: SketchEditorDialog,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        copy_source: bool,
    ) -> DrawingCollectionMirrorPreview:
        from mycad.core.drawing_collection_preview import collection_preview_payload
        from mycad.core.drawing_transactions import (
            prepare_collection_mirror,
            prepare_collection_mirror_copy,
        )
        from mycad.ui.drawing_collection_session import DrawingCollectionMirrorPreview

        session = editor.canvas.collection_session
        if session is None:
            raise ValidationError("二维暂存会话不可用。")
        before = session.snapshot
        seeds = self._selected_group_refs(editor, before)
        prepare = prepare_collection_mirror_copy if copy_source else prepare_collection_mirror
        operation = prepare(before, seeds, editor.current_frame(), start, end)
        return DrawingCollectionMirrorPreview(
            session.checkpoint(),
            frozenset(seeds),
            editor.current_frame(),
            start,
            end,
            copy_source,
            operation,
            collection_preview_payload(before, session.preview_operation(operation)),
        )

    def _preview_collection_affine(
        self,
        editor: SketchEditorDialog,
        kind: str,
        center: tuple[float, float],
        value: float,
        *,
        copy_source: bool = False,
    ) -> DrawingCollectionAffinePreview:
        from mycad.core.drawing_collection_preview import collection_preview_payload
        from mycad.core.drawing_transactions import (
            prepare_collection_rotation,
            prepare_collection_scale,
        )
        from mycad.ui.drawing_collection_session import DrawingCollectionAffinePreview

        session = editor.canvas.collection_session
        if session is None:
            raise ValidationError("二维暂存会话不可用。")
        before = session.snapshot
        seeds = self._selected_group_refs(editor, before)
        if copy_source:
            operation = session.prepare_affine_copy(
                seeds, editor.current_frame(), center, kind, value
            )
        elif kind == "rotate":
            operation = prepare_collection_rotation(
                before, seeds, editor.current_frame(), center, value
            )
        elif kind == "scale":
            operation = prepare_collection_scale(
                before, seeds, editor.current_frame(), center, value
            )
        else:
            raise ValidationError("不支持的组预览变换。")
        return DrawingCollectionAffinePreview(
            session.checkpoint(),
            frozenset(seeds),
            editor.current_frame(),
            kind,
            center,
            value,
            copy_source,
            operation,
            collection_preview_payload(before, session.preview_operation(operation)),
        )

    def _preview_collection_transform(
        self,
        editor: SketchEditorDialog,
        displacement: tuple[float, float],
        *,
        copy_source: bool,
    ) -> DrawingCollectionTransformPreview:
        from mycad.core.drawing_collection_preview import collection_preview_payload
        from mycad.core.drawing_transactions import (
            prepare_collection_copy,
            prepare_collection_translation,
        )
        from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview

        canvas = editor.canvas
        session = canvas.collection_session
        if session is None:
            raise ValidationError("二维暂存会话不可用。")
        before = session.snapshot
        seeds = self._selected_group_refs(editor, before)
        has_attached = any(
            item.leader_attachment is not None or item.leader_annotation_attachment is not None
            for item in before.frames
        ) or any(
            item.attachment is not None or item.annotation_attachment is not None
            for item in before.datums
        )
        if has_attached and not copy_source:
            operation = session.prepare_attached_move(seeds, editor.current_frame(), displacement)
        elif copy_source:
            tools = canvas.geometric_tolerance_tools
            operation = prepare_collection_copy(
                before,
                seeds,
                editor.current_frame(),
                displacement,
                datum_relayout=(
                    (lambda datum: tools.relayout_recorded_datum(datum, before.text_styles))
                    if tools is not None
                    else None
                ),
            )
        else:
            operation = prepare_collection_translation(
                before, seeds, editor.current_frame(), displacement
            )
        payload = collection_preview_payload(before, session.preview_operation(operation))
        return DrawingCollectionTransformPreview(
            session.checkpoint(),
            frozenset(seeds),
            editor.current_frame(),
            displacement,
            copy_source,
            operation,
            payload,
        )

    def _move_collection_geometry(
        self,
        editor: SketchEditorDialog,
        identities: tuple[str, ...],
        displacement: tuple[float, float],
        *,
        copy_source: bool = False,
        annotation_seeds: tuple[tuple[str, str], ...] = (),
    ) -> bool:
        from mycad.core.drawing_groups import DrawingObjectRef, expand_group_selection
        from mycad.core.drawing_transactions import (
            prepare_collection_copy,
            prepare_collection_translation,
        )
        from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview

        canvas = editor.canvas
        session = canvas.collection_session
        if session is None:
            return False
        copy_omits_constraints = False
        try:
            snapshot = session.snapshot
            if not annotation_seeds:
                annotation_seeds = tuple(
                    (item.kind, item.object_id)
                    for item in self._selected_group_refs(editor, snapshot)
                    if item.kind in {"tolerance", "datum", "reference_dimension"}
                )
            catalog = [
                DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
                for sketch in snapshot.sketches
                for entity in sketch.entities
            ]
            catalog.extend(
                DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                for sketch in snapshot.sketches
                for constraint in sketch.constraints
                if constraint.kind in DIMENSION_KINDS
            )
            catalog.extend(DrawingObjectRef("text", item.text_id) for item in snapshot.texts)
            catalog.extend(DrawingObjectRef("raster", item.image_id) for item in snapshot.rasters)
            catalog.extend(
                DrawingObjectRef("block_instance", item.instance_id)
                for item in snapshot.block_instances
            )
            catalog.extend(DrawingObjectRef("tolerance", item.frame_id) for item in snapshot.frames)
            catalog.extend(DrawingObjectRef("datum", item.datum_id) for item in snapshot.datums)
            catalog.extend(
                DrawingObjectRef("reference_dimension", item.dimension_id)
                for item in snapshot.reference_dimensions
            )
            seeds: list[DrawingObjectRef] = []
            for identity in dict.fromkeys(identities):
                picked = {
                    item
                    for item in canvas.selected_geometry_refs
                    if item.object_id == identity and item in catalog
                }
                if picked:
                    seeds.extend(sorted(picked, key=lambda item: item.sketch_id or ""))
                    continue
                matches = [
                    item
                    for item in catalog
                    if item.kind == "geometry" and item.object_id == identity
                ]
                if len(matches) != 1:
                    raise ValidationError("选择的对象身份不存在或不唯一。")
                seeds.append(matches[0])
            for identity in canvas.selected_constraint_ids:
                picked = {
                    item
                    for item in canvas.selected_dimension_refs
                    if item.object_id == identity and item in catalog
                }
                if picked:
                    seeds.extend(sorted(picked, key=lambda item: item.sketch_id or ""))
                    continue
                matches = [
                    item
                    for item in catalog
                    if item.kind == "dimension" and item.object_id == identity
                ]
                if len(matches) != 1:
                    raise ValidationError("选择的尺寸不存在或身份不唯一。")
                seeds.append(matches[0])
            extra = (
                *(DrawingObjectRef("raster", identity) for identity in canvas.selected_raster_ids),
                *(
                    DrawingObjectRef("block_instance", identity)
                    for identity in canvas.selected_block_instance_ids
                ),
                *(
                    DrawingObjectRef("text", identity)
                    for identity in (
                        canvas.text_tools.selected_ids if canvas.text_tools is not None else ()
                    )
                ),
                *(DrawingObjectRef(kind, identity) for kind, identity in annotation_seeds),
            )
            if any(catalog.count(item) != 1 for item in extra):
                raise ValidationError("选择的文字、图片或标注已变化。")
            seeds.extend(extra)
            if copy_source:
                effective = expand_group_selection(seeds, snapshot.groups)
                geometry = {
                    (item.sketch_id, item.object_id)
                    for item in effective
                    if item.kind == "geometry"
                }
                dimensions = {
                    (item.sketch_id, item.object_id)
                    for item in effective
                    if item.kind == "dimension"
                }
                copy_omits_constraints = any(
                    (sketch.sketch_id, constraint.constraint_id) not in dimensions
                    and any(
                        (sketch.sketch_id, ref.entity_id) in geometry
                        for ref in constraint.references
                    )
                    for sketch in snapshot.sketches
                    for constraint in sketch.constraints
                ) or any(
                    sum(
                        (ref.sketch_id, ref.entity_id) in geometry
                        for ref in (relation.first, relation.second)
                    )
                    == 1
                    for relation in snapshot.cross_tangencies
                )
            has_attached = any(
                item.leader_attachment is not None or item.leader_annotation_attachment is not None
                for item in snapshot.frames
            ) or any(
                item.attachment is not None or item.annotation_attachment is not None
                for item in snapshot.datums
            )
            cached = canvas.collection_commit_preview
            if (
                isinstance(cached, DrawingCollectionTransformPreview)
                and cached.checkpoint == session.checkpoint()
                and cached.seeds == frozenset(seeds)
                and cached.frame == editor.current_frame()
                and cached.displacement == displacement
                and cached.copy_source == copy_source
            ):
                operation = cached.operation
            elif has_attached and not copy_source:
                operation = session.prepare_attached_move(
                    tuple(seeds), editor.current_frame(), displacement
                )
            elif copy_source:
                tools = canvas.geometric_tolerance_tools
                operation = prepare_collection_copy(
                    snapshot,
                    tuple(seeds),
                    editor.current_frame(),
                    displacement,
                    datum_relayout=(
                        (lambda datum: tools.relayout_recorded_datum(datum, snapshot.text_styles))
                        if tools is not None
                        else None
                    ),
                )
            else:
                operation = prepare_collection_translation(
                    snapshot, tuple(seeds), editor.current_frame(), displacement
                )
            previous_position = canvas.history_position
            if not canvas.stage_collection_operation(operation):
                raise ValidationError(canvas.message)
        except (KeyError, ValueError, ValidationError) as exc:
            if copy_source:
                canvas.finish_collection_copy(None)
            canvas.message = str(exc) + (
                "；可以重新指定目标点。"
                if copy_source and canvas.active_transform == "copy"
                else ""
            )
            editor.status_label.setText(canvas.message)
            return False
        if copy_source:
            canvas.finish_collection_copy(previous_position)
        message = "已暂存组移动；可逐步撤销。"
        if copy_source:
            if canvas.active_transform == "copy":
                message = canvas.message
                if copy_omits_constraints:
                    message += " 部分约束未复制。"
            else:
                message = (
                    "已暂存组复制；部分约束未复制，可逐步撤销。"
                    if copy_omits_constraints
                    else "已暂存组复制；可逐步撤销。"
                )
        canvas.message = message
        editor.status_label.setText(canvas.message)
        return True

    def _on_drawing_move(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        ids: object,
        delta: object,
        *,
        angle: float | None = None,
        scale: float | None = None,
        mirror_end: tuple[float, float] | None = None,
        erase: bool = False,
        copy_source: bool = False,
        copy_count: int = 2,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        if (
            editor.canvas.mixed_move is None
            and editor.canvas.source_context_revision != loaded.document.revision
        ):
            self._sync_drawing_layers()
            editor.status_label.setText("文档已变化；所选对象未修改。")
            return
        if angle is not None and (
            not isfinite(angle) or (not copy_source and remainder(angle, 360.0) == 0.0)
        ):
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
        if editor.canvas.collection_session is not None:
            if mirror_end is not None:
                self._affine_collection_selection(
                    editor, displacement, mirror_end=mirror_end, copy_source=copy_source
                )
                return
            if angle is not None:
                self._affine_collection_selection(
                    editor, displacement, angle=angle, copy_source=copy_source
                )
                return
            if scale is not None:
                self._affine_collection_selection(
                    editor, displacement, factor=scale, copy_source=copy_source
                )
                return
            if (
                angle is not None
                or scale is not None
                or mirror_end is not None
                or erase
                or (copy_source and copy_count != 2)
            ):
                if copy_source:
                    editor.canvas.finish_collection_copy(None)
                editor.status_label.setText("该暂存变换尚未接入，请先完成或取消暂存。")
                return
            self._move_collection_geometry(editor, selected, displacement, copy_source=copy_source)
            return
        annotation_appends: tuple[ReplayAppend, ...] = ()
        tolerance_tools = editor.canvas.geometric_tolerance_tools
        if erase and tolerance_tools is not None and tolerance_tools.selected_id is not None:
            identities = tolerance_tools.selected_ids
            if tolerance_tools.selected_id not in identities:
                editor.status_label.setText("所选标注已变化；对象未删除。")
                return
            frames = [
                item.frame_id for item in tolerance_tools.frames if item.frame_id in identities
            ]
            datums = [
                item.datum_id for item in tolerance_tools.datums if item.datum_id in identities
            ]
            references = [
                item.dimension_id
                for item in tolerance_tools.reference_dimensions
                if item.dimension_id in identities
            ]
            if len(frames) + len(datums) + len(references) != len(identities):
                editor.status_label.setText("所选标注已变化；对象未删除。")
                return
            if any(
                frame.frame_id not in identities
                and any(
                    reference.datum_id in datums
                    for row in frame.rows
                    for reference in row.datums
                    if reference.datum_id is not None
                )
                for frame in services.kernel.drawing_tolerance_frames
            ):
                editor.status_label.setText("基准仍被公差框引用；请先解除引用或同时删除该公差框。")
                return
            for annotation in (
                *services.kernel.drawing_tolerance_frames,
                *services.kernel.drawing_datum_identifiers,
            ):
                if isinstance(annotation, FeatureControlFrame):
                    identity, attachment = (
                        annotation.frame_id,
                        annotation.leader_annotation_attachment,
                    )
                else:
                    identity, attachment = annotation.datum_id, annotation.annotation_attachment
                if (
                    identity not in identities
                    and attachment is not None
                    and attachment.kind == "frame"
                    and attachment.object_id in frames
                ):
                    editor.status_label.setText(
                        "公差框仍被标注附着；请先解除附着或同时删除该标注。"
                    )
                    return
                if (
                    identity not in identities
                    and attachment is not None
                    and attachment.kind == "reference_dimension"
                    and attachment.object_id in references
                ):
                    editor.status_label.setText(
                        "参考尺寸仍被标注附着；请先解除附着或同时删除该标注。"
                    )
                    return
            if frames or datums:
                annotation_appends += (
                    ReplayAppend(
                        "drawing.tolerance.batch",
                        services.registry.get("drawing.tolerance.batch").version,
                        {"remove_frames": frames, "remove_datums": datums},
                        "local",
                    ),
                )
            if references:
                annotation_appends += (
                    ReplayAppend(
                        "drawing.reference_dimensions.batch",
                        services.registry.get("drawing.reference_dimensions.batch").version,
                        {"remove": references},
                        "local",
                    ),
                )
        if erase:
            removed_dimensions = set(editor.canvas.selected_constraint_ids)
            removed_dimensions.update(
                constraint.constraint_id
                for sketch in services.kernel.sketches
                for constraint in sketch.constraints
                if constraint.kind in DIMENSION_KINDS
                and any(reference.entity_id in selected for reference in constraint.references)
            )
            selected_annotations: set[str] = (
                tolerance_tools.selected_ids
                if tolerance_tools is not None and tolerance_tools.selected_id is not None
                else set()
            )
            if _dimensions_have_unselected_tolerance_attachment(
                services.kernel.sketches,
                services.kernel.drawing_tolerance_frames,
                services.kernel.drawing_datum_identifiers,
                removed_dimensions,
                selected_annotations,
            ):
                editor.status_label.setText("草图尺寸仍被标注附着；请先解除附着或同时删除该标注。")
                return
        image_ids: frozenset[str] = frozenset(editor.canvas.selected_raster_ids)
        images: tuple[DrawingRaster, ...] = ()
        if image_ids:
            images = tuple(
                image for image in services.kernel.drawing_rasters if image.image_id in image_ids
            )
            if len(images) != len(image_ids) or any(
                not editor.canvas.layer_table.get(image.layer_name).displayed
                or editor.canvas.layer_table.get(image.layer_name).locked
                for image in images
            ):
                editor.status_label.setText("图片已变化或所在图层不可编辑；对象未修改。")
                return
            if copy_source and (copy_count < 2 or (copy_count - 1) * len(images) > 1000):
                editor.status_label.setText("复制阵列数量无效，最多生成 1000 张图片。")
                return
        action = (
            "删除"
            if erase
            else "缩放复制"
            if copy_source and scale is not None
            else "旋转复制"
            if copy_source and angle is not None
            else "复制"
            if copy_source and mirror_end is None
            else "缩放"
            if scale is not None
            else "镜像"
            if mirror_end is not None
            else "旋转"
            if angle is not None
            else "移动"
        )
        text_tools = editor.canvas.text_tools
        selected_texts = text_tools.selected() if text_tools is not None else ()
        if text_tools is not None and text_tools.selection_error():
            editor.status_label.setText(text_tools.selection_error())
            return
        if selected_texts and (
            editor.canvas.mixed_move is not None
            or (
                (editor.canvas.pending_cross_tangencies or editor.canvas.pending_associative_arrays)
                and not erase
            )
        ):
            editor.status_label.setText("请先完成关联草稿，再变换文字与图形。")
            return
        text_batch: dict[str, object] | None = None
        if selected_texts:
            changed_texts: list[DrawingText] = []
            try:
                if not erase:
                    for text in selected_texts:
                        if mirror_end is not None:
                            changed_texts.append(mirror_text(text, displacement, mirror_end))
                        elif angle is not None:
                            changed_texts.append(rotate_text(text, angle, displacement))
                        elif scale is not None:
                            changed_texts.append(
                                scale_text(
                                    text, scale, displacement, services.kernel.drawing_text_styles
                                )
                            )
                        else:
                            for index in range(1, copy_count if copy_source else 2):
                                changed_texts.append(
                                    move_text(
                                        text, (displacement[0] * index, displacement[1] * index)
                                    )
                                )
                if copy_source:
                    changed_texts = [replace(text, text_id=uuid4().hex) for text in changed_texts]
                text_batch = {
                    "add": [text.to_mapping() for text in changed_texts] if copy_source else [],
                    "update": [] if copy_source else [text.to_mapping() for text in changed_texts],
                    "remove": [text.text_id for text in selected_texts] if erase else [],
                }
            except ValueError as exc:
                editor.status_label.setText(str(exc))
                return
        draft_ids = tuple(
            entity.entity_id for entity in editor.canvas.entities if entity.entity_id in selected
        )
        if annotation_appends and editor.canvas.mixed_move is not None:
            editor.status_label.setText("请先完成暂存变换，再同时删除图元和标注。")
            return
        if (
            annotation_appends
            and draft_ids
            and (editor.canvas.pending_cross_tangencies or editor.canvas.pending_associative_arrays)
            and not erase
        ):
            editor.status_label.setText("请先完成暂存关联，再同时删除图元和标注。")
            return
        draft_copy_omits_constraints = (
            copy_source and bool(draft_ids) and editor.canvas.selected_draft_constraints_exist()
        )
        pending_copy_tangent, pending_copy_array = (
            editor.canvas.selected_pending_copy_omissions() if copy_source else (False, False)
        )
        draft_candidate: tuple[SketchEntity, ...] | None = None
        draft_pending_arrays: tuple[AssociativeRectArray, ...] | None = None
        draft_remove_constraint_ids: frozenset[str] = frozenset()
        if (
            image_ids
            and draft_ids
            and editor.canvas.mixed_move is not None
            and editor.canvas.pending_cross_tangencies
            and not editor.canvas.pending_associative_arrays
            and not copy_source
            and not erase
            and all(
                all(draft_tangent_reference(ref).entity_id in selected for ref in pair)
                for pair in editor.canvas.pending_cross_tangencies
            )
        ):
            transformed: list[DrawingRaster] = []
            for image in images:
                x, y = image.origin_mm[0] - displacement[0], image.origin_mm[1] - displacement[1]
                if mirror_end is not None:
                    axis = atan2(mirror_end[1] - displacement[1], mirror_end[0] - displacement[0])
                    c, sn = cos(2 * axis), sin(2 * axis)
                    transformed.append(
                        replace(
                            image,
                            origin_mm=(
                                displacement[0] + c * x + sn * y,
                                displacement[1] + sn * x - c * y,
                            ),
                            angle_deg=degrees(2 * axis) - image.angle_deg,
                            mirrored=not image.mirrored,
                        )
                    )
                elif angle is not None:
                    c, sn = cos(radians(angle)), sin(radians(angle))
                    transformed.append(
                        replace(
                            image,
                            origin_mm=(
                                displacement[0] + c * x - sn * y,
                                displacement[1] + sn * x + c * y,
                            ),
                            angle_deg=image.angle_deg + angle,
                        )
                    )
                elif scale is not None:
                    transformed.append(
                        replace(
                            image,
                            origin_mm=(displacement[0] + x * scale, displacement[1] + y * scale),
                            width_mm=image.width_mm * scale,
                            height_mm=image.height_mm * scale,
                        )
                    )
                else:
                    transformed.append(
                        replace(
                            image,
                            origin_mm=(
                                image.origin_mm[0] + displacement[0],
                                image.origin_mm[1] + displacement[1],
                            ),
                        )
                    )
            self._stage_drawing_mixed_move(
                editor,
                session_id,
                selected,
                displacement,
                angle=angle,
                scale=scale,
                mirror_end=mirror_end,
                raster_updates=tuple(transformed),
            )
            return
        preserve_pending_transform = bool(
            image_ids
            and draft_ids
            and editor.canvas.pending_cross_tangencies
            and not editor.canvas.pending_associative_arrays
            and not copy_source
            and not erase
            and all(
                all(draft_tangent_reference(ref).entity_id in selected for ref in pair)
                for pair in editor.canvas.pending_cross_tangencies
            )
        )
        pending_source_ids = {
            ref.entity_id
            for array in editor.canvas.pending_associative_arrays
            for ref in (
                *array.sources,
                *(member.replacement.source for member in array.members if member.replacement),
                *(output.source for output in array.extra_outputs),
                *(output.anchor_source for output in array.extra_outputs),
            )
        }
        if (
            draft_ids
            or editor.canvas.mixed_move is not None
            or (scale is not None and pending_source_ids.intersection(selected))
        ):
            can_transform_three = bool(
                (image_ids or selected_texts or annotation_appends)
                and draft_ids
                and editor.canvas.mixed_move is None
                and (
                    copy_source
                    or preserve_pending_transform
                    or erase
                    or not (
                        editor.canvas.pending_cross_tangencies
                        or editor.canvas.pending_associative_arrays
                    )
                )
            )
            if can_transform_three:
                if any(
                    entity.entity_id in draft_ids
                    for entity, _layer in editor.canvas.background_entities
                ):
                    editor.status_label.setText("草稿与已提交图元身份重复；对象未修改。")
                    return
                operation = (
                    "delete_mixed"
                    if erase
                    else "mirror"
                    if mirror_end is not None
                    else "scale"
                    if scale is not None
                    else "rotate"
                    if angle is not None
                    else "copy"
                    if copy_source
                    else "move"
                )
                error = editor.canvas.transform_selection_error(operation)
                if error:
                    editor.status_label.setText(error)
                    return
                if erase:
                    affected = tuple(
                        constraint
                        for constraint in editor.canvas.constraints
                        if constraint.constraint_id in editor.canvas.selected_constraint_ids
                        or any(ref.entity_id in selected for ref in constraint.references)
                    )
                    if any(
                        editor.canvas.annotation_layer(constraint).locked
                        or not editor.canvas.annotation_layer(constraint).displayed
                        for constraint in affected
                    ) or any(
                        entity.entity_id in selected and (layer.locked or not layer.displayed)
                        for entity, layer in editor.canvas.background_entities
                    ):
                        editor.status_label.setText(
                            "所选对象或约束所在图层隐藏或已锁定；对象未删除。"
                        )
                        return
                    draft_remove_constraint_ids = frozenset(c.constraint_id for c in affected)
                try:
                    if erase:
                        if editor.canvas.pending_associative_arrays:
                            member_ids = {
                                member.target.entity_id
                                for array in editor.canvas.pending_associative_arrays
                                for member in array.members
                                if member.erased_index is None
                            } | {
                                output.target.entity_id
                                for array in editor.canvas.pending_associative_arrays
                                for output in array.extra_outputs
                            }
                            if any(
                                draft_tangent_reference(target).entity_id
                                in set(draft_ids) & member_ids
                                and draft_tangent_reference(source).entity_id not in selected
                                for source, target in editor.canvas.pending_cross_tangencies
                            ):
                                raise ValueError("阵列成员仍有对象相切关系；图元未修改。")
                            states = editor.dimension_sources()
                            targets = tuple(
                                ArrayEntityRef(states[0].sketch_id, identity)
                                for identity in draft_ids
                            )
                            requested = replace(
                                states[0],
                                constraints=tuple(
                                    item
                                    for item in states[0].constraints
                                    if item.constraint_id
                                    not in editor.canvas.selected_constraint_ids
                                ),
                            )
                            stripped = strip_erased_member_dimensions(
                                states, (requested, *states[1:]), targets
                            )
                            proposed, draft_pending_arrays = erase_drawing_entities(
                                stripped,
                                tuple(editor.canvas.pending_associative_arrays),
                                targets,
                            )
                            if proposed[1:] != states[1:]:
                                raise ValueError("暂存阵列删除会修改其他草图；对象未删除。")
                            draft_candidate = proposed[0].entities
                        else:
                            draft_candidate = tuple(
                                entity
                                for entity in editor.canvas.entities
                                if entity.entity_id not in draft_ids
                            )
                    elif mirror_end is not None:
                        source = tuple(editor.canvas.entities)
                        if copy_source:
                            originals = {entity.entity_id for entity in source}
                            source = copy_entities(source, draft_ids, (0.0, 0.0))
                            mirror_ids = tuple(
                                entity.entity_id
                                for entity in source
                                if entity.entity_id not in originals
                            )
                        else:
                            mirror_ids = draft_ids
                        draft_candidate = mirror_entities(
                            source, mirror_ids, displacement, mirror_end
                        )
                    elif copy_source and scale is None and angle is None:
                        draft_candidate = tuple(editor.canvas.entities)
                        for index in range(1, copy_count):
                            draft_candidate = copy_entities(
                                draft_candidate,
                                draft_ids,
                                (displacement[0] * index, displacement[1] * index),
                            )
                    elif scale is not None:
                        source = tuple(editor.canvas.entities)
                        if copy_source:
                            originals = {entity.entity_id for entity in source}
                            source = copy_entities(source, draft_ids, (0.0, 0.0))
                            scale_ids = tuple(
                                entity.entity_id
                                for entity in source
                                if entity.entity_id not in originals
                            )
                        else:
                            scale_ids = draft_ids
                        draft_candidate = scale_entities(source, scale_ids, displacement, scale)
                    elif angle is not None:
                        source = tuple(editor.canvas.entities)
                        if copy_source:
                            originals = {entity.entity_id for entity in source}
                            source = copy_entities(source, draft_ids, (0.0, 0.0))
                            rotation_ids = tuple(
                                entity.entity_id
                                for entity in source
                                if entity.entity_id not in originals
                            )
                        else:
                            rotation_ids = draft_ids
                        draft_candidate = rotate_entities(source, rotation_ids, displacement, angle)
                    else:
                        draft_candidate = move_entities(
                            tuple(editor.canvas.entities),
                            draft_ids,
                            displacement,
                            preserve_rectangle_order=True,
                        )
                    editor.canvas.validate_draft_constraint_edits(
                        draft_candidate, removed_constraint_ids=draft_remove_constraint_ids
                    )
                except (IndexError, KeyError, ValueError) as exc:
                    editor.status_label.setText(str(exc))
                    return
                if draft_candidate == tuple(editor.canvas.entities):
                    editor.status_label.setText(f"{action}未改变图元。")
                    return
                if copy_source and not editor.canvas.draft_copy_preserves_sources(draft_candidate):
                    editor.status_label.setText("复制无法保留原草稿对象；对象未修改。")
                    return
                selected = tuple(identity for identity in selected if identity not in draft_ids)
            elif image_ids:
                if draft_ids and editor.canvas.pending_associative_arrays:
                    message = "存在暂存阵列时暂不能同时变换图片和图元，请先完成或撤销阵列。"
                elif (
                    draft_ids
                    and editor.canvas.pending_cross_tangencies
                    and not all(
                        all(draft_tangent_reference(ref).entity_id in selected for ref in pair)
                        for pair in editor.canvas.pending_cross_tangencies
                    )
                ):
                    message = "请同时选择暂存相切关系的两个对象，或先完成当前草稿。"
                elif draft_ids and editor.canvas.pending_cross_tangencies:
                    message = "存在其他暂存编辑，请先完成或撤销当前草稿操作。"
                elif draft_ids:
                    message = "暂不能同时编辑图片、草稿和已提交图元，请分开操作。"
                else:
                    message = "存在暂存关联时暂不能编辑图片，请先完成或撤销暂存操作。"
                editor.status_label.setText(message)
                return
            else:
                self._stage_drawing_mixed_move(
                    editor,
                    session_id,
                    selected,
                    displacement,
                    angle=angle,
                    scale=scale,
                    mirror_end=mirror_end,
                    erase=erase,
                )
                return
        committed_ids = set(selected)
        selected_constraints: set[str] = (
            set(editor.canvas.selected_constraint_ids) if erase else set()
        )
        if selected_constraints:
            matching_constraints = [
                constraint
                for constraint in (
                    *editor.canvas.constraints,
                    *(
                        constraint
                        for sketch in services.kernel.sketches
                        for constraint in sketch.constraints
                    ),
                )
                if constraint.constraint_id in selected_constraints
            ]
            if len(matching_constraints) != len(selected_constraints):
                editor.status_label.setText("所选标注身份不唯一或已变化；对象未删除。")
                return
            if any(
                editor.canvas.annotation_layer(constraint).locked
                or not editor.canvas.annotation_layer(constraint).displayed
                for constraint in matching_constraints
            ):
                editor.status_label.setText("所选标注所在图层隐藏或已锁定；对象未删除。")
                return
        if not (
            (copy_source and image_ids and draft_candidate is not None)
            or preserve_pending_transform
        ) and any(
            draft_tangent_reference(source).entity_id in committed_ids
            for source, _ in editor.canvas.pending_cross_tangencies
        ):
            editor.status_label.setText("请先完成包含相切关系的当前草图，再编辑关联图元。")
            return
        sketches = tuple(
            sketch
            for sketch in services.kernel.sketches
            if any(entity.entity_id in committed_ids for entity in sketch.entities)
            or any(
                constraint.constraint_id in selected_constraints
                for constraint in sketch.constraints
            )
        )
        if (not sketches and committed_ids) or not committed_ids.issubset(
            entity.entity_id for sketch in sketches for entity in sketch.entities
        ):
            editor.status_label.setText("选择的图元已变化；所选对象保持不变。")
            return
        selected_entities = [
            entity.entity_id
            for sketch in sketches
            for entity in sketch.entities
            if entity.entity_id in committed_ids
        ]
        if len(selected_entities) != len(set(selected_entities)):
            editor.status_label.setText("所选图元标识不唯一；所选对象保持不变。")
            return
        if erase:
            owning = [
                (
                    array,
                    tuple(
                        member.target
                        for member in array.members
                        if member.target.entity_id in committed_ids and member.erased_index is None
                    )
                    + tuple(
                        output.target
                        for output in array.extra_outputs
                        if output.target.entity_id in committed_ids
                    ),
                )
                for array in services.kernel.associative_arrays
            ]
            owning = [(array, refs) for array, refs in owning if refs]
            if owning:
                if annotation_appends and selected_constraints and draft_pending_arrays is None:
                    self._on_delete_drawing_dimensions(
                        editor,
                        session_id,
                        tuple(sorted(selected_constraints)),
                        annotation_appends=annotation_appends,
                        text_batch=text_batch,
                        draft_candidate=draft_candidate,
                        draft_remove_constraint_ids=draft_remove_constraint_ids,
                    )
                    return
                if selected_texts and not annotation_appends:
                    editor.status_label.setText("请先单独删除阵列成员，再删除文字。")
                    return
                if image_ids and not annotation_appends:
                    editor.status_label.setText("图片与阵列成员暂不能同时删除；对象未修改。")
                    return
                mixed = len(owning) != 1 or {ref.entity_id for ref in owning[0][1]} != committed_ids
                includes_extra = any(
                    output.target.entity_id in committed_ids
                    for array, _refs in owning
                    for output in array.extra_outputs
                )
                refs = tuple(
                    ArrayEntityRef(sketch.sketch_id, entity.entity_id)
                    for sketch in sketches
                    for entity in sketch.entities
                    if entity.entity_id in committed_ids
                )
                if draft_pending_arrays is not None:
                    params: dict[str, object] = {"targets": [ref.to_mapping() for ref in refs]}
                    if not mixed and not includes_extra:
                        params["array_id"] = owning[0][0].array_id
                    dimension_revisions: list[dict[str, object]] = []
                    for sketch in sketches:
                        remaining = tuple(
                            item
                            for item in sketch.constraints
                            if item.constraint_id not in selected_constraints
                        )
                        if remaining != sketch.constraints:
                            state = replace(sketch, constraints=remaining).to_state_mapping()
                            dimension_revisions.append(
                                {
                                    "sketch_id": sketch.sketch_id,
                                    "base_state_sha256": sketch.local_state_digest(),
                                    "entities": state["entities"],
                                    "constraints": state["constraints"],
                                }
                            )
                    self._submit_drawing_revisions(
                        editor,
                        session_id,
                        dimension_revisions,
                        any(
                            isinstance(entity, PointEntity)
                            for sketch in sketches
                            for entity in sketch.entities
                        ),
                        "删除",
                        raster_remove_ids=tuple(sorted(image_ids)),
                        draft_candidate=draft_candidate,
                        draft_pending_arrays=draft_pending_arrays,
                        draft_remove_constraint_ids=draft_remove_constraint_ids,
                        text_batch=text_batch,
                        annotation_appends=annotation_appends,
                        extra_appends=(
                            ReplayAppend(
                                "drawing.array.erase",
                                4 if includes_extra else 3 if mixed else 2,
                                params,
                                "local",
                            ),
                        ),
                    )
                    return
                revision = loaded.document.revision
                editor.setEnabled(False)

                def erase_members() -> object:
                    if (
                        self._loaded is not loaded
                        or self._session_id != session_id
                        or loaded.document.revision != revision
                        or any(
                            array not in services.kernel.associative_arrays for array, _ in owning
                        )
                    ):
                        raise ValidationError("文档或阵列已变化，请重新选择。")
                    params: dict[str, object] = {"targets": [ref.to_mapping() for ref in refs]}
                    if not mixed and not includes_extra:
                        params["array_id"] = owning[0][0].array_id
                    version = 4 if includes_extra else 3 if mixed else 2
                    if not annotation_appends:
                        return loaded.bus.execute(
                            "drawing.array.erase", params, "local", version=version
                        )
                    candidate = mycad_app.create_replay_candidate(
                        services, loaded, session_identity=session_id
                    )
                    candidate.stage(
                        ReplayChangeSet(
                            (),
                            (
                                ReplayAppend("drawing.array.erase", version, params, "local"),
                                *annotation_appends,
                                *(
                                    (ReplayAppend("drawing.text.batch", 1, text_batch, "local"),)
                                    if text_batch is not None
                                    else ()
                                ),
                                *(
                                    (
                                        ReplayAppend(
                                            "drawing.raster.batch",
                                            2,
                                            {"action": "remove", "image_ids": sorted(image_ids)},
                                            "local",
                                        ),
                                    )
                                    if image_ids
                                    else ()
                                ),
                            ),
                            False,
                        ),
                        current_session_identity=session_id,
                    )
                    preview = candidate.preview(current_session_identity=session_id)
                    if preview.state != "succeeded":
                        raise ValidationError(
                            preview.failure.reason if preview.failure else "混合删除预览失败。"
                        )
                    return candidate.commit(
                        candidate.authorize_commit(current_session_identity=session_id),
                        current_session_identity=session_id,
                    )

                def finish_erase(result: ExecutionResult) -> None:
                    editor.setEnabled(True)
                    if (
                        self._sketch_dialog is not editor
                        or self._loaded is not loaded
                        or self._session_id != session_id
                    ):
                        return
                    self._sync_drawing_layers()
                    if result.error is not None:
                        editor.status_label.setText(f"删除失败：{result.error}")
                        return
                    editor.canvas.selected_entity_ids.difference_update(committed_ids)
                    editor.canvas.selected_raster_ids.difference_update(image_ids)
                    editor.layer_history_boundaries[len(loaded.document.commands)] = (
                        editor.canvas.history_position
                    )
                    editor.layer_history_redo.clear()
                    editor.canvas.discard_redo_history()
                    editor.status_label.setText(
                        "已删除所选对象；可撤销恢复。"
                        if includes_extra
                        else "已删除所选对象；阵列成员可通过重置阵列恢复。"
                    )

                if not unit.submit(
                    erase_members,
                    operation="array-erase",
                    session_id=session_id,
                    on_complete=finish_erase,
                ):
                    editor.setEnabled(True)
                    editor.status_label.setText("几何工作线程忙碌，删除未应用。")
                return
        revisions: list[dict[str, object]] = []
        revised_sketches: dict[str, Sketch] = {}
        includes_points = False
        for sketch in sketches:
            sketch_ids = tuple(
                entity.entity_id for entity in sketch.entities if entity.entity_id in committed_ids
            )
            if not sketch_ids and not any(
                constraint.constraint_id in selected_constraints
                for constraint in sketch.constraints
            ):
                continue
            if not erase:
                try:
                    project_coplanar_vector((0.0, 0.0), editor.current_frame(), sketch.frame)
                except ValueError:
                    editor.status_label.setText("所选对象不在当前工作平面；图元未修改。")
                    return
            if erase and any(
                (
                    constraint.constraint_id in selected_constraints
                    or any(ref.entity_id in sketch_ids for ref in constraint.references)
                )
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
                if copy_source:
                    copied = copy_entities(sketch.entities, sketch_ids, (0.0, 0.0))
                    clone_ids = tuple(entity.entity_id for entity in copied[len(sketch.entities) :])
                    changed = mirror_entities(copied, clone_ids, start, end)
                else:
                    changed = mirror_entities(sketch.entities, sketch_ids, start, end)
            elif angle is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                local_angle = project_coplanar_rotation(angle, editor.current_frame(), sketch.frame)
                if copy_source:
                    copied = copy_entities(sketch.entities, sketch_ids, (0.0, 0.0))
                    clone_ids = tuple(entity.entity_id for entity in copied[len(sketch.entities) :])
                    changed = rotate_entities(copied, clone_ids, center, local_angle)
                else:
                    changed = rotate_entities(sketch.entities, sketch_ids, center, local_angle)
            elif scale is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                if copy_source:
                    copied = copy_entities(sketch.entities, sketch_ids, (0.0, 0.0))
                    clone_ids = tuple(entity.entity_id for entity in copied[len(sketch.entities) :])
                    changed = scale_entities(copied, clone_ids, center, scale)
                else:
                    changed = scale_entities(sketch.entities, sketch_ids, center, scale)
            else:
                local_delta = project_coplanar_vector(
                    displacement, editor.current_frame(), sketch.frame
                )
                if copy_source:
                    changed = sketch.entities
                    for index in range(1, copy_count):
                        changed = copy_entities(
                            changed, sketch_ids, (local_delta[0] * index, local_delta[1] * index)
                        )
                else:
                    changed = move_entities(
                        sketch.entities, sketch_ids, local_delta, preserve_rectangle_order=True
                    )
            constraints = tuple(
                constraint
                for constraint in sketch.constraints
                if not erase
                or (
                    constraint.constraint_id not in selected_constraints
                    and all(ref.entity_id not in sketch_ids for ref in constraint.references)
                )
            )
            if changed == sketch.entities and constraints == sketch.constraints:
                continue
            revised = replace(sketch, entities=changed, constraints=constraints)
            revised_sketches[sketch.sketch_id] = revised
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
        if not revisions and text_batch is None and not annotation_appends:
            editor.status_label.setText(f"{action}未改变图元。")
            return
        relations = services.kernel.cross_sketch_tangencies
        selected_array_refs = {
            ref.entity_id
            for array in services.kernel.associative_arrays
            for ref in (
                *array.sources,
                *(member.source for member in array.members),
                *(member.target for member in array.members),
                *(member.replacement.source for member in array.members if member.replacement),
                *(output.source for output in array.extra_outputs),
                *(output.target for output in array.extra_outputs),
                *(output.anchor_source for output in array.extra_outputs),
            )
        }
        copied_without_array = (
            bool(image_ids)
            and copy_source
            and (pending_copy_array or bool(selected_array_refs & committed_ids))
        )
        copied_without_constraints = (
            bool(image_ids)
            and copy_source
            and (
                draft_copy_omits_constraints
                or pending_copy_tangent
                or any(
                    ref.entity_id in committed_ids
                    for relation in relations
                    for ref in (relation.first, relation.second)
                )
                or any(
                    ref.entity_id in committed_ids
                    for sketch in sketches
                    for constraint in sketch.constraints
                    for ref in constraint.references
                )
            )
        )
        if (
            image_ids
            and not erase
            and not copy_source
            and (
                bool(selected_array_refs & committed_ids)
                or any(
                    ref.entity_id in committed_ids
                    for relation in relations
                    for ref in (relation.first, relation.second)
                )
            )
        ):
            editor.status_label.setText("图片与关联对象暂不能同时变换；对象未修改。")
            return
        related_ids = {
            ref.sketch_id for relation in relations for ref in (relation.first, relation.second)
        }
        related = next((sketch for sketch in sketches if sketch.sketch_id in related_ids), None)
        if related is not None and not erase and not (copy_source and image_ids):
            component_ids: set[str] = set()
            for sketch in sketches:
                connected, _ = resolve_tangency_component(
                    services.kernel.sketches, relations, sketch.sketch_id
                )
                component_ids.update(item.sketch_id for item in connected)
            component = tuple(
                sketch for sketch in services.kernel.sketches if sketch.sketch_id in component_ids
            )
            component_entities = [
                entity.entity_id for sketch in component for entity in sketch.entities
            ]
            if len(set(component_entities)) != len(component_entities):
                editor.status_label.setText("关联草图存在重复图元标识，无法安全编辑。")
                return
            background_layers = {
                entity.entity_id: layer for entity, layer in editor.canvas.background_entities
            }
            spatial = {
                (boundary.sketch_id, boundary.entity.entity_id)
                for boundary in editor.canvas.spatial_boundaries
            }
            view_frame = editor.current_frame()

            def accessible_layer(sketch: Sketch, entity: SketchEntity) -> bool:
                layer = background_layers.get(entity.entity_id)
                if layer is None:
                    if (
                        entity.entity_id in committed_ids
                        or (sketch.sketch_id, entity.entity_id) not in spatial
                    ):
                        return False
                    normal_dot = sum(
                        first * second
                        for first, second in zip(
                            sketch.frame.normal, view_frame.normal, strict=True
                        )
                    )
                    delta = tuple(
                        first - second
                        for first, second in zip(
                            sketch.frame.origin_mm, view_frame.origin_mm, strict=True
                        )
                    )
                    if (
                        abs(abs(normal_dot) - 1) > 1e-9
                        or abs(
                            sum(
                                value * normal
                                for value, normal in zip(delta, view_frame.normal, strict=True)
                            )
                        )
                        > 1e-7
                    ):
                        return False
                    table = (
                        merge_layer_tables(sketch.layers, editor.canvas.document_layer_table)
                        if editor.canvas.document_layer_table is not None
                        else sketch.layers
                    )
                    layer = table.get(entity.layer_name)
                return layer.displayed and not layer.locked

            if any(
                not accessible_layer(sketch, entity)
                for sketch in component
                for entity in sketch.entities
            ):
                editor.status_label.setText("关联草图包含锁定或隐藏图层；图元未修改。")
                return
            if any(
                draft_tangent_reference(source).entity_id in component_entities
                for source, _ in editor.canvas.pending_cross_tangencies
            ):
                editor.status_label.setText("请先完成包含相切关系的当前草图，再编辑关联图元。")
                return
            anchors = tuple(
                CrossSketchRef(sketch.sketch_id, entity.entity_id)
                for sketch in sketches
                for entity in sketch.entities
                if entity.entity_id in committed_ids
            )
            proposed = tuple(revised_sketches.get(sketch.sketch_id, sketch) for sketch in component)
            rectangle_transforms: list[RectangleTransformEvidence] = []
            polyline_transforms: list[RectangleTransformEvidence] = []
            line_transforms: list[RectangleTransformEvidence] = []
            if angle is not None or mirror_end is not None:
                related = {
                    (ref.sketch_id, ref.entity_id)
                    for relation in relations
                    for ref in (relation.first, relation.second)
                }
                for sketch in sketches:
                    targets = [
                        entity
                        for entity in sketch.entities
                        if isinstance(entity, RectangleEntity | PolylineEntity | LineEntity)
                        and entity.entity_id in committed_ids
                        and (sketch.sketch_id, entity.entity_id) in related
                    ]
                    if not targets:
                        continue
                    start = sketch.frame.world_to_local(
                        editor.current_frame().local_to_world(displacement)
                    )
                    if mirror_end is not None:
                        end = sketch.frame.world_to_local(
                            editor.current_frame().local_to_world(mirror_end)
                        )
                        dx, dy = end[0] - start[0], end[1] - start[1]
                        length = hypot(dx, dy)
                        if length <= 1e-12:
                            editor.status_label.setText("镜像轴必须有非零长度。")
                            return
                        ux, uy = dx / length, dy / length
                        a, b, c, d = 2 * ux * ux - 1, 2 * ux * uy, 2 * ux * uy, 2 * uy * uy - 1
                    else:
                        assert angle is not None
                        local_angle = project_coplanar_rotation(
                            angle, editor.current_frame(), sketch.frame
                        )
                        a, b, c, d = (
                            cos(radians(local_angle)),
                            -sin(radians(local_angle)),
                            sin(radians(local_angle)),
                            cos(radians(local_angle)),
                        )
                    matrix = (
                        a,
                        b,
                        c,
                        d,
                        start[0] - a * start[0] - b * start[1],
                        start[1] - c * start[0] - d * start[1],
                    )
                    for entity in targets:
                        proof = RectangleTransformEvidence(
                            CrossSketchRef(sketch.sketch_id, entity.entity_id), matrix
                        )
                        if isinstance(entity, RectangleEntity):
                            rectangle_transforms.append(proof)
                        elif isinstance(entity, PolylineEntity):
                            polyline_transforms.append(proof)
                        else:
                            line_transforms.append(proof)
            if not polyline_transforms:
                line_transforms.clear()
            self._submit_cross_sketch_edit(
                editor,
                session_id,
                component,
                proposed,
                anchors,
                action,
                tuple(rectangle_transforms),
                tuple(polyline_transforms),
                tuple(line_transforms),
            )
            return
        removed_relations = tuple(
            relation.relation_id
            for relation in relations
            if erase
            and any(ref.entity_id in committed_ids for ref in (relation.first, relation.second))
        )
        raster_updates: list[DrawingRaster] = []
        for image in images if not erase else ():
            if mirror_end is not None:
                dx, dy = mirror_end[0] - displacement[0], mirror_end[1] - displacement[1]
                axis = atan2(dy, dx)
                c, sn = cos(2 * axis), sin(2 * axis)
                x = image.origin_mm[0] - displacement[0]
                y = image.origin_mm[1] - displacement[1]
                raster_updates.append(
                    replace(
                        image,
                        image_id=uuid4().hex if copy_source else image.image_id,
                        origin_mm=(
                            displacement[0] + c * x + sn * y,
                            displacement[1] + sn * x - c * y,
                        ),
                        angle_deg=degrees(2 * axis) - image.angle_deg,
                        mirrored=not image.mirrored,
                    )
                )
            elif angle is not None:
                c, sn = cos(radians(angle)), sin(radians(angle))
                x = image.origin_mm[0] - displacement[0]
                y = image.origin_mm[1] - displacement[1]
                raster_updates.append(
                    replace(
                        image,
                        image_id=uuid4().hex if copy_source else image.image_id,
                        origin_mm=(
                            displacement[0] + c * x - sn * y,
                            displacement[1] + sn * x + c * y,
                        ),
                        angle_deg=image.angle_deg + angle,
                    )
                )
            elif scale is not None:
                raster_updates.append(
                    replace(
                        image,
                        image_id=uuid4().hex if copy_source else image.image_id,
                        origin_mm=(
                            displacement[0] + (image.origin_mm[0] - displacement[0]) * scale,
                            displacement[1] + (image.origin_mm[1] - displacement[1]) * scale,
                        ),
                        width_mm=image.width_mm * scale,
                        height_mm=image.height_mm * scale,
                    )
                )
            else:
                for index in range(1, copy_count if copy_source else 2):
                    raster_updates.append(
                        replace(
                            image,
                            image_id=uuid4().hex if copy_source else image.image_id,
                            origin_mm=(
                                image.origin_mm[0] + displacement[0] * index,
                                image.origin_mm[1] + displacement[1] * index,
                            ),
                        )
                    )
        self._submit_drawing_revisions(
            editor,
            session_id,
            revisions,
            includes_points,
            action,
            removed_relations,
            raster_remove_ids=tuple(sorted(image_ids)) if erase else (),
            raster_updates=() if copy_source else tuple(raster_updates),
            raster_additions=tuple(raster_updates) if copy_source else (),
            draft_candidate=draft_candidate,
            draft_pending_arrays=draft_pending_arrays,
            text_batch=text_batch,
            draft_remove_constraint_ids=draft_remove_constraint_ids,
            preserve_pending_tangencies=preserve_pending_transform,
            copy_omitted_constraints=copied_without_constraints,
            copy_omitted_array=copied_without_array,
            annotation_appends=annotation_appends,
        )

    def _on_saved_handle_preview(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_token: object,
        raw_reference: object,
        raw_point: object,
        raw_revision: object,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            loaded is None
            or services is None
            or unit is None
            or session_id != self._session_id
            or not isinstance(raw_token, str)
            or not isinstance(raw_reference, SketchGeometryReference)
            or not isinstance(raw_point, tuple)
            or not isinstance(raw_revision, int)
        ):
            return
        values = cast("tuple[object, ...]", raw_point)
        if len(values) != 2 or not all(
            isinstance(item, int | float) and isfinite(item) for item in values
        ):
            return
        token, reference, point, revision = (
            raw_token,
            raw_reference,
            cast("tuple[float, float]", raw_point),
            raw_revision,
        )
        frame = editor.current_frame()
        commands = tuple(loaded.document.commands)
        canvas = editor.canvas
        collection = canvas.collection_session
        collection_snapshot = None
        collection_checkpoint = None
        if collection is not None:
            try:
                collection_snapshot = collection.snapshot
                collection_checkpoint = collection.checkpoint()
            except ValidationError as exc:
                canvas.complete_saved_handle_preview(token, point, None, str(exc))
                return
        previous = canvas.mixed_move
        pairs = tuple(canvas.pending_cross_tangencies)
        mixed: _MixedHandleContext | None = None
        if collection is None and (
            previous is not None or pairs or canvas.pending_associative_arrays
        ):
            if previous is not None and (
                previous.source_revision != revision or previous.original_draft.frame != frame
            ):
                canvas.complete_saved_handle_preview(
                    token, point, None, "暂存草图或工作平面已变化。"
                )
                return
            draft = Sketch(
                editor.draft_sketch_id,
                frame,
                tuple(canvas.entities),
                tuple(canvas.constraints),
                canvas.layer_table,
            )
            saved = previous.original_saved if previous else services.kernel.sketches
            mixed = _MixedHandleContext(
                previous,
                tuple(saved),
                previous.current_saved if previous else tuple(saved),
                previous.original_draft if previous else draft,
                draft,
                canvas.background_entities,
                pairs,
                canvas.mixed_move_timeline_with_tangencies(),
                canvas.history_position,
                tuple(canvas.pending_associative_arrays),
                tuple(
                    arrays
                    for _saved, _draft, _pairs, arrays in canvas.mixed_move_timeline_with_arrays()
                ),
                tuple(
                    transforms
                    for _saved, _draft, _pairs, _arrays, transforms in canvas.mixed_move_timeline_with_transforms()
                ),
            )

        def solve() -> SavedHandlePreview:
            if loaded.document.revision != revision or tuple(loaded.document.commands) != commands:
                raise ValueError("文档已变化，请重新拖动。")
            owners = [
                sketch
                for sketch in (
                    (*mixed.current_saved, mixed.draft)
                    if mixed is not None
                    else collection_snapshot.sketches
                    if collection_snapshot is not None
                    else services.kernel.sketches
                )
                if any(entity.entity_id == reference.entity_id for entity in sketch.entities)
            ]
            if len(owners) != 1:
                raise ValueError("控制点图元不存在或身份不唯一。")
            source = owners[0]
            local_point = source.frame.world_to_local(frame.local_to_world(point))
            if mixed is not None:
                return self._solve_mixed_handle_preview(
                    services,
                    loaded,
                    mixed,
                    source,
                    reference,
                    local_point,
                    frame,
                    revision,
                    session_id,
                )
            if collection_snapshot is not None:
                original, solved, anchors = mycad_app.prepare_cross_sketch_drag_from_state(
                    services,
                    collection_snapshot.sketches,
                    collection_snapshot.cross_tangencies,
                    source.sketch_id,
                    reference,
                    local_point,
                )
                from mycad.core.drawing_transactions import require_independent_geometry_edits

                require_independent_geometry_edits(collection_snapshot.groups, original, solved)
            else:
                original, solved, anchors = mycad_app.prepare_cross_sketch_drag(
                    services, source.sketch_id, reference, local_point
                )
            before = {sketch.sketch_id: sketch for sketch in original}
            overlay: list[tuple[SketchEntity, SketchLayer]] = []
            for sketch in solved:
                for previous, entity in zip(
                    before[sketch.sketch_id].entities, sketch.entities, strict=True
                ):
                    if previous == entity:
                        continue
                    if isinstance(entity, PolylineEntity):
                        view_entity = project_polyline_entity(entity, sketch.frame, frame)
                    elif isinstance(
                        entity, RectangleEntity | PointEntity | SplineEntity | EllipseEntity
                    ):
                        view_entity = project_coplanar_entity(entity, sketch.frame, frame)
                    else:
                        view_entity = project_tangent_entity(entity, sketch.frame, frame)
                    overlay.append(
                        (
                            view_entity,
                            sketch.layers.get(entity.layer_name),
                        )
                    )
            return SavedHandlePreview(
                original,
                solved,
                anchors,
                tuple(overlay),
                collection_checkpoint=collection_checkpoint,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            if collection is not None:
                try:
                    if (
                        canvas.collection_session is not collection
                        or collection.checkpoint() != collection_checkpoint
                    ):
                        raise ValidationError("暂存内容已变化，请重新拖动。")
                except ValidationError as exc:
                    canvas.cancel_saved_handle_drag(str(exc), token=token)
                    return
            preview = result.value if isinstance(result.value, SavedHandlePreview) else None
            editor.canvas.complete_saved_handle_preview(token, point, preview, result.error)

        if not unit.submit(
            solve, operation="saved-handle-preview", session_id=session_id, on_complete=finish
        ):
            editor.canvas.complete_saved_handle_preview(
                token, point, None, "几何工作线程忙碌，请重试。"
            )

    def _solve_mixed_handle_preview(
        self,
        services: AppServices,
        loaded: LoadedDocument,
        context: _MixedHandleContext,
        source: Sketch,
        reference: SketchGeometryReference,
        local_point: tuple[float, float],
        frame: WorkPlaneFrame,
        revision: int,
        session_id: int,
    ) -> SavedHandlePreview:
        """Solve and replay-check a handle against the current mixed draft."""
        saved, draft, anchors = mycad_app.prepare_mixed_handle_drag(
            services,
            context.current_saved,
            context.draft,
            context.pairs,
            _staged_committed_tangencies(
                context.original_saved,
                services.kernel.cross_sketch_tangencies,
                tuple(
                    (saved, transforms)
                    for (saved, _draft, _pairs), transforms in zip(
                        context.history, context.transform_history, strict=True
                    )
                ),
            ),
            CrossSketchRef(source.sketch_id, reference.entity_id),
            reference,
            local_point,
        )
        before = {item.sketch_id: item for item in (*context.current_saved, context.draft)}
        projected: dict[str, SketchEntity] = {}
        overlay: list[tuple[SketchEntity, SketchLayer]] = []
        background_ids = {entity.entity_id for entity, _layer in context.background}
        for sketch in (*saved, draft):
            for original, entity in zip(
                before[sketch.sketch_id].entities, sketch.entities, strict=True
            ):
                if entity == original and (
                    sketch.sketch_id == draft.sketch_id or entity.entity_id not in background_ids
                ):
                    continue
                if isinstance(entity, PolylineEntity):
                    view_entity = project_polyline_entity(entity, sketch.frame, frame)
                elif isinstance(
                    entity, RectangleEntity | PointEntity | SplineEntity | EllipseEntity
                ):
                    view_entity = project_coplanar_entity(entity, sketch.frame, frame)
                else:
                    view_entity = project_tangent_entity(entity, sketch.frame, frame)
                if sketch.sketch_id != draft.sketch_id:
                    if entity.entity_id in projected:
                        raise ValueError("关联图元身份重复。")
                    projected[entity.entity_id] = view_entity
                if entity != original:
                    overlay.append((view_entity, sketch.layers.get(entity.layer_name)))
        background = tuple(
            (projected.get(item.entity_id, item), layer) for item, layer in context.background
        )
        previous = context.previous
        state = MixedMoveState(
            previous.transaction_id if previous else uuid4().hex,
            revision,
            context.original_draft,
            context.original_saved,
            saved,
            previous.base_background if previous else context.background,
            background,
            previous.original_cross_tangencies if previous else context.pairs,
            previous.original_associative_arrays if previous else context.arrays,
        )
        steps = tuple((items, item) for items, item, _pairs in context.history) + ((saved, draft),)
        pairs_by_step = tuple(pairs for _items, _item, pairs in context.history) + (context.pairs,)
        candidate = mycad_app.stage_mixed_drawing_timeline(
            services,
            loaded,
            context.original_draft,
            context.original_saved,
            steps,
            session_identity=session_id,
            cross_pairs_by_step=pairs_by_step,
            arrays_by_step=(*context.array_history, context.arrays),
            initial_cross_pairs=state.original_cross_tangencies,
            initial_associative_arrays=state.original_associative_arrays,
            rectangle_transforms_by_step=(*context.transform_history, ()),
        )
        try:
            result = candidate.preview(current_session_identity=session_id)
            if result.state != "succeeded":
                raise ValueError(str(result.failure or "混合拖动预览失败。"))
        finally:
            candidate.cancel()
        return SavedHandlePreview(
            (*context.current_saved, context.draft),
            (*saved, draft),
            anchors,
            tuple(overlay),
            state,
            draft,
            previous,
            context.draft,
            context.pairs,
            context.history_position,
        )

    def _on_saved_handle_commit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_token: object,
        raw_preview: object,
        raw_revision: object,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if (
            loaded is None
            or services is None
            or unit is None
            or session_id != self._session_id
            or not isinstance(raw_token, str)
            or not isinstance(raw_preview, SavedHandlePreview)
            or not isinstance(raw_revision, int)
        ):
            return
        token, preview, revision = raw_token, raw_preview, raw_revision

        def still_current() -> bool:
            return (
                self._loaded is loaded
                and self._session_id == session_id
                and editor.canvas.saved_handle_commit_is_current(token, revision)
            )

        if preview.collection_checkpoint is not None:
            canvas = editor.canvas
            collection = canvas.collection_session
            try:
                if (
                    not still_current()
                    or collection is None
                    or collection.checkpoint() != preview.collection_checkpoint
                ):
                    raise ValidationError("暂存内容已变化，请重新拖动。")
                revisions = mycad_app.build_tangency_revisions(preview.original, preview.solved)
                if not canvas.stage_collection_operation(
                    ReplayAppend(
                        "drawing.sketch.revise", 79, {"revisions": list(revisions)}, "local"
                    )
                ):
                    raise ValidationError(canvas.message)
            except (ValidationError, ValueError) as exc:
                canvas.finish_saved_handle_commit(token, str(exc))
                return
            canvas.finish_saved_handle_commit(token, None)
            return

        if preview.mixed_state is not None:
            before = preview.draft_before
            canvas = editor.canvas
            if (
                not still_current()
                or before is None
                or preview.mixed_draft is None
                or canvas.mixed_move != preview.mixed_before
                or tuple(canvas.entities) != before.entities
                or tuple(canvas.constraints) != before.constraints
                or canvas.layer_table != before.layers
                or editor.current_frame() != before.frame
                or tuple(canvas.pending_cross_tangencies) != preview.pairs_before
                or canvas.history_position != preview.history_before
            ):
                canvas.finish_saved_handle_commit(token, "草稿或来源已变化，请重新拖动。")
                return
            try:
                canvas.apply_mixed_move(
                    preview.mixed_state,
                    preview.mixed_draft.entities,
                    constraints=preview.mixed_draft.constraints,
                )
            except (KeyError, ValueError) as exc:
                canvas.finish_saved_handle_commit(token, str(exc))
                return
            canvas.finish_saved_handle_commit(token, None)
            canvas.message = "混合控制点拖动已暂存；完成草图时提交，可撤销。"
            canvas.changed.emit()
            return

        def commit() -> object:
            return mycad_app.commit_cross_sketch_drag(
                services,
                loaded,
                preview.original,
                preview.solved,
                preview.anchors,
                session_identity=session_id,
                still_current=still_current,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._sketch_dialog is not editor
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            editor.canvas.finish_saved_handle_commit(token, result.error)
            if result.error is None:
                self._sync_drawing_layers()
                editor.layer_history_boundaries[len(loaded.document.commands)] = (
                    editor.canvas.history_position
                )
                editor.layer_history_redo.clear()
                editor.canvas.discard_redo_history()

        if not unit.submit(
            commit, operation="saved-handle-commit", session_id=session_id, on_complete=finish
        ):
            editor.canvas.finish_saved_handle_commit(token, "几何工作线程忙碌，请重试。")

    def _submit_cross_sketch_edit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        original: tuple[Sketch, ...],
        proposed: tuple[Sketch, ...],
        anchors: tuple[CrossSketchRef, ...],
        action: str,
        rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
        polyline_transforms: tuple[RectangleTransformEvidence, ...] = (),
        line_transforms: tuple[RectangleTransformEvidence, ...] = (),
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        editor.setEnabled(False)

        def update() -> object:
            return mycad_app.commit_cross_sketch_edit(
                services,
                loaded,
                original,
                proposed,
                anchors,
                session_identity=session_id,
                rectangle_transforms=rectangle_transforms,
                polyline_transforms=polyline_transforms,
                line_transforms=line_transforms,
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
            editor.status_label.setText(f"已{action}所选对象及其相切关联；可撤销。")

        if not unit.submit(
            update, operation="drawing-move", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            editor.status_label.setText(f"几何工作线程忙碌，{action}未应用。")

    def _undo_saved_line_edit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        identity: str,
        position: int,
        revision: int,
        *,
        mixed_copy: bool = False,
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        commands = loaded.document.commands if loaded is not None else ()
        matching = [
            index for index, command in enumerate(commands) if command.instance_id == identity
        ]
        trailing = commands[matching[0] + 1 :] if len(matching) == 1 else ()
        settings_only = bool(trailing) and all(
            command.id in {"drawing.fillet_radius.set", "drawing.chamfer_values.set"}
            for command in trailing
        )
        current_revision = loaded.document.revision if loaded is not None else -1
        valid_history = (
            len(matching) == 1 and current_revision == revision and (not trailing or settings_only)
        )
        mixed_draft = (
            editor.mixed_draft_history.get(matching[0] + 1)
            if mixed_copy and len(matching) == 1 and not trailing
            else None
        )
        if mixed_draft is not None and mixed_draft[2] != identity:
            mixed_draft = None
        requires_mixed_draft = (
            mixed_copy
            and len(matching) == 1
            and (
                commands[matching[0]].id == "drawing.raster.batch"
                or editor.canvas.has_mixed_draft_copy(identity)
            )
        )
        if (
            loaded is None
            or services is None
            or unit is None
            or session_id != self._session_id
            or self._sketch_dialog is not editor
            or unit.is_busy
            or unit.is_delivering_result
            or editor.canvas.history_position != position
            or not valid_history
            or (requires_mixed_draft and mixed_draft is None)
            or (
                mixed_draft is not None
                and not editor.canvas.mixed_draft_history_matches(
                    mixed_draft[0], mixed_draft[1], redo=False
                )
            )
        ):
            editor.status_label.setText("文档或草稿历史已变化；不能撤销当前命令的编辑。")
            return

        def undo() -> None:
            if loaded.document.revision != current_revision:
                raise ValueError("文档历史已变化，撤销未执行。")
            if settings_only:
                loaded.bus.undo_operation_before_drawing_settings(identity, current_revision)
            else:
                loaded.bus.undo_operation()
            services.kernel.viewport_data()

        def finish(result: ExecutionResult) -> None:
            if mixed_draft is not None:
                editor.setEnabled(True)
            if self._loaded is not loaded or self._session_id != session_id:
                return
            if result.error is None and self._sketch_dialog is editor:
                if mixed_draft is not None:
                    editor.canvas.undo_mixed_draft_copy(mixed_draft[0], mixed_draft[1])
                    editor.layer_history_redo.append((matching[0] + 1, mixed_draft[0]))
                previous = next(
                    (
                        command.instance_id
                        for command in reversed(loaded.document.commands)
                        if command.id
                        not in {"drawing.fillet_radius.set", "drawing.chamfer_values.set"}
                    ),
                    None,
                )
                if mixed_copy:
                    editor.canvas.finish_mixed_copy_undo(identity, loaded.document.revision)
                else:
                    editor.canvas.finish_saved_line_edit_undo(
                        identity, previous, loaded.document.revision
                    )
            self._finish_worker_action(result, "撤销")

        if mixed_draft is not None:
            editor.setEnabled(False)
        if not unit.submit(undo, operation="undo", session_id=session_id, on_complete=finish):
            if mixed_draft is not None:
                editor.setEnabled(True)
            editor.status_label.setText("几何工作线程忙碌，请稍后重试撤销。")

    def _on_saved_line_edit(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        mode: object,
        identity: object,
        edited: object,
    ) -> None:
        services, loaded = self._services, self._loaded
        source_sketch_id: str | None = None
        if isinstance(identity, tuple):
            raw_identity = cast("tuple[object, ...]", identity)
            if (
                len(raw_identity) == 2
                and isinstance(raw_identity[0], str)
                and isinstance(raw_identity[1], str)
            ):
                identity, source_sketch_id = raw_identity[0], raw_identity[1]
        if (
            services is None
            or loaded is None
            or session_id != self._session_id
            or not isinstance(mode, str)
            or mode not in {"修剪", "延伸", "分割", "单点打断"}
            or not isinstance(identity, str)
            or not isinstance(edited, tuple)
        ):
            return
        canvas = editor.canvas

        def reject(message: str) -> None:
            canvas.message = message
            if mode == "单点打断":
                self.status_command.setText(message)
            editor.status_label.setText(message)

        previous = canvas.mixed_move
        session = canvas.collection_session
        saved = (
            tuple(
                sketch
                for sketch in session.snapshot.sketches
                if sketch.sketch_id != editor.draft_sketch_id
            )
            if session is not None
            else services.kernel.sketches
        )
        if previous is None and (
            canvas.source_context_revision != loaded.document.revision
            or tuple(editor.dimension_sources()[1:]) != saved
        ):
            self._sync_drawing_layers()
            reject("文档已变化；图元未修改。")
            return
        if previous is not None and (
            loaded.document.revision != previous.source_revision
            or editor.current_frame() != previous.original_draft.frame
            or not canvas.mixed_move_is_valid
        ):
            reject("文档或工作平面已变化；暂存修改未应用。")
            return
        current_saved = previous.current_saved if previous else saved
        candidates = [
            sketch
            for sketch in current_saved
            if source_sketch_id is None or sketch.sketch_id == source_sketch_id
            if any(entity.entity_id == identity for entity in sketch.entities)
        ]
        if len(candidates) != 1:
            reject("目标身份不唯一或已变化；图元未修改。")
            return
        sketch = candidates[0]
        fragments = cast("tuple[SketchEntity, ...]", edited)
        if fragments:
            try:
                fragments = tuple(
                    project_coplanar_entity(entity, editor.current_frame(), sketch.frame)
                    for entity in fragments
                )
            except ValueError as exc:
                reject(f"编辑结果无法映射到来源草图；图元未修改：{exc}")
                return
        revised_entities: list[SketchEntity] = []
        for entity in sketch.entities:
            if entity.entity_id == identity:
                revised_entities.extend(fragments)
            else:
                revised_entities.append(entity)
        revised = replace(sketch, entities=tuple(revised_entities))
        original_target = next(
            (entity for entity in sketch.entities if entity.entity_id == identity), None
        )
        if mode == "单点打断" and isinstance(original_target, LineEntity | ArcEntity):
            proof = (
                unique_split_line_relation_fragment
                if isinstance(original_target, LineEntity)
                else unique_split_arc_relation_fragment
            )
            updated_saved = tuple(
                revised if item.sketch_id == sketch.sketch_id else item for item in current_saved
            )
            relations = (
                session.snapshot.cross_tangencies
                if session is not None
                else services.kernel.cross_sketch_tangencies
            )
            for relation in relations:
                for ref in (relation.first, relation.second):
                    if (
                        ref.sketch_id == sketch.sketch_id
                        and ref.entity_id == identity
                        and proof(current_saved, updated_saved, relation, ref) is None
                    ):
                        reject("无法唯一确定打断后的相切片段；图元未修改。")
                        return
        if mode in {"修剪", "单点打断"}:
            try:
                revised = replace(
                    revised,
                    constraints=rebind_retained_local_tangencies(
                        sketch,
                        revised,
                        allow_fragment_rebind=True,
                        allow_split_lines=mode == "单点打断",
                        allow_split_arcs=mode == "单点打断",
                    ),
                )
            except ValueError as exc:
                reject(f"{mode}无法保留相切关系；图元未修改：{exc}")
                return
        if revised == sketch:
            reject(f"{mode}未改变图元。")
            return
        if mode in {"单点打断", "分割", "修剪", "延伸"}:
            from mycad.core.drawing_groups import DrawingObjectRef
            from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

            ref = DrawingObjectRef("geometry", identity, sketch.sketch_id)
            group_snapshot = (
                canvas.collection_session.snapshot.groups
                if canvas.collection_session is not None
                else services.kernel.drawing_groups
            )
            grouped = any(ref in group.members for group in group_snapshot)
            if grouped or canvas.collection_session is not None:
                if any(group.selectable and ref in group.members for group in group_snapshot):
                    reject("组选择已启用；请先关闭组选择再编辑单个成员。")
                    return
                try:
                    session = self._ensure_collection_session(editor)
                    source = next(
                        item
                        for item in session.snapshot.sketches
                        if item.sketch_id == sketch.sketch_id
                    )
                    if source != sketch:
                        raise ValidationError("来源草图已变化，请重新选择。")
                    replacements = tuple(
                        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
                        for item in fragments
                    )
                    operation = prepare_grouped_sketch_replacements(
                        (sketch,),
                        (revised,),
                        group_snapshot,
                        {ref: replacements} if grouped else {},
                    )
                    if not canvas.stage_collection_operation(operation):
                        reject(canvas.message)
                        return
                except (ValidationError, ValueError, StopIteration) as exc:
                    reject(f"{mode}未应用：{exc}")
                    return
                canvas.message = (
                    f"{mode}完成；组成员已更新，可撤销。" if grouped else f"{mode}完成，可撤销。"
                )
                editor.status_label.setText(canvas.message)
                return
        if canvas.entities or previous is not None:
            original_draft = (
                previous.original_draft
                if previous
                else Sketch(
                    editor.draft_sketch_id,
                    editor.current_frame(),
                    tuple(canvas.entities),
                    constraints=tuple(canvas.constraints),
                    layers=canvas.layer_table,
                )
            )
            original_saved = previous.original_saved if previous else services.kernel.sketches
            background = canvas.background_entities
            layer = next(
                (layer for entity, layer in background if entity.entity_id == identity), None
            )
            if layer is None:
                reject("目标图元已变化；暂存修改未应用。")
                return
            overlay: list[tuple[SketchEntity, SketchLayer]] = []
            for entity, item_layer in background:
                if entity.entity_id == identity:
                    overlay.extend(
                        (item, layer) for item in cast("tuple[SketchEntity, ...]", edited)
                    )
                else:
                    overlay.append((entity, item_layer))
            proposed = MixedMoveState(
                previous.transaction_id if previous else uuid4().hex,
                previous.source_revision if previous else loaded.document.revision,
                original_draft,
                tuple(original_saved),
                tuple(
                    revised if item.sketch_id == sketch.sketch_id else item
                    for item in current_saved
                ),
                previous.base_background if previous else background,
                tuple(overlay),
                previous.original_cross_tangencies
                if previous
                else tuple(canvas.pending_cross_tangencies),
                previous.original_associative_arrays
                if previous
                else tuple(canvas.pending_associative_arrays),
            )
            draft = replace(
                original_draft,
                entities=tuple(canvas.entities),
                constraints=tuple(canvas.constraints),
                layers=canvas.layer_table,
            )
            self._preview_mixed_drawing_change(editor, session_id, proposed, draft, action=mode)
            return
        frozen = revised.to_state_mapping()
        revisions: list[dict[str, object]] = [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": frozen["entities"],
                "constraints": frozen["constraints"],
            }
        ]
        self._submit_drawing_revisions(
            editor,
            session_id,
            revisions,
            any(isinstance(entity, PointEntity) for entity in revised.entities),
            mode,
        )

    def _on_delete_drawing_dimensions(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_ids: object,
        *,
        annotation_appends: tuple[ReplayAppend, ...] = (),
        text_batch: dict[str, object] | None = None,
        draft_candidate: tuple[SketchEntity, ...] | None = None,
        draft_remove_constraint_ids: frozenset[str] = frozenset(),
    ) -> None:
        loaded, services = self._loaded, self._services
        if (
            loaded is None
            or services is None
            or session_id != self._session_id
            or not isinstance(raw_ids, tuple)
        ):
            return
        raw_values = cast("tuple[object, ...]", raw_ids)
        if not raw_values or any(not isinstance(identity, str) for identity in raw_values):
            return
        ids = set(cast("tuple[str, ...]", raw_values))
        canvas = editor.canvas
        previous = canvas.mixed_move
        if annotation_appends and (
            previous is not None
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
            or (draft_candidate is None and any(c.constraint_id in ids for c in canvas.constraints))
        ):
            editor.status_label.setText("请先完成草稿与暂存关联，再删除阵列尺寸和标注。")
            return
        image_ids = set(canvas.selected_raster_ids)
        images = tuple(image for image in canvas.drawing_rasters if image.image_id in image_ids)
        if image_ids and (
            len(images) != len(image_ids)
            or any(
                canvas.layer_table.get(image.layer_name).locked
                or not canvas.layer_table.get(image.layer_name).displayed
                for image in images
            )
            or previous is not None
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
        ):
            editor.status_label.setText("图片不可编辑或存在暂存关联；所选对象未删除。")
            return
        if previous is not None and (
            loaded.document.revision != previous.source_revision
            or not canvas.mixed_move_is_valid
            or editor.current_frame() != previous.original_draft.frame
        ):
            editor.status_label.setText("文档或工作平面已变化；标注未删除。")
            return
        if previous is None and canvas.source_context_revision != loaded.document.revision:
            self._sync_drawing_layers()
            editor.status_label.setText("文档已变化；所选对象未删除。")
            return
        originals = previous.current_saved if previous else services.kernel.sketches
        tools = canvas.geometric_tolerance_tools
        selected_annotations: set[str] = (
            tools.selected_ids if tools is not None and annotation_appends else set()
        )
        entity_ids = set(canvas.selected_entity_ids)
        removed_dimensions = ids | {
            constraint.constraint_id
            for sketch in originals
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
            and any(reference.entity_id in entity_ids for reference in constraint.references)
        }
        if _dimensions_have_unselected_tolerance_attachment(
            originals,
            services.kernel.drawing_tolerance_frames,
            services.kernel.drawing_datum_identifiers,
            removed_dimensions,
            selected_annotations,
        ):
            editor.status_label.setText("草图尺寸仍被标注附着；请先解除附着或同时删除该标注。")
            return
        if image_ids and any(
            constraint.constraint_id in ids
            or any(ref.entity_id in entity_ids for ref in constraint.references)
            for constraint in canvas.constraints
        ):
            editor.status_label.setText("所选对象涉及暂存标注或约束；请先完成草稿。")
            return
        selected_entities = [
            entity for entity in canvas.selectable_entities() if entity.entity_id in entity_ids
        ]
        if (
            len(selected_entities) != len(entity_ids)
            or {entity.entity_id for entity in selected_entities} != entity_ids
        ):
            editor.status_label.setText("图元不可编辑或身份不唯一；所选对象未删除。")
            return
        if any(
            entity.entity_id in entity_ids and (layer.locked or not layer.displayed)
            for entity, layer in canvas.background_entities
        ) or any(
            entity.entity_id in entity_ids
            and (
                canvas.layer_table.get(entity.layer_name).locked
                or not canvas.layer_table.get(entity.layer_name).displayed
            )
            for entity in canvas.entities
        ):
            editor.status_label.setText("所选图元所在图层隐藏或已锁定；对象未删除。")
            return
        if entity_ids:
            arrays = (*services.kernel.associative_arrays, *canvas.pending_associative_arrays)
            array_targets = {
                ref.entity_id
                for array in arrays
                for ref in (
                    *(member.target for member in array.members if member.erased_index is None),
                    *(output.target for output in array.extra_outputs),
                )
            }
            array_refs = {
                ref.entity_id
                for array in arrays
                for ref in (
                    *array.sources,
                    *(member.source for member in array.members),
                    *(member.target for member in array.members),
                    *(member.replacement.source for member in array.members if member.replacement),
                    *(output.source for output in array.extra_outputs),
                    *(output.target for output in array.extra_outputs),
                    *(output.anchor_source for output in array.extra_outputs),
                )
            }
            if entity_ids & (array_refs - array_targets):
                editor.status_label.setText("所选图元有关联阵列；请分别处理。")
                return
        matches = [
            constraint
            for sketch in originals
            for constraint in sketch.constraints
            if constraint.constraint_id in ids
        ]
        matches.extend(
            constraint for constraint in canvas.constraints if constraint.constraint_id in ids
        )
        if len(matches) != len(ids) or any(
            constraint.kind not in DIMENSION_KINDS and constraint.kind != "tangent"
            for constraint in matches
        ):
            editor.status_label.setText("约束身份不唯一、不受支持或已变化；请重新选择。")
            return
        if any(
            canvas.annotation_layer(item).locked or not canvas.annotation_layer(item).displayed
            for item in matches
        ):
            editor.status_label.setText("标注图层隐藏或已锁定；标注未删除。")
            return
        if any(
            any(ref.entity_id in entity_ids for ref in constraint.references)
            and (
                canvas.annotation_layer(constraint).locked
                or not canvas.annotation_layer(constraint).displayed
            )
            for constraint in (
                *canvas.constraints,
                *(constraint for sketch in originals for constraint in sketch.constraints),
            )
        ):
            editor.status_label.setText("相关约束位于已锁定或隐藏图层；所选对象未删除。")
            return
        current = tuple(
            replace(
                sketch,
                entities=tuple(
                    entity for entity in sketch.entities if entity.entity_id not in entity_ids
                ),
                constraints=tuple(
                    c
                    for c in sketch.constraints
                    if c.constraint_id not in ids
                    and not any(ref.entity_id in entity_ids for ref in c.references)
                ),
            )
            for sketch in originals
        )
        if (
            (canvas.entities or canvas.constraints or previous is not None)
            and not image_ids
            and not annotation_appends
        ):
            original_draft = (
                previous.original_draft
                if previous
                else Sketch(
                    editor.draft_sketch_id,
                    editor.current_frame(),
                    tuple(canvas.entities),
                    constraints=tuple(canvas.constraints),
                    layers=canvas.layer_table,
                )
            )
            draft = replace(
                original_draft,
                entities=tuple(
                    entity for entity in canvas.entities if entity.entity_id not in entity_ids
                ),
                constraints=tuple(
                    c
                    for c in canvas.constraints
                    if c.constraint_id not in ids
                    and not any(ref.entity_id in entity_ids for ref in c.references)
                ),
                layers=canvas.layer_table,
            )
            proposed = MixedMoveState(
                previous.transaction_id if previous else uuid4().hex,
                previous.source_revision if previous else loaded.document.revision,
                original_draft,
                previous.original_saved if previous else services.kernel.sketches,
                current,
                previous.base_background if previous else canvas.background_entities,
                tuple(
                    (entity, layer)
                    for entity, layer in canvas.background_entities
                    if entity.entity_id not in entity_ids
                ),
                previous.original_cross_tangencies
                if previous
                else tuple(canvas.pending_cross_tangencies),
                previous.original_associative_arrays
                if previous
                else tuple(canvas.pending_associative_arrays),
            )
            pending_targets = tuple(
                ref
                for array in canvas.pending_associative_arrays
                for ref in (
                    *(member.target for member in array.members if member.erased_index is None),
                    *(output.target for output in array.extra_outputs),
                )
                if ref.entity_id in entity_ids
            )
            pending_arrays = None
            if pending_targets:
                try:
                    prior_draft = replace(
                        original_draft,
                        entities=tuple(canvas.entities),
                        constraints=tuple(canvas.constraints),
                        layers=canvas.layer_table,
                    )
                    _, pending_arrays = erase_drawing_entities(
                        strip_erased_member_dimensions(
                            (prior_draft, *originals), (draft, *current), pending_targets
                        ),
                        tuple(canvas.pending_associative_arrays),
                        pending_targets,
                    )
                except (KeyError, ValueError) as exc:
                    editor.status_label.setText(f"混合删除失败：{exc}")
                    return
            self._preview_mixed_drawing_change(
                editor, session_id, proposed, draft, erase=True, pending_arrays=pending_arrays
            )
            return
        revisions: list[dict[str, object]] = []
        for before, after in zip(originals, current, strict=True):
            if before != after:
                state = after.to_state_mapping()
                revisions.append(
                    {
                        "sketch_id": before.sketch_id,
                        "base_state_sha256": before.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                )
        if revisions:
            self._submit_drawing_revisions(
                editor,
                session_id,
                revisions,
                any(
                    isinstance(entity, PointEntity)
                    for sketch in current
                    for entity in sketch.entities
                ),
                "删除约束" if any(item.kind == "tangent" for item in matches) else "删除标注",
                tuple(
                    relation.relation_id
                    for relation in services.kernel.cross_sketch_tangencies
                    if any(ref.entity_id in entity_ids for ref in (relation.first, relation.second))
                ),
                tuple(
                    ref
                    for array in services.kernel.associative_arrays
                    for ref in (
                        *(member.target for member in array.members if member.erased_index is None),
                        *(output.target for output in array.extra_outputs),
                    )
                    if ref.entity_id in entity_ids
                ),
                raster_remove_ids=tuple(sorted(image_ids)),
                annotation_appends=annotation_appends,
                text_batch=text_batch,
                draft_candidate=draft_candidate,
                draft_remove_constraint_ids=draft_remove_constraint_ids,
            )

    def _on_saved_drag_trim(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        raw_events: object,
        raw_draft: object,
        raw_constraints: object,
        raw_background: object,
        raw_revision: object,
    ) -> None:
        services, loaded = self._services, self._loaded
        if (
            services is None
            or loaded is None
            or session_id != self._session_id
            or not isinstance(raw_events, tuple)
            or not isinstance(raw_draft, tuple)
            or not isinstance(raw_constraints, tuple)
            or not isinstance(raw_background, tuple)
            or not isinstance(raw_revision, int)
        ):
            return
        action = (
            "直线圆角"
            if editor.canvas.tool == "二维圆角"
            else "二维倒角"
            if editor.canvas.tool == "二维倒角"
            else "偏移删除源"
            if editor.canvas.active_transform == "offset"
            else "围栏延伸"
            if editor.canvas.tool == "延伸"
            else "拖动修剪"
        )
        if loaded.document.revision != raw_revision:
            self._sync_drawing_layers()
            editor.status_label.setText(f"文档已变化；{action}未应用。")
            return
        canvas = editor.canvas
        previous = canvas.mixed_move
        if previous is not None and (
            loaded.document.revision != previous.source_revision
            or editor.current_frame() != previous.original_draft.frame
            or not canvas.mixed_move_is_valid
        ):
            self._sync_drawing_layers()
            editor.status_label.setText(f"文档或工作平面已变化；{action}未应用。")
            return
        original = (
            previous.current_saved
            if previous is not None
            else tuple(
                sketch
                for sketch in canvas.collection_session.snapshot.sketches
                if sketch.sketch_id != editor.draft_sketch_id
            )
            if canvas.collection_session is not None
            else services.kernel.sketches
        )
        if previous is None and tuple(editor.dimension_sources()[1:]) != original:
            self._sync_drawing_layers()
            editor.status_label.setText(f"文档已变化；{action}未应用。")
            return
        raw_pairs = cast("tuple[tuple[object, tuple[SketchEntity, ...]], ...]", raw_events)
        events: list[tuple[str, tuple[SketchEntity, ...]]] = []
        event_sources: list[str | None] = []
        for raw_identity, fragments in raw_pairs:
            if isinstance(raw_identity, str):
                events.append((raw_identity, fragments))
                event_sources.append(None)
            elif isinstance(raw_identity, tuple):
                parts = cast("tuple[object, ...]", raw_identity)
                if len(parts) != 2 or not all(isinstance(item, str) for item in parts):
                    editor.status_label.setText(f"目标身份无效；{action}未应用。")
                    return
                identity, owner = parts
                if not isinstance(identity, str) or not isinstance(owner, str):
                    return
                events.append((identity, fragments))
                event_sources.append(owner)
            else:
                editor.status_label.setText(f"目标身份无效；{action}未应用。")
                return
        current = list(original)
        for (identity, projected), owner in zip(events, event_sources, strict=True):
            owners = [
                (index, sketch)
                for index, sketch in enumerate(current)
                if owner is None or sketch.sketch_id == owner
                if any(entity.entity_id == identity for entity in sketch.entities)
            ]
            if len(owners) != 1:
                editor.status_label.setText(f"目标身份不唯一或已变化；{action}未应用。")
                return
            index, sketch = owners[0]
            fragments = projected
            if fragments:
                try:
                    fragments = tuple(
                        project_coplanar_entity(entity, editor.current_frame(), sketch.frame)
                        for entity in fragments
                    )
                except ValueError as exc:
                    editor.status_label.setText(f"编辑结果无法映射到来源草图；图元未修改：{exc}")
                    return
            result: list[SketchEntity] = []
            for entity in sketch.entities:
                if entity.entity_id == identity:
                    result.extend(fragments)
                else:
                    result.append(entity)
            revised = replace(sketch, entities=tuple(result))
            if action == "拖动修剪":
                try:
                    revised = replace(
                        revised,
                        constraints=rebind_retained_local_tangencies(
                            sketch, revised, allow_fragment_rebind=True
                        ),
                    )
                except ValueError as exc:
                    editor.status_label.setText(f"修剪无法保留相切关系；图元未修改：{exc}")
                    return
            if action in {"直线圆角", "二维倒角"}:
                try:
                    revised = replace(
                        revised,
                        constraints=rebind_unchanged_user_polyline_constraints(
                            sketch, revised, include_inferred=True
                        ),
                    )
                except ValueError as exc:
                    editor.canvas.finish_fillet_candidate(success=False)
                    editor.status_label.setText(f"{action}无法保留约束；图元未修改：{exc}")
                    return
            current[index] = revised
        if action in {"拖动修剪", "围栏延伸", "二维倒角", "直线圆角", "偏移删除源"}:
            from mycad.core.drawing_groups import DrawingObjectRef
            from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

            groups = (
                canvas.collection_session.snapshot.groups
                if canvas.collection_session is not None
                else services.kernel.drawing_groups
            )
            saved_events = tuple(
                (identity, tuple(fragment.entity_id for fragment in fragments))
                for identity, fragments in events
            )
            draft_events = canvas.collection_trim_draft_events
            changed_refs = {
                member
                for group in groups
                for member in group.members
                if member.kind == "geometry"
                and (
                    member.sketch_id == editor.draft_sketch_id
                    and any(identity == member.object_id for identity, _ in draft_events)
                    or any(
                        member.sketch_id == sketch.sketch_id
                        and any(entity.entity_id == member.object_id for entity in sketch.entities)
                        for sketch in original
                    )
                    and any(
                        identity == member.object_id
                        and (owner is None or owner == member.sketch_id)
                        for (identity, _), owner in zip(saved_events, event_sources, strict=True)
                    )
                )
            }
            if changed_refs or canvas.collection_session is not None:
                if any(
                    group.selectable and changed_refs.intersection(group.members)
                    for group in groups
                ):
                    if action in {"二维倒角", "直线圆角"}:
                        canvas.finish_fillet_candidate(success=False)
                    if action == "偏移删除源":
                        canvas.finish_collection_offset(success=False)
                    canvas.message = "组选择已启用；请先关闭组选择再编辑单个成员。"
                    editor.status_label.setText(canvas.message)
                    return
                try:
                    session = canvas.collection_session or self._ensure_collection_session(
                        editor, allow_offset_completion=action == "偏移删除源"
                    )
                    mapping: dict[DrawingObjectRef, tuple[DrawingObjectRef, ...]] = {}
                    for ref in changed_refs:
                        if action == "偏移删除源":
                            existing = {item.entity_id for item in canvas.entities}
                            added = tuple(
                                DrawingObjectRef("geometry", item.entity_id, editor.draft_sketch_id)
                                for item in cast("tuple[SketchEntity, ...]", raw_draft)
                                if item.entity_id not in existing
                            )
                            if len(events) != 1 or not added:
                                raise ValidationError("无法确定偏移结果的组成员映射。")
                            mapping[ref] = added
                            continue
                        identities = (ref.object_id,)
                        relevant_events = (
                            draft_events
                            if ref.sketch_id == editor.draft_sketch_id
                            else tuple(
                                event
                                for event, owner in zip(saved_events, event_sources, strict=True)
                                if owner is None or owner == ref.sketch_id
                            )
                        )
                        for identity, fragments in relevant_events:
                            identities = tuple(
                                result
                                for item in identities
                                for result in (fragments if item == identity else (item,))
                            )
                        mapped_refs = tuple(
                            replace(ref, object_id=item) for item in dict.fromkeys(identities)
                        )
                        mapping[ref] = mapped_refs
                    collection_before: list[Sketch] = []
                    collection_after: list[Sketch] = []
                    for before, after in zip(original, current, strict=True):
                        if before == after:
                            continue
                        source = next(
                            item
                            for item in session.snapshot.sketches
                            if item.sketch_id == before.sketch_id
                        )
                        if source != before:
                            raise ValidationError("来源草图已变化，请重新选择。")
                        collection_before.append(before)
                        collection_after.append(after)
                    draft_source = next(
                        item
                        for item in session.snapshot.sketches
                        if item.sketch_id == editor.draft_sketch_id
                    )
                    draft_after = replace(
                        draft_source,
                        entities=cast("tuple[SketchEntity, ...]", raw_draft),
                        constraints=cast("tuple[SketchConstraint, ...]", raw_constraints),
                    )
                    if draft_after != draft_source:
                        collection_before.append(draft_source)
                        collection_after.append(draft_after)
                    cross_tangencies = (
                        mycad_app.draft_cross_relations(
                            current, draft_after, canvas.fillet_pending_cross_tangencies
                        )
                        if action == "直线圆角"
                        else ()
                    )
                    operation = prepare_grouped_sketch_replacements(
                        tuple(collection_before),
                        tuple(collection_after),
                        groups,
                        mapping,
                        cross_tangencies=cross_tangencies,
                    )
                    if not canvas.stage_collection_operation(operation):
                        raise ValidationError(canvas.message)
                except (ValidationError, ValueError, StopIteration) as exc:
                    if action in {"二维倒角", "直线圆角"}:
                        canvas.finish_fillet_candidate(success=False)
                    if action == "偏移删除源":
                        canvas.finish_collection_offset(success=False)
                    canvas.message = f"{action}未应用：{exc}"
                    editor.status_label.setText(canvas.message)
                    return
                if action in {"二维倒角", "直线圆角"}:
                    canvas.finish_fillet_candidate(success=True)
                if action == "偏移删除源":
                    canvas.finish_collection_offset(success=True)
                canvas.message = (
                    f"{action}完成；组成员已更新，可撤销。"
                    if changed_refs
                    else f"{action}完成，可撤销。"
                )
                editor.status_label.setText(canvas.message)
                return
        if canvas.entities or raw_draft or previous is not None:
            original_draft = (
                previous.original_draft
                if previous
                else Sketch(
                    editor.draft_sketch_id,
                    editor.current_frame(),
                    tuple(canvas.entities),
                    constraints=tuple(canvas.constraints),
                    layers=canvas.layer_table,
                )
            )
            original_saved = previous.original_saved if previous else services.kernel.sketches
            proposed = MixedMoveState(
                previous.transaction_id if previous else uuid4().hex,
                previous.source_revision if previous else loaded.document.revision,
                original_draft,
                tuple(original_saved),
                tuple(current),
                previous.base_background if previous else canvas.background_entities,
                cast("tuple[tuple[SketchEntity, SketchLayer], ...]", raw_background),
                previous.original_cross_tangencies
                if previous
                else tuple(canvas.pending_cross_tangencies),
                previous.original_associative_arrays
                if previous
                else tuple(canvas.pending_associative_arrays),
            )
            draft = replace(
                original_draft,
                entities=cast("tuple[SketchEntity, ...]", raw_draft),
                constraints=cast("tuple[SketchConstraint, ...]", raw_constraints),
                layers=canvas.layer_table,
            )
            self._preview_mixed_drawing_change(editor, session_id, proposed, draft)
            return
        revisions: list[dict[str, object]] = []
        includes_points = False
        for before, after in zip(original, current, strict=True):
            if before == after:
                continue
            frozen = after.to_state_mapping()
            includes_points = includes_points or any(
                isinstance(e, PointEntity) for e in after.entities
            )
            revisions.append(
                {
                    "sketch_id": before.sketch_id,
                    "base_state_sha256": before.local_state_digest(),
                    "entities": frozen["entities"],
                    "constraints": frozen["constraints"],
                }
            )
        if not revisions:
            editor.status_label.setText("拖动修剪未改变图元。")
            return
        self._submit_drawing_revisions(
            editor,
            session_id,
            revisions,
            includes_points,
            action,
        )

    def _submit_drawing_revisions(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        revisions: list[dict[str, object]],
        includes_points: bool,
        action: str,
        removed_relations: tuple[str, ...] = (),
        erased_members: tuple[ArrayEntityRef, ...] = (),
        raster_remove_ids: tuple[str, ...] = (),
        raster_updates: tuple[DrawingRaster, ...] = (),
        raster_additions: tuple[DrawingRaster, ...] = (),
        draft_candidate: tuple[SketchEntity, ...] | None = None,
        draft_pending_arrays: tuple[AssociativeRectArray, ...] | None = None,
        draft_constraint_candidate: tuple[SketchConstraint, ...] | None = None,
        dimension_layer_updates: bool = False,
        draft_remove_constraint_ids: frozenset[str] = frozenset(),
        preserve_pending_tangencies: bool = False,
        copy_omitted_constraints: bool = False,
        copy_omitted_array: bool = False,
        text_batch: dict[str, object] | None = None,
        annotation_appends: tuple[ReplayAppend, ...] = (),
        extra_appends: tuple[ReplayAppend, ...] = (),
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        source_revision = loaded.document.revision
        annotations_first = bool(extra_appends) or action == "删除"
        has_curves = mycad_app.revisions_include_curved_polylines(revisions)
        has_local_endpoints = mycad_app.revisions_include_local_endpoint_constraints(revisions)
        has_projection_axes = mycad_app.revisions_include_projection_axes(revisions)
        has_dimension_text = mycad_app.revisions_include_dimension_text(revisions)
        has_dimension_styles = mycad_app.revisions_include_dimension_styles(revisions)
        has_dimension_tolerances = mycad_app.revisions_include_dimension_tolerances(revisions)
        draft_before = editor.canvas.history_position
        draft_entities_before = tuple(editor.canvas.entities)
        draft_constraints_before = tuple(editor.canvas.constraints)
        draft_tangencies_before = tuple(editor.canvas.pending_cross_tangencies)
        draft_arrays_before = tuple(editor.canvas.pending_associative_arrays)
        checkpoint = loaded.bus.create_save_checkpoint() if draft_candidate is not None else None
        committed_revision: int | None = None
        editor.setEnabled(False)

        def update() -> object:
            nonlocal committed_revision
            if extra_appends and loaded.document.revision != source_revision:
                raise ValueError("文档已变化，请重新选择后删除。")
            text_appends = (
                (ReplayAppend("drawing.text.batch", 1, text_batch, "local"),)
                if text_batch is not None
                else ()
            )
            if not revisions and (
                raster_updates
                or raster_additions
                or raster_remove_ids
                or text_batch is not None
                or annotation_appends
                or extra_appends
            ):
                candidate = mycad_app.create_replay_candidate(
                    services, loaded, session_identity=session_id
                )
                candidate.stage(
                    ReplayChangeSet(
                        (),
                        (
                            *(annotation_appends if annotations_first else ()),
                            *extra_appends,
                            *(
                                (
                                    ReplayAppend(
                                        "drawing.raster.batch",
                                        2,
                                        {"action": "remove", "image_ids": list(raster_remove_ids)}
                                        if raster_remove_ids
                                        else {
                                            "action": "add" if raster_additions else "update",
                                            "images": [
                                                image.to_mapping(version=2)
                                                for image in (raster_additions or raster_updates)
                                            ],
                                        },
                                        "local",
                                    ),
                                )
                                if raster_remove_ids or raster_additions or raster_updates
                                else ()
                            ),
                            *text_appends,
                            *(annotation_appends if not annotations_first else ()),
                        ),
                        False,
                        8 if loaded.document.archive_version < 8 else None,
                    ),
                    current_session_identity=session_id,
                )
                preview = candidate.preview(current_session_identity=session_id)
                if preview.state != "succeeded":
                    raise ValueError(str(preview.failure or "图片修订预览失败"))
                committed = candidate.commit(
                    candidate.authorize_commit(current_session_identity=session_id),
                    current_session_identity=session_id,
                )
                committed_revision = loaded.document.revision
                return committed
            original = services.kernel.sketches
            revisions_by_id = {revision["sketch_id"]: revision for revision in revisions}
            updated: list[Sketch] = []
            for sketch in original:
                revision = revisions_by_id.get(sketch.sketch_id)
                if revision is None:
                    updated.append(sketch)
                    continue
                state = sketch.to_state_mapping()
                state["entities"] = revision["entities"]
                state["constraints"] = revision["constraints"]
                updated.append(Sketch.from_mapping(state))
            topology_maps, base_rebind, array_proof_version = (
                mycad_app.exact_attached_polyline_reorder_maps(services, original, updated)
                if not (
                    removed_relations
                    or erased_members
                    or raster_remove_ids
                    or raster_updates
                    or raster_additions
                    or dimension_layer_updates
                    or draft_candidate is not None
                    or text_batch is not None
                    or annotation_appends
                )
                else ((), False, 0)
            )
            existing = tuple(
                relation
                for relation in services.kernel.cross_sketch_tangencies
                if relation.relation_id not in removed_relations
            )
            special_relations = ()
            if array_proof_version >= 79:
                from mycad.core.geometric_tolerance_topology import (
                    PolylineTopologyMap,
                    rebind_proven_array_tangencies,
                )

                mapped = {
                    (cast("str", item["sketch_id"]), mapping.entity_id): mapping
                    for item in topology_maps
                    for mapping in (PolylineTopologyMap.from_mapping(item["mapping"]),)
                }
                members = {
                    (ref.sketch_id, ref.entity_id)
                    for array in services.kernel.associative_arrays
                    for ref in (
                        *(member.target for member in array.members),
                        *(output.target for output in array.extra_outputs),
                    )
                }
                special_relations = tuple(
                    relation
                    for relation in existing
                    if any(
                        (ref.sketch_id, ref.entity_id) in mapped
                        for ref in (relation.first, relation.second)
                    )
                    and any(
                        (ref.sketch_id, ref.entity_id) in members
                        for ref in (relation.first, relation.second)
                    )
                )
                special_rebound = rebind_proven_array_tangencies(
                    original,
                    tuple(updated),
                    special_relations,
                    mapped,
                    allow_reversed_segments=True,
                )
                special_by_id = {item.relation_id: item for item in special_rebound}
            else:
                special_by_id = {}
            ordinary = tuple(item for item in existing if item.relation_id not in special_by_id)
            ordinary_rebound, rebind_version = rebind_committed_tangencies_for_edit(
                original, tuple(updated), ordinary
            )
            rebound_by_id = {
                item.relation_id: item for item in (*ordinary_rebound, *special_by_id.values())
            }
            rebound = tuple(rebound_by_id[item.relation_id] for item in existing)
            replacements = tuple(
                after for before, after in zip(existing, rebound, strict=True) if before != after
            )
            removals = (*removed_relations, *(relation.relation_id for relation in replacements))
            updated_by_id = {sketch.sketch_id: sketch for sketch in updated}
            has_inferred_rebind = any(
                before.source == "inferred"
                and before.constraint_id == after.constraint_id
                and before.references != after.references
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            original_circles = {
                (sketch.sketch_id, entity.entity_id)
                for sketch in original
                for entity in sketch.entities
                if isinstance(entity, CircleEntity)
            }
            has_trimmed_circle = any(
                isinstance(entity, ArcEntity)
                and (sketch.sketch_id, entity.entity_id) in original_circles
                for sketch in updated
                for entity in sketch.entities
            )
            has_local_tangent_rebind = action in {"修剪", "拖动修剪", "单点打断"} and any(
                before.kind == "tangent"
                and before.source == "user"
                and before.constraint_id == after.constraint_id
                and before.references != after.references
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            has_local_fragment_rebind = has_local_tangent_rebind and any(
                before.kind == "tangent"
                and before.source == "user"
                and before.constraint_id == after.constraint_id
                and any(
                    a.entity_id != b.entity_id
                    for a, b in zip(before.references, after.references, strict=True)
                )
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            has_local_split_line_rebind = has_local_tangent_rebind and any(
                before.kind == "tangent"
                and before.source == "user"
                and before.constraint_id == after.constraint_id
                and any(
                    a.entity_id != b.entity_id
                    and any(
                        isinstance(entity, LineEntity) and entity.entity_id == a.entity_id
                        for entity in sketch.entities
                    )
                    for a, b in zip(before.references, after.references, strict=True)
                )
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            has_local_split_arc_rebind = has_local_tangent_rebind and any(
                before.kind == "tangent"
                and before.source == "user"
                and before.constraint_id == after.constraint_id
                and any(
                    a.entity_id != b.entity_id
                    and any(
                        isinstance(entity, ArcEntity) and entity.entity_id == a.entity_id
                        for entity in sketch.entities
                    )
                    for a, b in zip(before.references, after.references, strict=True)
                )
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            has_curve_point_ids = any(
                isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids
                for sketch in updated
                if sketch.sketch_id in revisions_by_id
                for entity in sketch.entities
            )
            batch = (
                dimension_layer_updates
                or bool(raster_remove_ids or raster_updates or raster_additions)
                or has_trimmed_circle
                or has_local_tangent_rebind
                or bool(rebind_version)
                or len(revisions) > 1
                or bool(removals)
                or bool(replacements)
                or bool(erased_members)
                or has_inferred_rebind
                or bool(topology_maps)
                or has_curve_point_ids
                or bool(extra_appends)
            )
            preserve_normal_side = mycad_app.revisions_require_normal_side_preservation(
                services, revisions
            )
            batch = batch or preserve_normal_side
            params: dict[str, object] = {"revisions": revisions} if batch else dict(revisions[0])
            if topology_maps:
                params["polyline_topology_maps"] = list(topology_maps)
            if raster_remove_ids:
                params["raster_batch"] = {"action": "remove", "image_ids": list(raster_remove_ids)}
            elif raster_updates:
                params["raster_batch"] = {
                    "action": "update",
                    "images": [image.to_mapping(version=2) for image in raster_updates],
                }
            elif raster_additions:
                params["raster_batch"] = {
                    "action": "add",
                    "images": [image.to_mapping(version=2) for image in raster_additions],
                }
            if removals:
                params["remove_tangencies"] = list(removals)
            if replacements:
                params["cross_tangencies"] = [relation.to_mapping() for relation in replacements]
            if erased_members:
                params["erase_array_members"] = [ref.to_mapping() for ref in erased_members]
            erased_set = set(erased_members)
            has_user_rebind = any(
                before.source == "user"
                and before.constraint_id == after.constraint_id
                and before.references != after.references
                for sketch in original
                for before in sketch.constraints
                for after in updated_by_id[sketch.sketch_id].constraints
            )
            removes_member_dimension = any(
                constraint.kind in DIMENSION_KINDS
                and constraint.constraint_id
                not in {item.constraint_id for item in updated_by_id[sketch.sketch_id].constraints}
                and any(
                    ArrayEntityRef(sketch.sketch_id, ref.entity_id) in erased_set
                    for ref in constraint.references
                )
                for sketch in original
                for constraint in sketch.constraints
            )
            version = (
                max(64, array_proof_version)
                if has_curve_point_ids
                else 63
                if raster_remove_ids or raster_updates or raster_additions
                else array_proof_version
                if array_proof_version
                else 58
                if base_rebind
                else 57
                if topology_maps
                else 56
                if preserve_normal_side
                else (53 if batch else 9)
                if has_dimension_tolerances
                else 52
                if dimension_layer_updates
                else 51
                if has_dimension_styles
                and (raster_remove_ids or raster_updates or raster_additions)
                else (50 if batch else 8)
                if has_dimension_styles
                else 49
                if has_dimension_text and (raster_remove_ids or raster_updates or raster_additions)
                else (48 if batch else 7)
                if has_dimension_text
                else 47
                if raster_remove_ids or raster_updates or raster_additions
                else max(46, rebind_version)
                if has_local_split_arc_rebind
                else max(45, rebind_version)
                if has_local_split_line_rebind
                else max(42, rebind_version)
                if has_local_fragment_rebind
                else max(41, rebind_version)
                if has_local_tangent_rebind
                else max(39, rebind_version)
                if has_trimmed_circle
                else rebind_version
                if rebind_version
                else (32 if batch else 6)
                if has_user_rebind or has_inferred_rebind
                else (31 if batch else 5)
                if has_projection_axes
                else 26
                if removes_member_dimension
                else 23
                if any(
                    output.target in erased_members
                    for array in services.kernel.associative_arrays
                    for output in array.extra_outputs
                )
                else 20
                if erased_members
                else 8
                if has_local_endpoints and batch
                else 4
                if has_local_endpoints
                else 7
                if any(
                    relation.first_endpoint or relation.second_endpoint for relation in replacements
                )
                else 5
                if replacements
                else 3
                if has_curves
                else 2
                if removals
                else 1
                if batch
                else 2
                if includes_points
                else 1
            )
            candidate = mycad_app.create_replay_candidate(
                services, loaded, session_identity=session_id
            )
            candidate.stage(
                ReplayChangeSet(
                    (),
                    (
                        *(annotation_appends if annotations_first else ()),
                        ReplayAppend(
                            "drawing.sketch.revise" if batch else "sketch.revise",
                            version,
                            params,
                            "local",
                        ),
                        *extra_appends,
                        *text_appends,
                        *(annotation_appends if not annotations_first else ()),
                    ),
                    False,
                    8
                    if (
                        dimension_layer_updates
                        or raster_remove_ids
                        or raster_updates
                        or raster_additions
                        or version >= 64
                        or extra_appends
                    )
                    and loaded.document.archive_version < 8
                    else 6
                    if loaded.document.archive_version < 6
                    else None,
                ),
                current_session_identity=session_id,
            )
            preview = candidate.preview(current_session_identity=session_id)
            if preview.state != "succeeded":
                if (
                    preview.failure is not None
                    and preview.failure.reason == "revised geometry violates existing constraints"
                ):
                    raise ValueError("修改与现有尺寸或约束冲突；图形保持原状。")
                raise ValueError(str(preview.failure or "草图修订预览失败"))
            committed = candidate.commit(
                candidate.authorize_commit(current_session_identity=session_id),
                current_session_identity=session_id,
            )
            committed_revision = loaded.document.revision
            return committed

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if self._loaded is not loaded or self._session_id != session_id:
                if checkpoint is not None:
                    loaded.bus.release_save_checkpoint(checkpoint)
                return
            if checkpoint is not None:
                if result.error is not None:
                    if loaded.document.revision == source_revision:
                        loaded.bus.restore_save_checkpoint(
                            checkpoint, expected_revision=source_revision
                        )
                    else:
                        loaded.bus.release_save_checkpoint(checkpoint)
                else:
                    previous_layer_redo = list(editor.layer_history_redo)
                    try:
                        if preserve_pending_tangencies:
                            self._sync_drawing_layers()
                        draft_unchanged = (
                            editor.canvas.history_position == draft_before
                            and tuple(editor.canvas.entities) == draft_entities_before
                            and tuple(editor.canvas.constraints) == draft_constraints_before
                            and tuple(editor.canvas.pending_cross_tangencies)
                            == draft_tangencies_before
                            and tuple(editor.canvas.pending_associative_arrays)
                            == draft_arrays_before
                            and draft_candidate is not None
                        )
                        if draft_unchanged and draft_constraint_candidate is not None:
                            original_draft = editor.dimension_sources()[0]
                            draft_applied = editor.canvas.apply_constraint_solution(
                                original_draft,
                                replace(
                                    original_draft,
                                    entities=draft_candidate,
                                    constraints=draft_constraint_candidate,
                                ),
                            )
                        else:
                            draft_applied = bool(
                                draft_unchanged
                                and draft_candidate is not None
                                and editor.canvas.replace_draft_entities_atomically(
                                    draft_candidate,
                                    remove_dependent_constraints=action == "删除",
                                    remove_constraint_ids=draft_remove_constraint_ids,
                                    preserve_pending_tangencies=preserve_pending_tangencies,
                                    pending_arrays=draft_pending_arrays,
                                )
                            )
                    except Exception as exc:
                        draft_applied = False
                        editor.canvas.message = f"草稿更新失败：{exc}"
                    if not draft_applied:
                        editor.layer_history_redo[:] = previous_layer_redo
                        assert committed_revision is not None
                        loaded.bus.restore_save_checkpoint(
                            checkpoint, expected_revision=committed_revision
                        )
                        if action == "复制":
                            editor.canvas.cancel_transform()
                        self._sync_drawing_layers()
                        editor.status_label.setText(f"草稿已变化或无法修改；本次{action}已回滚。")
                        return
                    loaded.bus.release_save_checkpoint(checkpoint)
                    count = loaded.document.command_count
                    editor.mixed_draft_history[count] = (
                        draft_before,
                        editor.canvas.history_position,
                        loaded.document.commands[-1].instance_id,
                    )
            self._sync_drawing_layers()
            if result.error is not None:
                if action == "复制" and raster_additions:
                    editor.canvas.finish_mixed_copy_commit(None, loaded.document.revision)
                if action in {"直线圆角", "二维倒角"}:
                    editor.canvas.finish_fillet_candidate(success=False)
                message = f"{action}失败：{result.error}"
                if action == "单点打断":
                    editor.canvas.message = message
                    editor.drawing_command_bar.status.setText(message)
                editor.status_label.setText(message)
                return
            if action == "复制" and raster_additions:
                identity = (
                    loaded.document.commands[-1].instance_id if loaded.document.commands else None
                )
                editor.canvas.finish_mixed_copy_commit(
                    identity, loaded.document.revision, includes_draft=draft_candidate is not None
                )
            if raster_remove_ids:
                editor.canvas.selected_raster_ids.difference_update(raster_remove_ids)
            if action in {"直线圆角", "二维倒角"}:
                editor.canvas.finish_fillet_candidate(success=True)
            if action in {"修剪", "延伸", "拖动修剪", "围栏延伸"}:
                editor.canvas.acknowledge_line_edit_revision(
                    source_revision, loaded.document.revision
                )
            if (
                (
                    action in {"修剪", "延伸", "拖动修剪", "围栏延伸", "二维倒角", "直线圆角"}
                    or (action == "删除" and editor.canvas.tool == "修剪")
                )
                and loaded.document.commands
                and loaded.document.commands[-1].instance_id
            ):
                editor.canvas.record_saved_line_edit(
                    loaded.document.commands[-1].instance_id, loaded.document.revision
                )
            editor.layer_history_boundaries[len(loaded.document.commands)] = (
                editor.canvas.history_position
            )
            editor.layer_history_redo.clear()
            editor.canvas.discard_redo_history()
            message = f"已{action}所选对象；可撤销。"
            if copy_omitted_constraints:
                message += "副本未继承原对象的约束关系。"
            if copy_omitted_array:
                message += "副本未继承原对象的阵列关联。"
            if action == "单点打断":
                editor.canvas.message = message
                editor.drawing_command_bar.status.setText(message)
            editor.status_label.setText(message)

        if not unit.submit(
            update, operation="drawing-move", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            if checkpoint is not None:
                loaded.bus.release_save_checkpoint(checkpoint)
            if action in {"直线圆角", "二维倒角"}:
                editor.canvas.finish_fillet_candidate(success=False)
            message = f"几何工作线程忙碌，{action}未应用。"
            if action == "单点打断":
                editor.canvas.message = message
                editor.drawing_command_bar.status.setText(message)
            editor.status_label.setText(message)

    def _stage_drawing_mixed_move(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        selected: tuple[str, ...],
        displacement: tuple[float, float],
        *,
        angle: float | None = None,
        scale: float | None = None,
        mirror_end: tuple[float, float] | None = None,
        erase: bool = False,
        raster_updates: tuple[DrawingRaster, ...] = (),
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
        if erase and any(
            any(ref.entity_id in selected for ref in constraint.references)
            and (
                canvas.annotation_layer(constraint).locked
                or not canvas.annotation_layer(constraint).displayed
            )
            for constraint in (
                *canvas.constraints,
                *(c for sketch in current_saved for c in sketch.constraints),
            )
        ):
            editor.status_label.setText("相关约束位于已锁定或隐藏图层；图元未修改。")
            return
        pending_arrays: tuple[AssociativeRectArray, ...] | None = None
        draft_entities = tuple(canvas.entities)
        if draft_ids:
            if erase:
                if canvas.pending_associative_arrays:
                    try:
                        prior_draft = replace(
                            original_draft,
                            entities=draft_entities,
                            constraints=tuple(canvas.constraints),
                            layers=canvas.layer_table,
                        )
                        states, arrays = erase_drawing_entities(
                            (prior_draft, *current_saved),
                            tuple(canvas.pending_associative_arrays),
                            tuple(
                                ArrayEntityRef(prior_draft.sketch_id, item) for item in draft_ids
                            ),
                        )
                        pending_ids = {
                            array.array_id for array in canvas.pending_associative_arrays
                        }
                        pending_arrays = tuple(
                            array for array in arrays if array.array_id in pending_ids
                        )
                        draft_entities = states[0].entities
                    except (KeyError, ValueError) as exc:
                        editor.status_label.setText(f"混合删除失败：{exc}")
                        return
                else:
                    draft_entities = tuple(
                        entity for entity in draft_entities if entity.entity_id not in draft_ids
                    )
            elif mirror_end is not None:
                draft_entities = mirror_entities(
                    draft_entities, draft_ids, displacement, mirror_end
                )
            elif angle is not None:
                draft_entities = rotate_entities(draft_entities, draft_ids, displacement, angle)
            elif scale is not None:
                draft_entities = scale_entities(draft_entities, draft_ids, displacement, scale)
            else:
                draft_entities = move_entities(
                    draft_entities, draft_ids, displacement, preserve_rectangle_order=True
                )
        revised_saved: list[Sketch] = []
        for sketch in current_saved:
            ids = tuple(
                entity.entity_id for entity in sketch.entities if entity.entity_id in saved_ids
            )
            if ids and not erase:
                try:
                    project_coplanar_vector((0.0, 0.0), editor.current_frame(), sketch.frame)
                except ValueError:
                    editor.status_label.setText("所选对象不在当前工作平面；图元未修改。")
                    return
            if ids and erase:
                changed = tuple(entity for entity in sketch.entities if entity.entity_id not in ids)
            elif ids and mirror_end is not None:
                start = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                end = sketch.frame.world_to_local(editor.current_frame().local_to_world(mirror_end))
                changed = mirror_entities(sketch.entities, ids, start, end)
            elif ids and angle is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                local_angle = project_coplanar_rotation(angle, editor.current_frame(), sketch.frame)
                changed = rotate_entities(sketch.entities, ids, center, local_angle)
            elif ids and scale is not None:
                center = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                changed = scale_entities(sketch.entities, ids, center, scale)
            elif ids:
                changed = move_entities(
                    sketch.entities,
                    ids,
                    project_coplanar_vector(displacement, editor.current_frame(), sketch.frame),
                    preserve_rectangle_order=True,
                )
            else:
                changed = sketch.entities
            constraints = tuple(
                constraint
                for constraint in sketch.constraints
                if not erase or all(ref.entity_id not in ids for ref in constraint.references)
            )
            revised_saved.append(replace(sketch, entities=changed, constraints=constraints))
        if scale is not None and canvas.pending_associative_arrays:
            prior_draft = replace(
                original_draft,
                entities=tuple(canvas.entities),
                constraints=tuple(canvas.constraints),
                layers=canvas.layer_table,
            )
            proposed_draft = replace(prior_draft, entities=draft_entities)
            try:
                propagated = propagate_array_changes(
                    (prior_draft, *current_saved),
                    (proposed_draft, *revised_saved),
                    tuple(canvas.pending_associative_arrays),
                )
                if propagated[1:] != tuple(revised_saved):
                    raise ValueError("请先完成草图，再修改关联的已保存对象。")
                draft_entities = propagated[0].entities
            except (KeyError, ValueError) as exc:
                editor.status_label.setText(f"关联阵列缩放失败：{exc}")
                return
        if tuple(revised_saved) == tuple(current_saved):
            if draft_entities == tuple(canvas.entities):
                editor.status_label.setText("变换未改变图元。")
                return
            if not any(
                draft_tangent_reference(target).entity_id in draft_ids
                for _source, target in canvas.pending_cross_tangencies
            ):
                canvas.replace_draft_entities(draft_entities)
                return
        background = canvas.background_entities
        overlay_source = tuple(entity for entity, _layer in background)
        if erase:
            overlay = tuple(
                entity for entity in overlay_source if entity.entity_id not in saved_ids
            )
        elif mirror_end is not None:
            overlay = mirror_entities(overlay_source, tuple(saved_ids), displacement, mirror_end)
        elif angle is not None:
            overlay = rotate_entities(overlay_source, tuple(saved_ids), displacement, angle)
        elif scale is not None:
            overlay = scale_entities(overlay_source, tuple(saved_ids), displacement, scale)
        else:
            overlay = move_entities(
                overlay_source, tuple(saved_ids), displacement, preserve_rectangle_order=True
            )
        rectangle_transforms: list[RectangleTransformEvidence] = []
        if angle is not None or mirror_end is not None:
            committed_related = {
                (ref.sketch_id, ref.entity_id)
                for relation in services.kernel.cross_sketch_tangencies
                for ref in (relation.first, relation.second)
            }
            related = {
                (ref.sketch_id, ref.entity_id)
                for relation in services.kernel.cross_sketch_tangencies
                for ref in (relation.first, relation.second)
                if ref.segment_index is not None
            }
            related.update(
                (sketch.sketch_id, entity.entity_id)
                for sketch in current_saved
                for entity in sketch.entities
                if any(
                    draft_tangent_reference(source).entity_id == entity.entity_id
                    and draft_tangent_reference(source).kind == "segment"
                    for source, _target in canvas.pending_cross_tangencies
                )
            )
            draft_source = replace(
                original_draft,
                entities=tuple(canvas.entities),
                constraints=tuple(canvas.constraints),
                layers=canvas.layer_table,
            )
            committed_related.update(
                (sketch.sketch_id, entity.entity_id)
                for sketch in current_saved
                for entity in sketch.entities
                if any(
                    draft_tangent_reference(source).entity_id == entity.entity_id
                    for source, _target in canvas.pending_cross_tangencies
                )
            )
            committed_related.update(
                (draft_source.sketch_id, draft_tangent_reference(target).entity_id)
                for _source, target in canvas.pending_cross_tangencies
            )
            related.update(
                (draft_source.sketch_id, reference.entity_id)
                for constraint in draft_source.constraints
                for reference in constraint.references
            )
            for sketch in (*current_saved, draft_source):
                targets = tuple(
                    entity
                    for entity in sketch.entities
                    if (
                        isinstance(entity, RectangleEntity)
                        and (sketch.sketch_id, entity.entity_id) in related
                        or isinstance(entity, PolylineEntity | LineEntity)
                        and (sketch.sketch_id, entity.entity_id) in committed_related
                    )
                    and entity.entity_id in selected
                )
                if not targets:
                    continue
                start = sketch.frame.world_to_local(
                    editor.current_frame().local_to_world(displacement)
                )
                if mirror_end is not None:
                    end = sketch.frame.world_to_local(
                        editor.current_frame().local_to_world(mirror_end)
                    )
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    length = hypot(dx, dy)
                    if length <= 1e-12:
                        editor.status_label.setText("镜像轴必须有非零长度。")
                        return
                    ux, uy = dx / length, dy / length
                    a, b, c, d = 2 * ux * ux - 1, 2 * ux * uy, 2 * ux * uy, 2 * uy * uy - 1
                else:
                    assert angle is not None
                    local_angle = project_coplanar_rotation(
                        angle, editor.current_frame(), sketch.frame
                    )
                    a, b, c, d = (
                        cos(radians(local_angle)),
                        -sin(radians(local_angle)),
                        sin(radians(local_angle)),
                        cos(radians(local_angle)),
                    )
                matrix = (
                    a,
                    b,
                    c,
                    d,
                    start[0] - a * start[0] - b * start[1],
                    start[1] - c * start[0] - d * start[1],
                )
                rectangle_transforms.extend(
                    RectangleTransformEvidence(
                        CrossSketchRef(sketch.sketch_id, entity.entity_id), matrix
                    )
                    for entity in targets
                )
        proposed = MixedMoveState(
            previous.transaction_id if previous else uuid4().hex,
            previous.source_revision if previous else loaded.document.revision,
            original_draft,
            tuple(original_saved),
            tuple(revised_saved),
            previous.base_background if previous else background,
            tuple(
                (entity, layer)
                for entity, (_old, layer) in zip(
                    overlay,
                    (
                        item
                        for item in background
                        if not erase or item[0].entity_id not in saved_ids
                    ),
                    strict=True,
                )
            ),
            previous.original_cross_tangencies
            if previous
            else tuple(canvas.pending_cross_tangencies),
            previous.original_associative_arrays
            if previous
            else tuple(canvas.pending_associative_arrays),
            tuple(rectangle_transforms),
        )
        draft = replace(
            original_draft,
            entities=draft_entities,
            constraints=tuple(
                constraint
                for constraint in canvas.constraints
                if not erase or all(ref.entity_id not in draft_ids for ref in constraint.references)
            ),
            layers=canvas.layer_table,
        )
        prior_draft = replace(
            original_draft,
            entities=tuple(canvas.entities),
            constraints=tuple(canvas.constraints),
            layers=canvas.layer_table,
        )
        anchors = tuple(
            CrossSketchRef(sketch.sketch_id, entity.entity_id)
            for sketch in (*current_saved, prior_draft)
            for entity in sketch.entities
            if entity.entity_id in selected
        )
        self._preview_mixed_drawing_change(
            editor,
            session_id,
            proposed,
            draft,
            erase=erase,
            solve_base=(tuple(current_saved), prior_draft, anchors) if not erase else None,
            pending_arrays=pending_arrays,
            raster_updates=raster_updates,
        )

    def _preview_mixed_drawing_change(
        self,
        editor: SketchEditorDialog,
        session_id: int,
        proposed: MixedMoveState,
        draft: Sketch,
        *,
        action: str = "",
        erase: bool = False,
        solve_base: tuple[tuple[Sketch, ...], Sketch, tuple[CrossSketchRef, ...]] | None = None,
        pending_arrays: tuple[AssociativeRectArray, ...] | None = None,
        raster_updates: tuple[DrawingRaster, ...] = (),
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        canvas = editor.canvas

        def report_failure(message: str) -> None:
            if action == "单点打断":
                canvas.message = message
                canvas.changed.emit()
            editor.status_label.setText(message)

        history = canvas.mixed_move_timeline_with_transforms()
        steps = tuple(
            (saved, old_draft) for saved, old_draft, _pairs, _arrays, _transforms in history
        ) + ((proposed.current_saved, draft),)
        surviving_sources = {
            entity.entity_id for sketch in proposed.current_saved for entity in sketch.entities
        }
        surviving_targets = {entity.entity_id for entity in draft.entities}
        current_pairs = tuple(
            (source, target)
            for source, target in canvas.pending_cross_tangencies
            if draft_tangent_reference(source).entity_id in surviving_sources
            and draft_tangent_reference(target).entity_id in surviving_targets
        )
        previous_saved = (
            canvas.mixed_move.current_saved
            if canvas.mixed_move is not None
            else proposed.original_saved
        )
        old_pairs: list[DraftTangentPair] = []
        rebound_pairs: list[DraftTangentPair] = []
        try:
            rectangle_proofs, _polyline_proofs, _line_proofs = split_transform_evidence(
                (
                    *previous_saved,
                    replace(proposed.original_draft, entities=tuple(canvas.entities)),
                ),
                proposed.step_rectangle_transforms,
            )
        except ValueError as exc:
            report_failure(f"暂存变换依据无效：{exc}")
            return
        for pair in current_pairs:
            try:
                mapped = rebind_pending_saved_sources(
                    previous_saved,
                    proposed.current_saved,
                    (pair,),
                    rectangle_proofs,
                    previous_draft=replace(
                        proposed.original_draft,
                        entities=tuple(canvas.entities),
                        constraints=tuple(canvas.constraints),
                        layers=canvas.layer_table,
                    ),
                    updated_draft=draft,
                )
            except ValueError as exc:
                report_failure(f"暂存相切关系无法重绑定：{exc}")
                return
            if mapped:
                old_pairs.append(pair)
                rebound_pairs.append(mapped[0])
        current_pairs = tuple(rebound_pairs)
        solve_pairs = tuple(old_pairs)
        pairs_by_step = tuple(pairs for _saved, _draft, pairs, _arrays, _transforms in history) + (
            current_pairs,
        )
        arrays_by_step = tuple(
            arrays for _saved, _draft, _pairs, arrays, _transforms in history
        ) + (
            pending_arrays
            if pending_arrays is not None
            else tuple(canvas.pending_associative_arrays),
        )
        layers = {entity.entity_id: layer for entity, layer in canvas.background_entities}
        relations = services.kernel.cross_sketch_tangencies
        try:
            relations = _staged_committed_tangencies(
                proposed.original_saved,
                relations,
                tuple(
                    (saved, transforms) for saved, _draft, _pairs, _arrays, transforms in history
                ),
            )
        except ValueError as exc:
            report_failure(f"暂存相切关系失效：{exc}")
            return
        editor.setEnabled(False)

        def preview() -> object:
            solved_proposed, solved_draft = proposed, draft
            if solve_base is not None and (current_pairs or relations):
                previous_saved, previous_draft, anchors = solve_base
                saved, solved_draft = mycad_app.solve_mixed_draft_tangencies(
                    previous_saved,
                    previous_draft,
                    proposed.current_saved,
                    draft,
                    solve_pairs,
                    relations,
                    anchors,
                    proposed_pairs=current_pairs,
                    rectangle_transforms=proposed.step_rectangle_transforms,
                )
                previous_entities = {
                    entity.entity_id: entity
                    for sketch in (*previous_saved, previous_draft)
                    for entity in sketch.entities
                }
                if len(previous_entities) != sum(
                    len(sketch.entities) for sketch in (*previous_saved, previous_draft)
                ):
                    raise ValueError("图元标识重复，无法安全联动编辑。")
                projected: dict[str, SketchEntity] = {}
                overlay_ids = {entity.entity_id for entity, _layer in proposed.overlay_background}
                for sketch in saved:
                    for entity in sketch.entities:
                        if entity != previous_entities.get(entity.entity_id):
                            layer = layers.get(entity.entity_id)
                            if layer is None or layer.locked or not layer.displayed:
                                raise ValueError("关联图元位于锁定或隐藏图层。")
                        if entity.entity_id in overlay_ids:
                            projected[entity.entity_id] = project_coplanar_entity(
                                entity, sketch.frame, draft.frame
                            )
                for entity in solved_draft.entities:
                    if entity != previous_entities.get(entity.entity_id):
                        layer = solved_draft.layers.get(entity.layer_name)
                        if layer.locked or not layer.displayed:
                            raise ValueError("关联图元位于锁定或隐藏图层。")
                solved_proposed = replace(
                    proposed,
                    current_saved=saved,
                    overlay_background=tuple(
                        (projected.get(entity.entity_id, entity), layer)
                        for entity, layer in proposed.overlay_background
                    ),
                )
            solved_steps = (*steps[:-1], (solved_proposed.current_saved, solved_draft))
            candidate = mycad_app.stage_mixed_drawing_timeline(
                services,
                loaded,
                proposed.original_draft,
                proposed.original_saved,
                solved_steps,
                session_identity=session_id,
                cross_pairs_by_step=pairs_by_step,
                arrays_by_step=arrays_by_step,
                initial_cross_pairs=proposed.original_cross_tangencies,
                initial_associative_arrays=proposed.original_associative_arrays,
                rectangle_transforms_by_step=(
                    *(transforms for _saved, _draft, _pairs, _arrays, transforms in history),
                    proposed.step_rectangle_transforms,
                ),
            )
            result = candidate.preview(current_session_identity=session_id)
            candidate.cancel()
            if result.state != "succeeded":
                raise ValueError(str(result.failure or "混合变换预览失败"))
            return solved_proposed, solved_draft

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._sketch_dialog is not editor
            ):
                return
            if result.error is not None:
                canvas.finish_fillet_candidate(success=False)
                report_failure(f"混合变换失败：{result.error}")
                return
            if loaded.document.revision != proposed.source_revision:
                report_failure("文档已变化；混合变换未应用。")
                return
            accepted, accepted_draft = cast("tuple[MixedMoveState, Sketch]", result.value)
            if not raster_updates:
                canvas.apply_mixed_move(
                    accepted,
                    accepted_draft.entities,
                    erase=erase,
                    constraints=accepted_draft.constraints,
                    pending_arrays=pending_arrays,
                    pending_pairs=current_pairs,
                )
                return
            checkpoint = loaded.bus.create_save_checkpoint()
            before = canvas.history_position
            old_revision = loaded.document.revision
            previous_layer_redo = list(editor.layer_history_redo)
            try:
                loaded.bus.execute(
                    "drawing.raster.batch",
                    {
                        "action": "update",
                        "images": [item.to_mapping(version=2) for item in raster_updates],
                    },
                    "local",
                    version=2,
                )
                new_revision = loaded.document.revision
                canvas.rebind_restored_source(old_revision, new_revision)
                canvas.apply_mixed_move_atomically(
                    replace(accepted, source_revision=new_revision),
                    accepted_draft.entities,
                    constraints=accepted_draft.constraints,
                    pending_arrays=pending_arrays,
                    pending_pairs=current_pairs,
                )
            except Exception as exc:
                editor.layer_history_redo[:] = previous_layer_redo
                current_revision = loaded.document.revision
                loaded.bus.restore_save_checkpoint(checkpoint, expected_revision=current_revision)
                canvas.rebind_restored_source(current_revision, loaded.document.revision)
                self._sync_drawing_layers()
                report_failure(f"混合移动失败，已回滚：{exc}")
                return
            loaded.bus.release_save_checkpoint(checkpoint)
            count = loaded.document.command_count
            editor.mixed_draft_history[count] = (
                before,
                canvas.history_position,
                loaded.document.commands[-1].instance_id,
            )
            editor.layer_history_boundaries[count] = canvas.history_position
            editor.layer_history_redo.clear()
            canvas.discard_redo_history()
            self._sync_drawing_layers()

        if not unit.submit(
            preview, operation="drawing-mixed-move", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            canvas.finish_fillet_candidate(success=False)
            report_failure("几何工作线程忙碌，变换未应用。")

    def _on_drawing_assign_construction(
        self, editor: SketchEditorDialog, session_id: int, raw_ids: object, construction: bool
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        if unit.is_busy or unit.is_delivering_result:
            editor.status_label.setText("几何工作线程忙碌，请稍后更改构造几何。")
            return
        if not isinstance(raw_ids, tuple):
            return
        identities = cast("tuple[object, ...]", raw_ids)
        if not all(isinstance(item, str) for item in identities):
            return
        ids = set(cast("tuple[str, ...]", identities))
        canvas = editor.canvas
        if (
            canvas.mixed_move
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
            or canvas.collection_session is not None
        ):
            editor.status_label.setText("请先完成或撤销当前暂存关联编辑，再更改构造几何。")
            return
        if canvas.source_context_revision != loaded.document.revision:
            self._sync_drawing_layers()
            editor.status_label.setText("图纸已变化，请重新选择对象。")
            return
        draft = tuple(entity for entity in canvas.entities if entity.entity_id in ids)
        saved = tuple(
            (sketch, entity)
            for sketch in services.kernel.sketches
            for entity in sketch.entities
            if entity.entity_id in ids
        )
        found = [entity.entity_id for entity in draft] + [entity.entity_id for _, entity in saved]
        if not ids or len(found) != len(ids) or set(found) != ids:
            editor.status_label.setText("所选图元已变化或身份不唯一，请重新选择。")
            return
        try:
            if any(
                (layer := canvas.layer_table.get(entity.layer_name)).locked or not layer.displayed
                for entity in (*draft, *(entity for _, entity in saved))
            ):
                editor.status_label.setText("所选图元位于隐藏、冻结或锁定的图层。")
                return
        except KeyError:
            editor.status_label.setText("所选图元的图层已变化，请重新选择。")
            return
        draft_candidate = tuple(
            replace(entity, construction=construction) if entity.entity_id in ids else entity
            for entity in canvas.entities
        )
        try:
            canvas.validate_draft_constraint_edits(
                draft_candidate, removed_constraint_ids=frozenset()
            )
        except ValueError as exc:
            editor.status_label.setText(str(exc))
            return
        revisions: list[dict[str, object]] = []
        includes_points = False
        for sketch in services.kernel.sketches:
            if not any(entity.entity_id in ids for entity in sketch.entities):
                continue
            revised = replace(
                sketch,
                entities=tuple(
                    replace(entity, construction=construction)
                    if entity.entity_id in ids
                    else entity
                    for entity in sketch.entities
                ),
            )
            if revised == sketch:
                continue
            state = revised.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            )
            includes_points = includes_points or any(
                isinstance(entity, PointEntity) for entity in revised.entities
            )
        if not revisions:
            if draft_candidate == tuple(canvas.entities):
                editor.status_label.setText("所选图元的构造几何状态未改变。")
            elif canvas.replace_draft_entities(draft_candidate):
                editor.status_label.setText("已更改构造几何；可撤销。")
            else:
                editor.status_label.setText(canvas.message)
            return
        self._submit_drawing_revisions(
            editor,
            session_id,
            revisions,
            includes_points,
            "更改构造几何",
            draft_candidate=draft_candidate if draft_candidate != tuple(canvas.entities) else None,
        )

    def _on_drawing_assign_layer(
        self, editor: SketchEditorDialog, session_id: int, raw_ids: object, layer_name: str
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            return
        if unit.is_busy or unit.is_delivering_result:
            editor.status_label.setText("几何工作线程忙碌，请稍后更改图层。")
            return
        if not isinstance(raw_ids, tuple):
            return
        identities = cast("tuple[object, ...]", raw_ids)
        if not all(isinstance(item, str) for item in identities):
            return
        ids = set(cast("tuple[str, ...]", identities))
        canvas = editor.canvas
        if (
            canvas.mixed_move
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
            or canvas.collection_session is not None
        ):
            editor.status_label.setText("请先完成或撤销当前暂存关联编辑，再更改图层。")
            return
        if canvas.source_context_revision != loaded.document.revision:
            self._sync_drawing_layers()
            editor.status_label.setText("图纸已变化，请重新选择对象。")
            return
        try:
            target = canvas.layer_table.get(layer_name)
        except KeyError:
            editor.status_label.setText("目标图层已不存在，请重新选择。")
            return
        if target.locked or not target.displayed:
            editor.status_label.setText("目标图层隐藏、冻结或已锁定，无法移入。")
            return
        draft = tuple(entity for entity in canvas.entities if entity.entity_id in ids)
        dimension_ids = set(canvas.selected_constraint_ids)
        draft_dimensions = tuple(
            item for item in canvas.constraints if item.constraint_id in dimension_ids
        )
        saved_dimensions = tuple(
            item
            for sketch in services.kernel.sketches
            for item in sketch.constraints
            if item.constraint_id in dimension_ids
        )
        dimensions = (*draft_dimensions, *saved_dimensions)
        if (
            len(dimensions) != len(dimension_ids)
            or {item.constraint_id for item in dimensions} != dimension_ids
            or any(item.kind not in DIMENSION_KINDS for item in dimensions)
        ):
            editor.status_label.setText("所选尺寸已变化或身份不唯一，请重新选择。")
            return
        image_ids = set(canvas.selected_raster_ids)
        images = tuple(
            image for image in services.kernel.drawing_rasters if image.image_id in image_ids
        )
        if len(images) != len(image_ids):
            editor.status_label.setText("所选图片已变化，请重新选择。")
            return
        saved = tuple(
            (sketch, entity)
            for sketch in services.kernel.sketches
            for entity in sketch.entities
            if entity.entity_id in ids
        )
        found = [entity.entity_id for entity in draft] + [entity.entity_id for _, entity in saved]
        if (
            (not ids and not image_ids and not dimension_ids)
            or len(found) != len(ids)
            or set(found) != ids
        ):
            editor.status_label.setText("所选图元已变化或身份不唯一，请重新选择。")
            return
        try:
            if any(
                (layer := canvas.layer_table.get(entity.layer_name)).locked or not layer.displayed
                for entity in (*draft, *(entity for _, entity in saved), *images)
            ) or any(
                (layer := canvas.annotation_layer(item)).locked or not layer.displayed
                for item in dimensions
            ):
                editor.status_label.setText("所选图元位于隐藏、冻结或锁定的图层。")
                return
        except KeyError:
            editor.status_label.setText("所选图元的图层已变化，请重新选择。")
            return
        draft_candidate = tuple(
            replace(entity, layer_name=target.name) if entity.entity_id in ids else entity
            for entity in canvas.entities
        )
        draft_constraint_candidate = tuple(
            replace(item, layer_name=target.name) if item.constraint_id in dimension_ids else item
            for item in canvas.constraints
        )
        try:
            canvas.validate_draft_constraint_edits(
                draft_candidate, removed_constraint_ids=frozenset()
            )
        except ValueError as exc:
            editor.status_label.setText(str(exc))
            return
        revisions: list[dict[str, object]] = []
        includes_points = False
        for sketch in services.kernel.sketches:
            if not any(entity.entity_id in ids for entity in sketch.entities) and not any(
                item.constraint_id in dimension_ids for item in sketch.constraints
            ):
                continue
            revised = replace(
                sketch,
                entities=tuple(
                    replace(entity, layer_name=target.name) if entity.entity_id in ids else entity
                    for entity in sketch.entities
                ),
                constraints=tuple(
                    replace(item, layer_name=target.name)
                    if item.constraint_id in dimension_ids
                    else item
                    for item in sketch.constraints
                ),
            )
            if revised == sketch:
                continue
            state = revised.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            )
            includes_points = includes_points or any(
                isinstance(entity, PointEntity) for entity in revised.entities
            )
        raster_updates = tuple(
            replace(image, layer_name=target.name)
            for image in images
            if image.layer_name != target.name
        )
        if not revisions and not raster_updates:
            if draft_candidate == tuple(canvas.entities) and draft_constraint_candidate == tuple(
                canvas.constraints
            ):
                editor.status_label.setText("所选图元已经位于当前图层。")
            elif draft_constraint_candidate != tuple(canvas.constraints):
                original = editor.dimension_sources()[0]
                if canvas.apply_constraint_solution(
                    original,
                    replace(
                        original, entities=draft_candidate, constraints=draft_constraint_candidate
                    ),
                ):
                    editor.status_label.setText(f"已将选中对象移至图层 {target.name}；可撤销。")
                else:
                    editor.status_label.setText("草稿已变化，请重新选择。")
            elif canvas.replace_draft_entities(draft_candidate):
                editor.status_label.setText(f"已将选中图元移至图层 {target.name}；可撤销。")
            else:
                editor.status_label.setText(canvas.message)
            return
        self._submit_drawing_revisions(
            editor,
            session_id,
            revisions,
            includes_points,
            "更改图层",
            raster_updates=raster_updates,
            draft_candidate=(
                draft_candidate
                if draft_candidate != tuple(canvas.entities)
                or draft_constraint_candidate != tuple(canvas.constraints)
                else None
            ),
            draft_constraint_candidate=(
                draft_constraint_candidate
                if draft_constraint_candidate != tuple(canvas.constraints)
                else None
            ),
            dimension_layer_updates=any(
                item.layer_name != target.name for item in saved_dimensions
            ),
        )

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
        if editor.canvas.collection_session is not None:
            editor.status_label.setText("请先完成或取消当前暂存，再修改图层。")
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

    def _prepare_collection_dimension(
        self,
        snapshot: DrawingCollectionSnapshot,
        sketch: Sketch,
        constraint: SketchConstraint,
    ) -> tuple[ReplayAppend, SketchConstraintSolveResult, tuple[Sketch, ...]]:
        services = self._services
        if services is None:
            raise ValidationError("图纸不可用。")
        if (
            next((item for item in snapshot.sketches if item.sketch_id == sketch.sketch_id), None)
            != sketch
        ):
            raise ValidationError("暂存草图已变化，请重新拾取尺寸。")
        linked = any(
            sketch.sketch_id in (item.first.sketch_id, item.second.sketch_id)
            for item in snapshot.cross_tangencies
        )
        if linked:
            params, solved, changes = mycad_app.prepare_cross_sketch_dimension_from_state(
                snapshot.sketches, snapshot.cross_tangencies, sketch.sketch_id, constraint
            )
            from mycad.core.drawing_transactions import require_independent_geometry_edits

            require_independent_geometry_edits(snapshot.groups, snapshot.sketches, solved)
            target = next(item for item in solved if item.sketch_id == sketch.sketch_id)
            return (
                ReplayAppend("drawing.sketch.revise", 79, params, "local"),
                SketchConstraintSolveResult("success", target, None, branch_changes=changes),
                tuple(item for item in solved if item.sketch_id != sketch.sketch_id),
            )
        updating = any(
            item.constraint_id == constraint.constraint_id for item in sketch.constraints
        )
        result = (
            services.kernel.preview_sketch_constraint_update(sketch, constraint)
            if updating
            else services.kernel.preview_sketch_constraint(sketch, constraint)
        )
        if result.status != "success" or result.sketch is None:
            raise ValidationError(result.message or "尺寸求解失败。")
        from mycad.core.drawing_transactions import require_independent_geometry_edits

        require_independent_geometry_edits(snapshot.groups, (sketch,), (result.sketch,))
        return (
            ReplayAppend(
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                9 if updating else 11,
                result.command_params(sketch, constraint, local_frame=True),
                "local",
            ),
            result,
            (),
        )

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
        collection = editor.canvas.collection_session
        if collection is not None:
            try:
                checkpoint = collection.checkpoint()
                collection_state = collection.snapshot
            except ValidationError as exc:
                editor.dimensions.complete_preview(
                    generation,
                    sketch,
                    constraint,
                    SketchConstraintSolveResult("failed", None, None, message=str(exc)),
                )
                return

            def solve_collection() -> _SketchConstraintPreview:
                operation, result, linked = self._prepare_collection_dimension(
                    collection_state, sketch, constraint
                )
                projected = collection.preview_operation(operation)
                expected = {
                    item.sketch_id: item for item in (result.sketch, *linked) if item is not None
                }
                if any(
                    next(
                        (item for item in projected.sketches if item.sketch_id == identity),
                        None,
                    )
                    != target
                    for identity, target in expected.items()
                ):
                    raise ValidationError("尺寸求解结果与暂存候选不一致。")
                return _SketchConstraintPreview(
                    result,
                    linked_sketches=linked,
                )

            def finish_collection(value: ExecutionResult) -> None:
                if (
                    self._sketch_dialog is not editor
                    or editor.canvas.collection_session is not collection
                ):
                    return
                try:
                    if collection.checkpoint() != checkpoint:
                        raise ValidationError("暂存内容已变化，请重新预览尺寸。")
                    preview = value.value
                    if value.error is not None or not isinstance(preview, _SketchConstraintPreview):
                        raise ValidationError(str(value.error or "尺寸预览失败。"))
                    result = preview.solve_result
                except (ValidationError, ValueError) as exc:
                    preview = None
                    result = SketchConstraintSolveResult("failed", None, None, message=str(exc))
                editor.dimensions.complete_preview(generation, sketch, constraint, result)
                if (
                    preview is not None
                    and editor.dimensions.accepted_preview(sketch, constraint) is result
                ):
                    editor.show_linked_dimension_previews(preview.linked_sketches)

            if not unit.submit(
                solve_collection,
                operation="collection-dimension-preview",
                session_id=session_id,
                on_complete=finish_collection,
            ):
                editor.dimensions.complete_preview(
                    generation,
                    sketch,
                    constraint,
                    SketchConstraintSolveResult(
                        "failed", None, None, message="几何工作线程忙碌，请重新预览"
                    ),
                )
            return
        commands = tuple(loaded.document.commands)
        source_archive_version = loaded.document.archive_version
        updating = any(c.constraint_id == constraint.constraint_id for c in sketch.constraints)
        linked = any(
            sketch.sketch_id in (relation.first.sketch_id, relation.second.sketch_id)
            for relation in services.kernel.cross_sketch_tangencies
        )

        def solve() -> _SketchConstraintPreview:
            from mycad.core.drawing_transactions import require_independent_geometry_edits

            if linked:
                params, solved, branch_changes = mycad_app.prepare_cross_sketch_dimension(
                    services, sketch.sketch_id, constraint
                )
                require_independent_geometry_edits(
                    services.kernel.drawing_groups, services.kernel.sketches, solved
                )
                target = next(item for item in solved if item.sketch_id == sketch.sketch_id)
                snapshot, previews = mycad_app.preview_command_with_sketches(
                    services,
                    commands,
                    "drawing.sketch.revise",
                    params,
                    source_archive_version=source_archive_version,
                    source_document_type=loaded.document.document_type,
                    source_document_kind=loaded.document.document_kind,
                    source_drawing_fillet_baseline=loaded.document.drawing_fillet_baseline,
                    source_drawing_chamfer_angle_baseline=(
                        loaded.document.drawing_chamfer_angle_baseline
                    ),
                    command_version=64
                    if mycad_app.revisions_include_curve_point_ids(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 56
                    if mycad_app.revisions_require_normal_side_preservation(
                        services, cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 53
                    if mycad_app.revisions_include_dimension_tolerances(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 50
                    if mycad_app.revisions_include_dimension_styles(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 48
                    if mycad_app.revisions_include_dimension_text(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 31
                    if mycad_app.revisions_include_projection_axes(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 9
                    if mycad_app.revisions_include_local_endpoint_constraints(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 4,
                    target_archive_version=8
                    if source_archive_version < 8
                    and mycad_app.revisions_include_curve_point_ids(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else None,
                )
                return _SketchConstraintPreview(
                    SketchConstraintSolveResult(
                        "success", target, None, branch_changes=branch_changes
                    ),
                    snapshot,
                    previews,
                    tuple(item for item in solved if item.sketch_id != sketch.sketch_id),
                )
            result = (
                services.kernel.preview_sketch_constraint_update(sketch, constraint)
                if updating
                else services.kernel.preview_sketch_constraint(sketch, constraint)
            )
            if result.status != "success":
                return _SketchConstraintPreview(result)
            if result.sketch is not None:
                require_independent_geometry_edits(
                    services.kernel.drawing_groups, (sketch,), (result.sketch,)
                )
            preserve_normal_side = mycad_app.revisions_require_attachment_protection(
                services, ({"sketch_id": sketch.sketch_id},)
            )
            snapshot, sketches = mycad_app.preview_command_with_sketches(
                services,
                commands,
                "sketch.constraint.update" if updating else "sketch.constraint.add",
                result.command_params(
                    sketch,
                    constraint,
                    local_frame=(
                        constraint.projection_axis is not None
                        or constraint.text_override is not None
                        or constraint.style_name is not None
                        or constraint.tolerance is not None
                        or preserve_normal_side
                        or mycad_app.sketch_has_curve_point_ids(sketch)
                    ),
                ),
                source_archive_version=source_archive_version,
                source_document_type=loaded.document.document_type,
                source_document_kind=loaded.document.document_kind,
                source_drawing_fillet_baseline=loaded.document.drawing_fillet_baseline,
                source_drawing_chamfer_angle_baseline=(
                    loaded.document.drawing_chamfer_angle_baseline
                ),
                command_version=(9 if updating else 11)
                if mycad_app.sketch_has_curve_point_ids(sketch)
                else (8 if updating else 10)
                if preserve_normal_side
                else (7 if updating else 9)
                if constraint.tolerance is not None
                else (6 if updating else 8)
                if constraint.style_name is not None
                else (5 if updating else 7)
                if constraint.text_override is not None
                else (4 if updating else 6)
                if constraint.projection_axis is not None
                else None,
                target_archive_version=6
                if (
                    constraint.projection_axis is not None
                    or constraint.text_override is not None
                    or constraint.style_name is not None
                    or constraint.tolerance is not None
                    or preserve_normal_side
                    or mycad_app.sketch_has_curve_point_ids(sketch)
                )
                and source_archive_version < 6
                else None,
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
            if (
                isinstance(preview, _SketchConstraintPreview)
                and result.status == "success"
                and editor.dimensions.accepted_preview(sketch, constraint) is result
            ):
                editor.show_linked_dimension_previews(preview.linked_sketches)

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
        collection = editor.canvas.collection_session
        if collection is not None:
            try:
                checkpoint = collection.checkpoint()
                state = collection.snapshot
                accepted = editor.dimensions.accepted_preview(sketch, constraint)
                presentation_only = editor.dimensions.presentation_only
                if presentation_only and accepted is None:
                    original_dimension = next(
                        (
                            item
                            for item in sketch.constraints
                            if item.constraint_id == constraint.constraint_id
                        ),
                        None,
                    )
                    if (
                        original_dimension is None
                        or replace(
                            original_dimension,
                            position_mm=constraint.position_mm,
                            text_position_mm=constraint.text_position_mm,
                        )
                        != constraint
                    ):
                        raise ValidationError("尺寸拖动仅能改变标注位置。")
                    expected = {item.sketch_id: item for item in state.sketches}
                    expected[sketch.sketch_id] = replace(
                        sketch,
                        constraints=tuple(
                            constraint if item.constraint_id == constraint.constraint_id else item
                            for item in sketch.constraints
                        ),
                    )
                else:
                    if accepted is None or accepted.status != "success" or accepted.sketch is None:
                        raise ValidationError("请重新预览跨草图尺寸。")
                    expected = {
                        item.sketch_id: item
                        for item in (accepted.sketch, *editor.canvas.dimension_linked_sources)
                    }
            except (ValidationError, ValueError) as exc:
                editor.dimensions.complete_commit(
                    sketch,
                    constraint,
                    SketchConstraintSolveResult("failed", None, None, message=str(exc)),
                )
                return

            def solve_collection() -> tuple[
                ReplayAppend, SketchConstraintSolveResult, tuple[Sketch, ...]
            ]:
                return self._prepare_collection_dimension(state, sketch, constraint)

            def finish_collection(value: ExecutionResult) -> None:
                if (
                    self._sketch_dialog is not editor
                    or editor.canvas.collection_session is not collection
                ):
                    return
                try:
                    if (
                        collection.checkpoint() != checkpoint
                        or editor.dimensions.candidate != constraint
                    ):
                        raise ValidationError("暂存内容或尺寸已变化，请重新预览。")
                    if value.error is not None or not isinstance(value.value, tuple):
                        raise ValidationError(str(value.error or "尺寸求解失败。"))
                    operation, solved, linked = cast(
                        "tuple[ReplayAppend, SketchConstraintSolveResult, tuple[Sketch, ...]]",
                        value.value,
                    )
                    actual = (
                        {item.sketch_id: item for item in (solved.sketch, *linked)}
                        if solved.sketch is not None
                        else {}
                    )
                    if solved.sketch is None or (
                        any(expected.get(identity) != item for identity, item in actual.items())
                        if presentation_only and accepted is None
                        else actual != expected
                    ):
                        raise ValidationError("求解结果与预览不一致，请重新预览。")
                    if not editor.canvas.stage_collection_operation(operation):
                        raise ValidationError(editor.canvas.message)
                    result = solved
                except (ValidationError, ValueError, StopIteration) as exc:
                    result = SketchConstraintSolveResult("failed", None, None, message=str(exc))
                editor.dimensions.complete_commit(sketch, constraint, result)

            if not unit.submit(
                solve_collection,
                operation="collection-dimension-commit",
                session_id=session_id,
                on_complete=finish_collection,
            ):
                editor.dimensions.complete_commit(
                    sketch,
                    constraint,
                    SketchConstraintSolveResult(
                        "failed", None, None, message="几何工作线程忙碌，请重试。"
                    ),
                )
            return
        commands = tuple(loaded.document.commands)
        updating = any(c.constraint_id == constraint.constraint_id for c in sketch.constraints)
        linked = any(
            sketch.sketch_id in (relation.first.sketch_id, relation.second.sketch_id)
            for relation in services.kernel.cross_sketch_tangencies
        )
        accepted = editor.dimensions.accepted_preview(sketch, constraint) if linked else None
        expected_sketches = (
            (accepted.sketch, *editor.canvas.dimension_linked_sources)
            if accepted is not None and accepted.status == "success" and accepted.sketch is not None
            else None
        )

        def submit() -> SketchConstraintSolveResult:
            from mycad.core.drawing_transactions import require_independent_geometry_edits

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
            if linked:
                if expected_sketches is None:
                    return SketchConstraintSolveResult(
                        "failed", None, None, message="请重新预览跨草图尺寸"
                    )
                require_independent_geometry_edits(
                    services.kernel.drawing_groups, services.kernel.sketches, expected_sketches
                )

                def still_current() -> bool:
                    return (
                        session_id == self._session_id
                        and loaded is self._loaded
                        and editor.dimensions.candidate == constraint
                        and tuple(loaded.document.commands) == commands
                    )

                mycad_app.commit_cross_sketch_dimension(
                    services,
                    loaded,
                    sketch.sketch_id,
                    constraint,
                    session_identity=session_id,
                    still_current=still_current,
                    expected_sketches=expected_sketches,
                )
                target = next(
                    item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id
                )
                return SketchConstraintSolveResult("success", target, None)
            result = (
                services.kernel.preview_sketch_constraint_update(sketch, constraint)
                if updating
                else services.kernel.preview_sketch_constraint(sketch, constraint)
            )
            if result.status != "success":
                return result
            if result.sketch is not None:
                require_independent_geometry_edits(
                    services.kernel.drawing_groups, (sketch,), (result.sketch,)
                )
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
            command_id = "sketch.constraint.update" if updating else "sketch.constraint.add"
            preserve_normal_side = mycad_app.revisions_require_attachment_protection(
                services, ({"sketch_id": sketch.sketch_id},)
            )
            if (
                constraint.projection_axis is not None
                or constraint.text_override is not None
                or constraint.style_name is not None
                or constraint.tolerance is not None
                or preserve_normal_side
                or mycad_app.sketch_has_curve_point_ids(sketch)
            ):
                candidate = mycad_app.create_replay_candidate(
                    services, loaded, session_identity=session_id
                )
                candidate.stage(
                    ReplayChangeSet(
                        (),
                        (
                            ReplayAppend(
                                command_id,
                                (9 if updating else 11)
                                if mycad_app.sketch_has_curve_point_ids(sketch)
                                else (8 if updating else 10)
                                if preserve_normal_side
                                else (7 if updating else 9)
                                if constraint.tolerance is not None
                                else (6 if updating else 8)
                                if constraint.style_name is not None
                                else (5 if updating else 7)
                                if constraint.text_override is not None
                                else (4 if updating else 6),
                                result.command_params(sketch, constraint, local_frame=True),
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
                    raise ValueError(str(preview.failure or "尺寸预览失败"))
                candidate.commit(
                    candidate.authorize_commit(current_session_identity=session_id),
                    current_session_identity=session_id,
                )
            else:
                loaded.bus.execute(
                    command_id, result.command_params(sketch, constraint), confirmed_by="local"
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

    def _on_cross_sketch_tangency(self, *, force_dialog: bool = False) -> None:
        loaded, services = self._loaded, self._services
        if loaded is None or services is None or loaded.document.document_type != "drawing2d":
            self.status_command.setText("对象相切需要已打开的二维图纸。")
            return
        if self._cross_tangency_dialog is not None:
            self._cross_tangency_dialog.raise_()
            return
        editor = self._sketch_dialog
        canvas = editor.canvas if editor is not None else None
        selected_segments = canvas.selected_tangent_segments() if canvas is not None else {}
        if canvas is not None and (canvas.has_pending_geometry or canvas.has_active_edit_gesture):
            self.status_command.setText("请先完成或取消当前绘图操作。")
            return
        if canvas is not None and not canvas.mixed_move_is_valid:
            self.status_command.setText("混合草稿已过期，请先撤销或取消。")
            return
        if (
            canvas is not None
            and canvas.mixed_move is None
            and canvas.source_context_revision is not None
            and canvas.source_context_revision != loaded.document.revision
            and any(
                entity.entity_id in canvas.selected_entity_ids
                for entity, _layer in canvas.background_entities
            )
        ):
            canvas.selected_entity_ids.clear()
            canvas.clear_selected_tangent_segments()
            self._sync_drawing_layers()
            canvas.message = "文档已变化；请重新选择对象。"
            canvas.changed.emit()
            canvas.update()
            return
        if canvas is not None and not force_dialog and len(canvas.selected_entity_ids) < 2:
            canvas.begin_object_tangency_selection()
            canvas.setFocus()
            return
        try:
            collection_snapshot = (
                canvas.collection_session.snapshot
                if canvas is not None and canvas.collection_session is not None
                else None
            )
            saved = (
                tuple(
                    sketch
                    for sketch in collection_snapshot.sketches
                    if editor is None or sketch.sketch_id != editor.draft_sketch_id
                )
                if collection_snapshot is not None
                else canvas.mixed_move.current_saved
                if canvas is not None and canvas.mixed_move
                else services.kernel.sketches
            )
        except ValidationError as exc:
            self.status_command.setText(str(exc))
            return
        draft = (
            Sketch(
                editor.draft_sketch_id,
                editor.current_frame(),
                tuple(canvas.entities),
                tuple(canvas.constraints),
                canvas.layer_table,
            )
            if editor is not None and canvas is not None and canvas.entities
            else None
        )
        if (
            not force_dialog
            and draft is not None
            and canvas is not None
            and editor is not None
            and len(canvas.selected_entity_ids) == 2
        ):
            selected = tuple(
                entity
                for entity in draft.entities
                if entity.entity_id in canvas.selected_entity_ids
            )
            if len(selected) == 2 and all(
                isinstance(entity, LineEntity | CircleEntity | ArcEntity)
                or (
                    isinstance(entity, PolylineEntity | RectangleEntity)
                    and entity.entity_id in selected_segments
                )
                for entity in selected
            ):
                linked_draft = collection_snapshot is not None and any(
                    draft.sketch_id in (item.first.sketch_id, item.second.sketch_id)
                    for item in collection_snapshot.cross_tangencies
                )
                if canvas.mixed_move or canvas.pending_cross_tangencies or linked_draft:
                    constraint = SketchConstraint(
                        uuid4().hex,
                        "tangent",
                        tuple(
                            SketchGeometryReference(
                                entity.entity_id,
                                "segment"
                                if isinstance(entity, PolylineEntity | RectangleEntity)
                                else "geometry",
                                selected_segments.get(entity.entity_id),
                            )
                            for entity in selected
                        ),
                    )
                    self._start_mixed_local_tangency(editor, draft, constraint)
                    return
                unit = self.execution_unit
                if unit is None:
                    self.status_command.setText("几何工作线程不可用。")
                    return
                constraint = SketchConstraint(
                    uuid4().hex,
                    "tangent",
                    tuple(
                        SketchGeometryReference(
                            entity.entity_id,
                            "segment"
                            if isinstance(entity, PolylineEntity | RectangleEntity)
                            else "geometry",
                            selected_segments.get(entity.entity_id),
                        )
                        for entity in selected
                    ),
                )
                session_id = self._session_id
                revision = loaded.document.revision

                def finish_local_tangency(result: ExecutionResult) -> None:
                    if (
                        self._loaded is not loaded
                        or self._session_id != session_id
                        or self._sketch_dialog is not editor
                        or loaded.document.revision != revision
                        or editor.current_frame() != draft.frame
                        or canvas.layer_table != draft.layers
                        or canvas.mixed_move
                        or canvas.pending_cross_tangencies
                    ):
                        return
                    solved = result.value
                    if (
                        result.error is not None
                        or not isinstance(solved, SketchConstraintSolveResult)
                        or solved.status != "success"
                        or solved.sketch is None
                    ):
                        self.status_command.setText(
                            result.error or getattr(solved, "message", None) or "无法建立相切。"
                        )
                        return
                    if canvas.apply_constraint_solution(
                        draft, solved.sketch, confirmed_constraint=constraint, solve_result=solved
                    ):
                        canvas.message = "相切约束已建立，可撤销。"
                        canvas.changed.emit()
                    else:
                        self.status_command.setText(
                            canvas.message or "图形已改变，请重新选择对象。"
                        )

                if not unit.submit(
                    lambda: services.kernel.preview_sketch_constraint(draft, constraint),
                    operation="canvas-tangency",
                    session_id=session_id,
                    on_complete=finish_local_tangency,
                ):
                    self.status_command.setText("几何工作线程忙碌，请重试。")
                return
        if (
            not force_dialog
            and canvas is not None
            and editor is not None
            and len(canvas.selected_entity_ids) == 2
        ):
            owners = [
                sketch
                for sketch in saved
                if canvas.selected_entity_ids <= {entity.entity_id for entity in sketch.entities}
            ]
            if len(owners) == 1:
                owner = owners[0]
                selected = tuple(
                    entity
                    for entity in owner.entities
                    if entity.entity_id in canvas.selected_entity_ids
                )
                if len(selected) == 2 and all(
                    isinstance(entity, LineEntity | CircleEntity | ArcEntity)
                    or (
                        isinstance(entity, PolylineEntity | RectangleEntity)
                        and entity.entity_id in selected_segments
                    )
                    for entity in selected
                ):
                    if canvas.mixed_move or canvas.pending_cross_tangencies:
                        self.status_command.setText("对象存在关联编辑，请先完成或处理关联关系。")
                        return
                    unit = self.execution_unit
                    if unit is None:
                        self.status_command.setText("几何工作线程不可用。")
                        return
                    constraint = SketchConstraint(
                        uuid4().hex,
                        "tangent",
                        tuple(
                            SketchGeometryReference(
                                entity.entity_id,
                                "segment"
                                if isinstance(entity, PolylineEntity | RectangleEntity)
                                else "geometry",
                                selected_segments.get(entity.entity_id),
                            )
                            for entity in selected
                        ),
                    )
                    collection = canvas.collection_session
                    if collection is not None:
                        try:
                            checkpoint = collection.checkpoint()
                            snapshot = collection.snapshot
                        except ValidationError as exc:
                            self.status_command.setText(str(exc))
                            return

                        def finish_collection_tangency(value: ExecutionResult) -> None:
                            if (
                                self._sketch_dialog is not editor
                                or canvas.collection_session is not collection
                            ):
                                return
                            try:
                                if collection.checkpoint() != checkpoint:
                                    raise ValidationError("暂存内容已变化，请重新选择对象。")
                                if value.error is not None or not isinstance(value.value, tuple):
                                    raise ValidationError(str(value.error or "对象相切求解失败。"))
                                operation, _solved, _linked = cast(
                                    "tuple[ReplayAppend, SketchConstraintSolveResult, tuple[Sketch, ...]]",
                                    value.value,
                                )
                                if not canvas.stage_collection_operation(operation):
                                    raise ValidationError(canvas.message)
                            except (ValidationError, ValueError) as exc:
                                self.status_command.setText(f"对象相切未暂存：{exc}")
                                return
                            self.status_command.setText("对象相切已暂存，可撤销。")

                        if not unit.submit(
                            lambda: self._prepare_collection_dimension(snapshot, owner, constraint),
                            operation="collection-saved-tangency",
                            session_id=self._session_id,
                            on_complete=finish_collection_tangency,
                        ):
                            self.status_command.setText("几何工作线程忙碌，请重试。")
                        return
                    session_id = self._session_id
                    commands = tuple(loaded.document.commands)
                    linked = any(
                        owner.sketch_id in (relation.first.sketch_id, relation.second.sketch_id)
                        for relation in services.kernel.cross_sketch_tangencies
                    )

                    def submit_saved_tangency() -> SketchConstraintSolveResult:
                        from mycad.core.drawing_transactions import (
                            require_independent_geometry_edits,
                        )

                        if linked:

                            def still_current() -> bool:
                                return (
                                    self._loaded is loaded
                                    and self._session_id == session_id
                                    and tuple(loaded.document.commands) == commands
                                )

                            if not still_current():
                                return SketchConstraintSolveResult(
                                    "failed", None, None, message="图纸已改变，请重新选择对象。"
                                )
                            _params, expected, _changes = mycad_app.prepare_cross_sketch_dimension(
                                services, owner.sketch_id, constraint
                            )
                            require_independent_geometry_edits(
                                services.kernel.drawing_groups, services.kernel.sketches, expected
                            )
                            mycad_app.commit_cross_sketch_dimension(
                                services,
                                loaded,
                                owner.sketch_id,
                                constraint,
                                session_identity=session_id,
                                still_current=still_current,
                                expected_sketches=expected,
                            )
                            updated = next(
                                sketch
                                for sketch in services.kernel.sketches
                                if sketch.sketch_id == owner.sketch_id
                            )
                            return SketchConstraintSolveResult("success", updated, None)
                        result = services.kernel.preview_sketch_constraint(owner, constraint)
                        if result.status != "success":
                            return result
                        if result.sketch is not None:
                            require_independent_geometry_edits(
                                services.kernel.drawing_groups, (owner,), (result.sketch,)
                            )
                        if (
                            self._loaded is not loaded
                            or self._session_id != session_id
                            or tuple(loaded.document.commands) != commands
                            or next(
                                (
                                    s
                                    for s in services.kernel.sketches
                                    if s.sketch_id == owner.sketch_id
                                ),
                                None,
                            )
                            != owner
                        ):
                            return SketchConstraintSolveResult(
                                "failed", None, None, message="图纸已改变，请重新选择对象。"
                            )
                        preserve_normal_side = mycad_app.revisions_require_attachment_protection(
                            services, ({"sketch_id": owner.sketch_id},)
                        )
                        loaded.bus.execute(
                            "sketch.constraint.add",
                            result.command_params(
                                owner, constraint, local_frame=preserve_normal_side
                            ),
                            confirmed_by="local",
                            version=10 if preserve_normal_side else None,
                        )
                        return result

                    def finish_saved_tangency(value: ExecutionResult) -> None:
                        if self._loaded is not loaded or self._session_id != session_id:
                            return
                        result = value.value
                        if (
                            value.error is not None
                            or not isinstance(result, SketchConstraintSolveResult)
                            or result.status != "success"
                        ):
                            self.status_command.setText(
                                value.error or getattr(result, "message", None) or "无法建立相切。"
                            )
                            return
                        if self._sketch_dialog is editor:
                            editor.set_context_sketches(services.kernel.sketches)
                        if self.viewport is not None:
                            self.viewport.refresh()
                        self.status_command.setText("相切约束已写入历史，可撤销。")

                    if not unit.submit(
                        submit_saved_tangency,
                        operation="saved-object-tangency",
                        session_id=session_id,
                        on_complete=finish_saved_tangency,
                    ):
                        self.status_command.setText("几何工作线程忙碌，请重试。")
                    return
        sketches = (*saved, *((draft,) if draft is not None else ()))
        if not sketches:
            self.status_command.setText("请先选择两个可建立相切关系的对象。")
            return
        try:
            committed_relations = (
                canvas.collection_session.snapshot.cross_tangencies
                if canvas is not None and canvas.collection_session is not None
                else _staged_committed_tangencies(
                    canvas.mixed_move.original_saved,
                    services.kernel.cross_sketch_tangencies,
                    tuple(
                        (saved_step, transforms)
                        for saved_step, _draft, _pairs, _arrays, transforms in canvas.mixed_move_timeline_with_transforms()
                    ),
                )
                if canvas is not None and canvas.mixed_move is not None
                else services.kernel.cross_sketch_tangencies
            )
            staged = (
                mycad_app.draft_cross_relations(
                    saved, draft, tuple(canvas.pending_cross_tangencies)
                )
                if draft is not None and canvas is not None and canvas.collection_session is None
                else ()
            )
        except (ValueError, ValidationError) as exc:
            self.status_command.setText(f"暂存相切关系无效：{exc}")
            return
        dialog = CrossSketchTangencyDialog(
            sketches,
            (*committed_relations, *staged),
            self,
            draft_sketch_id=draft.sketch_id if draft else None,
            selected_entity_ids=frozenset(canvas.selected_entity_ids) if canvas else frozenset(),
            selected_segment_indices=selected_segments,
        )
        self._cross_tangency_dialog = dialog
        self._cross_tangency_preview = None
        session_id = self._session_id
        dialog.preview_requested.connect(partial(self._preview_cross_tangency, dialog, session_id))
        dialog.commit_requested.connect(partial(self._commit_cross_tangency, dialog, session_id))
        dialog.remove_requested.connect(partial(self._remove_cross_tangency, dialog, session_id))

        def select_on_canvas() -> None:
            if self._cross_tangency_dialog is not dialog or self._sketch_dialog is not editor:
                return
            dialog.reject()
            if editor is not None:
                editor.canvas.begin_object_tangency_selection()
                editor.canvas.setFocus()

        dialog.canvas_selection_requested.connect(select_on_canvas)

        def finished(_result: int) -> None:
            if self._cross_tangency_dialog is dialog:
                self._cross_tangency_dialog = None
                self._cross_tangency_preview = None

        dialog.finished.connect(finished)
        dialog.open()
        if not force_dialog and canvas is not None and len(canvas.selected_entity_ids) == 2:
            first, second = dialog.first_combo.currentData(), dialog.second_combo.currentData()
            if (
                isinstance(first, CrossSketchRef)
                and isinstance(second, CrossSketchRef)
                and first.sketch_id != second.sketch_id
                and {first.entity_id, second.entity_id} == canvas.selected_entity_ids
                and isinstance(dialog.branch_combo.currentData(), str)
            ):

                def complete_automatic_preview(success: bool) -> None:
                    dialog.preview_completed.disconnect(complete_automatic_preview)
                    if success and self._cross_tangency_dialog is dialog:
                        dialog.commit_button.click()

                dialog.preview_completed.connect(complete_automatic_preview)
                dialog.preview_button.click()

    def _start_mixed_local_tangency(
        self, editor: SketchEditorDialog, draft: Sketch, constraint: SketchConstraint
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None:
            self.status_command.setText("图纸或几何工作线程不可用。")
            return
        canvas = editor.canvas
        collection = canvas.collection_session
        if collection is not None:
            try:
                checkpoint = collection.checkpoint()
                snapshot = collection.snapshot
            except ValidationError as exc:
                self.status_command.setText(str(exc))
                return
            session_id = self._session_id

            def finish_collection(result: ExecutionResult) -> None:
                if (
                    self._loaded is not loaded
                    or self._session_id != session_id
                    or self._sketch_dialog is not editor
                    or canvas.collection_session is not collection
                ):
                    return
                try:
                    if collection.checkpoint() != checkpoint:
                        raise ValidationError("暂存内容已变化，请重新选择对象。")
                    value = result.value
                    if (
                        result.error is not None
                        or not isinstance(value, tuple)
                        or len(cast("tuple[object, ...]", value)) != 3
                    ):
                        raise ValidationError(str(result.error or "对象相切求解失败。"))
                    params, solved, _changes = cast("tuple[object, ...]", value)
                    if not isinstance(params, dict) or not isinstance(solved, tuple):
                        raise ValidationError("对象相切求解结果无效。")
                    from mycad.core.drawing_transactions import require_independent_geometry_edits

                    require_independent_geometry_edits(
                        snapshot.groups, snapshot.sketches, cast("tuple[Sketch, ...]", solved)
                    )
                    operation = ReplayAppend(
                        "drawing.sketch.revise", 79, cast("dict[str, object]", params), "local"
                    )
                    if not canvas.stage_collection_operation(operation):
                        raise ValidationError(canvas.message)
                except (ValidationError, ValueError) as exc:
                    self.status_command.setText(f"对象相切未暂存：{exc}")
                    return
                canvas.message = "对象相切已暂存，可撤销。"
                self.status_command.setText(canvas.message)
                canvas.changed.emit()
                canvas.update()

            if not unit.submit(
                lambda: mycad_app.prepare_cross_sketch_dimension_from_state(
                    snapshot.sketches, snapshot.cross_tangencies, draft.sketch_id, constraint
                ),
                operation="collection-local-tangency",
                session_id=session_id,
                on_complete=finish_collection,
            ):
                self.status_command.setText("几何工作线程忙碌，请重试。")
            return
        previous = canvas.mixed_move
        revision, session_id = loaded.document.revision, self._session_id
        if previous is not None and (
            not canvas.mixed_move_is_valid or previous.source_revision != revision
        ):
            self.status_command.setText("关联编辑已过期，请撤销后重试。")
            return
        original_saved = previous.original_saved if previous else services.kernel.sketches
        context = _MixedHandleContext(
            previous,
            original_saved,
            previous.current_saved if previous else original_saved,
            previous.original_draft if previous else draft,
            draft,
            canvas.background_entities,
            tuple(canvas.pending_cross_tangencies),
            canvas.mixed_move_timeline_with_tangencies(),
            canvas.history_position,
            tuple(canvas.pending_associative_arrays),
            tuple(arrays for _s, _d, _p, arrays in canvas.mixed_move_timeline_with_arrays()),
            tuple(
                transforms
                for _s, _d, _p, _a, transforms in canvas.mixed_move_timeline_with_transforms()
            ),
        )

        def prepare() -> tuple[MixedMoveState, Sketch]:
            relations = _staged_committed_tangencies(
                context.original_saved,
                services.kernel.cross_sketch_tangencies,
                tuple(
                    (saved_step, transforms)
                    for (saved_step, _draft, _pairs), transforms in zip(
                        context.history, context.transform_history, strict=True
                    )
                ),
            )
            saved, solved_draft = mycad_app.prepare_mixed_draft_local_tangency(
                services,
                context.current_saved,
                draft,
                context.pairs,
                constraint,
                existing_relations=relations,
            )
            projected: dict[str, SketchEntity] = {}
            background_ids = {item.entity_id for item, _layer in context.background}
            for sketch in saved:
                for entity in sketch.entities:
                    if entity.entity_id not in background_ids:
                        continue
                    if entity.entity_id in projected:
                        raise ValueError("关联图元身份重复。")
                    projected[entity.entity_id] = project_coplanar_entity(
                        entity, sketch.frame, draft.frame
                    )
            background = tuple(
                (projected.get(item.entity_id, item), layer) for item, layer in context.background
            )
            state = MixedMoveState(
                previous.transaction_id if previous else uuid4().hex,
                revision,
                context.original_draft,
                context.original_saved,
                saved,
                previous.base_background if previous else context.background,
                background,
                previous.original_cross_tangencies if previous else context.pairs,
                previous.original_associative_arrays if previous else context.arrays,
            )
            candidate = mycad_app.stage_mixed_drawing_timeline(
                services,
                loaded,
                context.original_draft,
                context.original_saved,
                tuple((s, d) for s, d, _p in context.history) + ((saved, solved_draft),),
                session_identity=session_id,
                cross_pairs_by_step=tuple(p for _s, _d, p in context.history) + (context.pairs,),
                arrays_by_step=(*context.array_history, context.arrays),
                initial_cross_pairs=state.original_cross_tangencies,
                initial_associative_arrays=state.original_associative_arrays,
                rectangle_transforms_by_step=(*context.transform_history, ()),
            )
            try:
                result = candidate.preview(current_session_identity=session_id)
                if result.state != "succeeded":
                    raise ValueError(str(result.failure or "对象相切预览失败。"))
            finally:
                candidate.cancel()
            return state, solved_draft

        def finish(result: ExecutionResult) -> None:
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._sketch_dialog is not editor
                or loaded.document.revision != revision
                or not self._draft_tangency_context_current(editor, context)
            ):
                return
            value = result.value
            if (
                result.error is not None
                or not isinstance(value, tuple)
                or len(cast("tuple[object, ...]", value)) != 2
            ):
                self.status_command.setText(drawing_message(result.error or "对象相切求解失败。"))
                return
            state, solved_draft = cast("tuple[object, object]", value)
            if not isinstance(state, MixedMoveState) or not isinstance(solved_draft, Sketch):
                self.status_command.setText("对象相切求解结果无效。")
                return
            try:
                canvas.apply_mixed_move(
                    state, solved_draft.entities, constraints=solved_draft.constraints
                )
            except (KeyError, ValueError) as exc:
                self.status_command.setText(f"对象相切未暂存：{exc}")
                return
            canvas.message = "对象相切已暂存，可撤销。"
            canvas.changed.emit()
            canvas.update()

        if not unit.submit(
            prepare, operation="mixed-local-tangency", session_id=session_id, on_complete=finish
        ):
            self.status_command.setText("几何工作线程忙碌，请重试。")

    def _preview_cross_tangency(
        self, dialog: CrossSketchTangencyDialog, session_id: int, relation: CrossSketchTangency
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            dialog.complete_preview(relation, "文档已切换。", success=False)
            return
        revision = loaded.document.revision
        commands = tuple(loaded.document.commands)
        self._cross_tangency_preview = None
        editor = self._sketch_dialog
        collection = editor.canvas.collection_session if editor is not None else None
        if collection is not None:
            try:
                checkpoint = collection.checkpoint()
                snapshot = collection.snapshot
            except ValidationError as exc:
                dialog.complete_preview(relation, str(exc), success=False)
                return

            def solve_collection() -> tuple[ReplayAppend, tuple[Sketch, ...], tuple[Sketch, ...]]:
                from mycad.core.drawing_transactions import require_independent_geometry_edits

                original, solved = mycad_app.prepare_cross_sketch_tangency_from_state(
                    snapshot.sketches, snapshot.cross_tangencies, relation
                )
                require_independent_geometry_edits(snapshot.groups, original, solved)
                revisions = mycad_app.build_tangency_revisions(original, solved)
                operation = ReplayAppend(
                    "drawing.tangency.add",
                    13 if mycad_app.revisions_include_curve_point_ids(revisions) else 12,
                    {"relation": relation.to_mapping(), "revisions": list(revisions)},
                    "local",
                )
                collection.preview_operation(operation)
                return operation, original, solved

            def finish_collection(value: ExecutionResult) -> None:
                if (
                    self._cross_tangency_dialog is not dialog
                    or self._sketch_dialog is not editor
                    or editor is None
                    or editor.canvas.collection_session is not collection
                ):
                    return
                try:
                    if collection.checkpoint() != checkpoint:
                        raise ValidationError("暂存内容已变化，请重新预览。")
                    if value.error is not None or not isinstance(value.value, tuple):
                        raise ValidationError(str(value.error or "相切预览失败。"))
                    operation, original, solved = cast(
                        "tuple[ReplayAppend, tuple[Sketch, ...], tuple[Sketch, ...]]", value.value
                    )
                    self._cross_tangency_preview = _CollectionTangencyPreview(
                        relation, collection, checkpoint, operation
                    )
                    dialog.complete_preview(
                        relation, tangent_preview_summary(relation, original, solved), success=True
                    )
                except (ValidationError, ValueError) as exc:
                    dialog.complete_preview(relation, str(exc), success=False)

            if not unit.submit(
                solve_collection,
                operation="collection-cross-tangency-preview",
                session_id=session_id,
                on_complete=finish_collection,
            ):
                dialog.complete_preview(relation, "几何工作线程忙碌，请重试。", success=False)
            return
        is_draft = editor is not None and editor.draft_sketch_id in (
            relation.first.sketch_id,
            relation.second.sketch_id,
        )
        context: _MixedHandleContext | None = None
        if is_draft and editor is not None:
            canvas = editor.canvas
            previous = canvas.mixed_move
            if previous is not None and (
                not canvas.mixed_move_is_valid or previous.source_revision != revision
            ):
                dialog.complete_preview(relation, "混合草稿已过期，请重新开始。", success=False)
                return
            draft = Sketch(
                editor.draft_sketch_id,
                editor.current_frame(),
                tuple(canvas.entities),
                tuple(canvas.constraints),
                canvas.layer_table,
            )
            original_saved = previous.original_saved if previous else services.kernel.sketches
            context = _MixedHandleContext(
                previous,
                original_saved,
                previous.current_saved if previous else original_saved,
                previous.original_draft if previous else draft,
                draft,
                canvas.background_entities,
                tuple(canvas.pending_cross_tangencies),
                canvas.mixed_move_timeline_with_tangencies(),
                canvas.history_position,
                tuple(canvas.pending_associative_arrays),
                tuple(
                    arrays
                    for _saved, _draft, _pairs, arrays in canvas.mixed_move_timeline_with_arrays()
                ),
                tuple(
                    transforms
                    for _saved, _draft, _pairs, _arrays, transforms in canvas.mixed_move_timeline_with_transforms()
                ),
            )
        elif editor is not None and (
            editor.canvas.mixed_move or editor.canvas.pending_cross_tangencies
        ):
            dialog.complete_preview(
                relation, "请先完成关联草稿，再修改两个已保存草图。", success=False
            )
            return

        def finish(result: ExecutionResult) -> None:
            if (
                self._cross_tangency_dialog is not dialog
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            if loaded.document.revision != revision or tuple(loaded.document.commands) != commands:
                dialog.complete_preview(relation, "文档已改变，请重新预览。", success=False)
                return
            if isinstance(result.value, _DraftTangencyPreview):
                value = result.value
                if editor is None or not self._draft_tangency_context_current(
                    editor, value.context
                ):
                    dialog.complete_preview(relation, "草稿已改变，请重新预览。", success=False)
                    return
                self._cross_tangency_preview = value
                dialog.complete_preview(
                    relation,
                    tangent_preview_summary(
                        relation,
                        (*value.context.current_saved, value.context.draft),
                        (*value.state.current_saved, value.solved_draft),
                    )
                    + "\n确认后先暂存，完成草图时统一提交。",
                    success=True,
                )
                return
            if result.error is not None or not isinstance(result.value, tuple):
                dialog.complete_preview(relation, result.error or "相切预览失败。", success=False)
                return
            if len(cast("tuple[object, ...]", result.value)) != 2:
                dialog.complete_preview(relation, "相切预览结果无效。", success=False)
                return
            original, solved = cast("tuple[tuple[Sketch, ...], tuple[Sketch, ...]]", result.value)
            self._cross_tangency_preview = (relation, original, solved, revision)
            dialog.complete_preview(
                relation, tangent_preview_summary(relation, original, solved), success=True
            )

        action = (
            (
                lambda: self._build_draft_tangency_preview(
                    services, loaded, context, relation, revision, session_id
                )
            )
            if context is not None
            else (lambda: mycad_app.prepare_cross_sketch_tangency(services, relation))
        )
        if not unit.submit(
            action,
            operation="cross-tangency-preview",
            session_id=session_id,
            on_complete=finish,
        ):
            dialog.complete_preview(relation, "几何工作线程忙碌，请重试。", success=False)

    @staticmethod
    def _draft_tangency_context_current(
        editor: SketchEditorDialog, context: _MixedHandleContext
    ) -> bool:
        canvas = editor.canvas
        return (
            canvas.mixed_move == context.previous
            and tuple(canvas.entities) == context.draft.entities
            and tuple(canvas.constraints) == context.draft.constraints
            and canvas.layer_table == context.draft.layers
            and editor.current_frame() == context.draft.frame
            and tuple(canvas.pending_cross_tangencies) == context.pairs
            and tuple(canvas.pending_associative_arrays) == context.arrays
            and canvas.history_position == context.history_position
        )

    def _build_draft_tangency_preview(
        self,
        services: AppServices,
        loaded: LoadedDocument,
        context: _MixedHandleContext,
        relation: CrossSketchTangency,
        revision: int,
        session_id: int,
    ) -> _DraftTangencyPreview:
        saved, draft = mycad_app.prepare_mixed_draft_tangency(
            services,
            context.current_saved,
            context.draft,
            context.pairs,
            relation,
            existing_relations=_staged_committed_tangencies(
                context.original_saved,
                services.kernel.cross_sketch_tangencies,
                tuple(
                    (saved_step, transforms)
                    for (saved_step, _draft, _pairs), transforms in zip(
                        context.history, context.transform_history, strict=True
                    )
                ),
            ),
        )
        source, target = (
            (relation.second, relation.first)
            if relation.first.sketch_id == draft.sketch_id
            else (relation.first, relation.second)
        )

        def endpoint(ref: CrossSketchRef) -> str | SketchGeometryReference:
            return (
                SketchGeometryReference(ref.entity_id, "segment", ref.segment_index)
                if ref.segment_index is not None
                else ref.entity_id
            )

        pair: DraftTangentPair = (endpoint(source), endpoint(target))
        projected: dict[str, SketchEntity] = {}
        background_ids = {item.entity_id for item, _layer in context.background}
        for sketch in saved:
            for entity in sketch.entities:
                if entity.entity_id not in background_ids:
                    continue
                if entity.entity_id in projected:
                    raise ValueError("关联图元身份重复。")
                projected[entity.entity_id] = project_coplanar_entity(
                    entity, sketch.frame, draft.frame
                )
        background = tuple(
            (projected.get(item.entity_id, item), layer) for item, layer in context.background
        )
        previous = context.previous
        state = MixedMoveState(
            previous.transaction_id if previous else uuid4().hex,
            revision,
            context.original_draft,
            context.original_saved,
            saved,
            previous.base_background if previous else context.background,
            background,
            previous.original_cross_tangencies if previous else context.pairs,
            previous.original_associative_arrays if previous else context.arrays,
        )
        steps = tuple((old_saved, old_draft) for old_saved, old_draft, _ in context.history) + (
            (saved, draft),
        )
        pairs_by_step = tuple(pairs for _, _, pairs in context.history) + ((*context.pairs, pair),)
        candidate = mycad_app.stage_mixed_drawing_timeline(
            services,
            loaded,
            context.original_draft,
            context.original_saved,
            steps,
            session_identity=session_id,
            cross_pairs_by_step=pairs_by_step,
            arrays_by_step=(*context.array_history, context.arrays),
            initial_cross_pairs=state.original_cross_tangencies,
            initial_associative_arrays=state.original_associative_arrays,
            rectangle_transforms_by_step=(*context.transform_history, ()),
        )
        try:
            result = candidate.preview(current_session_identity=session_id)
            if result.state != "succeeded":
                raise ValueError(str(result.failure or "混合相切预览失败。"))
        finally:
            candidate.cancel()
        return _DraftTangencyPreview(relation, context, state, draft, pair, revision)

    def _commit_cross_tangency(
        self, dialog: CrossSketchTangencyDialog, session_id: int, relation: CrossSketchTangency
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        preview = self._cross_tangency_preview
        if isinstance(preview, _CollectionTangencyPreview):
            editor = self._sketch_dialog
            try:
                if (
                    editor is None
                    or editor.canvas.collection_session is not preview.session
                    or preview.relation != relation
                    or session_id != self._session_id
                    or preview.session.checkpoint() != preview.checkpoint
                ):
                    raise ValidationError("暂存内容已变化，请重新预览。")
                if not editor.canvas.stage_collection_operation(preview.operation):
                    raise ValidationError(editor.canvas.message)
            except (ValidationError, ValueError) as exc:
                dialog.submission_failed(str(exc))
                return
            self.status_command.setText("对象相切已暂存，可撤销。")
            dialog.accept()
            return
        if isinstance(preview, _DraftTangencyPreview):
            editor = self._sketch_dialog
            if (
                loaded is None
                or editor is None
                or preview.relation != relation
                or session_id != self._session_id
                or loaded.document.revision != preview.revision
                or not self._draft_tangency_context_current(editor, preview.context)
            ):
                dialog.submission_failed("草稿或文档已改变，请重新预览。")
                return
            try:
                editor.canvas.apply_mixed_move(
                    preview.state,
                    preview.solved_draft.entities,
                    constraints=preview.solved_draft.constraints,
                )
                editor.canvas.pending_cross_tangencies.append(preview.pair)
                editor.canvas.message = "对象相切已暂存；完成绘图时提交，可撤销。"
                editor.canvas.changed.emit()
                editor.canvas.update()
            except (KeyError, ValueError) as exc:
                dialog.submission_failed(str(exc))
                return
            dialog.accept()
            return
        if (
            loaded is None
            or services is None
            or unit is None
            or preview is None
            or preview[0] != relation
        ):
            dialog.submission_failed("请重新预览。")
            return
        _, original, solved, revision = preview
        if session_id != self._session_id or loaded.document.revision != revision:
            dialog.submission_failed("文档已改变，请重新预览。")
            return

        def current() -> bool:
            return (
                self._cross_tangency_dialog is dialog
                and self._loaded is loaded
                and self._session_id == session_id
                and loaded.document.revision == revision
            )

        def commit() -> object:
            if not current():
                raise ValidationError("文档已改变，请重新预览。")
            return mycad_app.commit_cross_sketch_tangency(
                services,
                loaded,
                relation,
                session_identity=session_id,
                expected_original=original,
                expected_solved=solved,
                still_current=current,
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._cross_tangency_dialog is not dialog
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            if result.error is not None:
                dialog.submission_failed(result.error)
                return
            if self._sketch_dialog is not None:
                self._sketch_dialog.set_context_sketches(services.kernel.sketches)
            if self.viewport is not None:
                self.viewport.refresh()
            self.status_command.setText("对象相切已写入历史。")
            dialog.accept()

        if not unit.submit(
            commit, operation="cross-tangency-commit", session_id=session_id, on_complete=finish
        ):
            dialog.submission_failed("几何工作线程忙碌，请重试。")

    def _remove_selected_associative_array(self) -> None:
        self._change_selected_associative_array(mode="remove")

    def _edit_selected_associative_array(self) -> None:
        self._change_selected_associative_array(mode="spacing")

    def _resize_selected_associative_array(self) -> None:
        self._change_selected_associative_array(mode="resize")

    def _rotate_selected_associative_array(self) -> None:
        self._change_selected_associative_array(mode="angle")

    def _base_selected_associative_array(self) -> None:
        self._change_selected_associative_array(mode="base")

    def _offset_selected_associative_member(self) -> None:
        self._change_selected_associative_array(mode="member_offset")

    def _rotate_associative_member(self) -> None:
        self._change_selected_associative_array(mode="member_rotation")

    def _replace_associative_member(self) -> None:
        editor = self._sketch_dialog
        if editor is not None and len(editor.canvas.selected_entity_ids) > 1:
            self._replace_associative_cell_members()
            return
        self._change_selected_associative_array(mode="member_replace")

    def _replace_associative_cell_members(self) -> None:
        loaded, services, unit, editor = (
            self._loaded,
            self._services,
            self.execution_unit,
            self._sketch_dialog,
        )
        if loaded is None or services is None or unit is None or editor is None:
            return
        canvas = editor.canvas
        if canvas.collection_session is not None:
            self.status_command.setText("请先完成或取消当前草稿，再修改关联阵列。")
            return
        if (
            canvas.has_active_edit_gesture
            or canvas.has_pending_geometry
            or canvas.mixed_move
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
        ):
            self.status_command.setText("请先完成或撤销当前草稿操作。")
            return
        selected = frozenset(canvas.selected_entity_ids)
        if any(entity.entity_id in selected for entity in canvas.entities):
            self.status_command.setText("请选择已保存的阵列副本。")
            return
        matches: list[tuple[AssociativeRectArray, tuple[ArrayMember, ...]]] = []
        for array in services.kernel.associative_arrays:
            members = tuple(
                member for member in array.members if member.target.entity_id in selected
            )
            if frozenset(member.target.entity_id for member in members) == selected:
                positions = {(member.row, member.column) for member in members}
                if len(positions) == 1 and len(members) == len(array.sources):
                    matches.append((array, members))
        if len(matches) != 1:
            self.status_command.setText("请选择同一阵列单元的全部副本。")
            return
        array, members = matches[0]
        sketches = services.kernel.sketches
        if any(
            sum(entity.entity_id == identity for sketch in sketches for entity in sketch.entities)
            != 1
            for identity in selected
        ):
            self.status_command.setText("所选图元身份不唯一。")
            return
        if any(
            member.erased_index is not None or member.offset_mm != (0, 0) or member.rotation_deg
            for member in members
        ):
            self.status_command.setText("请先重置该单元的位置及旋转覆盖。")
            return
        candidates = [
            (sketch, entity)
            for sketch in sketches
            for entity in sketch.entities
            if entity.entity_id not in selected
            and sketch.layers.get(entity.layer_name).displayed
            and not sketch.layers.get(entity.layer_name).locked
            and canvas.entity_point_references(entity)
        ]
        maximum = min(
            len(candidates), 10000 - len(array.members) - len(array.extra_outputs) + len(members)
        )
        if maximum < 1:
            self.status_command.setText("没有可用的替换来源。")
            return

        def collection_started() -> bool:
            if canvas.collection_session is None:
                return False
            self.status_command.setText("暂存内容已变化，请先完成或取消草稿。")
            return True

        count, accepted = QInputDialog.getInt(
            self, "替换阵列单元", "替换来源图元数量", min(len(members), maximum), 1, maximum
        )
        if not accepted or collection_started():
            return
        if not 1 <= count <= maximum:
            self.status_command.setText("替换来源图元数量无效。")
            return
        replaced_members, erased_members = members[:count], members[count:]
        chosen_sources: list[tuple[Sketch, SketchEntity]] = []
        for index in range(count):
            available = [
                (sketch, entity)
                for sketch, entity in candidates
                if (sketch, entity) not in chosen_sources
            ]
            labels = [
                f"{i + 1}: {entity.entity_id[:8]} {type(entity).__name__} [{entity.layer_name}]"
                for i, (_sketch, entity) in enumerate(available)
            ]
            if not labels:
                self.status_command.setText("没有足够的替换来源。")
                return
            chosen, accepted = QInputDialog.getItem(
                self, "替换阵列单元", f"选择第 {index + 1} 个副本的替换来源", labels, 0, False
            )
            if not accepted or collection_started() or chosen not in labels:
                return
            chosen_sources.append(available[labels.index(chosen)])
        first_sketch, first_entity = chosen_sources[0]
        first_anchor = canvas.entity_point_references(first_entity)[0][1]
        default = editor.current_frame().world_to_local(
            first_sketch.frame.local_to_world(first_anchor)
        )
        value, accepted = QInputDialog.getText(
            self, "替换阵列单元", "替换来源共同基点 U,V", text=f"{default[0]!r},{default[1]!r}"
        )
        if not accepted or collection_started():
            return
        try:
            point = tuple(float(part.strip()) for part in value.split(","))
            if len(point) != 2 or not all(isfinite(part) for part in point):
                raise ValueError
            changes: dict[ArrayEntityRef, ArrayReplacement] = {}
            for member, (replacement_sketch, replacement_entity) in zip(
                replaced_members, chosen_sources[: len(replaced_members)], strict=True
            ):
                anchor = canvas.entity_point_references(replacement_entity)[0][1]
                base = replacement_sketch.frame.world_to_local(
                    editor.current_frame().local_to_world((point[0], point[1]))
                )
                changes[member.target] = ArrayReplacement(
                    ArrayEntityRef(replacement_sketch.sketch_id, replacement_entity.entity_id),
                    (base[0] - anchor[0], base[1] - anchor[1]),
                    anchor_source=members[0].source,
                )
            extras: list[ArrayExtraOutput] = []
            for replacement_sketch, replacement_entity in chosen_sources[len(members) :]:
                anchor = canvas.entity_point_references(replacement_entity)[0][1]
                base = replacement_sketch.frame.world_to_local(
                    editor.current_frame().local_to_world((point[0], point[1]))
                )
                extras.append(
                    ArrayExtraOutput(
                        ArrayEntityRef(replacement_sketch.sketch_id, replacement_entity.entity_id),
                        ArrayEntityRef(members[0].target.sketch_id, uuid4().hex),
                        members[0].source,
                        members[0].row,
                        members[0].column,
                        (base[0] - anchor[0], base[1] - anchor[1]),
                    )
                )
        except (KeyError, IndexError, ValueError):
            self.status_command.setText("替换基点或源图元无效。")
            return
        if canvas.collection_session is not None:
            self.status_command.setText("暂存内容已变化，请先完成或取消草稿。")
            return
        revision, session_id = loaded.document.revision, self._session_id
        editor.setEnabled(False)

        def commit() -> object:
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or loaded.document.revision != revision
                or canvas.collection_session is not None
                or array not in services.kernel.associative_arrays
                or self._sketch_dialog is not editor
                or frozenset(canvas.selected_entity_ids) != selected
            ):
                raise ValidationError("文档或阵列已变化，请重新选择。")
            params: dict[str, object] = {
                "array_id": array.array_id,
                "members": [
                    {"target": target.to_mapping(), "replacement": replacement.to_mapping()}
                    for target, replacement in changes.items()
                ],
            }
            if erased_members:
                params["erase_members"] = [member.target.to_mapping() for member in erased_members]
            if extras:
                params["extra_outputs"] = [output.to_mapping() for output in extras]
            return loaded.bus.execute(
                "drawing.array.replace",
                params,
                "local",
                version=9
                if mycad_app.revisions_require_attachment_protection(
                    services,
                    tuple({"sketch_id": ref.sketch_id} for ref in changes),
                )
                else 6
                if extras
                else 5
                if erased_members
                else 4,
            )

        def finish(result: ExecutionResult) -> None:
            editor.setEnabled(True)
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or self._sketch_dialog is not editor
            ):
                return
            if result.error is not None:
                self.status_command.setText(f"阵列操作失败：{result.error}")
                return
            editor.set_context_sketches(services.kernel.sketches)
            self._sync_drawing_layers()
            self.status_command.setText("已替换阵列单元；可撤销。")

        if not unit.submit(
            commit, operation="array-cell-replace", session_id=session_id, on_complete=finish
        ):
            editor.setEnabled(True)
            self.status_command.setText("几何工作线程忙碌，请重试。")

    def _reset_associative_offsets(self) -> None:
        self._change_selected_associative_array(mode="reset_offsets")

    def _reset_associative_overrides(self) -> None:
        self._change_selected_associative_array(mode="reset_overrides")

    def _change_selected_associative_array(self, *, mode: str) -> None:
        loaded, services, unit, editor = (
            self._loaded,
            self._services,
            self.execution_unit,
            self._sketch_dialog,
        )
        if loaded is None or services is None or unit is None or editor is None:
            self.status_command.setText("请先打开独立二维草稿并选择阵列源或副本。")
            return
        canvas = editor.canvas
        if canvas.collection_session is not None:
            self.status_command.setText("请先完成或取消当前草稿，再修改关联阵列。")
            return

        def collection_started() -> bool:
            if canvas.collection_session is None:
                return False
            self.status_command.setText("暂存内容已变化，请先完成或取消草稿。")
            return True

        if (
            canvas.has_active_edit_gesture
            or canvas.has_pending_geometry
            or canvas.mixed_move
            or canvas.pending_cross_tangencies
            or canvas.pending_associative_arrays
        ):
            self.status_command.setText("请先完成或撤销当前草稿操作。")
            return
        selected = canvas.selected_entity_ids
        if not selected or (
            len(selected) != 1 and mode not in {"member_offset", "member_rotation"}
        ):
            self.status_command.setText("请选择已保存的关联阵列源或副本。")
            return
        identity = next(iter(selected))
        if any(entity.entity_id in selected for entity in canvas.entities):
            self.status_command.setText("请选择身份唯一的已保存阵列源或副本。")
            return
        owners = sum(
            entity.entity_id == identity
            for sketch in services.kernel.sketches
            for entity in sketch.entities
        )
        if mode in {"member_offset", "member_rotation"} and any(
            sum(
                entity.entity_id == chosen
                for sketch in services.kernel.sketches
                for entity in sketch.entities
            )
            != 1
            for chosen in selected
        ):
            self.status_command.setText("所选阵列副本身份不唯一或已变化。")
            return
        arrays = [
            array
            for array in services.kernel.associative_arrays
            if any(source.entity_id == identity for source in array.sources)
            or any(member.target.entity_id == identity for member in array.members)
            or any(output.target.entity_id == identity for output in array.extra_outputs)
        ]
        batch_owners: dict[ArrayEntityRef, AssociativeRectArray] = {}
        if mode in {"member_offset", "member_rotation"}:
            for candidate in services.kernel.associative_arrays:
                for item in (*candidate.members, *candidate.extra_outputs):
                    if item.target.entity_id in selected:
                        if item.target in batch_owners:
                            self.status_command.setText("阵列副本身份不唯一。")
                            return
                        batch_owners[item.target] = candidate
        cross_array = len({owner.array_id for owner in batch_owners.values()}) > 1
        if cross_array:
            if len(batch_owners) != len(selected):
                self.status_command.setText("请选择身份唯一的已保存阵列副本。")
                return
            arrays = list({owner.array_id: owner for owner in batch_owners.values()}.values())
        if not cross_array and mode in {
            "member_offset",
            "member_rotation",
            "member_replace",
            "reset_offsets",
            "reset_overrides",
        }:
            owning = [
                candidate
                for candidate in arrays
                if (
                    mode not in {"member_offset", "member_rotation"}
                    and (
                        any(member.target.entity_id == identity for member in candidate.members)
                        or (
                            mode in {"reset_offsets", "reset_overrides"}
                            and any(
                                output.target.entity_id == identity
                                for output in candidate.extra_outputs
                            )
                        )
                    )
                )
                or (
                    mode in {"member_offset", "member_rotation"}
                    and selected.issubset(
                        {member.target.entity_id for member in candidate.members}
                        | {output.target.entity_id for output in candidate.extra_outputs}
                    )
                )
            ]
            erased = [
                candidate
                for candidate in arrays
                if any(member.erased_index is not None for member in candidate.members)
            ]
            if mode == "reset_overrides" and erased:
                arrays = erased
            elif owning:
                arrays = owning
            elif mode in {"member_offset", "member_rotation", "member_replace"}:
                self.status_command.setText("请选择一个已保存的阵列副本。")
                return
        if len(arrays) > 1 and not cross_array:
            self.status_command.setText("所选图元属于多个关联阵列；请选择唯一的阵列副本。")
            return
        if owners != 1 or (len(arrays) != 1 and not cross_array):
            self.status_command.setText("所选对象不是唯一的已保存关联阵列源或副本。")
            return
        array = arrays[0]
        revision, session_id = loaded.document.revision, self._session_id
        row_spacing, column_spacing = array.row_spacing, array.column_spacing
        rows, columns = array.rows, array.columns
        angle = array.angle_deg
        selected_snapshot = frozenset(canvas.selected_entity_ids)
        draft_snapshot = (
            tuple(canvas.entities),
            tuple(canvas.constraints),
            canvas.layer_table,
            canvas.active_layer_name,
            canvas.history_position,
        )
        base_point: ArrayBasePoint | None = None
        reset_base_point = False
        member_offset: tuple[float, float] | None = None
        member_rotations: dict[ArrayEntityRef, tuple[float, tuple[float, float]]] = {}
        member_replacement: ArrayReplacement | None = None
        selected_member = next(
            (member for member in array.members if member.target.entity_id == identity), None
        )
        selected_offsets = tuple(
            item
            for owner in arrays
            for item in (*owner.members, *owner.extra_outputs)
            if item.target.entity_id in selected
        )
        if mode == "member_offset":
            if len(selected_offsets) != len(selected):
                self.status_command.setText("请选择一个已保存的阵列副本。")
                return
            initial = selected_offsets[0].offset_mm
            initial_text = (
                f"{initial[0]!r},{initial[1]!r}"
                if all(item.offset_mm == initial for item in selected_offsets)
                else ""
            )
            value, accepted = QInputDialog.getText(
                self,
                "修改阵列成员偏移",
                "工作平面偏移 ΔU,ΔV",
                text=initial_text,
            )
            if not accepted:
                return
            try:
                coordinates = tuple(float(part.strip()) for part in value.split(","))
                if len(coordinates) != 2 or not all(isfinite(part) for part in coordinates):
                    raise ValueError
                member_offset = (coordinates[0], coordinates[1])
            except ValueError:
                self.status_command.setText("请输入有限的二维偏移，格式为 ΔU,ΔV。")
                return
            if all(member_offset == item.offset_mm for item in selected_offsets):
                self.status_command.setText("阵列成员偏移未变化。")
                return
        if mode == "member_rotation":
            if len(selected_offsets) != len(selected):
                self.status_command.setText("请选择同一阵列中的已保存副本。")
                return
            initial_angle = selected_offsets[0].rotation_deg
            angle_text = (
                f"{initial_angle!r}"
                if all(item.rotation_deg == initial_angle for item in selected_offsets)
                else ""
            )
            value, accepted = QInputDialog.getText(
                self, "旋转阵列成员", "旋转角度（度）", text=angle_text
            )
            if not accepted:
                return
            try:
                rotation = float(value.strip())
                if not isfinite(rotation):
                    raise ValueError
            except ValueError:
                self.status_command.setText("请输入有限的旋转角度。")
                return
            centers: dict[ArrayEntityRef, tuple[Sketch, tuple[float, float]]] = {}
            if rotation != 0:
                try:
                    display_centers: list[tuple[float, float]] = []
                    for item in selected_offsets:
                        anchor = array_member_rotation_anchor(
                            batch_owners[item.target], item, services.kernel.sketches
                        )
                        target_sketch = next(
                            (
                                sketch
                                for sketch in services.kernel.sketches
                                if sketch.sketch_id == item.target.sketch_id
                            ),
                            None,
                        )
                        if target_sketch is None:
                            raise ValueError("阵列目标草图已变化。")
                        centers[item.target] = (target_sketch, anchor)
                        current_center = (
                            anchor[0] + item.rotation_center_offset_mm[0],
                            anchor[1] + item.rotation_center_offset_mm[1],
                        )
                        display_centers.append(
                            editor.current_frame().world_to_local(
                                target_sketch.frame.local_to_world(current_center)
                            )
                        )
                except ValueError as exc:
                    self.status_command.setText(str(exc))
                    return
                display_center = display_centers[0]
                center_text = (
                    f"{display_center[0]!r},{display_center[1]!r}"
                    if all(center == display_center for center in display_centers)
                    else ""
                )
                value, accepted = QInputDialog.getText(
                    self,
                    "旋转阵列成员",
                    "旋转中心坐标 U,V",
                    text=center_text,
                )
                if not accepted:
                    return
                try:
                    coordinates = tuple(float(part.strip()) for part in value.split(","))
                    if len(coordinates) != 2 or not all(isfinite(part) for part in coordinates):
                        raise ValueError
                    world_center = editor.current_frame().local_to_world(
                        (coordinates[0], coordinates[1])
                    )
                    for ref, (target_sketch, anchor) in centers.items():
                        target_center = target_sketch.frame.world_to_local(world_center)
                        member_rotations[ref] = (
                            rotation,
                            (target_center[0] - anchor[0], target_center[1] - anchor[1]),
                        )
                except ValueError:
                    self.status_command.setText("请输入有限的旋转中心，格式为 U,V。")
                    return
            else:
                member_rotations = {item.target: (0.0, (0.0, 0.0)) for item in selected_offsets}
            if all(
                member_rotations[item.target] == (item.rotation_deg, item.rotation_center_offset_mm)
                for item in selected_offsets
            ):
                self.status_command.setText("阵列成员旋转未变化。")
                return
        if mode == "member_replace":
            assert selected_member is not None
            replacement_candidates = [
                (sketch, entity)
                for sketch in services.kernel.sketches
                for entity in sketch.entities
                if entity.entity_id != identity
                and sketch.layers.get(entity.layer_name).displayed
                and not sketch.layers.get(entity.layer_name).locked
                and canvas.entity_point_references(entity)
            ]
            if not replacement_candidates:
                self.status_command.setText("没有可用的替换来源。")
                return
            entity_labels = {
                "PointEntity": "点",
                "LineEntity": "直线",
                "PolylineEntity": "多段线",
                "CircleEntity": "圆",
                "ArcEntity": "圆弧",
                "RectangleEntity": "矩形",
                "SplineEntity": "样条",
            }
            labels = [
                f"{index + 1}: {entity.entity_id[:8]} {entity_labels.get(type(entity).__name__, '图元')} [{entity.layer_name}]"
                for index, (_sketch, entity) in enumerate(replacement_candidates)
            ]
            chosen, accepted = QInputDialog.getItem(
                self, "替换阵列成员", "替换来源", labels, 0, False
            )
            if not accepted or chosen not in labels:
                return
            replacement_sketch, replacement_entity = replacement_candidates[labels.index(chosen)]
            anchor = canvas.entity_point_references(replacement_entity)[0][1]
            default_point = editor.current_frame().world_to_local(
                replacement_sketch.frame.local_to_world(anchor)
            )
            value, accepted = QInputDialog.getText(
                self,
                "替换阵列成员",
                "替换来源基点坐标 U,V",
                text=f"{default_point[0]!r},{default_point[1]!r}",
            )
            if not accepted:
                return
            try:
                coordinates = tuple(float(part.strip()) for part in value.split(","))
                if len(coordinates) != 2 or not all(isfinite(part) for part in coordinates):
                    raise ValueError
                local_point = replacement_sketch.frame.world_to_local(
                    editor.current_frame().local_to_world((coordinates[0], coordinates[1]))
                )
                member_replacement = ArrayReplacement(
                    ArrayEntityRef(replacement_sketch.sketch_id, replacement_entity.entity_id),
                    (local_point[0] - anchor[0], local_point[1] - anchor[1]),
                )
            except ValueError:
                self.status_command.setText("请输入有限的替换基点坐标，格式为 U,V。")
                return
            if member_replacement == selected_member.replacement:
                self.status_command.setText("阵列成员替换未变化。")
                return
        if mode == "reset_offsets" and all(
            item.offset_mm == (0, 0) for item in (*array.members, *array.extra_outputs)
        ):
            self.status_command.setText("阵列没有需要重置的位置偏移。")
            return
        if (
            mode == "reset_overrides"
            and not array.extra_outputs
            and all(
                member.offset_mm == (0, 0)
                and member.rotation_deg == 0
                and member.erased_index is None
                and member.replacement is None
                for member in array.members
            )
        ):
            self.status_command.setText("阵列没有需要重置的成员覆盖。")
            return
        if mode == "base":
            choice, accepted = QInputDialog.getItem(
                self, "修改矩形阵列基点", "基点方式", ["坐标", "源关键点", "恢复默认"], 0, False
            )
            if not accepted:
                return
            if choice == "坐标":
                value, accepted = QInputDialog.getText(self, "修改矩形阵列基点", "工作平面坐标 U,V")
                if not accepted:
                    return
                try:
                    coordinates = tuple(float(part.strip()) for part in value.split(","))
                    if len(coordinates) != 2 or not all(isfinite(part) for part in coordinates):
                        raise ValueError
                    base_point = ArrayBasePoint(point_mm=(coordinates[0], coordinates[1]))
                except ValueError:
                    self.status_command.setText("请输入有限的二维坐标，格式为 U,V。")
                    return
            elif choice == "源关键点":
                candidates: list[
                    tuple[ArrayEntityRef, SketchGeometryReference, tuple[float, float]]
                ] = []
                for source in array.sources:
                    for sketch in services.kernel.sketches:
                        if sketch.sketch_id != source.sketch_id:
                            continue
                        for entity in sketch.entities:
                            if entity.entity_id == source.entity_id:
                                candidates.extend(
                                    (
                                        source,
                                        reference,
                                        array.frame.world_to_local(
                                            sketch.frame.local_to_world(point)
                                        ),
                                    )
                                    for reference, point in canvas.entity_point_references(entity)
                                )
                if not candidates:
                    self.status_command.setText("阵列源没有可用关键点。")
                    return
                labels = [
                    f"{index + 1}: {source.entity_id[:8]} {reference.kind}"
                    f"{'' if reference.index is None else f' {reference.index}'} ({point[0]:.8g}, {point[1]:.8g})"
                    for index, (source, reference, point) in enumerate(candidates)
                ]
                selected_key, accepted = QInputDialog.getItem(
                    self, "修改矩形阵列基点", "源关键点", labels, 0, False
                )
                if not accepted or selected_key not in labels:
                    return
                source, reference, _point = candidates[labels.index(selected_key)]
                base_point = ArrayBasePoint(source=source, reference=reference)
            elif choice == "恢复默认":
                reset_base_point = True
            else:
                return
            if (reset_base_point and array.base_point is None) or base_point == array.base_point:
                self.status_command.setText("阵列基点未变化。")
                return
        if mode == "angle":
            value, accepted = QInputDialog.getText(
                self, "修改矩形阵列", "方向角（度）", text=repr(angle)
            )
            if not accepted:
                return
            try:
                angle = float(value.strip())
                if not isfinite(angle):
                    raise ValueError
            except ValueError:
                self.status_command.setText("请输入有限的阵列方向角。")
                return
            if angle == array.angle_deg:
                self.status_command.setText("阵列方向未变化。")
                return
        if mode == "resize":
            rows, accepted = QInputDialog.getInt(self, "修改矩形阵列", "行数", rows, 1, 1000)
            if not accepted or collection_started():
                return
            columns, accepted = QInputDialog.getInt(self, "修改矩形阵列", "列数", columns, 1, 1000)
            if not accepted or collection_started():
                return
            if not 2 <= rows * columns <= 1000 or (rows * columns - 1) * len(array.sources) > 10000:
                self.status_command.setText("阵列位置须为 2 到 1000 个，副本不能超过 10000 个。")
                return
            if rows == array.rows and columns == array.columns:
                self.status_command.setText("阵列数量未变化。")
                return

        def request_spacing(label: str, current: float) -> float | None:
            value, accepted = QInputDialog.getText(self, "修改矩形阵列", label, text=repr(current))
            if not accepted or collection_started():
                return None
            try:
                result = float(value.strip())
                if not isfinite(result) or abs(result) <= 1e-9:
                    raise ValueError
            except ValueError:
                self.status_command.setText("请输入有限且非零的阵列间距。")
                return None
            return result

        if (mode == "spacing" and array.rows > 1) or (
            mode == "resize" and array.rows == 1 and rows > 1
        ):
            value = request_spacing("行间距 ΔV", row_spacing)
            if value is None:
                return
            row_spacing = value
        if (mode == "spacing" and array.columns > 1) or (
            mode == "resize" and array.columns == 1 and columns > 1
        ):
            value = request_spacing("列间距 ΔU", column_spacing)
            if value is None:
                return
            column_spacing = value
        if (
            mode == "spacing"
            and row_spacing == array.row_spacing
            and column_spacing == array.column_spacing
        ):
            self.status_command.setText("阵列间距未变化。")
            return

        resized: AssociativeRectArray | None = None
        if mode == "resize":
            target_sketches = {member.target.sketch_id for member in array.members}
            if len(target_sketches) != 1:
                self.status_command.setText("暂不支持跨目标草图的阵列数量修改。")
                return
            target_sketch = next(iter(target_sketches))
            existing = {
                (member.source, member.row, member.column): member for member in array.members
            }
            members = tuple(
                existing.get((source, row, column))
                or ArrayMember(source, ArrayEntityRef(target_sketch, uuid4().hex), row, column)
                for row in range(rows)
                for column in range(columns)
                if row or column
                for source in array.sources
            )
            try:
                resized = replace(
                    array,
                    rows=rows,
                    columns=columns,
                    row_spacing=row_spacing,
                    column_spacing=column_spacing,
                    members=members,
                    extra_outputs=tuple(
                        output
                        for output in array.extra_outputs
                        if output.row < rows and output.column < columns
                    ),
                )
            except ValueError as exc:
                self.status_command.setText(str(exc))
                return

        if canvas.collection_session is not None:
            self.status_command.setText("暂存内容已变化，请先完成或取消草稿。")
            return

        def remove() -> object:
            if (
                self._loaded is not loaded
                or self._session_id != session_id
                or loaded.document.revision != revision
                or canvas.collection_session is not None
                or any(owner not in services.kernel.associative_arrays for owner in arrays)
                or (
                    mode
                    in {
                        "base",
                        "member_offset",
                        "member_rotation",
                        "member_replace",
                        "reset_offsets",
                        "reset_overrides",
                    }
                    and (
                        self._sketch_dialog is not editor
                        or frozenset(canvas.selected_entity_ids) != selected_snapshot
                        or (
                            tuple(canvas.entities),
                            tuple(canvas.constraints),
                            canvas.layer_table,
                            canvas.active_layer_name,
                            canvas.history_position,
                        )
                        != draft_snapshot
                    )
                )
            ):
                raise ValidationError("文档或阵列已变化，请重新选择。")
            if resized is not None:
                return loaded.bus.execute(
                    "drawing.array.resize",
                    {"array": resized.to_mapping()},
                    confirmed_by="local",
                    version=16
                    if mycad_app.revisions_require_attachment_protection(
                        services,
                        tuple(
                            {"sketch_id": ref.sketch_id}
                            for ref in (
                                *array.sources,
                                *(member.target for member in array.members),
                                *(member.target for member in resized.members),
                                *(output.target for output in array.extra_outputs),
                            )
                        ),
                    )
                    else 15
                    if any(output.rotation_deg != 0 for output in resized.extra_outputs)
                    else 14
                    if any(output.offset_mm != (0, 0) for output in resized.extra_outputs)
                    else 13
                    if resized.extra_outputs != array.extra_outputs
                    else 12
                    if resized.extra_outputs
                    else 11
                    if any(
                        member.replacement is not None
                        and member.replacement.anchor_source is not None
                        for member in resized.members
                    )
                    else 10
                    if has_interleaved_array_dependencies(
                        tuple(
                            resized if item.array_id == resized.array_id else item
                            for item in services.kernel.associative_arrays
                        )
                    )
                    else 9
                    if has_internal_replacements(resized)
                    else 8
                    if any(member.replacement is not None for member in resized.members)
                    else 7
                    if any(member.erased_neighbors is not None for member in resized.members)
                    else 6
                    if any(member.erased_index is not None for member in resized.members)
                    else 5
                    if any(member.rotation_deg != 0 for member in resized.members)
                    else 4
                    if any(member.offset_mm != (0, 0) for member in resized.members)
                    else 3
                    if resized.base_point is not None
                    else 2
                    if resized.angle_deg != 0
                    else 1,
                )
            if mode == "spacing":
                return loaded.bus.execute(
                    "drawing.array.update",
                    {
                        "array_id": array.array_id,
                        "row_spacing": row_spacing,
                        "column_spacing": column_spacing,
                    },
                    confirmed_by="local",
                    version=1,
                )
            if mode == "angle":
                return loaded.bus.execute(
                    "drawing.array.update",
                    {
                        "array_id": array.array_id,
                        "row_spacing": row_spacing,
                        "column_spacing": column_spacing,
                        "angle_deg": angle,
                    },
                    confirmed_by="local",
                    version=2,
                )
            if mode == "base":
                params: dict[str, object] = {
                    "array_id": array.array_id,
                    "row_spacing": row_spacing,
                    "column_spacing": column_spacing,
                }
                if reset_base_point:
                    params["reset_base_point"] = True
                elif base_point is not None:
                    params["base_point"] = base_point.to_mapping()
                return loaded.bus.execute(
                    "drawing.array.update", params, confirmed_by="local", version=3
                )
            if cross_array and mode in {"member_offset", "member_rotation"}:
                groups: list[dict[str, object]] = []
                for owner in arrays:
                    items = [
                        item for item in selected_offsets if batch_owners[item.target] == owner
                    ]
                    members: list[dict[str, object]] = []
                    for item in items:
                        if mode == "member_offset":
                            assert member_offset is not None
                            members.append(
                                {
                                    "target": item.target.to_mapping(),
                                    "offset_mm": list(member_offset),
                                }
                            )
                        else:
                            rotation, center = member_rotations[item.target]
                            members.append(
                                {
                                    "target": item.target.to_mapping(),
                                    "angle_deg": rotation,
                                    "center_offset_mm": list(center),
                                }
                            )
                    groups.append({"array_id": owner.array_id, "members": members})
                return loaded.bus.execute(
                    "drawing.array.batch_override",
                    {
                        "operation": "offset" if mode == "member_offset" else "rotate",
                        "groups": groups,
                    },
                    confirmed_by="local",
                    version=2
                    if mycad_app.revisions_require_attachment_protection(
                        services,
                        tuple({"sketch_id": item.target.sketch_id} for item in selected_offsets),
                    )
                    else 1,
                )
            if mode == "member_offset":
                assert selected_offsets and member_offset is not None
                return loaded.bus.execute(
                    "drawing.array.offset",
                    {
                        "array_id": array.array_id,
                        "members": [
                            {
                                "target": item.target.to_mapping(),
                                "offset_mm": list(member_offset),
                            }
                            for item in selected_offsets
                        ],
                    },
                    confirmed_by="local",
                    version=2
                    if any(isinstance(item, ArrayExtraOutput) for item in selected_offsets)
                    else 1,
                )
            if mode == "member_rotation":
                assert member_rotations
                return loaded.bus.execute(
                    "drawing.array.rotate",
                    {
                        "array_id": array.array_id,
                        "members": [
                            {
                                "target": item.target.to_mapping(),
                                "angle_deg": member_rotations[item.target][0],
                                "center_offset_mm": list(member_rotations[item.target][1]),
                            }
                            for item in selected_offsets
                        ],
                    },
                    confirmed_by="local",
                    version=3
                    if mycad_app.revisions_require_attachment_protection(
                        services,
                        tuple({"sketch_id": item.target.sketch_id} for item in selected_offsets),
                    )
                    else 2
                    if any(isinstance(item, ArrayExtraOutput) for item in selected_offsets)
                    else 1,
                )
            if mode == "member_replace":
                assert selected_member is not None and member_replacement is not None
                replacement_array = replace(
                    array,
                    members=tuple(
                        replace(member, replacement=member_replacement)
                        if member.target == selected_member.target
                        else member
                        for member in array.members
                    ),
                )
                candidate_arrays = tuple(
                    replacement_array if item.array_id == array.array_id else item
                    for item in services.kernel.associative_arrays
                )
                return loaded.bus.execute(
                    "drawing.array.replace",
                    {
                        "array_id": array.array_id,
                        "members": [
                            {
                                "target": selected_member.target.to_mapping(),
                                "replacement": member_replacement.to_mapping(),
                            }
                        ],
                    },
                    confirmed_by="local",
                    version=9
                    if mycad_app.revisions_require_attachment_protection(
                        services, ({"sketch_id": selected_member.target.sketch_id},)
                    )
                    else 3
                    if has_interleaved_array_dependencies(candidate_arrays)
                    else 2
                    if has_internal_replacements(array)
                    or member_replacement.source in {member.target for member in array.members}
                    else 1,
                )
            if mode == "reset_offsets":
                return loaded.bus.execute(
                    "drawing.array.offset",
                    {"array_id": array.array_id, "reset_all": True},
                    confirmed_by="local",
                    version=2
                    if any(output.offset_mm != (0, 0) for output in array.extra_outputs)
                    else 1,
                )
            if mode == "reset_overrides":
                reset_sketches = tuple(
                    {"sketch_id": ref.sketch_id}
                    for ref in (
                        *array.sources,
                        *(member.target for member in array.members),
                        *(output.target for output in array.extra_outputs),
                    )
                )
                return loaded.bus.execute(
                    "drawing.array.reset",
                    {"array_id": array.array_id},
                    confirmed_by="local",
                    version=5
                    if mycad_app.revisions_require_attachment_protection(services, reset_sketches)
                    else 4
                    if array.extra_outputs
                    else 3
                    if any(member.replacement is not None for member in array.members)
                    else 2
                    if any(member.erased_index is not None for member in array.members)
                    else 1,
                )
            return loaded.bus.execute(
                "drawing.array.remove", {"array_id": array.array_id}, confirmed_by="local"
            )

        def finish(result: ExecutionResult) -> None:
            if self._loaded is not loaded or self._session_id != session_id:
                return
            if result.error is not None:
                self.status_command.setText(f"阵列操作失败：{result.error}")
                return
            if self._sketch_dialog is editor:
                editor.set_context_sketches(services.kernel.sketches)
                self._sync_drawing_layers()
            self.status_command.setText(
                {
                    "spacing": "已修改矩形阵列间距；可撤销。",
                    "resize": "已修改矩形阵列数量；可撤销。",
                    "angle": "已修改矩形阵列方向；可撤销。",
                    "base": "已修改矩形阵列基点；可撤销。",
                    "member_offset": "已修改阵列成员位置偏移；可撤销。",
                    "member_rotation": "已旋转阵列成员；可撤销。",
                    "member_replace": "已替换阵列成员；可撤销。",
                    "reset_offsets": "已重置阵列成员位置偏移；可撤销。",
                    "reset_overrides": "已重置阵列成员覆盖；可撤销。",
                    "remove": "已解除矩形阵列关联，副本保留；可撤销。",
                }[mode]
            )

        if not unit.submit(
            remove,
            operation=f"array-{mode}",
            session_id=session_id,
            on_complete=finish,
        ):
            self.status_command.setText("几何工作线程忙碌，请重试。")

    def _remove_cross_tangency(
        self, dialog: CrossSketchTangencyDialog, session_id: int, identity: str
    ) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        editor = self._sketch_dialog
        collection = editor.canvas.collection_session if editor is not None else None
        if editor is not None and collection is not None:
            canvas = editor.canvas
            try:
                snapshot = collection.snapshot
                relation = next(
                    (item for item in snapshot.cross_tangencies if item.relation_id == identity),
                    None,
                )
                if relation is None or dialog.relations_by_id.get(identity) != relation:
                    raise ValidationError("暂存相切关系已变化，请重新打开。")
                draft = next(
                    item for item in snapshot.sketches if item.sketch_id == editor.draft_sketch_id
                )
                saved = tuple(
                    item for item in snapshot.sketches if item.sketch_id != draft.sketch_id
                )
                pairs = tuple(canvas.pending_cross_tangencies)
                pending_relations = mycad_app.draft_cross_relations(saved, draft, pairs)
                retained = [
                    pair
                    for pending, pair in zip(pending_relations, pairs, strict=True)
                    if pending.relation_id != identity
                ]
                if not canvas.stage_collection_operation(
                    ReplayAppend("drawing.tangency.remove", 1, {"relation_id": identity}, "local")
                ):
                    raise ValidationError(canvas.message)
                canvas.pending_cross_tangencies = retained
                self.status_command.setText("对象相切关系已暂存移除，可撤销。")
                dialog.accept()
            except (ValidationError, ValueError, StopIteration) as exc:
                dialog.submission_failed(str(exc))
            return
        if loaded is not None and services is not None and editor is not None:
            canvas = editor.canvas
            mixed = canvas.mixed_move
            if mixed is not None and (
                not canvas.mixed_move_is_valid or mixed.source_revision != loaded.document.revision
            ):
                dialog.submission_failed("混合草稿已过期，请重新开始。")
                return
            draft = Sketch(
                editor.draft_sketch_id,
                editor.current_frame(),
                tuple(canvas.entities),
                tuple(canvas.constraints),
                canvas.layer_table,
            )
            saved = mixed.current_saved if mixed else services.kernel.sketches
            try:
                pairs = tuple(canvas.pending_cross_tangencies)
                staged = mycad_app.draft_cross_relations(saved, draft, pairs)
                for relation, pair in zip(staged, pairs, strict=True):
                    if relation.relation_id == identity:
                        if dialog.relations_by_id.get(
                            identity
                        ) != relation or not canvas.remove_pending_cross_tangency(pair):
                            raise ValueError("暂存相切关系已变化，请重新打开。")
                        dialog.accept()
                        return
            except (ValueError, ValidationError) as exc:
                dialog.submission_failed(str(exc))
                return
        if self._sketch_dialog is not None and (
            self._sketch_dialog.canvas.mixed_move
            or self._sketch_dialog.canvas.pending_cross_tangencies
        ):
            dialog.submission_failed("请先完成或取消关联草稿。")
            return
        if loaded is None or services is None or unit is None or session_id != self._session_id:
            dialog.submission_failed("文档已切换。")
            return
        revision = loaded.document.revision

        def remove() -> object:
            if (
                self._cross_tangency_dialog is not dialog
                or self._loaded is not loaded
                or self._session_id != session_id
                or loaded.document.revision != revision
            ):
                raise ValidationError("文档已改变，请重新打开相切关系。")
            expected = dialog.relations_by_id.get(identity)
            if expected is None or expected not in services.kernel.cross_sketch_tangencies:
                raise ValidationError("相切关系已改变，请重新打开。")
            return loaded.bus.execute(
                "drawing.tangency.remove", {"relation_id": identity}, confirmed_by="local"
            )

        def finish(result: ExecutionResult) -> None:
            if (
                self._cross_tangency_dialog is not dialog
                or self._loaded is not loaded
                or self._session_id != session_id
            ):
                return
            if result.error is not None:
                dialog.submission_failed(result.error)
                return
            if self._sketch_dialog is not None:
                self._sketch_dialog.set_context_sketches(services.kernel.sketches)
            self.status_command.setText("对象相切关系已移除，可撤销。")
            dialog.accept()

        if not unit.submit(
            remove, operation="cross-tangency-remove", session_id=session_id, on_complete=finish
        ):
            dialog.submission_failed("几何工作线程忙碌，请重试。")

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
                solved.command_params(
                    sketch,
                    constraint,
                    local_frame=(
                        constraint.text_override is not None
                        or constraint.style_name is not None
                        or mycad_app.sketch_has_curve_point_ids(sketch)
                    ),
                ),
                source_archive_version=source_archive_version,
                source_document_type=loaded.document.document_type,
                source_document_kind=loaded.document.document_kind,
                source_drawing_fillet_baseline=loaded.document.drawing_fillet_baseline,
                source_drawing_chamfer_angle_baseline=(
                    loaded.document.drawing_chamfer_angle_baseline
                ),
                command_version=(9 if updating else 11)
                if mycad_app.sketch_has_curve_point_ids(sketch)
                else (6 if updating else 8)
                if constraint.style_name is not None
                else (5 if updating else 7)
                if constraint.text_override is not None
                else None,
                target_archive_version=6
                if (
                    constraint.text_override is not None
                    or constraint.style_name is not None
                    or mycad_app.sketch_has_curve_point_ids(sketch)
                )
                and source_archive_version < 6
                else None,
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
            if (
                constraint.text_override is not None
                or constraint.style_name is not None
                or mycad_app.sketch_has_curve_point_ids(sketch)
            ):
                assert self._services is not None
                candidate = mycad_app.create_replay_candidate(
                    self._services, loaded, session_identity=session_id
                )
                candidate.stage(
                    ReplayChangeSet(
                        (),
                        (
                            ReplayAppend(
                                "sketch.constraint.update" if updating else "sketch.constraint.add",
                                (9 if updating else 11)
                                if mycad_app.sketch_has_curve_point_ids(sketch)
                                else (6 if updating else 8)
                                if constraint.style_name is not None
                                else (5 if updating else 7),
                                result.command_params(sketch, constraint, local_frame=True),
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
                    raise ValueError(str(preview.failure or "尺寸预览失败"))
                return candidate.commit(
                    candidate.authorize_commit(current_session_identity=session_id),
                    current_session_identity=session_id,
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
        collection_session = dialog.canvas.collection_session
        mixed_valid = dialog.canvas.mixed_move_is_valid
        cross_timeline = (
            dialog.canvas.mixed_move_timeline_with_transforms()
            if mixed is not None and result == QDialog.DialogCode.Accepted
            else ()
        )
        timeline = tuple(
            (saved, draft) for saved, draft, _pending, _arrays, _transforms in cross_timeline
        )
        cross_pairs_by_step = tuple(
            pending for _saved, _draft, pending, _arrays, _transforms in cross_timeline
        )
        arrays_by_step = tuple(
            arrays for _saved, _draft, _pending, arrays, _transforms in cross_timeline
        )
        rectangle_transforms_by_step = tuple(
            transforms for _saved, _draft, _pending, _arrays, transforms in cross_timeline
        )
        after_commit = self._after_sketch_commit
        self._after_sketch_commit = None
        after_failure = self._after_sketch_failure
        self._after_sketch_failure = None
        if self._sketch_dialog is dialog:
            self._sketch_dialog = None
        if self.document_session is not None and self.document_session.active is not None:
            active = self.document_session.active
            active.draft = self._owned_session_draft(active)
        self._hide_sketch_workbench(dialog)
        sketch = dialog.result_sketch
        if result != QDialog.DialogCode.Accepted or sketch is None:
            if collection_session is not None:
                collection_session.cancel()
            self.status_command.setText("草图已取消；文档历史未改变。")
            return
        loaded = self._loaded
        unit = self.execution_unit
        services = self._services
        if loaded is None or unit is None or services is None or session_id != self._session_id:
            self.status_command.setText("草图所属文档已切换，草图未提交。")
            return
        preparation = self._prepared_sketch_save
        source_revision = loaded.document.revision

        def submit_sketch() -> object:
            if (
                preparation is not None
                and preparation.draft is dialog
                and loaded.document.revision != preparation.source_revision
            ):
                raise ValidationError("保存准备前文档已变化，拒绝提交草稿。")
            try:
                return commit_sketch()
            finally:
                if preparation is not None and preparation.draft is dialog:
                    preparation.prepared_revision = loaded.document.revision

        def commit_sketch() -> object:
            if collection_session is not None:
                if mixed is not None:
                    raise ValueError("草稿存在不兼容的混合暂存操作，请先撤销或取消。")
                return collection_session.commit()
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
                    cross_pairs_by_step=cross_pairs_by_step,
                    arrays_by_step=arrays_by_step,
                    initial_cross_pairs=mixed.original_cross_tangencies,
                    initial_associative_arrays=mixed.original_associative_arrays,
                    rectangle_transforms_by_step=rectangle_transforms_by_step,
                )
                preview = candidate.preview(current_session_identity=session_id)
                if preview.state != "succeeded":
                    raise ValueError(str(preview.failure or "暂存变换预览失败"))
                return candidate.commit(
                    candidate.authorize_commit(current_session_identity=session_id),
                    current_session_identity=session_id,
                )
            return mycad_app.commit_new_sketch(
                services,
                loaded,
                sketch,
                session_identity=session_id,
                cross_tangent_pairs=tuple(dialog.canvas.pending_cross_tangencies),
                associative_arrays=dialog.result_associative_arrays,
            )

        def finish_submission(result_value: ExecutionResult) -> None:
            if result_value.error is not None:
                self.status_command.setText(f"草图提交失败：{result_value.error}")
                recovery_error = ""
                if (
                    collection_session is not None
                    and (preparation is None or preparation.draft is not dialog)
                    and loaded.document.revision != source_revision
                ):
                    try:
                        collection_session.rebind_after_failed_commit(source_revision, session_id)
                        dialog.canvas.rebind_restored_source(
                            source_revision, loaded.document.revision
                        )
                        collection_session.complete_failed_commit_canvas_rebind(
                            (source_revision, loaded.document.revision)
                        )
                    except Exception as exc:
                        recovery_error = f"；暂存恢复失败：{exc}，可再次完成草稿以重试"
                if self._loaded is loaded and self._session_id == session_id:
                    self._sketch_dialog = dialog
                    dialog.result_sketch = None
                    dialog.setResult(QDialog.DialogCode.Rejected)
                    self._show_sketch_workbench(dialog)
                    self._sync_drawing_layers()
                    dialog.status_label.setText(
                        f"草图提交失败：{result_value.error}{recovery_error}。"
                        "草稿已保留，可修正后重试或取消。"
                    )
                if after_failure is not None:
                    after_failure()
                return
            if self.viewport is not None:
                self.viewport.refresh()
            self.status_command.setText(
                "草稿及暂存操作已提交；可撤销、重做和保存重放。"
                if collection_session is not None
                else "草图已提交为一条命令；可撤销、重做和保存重放。"
            )
            saving = self._prepared_sketch_save
            if loaded.document.document_type == "drawing2d" and not (
                saving is not None and saving.draft is dialog
            ):
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
            owns_viewport=lambda: self._session_id == session,
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

    def _sync_selection_filter_action(self) -> None:
        if self.viewport is not None:
            self.selection_filter_actions[self.viewport.selection_filter()].setChecked(True)

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
        drawing = (
            self.active_workspace == "sketch"
            and self._sketch_dialog is not None
            and self._sketch_dialog.canvas.select_committed_entities
        )
        self.status_command.setText(drawing_message(result.error) if drawing else result.error)
        if result.error_detail is not None:
            self.information_tab.append_message(
                drawing_message(result.error_detail) if drawing else result.error_detail
            )

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
        self.start_page.set_theme(theme)
        self._refresh_action_icons()
        if self.command_palette is not None:
            self.command_palette.set_icon_theme(theme)
        if self.right_panel is not None:
            self.right_panel.set_icon_theme(theme)
        if self.viewport is not None:
            self.viewport.set_theme(theme)
        for canvas in self.findChildren(SketchCanvas):
            canvas.set_drawing_theme(theme)
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
        settings = QSettings(ORG_NAME, APP_NAME)
        dialog = CursorSettingsDialog(
            drawing_cursor_style(settings),
            self,
            markers_visible=drawing_constraint_markers_visible(settings),
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        style = dialog.selected_style()
        markers_visible = dialog.constraint_markers.isChecked()
        settings.setValue(CURSOR_STYLE_KEY, style)
        settings.setValue(CONSTRAINT_MARKERS_KEY, markers_visible)
        if self._sketch_dialog is not None and self._sketch_dialog.canvas.select_committed_entities:
            self._sketch_dialog.canvas.set_crosshair_style(style)
            self._sketch_dialog.canvas.set_constraint_markers_visible(markers_visible)
        if self.document_session is not None:
            for document in self.document_session.documents:
                if document.draft is not None and document.draft.canvas.select_committed_entities:
                    document.draft.canvas.set_crosshair_style(style)
                    document.draft.canvas.set_constraint_markers_visible(markers_visible)

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

    def active_cross_sketch_tangency_dialog(self) -> CrossSketchTangencyDialog | None:
        """Return the active cross-sketch tangency editor."""
        return self._cross_tangency_dialog

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
        if self._cross_tangency_dialog is not None:
            self._cross_tangency_dialog.reject()
        if self._sketch_dialog is not None:
            self._sketch_dialog.reject()
        if self._active_modeling_command is not None:
            self._end_modeling_tool(cancel_editor=True)
        self._bus = loaded.bus
        self._fillet_last_successful_radius = 1.0
        self._fillet_radius_value = 1.0
        self._session_id += 1
        self._history_display_candidate = None
        self._history_display_snapshot = None
        if self.execution_unit is not None:
            self.execution_unit.set_session(self._session_id)
        # Replacement semantics: dropping our strong adapter list unsubscribes
        # the previous document—its bus only holds subscribers weakly.
        self._signal_adapters.clear()
        self._loaded = loaded
        self._sync_session_document_actions()
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
        if self._pending_drawing_text_blocks_navigation():
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
        if not self._close_block_editor(entry.loaded):
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
        preparation = self._prepared_sketch_save
        if preparation is not None and preparation.entry is entry:
            # The user explicitly discarded this document. A failed rebuild
            # may already have consumed the handle; neither case retains it.
            with suppress(ValidationError):
                preparation.loaded.bus.release_save_checkpoint(preparation.checkpoint)
            collection = preparation.draft.canvas.collection_session
            if collection is not None:
                collection.discard_failed_save_recovery()
            self._prepared_sketch_save = None
            preparation.draft.reject()
            entry.draft = None
        if self.part_sketch_task is not None:
            self.part_sketch_task.reject()
        if self._cross_tangency_dialog is not None:
            self._cross_tangency_dialog.reject()
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
        self._sync_session_document_actions()
        self._sync_workspace_actions()
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
            entry.draft = self._owned_session_draft(entry)
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
        if entry is not session.active and self._pending_drawing_text_blocks_navigation():
            self._refresh_document_choice()
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
                previous.draft = self._owned_session_draft(previous)
                if self._sketch_dialog is not None:
                    self._drafting_toolbar_state = self._sketch_dialog.toolbar_layout_state()
                previous.plan_draft = self.plan_draft
            if self.viewport is not None:
                previous.view_state = self.viewport.capture_view()
        if self.cli_tab is not None:
            self.cli_tab.set_drawing_bar(None)
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
            if entry.draft is not None and entry.draft.canvas.collection_session is not None:
                try:
                    entry.draft.canvas.collection_session.rebind_workspace(
                        entry.services, entry.loaded, self._session_id
                    )
                except (KeyError, ValueError, ValidationError) as exc:
                    entry.draft.status_label.setText(str(exc))
                    self.status_command.setText(str(exc))
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
        if self.cli_tab is not None and self.cli_tab.drawing_bar is not None:
            self._show_console_page(self.cli_tab)
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
        if name == "metadata_changed" and self._sketch_dialog is not None:
            self._sketch_dialog.refresh_document_properties()
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
        session_id = self._session_id

        def submit_reference() -> object:
            archive = params.get("archive")
            source_version = (
                cast("Mapping[str, object]", archive).get("version")
                if isinstance(archive, Mapping)
                else None
            )
            if (
                command in ("reference.attach", "reference.update")
                and type(source_version) is int
                and source_version in (7, 8)
                and entry.loaded.document.archive_version < source_version
            ):
                candidate = mycad_app.create_replay_candidate(
                    entry.services, entry.loaded, session_identity=session_id
                )
                candidate.stage(
                    ReplayChangeSet(
                        (),
                        (ReplayAppend(command, 1, params, "local"),),
                        False,
                        target_archive_version=source_version,
                    ),
                    current_session_identity=session_id,
                )
                preview = candidate.preview(current_session_identity=session_id)
                if preview.state != "succeeded":
                    candidate.cancel()
                    raise ValidationError(str(preview.failure or "来源关联预览失败。"))
                if self._session_id != session_id:
                    candidate.cancel()
                    raise ValidationError("来源关联期间文档已切换。")
                grant = candidate.authorize_commit(current_session_identity=session_id)
                return candidate.commit(grant, current_session_identity=session_id)
            return entry.loaded.bus.execute(command, params, "local")

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
            submit_reference,
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
        if unit is not None and (
            unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result
        ):
            self.status_command.setText("几何操作正在完成，请等待后再编辑历史。")
            dialog.reject()
            return
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
        dialog.set_cancel_guard(
            lambda: not (unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result)
        )
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
                    self._history_display_candidate = candidate
                    self._history_display_snapshot = snapshot

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
            unit = self.execution_unit
            if unit is not None and (
                unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result
            ):
                if value not in self._pending_history_discards:
                    self._pending_history_discards.append(value)
                self._history_discard_timer.start(100)
                return
            if value.state not in ("cancelled", "committed"):
                value.cancel()
            self._clear_history_candidate_display(value)

    def _clear_history_candidate_display(self, candidate: mycad_app.ReplayCandidateSession) -> None:
        if self._history_display_candidate is not candidate:
            return
        snapshot = self._history_display_snapshot
        self._history_display_candidate = None
        self._history_display_snapshot = None
        if (
            self.viewport is not None
            and snapshot is not None
            and self.viewport.displays_candidate_preview(snapshot)
        ):
            self.viewport.clear_candidate_preview()

    def _flush_history_discards(self) -> None:
        unit = self.execution_unit
        if unit is not None and (
            unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result
        ):
            self._history_discard_timer.start(100)
            return
        pending = tuple(self._pending_history_discards)
        self._pending_history_discards.clear()
        for candidate in pending:
            self._discard_history_candidate(candidate)

    def _commit_history_candidate(self, value: object, ordinal: int) -> None:
        if not isinstance(value, mycad_app.ReplayCandidateSession):
            return
        candidate = value
        unit, loaded, session_id = self.execution_unit, self._loaded, self._session_id
        proposal = candidate.proposal
        if (
            unit is None
            or loaded is None
            or proposal is None
            or candidate.state in ("cancelled", "committed")
            or proposal.session_identity != session_id
            or proposal.document_id != loaded.document.document_id
        ):
            self._discard_history_candidate(candidate)
            self.status_command.setText("历史候选已失效，请重新预览。")
            return
        if unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result:
            self.status_command.setText("几何操作正在执行，请稍后确认历史候选。")
            return
        self._clear_history_candidate_display(candidate)

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
            transaction_memberships = payload.get("transaction_unmapped_group_memberships")
            if payload.get("unmapped_group_members") or transaction_memberships:
                self.status_command.setText(
                    f"当前：{command_id}（#{ordinal}）；原组成员已清理，未提供确定的替换映射。"
                )
                raw_memberships = transaction_memberships or payload.get(
                    "unmapped_group_memberships"
                )
                details: list[str] = []
                if isinstance(raw_memberships, list):
                    for item in cast("list[object]", raw_memberships):
                        if not isinstance(item, Mapping):
                            continue
                        entry = cast("Mapping[str, object]", item)
                        group_id, member = entry.get("group_id"), entry.get("member")
                        if isinstance(group_id, str) and isinstance(member, Mapping):
                            ref = cast("Mapping[str, object]", member)
                            details.append(
                                f"组 {group_id}：{ref.get('kind', '?')} {ref.get('object_id', '?')}"
                                + (f" / 草图 {ref['sketch_id']}" if ref.get("sketch_id") else "")
                            )
                self.status_command.setToolTip("\n".join(details))
            else:
                self.status_command.setText(f"当前：{command_id}（#{ordinal}）")
                self.status_command.setToolTip("")
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
            preparation = self._prepared_sketch_save
            retained = preparation is not None and preparation.draft is self._sketch_dialog
            interactive_drag = (
                busy
                and self.execution_unit is not None
                and self.execution_unit.operation in ("saved-handle-preview", "saved-handle-commit")
                and self._sketch_dialog.canvas.saved_handle_drag_active
            )
            self._sketch_dialog.setEnabled(
                (not busy or interactive_drag) and not retained and not self._mixed_history_pending
            )
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
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.isEnabled()
            and self._services is not None
        ):
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
            message = f"{label}失败：{result.error}"
            if (
                self._sketch_dialog is not None
                and self._sketch_dialog.canvas.select_committed_entities
            ):
                message = drawing_message(message)
            self.status_command.setText(message)
        elif self._sketch_dialog is not None and self._services is not None:
            self._sync_drawing_layers()

    def request_undo(self) -> None:
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools.pending
        ):
            self.status_command.setText("请先完成或取消形位公差放置，再撤销文档操作。")
            return
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.text_tools is not None
            and self._sketch_dialog.canvas.text_tools.pending
        ):
            self.status_command.setText("请先完成或取消文字编辑，再撤销文档操作。")
            return
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
        if (
            draft is not None
            and self.active_workspace == "sketch"
            and draft.canvas.collection_session is not None
        ):
            if not draft.canvas.undo_last_operation():
                self.status_command.setText(draft.canvas.message or "没有可撤销的暂存操作。")
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
            in {
                "drawing.layers.set",
                "drawing.clipboard.prepare",
                "drawing.dimension_styles.set",
                "drawing.text.add",
                "drawing.text.update",
                "drawing.text.remove",
                "drawing.text.batch",
                "drawing.text_styles.set",
                "drawing.tolerance.batch",
                "drawing.reference_dimensions.batch",
                "drawing.raster.add",
                "drawing.raster.update",
                "drawing.raster.remove",
                "drawing.raster.batch",
                "drawing.fillet_radius.set",
                "drawing.chamfer_values.set",
                "sketch.revise",
                "drawing.sketch.revise",
            }
        )
        boundary = (
            (len(self._loaded.document.commands), draft.canvas.history_position)
            if layer_undo and draft is not None and self._loaded is not None
            else None
        )
        if (
            layer_undo
            and draft is not None
            and self._loaded is not None
            and self._services is not None
            and self._loaded.document.commands[-1].id == "drawing.dimension_styles.set"
        ):
            previous = next(
                (
                    DimensionStyleTable.from_mapping(
                        command.params
                        if command.id == "drawing.dimension_styles.set"
                        else command.params["clipboard_styles"]
                    )
                    for command in reversed(self._loaded.document.commands[:-1])
                    if command.id == "drawing.dimension_styles.set"
                    or (
                        command.id in {"drawing.clipboard.prepare", "sketch.create"}
                        and "clipboard_styles" in command.params
                    )
                ),
                DimensionStyleTable((DimensionStyle("标准"),), "标准"),
            )
            current = self._services.kernel.drawing_dimension_styles
            for constraint in draft.canvas.constraints:
                if constraint.style_name is None:
                    continue
                try:
                    unchanged = current.get(constraint.style_name) == previous.get(
                        constraint.style_name
                    )
                except KeyError:
                    unchanged = False
                if not unchanged:
                    self.status_command.setText(
                        "草稿尺寸使用图纸标注样式，请先完成草图再撤销样式。"
                    )
                    return
        mixed_draft = (
            draft.mixed_draft_history.get(boundary[0])
            if boundary is not None and draft is not None
            else None
        )
        if (
            mixed_draft is not None
            and self._loaded is not None
            and (self._loaded.document.commands[-1].instance_id != mixed_draft[2])
        ):
            mixed_draft = None
        if mixed_draft is not None and draft is not None:
            if not draft.canvas.mixed_draft_history_matches(
                mixed_draft[0], mixed_draft[1], redo=False
            ):
                self.status_command.setText("草稿历史已变化，无法安全撤销混合操作。")
                return
            self._mixed_history_pending = True
            draft.setEnabled(False)
        mixed_raster_undo = bool(
            boundary is not None
            and draft is not None
            and draft.canvas.mixed_move is not None
            and self._loaded is not None
            and self._loaded.document.commands[-1].id
            in {"drawing.raster.add", "drawing.raster.batch"}
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
            undo_document = self._loaded
            previous_revision = undo_document.document.revision if undo_document else None
            radius_undo = bool(
                undo_document
                and undo_document.document.commands
                and undo_document.document.commands[-1].id
                in {"drawing.fillet_radius.set", "drawing.chamfer_values.set"}
            )
            layers_undo = bool(
                boundary is not None
                and undo_document
                and undo_document.document.commands
                and undo_document.document.commands[-1].id == "drawing.layers.set"
            )

            def undo() -> None:
                bus.undo_operation()
                services.kernel.viewport_data()

            def finished(result: ExecutionResult) -> None:
                if mixed_draft is not None and draft is not None:
                    self._mixed_history_pending = False
                    draft.setEnabled(True)
                    if result.error is None:
                        draft.canvas.document_layer_table = services.kernel.drawing_layers
                        draft.canvas.undo_last_operation()
                if (
                    result.error is None
                    and mixed_raster_undo
                    and previous_revision is not None
                    and undo_document is not None
                    and draft is not None
                ):
                    draft.canvas.rebind_restored_source(
                        previous_revision, undo_document.document.revision
                    )
                if (
                    result.error is None
                    and layers_undo
                    and previous_revision is not None
                    and undo_document is self._loaded
                    and undo_document is not None
                    and draft is self._sketch_dialog
                    and draft is not None
                    and draft.canvas.mixed_move is not None
                    and draft.canvas.mixed_move.source_revision == previous_revision
                    and draft.canvas.rebase_mixed_layers(
                        services.kernel.sketches, services.kernel.drawing_layers
                    )
                ):
                    draft.canvas.acknowledge_fillet_setting_revision(
                        previous_revision, undo_document.document.revision
                    )
                if (
                    result.error is None
                    and radius_undo
                    and previous_revision is not None
                    and undo_document is not None
                    and undo_document is self._loaded
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.canvas.acknowledge_fillet_setting_revision(
                        previous_revision, undo_document.document.revision
                    )
                if (
                    result.error is None
                    and boundary is not None
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.layer_history_redo.append(
                        (boundary[0], mixed_draft[0]) if mixed_draft is not None else boundary
                    )
                self._finish_worker_action(result, "撤销")

            submitted = unit.submit(
                undo,
                operation="undo",
                session_id=self._session_id,
                on_complete=finished,
            )
            if not submitted and mixed_draft is not None and draft is not None:
                self._mixed_history_pending = False
                draft.setEnabled(True)
            return
        try:
            self._bus.undo_operation()
        except InvalidHistoryError as err:
            self.status_command.setText(f"撤销失败：{err}")

    def request_redo(self) -> None:
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools.pending
        ):
            self.status_command.setText("请先完成或取消形位公差放置，再重做文档操作。")
            return
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.text_tools is not None
            and self._sketch_dialog.canvas.text_tools.pending
        ):
            self.status_command.setText("请先完成或取消文字编辑，再重做文档操作。")
            return
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
        if (
            draft is not None
            and self.active_workspace == "sketch"
            and draft.canvas.collection_session is not None
        ):
            if not draft.canvas.redo_last_operation():
                self.status_command.setText(draft.canvas.message or "没有可重做的暂存操作。")
            return
        layer_redo = (
            draft is not None
            and self._loaded is not None
            and bool(draft.layer_history_redo)
            and draft.layer_history_redo[-1][0] > len(self._loaded.document.commands)
            and draft.layer_history_redo[-1][1] == draft.canvas.history_position
            and not draft.canvas.has_pending_geometry
            and not draft.canvas.has_active_edit_gesture
        )
        mixed_draft = (
            draft.mixed_draft_history.get(draft.layer_history_redo[-1][0])
            if layer_redo and draft is not None and self._loaded is not None
            else None
        )
        if mixed_draft is not None and draft is not None:
            if not draft.canvas.mixed_draft_history_matches(
                mixed_draft[0], mixed_draft[1], redo=True
            ):
                self.status_command.setText("草稿历史已变化，无法安全重做混合操作。")
                return
            self._mixed_history_pending = True
            draft.setEnabled(False)
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
            redo_document = self._loaded
            previous_revision = redo_document.document.revision if redo_document else None
            previous_count = len(redo_document.document.commands) if redo_document else 0

            def redo() -> None:
                bus.redo_operation()
                services.kernel.viewport_data()

            def finished(result: ExecutionResult) -> None:
                if mixed_draft is not None and draft is not None:
                    self._mixed_history_pending = False
                    draft.setEnabled(True)
                    if result.error is None:
                        draft.canvas.document_layer_table = services.kernel.drawing_layers
                        draft.canvas.redo_last_operation()
                if (
                    result.error is None
                    and layer_redo
                    and previous_revision is not None
                    and redo_document is not None
                    and draft is not None
                    and draft.canvas.mixed_move is not None
                    and redo_document.document.commands
                    and redo_document.document.commands[-1].id
                    in {"drawing.raster.add", "drawing.raster.batch"}
                ):
                    draft.canvas.rebind_restored_source(
                        previous_revision, redo_document.document.revision
                    )
                if (
                    result.error is None
                    and layer_redo
                    and previous_revision is not None
                    and redo_document is self._loaded
                    and redo_document is not None
                    and len(redo_document.document.commands) == previous_count + 1
                    and redo_document.document.commands[-1].id == "drawing.layers.set"
                    and draft is self._sketch_dialog
                    and draft is not None
                    and draft.canvas.mixed_move is not None
                    and draft.canvas.mixed_move.source_revision == previous_revision
                    and draft.canvas.rebase_mixed_layers(
                        services.kernel.sketches, services.kernel.drawing_layers
                    )
                ):
                    draft.canvas.acknowledge_fillet_setting_revision(
                        previous_revision, redo_document.document.revision
                    )
                if (
                    result.error is None
                    and previous_revision is not None
                    and redo_document is self._loaded
                    and redo_document is not None
                    and len(redo_document.document.commands) == previous_count + 1
                    and redo_document.document.commands[-1].id
                    in {"drawing.fillet_radius.set", "drawing.chamfer_values.set"}
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.canvas.acknowledge_fillet_setting_revision(
                        previous_revision, redo_document.document.revision
                    )
                if (
                    result.error is None
                    and layer_redo
                    and draft is not None
                    and draft is self._sketch_dialog
                ):
                    draft.layer_history_redo.pop()
                self._finish_worker_action(result, "重做")

            submitted = unit.submit(
                redo,
                operation="redo",
                session_id=self._session_id,
                on_complete=finished,
            )
            if not submitted and mixed_draft is not None and draft is not None:
                self._mixed_history_pending = False
                draft.setEnabled(True)
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
        if self._pending_drawing_text_blocks_navigation():
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
        if self._pending_drawing_text_blocks_navigation():
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
            (
                mycad_app.new_workspace_document(self._services, kind="sketch")
                if document_type == "drawing2d"
                else mycad_app.new_document(self._services, document_type=document_type)
            ),
            None,
        )

    def _queue_dxf_collection_import(
        self,
        imported: DxfSketchImport,
        loaded: LoadedDocument,
        services: AppServices,
        session_id: int,
    ) -> None:
        from mycad.formats.dxf_collection_import import prepare_dxf_collection_import

        unit = self.execution_unit
        editor = self._sketch_dialog
        if unit is None or self._loaded is not loaded or self._session_id != session_id:
            self.status_command.setText("文档已变化，DXF 未导入。")
            return
        if loaded.document.document_type != "drawing2d":
            self._show_error("DXF 块和组只能导入独立二维文档。")
            return
        if editor is not None and (
            editor.canvas.collection_session is not None
            or editor.canvas.entities
            or editor.canvas.constraints
            or editor.canvas.has_pending_geometry
            or editor.canvas.has_active_edit_gesture
            or (editor.canvas.text_tools is not None and editor.canvas.text_tools.pending)
        ):
            self._show_error("请先完成或取消当前草稿，再导入 DXF 集合。")
            return
        try:
            datum_tools = editor.canvas.geometric_tolerance_tools if editor is not None else None
            prepared = prepare_dxf_collection_import(
                imported,
                mycad_app.drawing_collection_snapshot(services),
                datum_relayout=datum_tools.relayout_recorded_datum if datum_tools else None,
            )
            candidate = mycad_app.create_replay_candidate(
                services, loaded, session_identity=session_id
            )
            try:
                candidate.stage(
                    ReplayChangeSet((), (prepared.operation,), False, target_archive_version=8),
                    current_session_identity=session_id,
                )
            except Exception:
                candidate.cancel()
                raise
        except (KeyError, ValueError, MycadError) as exc:
            self._show_error(f"无法准备 DXF 集合导入：{exc}")
            return

        def preview_candidate() -> object:
            return candidate.preview(current_session_identity=session_id)

        def finish_preview(result: ExecutionResult) -> None:
            if result.error is not None or not isinstance(
                result.value, mycad_app.ReplayCandidatePreview
            ):
                candidate.cancel()
                self._show_error(f"DXF 候选预览失败：{result.error or '返回结果无效'}")
                return
            preview = result.value
            if preview.state != "succeeded":
                candidate.cancel()
                self._show_error(f"DXF 候选预览失败：{preview.failure or preview.state}")
                return
            report = replace(
                imported.report, warnings=(*imported.report.warnings, *prepared.warnings)
            )
            message = (
                f"{report}\n\n将导入 {len(imported.sketch.entities)} 个几何、"
                f"{len(imported.texts)} 个文字、{len(imported.block_definitions)} 个块定义、"
                f"{len(imported.block_instances)} 个块实例和 {len(imported.groups)} 个组。"
                f"\n关联尺寸 {len(imported.sketch.constraints)} 个，"
                f"独立参考尺寸 {len(imported.detached_dimensions)} 个，"
                f"公差框 {len(imported.tolerance_frames)} 个，基准 {len(imported.datum_identifiers)} 个。"
                "\n确认前不会修改命令历史或模型。"
            )
            choice = QMessageBox.question(
                self,
                "导入 DXF 集合预览",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                candidate.cancel()
                self.status_command.setText("DXF 导入已取消；文档历史未改变。")
                return

            def commit_candidate() -> object:
                if self._loaded is not loaded or self._session_id != session_id:
                    raise ValidationError("文档已变化；DXF 未导入。")
                grant = candidate.authorize_commit(current_session_identity=session_id)
                candidate.commit(grant, current_session_identity=session_id)
                return None

            def finish_commit(commit_result: ExecutionResult) -> None:
                if commit_result.error is not None:
                    candidate.cancel()
                    self._show_error(f"DXF 集合提交失败：{commit_result.error[:240]}")
                    return
                self._sync_drawing_layers()
                if self.viewport is not None:
                    self.viewport.refresh()
                self.status_command.setText("DXF 集合已导入；可一次撤销、重做和保存重放。")

            if not unit.submit(
                commit_candidate,
                operation="dxf-collection-import-commit",
                session_id=session_id,
                on_complete=finish_commit,
            ):
                candidate.cancel()
                self.status_command.setText("应用工作线程忙碌，DXF 集合尚未提交。")

        if not unit.submit(
            preview_candidate,
            operation="dxf-collection-import-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            candidate.cancel()
            self.status_command.setText("应用工作线程忙碌，DXF 集合尚未预览。")

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
            if imported.groups or imported.block_instances or imported.block_definitions:
                self._queue_dxf_collection_import(imported, loaded, services, session_id)
                return
            if (
                not imported.sketch.entities
                and not imported.texts
                and not imported.tolerance_frames
                and not imported.datum_identifiers
                and not imported.detached_dimensions
            ):
                self._show_error(f"DXF 中没有可导入的支持图元：{imported.report}")
                return
            existing_sketch_ids = {
                command.params.get("sketch_id")
                for command in loaded.document.commands
                if command.id == "sketch.create"
            }
            report = imported.report
            sketch = imported.sketch
            imported_styles: DimensionStyleTable | None = None
            prepared_text_styles = imported.text_styles
            prepared_texts = imported.texts
            prepared_frames = imported.tolerance_frames
            prepared_datums = imported.datum_identifiers
            if imported.dimension_styles and loaded.document.document_type == "drawing2d":
                try:
                    table = services.kernel.drawing_dimension_styles
                    styles_by_id = dict(imported.dimension_styles)
                    font_ids = tuple(
                        style.text_style_id
                        for style in styles_by_id.values()
                        if style.text_style_id is not None
                    )
                    if font_ids:
                        if prepared_text_styles is None:
                            raise ValueError("DXF 标注引用了缺失的文字样式。")
                        font_ids += tuple(text.style_id for text in prepared_texts)
                        font_ids += tuple(
                            frame.text_style_id
                            for frame in prepared_frames
                            if frame.text_style_id is not None
                        )
                        font_ids += tuple(
                            datum.text_style_id
                            for datum in prepared_datums
                            if datum.text_style_id is not None
                        )
                        prepared_text_styles, font_map = reconcile_text_style_ids(
                            font_ids, prepared_text_styles, services.kernel.drawing_text_styles
                        )
                        styles_by_id = {
                            identity: replace(style, text_style_id=font_map[style.text_style_id])
                            if style.text_style_id is not None
                            else style
                            for identity, style in styles_by_id.items()
                        }
                        prepared_texts = tuple(
                            replace(text, style_id=font_map[text.style_id])
                            for text in prepared_texts
                        )
                        prepared_frames = tuple(
                            replace(frame, text_style_id=font_map[frame.text_style_id])
                            if frame.text_style_id is not None
                            else frame
                            for frame in prepared_frames
                        )
                        prepared_datums = tuple(
                            replace(datum, text_style_id=font_map[datum.text_style_id])
                            if datum.text_style_id is not None
                            else datum
                            for datum in prepared_datums
                        )
                    constraints: list[SketchConstraint] = []
                    for constraint in sketch.constraints:
                        style = styles_by_id.get(constraint.constraint_id)
                        if style is None:
                            constraints.append(constraint)
                            continue
                        single = replace(
                            sketch, constraints=(replace(constraint, style_name=style.name),)
                        )
                        table, renamed = reconcile_clipboard_styles(
                            single, DimensionStyleTable((style,), style.name), table
                        )
                        constraints.append(renamed.constraints[0])
                    sketch = replace(sketch, constraints=tuple(constraints))
                    if table != services.kernel.drawing_dimension_styles:
                        imported_styles = table
                except (KeyError, ValueError) as exc:
                    self._show_error(f"无法导入 DXF 标注样式：{exc}")
                    return
            sketch, prepared_datums, prepared_frames, curve_count = remap_colliding_curves(
                sketch, prepared_datums, prepared_frames, services.kernel.sketches
            )
            try:
                prepared_datums, prepared_frames, label_changes = remap_datum_labels(
                    prepared_datums, prepared_frames, services.kernel.drawing_datum_identifiers
                )
            except ValueError as exc:
                self._show_error(f"无法导入 DXF 基准：{exc}")
                return
            identity_warnings = (
                (f"{curve_count} 条曲线的身份与当前文档重复，已分配新的图元及点身份",)
                if curve_count
                else ()
            ) + tuple(f"基准名称冲突：{old} → {new}" for old, new in label_changes)
            if identity_warnings:
                report = DxfExchangeReport(
                    report.action,
                    report.dxf_version,
                    report.unit,
                    report.entity_count,
                    (*report.warnings, *identity_warnings),
                )
            if sketch.sketch_id in existing_sketch_ids:
                new_sketch_id = uuid4().hex
                imported = replace(
                    imported,
                    datum_identifiers=tuple(
                        replace(
                            datum, attachment=replace(datum.attachment, sketch_id=new_sketch_id)
                        )
                        if datum.attachment is not None
                        and datum.attachment.sketch_id == sketch.sketch_id
                        else datum
                        for datum in imported.datum_identifiers
                    ),
                )
                prepared_datums = tuple(
                    replace(datum, attachment=replace(datum.attachment, sketch_id=new_sketch_id))
                    if datum.attachment is not None
                    and datum.attachment.sketch_id == sketch.sketch_id
                    else datum
                    for datum in prepared_datums
                )
                prepared_datums = tuple(
                    replace(
                        datum,
                        annotation_attachment=replace(
                            datum.annotation_attachment, sketch_id=new_sketch_id
                        ),
                    )
                    if datum.annotation_attachment is not None
                    and datum.annotation_attachment.sketch_id == sketch.sketch_id
                    else datum
                    for datum in prepared_datums
                )
                prepared_frames = tuple(
                    replace(
                        frame,
                        leader_attachment=replace(frame.leader_attachment, sketch_id=new_sketch_id),
                    )
                    if frame.leader_attachment is not None
                    and frame.leader_attachment.sketch_id == sketch.sketch_id
                    else frame
                    for frame in prepared_frames
                )
                prepared_frames = tuple(
                    replace(
                        frame,
                        leader_annotation_attachment=replace(
                            frame.leader_annotation_attachment, sketch_id=new_sketch_id
                        ),
                    )
                    if frame.leader_annotation_attachment is not None
                    and frame.leader_annotation_attachment.sketch_id == sketch.sketch_id
                    else frame
                    for frame in prepared_frames
                )
                sketch = Sketch(
                    new_sketch_id,
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
                f"\n恢复关联尺寸 {len(sketch.constraints)} 个；独立参考尺寸 {len(imported.detached_dimensions)} 个；文字 {len(imported.texts)} 个。"
                f"\n恢复形位公差框 {len(imported.tolerance_frames)} 个，基准 {len(imported.datum_identifiers)} 个。"
                f"\n恢复图纸样式关联 {sum(c.style_name is not None for c in sketch.constraints)} 个。"
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
                    services,
                    loaded,
                    sketch,
                    session_identity=session_id,
                    imported_styles=imported_styles,
                    imported_texts=prepared_texts,
                    imported_text_styles=prepared_text_styles,
                    imported_tolerance_frames=prepared_frames,
                    imported_datums=prepared_datums,
                    imported_reference_dimensions=imported.detached_dimensions,
                    imported_curve_ids=True,
                )

            def finish_submit(submit_result: ExecutionResult) -> None:
                if submit_result.error is not None:
                    self._show_error(f"DXF 草图提交失败：{submit_result.error[:240]}")
                    return
                self._sync_drawing_layers()
                if self.viewport is not None:
                    self.viewport.refresh()
                self.status_command.setText(
                    f"DXF 草图已导入并写入命令历史：{len(sketch.entities)} 个图元，"
                    f"{len(sketch.constraints)} 个关联尺寸，{len(imported.detached_dimensions)} 个独立参考尺寸，{len(imported.texts)} 个文字，"
                    f"{len(imported.tolerance_frames)} 个形位公差框，{len(imported.datum_identifiers)} 个基准；可撤销、重做和保存重放。"
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
        if self._pending_drawing_text_blocks_navigation():
            return
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
        self.open_document_path(Path(selected).absolute(), _already_confirmed=True)

    def open_document_path(
        self,
        path: Path,
        *,
        old_recent_path: Path | None = None,
        _already_confirmed: bool = False,
    ) -> None:
        if self._pending_drawing_text_blocks_navigation():
            return
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
        if self.document_session is None and not _already_confirmed:
            resume = partial(self.open_document_path, path, old_recent_path=old_recent_path)
            if not self._confirm_unsaved_changes(on_saved=resume):
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
        if self.execution_unit is not None and (
            self.execution_unit.is_busy or self.execution_unit.is_notifying_result
        ):
            raise ValidationError("请等待当前操作完成后再保存。")
        if self.document_session is not None and self.document_session.active is not entry:
            self.activate_session_document(entry.loaded.document.document_id)
        if self.document_session is not None and (
            self.document_session.active is not entry or self._loaded is not entry.loaded
        ):
            raise ValidationError("无法切换到待保存文档；请先完成或取消当前命令。")
        return self._choose_document_save_path()

    def _owned_session_draft(self, entry: SessionDocument) -> SketchEditorDialog | None:
        preparation = self._prepared_sketch_save
        if (
            preparation is not None
            and preparation.entry is entry
            and preparation.loaded is entry.loaded
        ):
            return preparation.draft
        return self._sketch_dialog

    def _prepare_session_document(
        self, entry: SessionDocument, complete: Callable[[bool], None]
    ) -> None:
        preparation = self._prepared_sketch_save
        if preparation is not None:

            def retry_preparation(error: str | None) -> None:
                if error is not None:
                    complete(False)
                else:
                    self._prepare_session_document(entry, complete)

            self._settle_session_save(preparation.entry, False, retry_preparation)
            return
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
        if draft is None or not (
            draft.canvas.entities
            or (draft.canvas.text_tools is not None and draft.canvas.text_tools.pending)
            or draft.canvas.has_pending_geometry
            or draft.canvas.mixed_move is not None
            or (
                draft.canvas.collection_session is not None
                and draft.canvas.collection_session.has_staged_operations
            )
        ):
            complete(True)
            return
        collection = draft.canvas.collection_session
        if collection is not None:
            try:
                recovered = collection.retry_failed_commit_recovery()
                if recovered is not None:
                    draft.canvas.rebind_restored_source(*recovered)
                    collection.complete_failed_commit_canvas_rebind(recovered)
            except Exception as exc:
                draft.status_label.setText(f"二维暂存恢复失败：{exc}。请重试或取消草稿。")
                self._show_error(draft.status_label.text())
                complete(False)
                return
        revision = entry.loaded.document.revision
        self._prepared_sketch_save = _PreparedSketchSave(
            entry,
            entry.loaded,
            draft,
            entry.loaded.bus.create_save_checkpoint(),
            revision,
            revision,
        )
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

    def _settle_session_save(
        self, entry: SessionDocument, saved: bool, complete: Callable[[str | None], None]
    ) -> None:
        preparation = self._prepared_sketch_save
        if preparation is None or preparation.entry is not entry:
            complete(None)
            return
        bus, draft = preparation.loaded.bus, preparation.draft

        def retain_failed(error: str) -> None:
            collection = draft.canvas.collection_session
            if collection is not None:
                try:
                    collection.retain_failed_save_recovery()
                except Exception as exc:
                    error = f"{error}；无法恢复写入保护：{exc}"
            entry.draft = draft
            draft.setEnabled(False)
            draft.status_label.setText(f"保存恢复失败：{error}。原草稿已保留；再次保存可重试恢复。")
            complete(f"{error}；请再次保存以重试恢复")

        if saved:
            bus.release_save_checkpoint(preparation.checkpoint)
            self._prepared_sketch_save = None
            if (
                self._loaded is entry.loaded
                and self.document_session is not None
                and self.document_session.active is entry
            ):
                self._on_sketch_start()
                if self._sketch_dialog is not None:
                    self._sketch_dialog.continue_workspace_from(draft)
            complete(None)
            return

        def finish_restore() -> None:
            try:
                collection = draft.canvas.collection_session
                if collection is not None and not preparation.collection_restored:
                    collection.restore_after_save_failure(
                        entry.services,
                        preparation.loaded,
                        preparation.source_revision,
                        preparation.loaded.document.revision,
                        self._session_id,
                    )
                    preparation.collection_restored = True
                draft.canvas.rebind_restored_source(
                    preparation.source_revision, preparation.loaded.document.revision
                )
            except Exception as exc:
                retain_failed(str(exc))
                return
            self._prepared_sketch_save = None
            draft.result_sketch = None
            draft.setResult(QDialog.DialogCode.Rejected)
            draft.setEnabled(True)
            entry.draft = draft
            if (
                self._loaded is preparation.loaded
                and self.document_session is not None
                and self.document_session.active is entry
            ):
                self._sketch_dialog = draft
                self._show_sketch_workbench(draft)
                self._sync_drawing_layers()
                if self.viewport is not None:
                    self.viewport.refresh()
            elif (
                self.document_session is not None
                and self.document_session.active is not None
                and self.document_session.active.kind == "sketch"
                and self._sketch_dialog is None
            ):
                self._on_sketch_start()
            complete(None)

        if preparation.checkpoint_restored:
            finish_restore()
            return
        unit = self.execution_unit
        if unit is None or unit.is_busy or unit.is_notifying_result:
            retain_failed("恢复工作线程不可用；原草稿仍保留。")
            return
        # Keep the original editor detached from intermediate geometry signals.
        if self._sketch_dialog is draft:
            self._sketch_dialog = None
            self._hide_sketch_workbench(draft)
        session = self.document_session

        def restore() -> None:
            if (
                session is None
                or session.find(preparation.loaded.document.document_id) is not entry
                or entry.loaded is not preparation.loaded
            ):
                raise ValidationError("文档会话已变化，拒绝恢复到旧状态。")
            collection = draft.canvas.collection_session
            if collection is None:
                bus.restore_save_checkpoint(
                    preparation.checkpoint, expected_revision=preparation.prepared_revision
                )
            else:
                collection.restore_save_checkpoint(
                    preparation.checkpoint, preparation.prepared_revision
                )

        def restored(result: ExecutionResult) -> None:
            if result.error is not None:
                # Do not discard the retained draft or hide a failed recovery.
                retain_failed(result.error)
                return
            preparation.checkpoint_restored = True
            finish_restore()

        if not unit.submit(
            restore,
            operation="save-recovery",
            session_id=self._session_id,
            on_complete=restored,
        ):
            retain_failed("无法启动保存恢复；原草稿仍保留。")

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
        graphic_filter = "DXF 图形兼容（标注不可结构化编辑） (*.dxf)"
        selected, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出 DXF 草图" if drawing2d else "导出（STEP/STL/DXF）",
            "",
            f"DXF 草图 (*.dxf);;{graphic_filter}"
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
                self._queue_dxf_output_preview(
                    target, tolerance_graphics=drawing2d and selected_filter == graphic_filter
                )
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

    def _queue_dxf_output_preview(self, target: Path, *, tolerance_graphics: bool = False) -> None:
        loaded, services, unit = self._loaded, self._services, self.execution_unit
        if loaded is None or services is None or unit is None:
            self.status_command.setText("当前文档不可用，DXF 未导出。")
            return
        session_id, revision = self._session_id, loaded.document.revision
        legacy_frame_anchors: dict[str, tuple[float, float]] = {}
        legacy_frame_skipped_vertices: dict[str, int] = {}
        legacy_frame_bounds: dict[str, tuple[float, float, float, float]] = {}
        graphic_frame_widths: dict[str, tuple[tuple[float, ...], ...]] = {}
        graphic_frame_glyphs = None
        graphic_datum_snapshots = None
        legacy_datum_snapshots = None
        graphic_font_notices: tuple[str, ...] = ()
        legacy_font_notices: tuple[str, ...] = ()
        editor = self.active_sketch_dialog()
        if editor is not None and editor.canvas.geometric_tolerance_tools is not None:
            try:
                tools = editor.canvas.geometric_tolerance_tools
                frames = services.kernel.drawing_tolerance_frames
                legacy_frame_anchors = tools.legacy_frame_export_anchors(frames)
                legacy_frame_skipped_vertices = tools.legacy_frame_export_skipped_vertices(
                    frames, legacy_frame_anchors
                )
                legacy_frame_bounds = tools.legacy_frame_export_bounds(frames, legacy_frame_anchors)
                if tolerance_graphics:
                    datums = services.kernel.drawing_datum_identifiers
                    graphic_frame_widths = tools.graphic_frame_export_widths(frames)
                    graphic_frame_glyphs = tools.graphic_frame_export_glyphs(frames)
                    graphic_datum_snapshots = tools.graphic_datum_export_snapshots(datums)
                    graphic_font_notices = (
                        *tools.graphic_frame_export_font_notices(frames),
                        *tools.graphic_datum_export_font_notices(datums),
                    )
                else:
                    datums = services.kernel.drawing_datum_identifiers
                    legacy_datum_snapshots = tools.legacy_datum_export_snapshots(datums)
                    graphic_font_notices = tools.legacy_datum_export_font_notices(datums)
                legacy_font_notices = tools.legacy_frame_export_font_notices(
                    frames, legacy_frame_anchors
                )
            except ValueError as exc:
                self._show_error(f"DXF 输出预览失败：{exc}")
                return

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
            if legacy_font_notices or graphic_font_notices:
                preview = replace(
                    preview,
                    notices=(*preview.notices, *legacy_font_notices, *graphic_font_notices),
                )
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
            lambda: prepare_dxf_output_preview(
                services.kernel,
                tolerance_graphics=tolerance_graphics,
                legacy_frame_anchors=legacy_frame_anchors,
                legacy_frame_skipped_vertices=legacy_frame_skipped_vertices,
                legacy_frame_bounds=legacy_frame_bounds,
                graphic_frame_widths=graphic_frame_widths,
                graphic_frame_glyphs=graphic_frame_glyphs,
                graphic_datum_snapshots=graphic_datum_snapshots,
                legacy_datum_snapshots=legacy_datum_snapshots,
            ),
            operation="dxf-output-preview",
            session_id=session_id,
            on_complete=finish_preview,
        ):
            self.status_command.setText("正在生成 DXF 输出预览…")
        else:
            self.status_command.setText("应用工作线程忙碌，DXF 尚未导出；请稍后重试。")

    def _pending_drawing_text_blocks_navigation(self) -> bool:
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools is not None
            and self._sketch_dialog.canvas.geometric_tolerance_tools.pending
        ):
            self.status_command.setText("形位公差或基准尚未放置，请先完成或按 Esc 取消。")
            return True
        if (
            self._sketch_dialog is None
            or self._sketch_dialog.canvas.text_tools is None
            or not self._sketch_dialog.canvas.text_tools.pending
        ):
            return False
        self.status_command.setText("二维文字尚未提交：Ctrl+Enter 完成或 Esc 取消，再切换文档。")
        return True

    def _has_unsubmitted_geometry(
        self, *, include_sketch: bool = True, include_history: bool = True
    ) -> bool:
        if self._pending_drawing_text_blocks_navigation():
            return True
        if include_history and self.history_edit_task is not None:
            self.status_command.setText("历史编辑尚未确认，请先完成或取消当前命令。")
            return True
        if self.history_repair_task is not None:
            self.status_command.setText("历史修复尚未确认，请先完成或取消当前命令。")
            return True
        if self.bound_hole_task is not None:
            self.status_command.setText("绑定孔尚未确认，请先完成或取消当前命令。")
            return True
        if (
            self._sketch_dialog is not None
            and self._sketch_dialog.canvas.text_tools is not None
            and self._sketch_dialog.canvas.text_tools.pending
        ):
            self.status_command.setText(
                "二维文字尚未提交：Ctrl+Enter 完成或 Esc 取消，再保存或切换文档。"
            )
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
        if (
            draft.canvas.geometric_tolerance_tools is not None
            and draft.canvas.geometric_tolerance_tools.pending
        ):
            self.status_command.setText("形位公差或基准尚未放置，请先完成或按 Esc 取消。")
            draft.status_label.setText(self.status_command.text())
            return True
        if draft.canvas.text_tools is not None and draft.canvas.text_tools.pending:
            self.status_command.setText("二维文字尚未提交：Ctrl+Enter 完成或 Esc 取消。")
            draft.status_label.setText(self.status_command.text())
            return True
        if not (
            draft.canvas.entities
            or draft.canvas.has_pending_geometry
            or draft.canvas.mixed_move is not None
            or (
                draft.canvas.collection_session is not None
                and draft.canvas.collection_session.has_staged_operations
            )
        ):
            return False
        self.status_command.setText(
            "草图尚未提交：请先完成草图或取消草稿，再保存、切换或关闭文档。"
        )
        draft.status_label.setText(self.status_command.text())
        return True

    def _confirm_unsaved_changes(self, *, on_saved: Callable[[], object] | None = None) -> bool:
        """放行或保留当前文档；异步保存成功后通过 on_saved 继续原操作。"""
        if not self._close_block_editor(self._loaded):
            return False
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
        if not self._close_block_editor():
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
