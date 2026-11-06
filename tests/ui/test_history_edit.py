# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bus-backed history edit confirmation and impact preview."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document, open_app_document
from mycad.core.exceptions import InvalidHistoryError
from mycad.core.measurements import MeasurementRequest
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import HistoryEditDialog


def _sketch_entities(params: Mapping[str, object]) -> list[dict[str, object]]:
    value = params.get("entities")
    assert isinstance(value, list)
    return [dict(cast("Mapping[str, object]", entity)) for entity in cast("list[object]", value)]


@pytest.mark.parametrize("action", ["discard", "commit"])
@pytest.mark.parametrize("notification", [False, True])
def test_stale_history_candidate_does_not_clear_current_viewport(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str, notification: bool
) -> None:
    from mycad.app import create_replay_candidate
    from mycad.core.replay_proposal import ReplayChangeSet

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    unit, viewport, panel = window.execution_unit, window.viewport, window.right_panel
    assert unit is not None and viewport is not None and panel is not None and unit.session_id > 0
    old_session = unit.session_id - 1
    candidate = create_replay_candidate(services, loaded, session_identity=old_session)
    candidate.stage(ReplayChangeSet((), (), False), current_session_identity=old_session)
    before = loaded.document.commands
    cleared: list[bool] = []

    def record_clear() -> None:
        cleared.append(True)

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)

    def perform_action(_result: object = None) -> None:
        if action == "discard":
            panel.history_candidate_discard_requested.emit(candidate)
        else:
            panel.history_candidate_commit_requested.emit(candidate, 0)

    if notification:
        unit.result_ready.connect(perform_action)
        assert unit.submit(lambda: None, operation="test-stale-history", session_id=unit.session_id)
        qtbot.waitUntil(lambda: candidate.state == "cancelled", timeout=10000)
        unit.result_ready.disconnect(perform_action)
    else:
        perform_action()
    assert not cleared
    assert loaded.document.commands == before
    assert candidate.state == "cancelled"


@pytest.mark.parametrize("action", ["discard", "commit"])
def test_completed_history_candidate_ignores_late_actions(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from mycad.app import create_replay_candidate
    from mycad.core.replay_proposal import ReplayChangeSet, ReplayEdit

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet(
            (ReplayEdit(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "local", "调整尺寸"),),
            (),
            False,
        ),
        current_session_identity=0,
    )
    assert candidate.preview(current_session_identity=0).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, panel = window.viewport, window.right_panel
    assert viewport is not None and panel is not None
    cleared: list[bool] = []

    def record_clear() -> None:
        cleared.append(True)

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    if action == "discard":
        panel.history_candidate_discard_requested.emit(candidate)
    else:
        panel.history_candidate_commit_requested.emit(candidate, 0)
    assert not cleared and candidate.state == "committed"
    assert loaded.document.commands == before


def _history_with_downstream_commands() -> tuple[AppServices, LoadedDocument]:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    loaded.bus.execute("feature.cylinder", {"radius": 1.0, "height": 20.0, "mode": "cut"}, "test")
    loaded.bus.execute("feature.cylinder", {"radius": 0.5, "height": 20.0, "mode": "cut"}, "test")
    return services, loaded


@pytest.mark.parametrize("operation", ["confirm", "preview", "repair", "accept"])
def test_history_dialog_waits_before_consuming_candidate(qtbot: QtBot, operation: str) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    busy = [False]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
        can_cancel=lambda: not busy[0],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    candidate = object()
    assert dialog.candidate_preview_finished(
        candidate, "候选就绪", repairable=operation == "repair"
    )
    busy[0] = True
    if operation == "confirm":
        dialog.confirm_changes()
    elif operation == "preview":
        dialog.preview_changes()
    elif operation == "repair":
        dialog.begin_repair()
    else:
        dialog.accept()
    assert dialog.isVisible()
    assert dialog.candidate is candidate
    assert "等待" in dialog.impact_label.text()
    assert loaded.document.commands[0].params["radius"] == 5.0
    busy[0] = False
    dialog.reject()


@pytest.mark.parametrize("notification", ["idle", "result"])
def test_history_edit_does_not_start_during_execution_notification(
    qtbot: QtBot, notification: str
) -> None:
    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    unit, panel = window.execution_unit, window.right_panel
    assert unit is not None and panel is not None
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    observed: list[tuple[bool, bool, str]] = []

    def on_result(_result: object) -> None:
        panel.history_candidate_open_requested.emit(dialog, command.ordinal)
        observed.append(
            (window.history_edit_task is None, dialog.isVisible(), window.status_command.text())
        )

    def on_idle(busy: bool) -> None:
        if not busy:
            on_result(None)

    if notification == "idle":
        unit.busy_changed.connect(on_idle)
    else:
        unit.result_ready.connect(on_result)
    assert unit.submit(lambda: None, operation="test-history-open", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed) and not unit.is_delivering_result, timeout=10000)
    assert observed[0][:2] == (True, False)
    assert "等待" in observed[0][2] or "忙" in observed[0][2]
    assert loaded.document.commands[0].params["radius"] == 5.0


