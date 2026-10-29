# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plan-card confirmation flow (todo 12): bottom "Chat" tab as the card stream.

Product rules (需求 §6 / UI初稿 §7, ADR-004:24): every batched execution must
pass a product-side confirmation; the six-state
:class:`mycad.core.plan.Plan` machine is the pipeline and the card stream is
its interaction surface:

- The palette's ``command_activated`` (todo 6) starts a one-step draft through
  the shared :class:`mycad.ui.plan_draft.PlanDraftController`; this widget
  renders its steps as cards (id / params / ``affected_object`` literal from
  Appendix B.2).
- "编辑" opens a per-step parameter dialog that writes through the *same*
  controller (``set_params``), so the right panel's options tab and the card
  stay in sync via ``params_changed``.
- "取消" runs ``plan.cancel()`` (legal only in draft/confirmed; the button is
  disabled otherwise so an illegal transition cannot be triggered from the UI).
- "执行" asks the bound Bus for a GUI-scoped grant, then calls
  ``bus.execute_batch(plan, scope="gui")`` in a single call. Failure
  raises :class:`~mycad.core.exceptions.BatchRollbackError`; the widget shows
  the rollback ordinals (same computation as ``cli/session.py``) and marks the
  failed card red. Success turns the plan ``done``.

No NL generation, no confirmation_token plumbing (phase-2 MCP), and only one
active plan card stream at a time — a new palette activation replaces the
draft entirely.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mycad.core.exceptions import BatchRollbackError, InvalidPlanTransition, ValidationError
from mycad.core.plan import Plan
from mycad.core.viewport_protocol import ViewportData
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.execution import ExecutionResult, SerializedExecutionUnit
from mycad.ui.parameter_forms import ParameterForm
from mycad.ui.plan_draft import PlanDraftController

if TYPE_CHECKING:
    from mycad.core.bus import CommandBus
    from mycad.core.document import Document, ExecutedCommand, PlannedCommand
    from mycad.core.persistence import LoadedDocument


@dataclass(frozen=True, slots=True)
class _PlanExecutionValue:
    """Immutable UI summary for a completed atomic plan batch."""

    failed_step: int | None
    rolled_back: int
    status_text: str | None


def _params_text(step: PlannedCommand) -> str:
    """One-line rendering of the step's live params (card body)."""
    return ", ".join(f"{key}={value}" for key, value in step.params.items())


