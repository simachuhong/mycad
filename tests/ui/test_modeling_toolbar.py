# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Checks for the compact, schema-shaped modeling command bar."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QMainWindow, QPushButton
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.modeling_toolbar import ModelingCommandBar


def test_source_selection_cannot_interrupt_running_model_write(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    bar.configure("feature.hole")
    button = bar.findChild(QPushButton, "modelingSelectSource")
    assert button is not None
    bar.set_busy(True)
    assert not button.isEnabled()
    bar.set_busy(False)
    assert button.isEnabled()


def test_chamfer_command_bar_exposes_positive_setback_distance(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    bar.configure("modify.chamfer")

    distance = bar.findChild(QDoubleSpinBox, "distance")
    assert distance is not None
    assert distance.value() == pytest.approx(1.0)
    assert distance.minimum() > 0.0
    assert bar.values() == {"distance": 1.0}


def test_narrow_command_bar_keeps_confirmation_visible(qtbot: QtBot) -> None:
    window = QMainWindow()
    qtbot.addWidget(window)
    bar = ModelingCommandBar(window)
    window.addToolBar(bar)
    bar.configure("feature.hole_pattern")
    window.resize(683, 384)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.wait(50)
    assert window.width() <= 683
    for name in ("modelingCommitButton", "modelingCancelButton"):
        button = bar.findChild(QPushButton, name)
        assert button is not None and button.isVisible()
        assert window.rect().contains(button.mapTo(window, QPoint(0, 0)))
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
    field = bar.findChild(QDoubleSpinBox, "start_angle_deg")
    assert field is not None
    field.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.wait(30)
    assert field.hasFocus()
    assert field.visibleRegion().boundingRect().width() >= field.width() - 2


@pytest.mark.parametrize(
    ("command_id", "expected"),
    [
        (
            "feature.box",
            {
                "size_x": 20.0,
                "size_y": 20.0,
                "size_z": 10.0,
                "center": [0.0, 0.0, 0.0],
                "mode": "new",
            },
        ),
        (
            "feature.cylinder",
            {
                "radius": 5.0,
                "height": 10.0,
                "center": [0.0, 0.0, 0.0],
                "mode": "new",
            },
        ),
        (
            "feature.extrude",
            {
                "profile": {"type": "face"},
                "distance": 10.0,
                "mode": "add",
            },
        ),
        (
            "feature.revolve",
            {
                "profile": {"type": "circle", "radius": 5.0, "center": [0.0, 0.0]},
                "axis": "X",
                "angle_deg": 360.0,
                "mode": "new",
            },
        ),
        (
            "feature.hole",
            {
                "position": {"kind": "center"},
                "diameter": 5.0,
                "depth": {"kind": "blind", "value": 10.0},
            },
        ),
        (
            "feature.hole_pattern",
            {
                "base_hole": {
                    "position": {"kind": "center"},
                    "diameter": 5.0,
                    "depth": {"kind": "blind", "value": 10.0},
                },
                "pattern": {
                    "kind": "polar",
                    "radius": 20.0,
                    "count": 4,
                    "start_angle_deg": 0.0,
                },
            },
        ),
        (
            "modify.boolean_cut",
            {
                "tool": {
                    "type": "box",
                    "size_x": 10.0,
                    "size_y": 10.0,
                    "size_z": 10.0,
                    "center": [0.0, 0.0, 0.0],
                }
            },
        ),
        (
            "modify.boolean_intersect",
            {
                "tool": {
                    "type": "box",
                    "size_x": 10.0,
                    "size_y": 10.0,
                    "size_z": 10.0,
                    "center": [0.0, 0.0, 0.0],
                }
            },
        ),
        (
            "modify.boolean_bodies",
            {"operation": "union", "keep_tool": False},
        ),
        (
            "modify.body_transform",
            {
                "transform": {
                    "operation": "move",
                    "translation_mm": [10.0, 0.0, 0.0],
                }
            },
        ),
        (
            "modify.body_pattern",
            {
                "pattern": {
                    "kind": "linear",
                    "count": 2,
                    "spacing_mm": [10.0, 0.0, 0.0],
                }
            },
        ),
    ],
)
def test_modeling_command_bar_serializes_builtin_parameters(
    qtbot: QtBot,
    command_id: str,
    expected: dict[str, object],
) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)

    bar.configure(command_id)

    assert bar.values() == expected
    assert bar.height() <= 62


def test_profile_and_tool_switches_serialize_only_active_schema_branch(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)

    bar.configure("feature.extrude")
    source = bar.findChild(QComboBox, "extrudeSource")
    assert source is not None
    source.setCurrentIndex(source.findData("profile"))
    profile_type = bar.findChild(QComboBox, "profileType")
    assert profile_type is not None
    profile_type.setCurrentIndex(profile_type.findData("rect"))
    assert bar.values()["profile"] == {
        "type": "rect",
        "width": 10.0,
        "height": 10.0,
        "center": [0.0, 0.0],
    }
    extent = bar.findChild(QComboBox, "extentMode")
    assert extent is not None
    assert bar.values()["extent_mode"] == "one_sided"
    extent.setCurrentIndex(extent.findData("symmetric"))
    assert bar.values()["extent_mode"] == "symmetric"


def test_sketch_extrude_source_requires_and_serializes_a_selected_sketch(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    bar.configure("feature.extrude", sketch_ids=(sketch_id,))
    source = bar.findChild(QComboBox, "extrudeSource")
    sketch = bar.findChild(QComboBox, "sketchProfile")
    assert source is not None and sketch is not None
    source.setCurrentIndex(source.findData("sketch"))

    assert not bar.input_valid()
    sketch.setCurrentIndex(sketch.findData(sketch_id))

    assert bar.input_valid()
    assert bar.values() == {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "distance": 10.0,
        "mode": "new",
        "extent_mode": "one_sided",
    }


def test_sketch_extrude_exposes_symmetric_total_depth(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    bar.configure("feature.extrude", sketch_ids=(sketch_id,))
    source = bar.findChild(QComboBox, "extrudeSource")
    sketch = bar.findChild(QComboBox, "sketchProfile")
    extent = bar.findChild(QComboBox, "extentMode")
    assert source is not None and sketch is not None and extent is not None
    extent_container = extent.parentWidget()
    assert extent_container is not None and extent_container.isHidden()
    source.setCurrentIndex(source.findData("sketch"))
    assert not extent_container.isHidden()
    sketch.setCurrentIndex(sketch.findData(sketch_id))
    extent.setCurrentIndex(extent.findData("symmetric"))

    assert bar.values()["extent_mode"] == "symmetric"


def test_sketch_extrude_to_face_selects_target_without_a_distance_value(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    bar.configure("feature.extrude", sketch_ids=(sketch_id,))
    source = bar.findChild(QComboBox, "extrudeSource")
    sketch = bar.findChild(QComboBox, "sketchProfile")
    extent = bar.findChild(QComboBox, "extentMode")
    distance = bar.findChild(QDoubleSpinBox, "distance")
    assert source is not None and sketch is not None and extent is not None and distance is not None
    source.setCurrentIndex(source.findData("sketch"))
    sketch.setCurrentIndex(sketch.findData(sketch_id))
    extent.setCurrentIndex(extent.findData("to_face"))

    assert bar.values() == {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "mode": "new",
        "extent_mode": "to_face",
    }
    distance_parent = distance.parentWidget()
    assert distance_parent is not None and distance_parent.isHidden()


def test_sketch_revolve_source_requires_a_sketch_and_exposes_axis(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    bar.configure("feature.revolve", sketch_ids=(sketch_id,))
    source = bar.findChild(QComboBox, "revolveSource")
    sketch = bar.findChild(QComboBox, "sketchProfile")
    axis = bar.findChild(QComboBox, "axis")
    assert source is not None and sketch is not None and axis is not None
    source.setCurrentIndex(source.findData("sketch"))
    assert not bar.input_valid()
    sketch.setCurrentIndex(sketch.findData(sketch_id))
    axis.setCurrentIndex(axis.findData("Z"))

    assert bar.values() == {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "axis": "Z",
        "angle_deg": 360.0,
        "mode": "new",
    }


def test_sketch_revolve_can_reference_a_construction_line_axis(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    axis_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    sketch = Sketch(
        sketch_id,
        WorkPlaneFrame.xz(),
        (LineEntity(axis_id, (2.0, -10.0), (2.0, 0.0), construction=True),),
    )
    bar.configure("feature.revolve", sketch_ids=(sketch_id,), sketches=(sketch,))
    source = bar.findChild(QComboBox, "revolveSource")
    sketch_picker = bar.findChild(QComboBox, "sketchProfile")
    axis_source = bar.findChild(QComboBox, "axisSource")
    axis_line = bar.findChild(QComboBox, "axisLine")
    assert source is not None and sketch_picker is not None
    assert axis_source is not None and axis_line is not None
    source.setCurrentIndex(source.findData("sketch"))
    sketch_picker.setCurrentIndex(sketch_picker.findData(sketch_id))
    axis_source.setCurrentIndex(axis_source.findData("sketch_line"))

    assert not bar.input_valid()
    axis_line.setCurrentIndex(axis_line.findData(axis_id))

    assert bar.input_valid()
    assert bar.values() == {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "axis_reference": {
            "type": "sketch_line",
            "sketch_id": sketch_id,
            "entity_id": axis_id,
        },
        "angle_deg": 360.0,
        "mode": "new",
    }


def test_sketch_hole_source_requires_and_serializes_a_selected_sketch(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    bar.configure("feature.hole", sketch_ids=(sketch_id,))
    source = bar.findChild(QComboBox, "holeSource")
    sketch = bar.findChild(QComboBox, "sketchProfile")
    assert source is not None and sketch is not None
    source.setCurrentIndex(source.findData("sketch"))
    assert not bar.input_valid()
    sketch.setCurrentIndex(sketch.findData(sketch_id))

    assert bar.input_valid()
    assert bar.values() == {
        "profile": {"type": "sketch", "sketch_id": sketch_id},
        "depth": {"kind": "blind", "value": 10.0},
    }

    bar.configure("modify.boolean_cut")
    tool_type = bar.findChild(QComboBox, "toolType")
    assert tool_type is not None
    tool_type.setCurrentIndex(tool_type.findData("cylinder"))
    assert bar.values()["tool"] == {
        "type": "cylinder",
        "radius": 5.0,
        "height": 10.0,
        "center": [0.0, 0.0, 0.0],
    }


def test_through_hole_drops_the_blind_depth_value(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    bar.configure("feature.hole")

    depth_kind = bar.findChild(QComboBox, "depthKind")
    assert depth_kind is not None
    depth_kind.setCurrentIndex(depth_kind.findData("through_all"))

    assert bar.values()["depth"] == {"kind": "through_all"}


def test_sphere_command_bar_supports_world_center_and_radius(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    bar.configure("feature.sphere")
    for name, value in (("center_x", 3.0), ("center_y", -4.0), ("center_z", 5.0)):
        field = bar.findChild(QDoubleSpinBox, name)
        assert field is not None
        field.setValue(value)
    assert bar.values() == {"radius": 10.0, "center": [3.0, -4.0, 5.0], "mode": "new"}


def test_sphere_adopted_position_keeps_six_decimal_places(qtbot: QtBot) -> None:
    bar = ModelingCommandBar()
    qtbot.addWidget(bar)
    bar.configure("feature.sphere")
    bar.set_placement_point((1.234567, -2.345678, 3.456789))
    assert bar.values()["center"] == pytest.approx([1.234567, -2.345678, 3.456789], abs=1e-9)