def test_history_edit_can_start_in_owning_completion_callback(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    unit, panel = window.execution_unit, window.right_panel
    assert unit is not None and panel is not None
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    opened: list[bool] = []

    def on_complete(_result: object) -> None:
        panel.history_candidate_open_requested.emit(dialog, command.ordinal)
        opened.append(window.history_edit_task is dialog)

    assert unit.submit(
        lambda: None,
        operation="test-history-open-followup",
        session_id=unit.session_id,
        on_complete=on_complete,
    )
    qtbot.waitUntil(lambda: bool(opened), timeout=10000)
    assert opened == [True]
    dialog.reject()


@pytest.mark.parametrize("phase", ["busy", "notification"])
def test_history_dialog_cancel_completes_after_execution_handoff(qtbot: QtBot, phase: str) -> None:
    from threading import Event

    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    unit = window.execution_unit
    assert unit is not None
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
        can_cancel=lambda: not (unit.is_busy or unit.is_notifying_idle or unit.is_notifying_result),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    finished: list[int] = []
    observed: list[int] = []
    dialog.finished.connect(finished.append)
    entered, release = Event(), Event()

    def work() -> None:
        entered.set()
        assert release.wait(10)

    def cancel_on_result(_result: object) -> None:
        dialog.reject()
        observed.append(len(finished))

    if phase == "notification":
        unit.result_ready.connect(cancel_on_result)
    assert unit.submit(work, operation="test-history-cancel", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        if phase == "busy":
            dialog.reject()
            observed.append(len(finished))
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(finished), timeout=10000)
    assert observed == [0] and len(finished) == 1
    assert loaded.document.commands[0].params["radius"] == 5.0


def test_history_dialog_rejects_preview_result_after_cancel_requested(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    busy = [False]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
        can_cancel=lambda: not busy[0],
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    busy[0] = True
    dialog.reject()
    assert dialog.cancel_requested
    assert not dialog.candidate_preview_finished(object(), "迟到的预览")
    assert dialog.candidate is None and not dialog.confirm_button.isEnabled()
    busy[0] = False
    qtbot.waitUntil(lambda: not dialog.cancel_requested, timeout=5000)


def test_closed_history_dialog_ignores_late_controls_and_results(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    candidate = object()
    assert dialog.candidate_preview_finished(candidate, "候选就绪")
    finished: list[int] = []
    discarded: list[object] = []
    requested: list[bool] = []

    def record_request(_params: object, _reason: str) -> None:
        requested.append(True)

    dialog.finished.connect(finished.append)
    dialog.candidate_discard_requested.connect(discarded.append)
    dialog.candidate_preview_requested.connect(record_request)
    dialog.confirm_changes()
    dialog.reason_field.setText("迟到的修改")
    dialog.preview_changes()
    dialog.begin_repair()
    dialog.confirm_changes()
    assert not dialog.candidate_preview_finished(object(), "迟到的结果")
    dialog.reject()
    dialog.accept()
    assert len(finished) == 1 and not discarded and not requested
    assert dialog.candidate is candidate


def test_datum_tree_edit_previews_and_commits_name(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.app import create_replay_candidate
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
    from mycad.core.spatial_references import SpatialReference
    from mycad.ui.right_panel import DATUM_ROLE

    services = build_app(discoverers=[])
    loaded = new_document(services)
    candidate = create_replay_candidate(services, loaded, session_identity=1)
    params = {
        "name": "基准面 A",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xy",
        },
    }
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, params, "local"),), False, 6),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    tree = panel.structure_tree
    items = tree.findItems("基准面 A", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive)
    assert len(items) == 1
    tree.expandAll()
    tree.scrollToItem(items[0])
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(items[0]).center()
    )
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None and not button.isHidden() and button.isEnabled()
    reference = items[0].data(0, DATUM_ROLE)
    assert isinstance(reference, SpatialReference)
    panel.select_feature_ordinal(None)
    panel.select_datum_reference(reference)
    assert not button.isHidden() and button.isEnabled()
    assert button.text() == "编辑选中基准…"
    button.click()
    task = window.history_edit_task
    assert task is not None
    task.parameter_form.set_value("name", "基准面 B")
    task.reason_field.setText("调整基准名称")
    task.preview_changes()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    assert loaded.document.commands[0].params["name"] == "基准面 A"
    task.confirm_changes()
    qtbot.waitUntil(lambda: loaded.document.commands[0].params["name"] == "基准面 B")
    archive = tmp_path / "datum-history.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands[0].params["name"] == "基准面 B"


def test_datum_edit_replays_dependent_offset_plane(qtbot: QtBot) -> None:
    from mycad.app import create_replay_candidate
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = build_app(discoverers=[])
    loaded = new_document(services)

    def append_plane(params: dict[str, object]) -> None:
        candidate = create_replay_candidate(services, loaded, session_identity=1)
        candidate.stage(
            ReplayChangeSet(
                (), (ReplayAppend("datum.plane.create", 1, params, "local"),), False, 6
            ),
            current_session_identity=1,
        )
        assert candidate.preview(current_session_identity=1).state == "succeeded"
        candidate.commit(
            candidate.authorize_commit(current_session_identity=1), current_session_identity=1
        )

    append_plane(
        {
            "name": "源平面",
            "construction": {
                "kind": "principal",
                "coordinate_system": {"kind": "world"},
                "plane": "xy",
            },
        }
    )
    source_id = loaded.document.commands[0].instance_id
    assert source_id is not None
    append_plane(
        {
            "name": "偏置面",
            "construction": {
                "kind": "offset",
                "plane": {"kind": "datum_plane", "source_instance_id": source_id, "role": "plane"},
                "distance_mm": 5.0,
            },
        }
    )
    old_datums = services.kernel.datum_display_data()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None and button.isEnabled()
    button.click()
    task = window.history_edit_task
    assert task is not None
    task.parameter_form.set_value(
        "construction", {"kind": "principal", "coordinate_system": {"kind": "world"}, "plane": "xz"}
    )
    task.reason_field.setText("调整基准方向")
    task.preview_changes()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    assert services.kernel.datum_display_data() == old_datums
    task.confirm_changes()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=20000)
    assert loaded.document.commands[0].params["construction"] == {
        "kind": "principal",
        "coordinate_system": {"kind": "world"},
        "plane": "xz",
    }
    changed = services.kernel.datum_display_data()
    assert changed[0].reference == old_datums[0].reference
    assert changed[1].reference == old_datums[1].reference
    assert changed[1].frame.origin_mm != old_datums[1].frame.origin_mm
    loaded.bus.undo()
    assert services.kernel.datum_display_data() == changed[:1]
    loaded.bus.redo()
    assert services.kernel.datum_display_data() == changed