class _PlanCard(QFrame):
    """One planned step: id, params, affected object and the edit button."""

    edit_requested = Signal(object)

    def __init__(self, step: PlannedCommand, *, state: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLineWidth(1)
        if state == "failed":
            self.setStyleSheet("QFrame { background: #ffd6d6; }")
        elif state in ("executing", "done"):
            self.setStyleSheet("QFrame { background: #d6f5d6; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        title = QLabel(f"命令 {step.id}（影响: {step.affected_object}）", self)
        layout.addWidget(title)
        self._body = QLabel(_params_text(step), self)
        self._body.setWordWrap(True)
        layout.addWidget(self._body)
        self._edit_button = QPushButton("编辑", self)
        self._edit_button.setEnabled(state == "draft")
        self._edit_button.clicked.connect(lambda: self.edit_requested.emit(step))
        layout.addWidget(self._edit_button, 0)

    def body_text(self) -> str:
        return self._body.text()

    @property
    def edit_button(self) -> QPushButton:
        return self._edit_button


class PlanCards(QWidget):
    """Card stream for the active plan draft + the three-key confirmation bar."""

    plan_failed = Signal(str)
    plan_done = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._draft: PlanDraftController | None = None
        self._bus: CommandBus | None = None
        self._document: Document | None = None
        self._failed_step: int | None = None
        self._rolled_back: int | None = None
        self._execution_unit: SerializedExecutionUnit | None = None
        self._session_id: Callable[[], int] | None = None
        self._prepare_geometry: Callable[[], object] | None = None
        self._preview_builder: (
            Callable[[Sequence[ExecutedCommand], str, Mapping[str, object]], ViewportData] | None
        ) = None
        self._show_candidate_preview: Callable[[ViewportData], None] | None = None
        self._clear_candidate_preview: Callable[[], None] | None = None
        self._preview_generation = 0
        self._execution_busy = False
        self._parameter_dialog: _ParamDialog | None = None

        outer = QVBoxLayout(self)
        self._host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._host)
        self._cards_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._host)
        outer.addWidget(scroll, 1)
        self._status = QLabel(self)
        outer.addWidget(self._status)
        bar = QHBoxLayout()
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.clicked.connect(self.cancel_plan)
        self._btn_execute = QPushButton("执行", self)
        self._btn_execute.clicked.connect(self.execute_plan)
        bar.addStretch(1)
        bar.addWidget(self._btn_cancel)
        bar.addWidget(self._btn_execute)
        outer.addLayout(bar)
        self._rebuild()

    # ------------------------------------------------------------------
    # Binding (todo-6 controller + document bus)
    # ------------------------------------------------------------------

    def bind_draft(self, draft: PlanDraftController) -> None:
        """Swap in the shared plan-draft controller and follow its signals."""
        if self._draft is not None:
            self._draft.plan_replaced.disconnect(self._on_draft_replaced)
            self._draft.params_changed.disconnect(self._rebuild)
        self._draft = draft
        draft.plan_replaced.connect(self._on_draft_replaced)
        draft.params_changed.connect(self._rebuild)
        self._invalidate_preview()
        self._rebuild()

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Point the execution bar at the current document's bus."""
        self._invalidate_preview()
        self._bus = loaded.bus
        self._document = loaded.document
        self._rebuild()

    def configure_execution(
        self,
        execution_unit: SerializedExecutionUnit,
        *,
        session_id: Callable[[], int],
        prepare_geometry: Callable[[], object],
        preview_builder: (
            Callable[[Sequence[ExecutedCommand], str, Mapping[str, object]], ViewportData] | None
        ) = None,
        show_candidate_preview: Callable[[ViewportData], None] | None = None,
        clear_candidate_preview: Callable[[], None] | None = None,
    ) -> None:
        """Route GUI batch execution through the shared serialized worker."""
        if self._execution_unit is not execution_unit:
            if self._execution_unit is not None:
                self._execution_unit.busy_changed.disconnect(self.set_execution_busy)
            execution_unit.busy_changed.connect(self.set_execution_busy)
        self._execution_unit = execution_unit
        self._session_id = session_id
        self._prepare_geometry = prepare_geometry
        self._preview_builder = preview_builder
        self._show_candidate_preview = show_candidate_preview
        self._clear_candidate_preview = clear_candidate_preview

    def set_execution_busy(self, busy: bool) -> None:
        """Disable plan actions while the single document worker is active."""
        self._execution_busy = busy
        plan = self._draft.plan() if self._draft is not None else None
        self._update_buttons(plan)

    # ------------------------------------------------------------------
    # Public reads (tests assert through these, not private widgets)
    # ------------------------------------------------------------------

    @property
    def plan(self) -> Plan | None:
        """The active plan (imperative state source for the card stream)."""
        if self._draft is None:
            return None
        return self._draft.plan()

    def status_text(self) -> str:
        return self._status.text()

    def card_texts(self) -> list[str]:
        """Rendered body text of every card, in plan-step order."""
        texts: list[str] = []
        for index in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, _PlanCard):
                texts.append(widget.body_text())
        return texts

    def execute_enabled(self) -> bool:
        return self._btn_execute.isEnabled()

    def cancel_enabled(self) -> bool:
        return self._btn_cancel.isEnabled()

    # ------------------------------------------------------------------
    # Actions (the only legal transition triggers)
    # ------------------------------------------------------------------

    def execute_plan(self) -> None:
        """draft -> confirm(actor="gui") -> execute_batch (whole-plan atomic)."""
        bus = self._bus
        draft = self._draft
        plan = draft.plan() if draft is not None else None
        if bus is None or draft is None or plan is None:
            return
        if self._execution_busy:
            return
        # Illegal transitions must not be triggerable via the UI (todo 12
        # must-not): only draft/confirmed plans can start executing.
        if plan.status != "draft":
            return
        self._invalidate_preview()
        self._failed_step = None
        self._rolled_back = None
        try:
            bus.confirm_plan(plan, actor="gui", scope="gui")
        except ValidationError as exc:
            text = f"确认失败：{str(exc)[:200]}"
            self._status.setText(text)
            self._status.setStyleSheet("color: #b00020;")
            self.plan_failed.emit(text)
            self._rebuild()
            return
        if (
            self._execution_unit is not None
            and self._session_id is not None
            and self._prepare_geometry is not None
        ):
            if not self._submit_plan(plan, bus):
                plan.cancel()
                self._status.setStyleSheet("color: #b00020;")
                self._status.setText("执行未提交：确认已撤销，请重新创建计划")
                self._rebuild()
            return
        try:
            bus.execute_batch(plan, scope="gui")
        except BatchRollbackError as exc:
            document = self._document
            assert document is not None  # _bus and _document are bound together
            base = len(document.commands)  # post-rollback == pre-batch length
            ordinals = ", ".join(str(base + i) for i in range(len(exc.executed_ids)))
            self._failed_step = exc.failed_ordinal
            self._rolled_back = len(exc.executed_ids)
            text = f"执行失败：{str(exc)[:200]}（回滚: {ordinals}）"
            self._status.setText(text)
            self._status.setStyleSheet("color: #b00020;")
            self.plan_failed.emit(text)
            self._rebuild()
            return
        except InvalidPlanTransition as exc:
            text = f"执行已拒绝：{str(exc)[:200]}"
            self._status.setText(text)
            self._status.setStyleSheet("color: #b00020;")
            self.plan_failed.emit(text)
            self._rebuild()
            return
        self._status.setStyleSheet("")
        self._status.setText(f"完成：计划 {plan.plan_id[:8]}（{len(plan.steps)} 条命令）")
        self.plan_done.emit(len(plan.steps))
        self._rebuild()

    def _submit_plan(self, plan: Plan, bus: CommandBus) -> bool:
        """Execute an atomic batch off-thread and update widgets on completion."""
        execution_unit = self._execution_unit
        session_id = self._session_id
        prepare_geometry = self._prepare_geometry
        document = self._document
        if (
            execution_unit is None
            or session_id is None
            or prepare_geometry is None
            or document is None
        ):
            return False
        bound_session = session_id()

        def execute() -> _PlanExecutionValue:
            try:
                bus.execute_batch(plan, scope="gui")
            except BatchRollbackError as exc:
                base = len(document.commands)
                ordinals = ", ".join(str(base + index) for index in range(len(exc.executed_ids)))
                value = _PlanExecutionValue(
                    failed_step=exc.failed_ordinal,
                    rolled_back=len(exc.executed_ids),
                    status_text=(f"执行失败：{str(exc)[:200]}（回滚: {ordinals}）"),
                )
            else:
                value = _PlanExecutionValue(
                    failed_step=None,
                    rolled_back=0,
                    status_text=None,
                )
            prepare_geometry()
            return value

        def finish(result: ExecutionResult) -> None:
            if result.error is not None:
                text = f"执行失败：{result.error[:200]}"
                self._status.setText(text)
                self._status.setStyleSheet("color: #b00020;")
                self.plan_failed.emit(text)
                self._rebuild()
                return
            value = result.value
            if not isinstance(value, _PlanExecutionValue):
                text = "执行失败：返回结果无效"
                self._status.setText(text)
                self._status.setStyleSheet("color: #b00020;")
                self.plan_failed.emit(text)
                self._rebuild()
                return
            if value.status_text is not None:
                self._failed_step = value.failed_step
                self._rolled_back = value.rolled_back
                self._status.setText(value.status_text)
                self._status.setStyleSheet("color: #b00020;")
                self.plan_failed.emit(value.status_text)
                self._rebuild()
                return
            self._status.setStyleSheet("")
            self._status.setText(f"完成：计划 {plan.plan_id[:8]}（{len(plan.steps)} 条命令）")
            self.plan_done.emit(len(plan.steps))
            self._rebuild()

        self._status.setText("执行中…")
        return execution_unit.submit(
            execute,
            operation="plan-batch",
            session_id=bound_session,
            on_complete=finish,
        )

    def cancel_plan(self) -> None:
        """draft/confirmed -> cancelled; a no-op elsewhere (UI cannot cheat)."""
        if self._execution_busy:
            return
        self._invalidate_preview()
        plan = self._draft.plan() if self._draft is not None else None
        if plan is None or plan.status not in ("draft", "confirmed"):
            return
        plan.cancel()
        self._status.setStyleSheet("")
        self._status.setText("已取消")
        self._rebuild()

    def _on_edit_requested(self, step: PlannedCommand) -> None:
        self.open_parameter_editor(step)

    def open_parameter_editor(
        self,
        step: PlannedCommand,
        *,
        execute_on_apply: bool = False,
        discard_on_cancel: bool = False,
        wait_for_selection: bool = False,
        selection_prompt: str = "",
        overlay_host: QWidget | None = None,
        initial_params: Mapping[str, object] | None = None,
    ) -> _ParamDialog:
        """Open a parameter editor, optionally embedded over a viewport."""
        if self._parameter_dialog is not None:
            self._parameter_dialog.hide()
            self._parameter_dialog.deleteLater()
        dialog = _ParamDialog(
            step,
            controller=self._draft,
            preview_requested=self._submit_preview,
            clear_preview=self._invalidate_preview,
            execute_on_apply=execute_on_apply,
            embedded=overlay_host is not None,
            initial_params=initial_params,
            parent=overlay_host or self.window(),
        )
        self._parameter_dialog = dialog
        plan = self._draft.plan() if self._draft is not None else None
        plan_id = plan.plan_id if plan is not None else None

        def editor_finished(result: int) -> None:
            self._on_dialog_finished(
                dialog,
                result,
                plan_id,
                discard_on_cancel=discard_on_cancel,
            )

        dialog.finished.connect(editor_finished)
        if execute_on_apply:
            dialog.accepted.connect(self.execute_plan)
        if wait_for_selection:
            dialog.set_selection_status(selection_prompt)
            dialog.set_parameter_form_visible(False)
        dialog.show_near(QCursor.pos())
        return dialog

    def fill_parameter_selector(
        self,
        path: str,
        value: object,
        summary: str,
        global_position: QPoint | None = None,
    ) -> bool:
        """Fill a picked selector and show the active modeless editor."""
        dialog = self._parameter_dialog
        if dialog is None:
            return False
        try:
            dialog.fill_selector(path, value, summary)
        except (KeyError, ValueError, ValidationError) as exc:
            dialog.set_selection_status(f"选择无法用于此命令：{str(exc)[:180]}", error=True)
            return False
        dialog.show_near(global_position or QCursor.pos())
        return True

    def set_parameter_selection_status(self, message: str, *, error: bool = False) -> None:
        """Update the active editor's selector prompt or conversion error."""
        if self._parameter_dialog is not None:
            self._parameter_dialog.set_selection_status(message, error=error)

    def show_parameter_editor_at(self, global_position: QPoint) -> bool:
        """Raise or reposition the active editor after a viewport right-click."""
        dialog = self._parameter_dialog
        if dialog is None:
            return False
        dialog.show_near(global_position)
        return True

    def cancel_parameter_editor(self) -> None:
        """Cancel the active tool editor, if it is open or waiting for a pick."""
        dialog = self._parameter_dialog
        if dialog is not None:
            dialog.reject()

    def _on_dialog_finished(
        self,
        dialog: _ParamDialog,
        result: int,
        plan_id: str | None,
        *,
        discard_on_cancel: bool,
    ) -> None:
        if self._parameter_dialog is dialog:
            self._parameter_dialog = None
        self._invalidate_preview()
        current_plan = self._draft.plan() if self._draft is not None else None
        if (
            result != QDialog.DialogCode.Accepted
            and discard_on_cancel
            and self._draft is not None
            and current_plan is not None
            and current_plan.plan_id == plan_id
        ):
            self._draft.replace_plan(Plan(steps=[]))

    def _submit_preview(self, dialog: _ParamDialog, params: Mapping[str, object]) -> None:
        execution_unit = self._execution_unit
        session_id = self._session_id
        builder = self._preview_builder
        show_preview = self._show_candidate_preview
        document = self._document
        if (
            execution_unit is None
            or session_id is None
            or builder is None
            or show_preview is None
            or document is None
        ):
            dialog.set_preview_status("当前无法生成预览：几何服务尚未就绪。", error=True)
            return
        self._preview_generation += 1
        generation = self._preview_generation
        bound_session = session_id()
        command_id = dialog.command_id
        commands = document.commands
        if self._clear_candidate_preview is not None:
            self._clear_candidate_preview()
        dialog.set_preview_status("正在计算预览…")

        def preview() -> ViewportData:
            return builder(commands, command_id, params)

        def finish(result: ExecutionResult) -> None:
            if generation != self._preview_generation or not dialog.isVisible():
                return
            if result.error is not None:
                dialog.set_preview_status(f"预览失败：{result.error[:200]}", error=True)
                return
            if not isinstance(result.value, ViewportData):
                dialog.set_preview_status("预览失败：几何服务返回了无效结果。", error=True)
                return
            show_preview(result.value)
            action = dialog.apply_action
            dialog.set_preview_status(f"临时预览已显示；点击‘{action}’后正式提交。")

        if not execution_unit.submit(
            preview,
            operation="command-preview",
            session_id=bound_session,
            on_complete=finish,
        ):
            dialog.set_preview_status("另一个建模操作正在运行，请稍后再预览。", error=True)

    def _invalidate_preview(self) -> None:
        self._preview_generation += 1
        if self._clear_candidate_preview is not None:
            self._clear_candidate_preview()

    def _on_draft_replaced(self) -> None:
        self._invalidate_preview()
        if self._parameter_dialog is not None:
            self._parameter_dialog.hide()
            self._parameter_dialog.deleteLater()
            self._parameter_dialog = None
        self._rebuild()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        while self._cards_layout.count() > 1:  # keep the trailing stretch
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        plan = self._draft.plan() if self._draft is not None else None
        steps = plan.steps if plan is not None else []
        for index, step in enumerate(steps):
            state = "draft"
            if plan is not None:
                if plan.status in ("done", "executing"):
                    state = plan.status
                elif plan.status == "failed":
                    if index == self._failed_step:
                        state = "failed"
                    elif self._rolled_back is not None and index < self._rolled_back:
                        state = "done"
            card = _PlanCard(step, state=state)
            card.edit_requested.connect(self._on_edit_requested)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        if plan is None or (plan.status == "draft" and not steps):
            self._status.setText("暂无计划草稿——从命令库选择命令开始")
            self._status.setStyleSheet("")
        self._update_buttons(plan)

    def _update_buttons(self, plan: Plan | None) -> None:
        status = plan.status if plan is not None else None
        self._btn_cancel.setEnabled(not self._execution_busy and status in ("draft", "confirmed"))
        steps = plan.steps if plan is not None else []
        self._btn_execute.setEnabled(not self._execution_busy and status == "draft" and bool(steps))


