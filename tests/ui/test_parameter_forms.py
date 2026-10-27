# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Registry-driven parameter form field and validation contracts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QWidget
from pytestqt.qtbot import QtBot

from mycad.app import (
    build_app,
    interactive_selectors,
    new_document,
    open_app_document,
    preview_command,
)
from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.commands.validation import normalize_params, validate_params
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.ui.parameter_forms import ParameterForm, VectorField
from mycad.ui.plan_cards import PlanCards
from mycad.ui.plan_draft import PlanDraftController


def _registry() -> CommandRegistry:
    registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        registry.register(spec)
    return registry


def test_scalar_enum_vector_units_and_normalization_match_command_validation(qtbot: QtBot) -> None:
    registry = _registry()
    spec = registry.get("feature.cylinder")
    form = ParameterForm(
        spec,
        {"radius": 5, "height": 12, "center": [1, 2, 3], "mode": "new"},
        registry,
    )
    qtbot.addWidget(form)

    assert isinstance(form.field_widget("radius"), QDoubleSpinBox)
    assert isinstance(form.field_widget("mode"), QComboBox)
    assert isinstance(form.field_widget("center"), VectorField)
    assert form.unit_for("radius") == "mm"
    assert form.unit_for("center") == "mm"
    assert form.unit_for("mode") is None

    form.set_value("radius", 7.5)
    actual = form.normalized_params()
    expected = normalize_params(
        validate_params(
            spec,
            {"radius": 7.5, "height": 12, "center": [1, 2, 3], "mode": "new"},
            registry.schema_defs,
        )
    )
    assert actual == expected


def test_nested_face_and_edge_reference_fields_round_trip(qtbot: QtBot) -> None:
    registry = _registry()
    hole = ParameterForm(
        registry.get("feature.hole"),
        {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "through_all"},
        },
        registry,
    )
    qtbot.addWidget(hole)
    hole.set_value("target_face", {"surface": "cylinder"})
    assert hole.normalized_params()["target_face"] == {"surface": "cylinder"}

    fillet = ParameterForm(
        registry.get("modify.fillet"),
        {"edges": [], "radius": 1},
        registry,
    )
    qtbot.addWidget(fillet)
    fillet.set_value(
        "edges",
        [
            {
                "parent_faces": [{"surface": "plane", "axis": "+Z"}],
                "curve": "circle",
            }
        ],
    )
    assert fillet.normalized_params()["edges"] == [
        {"parent_faces": [{"surface": "plane", "axis": "+Z"}], "curve": "circle"}
    ]


def test_switching_one_of_branch_drops_values_from_old_branch(qtbot: QtBot) -> None:
    registry = _registry()
    form = ParameterForm(
        registry.get("feature.hole"),
        {
            "target_face": {"surface": "plane", "axis": "+Z"},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "blind", "value": 12},
        },
        registry,
    )
    qtbot.addWidget(form)

    depth_editor = form.field_widget("depth")
    assert depth_editor is not None
    branch_picker = depth_editor.findChild(QComboBox)
    assert branch_picker is not None
    branch_picker.setCurrentIndex(branch_picker.findData(0))

    assert form.normalized_params()["depth"] == {"kind": "through_all"}
    assert form.field_widget("depth.value") is None
    with pytest.raises(KeyError):
        form.set_value("depth.value", 5)


def test_invalid_value_keeps_validator_path_and_selector_fill_seam(qtbot: QtBot) -> None:
    registry = _registry()
    form = ParameterForm(registry.get("feature.cylinder"), {}, registry)
    qtbot.addWidget(form)

    form.set_value("radius", 0)
    with pytest.raises(ValidationError):
        form.normalized_params()

    assert "radius" in form.errors
    hole = ParameterForm(
        registry.get("feature.hole"),
        {"position": {"kind": "center"}, "diameter": 4, "depth": {"kind": "through_all"}},
        registry,
    )
    qtbot.addWidget(hole)
    hole.set_selector("target_face", {"surface": "plane", "axis": "+Z"})
    assert hole.normalized_params()["target_face"] == {"surface": "plane", "axis": "+Z"}


def test_unselected_root_one_of_reports_validation_error(qtbot: QtBot) -> None:
    registry = _registry()
    form = ParameterForm(registry.get("feature.hole"), {}, registry)
    qtbot.addWidget(form)

    with pytest.raises(ValidationError, match="parameters"):
        form.normalized_params()


def test_root_one_of_labels_hole_workflows(qtbot: QtBot) -> None:
    registry = _registry()
    form = ParameterForm(registry.get("feature.hole"), {}, registry)
    qtbot.addWidget(form)
    branch_picker = form.findChild(QComboBox)

    assert branch_picker is not None
    assert [branch_picker.itemText(index) for index in range(branch_picker.count())] == [
        "请选择…",
        "面孔",
        "草图孔",
    ]


