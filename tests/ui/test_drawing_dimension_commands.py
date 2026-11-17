# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""2D command line and dimension tools share one interactive workflow."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def submit(editor: SketchEditorDialog, text: str) -> None:
    editor.drawing_command_bar.input.setText(text)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)


@pytest.mark.parametrize(
    ("alias", "mode"),
    [
        ("DLI", "linear"),
        ("DAL", "aligned"),
        ("DAN", "angle"),
        ("DRA", "radius"),
        ("DDI", "diameter"),
        ("DAR", "arc_length"),
        ("DCO", "continue"),
        ("DBA", "baseline"),
        ("DOR", "ordinate"),
    ],
)
def test_dimension_alias_starts_and_repeats(qtbot: QtBot, alias: str, mode: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    submit(editor, alias)
    assert editor.dimensions.mode == mode
    submit(editor, "")
    submit(editor, "")
    assert editor.dimensions.mode == mode


@pytest.mark.parametrize(
    ("command", "mode"),
    [
        ("DIM", "smart"),
        ("DIMLINEAR", "linear"),
        ("DIMALIGNED", "aligned"),
        ("DIMANGULAR", "angle"),
        ("DIMRADIUS", "radius"),
        ("DIMDIAMETER", "diameter"),
        ("DIMARC", "arc_length"),
        ("DIMCONTINUE", "continue"),
        ("DIMBASELINE", "baseline"),
        ("DIMORDINATE", "ordinate"),
    ],
)
def test_dimension_commands_start_same_tools(qtbot: QtBot, command: str, mode: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    submit(editor, command)
    assert editor.dimensions.mode == mode, editor.drawing_command_bar.status.text()
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    assert editor.dimensions.mode is None


def test_radius_command_coordinates_place_reference_dimension(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    editor.canvas.entities = [circle]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    submit(editor, "DIMRADIUS")
    submit(editor, "5,0")
    submit(editor, "10,10")
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].kind == "radius"
    assert editor.canvas.constraints[0].value == pytest.approx(5)
    assert not editor.canvas.constraints[0].driving
    submit(editor, "")
    assert editor.dimensions.mode is None
    submit(editor, "")
    assert editor.dimensions.mode == "radius"
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert not editor.canvas.constraints


def test_smart_dimension_command_places_circle_diameter(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 5)]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIM", "5,0", "10,10"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].kind == "diameter"
    assert editor.canvas.constraints[0].value == pytest.approx(10)


def test_linear_command_accepts_two_points_and_dimension_location(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMLINEAR", "0,0", "20,10", "10,20"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    dimension = editor.canvas.constraints[0]
    assert dimension.axis == "horizontal"
    assert dimension.value == pytest.approx(20)
    assert not dimension.driving


def test_chain_and_ordinate_commands_place_dimensions(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (20, 0), (40, 20)),
    ]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMLINEAR", "0,0", "20,0", "10,-10", ""):
        submit(editor, text)
    first = editor.canvas.constraints[-1]
    for text in ("DIMCONTINUE", "40,20", "30,-10", ""):
        submit(editor, text)
    second = editor.canvas.constraints[-1]
    assert second.references[0] == first.references[-1]
    assert second.value == pytest.approx(20)
    for text in ("DIMBASELINE", "40,20", "30,-20", ""):
        submit(editor, text)
    assert editor.canvas.constraints[-1].references[0] == first.references[0]
    for text in ("DIMORDINATE", "0,0", "40,20", "40,-20"):
        submit(editor, text)
    assert editor.canvas.constraints[-1].axis == "ordinate_x"
    assert len(editor.canvas.constraints) == 4


def test_radius_command_accepts_driving_value(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 5)]
    editor.canvas.changed.emit()
    for text in ("DIMRADIUS", "5,0", "10,10", "7"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].driving
    circle = editor.canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(7)


def test_radius_command_accepts_current_driving_value_on_enter(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 5)]
    editor.canvas.changed.emit()
    for text in ("DIMRADIUS", "5,0", "10,10", ""):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].driving
    assert editor.canvas.constraints[0].value == pytest.approx(5)


def test_linear_command_vertical_option_overrides_automatic_direction(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMLINEAR", "0,0", "20,10", "V", "10,20"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].axis == "vertical"
    assert editor.canvas.constraints[0].value == pytest.approx(10)


def test_radius_command_commits_and_undoes_on_saved_geometry(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not editor
            and not unit.is_busy
        ),
        timeout=20000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMRADIUS", "5,0", "10,10"):
        submit(editor, text)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert len(entry.services.kernel.sketches[0].constraints) == 1
    assert entry.services.kernel.sketches[0].constraints[0].kind == "radius"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not entry.services.kernel.sketches[0].constraints


@pytest.mark.parametrize(
    ("command", "kind", "value"),
    [("DIMDIAMETER", "diameter", 10), ("DIMARC", "arc_length", 5 * 3.141592653589793 / 2)],
)
def test_curved_dimension_commands_place_reference(
    qtbot: QtBot, command: str, kind: str, value: float
) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    entity = (
        CircleEntity(uuid4().hex, (0, 0), 5)
        if kind == "diameter"
        else ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    )
    editor.canvas.entities = [entity]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in (command, "5,0", "10,10"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].kind == kind
    assert editor.canvas.constraints[0].value == pytest.approx(value)


def test_aligned_command_places_reference_dimension(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMALIGNED", "0,0", "20,10", "10,20"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].axis == "aligned"
    assert editor.canvas.constraints[0].value == pytest.approx(500**0.5)


def test_angular_command_places_reference_dimension(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 10)),
    ]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMANGULAR", "5,0", "0,5", "5,5"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    assert editor.canvas.constraints[0].kind == "angle"
    assert editor.canvas.constraints[0].value == pytest.approx(90)


def test_linear_command_rotated_option_uses_specified_projection(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    for text in ("DIMLINEAR", "0,0", "20,10", "R", "45", "10,20"):
        submit(editor, text)
    assert len(editor.canvas.constraints) == 1
    dimension = editor.canvas.constraints[0]
    assert dimension.projection_axis == pytest.approx((2**-0.5, 2**-0.5))
    assert dimension.value == pytest.approx(30 / 2**0.5)
    assert not dimension.driving


def test_rotation_angle_retry_and_new_dimension_reset(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    submit(editor, "DIMLINEAR")
    submit(editor, "R")
    submit(editor, "nan")
    assert "角度" in editor.drawing_command_bar.status.text()
    editor.dimensions.buttons["smart"].click()
    submit(editor, "DIMLINEAR")
    submit(editor, "0,0")
    assert "角度" not in editor.drawing_command_bar.status.text()


def test_rotation_option_does_not_consume_driving_value_input(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (20, 10))]
    editor.canvas.changed.emit()
    for text in ("DIMLINEAR", "0,0", "20,10", "10,20"):
        submit(editor, text)
    assert editor.dimensions.command_editing_value
    submit(editor, "R")
    assert editor.dimensions.command_editing_value
    assert "尺寸值" in editor.drawing_command_bar.status.text()