class _ParamDialog(QDialog):
    """Contextual parameter editor; writes via the shared controller.

    Rows mirror the step's current params (validated values that already
    passed ``set_params``); on accept the payload goes through the *same*
    ``PlanDraftController.set_params`` the right panel uses, so an invalid
    edit never lands and both panels stay in sync.
    """

    def __init__(
        self,
        step: PlannedCommand,
        *,
        controller: PlanDraftController | None,
        preview_requested: Callable[[_ParamDialog, Mapping[str, object]], None] | None = None,
        clear_preview: Callable[[], None] | None = None,
        execute_on_apply: bool = False,
        embedded: bool = False,
        initial_params: Mapping[str, object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._controller = controller
        self._preview_requested = preview_requested
        self._clear_preview = clear_preview
        self._execute_on_apply = execute_on_apply
        self._embedded = embedded
        self._parameter_form: ParameterForm | None = None
        self._preview_button: QPushButton | None = None
        self._button_box: QDialogButtonBox | None = None
        self._selection_status = QLabel(self)
        self._selection_status.setWordWrap(True)
        self._preview_status = QLabel(self)
        self._preview_status.setWordWrap(True)
        self._error = QLabel(self)
        self._error.setWordWrap(True)
        self._form = QFormLayout(self)
        self._form.setContentsMargins(12, 10, 12, 12)
        self._form.setHorizontalSpacing(10)
        self._form.setVerticalSpacing(8)
        self.setWindowFlags(Qt.WindowType.Widget if embedded else Qt.WindowType.Tool)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        title = f"设置参数：{step.id}"
        if controller is not None:
            spec = controller.registry.get(step.id, step.version)
            title = f"{spec.label_zh} · 参数"
            hint = {
                "feature.box": "输入长、宽、高；长度单位为 mm。",
                "feature.extrude": "选择圆形或矩形截面，填写尺寸和拉伸距离。",
                "feature.hole": "孔中心暂取所选面的面心。可继续旋转视图；右键可重新定位此面板。",
                "modify.fillet": "圆角只作用于所选边。可继续旋转视图；右键可重新定位此面板。",
            }.get(step.id)
            if hint is not None:
                hint_label = QLabel(hint, self)
                hint_label.setWordWrap(True)
                self._form.addRow(hint_label)
            values = initial_params if initial_params is not None else step.params
            self._parameter_form = ParameterForm(spec, values, controller.registry, self)
            self._parameter_form.values_changed.connect(self._on_values_changed)
            if step.id == "feature.hole":
                self._parameter_form.set_path_visible("target_face", False)
            elif step.id == "modify.fillet":
                self._parameter_form.set_path_visible("edges", False)
            self._form.addRow(self._parameter_form)
        self.setWindowTitle(title)
        if embedded:
            self.setObjectName("contextualParameterPanel")
            self.setStyleSheet(
                "QDialog#contextualParameterPanel {"
                "background: #ffffff; border: 1px solid #7d8b99; border-radius: 7px;"
                "}"
            )
            title_row = QHBoxLayout()
            title_label = QLabel(title, self)
            title_label.setStyleSheet("font-weight: 600; color: #172b3a;")
            close_button = QPushButton(self)
            set_button_icon(close_button, "cancel")
            close_button.setAccessibleName("关闭参数面板")
            close_button.setFixedSize(24, 24)
            close_button.clicked.connect(self.reject)
            title_row.addWidget(title_label, 1)
            title_row.addWidget(close_button)
            self._form.insertRow(0, title_row)
        self._form.addRow(self._selection_status)
        self._form.addRow(self._preview_status)
        self._form.addRow(self._error)
        preview_button = QPushButton("预览", self)
        preview_button.clicked.connect(self._preview)
        self._preview_button = preview_button
        self._form.addRow(preview_button)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        apply_button = box.button(QDialogButtonBox.StandardButton.Ok)
        apply_button.setText("应用并执行" if execute_on_apply else "保存参数")
        set_button_icon(apply_button, "confirm" if execute_on_apply else "save")
        cancel_button = box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("取消")
        set_button_icon(cancel_button, "cancel")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._button_box = box
        self._form.addRow(box)

    def accept(self) -> None:  # noqa: N802  (Qt override)
        if self._controller is None or self._parameter_form is None:
            self.reject()
            return
        try:
            new_params = self._parameter_form.normalized_params()
            self._controller.set_params(self._step, new_params)
        except ValidationError as exc:
            self._error.setText(f"参数非法：{str(exc)[:200]}")
            self._resize_to_content()
            return
        if self._clear_preview is not None:
            self._clear_preview()
        super().accept()

    def _preview(self) -> None:
        if self._parameter_form is None or self._preview_requested is None:
            self.set_preview_status("当前命令不支持预览。", error=True)
            return
        try:
            params = self._parameter_form.normalized_params()
        except ValidationError as exc:
            self.set_preview_status(f"参数非法：{str(exc)[:200]}", error=True)
            return
        self._preview_requested(self, params)

    def request_preview(self) -> None:
        """Request a scratch preview for the current validated form values."""
        self._preview()

    def fill_selector(self, path: str, value: object, summary: str) -> None:
        """Fill a geometry selector captured from the active viewport."""
        if self._parameter_form is None:
            raise ValueError("当前命令没有可写入的参数表单")
        self._parameter_form.set_selector(path, value)
        self.set_selection_status(summary)
        self.set_parameter_form_visible(True)

    def set_selection_status(self, message: str, *, error: bool = False) -> None:
        """Show the current pick or selection instruction beside the form."""
        self._selection_status.setText(message)
        self._selection_status.setStyleSheet("color: #b42318;" if error else "")
        self._resize_to_content()

    def _resize_to_content(self) -> None:
        """Reflow changing status text without squeezing dimension inputs."""
        self._form.invalidate()
        self._form.activate()
        self.adjustSize()
        host = self.parentWidget()
        if self._embedded and host is not None:
            margin = 8
            self.move(
                max(margin, min(self.x(), host.width() - self.width() - margin)),
                max(margin, min(self.y(), host.height() - self.height() - margin)),
            )

    def show_near(self, position: QPoint) -> None:
        """Show beside the cursor, clamped to the viewport when embedded."""
        self.show()
        self.adjustSize()
        if self._embedded:
            host = self.parentWidget()
            if host is not None:
                local = host.mapFromGlobal(position)
                bounds = host.rect()
                margin = 8
                x = min(
                    max(local.x() + 14, margin),
                    max(margin, bounds.width() - self.width() - margin),
                )
                y = min(
                    max(local.y() + 14, margin),
                    max(margin, bounds.height() - self.height() - margin),
                )
                self.move(x, y)
                self.raise_()
                return
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        x = min(max(position.x() + 14, available.left()), available.right() - self.width())
        y = min(max(position.y() + 14, available.top()), available.bottom() - self.height())
        self.move(x, y)

    def set_parameter_form_visible(self, visible: bool) -> None:
        """Reveal dimension controls after the required viewport pick."""
        if self._parameter_form is not None:
            self._parameter_form.setVisible(visible)
        if self._preview_button is not None:
            self._preview_button.setVisible(visible)
        if self._button_box is not None:
            self._button_box.setVisible(visible)
        self._resize_to_content()

    def _on_values_changed(self) -> None:
        self._error.clear()
        if self._clear_preview is not None:
            self._clear_preview()
        self.set_preview_status("参数已更改；点击‘预览’查看当前参数对应的模型。")

    @property
    def command_id(self) -> str:
        """Command being edited, used by the isolated preview builder."""

        return self._step.id

    @property
    def apply_action(self) -> str:
        """Visible apply action used in preview guidance."""

        return "应用并执行" if self._execute_on_apply else "保存参数"

    def set_preview_status(self, message: str, *, error: bool = False) -> None:
        """Show progress or a specific preview result inside this dialog."""

        self._preview_status.setText(message)
        self._preview_status.setStyleSheet("color: #b00020;" if error else "")
        self._resize_to_content()

    @property
    def parameter_form(self) -> ParameterForm | None:
        """Typed parameter form used by this dialog."""

        return self._parameter_form
