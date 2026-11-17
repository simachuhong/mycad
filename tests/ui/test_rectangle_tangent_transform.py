# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Window interaction for transformed cross-sketch rectangle tangencies."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    validate_tangency_component,
)
from mycad.core.sketch import CircleEntity, PolylineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize(
    ("mode", "local_dimension"),
    [("rotate90", False), ("rotate45", False), ("rotate45", True), ("mirror", False)],
)
def test_linked_rectangle_transform_from_window(
    qtbot: QtBot, mode: str, local_dimension: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    constraints = (
        (
            SketchConstraint(
                uuid4().hex,
                "length",
                (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
                10,
                "mm",
            ),
        )
        if local_dimension
        else ()
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), constraints)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1200, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id}
    before = len(loaded.document.commands)
    if mode == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if mode == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == before + 1, editor.status_label.text()
    assert loaded.document.commands[-1].version == 29
    solved = services.kernel.sketches
    if mode == "rotate45":
        assert isinstance(solved[0].entities[0], PolylineEntity)
    if local_dimension:
        assert solved[0].constraints == constraints
    relations = services.kernel.cross_sketch_tangencies
    validate_tangency_component(solved, relations, first.sketch_id)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    assert services.kernel.sketches == original
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert services.kernel.sketches == solved
    assert services.kernel.cross_sketch_tangencies == relations


def test_square_rotation_rebinds_dimension_to_transformed_side(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    square = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(square.entity_id, "segment", 0),), 10, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (square,), (dimension,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, square.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {square.entity_id}
    history = len(loaded.document.commands)
    for value in ("ROTATE", "0,0", "90"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == history + 1, editor.status_label.text()
    changed = services.kernel.sketches
    dimension_after = changed[0].constraints[0]
    assert dimension_after.references[0].index == 3
    assert dimension_after.value == 10
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == history, timeout=10000
    )
    assert services.kernel.sketches == before


@pytest.mark.parametrize("around_fixed", [False, True])
def test_rectangle_rotation_respects_fixed_corner(qtbot: QtBot, around_fixed: bool) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(rectangle.entity_id, "end"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id}
    history = len(loaded.document.commands)
    for value in ("ROTATE", "10,10" if around_fixed else "0,0", "90"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if around_fixed:
        assert len(loaded.document.commands) == history + 1, editor.status_label.text()
        assert services.kernel.sketches[0].constraints[0].references[0].kind == "vertex"
        window.request_undo()
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == history, timeout=10000
        )
    else:
        assert len(loaded.document.commands) == history
    assert services.kernel.sketches == before


@pytest.mark.parametrize("mode", ["rotate90", "rotate45", "mirror"])
def test_mixed_rectangle_rotation_stages_and_replays(qtbot: QtBot, mode: str) -> None:
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (20, 0), (25, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, line.entity_id}
    count = len(loaded.document.commands)
    if mode == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if mode == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert len(editor.canvas.mixed_move.step_rectangle_transforms) == 1
    assert services.kernel.sketches == before and len(loaded.document.commands) == count
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.mixed_move is None
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.mixed_move is not None
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    staged_relation = dialog.relations_by_id[relation.relation_id]
    validate_tangency_component(
        editor.canvas.mixed_move.current_saved, (staged_relation,), first.sketch_id
    )
    dialog.reject()
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, line.entity_id}
    for value in ("MOVE", "0,0", "1,2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(editor.canvas.mixed_move_timeline_with_transforms()) == 2, editor.status_label.text()
    extra = LineEntity(uuid4().hex, (30, 0), (35, 0))
    assert editor.canvas.replace_draft_entities((*editor.canvas.entities, extra))
    history = editor.canvas.mixed_move_timeline_with_transforms()
    assert len(history) == 3
    assert len(history[0][4]) == 1 and not history[1][4] and not history[2][4]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert len(loaded.document.commands) == count + 4
    assert loaded.document.commands[-3].version == 29
    validate_tangency_component(
        services.kernel.sketches, services.kernel.cross_sketch_tangencies, first.sketch_id
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 3, timeout=10000
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 2, timeout=10000
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert services.kernel.sketches[:2] == before


@pytest.mark.parametrize("operation", ["rotate45", "rotate90", "mirror"])
def test_mixed_rotation_preserves_two_pending_tangencies_to_same_circle(
    qtbot: QtBot, operation: str
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, -20))
    circle = CircleEntity(uuid4().hex, (5, -5), 5)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1200, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.replace_draft_entities((circle,))
    target = SketchGeometryReference(circle.entity_id, "geometry")
    pairs = tuple(
        (SketchGeometryReference(rectangle.entity_id, "segment", index), target) for index in (0, 3)
    )
    editor.canvas.pending_cross_tangencies = list(pairs)
    original_draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (circle,))
    original = app.draft_cross_relations(services.kernel.sketches, original_draft, pairs)
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, circle.entity_id}
    if operation == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if operation == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert len(editor.canvas.pending_cross_tangencies) == 2
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, circle.entity_id}
    for value in ("MOVE", "0,0", "1,2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(editor.canvas.mixed_move_timeline()) == 2, editor.status_label.text()
    assert len(editor.canvas.pending_cross_tangencies) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert {item.relation_id for item in relations} == {item.relation_id for item in original}
    validate_tangency_component(services.kernel.sketches, relations, saved.sketch_id)


@pytest.mark.parametrize("operation", ["rotate45", "rotate90", "mirror"])
@pytest.mark.parametrize("constrained", [False, True])
def test_multiple_tangent_components_transform_atomically(
    qtbot: QtBot, tmp_path: object, operation: str, constrained: bool
) -> None:
    from dataclasses import replace
    from pathlib import Path

    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangles = (
        RectangleEntity(uuid4().hex, (0, 0), (10, -10)),
        RectangleEntity(uuid4().hex, (30, 0), (40, -10)),
    )
    circles = (CircleEntity(uuid4().hex, (5, 2), 2), CircleEntity(uuid4().hex, (35, 2), 2))
    owners = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (*rectangles, *circles)
    )
    if constrained:
        fixed = SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(rectangles[1].entity_id, "end"),)
        )
        owners = (owners[0], replace(owners[1], constraints=(fixed,)), *owners[2:])
    line = LineEntity(uuid4().hex, (50, 5), (55, 5))
    independent = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (*owners, independent):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for rectangle, circle, owner, partner in zip(
        rectangles, circles, owners[:2], owners[2:], strict=True
    ):
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(owner.sketch_id, rectangle.entity_id, 0),
            CrossSketchRef(partner.sketch_id, circle.entity_id),
            "line_left",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {
        rectangles[0].entity_id,
        rectangles[1].entity_id,
        line.entity_id,
    }
    history = len(loaded.document.commands)
    if operation == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if operation == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if constrained:
        assert len(loaded.document.commands) == history
        assert services.kernel.sketches == original
        assert "失败" in editor.status_label.text()
        return
    assert len(loaded.document.commands) == history + 1, editor.status_label.text()
    assert loaded.document.commands[-1].version == 29
    result = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    for owner in owners[:2]:
        validate_tangency_component(result, relations, owner.sketch_id)
    assert result[-1] != independent
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == history, timeout=10000
    )
    assert services.kernel.sketches == original
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == history + 1, timeout=10000
    )
    assert services.kernel.sketches == result
    assert isinstance(tmp_path, Path)
    path = tmp_path / "multiple-components.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == relations
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == original
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result


