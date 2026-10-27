# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering drawing page with a floating settings dock and canvas gestures."""

from __future__ import annotations

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
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from mycad import app as mycad_app
from mycad.core.drawing import DrawingSheet, DrawingState, DrawingView
from mycad.core.drawing_codec import apply_drawing_command, drawing_object_mapping
from mycad.core.drawing_paper import validate_drawing_output
from mycad.core.drawing_projection import (
    DrawingScene,
    DrawingSourceSnapshot,
    Point2,
    ProjectionResult,
    ViewBasis,
    build_drawing_scene,
    projected_basis,
)
from mycad.core.persistence import LoadedDocument
from mycad.formats.drawing_export import export_drawing_dxf
from mycad.ui.drawing_annotation_tools import DrawingAnnotationTools
from mycad.ui.drawing_canvas import DrawingCanvas
from mycad.ui.drawing_pdf import export_drawing_pdf
from mycad.ui.drawing_tools import ViewPlacement, move_view, scale_view, set_view_alignment
from mycad.ui.drawing_updates import ProjectionBatch, ProjectionUpdates
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit

if TYPE_CHECKING:
    from collections.abc import Callable

    from mycad.app import AppServices


class DrawingWorkbench(QMainWindow):
    message = Signal(str)

    def __init__(
        self,
        services: AppServices | None,
        unit: SerializedExecutionUnit | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.services, self.unit = services, unit
        self.loaded: LoadedDocument | None = None
        self.session_id = 0
        self.state = DrawingState()
        self.sheet_id: UUID | None = None
        self.updates = ProjectionUpdates()
        self.projections = self.updates.results
        self._view_items: dict[UUID, QTreeWidgetItem] = {}
        self.placement: ViewPlacement | None = None
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
        self._start_after_sheet = False
        self.canvas = DrawingCanvas()
        self.setCentralWidget(self.canvas)
        self.toolbar = self.addToolBar("工程图")
        self.toolbar.setObjectName("drawingToolbar")
        self.sheet_action = QAction("新建图纸", self)
        self.base_action = QAction("基准与投影视图", self)
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
            self.base_action,
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
        self.update_action.triggered.connect(self.update_requested)
        self.settings_tabs = QTabWidget()
        settings = QWidget()
        form = QFormLayout(settings)
        self.paper = QComboBox()
        self.paper.addItems(["A4 横向", "A4 纵向", "A3 横向", "A3 纵向"])
        self.angle = QComboBox()
        self.angle.addItems(["第一角", "第三角"])
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.001, 1000)
        self.scale.setDecimals(3)
        self.scale.setValue(1)
        self.direction = QComboBox()
        self.direction.addItems(["前视", "后视", "俯视", "仰视", "左视", "右视"])
        self.title = QLineEdit()
        self.title.setPlaceholderText("图纸名称")
        self.hint = QLabel("先创建图纸，再在画布放置基准和投影视图。Enter 完成，Esc 取消。")
        self.hint.setWordWrap(True)
        for name, widget in [
            ("纸张", self.paper),
            ("投影法", self.angle),
            ("比例", self.scale),
            ("基准方向", self.direction),
            ("标题", self.title),
        ]:
            form.addRow(name, widget)
        apply_settings = QPushButton("应用图纸设置")
        apply_settings.clicked.connect(self.apply_sheet_settings)
        form.addRow(apply_settings)
        self.settings_tabs.addTab(settings, "设置")
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
        )
        self.settings_tabs.addTab(self.annotations, "标注")
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

    def _set_message(self, text: str) -> None:
        self.hint.setText(text)
        self.message.emit(text)

    def bind_document(self, loaded: LoadedDocument, session_id: int) -> None:
        self.annotations.cancel()
        self.annotations.select(None)
        self.loaded, self.session_id = loaded, session_id
        self.placement = None
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
        enabled = loaded.document.document_type == "part"
        self.annotation_toolbar.setEnabled(enabled)
        for action in (
            self.sheet_action,
            self.base_action,
            self.update_action,
            self.cancel_update_action,
            self.dxf_action,
            self.pdf_action,
        ):
            action.setEnabled(enabled)
        self.refresh()
        if not enabled:
            self._set_message("独立二维图不包含三维模型；请在平面草图中绘制。")

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

    def refresh(self) -> None:
        if self.services is None:
            return
        self.state = self.services.kernel.drawing_state
        self._reconcile_placement()
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
        if self.sheet_id is not None and previous_sheet != self.sheet_id:
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

    def create_sheet(self) -> None:
        if self.loaded is None or self.loaded.document.document_type != "part":
            return
        paper = "A4" if self.paper.currentIndex() < 2 else "A3"
        sheet = DrawingSheet.for_paper(uuid4(), paper, landscape=self.paper.currentIndex() % 2 == 0)
        sheet = replace(
            sheet,
            name=self.title.text().strip() or f"工程图 {len(self.state.sheets) + 1}",
            projection_angle="first" if self.angle.currentIndex() == 0 else "third",
            default_scale=self.scale.value(),
            title=(("标题", self.title.text().strip()),),
        )

        def done() -> None:
            self.sheet_id = sheet.sheet_id
            self._render()
            if self._start_after_sheet:
                self._start_after_sheet = False
                self.begin_placement()

        self._execute("drawing.sheet.create", drawing_object_mapping(sheet), done)

    def _load_sheet_settings(self) -> None:
        if self.sheet_id is None:
            return
        sheet = self.state.sheet(self.sheet_id)
        paper = 0 if max(sheet.size_mm) == 297 else 2
        self.paper.setCurrentIndex(paper + (0 if sheet.size_mm[0] > sheet.size_mm[1] else 1))
        self.angle.setCurrentIndex(0 if sheet.projection_angle == "first" else 1)
        self.scale.setValue(sheet.default_scale)
        self.title.setText(dict(sheet.title).get("标题", sheet.name))

    def _select_tree_sheet(self, item: QTreeWidgetItem, _column: int) -> None:
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(identity, UUID) and identity in {s.sheet_id for s in self.state.sheets}:
            self.cancel_placement()
            self.sheet_id = identity
            self._load_sheet_settings()
            self._render()
        elif isinstance(identity, UUID) and identity in {v.view_id for v in self.state.views}:
            self.sheet_id = self.state.view(identity).sheet_id
            self._load_sheet_settings()
            self._render()
            self.canvas.select_view(identity)

    def apply_sheet_settings(self) -> None:
        if self.sheet_id is None:
            self.create_sheet()
            return
        paper = DrawingSheet.for_paper(
            self.sheet_id,
            "A4" if self.paper.currentIndex() < 2 else "A3",
            landscape=self.paper.currentIndex() % 2 == 0,
        )
        self._execute(
            "drawing.sheet.update",
            {
                "sheet_id": str(self.sheet_id),
                "size_mm": list(paper.size_mm),
                "projection_angle": "first" if self.angle.currentIndex() == 0 else "third",
                "default_scale": self.scale.value(),
                "name": self.title.text().strip() or "工程图",
                "title": [["标题", self.title.text()]],
            },
        )

    def _edit_sheet(self) -> None:
        if self.sheet_id is not None:
            sheet = self.state.sheet(self.sheet_id)
            if self.title.text() == dict(sheet.title).get("标题", sheet.name):
                return
            self._execute(
                "drawing.sheet.update",
                {"sheet_id": str(self.sheet_id), "title": [["标题", self.title.text()]]},
            )

    def begin_placement(self) -> None:
        self.annotations.cancel()
        if self.loaded is None or self.loaded.document.document_type != "part":
            return
        if self.sheet_id is None:
            self._start_after_sheet = True
            self.create_sheet()
            return
        directions = ("front", "back", "top", "bottom", "left", "right")
        basis = projected_basis(ViewBasis(), directions[self.direction.currentIndex()])
        self._placement_stale = False
        if self.services is not None:
            self._placement_source_fingerprint = self.services.kernel.drawing_source_fingerprint
        self.placement = ViewPlacement(
            self.state.sheet(self.sheet_id), scale=self.scale.value(), basis=basis
        )
        self.canvas.placing = False
        self._set_message("正在准备投影；完成后在画布单击放置基准视图。")
        self.request_update()

    def _target_bases(self) -> dict[UUID, ViewBasis]:
        bases = {v.view_id: self.state.effective_basis(v.view_id) for v in self.state.views}
        if self.placement is not None and not self._placement_stale:
            placement = self.placement
            bases[placement.base_id] = placement.basis
            for direction in ("top", "bottom", "left", "right"):
                bases[placement.projected_id(direction)] = projected_basis(
                    placement.basis, direction
                )
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
        self.updates.sync(self.session_id, fingerprint, self._target_bases())
        return fingerprint

    def update_requested(self) -> None:
        self._placement_stale = False
        if self.services is not None:
            self._placement_source_fingerprint = self.services.kernel.drawing_source_fingerprint
        self.updates.retry()
        self.request_update()

    def request_update(self) -> None:
        if (
            self.services is None
            or self.unit is None
            or self.loaded is None
            or self.loaded.document.document_type != "part"
        ):
            return
        if self.unit.is_busy:
            self._pending = True
            return
        fingerprint = self._sync_targets()
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
                batch = self.updates.begin()
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
        batch = self.updates.begin()
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
        self.settings_tabs.setEnabled(not busy)
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
        if accepted:
            if (
                self.placement is not None
                and not self._placement_stale
                and self.updates.status(self.placement.base_id) == "clean"
            ):
                self.canvas.placing = True
                self._set_message(
                    "单击放置基准视图，再沿方向放置投影视图；Enter 完成整组，Esc 取消。"
                )
                if self.isVisible():
                    self.canvas.setFocus()
            elif not self._placement_stale:
                self._set_message("工程图已更新。")
        self._render()
        if self.updates.has_pending:
            self.request_update()

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
        if self.sheet_id is None:
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
        scene = build_drawing_scene(state, self.sheet_id, self.projections)
        labels = {"clean": "已更新", "stale": "待更新", "updating": "更新中", "failed": "更新失败"}
        names = {
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
            item = self._view_items.get(view.view_id)
            if item is not None:
                item.setText(
                    0,
                    f"{names[view.direction]} · {self.state.effective_scale(view.view_id):g}:1 · {labels[status]}",
                )
            if view.sheet_id == self.sheet_id and status != "clean":
                issues.append(f"{names[view.direction]} {str(view.view_id)[:8]}：{labels[status]}")
        self.canvas.set_scene(replace(scene, issues=tuple(dict.fromkeys(issues))))

    def _move(self, point: object) -> None:
        self.annotations.move_preview(cast("Point2", point))
        if self.placement is not None and self.canvas.placing:
            self._ghost = self.placement.preview(cast("Point2", point))
            self._render()

    def _click(self, point: object) -> None:
        self.annotations.click(cast("Point2", point))
        if self.placement is not None and self.canvas.placing:
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
            self._execute(
                "drawing.view.create",
                {"views": [drawing_object_mapping(v) for v in views]},
                self.cancel_placement,
            )

    def cancel_placement(self) -> None:
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
        if self.annotations.pending or (self.placement is not None and self.placement.pending):
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
        )

    def _edit_annotation(self, identity: object) -> None:
        self.annotations.select(identity)
        self.settings_tabs.setCurrentWidget(self.annotations)
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
        if self.annotations.pending:
            self.annotations.commit()
        elif self._pending_delete is not None:
            self.confirm_delete()
        else:
            self.commit_placement()

    def _cancel_canvas(self) -> None:
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
