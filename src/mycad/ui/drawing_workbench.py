# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Engineering drawing page with a floating settings dock and canvas gestures."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
from typing import TYPE_CHECKING, cast, override
from uuid import UUID, uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
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
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    DrawingSourceSnapshot,
    Point2,
    ProjectionResult,
    ViewBasis,
    build_drawing_scene,
    projected_basis,
)
from mycad.core.persistence import LoadedDocument
from mycad.ui.drawing_canvas import DrawingCanvas
from mycad.ui.drawing_tools import ViewPlacement
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
        self.projections: dict[UUID, ProjectionResult] = {}
        self.placement: ViewPlacement | None = None
        self._ghost: DrawingView | None = None
        self._placement_source_fingerprint = ""
        self._placement_stale = False
        self._generation = 0
        self._pending = False
        self._snapshot_inflight = False
        self._future: Future[tuple[ProjectionResult, ...]] | None = None
        self._future_session = 0
        self._worker: mycad_app.DrawingProjectionWorker | None = None
        self._worker_fingerprint = ""
        self._dock_visible = True
        self._start_after_sheet = False
        self.canvas = DrawingCanvas()
        self.setCentralWidget(self.canvas)
        self.toolbar = self.addToolBar("工程图")
        self.toolbar.setObjectName("drawingToolbar")
        self.sheet_action = QAction("新建图纸", self)
        self.base_action = QAction("基准与投影视图", self)
        self.update_action = QAction("更新视图", self)
        for action in (self.sheet_action, self.base_action, self.update_action):
            self.toolbar.addAction(action)
            action.setEnabled(False)
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
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["图形信息"])
        self.tree.itemClicked.connect(self._select_tree_sheet)
        self.settings_tabs.addTab(self.tree, "图形信息")
        self.parameter_dock = QDockWidget("工程图功能", self)
        self.parameter_dock.setObjectName("drawingParameterDock")
        self.parameter_dock.setWidget(self.settings_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock)
        self.resizeDocks([self.parameter_dock], [260], Qt.Orientation.Horizontal)
        self.canvas.paper_clicked.connect(self._click)
        self.canvas.paper_moved.connect(self._move)
        self.canvas.commit_requested.connect(self.commit_placement)
        self.canvas.cancel_requested.connect(self.cancel_placement)
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
        self.loaded, self.session_id = loaded, session_id
        self.placement = None
        self._placement_stale = False
        self.canvas.placing = False
        self.projections.clear()
        self.sheet_id = None
        self._generation += 1
        self._pending = False
        self._snapshot_inflight = False
        enabled = loaded.document.document_type == "part"
        for action in (self.sheet_action, self.base_action, self.update_action):
            action.setEnabled(enabled)
        self.refresh()
        if not enabled:
            self._set_message("独立二维图不包含三维模型；请在平面草图中绘制。")

    def refresh(self) -> None:
        if self.services is None:
            return
        self.state = self.services.kernel.drawing_state
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
        for sheet in self.state.sheets:
            item = QTreeWidgetItem([sheet.name])
            item.setData(0, Qt.ItemDataRole.UserRole, sheet.sheet_id)
            self.tree.addTopLevelItem(item)
            for view in self.state.views:
                if view.sheet_id == sheet.sheet_id:
                    item.addChild(
                        QTreeWidgetItem(
                            [f"{view.direction} · {self.state.effective_scale(view.view_id):g}:1"]
                        )
                    )
            item.setExpanded(True)
        self._render()
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

    def _requests(self, fingerprint: str) -> tuple[DrawingProjectionRequest, ...]:
        requests = [
            DrawingProjectionRequest(
                v.view_id, fingerprint, self._generation, self.state.effective_basis(v.view_id)
            )
            for v in self.state.views
        ]
        if self.placement is not None:
            placement = self.placement
            requests.append(
                DrawingProjectionRequest(
                    placement.base_id, fingerprint, self._generation, placement.basis
                )
            )
            for direction in ("top", "bottom", "left", "right"):
                requests.append(
                    DrawingProjectionRequest(
                        placement.projected_id(direction),
                        fingerprint,
                        self._generation,
                        projected_basis(placement.basis, direction),
                    )
                )
        return tuple(requests)

    def update_requested(self) -> None:
        self._placement_stale = False
        if self.services is not None:
            self._placement_source_fingerprint = self.services.kernel.drawing_source_fingerprint
        self.request_update()

    def request_update(self) -> None:
        if self._placement_stale:
            return
        if (
            self.services is None
            or self.unit is None
            or self.loaded is None
            or self.loaded.document.document_type != "part"
        ):
            return
        if not self.state.views and self.placement is None:
            return
        self._pending = True
        if self._future is not None or self._snapshot_inflight or self.unit.is_busy:
            return
        self._pending = False
        self._generation += 1
        self._snapshot_inflight = True
        services = self.services

        def captured(result: ExecutionResult) -> None:
            self._snapshot_inflight = False
            if result.error or not isinstance(result.value, DrawingSourceSnapshot):
                self._set_message(f"无法生成工程视图：{result.error or '来源快照不可用'}")
                return
            if self._worker is None:
                self._worker = mycad_app.create_drawing_worker()
            snapshot = result.value
            self._worker_fingerprint = snapshot.source_fingerprint
            self._future_session = self.session_id
            self._future = self._worker.submit(
                snapshot, self._requests(snapshot.source_fingerprint)
            )
            self._set_message("正在更新工程视图；可切换工作区，旧结果不会覆盖新模型。")

        if not self.unit.submit(
            services.kernel.drawing_snapshot,
            operation="drawing-source-snapshot",
            session_id=self.session_id,
            on_complete=captured,
        ):
            self._snapshot_inflight = False
            self._pending = True

    def _busy_changed(self, busy: bool) -> None:
        if not busy and self._pending:
            QTimer.singleShot(0, self, self.request_update)

    def _poll(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        self._future = None
        try:
            results = future.result()
        except Exception as error:
            self._set_message(f"投影失败，保留旧结果：{error}")
            return
        if self.services is None or self.unit is None:
            return
        if self._placement_stale:
            return
        if (
            self._future_session != self.session_id
            or self.unit.is_busy
            or self._worker_fingerprint != self.services.kernel.drawing_source_fingerprint
        ):
            self._pending = True
        else:
            for result in results:
                if result.generation == self._generation:
                    self.projections[result.view_id] = result
            if self.placement is not None:
                self.canvas.placing = True
                self._set_message(
                    "单击放置基准视图，再沿方向放置投影视图；Enter 完成整组，Esc 取消。"
                )
                self.canvas.setFocus()
            else:
                self._set_message("工程图已更新。")
            self._render()
        if self._pending:
            self.request_update()

    def _render(self) -> None:
        if self.sheet_id is None:
            self.canvas.clear_scene()
            return
        state = self.state
        if self.placement is not None:
            existing = {v.view_id for v in state.views}
            views = [v for v in self.placement.pending if v.view_id not in existing]
            if self._ghost is not None and self._ghost.view_id not in existing:
                views = [v for v in views if v.view_id != self._ghost.view_id] + [self._ghost]
            state = replace(state, views=(*state.views, *views))
        self.canvas.set_scene(build_drawing_scene(state, self.sheet_id, self.projections))

    def _move(self, point: object) -> None:
        if self.placement is not None and self.canvas.placing:
            self._ghost = self.placement.preview(cast("Point2", point))
            self._render()

    def _click(self, point: object) -> None:
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
        self._set_message("视图放置已结束。")

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
