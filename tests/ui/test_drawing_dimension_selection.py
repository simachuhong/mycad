# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved independent-drawing dimensions remain selectable and undoable."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("tool", ["arc_length", "ordinate"])
def test_saved_reference_dimension_right_click_delete_and_reopen(
    qtbot: QtBot, tmp_path: Path, tool: str
) -> None:
    entity = (
        ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)
        if tool == "arc_length"
        else LineEntity(uuid4().hex, (0, 0), (30, 20))
    )
    points = ((0, 10), (20, 20)) if tool == "arc_length" else ((0, 0), (30, 20), (40, -20))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)), session_identity=1
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons[tool].click()
    canvas = editor.canvas
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    dimension = services.kernel.sketches[0].constraints[0]
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen(points[-1]))
    assert editor.dimensions.mode is None
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 3, timeout=10000)
    assert not services.kernel.sketches[0].constraints
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == (dimension,)
    path = tmp_path / f"{tool}.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("engineering", [False, True])
def test_saved_driving_dimension_right_click_then_select_delete_and_replay(
    qtbot: QtBot, tmp_path: Path, engineering: bool
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="drawing" if engineering else "sketch")
    if engineering:
        part_services = app.fork_app_services(services)
        part = app.new_workspace_document(part_services, kind="part")
        part.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
        loaded.bus.execute("reference.attach", app.reference_parameters(part.document), "local")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    canvas = editor.canvas
    for point in ((10, 0), (20, 20)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    editor.dimensions.value_editor.setValue(7)
    original, candidate = editor.dimensions.original, editor.dimensions.candidate
    assert original is not None and candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None,
        timeout=10000,
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", preview.message if preview else ""
    before = len(loaded.document.commands)
    point = canvas.local_to_screen((20, 20))
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
    if preview.branch_changes:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    updated = services.kernel.sketches[0]
    dimension = updated.constraints[0]
    assert dimension.driving and dimension.value == pytest.approx(7)
    assert isinstance(updated.entities[0], CircleEntity)
    assert updated.entities[0].radius_mm == pytest.approx(7)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
    assert editor.dimensions.mode is None
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 2, timeout=10000
    )
    assert not services.kernel.sketches[0].constraints
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == (dimension,)
    path = tmp_path / "right-click-dimension.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (dimension,)


def test_saved_curved_polyline_angle_right_click_delete_and_replay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame

    path = PolylineEntity(uuid4().hex, ((-20, -20), (-20, 0), (20, 0)), bulges=(0.5, 0))
    line = LineEntity(uuid4().hex, (0, 0), (0, 30))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path, line))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["angle"].click()
    for point in ((-10, 0), (0, 15), (10, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert editor.dimensions.value_editor.isVisible()
    editor.dimensions.value_editor.setValue(45)
    original, candidate = editor.dimensions.original, editor.dimensions.candidate
    assert original is not None and candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", preview.message if preview else ""
    pos = canvas.local_to_screen((10, 10))
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=pos)
    if preview.branch_changes:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=pos)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    updated = services.kernel.sketches[0]
    dimension = updated.constraints[0]
    assert dimension.kind == "angle" and dimension.value == pytest.approx(45)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=pos)
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=10000)
    assert not services.kernel.sketches[0].constraints
    loaded.bus.undo()
    assert services.kernel.sketches[0] == updated
    save_path = tmp_path / "curved-line-angle.my2d"
    save_document(loaded.document, save_path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, save_path)
    assert reopened.kernel.sketches[0] == updated


