# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 12: plan-card confirmation pipeline on the six-state plan machine.

Six-state sequence, illegal-transition button guards, atomic rollback with
zero history growth and identical mass properties, the two-command done path,
and the options-tab / card param sync through the shared controller.
"""

from __future__ import annotations

import threading
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document
from mycad.core.document import AFFECTED_OBJECTS, AffectedObject, PlannedCommand
from mycad.core.exceptions import ValidationError
from mycad.core.plan import Plan
from mycad.ui.execution import SerializedExecutionUnit
from mycad.ui.plan_cards import PlanCards
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.right_panel import RightPanel


@pytest.fixture
def services(qapp: object) -> AppServices:
    del qapp
    return build_app(discoverers=[])


def _step(services: AppServices, command_id: str, params: dict[str, object]) -> PlannedCommand:
    spec = services.registry.get(command_id)
    affected = AFFECTED_OBJECTS.get(command_id)
    assert affected is not None
    return PlannedCommand(
        id=command_id,
        version=spec.version,
        params=params,
        summary_en=spec.summary_en,
        affected_object=cast("AffectedObject", affected),
    )


def _two_command_plan(services: AppServices) -> Plan:
    return Plan(
        [
            _step(services, "feature.cylinder", {"radius": 40.0, "height": 8.0}),
            _step(
                services,
                "feature.hole",
                {
                    "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                    "position": {"kind": "center"},
                    "diameter": 6.0,
                    "depth": {"kind": "through_all"},
                },
            ),
        ]
    )


def _fail_second_plan(services: AppServices) -> Plan:
    """box then a fillet that passes schema validation but fails geometry."""
    return Plan(
        [
            _step(services, "feature.box", {"size_x": 30.0, "size_y": 30.0, "size_z": 10.0}),
            _step(
                services,
                "modify.fillet",
                {
                    "edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}],
                    "radius": 999.0,
                },
            ),
        ]
    )


def test_six_state_sequence_reaches_done(services: AppServices, qtbot: QtBot) -> None:
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    assert cards.plan is not None
    plan = _two_command_plan(services)
    draft.replace_plan(plan)
    assert cards.execute_enabled() is True
    assert cards.cancel_enabled() is True
    cards.execute_plan()
    assert plan.status == "done"
    assert len(loaded.document.commands) == 2
    assert loaded.document.revision == 1
    assert all(command.confirmed_by == "gui" for command in loaded.document.commands)
    assert "2 条命令" in cards.status_text()
    # Terminal state: the buttons cannot trigger an illegal transition.
    assert cards.execute_enabled() is False
    assert cards.cancel_enabled() is False
    cards.cancel_plan()
    assert plan.status == "done"
    assert len(loaded.document.commands) == 2


def test_cancelled_plan_cannot_execute_at_all(services: AppServices, qtbot: QtBot) -> None:
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    assert cards.plan is not None
    plan = _two_command_plan(services)
    draft.replace_plan(plan)
    cards.cancel_plan()
    assert plan.status == "cancelled"
    assert cards.execute_enabled() is False
    assert len(loaded.document.commands) == 0
    # even direct call is a no-op on a cancelled plan
    cards.execute_plan()
    assert plan.status == "cancelled"


def test_failed_plan_rolls_back_atomically(services: AppServices, qtbot: QtBot) -> None:
    mass_before = services.kernel.mass_properties()
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    assert cards.plan is not None
    plan = _fail_second_plan(services)
    draft.replace_plan(plan)
    cards.execute_plan()
    assert plan.status == "failed"
    assert len(loaded.document.commands) == 0  # zero growth, whole rollback
    mass_after = services.kernel.mass_properties()
    assert (mass_after.solid_count, mass_after.volume) == (
        mass_before.solid_count,
        mass_before.volume,
    )
    # The failed card is visibly red and the status states the matter.
    assert "执行失败" in cards.status_text()
    assert "回滚: 0" in cards.status_text()


def test_normal_plan_executes_two_commands(services: AppServices, qtbot: QtBot) -> None:
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    assert cards.plan is not None
    plan = _two_command_plan(services)
    draft.replace_plan(plan)
    cards.execute_plan()
    assert plan.status == "done"
    assert len(loaded.document.commands) == 2


def test_plan_card_submission_is_serialized_and_duplicate_click_is_ignored(
    services: AppServices, qtbot: QtBot
) -> None:
    unit = SerializedExecutionUnit()
    unit.set_session(3)
    entered = threading.Event()
    release = threading.Event()

    def prepare_geometry() -> None:
        entered.set()
        assert release.wait(5.0)
        services.kernel.viewport_data()

    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    try:
        cards.configure_execution(
            unit,
            session_id=lambda: 3,
            prepare_geometry=prepare_geometry,
        )
        plan = _two_command_plan(services)
        draft.replace_plan(plan)

        cards.execute_plan()
        assert unit.is_busy
        assert cards.execute_enabled() is False
        assert entered.wait(5.0)
        cards.execute_plan()
        assert plan.status == "done"
        assert len(loaded.document.commands) == 2
        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy)
        assert "2 条命令" in cards.status_text()
    finally:
        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy)
        assert unit.shutdown()


def test_plan_card_revokes_confirmation_when_worker_rejects_submission(
    services: AppServices, qtbot: QtBot
) -> None:
    unit = SerializedExecutionUnit()
    assert unit.shutdown()
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    cards.configure_execution(unit, session_id=lambda: 1, prepare_geometry=lambda: None)
    plan = _two_command_plan(services)
    draft.replace_plan(plan)

    cards.execute_plan()

    assert plan.status == "cancelled"
    assert loaded.document.commands == ()
    assert "确认已撤销" in cards.status_text()


def test_param_edit_syncs_cards_and_options(services: AppServices, qtbot: QtBot) -> None:
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    panel = RightPanel()
    qtbot.addWidget(cards)
    qtbot.addWidget(panel)
    loaded = new_document(services)
    panel.bind_document(loaded, services.registry)
    panel.bind_draft(draft)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    assert cards.plan is not None
    plan = _two_command_plan(services)
    draft.replace_plan(plan)
    steps = draft.steps()
    draft.select_step(0)
    assert steps[0].params.get("radius") == pytest.approx(40.0)
    # The options table edits the same controller the cards listen to.
    table = panel.options_table
    item = table.item(0, 1)
    assert item is not None  # radius row exists (default-prefilled params)
    item.setText("10.0")
    assert steps[0].params.get("radius") == pytest.approx(10.0)
    assert any("radius=10.0" in text for text in cards.card_texts())


def test_confirmed_plan_freezes_controller_parameter_edits(
    services: AppServices, qtbot: QtBot
) -> None:
    draft = PlanDraftController(services.registry)
    cards = PlanCards()
    qtbot.addWidget(cards)
    loaded = new_document(services)
    cards.bind_draft(draft)
    cards.bind_document(loaded)
    plan = _two_command_plan(services)
    draft.replace_plan(plan)
    step = plan.steps[0]
    before = dict(step.params)
    loaded.bus.confirm_plan(plan, "gui", scope="gui")

    with pytest.raises(ValidationError, match="confirmed"):
        draft.set_params(step, {"radius": 99.0, "height": 8.0})

    assert plan.steps[0].params == before
    assert loaded.document.commands == ()