@pytest.mark.parametrize("operation", ["rotate45", "rotate90", "mirror"])
def test_two_rectangles_in_same_tangent_component_transform_together(
    qtbot: QtBot, tmp_path: object, operation: str
) -> None:
    from pathlib import Path

    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lower = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    upper = RectangleEntity(uuid4().hex, (-10, 10), (10, 20))
    circle = CircleEntity(uuid4().hex, (0, 5), 5)
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lower,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (upper,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for source, owner in ((lower, sketches[0]), (upper, sketches[1])):
        app.commit_cross_sketch_tangency(
            services,
            loaded,
            CrossSketchTangency(
                uuid4().hex,
                CrossSketchRef(owner.sketch_id, source.entity_id, 0),
                CrossSketchRef(sketches[2].sketch_id, circle.entity_id),
                "line_left" if source == lower else "line_right",
            ),
            session_identity=0,
        )
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None and editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {lower.entity_id, upper.entity_id}
    history = len(loaded.document.commands)
    if operation == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if operation == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == history + 1, editor.status_label.text()
    result = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 2
    validate_tangency_component(result, relations, sketches[0].sketch_id)
    assert isinstance(tmp_path, Path)
    path = tmp_path / "connected-rectangle-transform.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == before
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize("opposite_normal", [False, True])
@pytest.mark.parametrize("layer_state", ["normal", "locked", "hidden"])
def test_visible_rectangle_moves_linked_circle_in_rotated_frame(
    qtbot: QtBot, tmp_path: object, opposite_normal: bool, layer_state: str
) -> None:
    from dataclasses import replace
    from pathlib import Path

    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    layers = services.kernel.drawing_layers.add(SketchLayer("linked"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}
    )
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    frame = (
        WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite_normal
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    circle = CircleEntity(uuid4().hex, frame.world_to_local((0, 2, 0)), 2, layer_name="linked")
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, frame, (circle,), layers=layers)
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    if layer_state != "normal":
        layer = replace(
            layers.get("linked"), locked=layer_state == "locked", visible=layer_state != "hidden"
        )
        layers = layers.replace(layer)
        loaded.bus.execute(
            "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}
        )
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None and editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id}
    history = len(loaded.document.commands)
    for value in ("ROTATE", "0,0", "90"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if layer_state != "normal":
        assert len(loaded.document.commands) == history
        assert services.kernel.sketches == before
        assert "锁定或隐藏" in editor.status_label.text()
        return
    assert len(loaded.document.commands) == history + 1, editor.status_label.text()
    result, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    validate_tangency_component(result, relations, first.sketch_id)
    assert result[1] != before[1]
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == history, timeout=10000
    )
    assert services.kernel.sketches == before
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == history + 1, timeout=10000
    )
    assert services.kernel.sketches == result
    assert isinstance(tmp_path, Path)
    path = tmp_path / "rotated-frame-linked-circle.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == before
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result


@pytest.mark.parametrize("opposite_normal", [False, True])
def test_select_rotated_circle_moves_linked_rectangle(qtbot: QtBot, opposite_normal: bool) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    frame = (
        WorkPlaneFrame((5, 7, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite_normal
        else WorkPlaneFrame((5, 7, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, frame.world_to_local((0, 2, 0)), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, frame, (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 4))
    )
    assert editor.canvas.selected_entity_ids == {circle.entity_id}
    count = len(loaded.document.commands)
    for value in ("MOVE", "0,0", "0,3"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, editor.status_label.text()
    after = services.kernel.sketches
    changed = after[1].entities[0]
    assert isinstance(changed, CircleEntity)
    assert frame.local_to_world(changed.center_mm) == pytest.approx((0, 5, 0))
    assert after[0] != before[0]
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
