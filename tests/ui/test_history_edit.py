# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bus-backed history edit confirmation and impact preview."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QTimer
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


def _history_with_downstream_commands() -> tuple[AppServices, LoadedDocument]:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    loaded.bus.execute("feature.cylinder", {"radius": 1.0, "height": 20.0, "mode": "cut"}, "test")
    loaded.bus.execute("feature.cylinder", {"radius": 0.5, "height": 20.0, "mode": "cut"}, "test")
    return services, loaded


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


def test_editing_sketch_history_rebuilds_downstream_extrusion(qtbot: QtBot) -> None:
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
        params = loaded.document.commands[0].params
        entities = _sketch_entities(params)
        entities[0]["radius_mm"] = 6.0
        dialog.parameter_form.set_value("entities", entities)
        dialog.reason_field.setText("调整草图直径")
        dialog.preview_changes()
        assert "1 条下游命令" in dialog.impact_label.text()
        dialog.confirm_changes()

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
