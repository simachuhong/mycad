# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering drawing page with a floating settings dock and canvas gestures."""

from __future__ import annotations

import math
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast, override
from uuid import UUID, uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad import app as mycad_app
from mycad.core.drawing import DrawingSheet, DrawingState, DrawingView, SourceBinding
from mycad.core.drawing_codec import apply_drawing_command, drawing_object_mapping
from mycad.core.drawing_paper import section_marker_lines, validate_drawing_output
from mycad.core.drawing_projection import (
    ArcCurve,
    DrawingScene,
    DrawingSourceSnapshot,
    LineCurve,
    Point2,
    ProjectionResult,
    SectionMarker,
    ViewBasis,
    ViewDirection,
    build_drawing_scene,
    projected_basis,
)
from mycad.core.drawing_sketch import project_sketch
from mycad.core.drawing_templates import PAPER_SIZES
from mycad.core.persistence import LoadedDocument
from mycad.formats.drawing_export import export_drawing_dxf
from mycad.ui.cad_icons import cad_icon
from mycad.ui.drawing_annotation_tools import DrawingAnnotationTools
from mycad.ui.drawing_canvas import DrawingCanvas
from mycad.ui.drawing_note_tools import DrawingNoteTools
from mycad.ui.drawing_pdf import export_drawing_pdf
from mycad.ui.drawing_render import curve_path, paper_pen
from mycad.ui.drawing_templates import DrawingTemplatePanel
from mycad.ui.drawing_tools import (
    DetailPlacement,
    SectionPlacement,
    ViewPlacement,
    isometric_basis,
    move_view,
    scale_view,
    set_view_alignment,
)
from mycad.ui.drawing_updates import ProjectionBatch, ProjectionUpdates
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit

if TYPE_CHECKING:
    from collections.abc import Callable

    from mycad.app import AppServices