def test_hole_form_labels_nested_schema_choices(qtbot: QtBot) -> None:
    registry = _registry()
    form = ParameterForm(registry.get("feature.hole"), {}, registry)
    qtbot.addWidget(form)
    root_picker = form.findChild(QComboBox)

    assert root_picker is not None
    root_picker.setCurrentText("面孔")
    choices = [
        [picker.itemText(index) for index in range(picker.count())]
        for picker in form.findChildren(QComboBox)
    ]

    assert choices == [
        ["请选择…", "面孔", "草图孔"],
        ["请选择…", "几何条件", "视口锚定面"],
        ["请选择…", "面心", "指定点"],
        ["请选择…", "贯穿", "盲孔"],
    ]


def test_plan_edit_dialog_uses_typed_form_and_commits_normalized_values(qtbot: QtBot) -> None:
    registry = _registry()
    controller = PlanDraftController(registry)
    step = controller.new_draft("feature.hole")
    controller.set_params(
        step,
        {
            "target_face": {"surface": "cylinder", "axis": ""},
            "position": {"kind": "center"},
            "diameter": 6,
            "depth": {"kind": "through_all"},
        },
    )
    step = controller.steps()[0]
    cards = PlanCards()
    qtbot.addWidget(cards)
    cards.bind_draft(controller)
    dialog = cards.open_parameter_editor(step)

    assert isinstance(dialog.parameter_form, ParameterForm)
    dialog.parameter_form.set_value("diameter", 8)
    dialog.accept()

    assert controller.steps()[0].params["target_face"] == {"surface": "cylinder"}
    assert controller.steps()[0].params["diameter"] == 8


def test_picked_flange_edges_round_trip_through_form_preview_and_apply(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 40, "height": 8})
    hole = {
        "target_face": {"surface": "plane", "axis": "+Z"},
        "position": {"kind": "center"},
        "diameter": 20,
        "depth": {"kind": "through_all"},
    }
    loaded.bus.execute("feature.hole", hole)
    loaded.bus.execute(
        "feature.hole_pattern",
        {
            "base_hole": {**hole, "diameter": 6},
            "pattern": {"kind": "polar", "radius": 25, "count": 4, "start_angle_deg": 0},
        },
    )
    archive = tmp_path / "flange.mc.json"
    save_document(loaded.document, archive)
    loaded = open_app_document(services, archive)
    original_mesh = services.kernel.viewport_data()[-1]
    original_volume = services.kernel.mass_properties().volume
    selectors = interactive_selectors(
        services, "edge", [edge.topology_id for edge in original_mesh.boundary_edges]
    )
    outer_edges = [selector for selector in selectors if selector.get("radius_mm") == 40]
    assert len(outer_edges) == 2
    controller = PlanDraftController(services.registry)
    step = controller.new_draft("modify.fillet")
    cards = PlanCards()
    qtbot.addWidget(cards)
    cards.bind_draft(controller)
    dialog = cards.open_parameter_editor(step, initial_params={"edges": [], "radius": 0.5})
    form = dialog.parameter_form
    assert form is not None

    for selector in outer_edges:
        dialog.fill_selector("edges", [selector], "已选择 1 条边")
        params = form.normalized_params()
        assert params["edges"] == [selector]
        preview = preview_command(services, loaded.document.commands, "modify.fillet", params)
        assert preview.mesh != original_mesh.mesh
        assert len(loaded.document.commands) == 3
        assert services.kernel.mass_properties().volume == original_volume

    dialog.accept()
    loaded.bus.execute("modify.fillet", controller.steps()[0].params, confirmed_by="gui")
    assert len(loaded.document.commands) == 4
    assert services.kernel.mass_properties().volume < original_volume


def test_context_panel_keeps_radius_readable_when_status_wraps(qtbot: QtBot) -> None:
    registry = _registry()
    controller = PlanDraftController(registry)
    host = QWidget()
    host.resize(480, 564)
    qtbot.addWidget(host)
    host.show()
    cards = PlanCards()
    qtbot.addWidget(cards)
    cards.bind_draft(controller)
    dialog = cards.open_parameter_editor(
        controller.new_draft("modify.fillet"),
        overlay_host=host,
        wait_for_selection=True,
        initial_params={"edges": [], "radius": 1},
    )
    dialog.set_parameter_form_visible(False)
    dialog.show_near(host.mapToGlobal(QPoint(200, 350)))
    dialog.fill_selector(
        "edges",
        [{"parent_faces": [{"surface": "plane", "axis": "+Z"}], "curve": "circle"}],
        "已选择 1 条边；设置圆角半径后点击预览。",
    )
    dialog.show_near(host.mapToGlobal(QPoint(200, 350)))
    assert dialog.parameter_form is not None
    radius = cast("QDoubleSpinBox", dialog.parameter_form.field_widget("radius"))
    for message in (
        "参数非法：edges.0: oneOf matched no branch (expected exactly 1); "
        "branch errors: [0] edges.0: expected object, got object; [1]",
        "预览已更新。",
    ):
        dialog.set_preview_status(message, error=True)
        qtbot.waitUntil(lambda: radius.height() >= radius.sizeHint().height())
        assert host.rect().contains(dialog.geometry())
        assert all(
            not label.isVisible()
            for label in dialog.parameter_form.findChildren(QLabel)
            if label.text() == "目标边"
        )