def test_history_edit_preview_shows_ordinal_downstream_and_normalized_delta(qapp: object) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
    )
    form = dialog.parameter_form
    radius = form.field_widget("radius")
    assert isinstance(radius, QDoubleSpinBox)
    radius.setValue(6.0)

    dialog.preview_changes()

    assert "#0" in dialog.impact_label.text()
    assert "2 条" in dialog.impact_label.text()
    assert '"radius"' in dialog.impact_label.text()
    confirm = dialog.findChild(QPushButton, "confirmHistoryEdit")
    assert confirm is not None and confirm.isEnabled()
    dialog.reason_field.setText("调整外径")
    confirm.click()
    assert dialog.result_params["radius"] == 6.0
    assert dialog.edit_reason == "调整外径"


def test_history_edit_rejects_noop_until_a_real_change_is_proposed(qapp: object) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
    )

    dialog.preview_changes()

    confirm = dialog.findChild(QPushButton, "confirmHistoryEdit")
    assert confirm is not None
    assert not confirm.isEnabled()
    assert "没有变化" in dialog.impact_label.text()


def test_editing_sketch_history_rebuilds_downstream_extrusion(qtbot: QtBot, tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    entity_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame.xy(),
            (CircleEntity(entity_id, (0.0, 0.0), 5.0),),
        ).to_mapping(),
        confirmed_by="gui-local",
    )
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": sketch_id},
            "distance": 10.0,
            "mode": "new",
        },
        confirmed_by="gui-local",
        version=2,
    )
    original_timestamp = loaded.document.commands[0].timestamp_utc
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    edit_button = panel.findChild(QPushButton, "editHistoryFeature")
    assert edit_button is not None and not edit_button.isHidden() and edit_button.isEnabled()
    assert edit_button.text() == "编辑选中草图…"

    def edit_sketch_dialog() -> None:
        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        try:
            params = loaded.document.commands[0].params
            entities = _sketch_entities(params)
            entities[0]["radius_mm"] = 6.0
            dialog.parameter_form.set_value("entities", entities)
            dialog.reason_field.setText("调整草图直径")
            dialog.preview_changes()
            assert "1 条下游命令" in dialog.impact_label.text()
            assert not dialog.confirm_button.isEnabled()
            qtbot.waitUntil(lambda: dialog.confirm_button.isEnabled(), timeout=20000)
            assert "候选重放成功" in dialog.impact_label.text()
            assert dialog.impact_label.toolTip() == dialog.impact_label.text()
            assert _sketch_entities(loaded.document.commands[0].params)[0]["radius_mm"] == 5.0
            dialog.confirm_changes()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, edit_sketch_dialog)
    edit_button.click()
    qtbot.waitUntil(
        lambda: _sketch_entities(loaded.document.commands[0].params)[0]["radius_mm"] == 6.0
    )
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)

    edited = loaded.document.commands[0]
    edited_entity = _sketch_entities(edited.params)[0]
    assert edited_entity["entity_id"] == entity_id
    assert edited.timestamp_utc == original_timestamp
    amended_entity = _sketch_entities(edited.amendments[-1].from_params)[0]
    assert amended_entity["radius_mm"] == 5.0
    assert services.kernel.mass_properties().volume == pytest.approx(360.0 * 3.141592653589793)
    archive = tmp_path / "candidate-history.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert _sketch_entities(reopened.document.commands[0].params)[0]["radius_mm"] == 6.0
    assert reopened.document.commands[0].amendments == edited.amendments
    assert services.kernel.mass_properties().volume == pytest.approx(360.0 * 3.141592653589793)
    window.close()


def test_repaired_face_selector_is_committed_only_through_bus_amendment(qapp: object) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0}, "test")
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
        "test",
    )
    command = loaded.document.commands[1]
    timestamp = command.timestamp_utc
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=(),
    )
    dialog.parameter_form.set_value("target_face", {"surface": "plane", "axis": "-Z", "rank": 0})
    dialog.reason_field.setText("修复目标面的方向引用")
    dialog.preview_changes()
    dialog.confirm_changes()
    assert dialog.result_params["target_face"] == {
        "surface": "plane",
        "axis": "-Z",
        "rank": 0,
    }

    loaded.bus.edit_and_replay(
        command.ordinal,
        dialog.result_params,
        "gui-local",
        dialog.edit_reason,
    )

    repaired = loaded.document.commands[1]
    repaired_face = repaired.params["target_face"]
    assert isinstance(repaired_face, dict)
    assert repaired_face["axis"] == "-Z"
    assert repaired.timestamp_utc == timestamp
    assert len(repaired.amendments) == 1
    assert repaired.amendments[0].actor == "gui-local"
    assert "修复" in repaired.amendments[0].reason


def test_window_undo_redo_restores_history_edit(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    before = loaded.document.commands
    loaded.bus.edit_and_replay(0, {"radius": 6.0, "height": 8.0}, "gui-local", "增大外径")
    edited = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    unit = window.execution_unit
    assert unit is not None

    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=20000)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == edited, timeout=20000)


