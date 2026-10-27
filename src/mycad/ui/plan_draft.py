# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plan-draft controller: the UI-side edit buffer for one planned command.

Contract (plan todo 6, shared with todo 7 右栏「选项」 and todo 12 底栏
确认卡): the controller holds a :class:`mycad.core.plan.Plan` plus the
currently selected step index. Param edits are validated through the
``validate_params`` request of the plan (todo 6 wording) — i.e. by
``mycad.commands.validation.validate_params`` with the registry's shared
``$defs`` table — before they are written back, so a draft can never hold
schema-invalid params. Consumers listen to ``params_changed`` /
``plan_replaced`` instead of reading internals.

Remark on the plan's "通过 registry validate_params": the registry owns
no validator itself; validation lives in ``mycad.commands.validation``
and the registry supplies ``schema_defs`` — kept together here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Signal

from mycad.commands.validation import normalize_params, validate_params
from mycad.core.document import AFFECTED_OBJECTS, AffectedObject, PlannedCommand
from mycad.core.exceptions import ValidationError
from mycad.core.plan import Plan

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry


class PlanDraftController(QObject):
    """Edit buffer for a :class:`~mycad.core.plan.Plan` (six-state draft).

    ``params_changed`` carries ``(step_index, validated_params)`` where the
    index is the selected step's position in ``plan.steps``;
    ``plan_replaced`` fires whenever the whole draft plan is swapped (new
    draft from the palette or explicit ``replace_plan``).
    """

    params_changed = Signal(int, dict)
    plan_replaced = Signal()

    def __init__(
        self, registry: CommandRegistry, plan: Plan | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._plan: Plan = plan if plan is not None else Plan(steps=[])
        self._selected: int = 0

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def plan(self) -> Plan:
        """Return the draft plan (never ``None``; empty steps when idle)."""
        return self._plan

    @property
    def registry(self) -> CommandRegistry:
        """Registry used to validate draft values and build typed forms."""

        return self._registry

    def steps(self) -> list[PlannedCommand]:
        """Return the plan's steps (the plan's own mutable list)."""
        return self._plan.steps

    def selected_step_index(self) -> int:
        """Return the currently selected step index (0 for an empty plan)."""
        return self._selected

    def select_step(self, index: int) -> None:
        """Select one step by position; out-of-range raises ``IndexError``."""
        if not 0 <= index < len(self._plan.steps):
            raise IndexError(f"step index {index} out of range for {len(self._plan.steps)} steps")
        self._selected = index

    def params_of(self, step: PlannedCommand) -> dict[str, object]:
        """Return the live params dict of ``step``."""
        return step.params

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def replace_plan(self, plan: Plan) -> None:
        """Swap the whole draft plan (resets the selection to step 0)."""
        self._plan = plan
        self._selected = 0
        self.plan_replaced.emit()

    def new_draft(self, command_id: str) -> PlannedCommand:
        """Start a fresh single-step draft for ``command_id``.

        The step's ``affected_object`` comes from the Appendix B.2
        ``AFFECTED_OBJECTS`` table, so only the eight planned-able command
        ids can start a draft (raises ``ValueError`` otherwise — plugin
        commands are browse-able in the palette but not plan-able). Any
        previous draft is discarded (a plan swap, hence
        ``plan_replaced``).
        """
        spec = self._registry.get(command_id)
        affected = AFFECTED_OBJECTS.get(command_id)
        if affected is None:
            raise ValueError(f"command {command_id!r} cannot be planned (no affected object)")
        step = PlannedCommand(
            id=command_id,
            version=spec.version,
            params={},
            summary_en=spec.summary_en,
            # The table maps ids to the eight literal names the Literal
            # locks statically (Appendix B.2, single source).
            affected_object=cast("AffectedObject", affected),
        )
        self.replace_plan(Plan(steps=[step]))
        return step

    def set_params(self, step: PlannedCommand, params: dict[str, object]) -> dict[str, object]:
        """Validate ``params`` against the step's spec, then write them back.

        ``PlannedCommand`` is frozen, so a valid edit replaces the step
        with its params-filled copy in the plan's steps list; invalid
        params raise ``mycad.core.exceptions.ValidationError`` and leave
        the plan untouched. The validated (default-filled) params are
        broadcast via ``params_changed(step_index, validated)``, and the
        new step is returned.
        """
        if self._plan.status != "draft":
            raise ValidationError("confirmed plan content is frozen; create a new draft to edit")
        spec = self._registry.get(step.id, step.version)
        validated = normalize_params(validate_params(spec, params, defs=self._registry.schema_defs))
        index = self._plan.steps.index(step)
        new_step = replace(step, params=validated)
        self._plan.steps[index] = new_step
        self.params_changed.emit(index, validated)
        return validated