@pytest.mark.parametrize("driving", [False, True])
def test_delete_saved_dimension_replays_and_undoes(
    qtbot: QtBot, tmp_path: Path, driving: bool
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    assert editor.canvas.replace_draft_entities((circle,))
    editor.dimensions.driving_check.setChecked(driving)
    editor.dimensions.buttons["radius"].click()
    for point in ((10, 0), (20, 20)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if driving:
        editor.dimensions.value_editor.setValue(7)
        editor.dimensions.apply_button.click()
    dimension = editor.canvas.constraints[0]
    circle_after = editor.canvas.entities[0]
    assert isinstance(circle_after, CircleEntity)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    editor.tool_combo.setCurrentText("选择元素")
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    before = len(loaded.document.commands)
    if driving:
        editor.drawing_command_bar.input.setText("ERASE")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert not services.kernel.sketches[0].constraints
    assert services.kernel.sketches[0].entities == (circle_after,)
    path = tmp_path / "dimension-delete.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert not reopened_services.kernel.sketches[0].constraints
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].constraints == (dimension,)
    reopened.bus.redo()
    assert not reopened_services.kernel.sketches[0].constraints


def test_delete_saved_and_draft_dimensions_together(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    saved_circle = CircleEntity(uuid4().hex, (0, 0), 10)
    assert editor.canvas.replace_draft_entities((saved_circle,))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["radius"].click()
    for point in ((10, 0), (18, 18)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    saved_dimension = editor.canvas.constraints[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    from mycad.core.sketch import LineEntity

    draft_circle = CircleEntity(uuid4().hex, (40, 0), 6)
    draft_line = LineEntity(uuid4().hex, (65, 0), (85, 0))
    assert canvas.replace_draft_entities((draft_circle, draft_line))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["radius"].click()
    for point in ((46, 0), (50, 18)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    draft_dimension = canvas.constraints[0]
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    entities = canvas.dimension_entities()
    for index, dimension in enumerate((saved_dimension, draft_dimension)):
        layout = canvas.dimension_layout(dimension, entities)
        assert layout is not None
        QTest.mouseClick(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier if index else Qt.KeyboardModifier.NoModifier,
            pos=layout.label.toPoint(),
        )
    assert canvas.selected_constraint_ids == {
        saved_dimension.constraint_id,
        draft_dimension.constraint_id,
    }
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((75, 0)),
    )
    assert canvas.selected_entity_ids == {draft_line.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert not canvas.constraints and draft_line not in canvas.entities
    assert canvas.mixed_move is not None and all(
        not sketch.constraints for sketch in canvas.mixed_move.current_saved
    )
    assert canvas.undo_last_operation()
    assert canvas.constraints == [draft_dimension] and draft_line in canvas.entities
    assert canvas.mixed_move is None
    assert canvas.redo_last_operation()
    assert (
        not canvas.constraints
        and canvas.mixed_move is not None
        and draft_line not in canvas.entities
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    loaded = window.loaded_document()
    assert loaded is not None
    assert all(not sketch.constraints for sketch in services.kernel.sketches)
    path = tmp_path / "mixed-dimension-delete.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert all(not sketch.constraints for sketch in reopened_services.kernel.sketches)
    reopened.bus.undo()
    assert any(
        saved_dimension in sketch.constraints for sketch in reopened_services.kernel.sketches
    )
    reopened.bus.redo()
    assert all(not sketch.constraints for sketch in reopened_services.kernel.sketches)


def test_delete_saved_dimension_and_unrelated_saved_entity_in_one_step(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    line = LineEntity(uuid4().hex, (40, 0), (60, 0))
    assert editor.canvas.replace_draft_entities((circle, line))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["radius"].click()
    for point in ((10, 0), (20, 20)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    editor.tool_combo.setCurrentText("选择元素")
    canvas = editor.canvas
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((50, 0)),
    )
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    assert canvas.selected_entity_ids == {line.entity_id}
    count = len(loaded.document.commands)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert (
        services.kernel.sketches[0].entities == (circle,)
        and not services.kernel.sketches[0].constraints
    )
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (circle, line)
    assert services.kernel.sketches[0].constraints == (dimension,)


def test_delete_dimensions_from_two_saved_sketches_together(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    unit = window.execution_unit
    assert unit is not None
    dimensions: list[SketchConstraint] = []
    for x in (0, 40):
        editor = window.active_sketch_dialog()
        assert editor is not None
        circle = CircleEntity(uuid4().hex, (x, 0), 10)
        assert editor.canvas.replace_draft_entities((circle,))
        editor.dimensions.driving_check.setChecked(False)
        editor.dimensions.buttons["radius"].click()
        for point in ((x + 10, 0), (x + 20, 20)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
        dimensions.append(editor.canvas.constraints[0])
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda previous=editor: (
                window.active_sketch_dialog() is not previous and not unit.is_busy
            ),
            timeout=10000,
        )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    editor.tool_combo.setCurrentText("选择元素")
    for index, dimension in enumerate(dimensions):
        layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
        assert layout is not None
        QTest.mouseClick(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier if index else Qt.KeyboardModifier.NoModifier,
            pos=layout.label.toPoint(),
        )
    assert canvas.selected_constraint_ids == {item.constraint_id for item in dimensions}
    count = len(loaded.document.commands)
    layers = canvas.document_layer_table
    assert layers is not None
    canvas.document_layer_table = layers.replace(replace(layers.get("DIM"), locked=True))
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert len(loaded.document.commands) == count
    assert all(sketch.constraints for sketch in services.kernel.sketches)
    canvas.document_layer_table = layers
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert all(not sketch.constraints for sketch in services.kernel.sketches)
    loaded.bus.undo()
    assert {c.constraint_id for sketch in services.kernel.sketches for c in sketch.constraints} == {
        item.constraint_id for item in dimensions
    }