def test_confirmed_edit_uses_worker_preserves_audit_and_clears_redo(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services, loaded = _history_with_downstream_commands()
    loaded.bus.undo()
    timestamp = loaded.document.commands[0].timestamp_utc
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    panel = window.right_panel
    assert panel is not None
    panel.history_edit_requested.emit(0, {"radius": 6.0, "height": 8.0}, "gui-local", "增大外径")

    qtbot.waitUntil(lambda: loaded.document.commands[0].params["radius"] == 6.0)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)

    edited = loaded.document.commands[0]
    assert edited.timestamp_utc == timestamp
    assert edited.amendments[-1].from_params == {
        "radius": 5.0,
        "height": 8.0,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    }
    assert edited.amendments[-1].actor == "gui-local"
    assert loaded.document.is_dirty
    with pytest.raises(InvalidHistoryError):
        loaded.bus.redo()
    measured = services.kernel.measure(
        MeasurementRequest(kind="body_volume", revision=services.kernel.geometry_revision)
    )
    assert measured.value == pytest.approx(280.0 * 3.141592653589793)

    archive = tmp_path / "edited.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands[0].timestamp_utc == timestamp
    assert reopened.document.commands[0].amendments == edited.amendments
    assert reopened.document.commands[0].params["radius"] == 6.0
    window.close()


def test_failed_downstream_replay_rolls_back_and_reports_failing_command(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, "test")
    loaded.bus.execute(
        "modify.fillet",
        {"edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}], "radius": 4.0},
        "test",
    )
    before = loaded.document.commands
    before_volume = services.kernel.mass_properties().volume
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    panel = window.right_panel
    assert panel is not None
    panel.history_edit_requested.emit(
        0,
        {"size_x": 8.0, "size_y": 10.0, "size_z": 10.0, "center": [0.0, 0.0, 0.0]},
        "gui-local",
        "缩小宽度以验证圆角重放",
    )

    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)

    assert loaded.document.commands == before
    assert services.kernel.mass_properties().volume == pytest.approx(before_volume)
    assert "历史编辑失败" in window.status_command.text()
    assert "modify.fillet" in window.status_command.text()
    window.close()


def test_candidate_history_dialog_waits_for_actual_replay_before_confirm(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    with qtbot.waitSignal(dialog.candidate_preview_requested, timeout=1000):
        dialog.preview_changes()
    assert not dialog.confirm_button.isEnabled()
    assert "正在" in dialog.impact_label.text()
    assert loaded.document.commands[0].params["radius"] == 5.0


def test_failed_candidate_replay_keeps_dialog_and_original_model(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0}, "test")
    loaded.bus.execute(
        "modify.fillet",
        {"edges": [{"parent_faces": [{"surface": "plane", "axis": "+Z"}]}], "radius": 4.0},
        "test",
    )
    before = loaded.document.commands
    volume = services.kernel.mass_properties().volume
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None

    def inspect_dialog() -> None:
        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        try:
            dialog.parameter_form.set_value("size_x", 8.0)
            dialog.reason_field.setText("验证下游圆角")
            dialog.preview_changes()
            qtbot.waitUntil(lambda: "候选重放失败" in dialog.impact_label.text(), timeout=20000)
            assert "modify.fillet" in dialog.impact_label.text()
            assert not dialog.confirm_button.isEnabled()
            assert loaded.document.commands == before
            assert services.kernel.mass_properties().volume == pytest.approx(volume)
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect_dialog)
    button.click()
    qtbot.waitUntil(lambda: window.history_edit_task is None, timeout=30000)
    assert loaded.document.commands == before
    window.close()