class DrawingWorkbench(QMainWindow):
    message = Signal(str)
    sketch_requested = Signal()
    model_requested = Signal()
    open_requested = Signal()
    new_requested = Signal()
    choose_source_requested = Signal()

    def __init__(
        self,
        services: AppServices | None,
        unit: SerializedExecutionUnit | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.services, self.unit = services, unit
        self.source_selection_available = False
        self.loaded: LoadedDocument | None = None
        self.session_id = 0
        self.state = DrawingState()
        self.sheet_id: UUID | None = None
        self.updates = ProjectionUpdates()
        self.projections = self.updates.results
        self._view_items: dict[UUID, QTreeWidgetItem] = {}
        self.placement: ViewPlacement | None = None
        self.section_placement: SectionPlacement | None = None
        self._section_cursor: Point2 | None = None
        self.detail_placement: DetailPlacement | None = None
        self._detail_cursor: Point2 | None = None
        self._ghost: DrawingView | None = None
        self._preview_params: dict[str, object] | None = None
        self._pending_delete: tuple[UUID, tuple[UUID, ...], tuple[UUID, ...]] | None = None
        self._placement_source_fingerprint = ""
        self._placement_stale = False
        self._pending = False
        self._snapshot_inflight = False
        self._future: Future[tuple[ProjectionResult, ...]] | None = None
        self._future_batch: ProjectionBatch | None = None
        self._source_snapshot: DrawingSourceSnapshot | None = None
        self._worker: mycad_app.DrawingProjectionWorker | None = None
        self._dock_visible = True
        self._start_after_sheet: SourceBinding | None = None
        self.canvas = DrawingCanvas()
        self.canvas.view_selection_guard = self._allow_canvas_view_selection
        self.pages = QStackedWidget()
        self.drawing_page = QWidget()
        drawing_layout = QVBoxLayout(self.drawing_page)
        drawing_layout.setContentsMargins(0, 0, 0, 0)
        drawing_layout.setSpacing(0)
        self.drawing_status = QLabel()
        self.drawing_status.setWordWrap(True)
        self.drawing_status.setMargin(8)
        self.drawing_status.setStyleSheet(
            "QLabel { background: #fff2cf; color: #513800; border-bottom: 1px solid #c99a36; }"
        )
        self.drawing_status.hide()
        drawing_layout.addWidget(self.drawing_status)
        drawing_layout.addWidget(self.canvas, 1)
        self.pages.addWidget(self.drawing_page)
        self.start_page = QWidget()
        outer_layout = QVBoxLayout(self.start_page)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_layout.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        page_layout = QVBoxLayout(content)
        card = QWidget()
        card.setMaximumWidth(560)
        start_layout = QVBoxLayout(card)
        start_layout.setContentsMargins(24, 24, 24, 24)
        start_layout.setSpacing(14)
        page_layout.addStretch()
        page_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        page_layout.addStretch()
        heading = QLabel("创建工程图视图")
        heading.setStyleSheet("font-size: 22px; font-weight: 600;")
        start_layout.addWidget(heading)
        self.start_description = QLabel()
        self.start_description.setWordWrap(True)
        start_layout.addWidget(self.start_description)
        self.generate_button = QPushButton("从当前三维模型生成投影视图")
        self.generate_button.clicked.connect(self.begin_placement)
        self.sketch_view_button = QPushButton("放置草图平面视图")
        self.sketch_view_button.clicked.connect(self.begin_sketch_placement)
        self.sketch_button = QPushButton("前往平面草图")
        self.sketch_button.clicked.connect(self.sketch_requested.emit)
        self.model_button = QPushButton("前往 3D图 · 拉伸 / 旋转建模")
        self.model_button.clicked.connect(self.model_requested.emit)
        self.open_button = QPushButton("打开已有零件文件…")
        self.open_button.clicked.connect(self.open_requested.emit)
        self.new_button = QPushButton("新建零件…")
        self.new_button.clicked.connect(self.new_requested.emit)
        self.choose_source_button = QPushButton("选择工程图来源…")
        self.choose_source_button.clicked.connect(self.choose_source_requested.emit)
        for button in (
            self.choose_source_button,
            self.sketch_view_button,
            self.generate_button,
            self.sketch_button,
            self.model_button,
            self.open_button,
            self.new_button,
        ):
            button.setMinimumHeight(36)
            button.setStyleSheet("QPushButton { border: 1px solid palette(mid); }")
            start_layout.addWidget(button)
        self.generate_button.setStyleSheet(
            "QPushButton:enabled { background: palette(highlight); color: palette(highlighted-text); "
            "border: 1px solid palette(highlight); font-weight: 600; }"
            "QPushButton:disabled { border: 1px solid palette(mid); }"
        )
        self.sketch_view_button.setStyleSheet(self.generate_button.styleSheet())
        steps = QLabel(
            "选定来源、纸张和比例后，单击画布放置。\n"
            "Enter 完成，Esc 取消；完成后可在图中选择轮廓添加标注。"
        )
        steps.setMinimumHeight(64)
        steps.setWordWrap(True)
        start_layout.addWidget(steps)
        start_layout.addStretch()
        self.pages.addWidget(self.start_page)
        self.pages.setCurrentWidget(self.start_page)
        self.setCentralWidget(self.pages)
        self.toolbar = self.addToolBar("工程图")
        self.toolbar.setObjectName("drawingToolbar")
        self.sheet_action = QAction("新建图纸", self)
        self.sketch_view_action = QAction("放置草图平面视图", self)
        self.sketch_view_action.triggered.connect(self.begin_sketch_placement)
        self.base_action = QAction("从模型生成投影", self)
        self.section_action = QAction("创建剖视（开发中）", self)
        self.detail_action = QAction("创建详图（开发中）", self)
        self.update_action = QAction("更新视图", self)
        self.dxf_action = QAction("导出 DXF", self)
        self.pdf_action = QAction("导出 PDF", self)
        self.dxf_action.triggered.connect(lambda: self.choose_export("dxf"))
        self.pdf_action.triggered.connect(lambda: self.choose_export("pdf"))
        self.delete_action = QAction("删除视图", self)
        self.confirm_delete_action = QAction("确认删除（Enter）", self)
        self.confirm_delete_action.setVisible(False)
        self.cancel_update_action = QAction("取消更新", self)
        for action in (
            self.sheet_action,
            self.sketch_view_action,
            self.base_action,
            self.section_action,
            self.detail_action,
            self.update_action,
            self.delete_action,
            self.confirm_delete_action,
            self.cancel_update_action,
            self.dxf_action,
            self.pdf_action,
        ):
            self.toolbar.addAction(action)
            action.setEnabled(False)
        self.delete_action.triggered.connect(self.preview_delete)
        self.confirm_delete_action.triggered.connect(self.confirm_delete)
        self.cancel_update_action.triggered.connect(self.cancel_update)
        self.sheet_action.triggered.connect(self.create_sheet)
        self.base_action.triggered.connect(self.begin_placement)
        self.section_action.triggered.connect(self.begin_section)
        self.detail_action.triggered.connect(self.begin_detail)
        self.update_action.triggered.connect(self.update_requested)
        self.settings_tabs = QTabWidget()
        settings = QWidget()
        form = QFormLayout(settings)
        self.sketch_source = QComboBox()
        self.sketch_source.setToolTip("选择当前文档中已完成的草图；按草图局部 U/V 坐标放到图纸。")
        self.paper = QComboBox()
        self.paper.addItems(
            [f"{paper} {direction}" for paper in PAPER_SIZES for direction in ("横向", "纵向")]
        )
        self.templates = DrawingTemplatePanel()
        self._settings_sheet: DrawingSheet | None = None
        self.templates.selection_changed.connect(self._template_selected)
        self.templates.preview_button.clicked.connect(self._preview_template)
        self.angle = QComboBox()
        self.angle.addItems(["第一角", "第三角"])
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.001, 1000)
        self.scale.setDecimals(3)
        self.scale.setValue(1)
        self.direction = QComboBox()
        self.direction.addItems(["前视", "后视", "俯视", "仰视", "左视", "右视", "等轴测"])
        self.include_isometric = QCheckBox("同时放置等轴测视图")
        self.include_isometric.setToolTip(
            "放置基准视图后，沿对角方向单击放置等轴测视图；水平或垂直方向放置正投影视图。"
        )
        self.detail_scale_factor = QDoubleSpinBox()
        self.detail_scale_factor.setRange(1, 100)
        self.detail_scale_factor.setDecimals(2)
        self.detail_scale_factor.setValue(2)
        self.detail_scale_factor.setSuffix(" 倍")
        self.detail_scale_factor.setToolTip("创建详图时相对来源视图的放大倍数。")
        self.title = QLineEdit()
        self.title.setPlaceholderText("图纸名称")
        self.hint = QLabel("先创建图纸，再在画布放置基准和投影视图。Enter 完成，Esc 取消。")
        self.hint.setWordWrap(True)
        for name, widget in [
            ("草图来源", self.sketch_source),
            ("纸张", self.paper),
            ("投影法", self.angle),
            ("比例", self.scale),
            ("基准方向", self.direction),
            ("附加视图", self.include_isometric),
            ("详图放大", self.detail_scale_factor),
            ("标题", self.title),
        ]:
            form.addRow(name, widget)
        apply_settings = QPushButton("应用图纸设置")
        apply_settings.clicked.connect(self.apply_sheet_settings)
        form.addRow(apply_settings)
        self.settings_tabs.addTab(settings, "设置")
        template_scroll = QScrollArea()
        template_scroll.setWidgetResizable(True)
        template_scroll.setWidget(self.templates)
        self.settings_tabs.addTab(template_scroll, "模板")
        template_entry = QPushButton("选择 / 导入图纸模板…")
        template_entry.clicked.connect(lambda: self.settings_tabs.setCurrentWidget(template_scroll))
        form.insertRow(0, template_entry)
        self.view_properties = QWidget()
        view_form = QFormLayout(self.view_properties)
        self.selected_view_label = QLabel("在图中选择视图")
        self.selected_scale = QDoubleSpinBox()
        self.selected_scale.setRange(0.001, 1000)
        self.selected_scale.setDecimals(3)
        apply_scale = QPushButton("应用比例")
        restore_scale = QPushButton("恢复继承比例")
        alignment = QPushButton("解除 / 恢复对齐")
        self.hidden_lines = QCheckBox("显示隐藏线")
        self.tangent_lines = QCheckBox("显示相切线")
        restore_display = QPushButton("恢复继承显示")
        view_form.addRow(self.selected_view_label)
        view_form.addRow("纸上比例", self.selected_scale)
        for control in (
            apply_scale,
            restore_scale,
            alignment,
            self.hidden_lines,
            self.tangent_lines,
            restore_display,
        ):
            view_form.addRow(control)
        apply_scale.clicked.connect(self.apply_selected_scale)
        restore_scale.clicked.connect(self.restore_selected_scale)
        alignment.clicked.connect(self.toggle_selected_alignment)
        self.hidden_lines.toggled.connect(self.apply_selected_display)
        self.tangent_lines.toggled.connect(self.apply_selected_display)
        restore_display.clicked.connect(self.restore_selected_display)
        self.settings_tabs.addTab(self.view_properties, "视图")
        self.view_properties.setEnabled(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["图形信息"])
        self.tree.itemClicked.connect(self._select_tree_sheet)
        self.settings_tabs.addTab(self.tree, "图形信息")
        self.addToolBarBreak()
        self.annotation_toolbar = self.addToolBar("工程图标注")
        self.annotation_toolbar.setObjectName("drawingAnnotationToolbar")
        self.annotations = DrawingAnnotationTools(
            self.canvas,
            self.annotation_toolbar,
            lambda: self.state,
            self.projections,
            self._execute,
            self._render,
            self._set_message,
            self._annotation_source_clean,
            self._prepare_dimension,
            execute_with_success=self._execute,
        )
        self.annotation_page = QScrollArea()
        self.annotation_page.setWidgetResizable(True)
        self.annotation_page.setFrameShape(QScrollArea.Shape.NoFrame)
        self.annotation_page.setWidget(self.annotations)
        self.settings_tabs.addTab(self.annotation_page, "标注")
        self.notes = DrawingNoteTools(
            self.canvas,
            lambda: self.state,
            lambda: self.sheet_id,
            self._execute,
            self._render,
            self._set_message,
        )
        self.notes_page = QScrollArea()
        self.notes_page.setWidgetResizable(True)
        self.notes_page.setFrameShape(QScrollArea.Shape.NoFrame)
        self.notes_page.setWidget(self.notes)
        self.settings_tabs.addTab(self.notes_page, "文本")
        self.text_action = QAction(cad_icon("document"), "文本标注", self)
        self.text_action.setToolTip("在图纸上直接输入说明文字；Ctrl+Enter 完成，Esc 取消")
        self.text_action.triggered.connect(self.begin_text)
        self.dimension_menu = QToolButton()
        self.dimension_menu.setText("尺寸标注")
        self.dimension_menu.setIcon(cad_icon("dimension"))
        self.dimension_menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.dimension_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.dimension_menu)
        for action in self.annotations.tool_actions.values():
            menu.addAction(action)
        self.dimension_menu.setMenu(menu)
        self.toolbar.insertWidget(self.sketch_view_action, self.dimension_menu)
        self.toolbar.insertAction(self.sketch_view_action, self.text_action)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        side_text = QToolButton()
        side_text.setDefaultAction(self.text_action)
        side_text.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        annotation_form = cast("QFormLayout", self.annotations.layout())
        annotation_form.insertRow(0, side_text)
        self.canvas.annotation_edit_requested.connect(self._edit_annotation)
        self.parameter_dock = QDockWidget("工程图功能", self)
        self.parameter_dock.setObjectName("drawingParameterDock")
        self.parameter_dock.setWidget(self.settings_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock)
        self.resizeDocks([self.parameter_dock], [260], Qt.Orientation.Horizontal)
        self.canvas.paper_clicked.connect(self._click)
        self.canvas.paper_moved.connect(self._move)
        self.canvas.commit_requested.connect(self._confirm_canvas)
        self.canvas.cancel_requested.connect(self._cancel_canvas)
        self.canvas.view_selected.connect(self._selected_view_changed)
        self.canvas.view_dragged.connect(self._view_dragged)
        self.canvas.drag_cancelled.connect(self._clear_grip_preview)
        self.canvas.alignment_requested.connect(self._alignment_grip)
        self.canvas.delete_requested.connect(self.preview_delete)
        self.title.editingFinished.connect(self._edit_sheet)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        if unit is not None:
            unit.busy_changed.connect(self._busy_changed)
        self._set_message("工程图尺寸为关联测量尺寸；模型修改请切换 3D图。")
        self._update_start_page()

    def _show_annotation_tab(self, widget: QWidget) -> None:
        self._dock_visible = True
        self.parameter_dock.show()
        self.settings_tabs.setCurrentWidget(
            self.annotation_page if widget is self.annotations else self.notes_page
        )

    def _prepare_dimension(self) -> bool:
        if self.loaded is None or (self.unit is not None and self.unit.is_busy):
            return False
        if not self._view_edit_finished():
            return False
        if not self._annotation_finished():
            return False
        if self.placement is not None:
            self._set_message("请先完成或取消当前视图放置，再标尺寸。")
            return False
        if self.notes.pending:
            self._set_message("请先完成文字（Ctrl+Enter），或按 Esc 取消后再标尺寸。")
            return False
        self.canvas.selected_note = None
        self.notes.select(None)
        self._show_annotation_tab(self.annotations)
        return True

    def _annotation_finished(self) -> bool:
        if self.annotations.pending:
            self._set_message("请先完成或取消当前标注，再执行其他操作。")
            return False
        return True

    def begin_text(self) -> None:
        if self.loaded is None or (self.unit is not None and self.unit.is_busy):
            return
        if not self._view_edit_finished():
            return
        if not self._annotation_finished():
            return
        if self.placement is not None or self._start_after_sheet is not None:
            self._set_message("请先按 Enter 完成视图放置，或 Esc 取消，再添加文字。")
            return
        if self.notes.pending:
            return
        if self.sheet_id is None:
            self.create_sheet(self.begin_text)
            return
        self.annotations.cancel()
        self.canvas.cancel_drag()
        self.canvas.select_view(None)
        self._show_annotation_tab(self.notes)
        self.notes.begin()

    def _set_message(self, text: str) -> None:
        self.hint.setText(text)
        self.message.emit(text)

    def bind_document(self, loaded: LoadedDocument, session_id: int) -> None:
        if self.loaded is loaded:
            self.session_id = session_id
            self.refresh()
            return
        self.notes.cancel()
        self.notes.select(None)
        self.annotations.cancel()
        self.annotations.select(None)
        self.loaded, self.session_id = loaded, session_id
        self._start_after_sheet = None
        self._ghost = None
        self.placement = None
        self.section_placement = None
        self._section_cursor = None
        self.detail_placement = None
        self._detail_cursor = None
        self.settings_tabs.setEnabled(self.unit is None or not self.unit.is_busy)
        self._placement_stale = False
        self.canvas.placing = False
        self.updates.sync(session_id, "", {})
        self._source_snapshot = None
        self.sheet_id = None
        self._preview_params = None
        self._pending_delete = None
        self.canvas.select_view(None)
        self.canvas.deletion_preview.clear()
        self._pending = False
        self._snapshot_inflight = False
        enabled = True
        self.annotation_toolbar.setEnabled(enabled)
        for action in (
            self.sheet_action,
            self.sketch_view_action,
            self.base_action,
            self.section_action,
            self.detail_action,
            self.update_action,
            self.cancel_update_action,
            self.dxf_action,
            self.pdf_action,
        ):
            action.setEnabled(enabled)
        self.refresh()

    def _has_projection_source(self) -> bool:
        return bool(
            self.loaded is not None
            and self.loaded.document.document_kind in {"part", "drawing"}
            and self.services is not None
            and self.services.kernel.body_ids
        )

    @property
    def has_pending_view_edit(self) -> bool:
        return (
            self._preview_params is not None
            or self._pending_delete is not None
            or self.section_placement is not None
            or self.detail_placement is not None
        )

    def _view_edit_finished(self) -> bool:
        if self.has_pending_view_edit:
            self._set_message("请先完成或取消当前视图操作，再启动其他命令。")
            return False
        return True

    def _allow_canvas_view_selection(self, identity: UUID | None) -> bool:
        if (
            (self.section_placement is not None or self.detail_placement is not None)
            and self.canvas.placing
            and identity is None
        ):
            return True
        if self.has_pending_view_edit and identity != self.canvas.selected_view:
            self._set_message("请先完成或取消当前视图操作，再选择其他视图。")
            return False
        return True

    def _update_start_page(self) -> None:
        has_source = self._has_projection_source()
        busy = self.unit is not None and self.unit.is_busy
        has_sketch = self.sketch_source.count() > 0 and self.loaded is not None
        self.sketch_view_button.setEnabled(has_sketch and not busy)
        self.sketch_view_action.setEnabled(has_sketch and not busy)
        self.generate_button.setEnabled(has_source and not busy)
        self.base_action.setEnabled(has_source and not busy)
        self.open_button.setEnabled(self.services is not None and not busy)
        self.new_button.setEnabled(self.services is not None and not busy)
        self.choose_source_button.setVisible(
            self.loaded is not None and self.loaded.document.document_kind == "drawing"
        )
        self.choose_source_button.setEnabled(self.source_selection_available and not busy)
        self.choose_source_button.setToolTip(
            "选择已打开的零件或独立二维图作为来源。"
            if self.source_selection_available
            else "当前窗口不支持多文档来源选择。"
        )
        self.sketch_button.setEnabled(self.loaded is not None and not busy)
        self.model_button.setEnabled(
            self.loaded is not None and self.loaded.document.document_type == "part" and not busy
        )
        if self.loaded is None:
            description = "先新建或打开文件；完成草图后可直接放到图纸，也可从三维实体生成投影。"
        elif self.loaded.document.document_kind == "drawing" and not has_source:
            description = "请选择来源零件或独立二维草图，然后放置工程视图。"
        elif self.loaded.document.document_type != "part" and not has_source:
            description = (
                "当前是独立二维图。选择右侧已完成的草图，点击“放置草图平面视图”即可入纸。"
                "若来源列表为空，请先返回平面草图绘制并点击“完成草图”。"
            )
        elif has_source:
            description = "可以直接放置已完成的草图平面视图，也可以从当前三维模型生成投影视图。"
        else:
            description = (
                "完成草图后，可直接点击“放置草图平面视图”入纸，无需建模。"
                "如需机械三视图，请到 3D图使用拉伸或旋转生成实体后再投影。"
            )
        self.start_description.setText(description)
        empty = (
            self.placement is None
            and not (hasattr(self, "notes") and self.notes.pending)
            and not any(note.sheet_id == self.sheet_id for note in self.state.notes)
            and not any(view.sheet_id == self.sheet_id for view in self.state.views)
        )
        self.pages.setCurrentWidget(self.start_page if empty else self.drawing_page)

    def _reconcile_placement(self) -> None:
        if self.placement is None or self.placement.sheet.sheet_id in {
            sheet.sheet_id for sheet in self.state.sheets
        }:
            return
        self.placement = None
        self._ghost = None
        self._placement_stale = False
        self._pending = False
        self.canvas.placing = False
        self._set_message("目标图纸已删除或撤销，未提交的视图放置已取消。")

    def _refresh_sketch_sources(self) -> None:
        selected = self.sketch_source.currentData()
        self.sketch_source.clear()
        if self.services is None or self.loaded is None:
            return
        for index, sketch in enumerate(self.services.kernel.sketches, start=1):
            if sketch.entities:
                self.sketch_source.addItem(
                    f"草图 {index} · {sketch.sketch_id[:8]} · {len(sketch.entities)} 图元",
                    sketch.sketch_id,
                )
        index = self.sketch_source.findData(selected)
        if index >= 0:
            self.sketch_source.setCurrentIndex(index)

    def refresh(self) -> None:
        if self.services is None:
            return
        self.state = self.services.kernel.drawing_state
        self._refresh_sketch_sources()
        self._reconcile_placement()
        if self.notes.pending and self.sheet_id not in {
            sheet.sheet_id for sheet in self.state.sheets
        }:
            self.notes.cancel()
        if (
            self.placement is not None
            and self._placement_source_fingerprint
            != self.services.kernel.drawing_source_fingerprint
        ):
            self._placement_stale = True
            self.canvas.placing = False
            self._pending = False
            self._set_message("模型已变更，工程图草稿已保留；请点更新视图以更新预览后继续。")
        previous_sheet = self.sheet_id
        if self.sheet_id not in {s.sheet_id for s in self.state.sheets}:
            self.sheet_id = self.state.sheets[0].sheet_id if self.state.sheets else None
        if self.sheet_id is not None and (
            previous_sheet != self.sheet_id
            or self._settings_sheet != self.state.sheet(self.sheet_id)
        ):
            self._load_sheet_settings()
        self.tree.clear()
        self._view_items.clear()
        for sheet in self.state.sheets:
            item = QTreeWidgetItem([sheet.name])
            item.setData(0, Qt.ItemDataRole.UserRole, sheet.sheet_id)
            self.tree.addTopLevelItem(item)
            for view in self.state.views:
                if view.sheet_id == sheet.sheet_id:
                    child = QTreeWidgetItem([view.direction])
                    child.setData(0, Qt.ItemDataRole.UserRole, view.view_id)
                    item.addChild(child)
                    self._view_items[view.view_id] = child
            item.setExpanded(True)
        self._render()
        self._selected_view_changed(self.canvas.selected_view, False)
        if self.state.views:
            self.request_update()

    def _execute(
        self, command: str, params: dict[str, object], success: Callable[[], None] | None = None
    ) -> None:
        loaded, unit = self.loaded, self.unit
        if loaded is None or unit is None:
            return

        def finish(result: ExecutionResult) -> None:
            if result.error:
                self._start_after_sheet = None
                self._set_message(f"工程图操作失败：{result.error}")
                return
            self.refresh()
            if success is not None:
                success()

        if not unit.submit(
            lambda: loaded.bus.execute(command, params, confirmed_by="local"),
            operation=command,
            session_id=self.session_id,
            on_complete=finish,
        ):
            self._set_message("当前操作尚未结束，请稍后再试；图中草稿已保留。")

    def create_sheet(self, after: Callable[[], None] | None = None) -> None:
        if self.loaded is None:
            return
        if not self._view_edit_finished():
            return
        if not self._annotation_finished():
            return
        if self.placement is not None:
            self._set_message("请先完成或取消当前视图放置，再新建图纸。")
            return
        if self.notes.pending:
            self._set_message("文字尚未提交：请先 Ctrl+Enter 完成或 Esc 取消，再新建图纸。")
            return
        sheet = self._configured_sheet(uuid4())
        sheet = replace(
            sheet,
            name=self.title.text().strip() or f"工程图 {len(self.state.sheets) + 1}",
            projection_angle="first" if self.angle.currentIndex() == 0 else "third",
            default_scale=self.scale.value(),
            title=self._title_values(),
        )

        def done() -> None:
            self.sheet_id = sheet.sheet_id
            self._render()
            source = self._start_after_sheet
            self._start_after_sheet = None
            if source is not None:
                self._begin_source_placement(source)
            if callable(after):
                after()

        self._execute("drawing.sheet.create", drawing_object_mapping(sheet), done)

    def _load_sheet_settings(self) -> None:
        if self.sheet_id is None:
            return
        sheet = self.state.sheet(self.sheet_id)
        self._settings_sheet = sheet
        match = next(
            (
                i
                for i, size in enumerate(PAPER_SIZES.values())
                if tuple(sorted(sheet.size_mm)) == size
            ),
            None,
        )
        if match is not None:
            self.paper.setCurrentIndex(
                match * 2 + (0 if sheet.size_mm[0] > sheet.size_mm[1] else 1)
            )
        self.templates.load_sheet(sheet)
        self.angle.setCurrentIndex(0 if sheet.projection_angle == "first" else 1)
        self.scale.setValue(sheet.default_scale)
        self.title.setText(dict(sheet.title).get("标题", sheet.name))

    def _select_tree_sheet(self, item: QTreeWidgetItem, _column: int) -> None:
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(identity, UUID):
            return
        sheets = {sheet.sheet_id for sheet in self.state.sheets}
        views = {view.view_id: view.sheet_id for view in self.state.views}
        target_sheet = identity if identity in sheets else views.get(identity)
        pending = (
            self.notes.pending
            or self.annotations.pending
            or self.placement is not None
            or self.has_pending_view_edit
        )
        switching_view = (
            self.has_pending_view_edit
            and identity in views
            and identity != self.canvas.selected_view
        )
        if (
            target_sheet is not None
            and pending
            and (target_sheet != self.sheet_id or switching_view)
        ):
            self._set_message("请先完成或取消当前文字、标注或视图操作，再切换图纸或视图。")
            selected_view = self.canvas.selected_view
            selected = self._view_items.get(selected_view) if selected_view is not None else None
            if selected is None:
                selected = next(
                    (
                        top
                        for index in range(self.tree.topLevelItemCount())
                        if (top := self.tree.topLevelItem(index)) is not None
                        and top.data(0, Qt.ItemDataRole.UserRole) == self.sheet_id
                    ),
                    None,
                )
            if selected is not None:
                self.tree.setCurrentItem(selected)
            else:
                self.tree.clearSelection()
            return
        if identity == self.sheet_id and pending:
            return
        if identity in sheets:
            self.notes.cancel()
            self.cancel_placement()
            self.sheet_id = identity
            self._load_sheet_settings()
            self._render()
        elif identity in views:
            if self.sheet_id != self.state.view(identity).sheet_id:
                self.notes.cancel()
            self.sheet_id = self.state.view(identity).sheet_id
            self._load_sheet_settings()
            self._render()
            self.canvas.select_view(identity)

    def apply_sheet_settings(self) -> None:
        if not self._view_edit_finished():
            return
        if not self._annotation_finished():
            return
        if self.sheet_id is None:
            self.create_sheet()
            return
        if self.notes.pending or self.placement is not None:
            self._set_message("请先完成或取消图中文字/视图放置，再应用模板。")
            return
        sheet = self._configured_sheet(self.sheet_id)
        self._execute(
            "drawing.sheet.update",
            {
                "sheet_id": str(self.sheet_id),
                "size_mm": list(sheet.size_mm),
                "template": sheet.template.to_mapping() if sheet.template is not None else None,
                "projection_angle": "first" if self.angle.currentIndex() == 0 else "third",
                "default_scale": self.scale.value(),
                "name": self.title.text().strip() or "工程图",
                "title": [list(pair) for pair in self._title_values()],
            },
            self._sheet_applied,
        )

    def _sheet_applied(self) -> None:
        self._load_sheet_settings()
        self.pages.setCurrentWidget(self.drawing_page)
        self._set_message(
            "图纸模板已应用；已有视图位置与比例保持不变，请检查是否进入图框或标题栏。"
        )

    def _title_values(self) -> tuple[tuple[str, str], ...]:
        values = self.templates.values()
        values["标题"] = self.title.text().strip()
        return tuple(
            (key, value) for key, value in values.items() if value or key not in ("比例", "页码")
        )

    def _template_selected(self) -> None:
        self.paper.setEnabled(str(self.templates.selector.currentData()) in ("GB", "ISO", "legacy"))

    def _configured_sheet(self, identity: UUID) -> DrawingSheet:
        paper = list(PAPER_SIZES)[self.paper.currentIndex() // 2]
        landscape = self.paper.currentIndex() % 2 == 0
        template = self.templates.template_for(
            paper, landscape, "first" if self.angle.currentIndex() == 0 else "third"
        )
        sheet = DrawingSheet.for_paper(identity, paper, landscape=landscape)
        return replace(sheet, size_mm=template.size_mm, template=template) if template else sheet

    def _preview_template(self) -> None:
        template = self._configured_sheet(uuid4()).template
        if template is None:
            self._set_message("当前为旧版简单图框，请选择 GB、ISO 或导入模板进行预览。")
            return
        self.templates.show_preview(template, self._title_values())

    def _edit_sheet(self) -> None:
        if self.sheet_id is not None:
            sheet = self.state.sheet(self.sheet_id)
            if self.title.text() == dict(sheet.title).get("标题", sheet.name):
                return
            # This automatic title commit must not reload unrelated form drafts.
            # Undo/redo still reloads settings because its snapshot differs.
            self._settings_sheet = replace(
                sheet, title=tuple({**dict(sheet.title), "标题": self.title.text()}.items())
            )
            self._execute(
                "drawing.sheet.update",
                {
                    "sheet_id": str(self.sheet_id),
                    "title": [
                        list(pair)
                        for pair in {**dict(sheet.title), "标题": self.title.text()}.items()
                    ],
                },
            )

    def begin_placement(self) -> None:
        if not self._has_projection_source():
            self._set_message("当前没有可投影的三维实体；可直接放置草图平面视图，或先拉伸建模。")
            self._update_start_page()
            return
        self._begin_source_placement(SourceBinding())

    def begin_sketch_placement(self) -> None:
        identity = self.sketch_source.currentData()
        if not isinstance(identity, str):
            self._set_message("请先在平面草图中绘制并完成草图，再选择右侧草图来源。")
            return
        self._begin_source_placement(SourceBinding("sketch", identity))

    def begin_section(self) -> None:
        if self.loaded is None or self.services is None or self.unit is None or self.unit.is_busy:
            return
        if not self._view_edit_finished() or not self._annotation_finished():
            return
        if self.placement is not None or self.notes.pending:
            self._set_message("请先完成或取消当前视图或文字操作。")
            return
        identity = self.canvas.selected_view
        if identity is None or not self._annotation_source_clean(identity):
            self._set_message("请先选择一个已更新的实体正投影视图。")
            return
        self.annotations.cancel()
        self.canvas.cancel_drag()
        try:
            self.section_placement = SectionPlacement(
                self.state, identity, self.services.kernel.drawing_source_fingerprint
            )
        except ValueError as error:
            self._set_message(str(error))
            return
        self._section_cursor = None
        self.canvas.placing = True
        self.settings_tabs.setEnabled(False)
        self._set_message("依次单击剖切线起点、终点和剖视放置位置；Enter 完成，Esc 取消。")
        self.canvas.setFocus()

    def _cancel_section(self) -> None:
        self.section_placement = None
        self._section_cursor = None
        self.canvas.placing = False
        self.settings_tabs.setEnabled(self.unit is None or not self.unit.is_busy)
        self._render()
        self._set_message("剖视放置已结束。")

    def begin_detail(self) -> None:
        if self.loaded is None or self.services is None or self.unit is None or self.unit.is_busy:
            return
        if not self._view_edit_finished() or not self._annotation_finished():
            return
        if self.placement is not None or self.notes.pending:
            self._set_message("请先完成或取消当前视图或文字操作。")
            return
        identity = self.canvas.selected_view
        if identity is None or not self._annotation_source_clean(identity):
            self._set_message("请先选择一个已更新的实体投影视图。")
            return
        self.annotations.cancel()
        self.canvas.cancel_drag()
        try:
            self.detail_placement = DetailPlacement(
                self.state,
                identity,
                self.services.kernel.drawing_source_fingerprint,
                scale_factor=self.detail_scale_factor.value(),
            )
        except ValueError as error:
            self._set_message(str(error))
            return
        self._detail_cursor = None
        self.canvas.placing = True
        self.settings_tabs.setEnabled(False)
        self._set_message("依次单击详图圆心、半径和放置位置；Enter 完成，Esc 取消。")
        self.canvas.setFocus()

    def _cancel_detail(self) -> None:
        self.detail_placement = None
        self._detail_cursor = None
        self.canvas.placing = False
        self.settings_tabs.setEnabled(self.unit is None or not self.unit.is_busy)
        self._render()
        self._set_message("详图放置已结束。")

    def _commit_detail(self) -> None:
        placement = self.detail_placement
        if placement is None or self.services is None:
            return
        if not placement.matches(
            self.services.kernel.drawing_state, self.services.kernel.drawing_source_fingerprint
        ):
            self._set_message("来源或父视图已变化；请取消草稿并重新选择详图区域。")
            return
        try:
            view = placement.make_view()
        except ValueError as error:
            self._set_message(str(error))
            return
        self._execute("drawing.view.create", drawing_object_mapping(view), self._cancel_detail)

    def _commit_section(self) -> None:
        placement = self.section_placement
        if placement is None or self.services is None:
            return
        if not placement.matches(
            self.services.kernel.drawing_state, self.services.kernel.drawing_source_fingerprint
        ):
            self._set_message("来源或父视图已变化；请取消草稿并重新选择剖切线。")
            return
        try:
            view = placement.make_view()
        except ValueError as error:
            self._set_message(str(error))
            return
        self._execute("drawing.view.create", drawing_object_mapping(view), self._cancel_section)

    def _begin_source_placement(self, source: SourceBinding) -> None:
        if self.loaded is None or self.services is None:
            return
        if not self._view_edit_finished():
            return
        if not self._annotation_finished():
            return
        if self.placement is not None or self._start_after_sheet is not None:
            self._set_message("请先按 Enter 完成当前放置，或按 Esc 取消后重新选择来源。")
            return
        if self.notes.pending:
            self._set_message("请先完成文字（Ctrl+Enter），或按 Esc 取消。")
            return
        self.annotations.cancel()
        if source.kind == "sketch" and source.sketch_id not in {
            sketch.sketch_id for sketch in self.services.kernel.sketches if sketch.entities
        }:
            self._set_message("草图来源不存在或为空，请先完成草图。")
            return
        if self.sheet_id is None:
            self._start_after_sheet = source
            self.create_sheet()
            return
        directions = ("front", "back", "top", "bottom", "left", "right")
        isometric = source.kind == "current_part" and self.direction.currentIndex() == len(
            directions
        )
        basis = (
            isometric_basis()
            if isometric
            else projected_basis(
                ViewBasis(), directions[self.direction.currentIndex() % len(directions)]
            )
        )
        self._placement_stale = False
        self._placement_source_fingerprint = self.services.kernel.drawing_source_fingerprint
        self.placement = ViewPlacement(
            self.state.sheet(self.sheet_id),
            scale=self.scale.value(),
            basis=basis,
            source=source,
            allow_projected=not isometric,
            include_isometric=(
                source.kind == "current_part" and self.include_isometric.isChecked()
            ),
        )
        self.canvas.placing = False
        self._set_message("正在准备投影；完成后在画布单击放置基准视图。")
        self._render()
        self.canvas.setFocus()
        self.request_update()

    def _target_bases(self) -> dict[UUID, ViewBasis]:
        bases = {v.view_id: self.state.effective_basis(v.view_id) for v in self.state.views}
        if self.placement is not None and not self._placement_stale:
            placement = self.placement
            bases[placement.base_id] = placement.basis
            if placement.source.kind == "current_part" and placement.allow_projected:
                for direction in ("top", "bottom", "left", "right"):
                    bases[placement.projected_id(direction)] = projected_basis(
                        placement.basis, direction
                    )
                if placement.include_isometric:
                    bases[placement.projected_id("isometric")] = isometric_basis()
        return bases

    def _sync_targets(self) -> str:
        assert self.services is not None
        self.state = self.services.kernel.drawing_state
        self._reconcile_placement()
        fingerprint = self.services.kernel.drawing_source_fingerprint
        if (
            self.placement is not None
            and not self._placement_stale
            and self._placement_source_fingerprint != fingerprint
        ):
            self._placement_stale = True
            self.canvas.placing = False
            self._set_message("模型已变更，草稿已保留；请点更新视图以更新预览后继续。")
        sketch_ids = {v.view_id: v.source.sketch_id for v in self.state.views}
        sections = {
            view.view_id: (
                view.section.plane(self.state.effective_basis(view.parent_id)),
                2.5 / self.state.effective_scale(view.view_id),
            )
            for view in self.state.views
            if view.section is not None and view.parent_id is not None
        }
        details = {
            view.view_id: view.detail for view in self.state.views if view.detail is not None
        }
        if self.placement is not None:
            sketch_ids[self.placement.base_id] = self.placement.source.sketch_id
        self.updates.sync(
            self.session_id,
            fingerprint,
            self._target_bases(),
            sketch_ids=sketch_ids,
            sections=sections,
            details=details,
        )
        return fingerprint

    def update_requested(self) -> None:
        self._placement_stale = False
        if self.services is not None:
            self._placement_source_fingerprint = self.services.kernel.drawing_source_fingerprint
        self.updates.retry()
        self.request_update()

    def request_update(self) -> None:
        if self.services is None or self.unit is None or self.loaded is None:
            return
        if self.unit.is_busy:
            self._pending = True
            return
        fingerprint = self._sync_targets()
        batch = self.updates.begin(source="sketch")
        if batch is not None:
            sketches = {sketch.sketch_id: sketch for sketch in self.services.kernel.sketches}
            results: list[ProjectionResult] = []
            for request in batch.requests:
                sketch = sketches.get(request.sketch_id or "")
                if sketch is None:
                    results.append(
                        ProjectionResult(
                            request.view_id,
                            fingerprint,
                            request.generation,
                            (),
                            ("草图来源不存在，请重新选择来源",),
                        )
                    )
                else:
                    results.append(project_sketch(sketch, request))
            self._projection_ready(self.updates.finish(batch, tuple(results)))
        self._pending = self.updates.has_pending
        self._render()
        if not self._pending or self._future is not None or self._snapshot_inflight:
            return
        if (
            self._source_snapshot is not None
            and self._source_snapshot.source_fingerprint == fingerprint
        ):
            self._submit_projection()
            return
        self._snapshot_inflight = True
        self._pending = False
        services = self.services

        def captured(result: ExecutionResult) -> None:
            self._snapshot_inflight = False
            if result.error or not isinstance(result.value, DrawingSourceSnapshot):
                batch = self.updates.begin(source="current_part")
                if batch is not None:
                    self.updates.finish(
                        batch, (), error=result.error or "Source snapshot unavailable"
                    )
                self._set_message(f"无法生成工程视图：{result.error or '来源快照不可用'}")
                self._render()
                return
            self._source_snapshot = result.value
            self.request_update()

        if not self.unit.submit(
            services.kernel.drawing_snapshot,
            operation="drawing-source-snapshot",
            session_id=self.session_id,
            on_complete=captured,
        ):
            self._snapshot_inflight = False
            self._pending = True

    def _submit_projection(self) -> None:
        if self._source_snapshot is None:
            return
        batch = self.updates.begin(source="current_part")
        if batch is None:
            return
        try:
            if self._worker is None:
                self._worker = mycad_app.create_drawing_worker()
            self._future_batch = batch
            self._future = self._worker.submit(self._source_snapshot, batch.requests)
            self._pending = False
            self._set_message("正在更新工程视图；可继续切换工作区。")
        except (RuntimeError, BrokenProcessPool) as error:
            self.updates.finish(batch, (), error=str(error))
            if self._worker is not None:
                self._worker.restart()
            self._set_message(f"后台服务不可用，已准备重试：{error}")
        self._render()

    def _busy_changed(self, busy: bool) -> None:
        if busy:
            self.canvas.cancel_drag()
        self.canvas.setEnabled(not busy)
        self.settings_tabs.setEnabled(
            not busy and self.section_placement is None and self.detail_placement is None
        )
        self.text_action.setEnabled(not busy and self.loaded is not None)
        self.dimension_menu.setEnabled(not busy and self.loaded is not None)
        self._update_start_page()
        if not busy and self._pending:
            QTimer.singleShot(0, self, self.request_update)

    def _poll(self) -> None:
        future, batch = self._future, self._future_batch
        if (
            future is None
            or batch is None
            or not future.done()
            or self.unit is None
            or self.unit.is_busy
            or self.services is None
        ):
            return
        self._future = None
        self._future_batch = None
        self._sync_targets()
        try:
            accepted = self.updates.finish(batch, future.result())
        except Exception as error:
            self.updates.finish(batch, (), error=str(error))
            if isinstance(error, BrokenProcessPool) and self._worker is not None:
                self._worker.restart()
            self._set_message(f"投影失败，旧结果已标记过期：{error}")
            accepted = 0
        self._projection_ready(accepted)
        self._render()
        if self.updates.has_pending:
            self.request_update()

    def _projection_ready(self, accepted: int) -> None:
        if not accepted:
            failures = [
                self.updates.failure_message(identity)
                for identity in self._target_bases()
                if self.updates.status(identity) == "failed"
            ]
            if failures:
                reason = next((message for message in failures if message), "投影未生成")
                self._set_message(f"视图生成失败：{reason}；请更新视图重试。")
            return
        if (
            self.placement is not None
            and not self._placement_stale
            and self.updates.status(self.placement.base_id) == "clean"
        ):
            self.canvas.placing = True
            if self.placement.source.kind == "sketch":
                message = "单击放置草图平面视图；Enter 完成，Esc 取消。"
            elif not self.placement.allow_projected:
                message = "单击放置等轴测视图；Enter 完成，Esc 取消。"
            elif self.placement.include_isometric:
                message = (
                    "放置基准视图后，水平或垂直放置投影视图，对角放置等轴测；Enter 完成，Esc 取消。"
                )
            else:
                message = "单击放置基准视图，再沿方向放置投影视图；Enter 完成整组，Esc 取消。"
            self._set_message(message)
            if self.isVisible():
                self.canvas.setFocus()
        elif not self._placement_stale:
            if any(self.updates.status(view.view_id) == "failed" for view in self.state.views):
                self._set_message("部分视图更新失败，请查看图纸上的原因并重试。")
            elif self.updates.has_pending:
                self._set_message("部分视图已更新，其他视图仍在等待处理。")
            else:
                self._set_message("工程图已更新。")

    def cancel_update(self) -> None:
        self.updates.cancel()
        self._pending = False
        self._render()
        self._set_message("已停止接收本次投影结果；正在运行的后台任务会自行结束。")

    def _render(self) -> None:
        self._reconcile_placement()
        if self.sheet_id not in {sheet.sheet_id for sheet in self.state.sheets}:
            self.sheet_id = self.state.sheets[0].sheet_id if self.state.sheets else None
            if self.sheet_id is not None:
                self._load_sheet_settings()
        self._update_start_page()
        if self.sheet_id is None:
            self.drawing_status.hide()
            self.canvas.clear_scene()
            return
        state = self.state
        if self._preview_params is not None:
            try:
                state = apply_drawing_command(state, "drawing.view.update", self._preview_params)
            except ValueError:
                self._preview_params = None
        visible_ids = {v.view_id for v in state.views if v.sheet_id == self.sheet_id}
        if self.canvas.selected_view is not None and self.canvas.selected_view not in visible_ids:
            self.canvas.select_view(None)
        self.canvas.alignable_views = {v.view_id for v in state.views if v.parent_id is not None}
        self.canvas.view_statuses = {v.view_id: self.updates.status(v.view_id) for v in state.views}
        if self.placement is not None:
            existing = {v.view_id for v in state.views}
            views = [v for v in self.placement.pending if v.view_id not in existing]
            if self._ghost is not None and self._ghost.view_id not in existing:
                views = [v for v in views if v.view_id != self._ghost.view_id] + [self._ghost]
            state = replace(state, views=(*state.views, *views))
        state = self.annotations.preview(state)
        if hasattr(self, "notes"):
            state = self.notes.preview(state)
        scene = build_drawing_scene(state, self.sheet_id, self.projections)
        labels = {"clean": "已更新", "stale": "待更新", "updating": "更新中", "failed": "更新失败"}
        names: dict[ViewDirection, str] = {
            "front": "主视",
            "back": "后视",
            "top": "俯视",
            "bottom": "仰视",
            "left": "左视",
            "right": "右视",
        }
        issues = list(scene.issues)
        for view in state.views:
            status = self.updates.status(view.view_id)
            if view.source.kind == "sketch":
                name = "草图平面视图"
            elif view.section is not None:
                name = "剖视（开发中）"
            elif view.detail is not None:
                name = "局部详图（开发中）"
            elif view.parent_id is None and view.basis == isometric_basis():
                name = "等轴测"
            elif view.parent_id is None:
                name = next(
                    (
                        label
                        for direction, label in names.items()
                        if view.basis == projected_basis(ViewBasis(), direction)
                    ),
                    "自定义视图",
                )
            else:
                name = names[view.direction]
            item = self._view_items.get(view.view_id)
            if item is not None:
                item.setText(
                    0,
                    f"{name} · {self.state.effective_scale(view.view_id):g}:1 · {labels[status]}",
                )
            if view.sheet_id == self.sheet_id and status != "clean":
                issues.append(f"{name} {str(view.view_id)[:8]}：{labels[status]}")
        self.canvas.set_scene(replace(scene, issues=tuple(dict.fromkeys(issues))))
        statuses = [
            self.updates.status(view.view_id)
            for view in self.state.views
            if view.sheet_id == self.sheet_id
        ]
        warnings: list[str] = []
        for status, label in (
            ("stale", "待更新"),
            ("updating", "更新中"),
            ("failed", "更新失败"),
        ):
            count = statuses.count(status)
            if count:
                warnings.append(f"{count} 个视图{label}")
        failures = [
            self.updates.failure_message(view.view_id)
            for view in self.state.views
            if view.sheet_id == self.sheet_id and self.updates.status(view.view_id) == "failed"
        ]
        failures = list(dict.fromkeys(message for message in failures if message))
        if failures:
            warnings.append(f"原因：{failures[0]}")
        affected = {
            view.view_id
            for view in self.state.views
            if view.sheet_id == self.sheet_id and self.updates.status(view.view_id) != "clean"
        }
        if any(annotation.view_id in affected for annotation in self.state.annotations):
            warnings.append("更新后关联标注可能失联，请检查")
        orphaned = sum(
            item.status != "resolved" and item.view_id not in affected
            for item in scene.resolved_annotations
        )
        if orphaned:
            warnings.append(f"{orphaned} 个标注失联，请重新附着后出图")
        if any(
            view.sheet_id == self.sheet_id and view.section is not None for view in self.state.views
        ):
            warnings.append("剖视功能开发中，暂不能出图")
        if any(
            view.sheet_id == self.sheet_id and view.detail is not None for view in self.state.views
        ):
            warnings.append("局部详图功能开发中，暂不能出图")
        self.drawing_status.setText("；".join(warnings))
        self.drawing_status.setVisible(bool(warnings))
        if self.section_placement is not None:
            start = self.section_placement.start
            end = self.section_placement.end or self._section_cursor
            graphics = self.canvas.scene()
            if start is not None and end is not None:
                try:
                    line = LineCurve(start, end)
                except ValueError:
                    pass
                else:
                    target = self.section_placement.position or self._section_cursor
                    cross = (
                        (end[0] - start[0]) * (target[1] - start[1])
                        - (end[1] - start[1]) * (target[0] - start[0])
                        if self.section_placement.end is not None and target is not None
                        else 0
                    )
                    preview = (line,)
                    if abs(cross) > 1e-9 and target is not None:
                        marker = SectionMarker(
                            "", start, end, "left" if cross > 0 else "right", target
                        )
                        preview = section_marker_lines(replace(scene, section_markers=(marker,)))
                    for curve in preview:
                        item = graphics.addPath(curve_path(curve), paper_pen("SECTION"))
                        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        if self.detail_placement is not None and self.detail_placement.center is not None:
            center = self.detail_placement.center
            radius = self.detail_placement.radius_paper
            if radius is None and self._detail_cursor is not None:
                radius = math.dist(center, self._detail_cursor)
            if radius is not None and radius > 1e-9:
                item = self.canvas.scene().addPath(
                    curve_path(ArcCurve(center, radius)), paper_pen("DETAIL")
                )
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            if self.detail_placement.radius_paper is not None:
                target = self.detail_placement.position or self._detail_cursor
                if target is not None:
                    item = self.canvas.scene().addPath(
                        curve_path(
                            ArcCurve(
                                target,
                                self.detail_placement.scale_factor
                                * self.detail_placement.radius_paper,
                            )
                        ),
                        paper_pen("DETAIL"),
                    )
                    item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def _move(self, point: object) -> None:
        if self.section_placement is not None:
            self._section_cursor = cast("Point2", point)
            self._render()
            return
        if self.detail_placement is not None:
            self._detail_cursor = cast("Point2", point)
            self._render()
            return
        self.annotations.move_preview(cast("Point2", point))
        if self.placement is not None and self.canvas.placing:
            self._ghost = self.placement.preview(cast("Point2", point))
            self._render()

    def _click(self, point: object) -> None:
        if self.section_placement is not None:
            try:
                self.section_placement.click(cast("Point2", point))
            except ValueError as error:
                self._set_message(str(error))
            else:
                if self.section_placement.end is None:
                    self._set_message("请选择剖切线终点；Esc 取消。")
                elif self.section_placement.position is None:
                    self._set_message("请选择剖视放置位置及观察侧；Esc 取消。")
                else:
                    self._set_message("按 Enter 创建剖视，或继续单击调整位置；Esc 取消。")
            self._render()
            return
        if self.detail_placement is not None:
            try:
                self.detail_placement.click(cast("Point2", point))
            except ValueError as error:
                self._set_message(str(error))
            else:
                if self.detail_placement.radius_paper is None:
                    self._set_message("请选择详图圈半径；Esc 取消。")
                elif self.detail_placement.position is None:
                    self._set_message(
                        f"请选择详图放置位置；相对来源放大 {self.detail_placement.scale_factor:g} 倍。"
                    )
                else:
                    self._set_message("按 Enter 创建详图，或继续单击调整位置；Esc 取消。")
            self._render()
            return
        self.annotations.click(cast("Point2", point))
        if self.placement is not None and self.canvas.placing:
            candidate = self.placement.preview(cast("Point2", point))
            if candidate is not None and self.updates.status(candidate.view_id) != "clean":
                reason = self.updates.failure_message(candidate.view_id)
                self._set_message(
                    f"该视图尚未准备好{f'：{reason}' if reason else '，请等待或更新视图'}。"
                )
                return
            self.placement.click(cast("Point2", point))
            self._ghost = None
            self._render()

    def commit_placement(self) -> None:
        if self.placement is None or self._placement_stale or not self.canvas.placing:
            return
        if (
            self.services is not None
            and self._placement_source_fingerprint
            != self.services.kernel.drawing_source_fingerprint
        ):
            self.refresh()
            return
        views = self.placement.finish()
        if views:
            if any(self.updates.status(view.view_id) != "clean" for view in views):
                self._set_message("视图组中有投影尚未准备好，请更新后再提交。")
                return
            self._execute(
                "drawing.view.create",
                {"views": [drawing_object_mapping(v) for v in views]},
                self.cancel_placement,
            )

    def cancel_placement(self) -> None:
        self._start_after_sheet = None
        self.placement = None
        self._placement_stale = False
        self._ghost = None
        self.canvas.placing = False
        self._render()
        self.request_update()
        self._set_message("视图放置已结束。")

    def choose_export(self, kind: str) -> None:
        try:
            self.output_scene()
        except ValueError as error:
            self._set_message(str(error))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, f"导出工程图 {kind.upper()}", f"工程图.{kind}", f"{kind.upper()} (*.{kind})"
        )
        if filename:
            path = Path(filename)
            if path.suffix.lower() != f".{kind}":
                path = path.with_name(path.name + f".{kind}")
            self.export_to(kind, path)

    def output_scene(self) -> DrawingScene:
        if self.services is None or self.unit is None or self.unit.is_busy or self.sheet_id is None:
            raise ValueError("当前图纸尚未就绪，请等待更新完成")
        if (
            self.notes.pending
            or self.annotations.pending
            or (self.placement is not None and self.placement.pending)
            or self.has_pending_view_edit
        ):
            raise ValueError("图中预览尚未提交，请先完成或取消再出图")
        current = self.services.kernel.drawing_state
        views = [view for view in current.views if view.sheet_id == self.sheet_id]
        if any(not self._annotation_source_clean(view.view_id) for view in views):
            raise ValueError("视图已过期或尚未生成，请更新后再出图")
        scene = build_drawing_scene(current, self.sheet_id, self.projections)
        validate_drawing_output(scene)
        return scene

    def export_to(self, kind: str, path: Path) -> None:
        try:
            scene = self.output_scene()
            if kind not in ("dxf", "pdf"):
                raise ValueError("工程图仅支持 DXF/PDF 输出")
        except ValueError as error:
            self._set_message(str(error))
            return
        assert self.unit is not None
        exporter = export_drawing_dxf if kind == "dxf" else export_drawing_pdf

        def completed(result: ExecutionResult) -> None:
            if result.error:
                self._set_message(f"出图失败，原文件未修改：{result.error}")
            else:
                self._set_message(
                    f"已导出 {path.name}；按图纸实际大小输出。DXF 为静态交付，不包含跨软件模型关联。"
                )

        if self.unit.submit(
            lambda: exporter(scene, path),
            operation=f"export-drawing-{kind}",
            session_id=self.session_id,
            on_complete=completed,
        ):
            self._set_message("正在生成矢量图纸…")

    def _annotation_source_clean(self, identity: UUID) -> bool:
        if self.services is None or self.unit is None or self.unit.is_busy:
            return False
        result = self.projections.get(identity)
        current = self.services.kernel.drawing_state
        return (
            result is not None
            and self.updates.status(identity) == "clean"
            and result.source_fingerprint == self.services.kernel.drawing_source_fingerprint
            and identity in {v.view_id for v in current.views}
            and identity in {v.view_id for v in self.state.views}
            and current.effective_basis(identity) == self.state.effective_basis(identity)
            and current.view(identity).source == self.state.view(identity).source
            and current.view(identity).section == self.state.view(identity).section
            and current.view(identity).detail == self.state.view(identity).detail
            and (
                current.view(identity).section is None
                or current.effective_scale(identity) == self.state.effective_scale(identity)
            )
        )

    def _edit_annotation(self, identity: object) -> None:
        self.annotations.select(identity)
        self._show_annotation_tab(self.annotations)
        self.annotations.precision.setFocus()

    def _selected_view_changed(self, identity: object, activate: bool = True) -> None:
        valid = isinstance(identity, UUID) and identity in {v.view_id for v in self.state.views}
        self.delete_action.setEnabled(valid)
        self.view_properties.setEnabled(valid)
        if not valid or not isinstance(identity, UUID):
            self.selected_view_label.setText("在图中选择视图")
            return
        view = self.state.view(identity)
        self.selected_view_label.setText(
            f"视图 {str(identity)[:8]} · {'保持对齐' if view.aligned else '自由放置'}"
        )
        self.selected_scale.setValue(self.state.effective_scale(identity))
        hidden, tangent = self.state.effective_display(identity)
        for control, value in ((self.hidden_lines, hidden), (self.tangent_lines, tangent)):
            blocked = control.blockSignals(True)
            control.setChecked(value)
            control.blockSignals(blocked)
        if activate:
            self.settings_tabs.setCurrentWidget(self.view_properties)

    def _view_dragged(self, identity: object, mode: str, value: object, finished: bool) -> None:
        if not isinstance(identity, UUID):
            return
        try:
            if mode == "scale" and isinstance(value, int | float):
                params = scale_view(self.state, identity, float(value))
                self._set_message(f"纸上比例 {value:.3f}:1；松开提交一次，Esc 取消。")
            elif mode == "move" and isinstance(value, tuple):
                params = move_view(self.state, identity, cast("Point2", value))
            else:
                return
            self._preview_params = params
            self._render()
            if finished:
                self._execute("drawing.view.update", params, self._clear_grip_preview)
        except ValueError as error:
            self._clear_grip_preview()
            self._set_message(f"视图操作已取消：{error}")

    def _clear_grip_preview(self) -> None:
        self._preview_params = None
        self._render()

    def apply_selected_scale(self) -> None:
        identity = self.canvas.selected_view
        if identity is not None:
            self._execute(
                "drawing.view.update", scale_view(self.state, identity, self.selected_scale.value())
            )

    def restore_selected_scale(self) -> None:
        identity = self.canvas.selected_view
        if identity is not None:
            self._execute("drawing.view.update", scale_view(self.state, identity, None))

    def _alignment_grip(self, identity: object) -> None:
        if isinstance(identity, UUID):
            self.canvas.select_view(identity)
            self.toggle_selected_alignment()

    def toggle_selected_alignment(self) -> None:
        identity = self.canvas.selected_view
        if identity is not None:
            view = self.state.view(identity)
            if view.parent_id is not None:
                self._execute(
                    "drawing.view.update",
                    set_view_alignment(self.state, identity, not view.aligned),
                )

    def apply_selected_display(self) -> None:
        identity = self.canvas.selected_view
        if identity is not None:
            self._execute(
                "drawing.view.update",
                {
                    "view_id": str(identity),
                    "inherit_display": False,
                    "hidden_lines": self.hidden_lines.isChecked(),
                    "tangent_lines": self.tangent_lines.isChecked(),
                },
            )

    def restore_selected_display(self) -> None:
        identity = self.canvas.selected_view
        if identity is not None:
            self._execute(
                "drawing.view.update", {"view_id": str(identity), "inherit_display": True}
            )

    def _delete_scope(self, identity: UUID) -> tuple[UUID, tuple[UUID, ...], tuple[UUID, ...]]:
        ids = {identity}
        while True:
            descendants = {v.view_id for v in self.state.views if v.parent_id in ids}
            if descendants <= ids:
                break
            ids.update(descendants)
        return (
            identity,
            tuple(v.view_id for v in self.state.views if v.view_id in ids),
            tuple(a.annotation_id for a in self.state.annotations if a.view_id in ids),
        )

    def preview_delete(self) -> None:
        identity = self.canvas.selected_view
        if identity is None:
            return
        if not self._view_edit_finished():
            return
        if not self._annotation_finished():
            return
        if self.notes.pending or self.placement is not None:
            self._set_message("请先完成或取消当前文字或视图放置，再删除视图。")
            return
        self._pending_delete = self._delete_scope(identity)
        self.canvas.deletion_preview = set(self._pending_delete[1])
        self.confirm_delete_action.setVisible(True)
        self.confirm_delete_action.setEnabled(True)
        self._set_message(
            f"将删除 {len(self._pending_delete[1])} 个视图及 {len(self._pending_delete[2])} 个标注；Enter 确认，Esc 取消。"
        )
        self._render()
        self.canvas.setFocus()

    def confirm_delete(self) -> None:
        scope = self._pending_delete
        if scope is None:
            return
        if scope[0] not in {v.view_id for v in self.state.views}:
            self._clear_delete_preview()
            self._set_message("视图已被删除，删除预览已结束。")
            return
        if self._delete_scope(scope[0]) != scope:
            self.preview_delete()
            self._set_message("删除范围已变化，请检查红框并再次确认。")
            return
        self._execute("drawing.view.delete", {"view_id": str(scope[0])}, self._clear_delete_preview)

    def _clear_delete_preview(self) -> None:
        self._pending_delete = None
        self.canvas.deletion_preview.clear()
        self.confirm_delete_action.setVisible(False)
        self._render()

    def _confirm_canvas(self) -> None:
        if self.section_placement is not None:
            self._commit_section()
        elif self.detail_placement is not None:
            self._commit_detail()
        elif self.annotations.pending:
            self.annotations.commit()
        elif self._pending_delete is not None:
            self.confirm_delete()
        else:
            self.commit_placement()

    def _cancel_canvas(self) -> None:
        if self.section_placement is not None:
            self._cancel_section()
            return
        if self.detail_placement is not None:
            self._cancel_detail()
            return
        if self.notes.pending:
            self.notes.cancel()
            return
        if self.canvas.annotation_mode or self.annotations.pending:
            self.annotations.cancel()
            return
        self._clear_grip_preview()
        if self._pending_delete is not None:
            self._clear_delete_preview()
        elif self.placement is not None:
            self.cancel_placement()
        elif self._future is not None:
            self.cancel_update()
        else:
            self.canvas.select_view(None)

    def shutdown(self) -> None:
        self._timer.stop()
        if self._worker is not None:
            self._worker.close()

    @override
    def hideEvent(self, event: QHideEvent) -> None:
        self._dock_visible = not self.parameter_dock.isHidden()
        self.parameter_dock.hide()
        super().hideEvent(event)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        self.parameter_dock.setVisible(self._dock_visible)
        super().showEvent(event)
