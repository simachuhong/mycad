# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicitly repair a bound-hole face in an isolated failed replay prefix."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import override

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QWidget

from mycad import app
from mycad.core.exceptions import MycadError
from mycad.core.persistence import LoadedDocument
from mycad.core.replay_proposal import ReplayChangeSet, ReplayEdit
from mycad.core.viewport_protocol import CandidateInteractionScene, PlanarFaceFrame
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.viewport import GLViewport, SelectionKind, SelectionState


class HistoryRepairTask(QDialog):
    """Pick a replacement in a failure prefix and preview the complete repair."""

    def __init__(
        self,
        candidate: app.ReplayCandidateSession,
        loaded: LoadedDocument,
        viewport: GLViewport,
        unit: SerializedExecutionUnit,
        *,
        ordinal: int,
        params: Mapping[str, object],
        reason: str,
        session_identity: int,
        current_session: Callable[[], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        preview = candidate.latest_preview
        if preview is None or preview.failure is None or preview.failure_scene is None:
            raise ValueError("没有可修复的失败前缀")
        self._candidate = candidate
        self._loaded = loaded
        self._viewport = viewport
        self._unit = unit
        self._ordinal = ordinal
        self._params = dict(params)
        self._reason = reason
        self._failed_ordinal = preview.failure.ordinal
        self._session_identity = session_identity
        self._current_session = current_session
        self._previous_filter: SelectionKind = viewport.selection_filter()
        self._source_params = dict(preview.proposal.commands[self._failed_ordinal].params)
        self._binding: dict[str, object] | None = None
        self._preview_params: dict[str, object] | None = None
        self._finished = False
        self._dialog_completed = False
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self.reject)
        self._preview_epoch = 0
        self._preview_clear_pending = False
        self._clear_preview_epoch = 0
        self._clear_preview_timer = QTimer(self)
        self._clear_preview_timer.setSingleShot(True)
        self._clear_preview_timer.timeout.connect(self._clear_invalidated_preview)
        self._cancel_requested = False
        self._committing = False
        self.scene: CandidateInteractionScene | None = preview.failure_scene
        self.status_label = QLabel(
            f"#{self._failed_ordinal} 绑定面失效；请在失败前缀中选择替代平面。", self
        )
        self.status_label.setWordWrap(True)
        self.u_field = self._number()
        self.v_field = self._number()
        self.reselect_button = QPushButton("重选面", self)
        self.preview_button = QPushButton("预览完整修复", self)
        self.preview_button.setEnabled(False)
        self.confirm_button = QPushButton("确认全部修改", self)
        self.confirm_button.setEnabled(False)
        self.cancel_button = QPushButton("取消", self)
        layout = QHBoxLayout(self)
        for label, field in (("U mm", self.u_field), ("V mm", self.v_field)):
            layout.addWidget(QLabel(label, self))
            layout.addWidget(field)
            field.valueChanged.connect(self._parameters_changed)
        layout.addWidget(self.status_label)
        layout.addWidget(self.reselect_button)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.confirm_button)
        layout.addWidget(self.cancel_button)
        self.reselect_button.clicked.connect(self.reselect)
        self.preview_button.clicked.connect(self.preview)
        self.confirm_button.clicked.connect(self.commit)
        self.cancel_button.clicked.connect(self.reject)
        viewport.selection_changed.connect(self._selected_face)
        viewport.escape_pressed.connect(self.reject)
        try:
            self._show_prefix(preview.failure_scene)
        except ValueError:
            viewport.selection_changed.disconnect(self._selected_face)
            viewport.escape_pressed.disconnect(self.reject)
            raise

    def _number(self) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self)
        field.setRange(-100000, 100000)
        field.setDecimals(3)
        return field

    def _show_prefix(self, scene: CandidateInteractionScene) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
        ):
            return
        self.scene = scene
        self._viewport.show_interaction_scene(
            scene,
            session_identity=self._session_identity,
            is_current=lambda: self._candidate.is_failure_scene_current(
                scene, current_session_identity=self._current_session()
            ),
        )
        self._viewport.set_selection_filter("face")

    def _submit(
        self, action: Callable[[], object], done: Callable[[ExecutionResult], None]
    ) -> None:
        if self._cancel_requested or self._current_session() != self._session_identity:
            return
        if (
            self._finished
            or self._unit.is_busy
            or self._unit.is_notifying_idle
            or self._unit.is_notifying_result
        ):
            self.status_label.setText("几何操作正在执行，请稍后重试。")
            return
        self.preview_button.setEnabled(False)
        self.confirm_button.setEnabled(False)

        def stale(session: int) -> None:
            if session == self._session_identity:
                self._unit.stale_result_discarded.disconnect(stale)
                self._finish_cancel()

        def finish(result: ExecutionResult) -> None:
            self._unit.stale_result_discarded.disconnect(stale)
            if self._cancel_requested or self._current_session() != self._session_identity:
                self._finish_cancel()
            else:
                done(result)

        self._unit.stale_result_discarded.connect(stale)
        if not self._unit.submit(
            action,
            operation="history-repair-preview",
            session_id=self._session_identity,
            on_complete=finish,
        ):
            self._unit.stale_result_discarded.disconnect(stale)
            self.status_label.setText("几何操作正在执行，请稍后重试。")

    def _selected_face(self, value: object) -> None:
        scene = self.scene
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
            or scene is None
            or not isinstance(value, SelectionState)
        ):
            return
        if value.kind != "face" or len(value.topology_ids) != 1:
            return
        try:
            binding = self._candidate.interactive_failure_face_binding(
                value.topology_ids[0],
                generation=scene.generation,
                current_session_identity=self._current_session(),
            )
            frame = self._candidate.interactive_failure_bound_face_frame(
                value.topology_ids[0],
                generation=scene.generation,
                current_session_identity=self._current_session(),
            )
        except MycadError as exc:
            self._binding = None
            self.preview_button.setEnabled(False)
            self.status_label.setText(f"无法绑定此面：{exc}")
            return
        hit = self._viewport.picked_face_frame(PlanarFaceFrame(frame.origin_mm, frame.normal))
        u, v = frame.world_to_local(hit.origin)
        with QSignalBlocker(self.u_field), QSignalBlocker(self.v_field):
            self.u_field.setValue(u)
            self.v_field.setValue(v)
        self._binding = dict(binding)
        self._preview_params = None
        self.confirm_button.setEnabled(False)
        self.preview_button.setEnabled(True)
        self.status_label.setText(
            f"已选择 {binding['role']}；孔位 U/V 随新设计面定义，请预览全部下游。"
        )

    def _repair_params(self) -> dict[str, object]:
        if self._binding is None:
            raise ValueError("请先选择替代面")
        params = dict(self._source_params)
        params["target_face"] = dict(self._binding)
        params["position"] = {
            "kind": "local",
            "uv_mm": [self.u_field.value(), self.v_field.value()],
        }
        return params

    def _changes(self, repair: dict[str, object] | None) -> ReplayChangeSet:
        if self._failed_ordinal == self._ordinal:
            edits = (ReplayEdit(self._ordinal, repair or self._params, "gui-local", self._reason),)
        else:
            edits = (ReplayEdit(self._ordinal, self._params, "gui-local", self._reason),)
            if repair is not None:
                edits += (ReplayEdit(self._failed_ordinal, repair, "gui-local", "重选失效绑定面"),)
        return ReplayChangeSet(edits, (), False)

    def _parameters_changed(self) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
        ):
            return
        self._preview_epoch += 1
        epoch = self._preview_epoch
        had_preview = self._preview_params is not None
        self._preview_clear_pending = self._preview_clear_pending or had_preview
        self._preview_params = None
        self.confirm_button.setEnabled(False)
        if self._unit.is_busy or self._unit.is_notifying_idle or self._unit.is_notifying_result:
            self.preview_button.setEnabled(False)
            if self._preview_clear_pending or self._binding is not None:
                self._clear_preview_epoch = epoch
                self._clear_preview_timer.start(0)
            self.status_label.setText("几何操作正在完成，请稍后重新预览修复。")
            return
        if self._binding is not None and not self._unit.is_busy:
            if self._preview_clear_pending:
                self._viewport.clear_candidate_preview()
                self._preview_clear_pending = False
            self.preview_button.setEnabled(True)
            self.status_label.setText("孔位已变化，请重新预览完整修复。")

    def _clear_invalidated_preview(self) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
            or self._clear_preview_epoch != self._preview_epoch
        ):
            return
        if self._unit.is_busy or self._unit.is_notifying_idle or self._unit.is_notifying_result:
            self._clear_preview_timer.start(100)
            return
        if self._preview_clear_pending:
            self._viewport.clear_candidate_preview()
            self._preview_clear_pending = False
        self.preview_button.setEnabled(
            self._binding is not None and self._candidate.state != "stale"
        )

    def reselect(self) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
        ):
            return
        if self._unit.is_busy or self._unit.is_notifying_idle or self._unit.is_notifying_result:
            return
        self._preview_epoch += 1
        self._preview_clear_pending = False
        self._clear_preview_timer.stop()
        self.scene = None
        self._binding = None
        self._preview_params = None
        self._viewport.clear_candidate_preview()

        def work() -> app.ReplayCandidatePreview:
            self._candidate.stage(
                self._changes(None), current_session_identity=self._session_identity
            )
            return self._candidate.preview(current_session_identity=self._session_identity)

        def finished(result: ExecutionResult) -> None:
            preview = result.value
            if (
                result.error
                or not isinstance(preview, app.ReplayCandidatePreview)
                or preview.failure_scene is None
            ):
                self.status_label.setText(f"无法重建失败前缀：{result.error or ''}")
                return
            self._show_prefix(preview.failure_scene)
            self.status_label.setText("请选择替代平面。")

        self._submit(work, finished)

    def preview(self) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
        ):
            return
        if self._unit.is_busy or self._unit.is_notifying_idle or self._unit.is_notifying_result:
            self.status_label.setText("几何操作正在执行，请稍后重试。")
            return
        try:
            params = self._repair_params()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._preview_epoch += 1
        self._preview_clear_pending = False
        self._clear_preview_timer.stop()
        self.scene = None
        self._viewport.clear_candidate_preview()

        def work() -> app.ReplayCandidatePreview:
            self._candidate.stage(
                self._changes(params), current_session_identity=self._session_identity
            )
            return self._candidate.preview(current_session_identity=self._session_identity)

        def finished(result: ExecutionResult) -> None:
            preview = result.value
            if (
                result.error
                or not isinstance(preview, app.ReplayCandidatePreview)
                or preview.state != "succeeded"
            ):
                stale = self._candidate.state == "stale"
                self.preview_button.setEnabled(self._binding is not None and not stale)
                self.reselect_button.setEnabled(not stale)
                self.status_label.setText(
                    "来源已变化，请取消后重新编辑历史。"
                    if stale
                    else f"完整修复预览失败：{result.error or getattr(preview, 'failure', '')}"
                )
                return
            if params != self._repair_params():
                self.preview_button.setEnabled(True)
                self.status_label.setText("孔位已变化，请重新预览完整修复。")
                return
            self._preview_params = params
            if preview.viewport is not None:
                self._viewport.show_candidate_preview(
                    preview.viewport, preserve_view=True, sketches=preview.sketches
                )
            self.preview_button.setEnabled(True)
            self.confirm_button.setEnabled(True)
            self.status_label.setText(
                f"预览成功：修改 #{self._ordinal} 并修复 #{self._failed_ordinal}，其余下游已重放。"
            )

        self._submit(work, finished)

    def commit(self) -> None:
        if (
            self._finished
            or self._cancel_requested
            or self._current_session() != self._session_identity
        ):
            return
        if (
            self._unit.is_busy
            or self._unit.is_notifying_idle
            or self._unit.is_notifying_result
            or self._preview_params is None
            or self._preview_params != self._repair_params()
        ):
            self.confirm_button.setEnabled(False)
            return

        def work() -> None:
            if self._current_session() != self._session_identity:
                raise ValueError("文档已切换")
            self._candidate.commit(
                self._candidate.authorize_commit(current_session_identity=self._session_identity),
                current_session_identity=self._session_identity,
            )

        def finished(result: ExecutionResult) -> None:
            self._committing = False
            if result.error:
                self.setEnabled(True)
                self._viewport.clear_candidate_preview()
                self._preview_params = None
                stale = self._candidate.state == "stale"
                self.preview_button.setEnabled(self._binding is not None and not stale)
                self.reselect_button.setEnabled(not stale)
                self.status_label.setText(
                    "来源已变化，请取消后重新编辑历史。" if stale else f"修复未提交：{result.error}"
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
        self._cancel_timer.stop()
        self._clear_preview_timer.stop()
        self._finished = True
        self._viewport.selection_changed.disconnect(self._selected_face)
        self._viewport.escape_pressed.disconnect(self.reject)
        if self._current_session() == self._session_identity:
            self._viewport.clear_candidate_preview()
            self._viewport.set_selection_filter(self._previous_filter)
        if self._candidate.state not in ("committed", "cancelled"):
            self._candidate.cancel()

    def _finish_cancel(self) -> None:
        if self._dialog_completed:
            return
        self._cleanup()
        self._dialog_completed = True
        super().reject()

    @override
    def accept(self) -> None:
        if not self._dialog_completed:
            self._dialog_completed = True
            super().accept()

    @override
    def reject(self) -> None:
        if self._finished:
            return
        if self._unit.is_notifying_idle or self._unit.is_notifying_result:
            if self._committing:
                self.status_label.setText("正在提交，请等待操作完成。")
                return
            self._cancel_requested = True
            self.confirm_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.status_label.setText("正在完成当前操作，完成后取消。")
            self._cancel_timer.start(0)
            return
        if self._unit.is_busy:
            if self._committing:
                self.status_label.setText("正在提交，请等待操作完成。")
            else:
                self._cancel_requested = True
                self.confirm_button.setEnabled(False)
                self.preview_button.setEnabled(False)
                self.status_label.setText("正在结束预览，完成后取消。")
                self._cancel_timer.start(100)
            return
        self._finish_cancel()