def test_history_candidate_changed_reason_cannot_be_confirmed(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("原原因")
    dialog.preview_changes()
    assert dialog.candidate_preview_finished(object(), "候选重放成功")
    dialog.reason_field.setText("修改原因")
    assert not dialog.confirm_button.isEnabled()
    assert dialog.candidate is None
    assert "重新预览" in dialog.impact_label.text()
    assert loaded.document.commands[0].params["radius"] == 5.0


def test_history_candidate_preview_rejects_changed_parameters(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    dialog.parameter_form.set_value("radius", 7.0)
    assert not dialog.candidate_preview_finished(object(), "候选重放成功")
    assert not dialog.confirm_button.isEnabled()
    assert dialog.candidate is None
    assert "重新预览" in dialog.impact_label.text()


def test_stale_history_candidate_cannot_replace_newer_document(qtbot: QtBot) -> None:
    from mycad.app import create_replay_candidate
    from mycad.core.replay_proposal import ReplayChangeSet, ReplayEdit

    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    identity = window.drawing_workbench.session_id
    candidate = create_replay_candidate(services, loaded, session_identity=identity)
    params = dict(loaded.document.commands[0].params)
    params["radius"] = 6.0
    candidate.stage(
        ReplayChangeSet((ReplayEdit(0, params, "gui-local", "调整外径"),), (), False),
        current_session_identity=identity,
    )
    assert candidate.preview(current_session_identity=identity).state == "succeeded"
    loaded.bus.undo()
    latest = loaded.document.commands
    panel = window.right_panel
    assert panel is not None
    panel.history_candidate_commit_requested.emit(candidate, 0)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=20000)
    assert loaded.document.commands == latest
    assert "历史编辑失败" in window.status_command.text()
    window.close()


@pytest.mark.parametrize("interruption", ["session", "close"])
def test_history_preview_is_discarded_after_interruption(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    from threading import Event

    from mycad.app import ReplayCandidatePreview, ReplayCandidateSession

    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        parent=window,
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    started, release = Event(), Event()
    seen: list[ReplayCandidateSession] = []
    original = ReplayCandidateSession.preview

    def delayed_preview(
        candidate: ReplayCandidateSession, *, current_session_identity: int
    ) -> ReplayCandidatePreview:
        seen.append(candidate)
        started.set()
        assert release.wait(20)
        return original(candidate, current_session_identity=current_session_identity)

    monkeypatch.setattr(ReplayCandidateSession, "preview", delayed_preview)

    def request_preview(params: object, reason: str) -> None:
        panel = window.right_panel
        assert panel is not None
        panel.history_candidate_preview_requested.emit(dialog, 0, params, reason)

    dialog.candidate_preview_requested.connect(request_preview)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    try:
        dialog.preview_changes()
        qtbot.waitUntil(started.is_set, timeout=10000)
        if interruption == "session":
            window.bind_document(loaded)
        else:
            dialog.reject()
    finally:
        release.set()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=20000)
    assert len(seen) == 1 and seen[0].state == "cancelled"
    assert dialog.candidate is None and not dialog.confirm_button.isEnabled()
    if interruption == "session":
        assert "文档已切换" in dialog.impact_label.text()
    assert loaded.document.commands[0].params["radius"] == 5.0
    dialog.reject()
    window.close()


def test_history_candidate_preview_preserves_unsubmitted_drawing_note(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.drawing_workbench.notes.begin()
    window.drawing_workbench.notes.click((40.0, 40.0))
    window.drawing_workbench.notes.editor.setPlainText("未提交文字")
    assert window.drawing_workbench.notes.pending
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        parent=window,
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    panel = window.right_panel
    assert panel is not None

    def request_preview(params: object, reason: str) -> None:
        panel.history_candidate_preview_requested.emit(dialog, 0, params, reason)

    dialog.candidate_preview_requested.connect(request_preview)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    assert not dialog.confirm_button.isEnabled()
    assert "完成或取消" in dialog.impact_label.text()
    assert window.drawing_workbench.notes.editor.toPlainText() == "未提交文字"
    assert loaded.document.commands[0].params["radius"] == 5.0
    window.drawing_workbench.notes.cancel()
    window.close()


@pytest.mark.parametrize("followup", [False, True])
@pytest.mark.parametrize("external_preview", [False, True])
@pytest.mark.parametrize("external_cancel", [False, True])
def test_cancelling_history_candidate_preserves_original_model(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    followup: bool,
    external_preview: bool,
    external_cancel: bool,
) -> None:
    from mycad.app import ReplayCandidateSession

    services, loaded = _history_with_downstream_commands()
    before = loaded.document.commands
    volume = services.kernel.mass_properties().volume
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None
    cancelled: list[ReplayCandidateSession] = []
    viewport = window.viewport
    unit = window.execution_unit
    assert viewport is not None and unit is not None
    rendered: list[object] = []
    cleared: list[bool] = []
    original_show = viewport.show_candidate_preview
    original_clear = viewport.clear_candidate_preview

    def capture_preview(
        snapshot: object,
        *,
        preserve_view: bool = False,
        sketches: object = None,
    ) -> None:
        from mycad.core.viewport_protocol import ViewportData, ViewportSketchData

        assert isinstance(snapshot, ViewportData)
        assert sketches is None or isinstance(sketches, tuple)
        rendered.append(snapshot)
        original_show(
            snapshot,
            preserve_view=preserve_view,
            sketches=cast("tuple[ViewportSketchData, ...] | None", sketches),
        )

    monkeypatch.setattr(viewport, "show_candidate_preview", capture_preview)

    def capture_clear() -> None:
        cleared.append(True)
        original_clear()

    monkeypatch.setattr(viewport, "clear_candidate_preview", capture_clear)
    original_cancel = ReplayCandidateSession.cancel

    def record_cancel(candidate: ReplayCandidateSession) -> None:
        original_cancel(candidate)
        cancelled.append(candidate)

    monkeypatch.setattr(ReplayCandidateSession, "cancel", record_cancel)

    def inspect_dialog() -> None:
        from mycad.core.viewport_protocol import ViewportData

        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        other_snapshot: ViewportData | None = None
        try:
            dialog.parameter_form.set_value("radius", 6.0)
            dialog.reason_field.setText("调整外径")
            dialog.preview_changes()
            qtbot.waitUntil(lambda: dialog.confirm_button.isEnabled(), timeout=20000)
            original_candidate = dialog.candidate
            held_during_notification: list[tuple[bool, bool]] = []

            def try_actions_on_result(_result: object) -> None:
                dialog.confirm_changes()
                dialog.preview_changes()
                dialog.begin_repair()
                held_during_notification.append(
                    (dialog.isVisible(), dialog.candidate is original_candidate)
                )

            unit.result_ready.connect(try_actions_on_result)
            assert unit.submit(
                lambda: None, operation="test-history-handover", session_id=unit.session_id
            )
            qtbot.waitUntil(
                lambda: bool(held_during_notification) and not unit.is_delivering_result,
                timeout=10000,
            )
            unit.result_ready.disconnect(try_actions_on_result)
            assert held_during_notification == [(True, True)]
            clear_before = len(cleared)
            during_notification: list[tuple[int, bool, bool]] = []

            def invalidate_on_result(_result: object) -> None:
                unit.result_ready.disconnect(invalidate_on_result)
                dialog.reason_field.setText("调整外径并说明原因")
                during_notification.append(
                    (len(cleared), dialog.candidate is None, dialog.confirm_button.isEnabled())
                )

            unit.result_ready.connect(invalidate_on_result)
            assert unit.submit(
                lambda: None,
                operation="test-history-invalidate",
                session_id=unit.session_id,
                on_complete=(lambda _result: dialog.preview_changes()) if followup else None,
            )
            qtbot.waitUntil(lambda: bool(during_notification), timeout=10000)
            assert during_notification == [(clear_before, True, False)]
            qtbot.waitUntil(lambda: len(cancelled) == 1, timeout=10000)
            assert len(cancelled) == 1 and cancelled[0].state == "cancelled"
            if followup:
                assert len(cleared) == clear_before
            else:
                assert not dialog.confirm_button.isEnabled()
                dialog.preview_changes()
            qtbot.waitUntil(lambda: dialog.confirm_button.isEnabled(), timeout=20000)
            clear_count = len(cleared)
            panel.history_candidate_discard_requested.emit(cancelled[0])
            assert len(cleared) == clear_count
            assert dialog.confirm_button.isEnabled()
            if external_preview:
                from dataclasses import replace

                other_snapshot = replace(cast("ViewportData", rendered[-1]))
                viewport.show_candidate_preview(other_snapshot, preserve_view=True)
            if external_cancel:
                current_candidate = dialog.candidate
                assert isinstance(current_candidate, ReplayCandidateSession)
                current_candidate.cancel()
                clear_count = len(cleared)
                panel.history_candidate_discard_requested.emit(current_candidate)
                assert len(cleared) == clear_count + int(not external_preview)
            if external_preview:
                assert other_snapshot is not None
                clear_count = len(cleared)
                dialog.reject()
                assert len(cleared) == clear_count
                assert viewport.displays_candidate_preview(other_snapshot)
        finally:
            dialog.reject()

    QTimer.singleShot(0, inspect_dialog)
    button.click()
    qtbot.waitUntil(lambda: window.history_edit_task is None, timeout=30000)
    assert len(cancelled) == 2 and all(item.state == "cancelled" for item in cancelled)
    assert len(rendered) == (3 if external_preview else 2)
    assert len(cleared) >= (0 if followup else 1) + int(not external_preview)
    assert loaded.document.commands == before
    assert services.kernel.mass_properties().volume == pytest.approx(volume)
    window.close()


def test_failed_bound_hole_candidate_offers_explicit_repair_without_confirm(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    command = loaded.document.commands[0]
    dialog = HistoryEditDialog(
        services.registry.get(command.id, command.version),
        command.params,
        services.registry,
        ordinal=command.ordinal,
        downstream=loaded.document.commands[1:],
        candidate_preview=True,
    )
    qtbot.addWidget(dialog)
    dialog.parameter_form.set_value("radius", 6.0)
    dialog.reason_field.setText("调整外径")
    dialog.preview_changes()
    candidate = object()
    assert dialog.candidate_preview_finished(candidate, "绑定面失效", repairable=True)
    assert not dialog.confirm_button.isEnabled()
    assert dialog.repair_button.isEnabled()
    dialog.reason_field.setText("原因已改变")
    assert not dialog.repair_button.isEnabled()
    assert dialog.candidate is None


@pytest.mark.parametrize(
    "completion",
    [
        "commit",
        "cancel",
        "stale",
        "busy_cancel",
        "stale_entry",
        "stale_callback",
        "notification",
        "notification_no_preview",
        "notification_idle",
        "notification_stale",
        "followup",
        "cancel_notification",
        "cancel_commit_notification",
        "cancel_unrelated_busy",
        "cancel_followup",
    ],
)
def test_failed_upstream_history_edit_rebinds_hole_in_prefix_and_commits(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completion: str
) -> None:
    from math import pi

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    loaded.bus.execute(
        "feature.box", {"size_x": 20, "size_y": 20, "size_z": 6, "center": [-20, 0, 0]}
    )
    loaded.bus.execute(
        "feature.cylinder", {"radius": 8, "height": 6, "center": [20, 0, 0], "mode": "add"}
    )
    box_id = loaded.document.commands[0].instance_id
    cylinder_id = loaded.document.commands[1].instance_id
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"kind": "bound_face", "source_instance_id": box_id, "role": "box.+Z"},
            "position": {"kind": "local", "uv_mm": [0, 0]},
            "diameter": 2,
            "depth": {"kind": "blind", "value": 2},
        },
        version=3,
    )
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(1)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None

    def propose() -> None:
        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        try:
            dialog.parameter_form.set_value("mode", "new")
            dialog.reason_field.setText("替换上游实体")
            dialog.preview_changes()
            qtbot.waitUntil(lambda: dialog.repair_button.isEnabled(), timeout=20000)
            assert not dialog.confirm_button.isEnabled()
            assert loaded.document.commands == before
            dialog.repair_button.click()
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, propose)
    button.click()
    qtbot.waitUntil(lambda: window.history_repair_task is not None, timeout=30000)
    task, viewport, unit = window.history_repair_task, window.viewport, window.execution_unit
    assert task is not None and viewport is not None and unit is not None
    if completion == "cancel_followup":
        cancel_cleared: list[bool] = []
        cancel_callback_clears: list[int] = []
        cancel_finished: list[int] = []
        task.finished.connect(cancel_finished.append)

        def record_cancel_clear() -> None:
            cancel_cleared.append(True)

        def cancel_before_callback(_result: object) -> None:
            task.reject()

        def restart_after_cancel(_result: object) -> None:
            task.reselect()
            cancel_callback_clears.append(len(cancel_cleared))

        monkeypatch.setattr(viewport, "clear_candidate_preview", record_cancel_clear)
        unit.result_ready.connect(cancel_before_callback)
        assert unit.submit(
            lambda: None,
            operation="test-repair-cancel-restart",
            session_id=unit.session_id,
            on_complete=restart_after_cancel,
        )
        qtbot.waitUntil(lambda: bool(cancel_finished), timeout=10000)
        assert cancel_callback_clears == [0] and cancel_cleared == [True]
        assert not unit.is_busy and loaded.document.commands == before
        return
    if completion == "cancel_unrelated_busy":
        from threading import Event

        busy_finished: list[int] = []
        task.finished.connect(busy_finished.append)
        entered, release = Event(), Event()

        def unrelated_work() -> None:
            entered.set()
            assert release.wait(10)

        assert unit.submit(
            unrelated_work, operation="test-repair-unrelated", session_id=unit.session_id
        )
        try:
            qtbot.waitUntil(entered.is_set, timeout=5000)
            task.reject()
            assert not busy_finished
        finally:
            release.set()
        qtbot.waitUntil(lambda: bool(busy_finished), timeout=5000)
        assert len(busy_finished) == 1 and loaded.document.commands == before
        return
    if completion in {"cancel_notification", "cancel_commit_notification"}:
        cancellation_finished: list[int] = []
        cancellation_observed: list[int] = []
        task.finished.connect(cancellation_finished.append)
        monkeypatch.setattr(task, "_committing", completion == "cancel_commit_notification")

        def cancel_on_result(_result: object) -> None:
            task.reject()
            cancellation_observed.append(len(cancellation_finished))

        unit.result_ready.connect(cancel_on_result)
        assert unit.submit(lambda: None, operation="test-repair-cancel", session_id=unit.session_id)
        qtbot.waitUntil(
            lambda: bool(cancellation_observed) and not unit.is_delivering_result, timeout=10000
        )
        assert cancellation_observed == [0]
        if completion == "cancel_commit_notification":
            qtbot.wait(100)
            assert not cancellation_finished and "提交" in task.status_label.text()
            monkeypatch.setattr(task, "_committing", False)
            task.reject()
        else:
            qtbot.waitUntil(lambda: bool(cancellation_finished), timeout=10000)
        assert len(cancellation_finished) == 1
        assert loaded.document.commands == before
        return
    if completion == "followup":
        followup_cleared: list[bool] = []

        def record_followup_clear() -> None:
            followup_cleared.append(True)

        def change_before_followup(_result: object) -> None:
            unit.result_ready.disconnect(change_before_followup)
            task.u_field.setValue(1.0)

        monkeypatch.setattr(viewport, "clear_candidate_preview", record_followup_clear)
        monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
        monkeypatch.setattr(task, "_preview_params", {"diameter": 2.0})
        unit.result_ready.connect(change_before_followup)
        assert unit.submit(
            lambda: None,
            operation="test-repair-followup",
            session_id=unit.session_id,
            on_complete=lambda _result: task.reselect(),
        )
        qtbot.waitUntil(lambda: task.scene is not None and not unit.is_busy, timeout=20000)
        qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
        qtbot.wait(100)
        assert followup_cleared == [True]
        task.reject()
        assert loaded.document.commands == before
        return
    if completion in {
        "notification",
        "notification_no_preview",
        "notification_idle",
        "notification_stale",
    }:
        handover_cleared: list[bool] = []
        handover_observed: list[tuple[int, bool]] = []
        handover_session = [unit.session_id]

        def record_handover_clear() -> None:
            handover_cleared.append(True)

        def on_result(_result: object) -> None:
            task.u_field.setValue(1.0)
            task.u_field.setValue(2.0)
            task.reselect()
            handover_observed.append((len(handover_cleared), task.confirm_button.isEnabled()))
            if completion == "notification_stale":
                handover_session[0] += 1

        def on_idle(busy: bool) -> None:
            if not busy:
                on_result(None)

        monkeypatch.setattr(viewport, "clear_candidate_preview", record_handover_clear)
        monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
        monkeypatch.setattr(
            task,
            "_preview_params",
            None if completion == "notification_no_preview" else {"diameter": 2.0},
        )
        monkeypatch.setattr(task, "_current_session", lambda: handover_session[0])
        task.confirm_button.setEnabled(True)
        if completion == "notification_idle":
            unit.busy_changed.connect(on_idle)
        else:
            unit.result_ready.connect(on_result)
        assert unit.submit(
            lambda: None, operation="test-repair-handover", session_id=unit.session_id
        )
        qtbot.waitUntil(
            lambda: bool(handover_observed) and not unit.is_delivering_result, timeout=10000
        )
        assert handover_observed == [(0, False)]
        if completion == "notification_stale":
            qtbot.wait(150)
            assert not handover_cleared
        else:
            qtbot.waitUntil(task.preview_button.isEnabled, timeout=5000)
            assert len(handover_cleared) == int(completion != "notification_no_preview")
        assert not task.confirm_button.isEnabled()
        task.reject()
        assert loaded.document.commands == before
        return
    if completion == "stale_callback":
        session = [unit.session_id]
        delivered: list[bool] = []
        shown: list[bool] = []

        def record_scene(*_args: object, **_kwargs: object) -> None:
            shown.append(True)

        def change_session(_result: object) -> None:
            session[0] += 1
            delivered.append(True)

        monkeypatch.setattr(task, "_current_session", lambda: session[0])
        monkeypatch.setattr(viewport, "show_interaction_scene", record_scene)
        unit.result_ready.connect(change_session)
        task.reselect()
        qtbot.waitUntil(lambda: bool(delivered) and not unit.is_busy, timeout=20000)
        qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=20000)
        assert not shown and task.scene is None
        assert loaded.document.commands == before
        return
    if completion == "stale_entry":
        cleared: list[bool] = []
        submitted: list[bool] = []
        finished: list[int] = []
        task.finished.connect(finished.append)

        def record_clear() -> None:
            cleared.append(True)

        def reject_submit(*_args: object, **_kwargs: object) -> bool:
            submitted.append(True)
            return False

        monkeypatch.setattr(task, "_current_session", lambda: -1)
        monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
        monkeypatch.setattr(unit, "submit", reject_submit)
        monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
        monkeypatch.setattr(task, "_preview_params", {"diameter": 2.0})
        task.u_field.setValue(1.0)
        task.reselect()
        task.preview()
        task.commit()
        task.reject()
        monkeypatch.setattr(task, "_current_session", lambda: unit.session_id)
        task.reselect()
        task.preview()
        task.commit()
        task.u_field.setValue(2.0)
        task.accept()
        assert not cleared and not submitted
        assert len(finished) == 1
        assert loaded.document.commands == before
        return
    window.act_save.trigger()
    assert "完成或取消历史修复" in window.status_command.text()
    window.request_undo()
    assert loaded.document.commands == before
    window.workspace_tabs.activate("drawing")
    assert window.active_workspace == "model"
    viewport.set_orientation("top")
    viewport.fit_view()
    position = viewport.project_world_point((20, 0, 3))
    assert position is not None
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.preview_button.isEnabled(), task.status_label.text()
    task.u_field.setValue(500.0)
    task.preview_button.click()
    qtbot.waitUntil(lambda: "预览失败" in task.status_label.text(), timeout=20000)
    assert not task.confirm_button.isEnabled() and task.u_field.value() == 500.0
    assert loaded.document.commands == before
    if completion == "commit":
        task.reselect_button.click()
        qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
        QTest.mouseClick(
            viewport, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
        )
        assert task.preview_button.isEnabled()
    task.u_field.setValue(0.0)
    task.v_field.setValue(0.0)
    if completion == "busy_cancel":
        from threading import Event

        from mycad.app import ReplayCandidatePreview, ReplayCandidateSession

        started, release = Event(), Event()
        original = ReplayCandidateSession.preview

        def delayed_preview(
            candidate: ReplayCandidateSession, *, current_session_identity: int
        ) -> ReplayCandidatePreview:
            started.set()
            assert release.wait(20)
            return original(candidate, current_session_identity=current_session_identity)

        monkeypatch.setattr(ReplayCandidateSession, "preview", delayed_preview)
        try:
            task.preview_button.click()
            qtbot.waitUntil(started.is_set, timeout=10000)
            task.cancel_button.click()
        finally:
            release.set()
        qtbot.waitUntil(lambda: window.history_repair_task is None, timeout=20000)
        assert loaded.document.commands == before
        window.close()
        return
    task.preview_button.click()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    assert loaded.document.commands == before
    if completion == "cancel":
        task.cancel_button.click()
        assert window.history_repair_task is None
        assert loaded.document.commands == before
        assert services.kernel.mass_properties().volume == pytest.approx(2400 + 382 * pi)
        window.close()
        return
    if completion == "stale":
        loaded.bus.execute("feature.box", {"size_x": 12, "size_y": 12, "size_z": 6})
        latest = loaded.document.commands
        task.confirm_button.click()
        qtbot.waitUntil(lambda: "来源已变化" in task.status_label.text(), timeout=20000)
        assert loaded.document.commands == latest
        assert task.u_field.value() == 0.0 and task.v_field.value() == 0.0
        assert not task.confirm_button.isEnabled() and not task.preview_button.isEnabled()
        task.cancel_button.click()
        window.close()
        return
    task.confirm_button.click()
    qtbot.waitUntil(lambda: window.history_repair_task is None and not unit.is_busy, timeout=20000)
    edited, repaired = loaded.document.commands[1:]
    assert edited.params["mode"] == "new"
    target = repaired.params["target_face"]
    assert (
        isinstance(target, dict)
        and cast("Mapping[str, object]", target)["source_instance_id"] == cylinder_id
    )
    assert len(edited.amendments) == 1 and len(repaired.amendments) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(382 * pi)
    archive = tmp_path / "repaired.my3d"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands == loaded.document.commands
    window.close()


