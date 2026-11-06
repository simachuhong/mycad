# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated, explicitly confirmed design-bound hole interaction."""

from __future__ import annotations

from collections.abc import Callable
from typing import override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QWidget

from mycad import app
from mycad.core.exceptions import MycadError
from mycad.core.persistence import LoadedDocument
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.viewport_protocol import CandidateInteractionScene, PlanarFaceFrame
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.viewport import GLViewport, SelectionKind, SelectionState


class BoundHoleTask(QDialog):
    """Prepare identity, select a design face, preview and explicitly commit a hole."""

    def __init__(
        self,
        services: app.AppServices,
        loaded: LoadedDocument,
        viewport: GLViewport,
        unit: SerializedExecutionUnit,
        *,
        session_identity: int,
        current_session: Callable[[], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._loaded = loaded
        self._viewport = viewport
        self._unit = unit
        self._session_identity = session_identity
        self._current_session = current_session
        self._candidate = app.create_replay_candidate(
            services, loaded, session_identity=session_identity
        )
        self._previous_filter: SelectionKind = viewport.selection_filter()
        self._binding: dict[str, object] | None = None
        self._frame: WorkPlaneFrame | None = None
        self._preview_params: dict[str, object] | None = None
        self._cancel_requested = False
        self._committing = False
        self._finished = False
        self.scene: CandidateInteractionScene | None = None
        self.status_label = QLabel(
            "确认后存档将升级至 v5，旧版本可能无法打开；取消不更改文档。"
            if loaded.document.archive_version < 5
            else "选择可追溯的平面，预览后确认创建绑定孔。",
            self,
        )
        self.status_label.setWordWrap(True)
        self.u_field = self._number(0.0, -100000.0)
        self.v_field = self._number(0.0, -100000.0)
        self.diameter_field = self._number(5.0, 0.001)
        self.depth_field = self._number(5.0, 0.001)
        self.preview_button = QPushButton("预览孔", self)
        self.preview_button.setEnabled(False)
        self.select_face_button = QPushButton("重选面", self)
        self.confirm_button = QPushButton(
            "确认并升级" if loaded.document.archive_version < 5 else "确认", self
        )
        if loaded.document.archive_version < 5:
            self.confirm_button.setToolTip("确认将存档升级至 v5；旧版本可能无法打开。")
        self.confirm_button.setEnabled(False)
        self.cancel_button = QPushButton("取消", self)
        layout = QHBoxLayout(self)
        for label, widget in (
            ("U mm", self.u_field),
            ("V mm", self.v_field),
            ("孔径 mm", self.diameter_field),
            ("深度 mm", self.depth_field),
        ):
            layout.addWidget(QLabel(label, self))
            layout.addWidget(widget)
        layout.addWidget(self.status_label)
        layout.addWidget(self.select_face_button)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.confirm_button)
        layout.addWidget(self.cancel_button)
        for field in (self.u_field, self.v_field, self.diameter_field, self.depth_field):
            field.valueChanged.connect(self._parameters_changed)
        self.preview_button.clicked.connect(self.preview)
        self.select_face_button.clicked.connect(self.start)
        self.confirm_button.clicked.connect(self.commit)
        self.cancel_button.clicked.connect(self.reject)
        self._viewport.selection_changed.connect(self._selected_face)
        self._viewport.escape_pressed.connect(self.reject)

    def _number(self, value: float, minimum: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self)
        field.setRange(minimum, 100000.0)
        field.setDecimals(3)
        field.setValue(value)
        return field

    def _submit(
        self, action: Callable[[], object], done: Callable[[ExecutionResult], None]
    ) -> None:
        if self._finished or self._unit.is_busy:
            self.status_label.setText("几何操作正在执行，请稍后重试。")
            return
        self.preview_button.setEnabled(False)
        self.confirm_button.setEnabled(False)

        def stale(session: int) -> None:
            if session != self._session_identity:
                return
            self._unit.stale_result_discarded.disconnect(stale)
            self._finish_cancel()

        def finish(result: ExecutionResult) -> None:
            self._unit.stale_result_discarded.disconnect(stale)
            if self._cancel_requested:
                self._finish_cancel()
                return
            done(result)

        self._unit.stale_result_discarded.connect(stale)
        if not self._unit.submit(
            action,
            operation="bound-hole-preview",
            session_id=self._session_identity,
            on_complete=finish,
        ):
            self._unit.stale_result_discarded.disconnect(stale)
            self.status_label.setText("几何操作正在执行，请稍后重试。")

    def start(self) -> None:
        """Preview the uncommitted identity upgrade and enable exact candidate picks."""
        if self._unit.is_busy:
            self.status_label.setText("几何操作正在执行，请稍后重试。")
            return
        self._binding = None
        self._frame = None
        self._preview_params = None
        self.scene = None
        self._viewport.clear_candidate_preview()

        def work() -> app.ReplayCandidatePreview:
            self._candidate.stage(
                ReplayChangeSet((), (), self._loaded.document.archive_version < 5),
                current_session_identity=self._session_identity,
            )
            return self._candidate.preview(current_session_identity=self._session_identity)

        def finished(result: ExecutionResult) -> None:
            preview = result.value
            if (
                result.error is not None
                or not isinstance(preview, app.ReplayCandidatePreview)
                or preview.scene is None
            ):
                self.status_label.setText(
                    f"身份预览失败：{result.error or getattr(preview, 'failure', '')}"
                )
                return
            self.scene = preview.scene
            scene = preview.scene
            if scene.viewport is None or not scene.viewport.faces:
                self.scene = None
                self.status_label.setText("模型没有可绑定的实体面，请先创建实体。")
                return
            self._viewport.show_interaction_scene(
                scene,
                session_identity=self._session_identity,
                is_current=lambda: self._candidate.is_scene_current(
                    scene, current_session_identity=self._current_session()
                ),
            )
            self._viewport.set_selection_filter("face")
            self.status_label.setText(
                "请选择盒体平面或圆柱端面；确认后升级至 v5，旧版可能无法打开。"
                if self._loaded.document.archive_version < 5
                else "请选择盒体平面或圆柱顶面/底面。"
            )

        self._submit(work, finished)

    def _selected_face(self, value: object) -> None:
        scene = self.scene
        if self._finished or scene is None or not isinstance(value, SelectionState):
            return
        if value.kind != "face" or len(value.topology_ids) != 1:
            return
        try:
            binding = self._candidate.interactive_face_binding(
                value.topology_ids[0],
                generation=scene.generation,
                current_session_identity=self._current_session(),
            )
            frame = self._candidate.interactive_bound_face_frame(
                value.topology_ids[0],
                generation=scene.generation,
                current_session_identity=self._current_session(),
            )
        except MycadError as exc:
            self._binding = None
            self._frame = None
            self.preview_button.setEnabled(False)
            self.status_label.setText(f"无法绑定此面：{exc}")
            return
        self._binding = dict(binding)
        self._frame = frame
        hit = self._viewport.picked_face_frame(PlanarFaceFrame(frame.origin_mm, frame.normal))
        u, v = frame.world_to_local(hit.origin)
        with QSignalBlocker(self.u_field), QSignalBlocker(self.v_field):
            self.u_field.setValue(u)
            self.v_field.setValue(v)
        self._preview_params = None
        self.confirm_button.setEnabled(False)
        self.preview_button.setEnabled(True)
        self.status_label.setText(f"已绑定 {binding['role']}；U/V 为选点的设计面局部坐标。")
        self.status_label.setToolTip(
            f"原点 {frame.origin_mm} mm；U 方向 {frame.u_axis}；V 方向 {frame.v_axis}。"
        )

    def _parameters(self) -> dict[str, object]:
        if self._binding is None or self._frame is None:
            raise ValueError("请先选择可绑定的平面")
        return {
            "target_face": dict(self._binding),
            "position": {"kind": "local", "uv_mm": [self.u_field.value(), self.v_field.value()]},
            "diameter": self.diameter_field.value(),
            "depth": {"kind": "blind", "value": self.depth_field.value()},
        }

    def _parameters_changed(self) -> None:
        had_preview = self._preview_params is not None
        self._preview_params = None
        self.confirm_button.setEnabled(False)
        if self._binding is not None and not self._unit.is_busy:
            self.preview_button.setEnabled(True)
            if had_preview:
                self._viewport.clear_candidate_preview()
            self.status_label.setText("参数已变化，请重新预览绑定孔。")

    def preview(self) -> None:
        try:
            params = self._parameters()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.scene = None
        self._viewport.clear_candidate_preview()

        def work() -> app.ReplayCandidatePreview:
            self._candidate.stage(
                ReplayChangeSet(
                    (),
                    (ReplayAppend("feature.hole", 3, params, "local"),),
                    self._loaded.document.archive_version < 5,
                ),
                current_session_identity=self._session_identity,
            )
            return self._candidate.preview(current_session_identity=self._session_identity)

        def finished(result: ExecutionResult) -> None:
            preview = result.value
            if (
                result.error is not None
                or not isinstance(preview, app.ReplayCandidatePreview)
                or preview.state != "succeeded"
            ):
                stale = self._candidate.state == "stale"
                self.preview_button.setEnabled(not stale)
                self.select_face_button.setEnabled(not stale)
                self.status_label.setText(
                    "来源已变化，请取消后重新启动绑定孔。"
                    if stale
                    else f"绑定孔预览失败：{result.error or getattr(preview, 'failure', '')}"
                )
                return
            if params != self._parameters():
                self.preview_button.setEnabled(True)
                self.status_label.setText("参数已变化，请重新预览绑定孔。")
                return
            self._preview_params = params
            if preview.viewport is not None:
                self._viewport.show_candidate_preview(
                    preview.viewport, preserve_view=True, sketches=preview.sketches
                )
            self.preview_button.setEnabled(True)
            self.confirm_button.setEnabled(True)
            self.status_label.setText(
                "预览成功；确认将提交绑定孔"
                + ("并升级存档。" if self._loaded.document.archive_version < 5 else "。")
            )

        self._submit(work, finished)

    def commit(self) -> None:
        if self._unit.is_busy:
            self.status_label.setText("几何操作正在执行，请稍后重试。")
            return
        if self._preview_params is None or self._preview_params != self._parameters():
            self.status_label.setText("参数已变化，请重新预览绑定孔。")
            self.confirm_button.setEnabled(False)
            return

        def work() -> None:
            if self._current_session() != self._session_identity:
                raise ValueError("文档已切换，绑定孔候选失效")
            self._candidate.commit(
                self._candidate.authorize_commit(current_session_identity=self._session_identity),
                current_session_identity=self._session_identity,
            )

        def finished(result: ExecutionResult) -> None:
            self._committing = False
            if result.error is not None:
                self.setEnabled(True)
                self._viewport.clear_candidate_preview()
                self._preview_params = None
                stale = self._candidate.state == "stale"
                self.preview_button.setEnabled(self._binding is not None and not stale)
                self.select_face_button.setEnabled(not stale)
                self.status_label.setText(
                    "来源已变化，请取消后重新启动绑定孔。"
                    if stale
                    else f"无法提交绑定孔：{result.error}"
                )
                return
            self._cleanup()
            self._viewport.refresh()
            self.accept()

        self._committing = True
        self.setEnabled(False)
        self._submit(work, finished)
        if not self._unit.is_busy:
            self._committing = False
            self.setEnabled(True)

    def _cleanup(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._viewport.selection_changed.disconnect(self._selected_face)
        self._viewport.escape_pressed.disconnect(self.reject)
        if self._current_session() == self._session_identity:
            self._viewport.clear_candidate_preview()
            self._viewport.set_selection_filter(self._previous_filter)
        if self._candidate.state not in ("committed", "cancelled"):
            self._candidate.cancel()

    def _finish_cancel(self) -> None:
        self._cleanup()
        super().reject()

    @override
    def reject(self) -> None:
        if self._finished:
            return
        if self._unit.is_busy:
            if self._committing:
                self.status_label.setText("正在提交，请等待操作完成。")
                return
            self._cancel_requested = True
            self.status_label.setText("正在结束预览，完成后取消。")
            return
        self._finish_cancel()
