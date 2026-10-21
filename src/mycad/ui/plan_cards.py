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
- "执行" runs ``plan.confirm(actor="gui")`` — the non-empty-actor product-side
  confirmation — then ``bus.execute_batch(plan)`` in a single call. Failure
  raises :class:`~mycad.core.exceptions.BatchRollbackError`; the widget shows
  the rollback ordinals (same computation as ``cli/session.py``) and marks the
  failed card red. Success turns the plan ``done``.

No NL generation, no confirmation_token plumbing (phase-2 MCP), and only one
active plan card stream at a time — a new palette activation replaces the
draft entirely.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mycad.core.exceptions import BatchRollbackError
from mycad.core.plan import Plan
from mycad.ui.plan_draft import PlanDraftController

if TYPE_CHECKING:
    from mycad.core.bus import CommandBus
    from mycad.core.document import Document, PlannedCommand
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import LoadedDocument


def _params_text(step: PlannedCommand) -> str:
    """One-line rendering of the step's live params (card body)."""
    return ", ".join(f"{key}={value}" for key, value in step.params.items())


def _parse_value(text: str) -> object:
    """JSON-parse a field text (falls back to the raw string like the right panel)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


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
            self._draft.plan_replaced.disconnect(self._rebuild)
            self._draft.params_changed.disconnect(self._rebuild)
        self._draft = draft
        draft.plan_replaced.connect(self._rebuild)
        draft.params_changed.connect(self._rebuild)
        self._rebuild()

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Point the execution bar at the current document's bus."""
        self._bus = loaded.bus
        self._document = loaded.document
        self._rebuild()

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
        # Illegal transitions must not be triggerable via the UI (todo 12
        # must-not): only draft/confirmed plans can start executing.
        if plan.status not in ("draft", "confirmed"):
            return
        self._failed_step = None
        self._rolled_back = None
        plan.confirm(actor="gui")
        try:
            bus.execute_batch(plan)
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
        self._status.setStyleSheet("")
        self._status.setText(f"完成：计划 {plan.plan_id[:8]}（{len(plan.steps)} 条命令）")
        self.plan_done.emit(len(plan.steps))
        self._rebuild()

    def cancel_plan(self) -> None:
        """draft/confirmed -> cancelled; a no-op elsewhere (UI cannot cheat)."""
        plan = self._draft.plan() if self._draft is not None else None
        if plan is None or plan.status not in ("draft", "confirmed"):
            return
        plan.cancel()
        self._status.setStyleSheet("")
        self._status.setText("已取消")
        self._rebuild()

    def _on_edit_requested(self, step: PlannedCommand) -> None:
        dialog = _ParamDialog(step, controller=self._draft, parent=self)
        dialog.exec()

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
        self._btn_cancel.setEnabled(status in ("draft", "confirmed"))
        steps = plan.steps if plan is not None else []
        self._btn_execute.setEnabled(status == "draft" and bool(steps))


class _ParamDialog(QDialog):
    """Per-step parameter editor (todo12「编辑」); writes via the controller.

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._controller = controller
        self._error = QLabel(self)
        self._form = QFormLayout(self)
        self._edits: dict[str, QLineEdit] = {}
        for key, value in step.params.items():
            edit = QLineEdit(str(value), self)
            self._edits[key] = edit
            self._form.addRow(key, edit)
        self._form.addRow(self._error)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._form.addRow(box)

    def accept(self) -> None:  # noqa: N802  (Qt override)
        if self._controller is None or not self._edits:
            self.reject()
            return
        new_params: dict[str, object] = {
            key: _parse_value(edit.text()) for key, edit in self._edits.items()
        }
        try:
            self._controller.set_params(self._step, new_params)
        except ValidationError as exc:
            self._error.setText(f"参数非法：{str(exc)[:200]}")
            return
        super().accept()