def test_history_edit_opens_nonmodal_command_bar_and_keeps_parameter_editor(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None

    button.click()
    task = window.history_edit_task
    assert task is not None and task.isVisible()
    assert task.parameter_button.isVisible()
    assert window.findChild(HistoryEditDialog) is task

    def change_parameters() -> None:
        try:
            task.parameter_form.set_value("radius", 6.0)
        finally:
            task.parameter_dialog.accept()

    QTimer.singleShot(0, change_parameters)
    task.parameter_button.click()
    assert task.parameter_form.normalized_params()["radius"] == 6.0
    window.act_save.trigger()
    assert "完成或取消历史编辑" in window.status_command.text()
    task.cancel_button.click()
    assert window.history_edit_task is None
    assert loaded.document.commands == before
    window.close()


def test_history_command_bar_cancels_after_running_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from mycad.app import ReplayCandidatePreview, ReplayCandidateSession

    services, loaded = _history_with_downstream_commands()
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None
    button.click()
    task = window.history_edit_task
    assert task is not None
    task.parameter_form.set_value("radius", 6.0)
    task.reason_field.setText("调整外径")
    started, release = Event(), Event()
    original = ReplayCandidateSession.preview
    candidates: list[ReplayCandidateSession] = []

    def delayed_preview(
        candidate: ReplayCandidateSession, *, current_session_identity: int
    ) -> ReplayCandidatePreview:
        candidates.append(candidate)
        started.set()
        assert release.wait(20)
        return original(candidate, current_session_identity=current_session_identity)

    monkeypatch.setattr(ReplayCandidateSession, "preview", delayed_preview)
    try:
        task.preview_button.click()
        qtbot.waitUntil(started.is_set, timeout=10000)
        task.cancel_button.click()
        assert task.cancel_requested
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.history_edit_task is None, timeout=20000)
    assert len(candidates) == 1 and candidates[0].state == "cancelled"
    assert loaded.document.commands == before
    window.close()


def test_history_parameter_editor_fits_small_logical_screen(qtbot: QtBot) -> None:
    services, loaded = _history_with_downstream_commands()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(512, 384)
    window.bind_document(loaded)
    window.show()
    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(0)
    button = panel.findChild(QPushButton, "editHistoryFeature")
    assert button is not None
    button.click()
    task = window.history_edit_task
    assert task is not None
    result: list[tuple[int, int]] = []

    def inspect_editor() -> None:
        try:
            result.append((task.parameter_dialog.width(), task.parameter_dialog.height()))
        finally:
            task.parameter_dialog.accept()

    QTimer.singleShot(0, inspect_editor)
    task.parameter_button.click()
    assert result and result[0][0] <= 512 and result[0][1] <= 384
    task.cancel_button.click()
    window.close()
