# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Angular dimensions choose the sector containing their placement point."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.angular_dimension import angular_sector
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


@pytest.mark.parametrize(("sector", "desired"), ((30, 75), (120, 105), (210, 75), (300, 105)))
def test_angular_driving_value_converts_selected_sector(sector: int, desired: int) -> None:
    first = ((0.0, 0.0), (10.0, 0.0))
    second = ((0.0, 0.0), (5.0, 5 * math.sqrt(3)))
    position = (20 * math.cos(math.radians(sector)), 20 * math.sin(math.radians(sector)))
    selected = angular_sector(first, second, position)
    assert selected.solver_degrees(desired) == pytest.approx(75)


@pytest.mark.parametrize("reverse_first", (False, True))
@pytest.mark.parametrize("reverse_second", (False, True))
@pytest.mark.parametrize("sector", (30, 120, 210, 300))
def test_angular_driving_conversion_respects_line_orientation(
    reverse_first: bool, reverse_second: bool, sector: int
) -> None:
    first = ((0.0, 0.0), (10.0, 0.0))
    second = ((0.0, 0.0), (5.0, 5 * math.sqrt(3)))
    if reverse_first:
        first = first[::-1]
    if reverse_second:
        second = second[::-1]
    u = (first[1][0] - first[0][0], first[1][1] - first[0][1])
    v = (second[1][0] - second[0][0], second[1][1] - second[0][1])
    measured = math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1]))
    position = (20 * math.cos(math.radians(sector)), 20 * math.sin(math.radians(sector)))
    selected = angular_sector(first, second, position)
    assert selected.solver_degrees(math.degrees(selected.sweep)) == pytest.approx(measured)


@pytest.mark.parametrize(("sector", "expected"), ((30, 60), (120, 120), (210, 60), (300, 120)))
def test_angular_dimension_placement_selects_quadrant(
    qtbot: QtBot, sector: int, expected: int
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (5, 5 * math.sqrt(3)))
    canvas.entities = [first, second]
    point = (20 * math.cos(math.radians(sector)), 20 * math.sin(math.radians(sector)))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        60,
        "deg",
        driving=False,
        position_mm=point,
    )
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    center = canvas.local_to_screen((0, 0))
    middle = layout.lines[15][1]
    angle = math.degrees(math.atan2(center.y() - middle.y(), middle.x() - center.x())) % 360
    assert angle == pytest.approx(sector)
    assert canvas.dimension_display_text(dimension) == f"{expected:.2f}°"


@pytest.mark.parametrize(("sector", "expected"), ((30, 60), (120, 120), (210, 60), (300, 120)))
def test_angular_command_previews_and_places_chosen_quadrant(
    qtbot: QtBot, sector: int, expected: int
) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (10, 10 * math.sqrt(3)))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["angle"].click()
    for point in ((15, 0), (7.5, 7.5 * math.sqrt(3))):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    point = (25 * math.cos(math.radians(sector)), 25 * math.sin(math.radians(sector)))
    position = editor.canvas.local_to_screen(point)
    QTest.mouseMove(editor.canvas, position)
    assert editor.dimensions.value_editor.value() == pytest.approx(expected, abs=0.15)
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=position)
    assert len(editor.canvas.constraints) == 1, editor.canvas.message
    dimension = editor.canvas.constraints[0]
    assert editor.canvas.dimension_display_text(dimension) == f"{expected:.2f}°"
    assert editor.canvas.undo_last_operation()
    assert not editor.canvas.constraints


def test_angular_quadrant_dxf_roundtrip(tmp_path: Path) -> None:
    import ezdxf

    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (5, 5 * math.sqrt(3)))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        60,
        "deg",
        driving=False,
        position_mm=(-10, 10 * math.sqrt(3)),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    path = tmp_path / "quadrant.dxf"
    report = write_sketch_dxf(sketch, path)
    assert report.complete
    native = next(e for e in ezdxf.readfile(path).modelspace() if e.dxftype() == "DIMENSION")
    assert native.get_measurement() == pytest.approx(120)
    imported = read_sketch_dxf(path).sketch
    assert imported.constraints[0].position_mm == pytest.approx(dimension.position_mm)
    assert imported.constraints[0].value == pytest.approx(60)


def test_driving_angular_dimension_edits_obtuse_sector(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (10, 10 * math.sqrt(3)))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["angle"].click()
    for point in ((15, 0), (7.5, 7.5 * math.sqrt(3)), (-12.5, 12.5 * math.sqrt(3))):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert editor.dimensions.value_editor.value() == pytest.approx(120, abs=0.15)
    editor.dimensions.value_editor.setValue(105)
    editor.dimensions.apply_edit()
    if not editor.canvas.constraints and "再次确认" in editor.dimensions.prompt.text():
        editor.dimensions.apply_edit()
    assert len(editor.canvas.constraints) == 1, editor.dimensions.prompt.text()
    dimension = editor.canvas.constraints[0]
    assert dimension.driving and dimension.value == pytest.approx(75)
    assert editor.canvas.dimension_display_text(dimension) == "105.00°"
    assert editor.canvas.undo_last_operation()
    assert not editor.canvas.constraints


def test_angular_quadrant_survives_save_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (5, 5 * math.sqrt(3)))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        60,
        "deg",
        driving=False,
        position_mm=(-10, 10 * math.sqrt(3)),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    path = tmp_path / "quadrant.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    result = reopened.kernel.sketches[0]
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.entities = list(result.entities)
    assert canvas.dimension_display_text(result.constraints[0]) == "120.00°"
    assert result.constraints[0].position_mm == pytest.approx(dimension.position_mm)


def test_angular_quadrant_value_in_properties_and_quick_select(qtbot: QtBot) -> None:
    from mycad.ui.quick_select import QuickSelectDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (5, 5 * math.sqrt(3)))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        60,
        "deg",
        driving=False,
        position_mm=(-10, 10 * math.sqrt(3)),
    )
    editor.canvas.entities = [first, second]
    editor.canvas.constraints = [dimension]
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    values = {
        editor.properties_table.item(row, 0).text(): editor.properties_table.item(row, 1).text()
        for row in range(editor.properties_table.rowCount())
        if editor.properties_table.item(row, 0) is not None
        and editor.properties_table.item(row, 1) is not None
    }
    assert values["约束值"] == "120 deg"
    recorded: list[tuple[float, str] | None] = []

    def inspect() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        recorded.append(dialog.dimension_values.get(dimension.constraint_id))
        dialog.reject()

    QTimer.singleShot(100, inspect)
    editor.open_quick_select()
    assert recorded == [(pytest.approx(120), "deg")]
