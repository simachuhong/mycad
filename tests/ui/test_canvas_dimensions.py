# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mouse acceptance for dimension commands, with no dialog-form input."""

from dataclasses import replace
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def editor(qtbot: QtBot) -> SketchEditorDialog:
    services = build_app(discoverers=())
    result = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(result)
    result.resize(1280, 800)
    result.show()
    # These placement tests exercise explicit reference annotations.
    result.dimensions.driving_check.setChecked(False)
    result.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (30, 20))]
    result.canvas.changed.emit()
    return result


def click(view: SketchEditorDialog, point: Point2D) -> None:
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=view.canvas.local_to_screen(point))


def erase_command(view: SketchEditorDialog) -> None:
    view.drawing_command_bar.input.setText("ERASE")
    QTest.keyClick(view.drawing_command_bar.input, Qt.Key.Key_Return)


def test_tool_inventory_has_real_commands_and_distinct_icons(qtbot: QtBot) -> None:
    view = editor(qtbot)
    expected = {
        "smart",
        "horizontal",
        "vertical",
        "aligned",
        "angle",
        "radius",
        "diameter",
        "continue",
        "baseline",
        "ordinate",
        "arc_length",
    }
    assert expected <= set(view.dimensions.buttons)
    assert all(not button.icon().isNull() for button in view.dimensions.buttons.values())
    assert len({b.icon().cacheKey() for b in view.dimensions.buttons.values()}) == len(expected)


@pytest.mark.parametrize(
    "tool,axis,value",
    [
        ("horizontal", "horizontal", 30),
        ("vertical", "vertical", 20),
        ("aligned", "aligned", 1300**0.5),
    ],
)
def test_pick_preview_place_reference_and_undo(
    qtbot: QtBot, tool: str, axis: str, value: float
) -> None:
    view = editor(qtbot)
    view.dimensions.buttons[tool].click()
    click(view, (15, 10))
    QTest.mouseMove(view.canvas, view.canvas.local_to_screen((20, -15)))
    assert view.canvas.dimension_candidate is not None
    assert view.canvas.constraints == []
    assert QApplication.activeModalWidget() is None
    click(view, (20, -15))
    assert len(view.canvas.constraints) == 1
    dimension = view.canvas.constraints[0]
    assert dimension.axis == axis
    assert dimension.value == pytest.approx(value)
    assert not dimension.driving
    assert dimension.position_mm == pytest.approx((20, -15), abs=0.2)
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    view.canvas.undo_last_operation()
    assert view.canvas.constraints == []
    view.canvas.redo_last_operation()
    assert len(view.canvas.constraints) == 1


def test_cancel_discards_candidate_and_preserves_geometry(qtbot: QtBot) -> None:
    view = editor(qtbot)
    before = tuple(view.canvas.entities)
    view.dimensions.buttons["smart"].click()
    click(view, (15, 10))
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    assert view.canvas.dimension_candidate is None
    assert not view.canvas.constraints
    assert tuple(view.canvas.entities) == before


def test_hover_shows_candidate_without_selecting_or_mutating(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["smart"].click()
    QApplication.processEvents()
    position = view.canvas.local_to_screen((15, 10))
    QApplication.sendEvent(
        view.canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(position),
            QPointF(view.canvas.mapToGlobal(position)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert view.canvas.dimension_candidate is not None
    assert view.dimensions.candidate is None
    assert view.dimensions.references == []
    assert not view.canvas.constraints


def test_baseline_after_new_independent_dimension_uses_new_origin(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 10))
    click(view, (15, -15))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (50, 0), (80, 0)),))
    view.set_context_sketches((other,))
    view.dimensions.buttons["horizontal"].click()
    click(view, (65, 0))
    click(view, (65, -15))
    # Simulate async completion through the same public result boundary.
    original, candidate = view.dimensions.original, view.dimensions.candidate
    assert original is not None and candidate is not None
    solved = view.preview_dimension(original, candidate)
    assert solved.sketch is not None
    view.set_context_sketches((solved.sketch,))
    view.dimensions.complete_commit(original, candidate, solved)
    view.dimensions.buttons["baseline"].click()
    assert view.dimensions.references[0].entity_id == other.entities[0].entity_id


def test_coplanar_shifted_source_has_visible_driving_preview(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch_constraints import SketchConstraintSolveResult

    view = editor(qtbot)
    frame = replace(WorkPlaneFrame.xy(), origin_mm=(100, 0, 0))
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    source = Sketch(uuid4().hex, frame, (line,))
    view.set_context_sketches((source,))
    view.show_dimension_preview(SketchConstraintSolveResult("success", source, 3))
    preview = view.canvas.dimension_preview
    assert preview is not None
    assert preview.frame == view.current_frame()
    entity = preview.entities[0]
    assert isinstance(entity, LineEntity)
    assert entity.start_mm == (100, 0)


def test_dimension_preview_preserves_rectangle_segment_identity(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import tangent_entity_curve
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import RectangleEntity
    from mycad.core.sketch_constraints import (
        SketchConstraint,
        SketchConstraintSolveResult,
        SketchGeometryReference,
    )

    view = editor(qtbot)
    frame = replace(WorkPlaneFrame.xy(), origin_mm=(100, 0, 0))
    rectangle = RectangleEntity(uuid4().hex, (10, 20), (-10, 0))
    circle = CircleEntity(uuid4().hex, (0, 22), 2)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    source = Sketch(uuid4().hex, frame, (rectangle, circle), constraints=(tangent,))
    view.set_context_sketches((source,))
    view.show_dimension_preview(SketchConstraintSolveResult("success", source, 3))
    preview = view.canvas.dimension_preview
    assert preview is not None
    projected_rectangle, projected_circle = preview.entities
    assert isinstance(projected_rectangle, RectangleEntity)
    assert isinstance(projected_circle, CircleEntity)
    assert projected_rectangle.first_corner_mm == (110, 20)
    assert projected_rectangle.opposite_corner_mm == (90, 0)
    assert tangent_on_curves(tangent_entity_curve(projected_rectangle, 0), projected_circle)


def test_click_and_double_click_cancel_do_not_create_undo_entries(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 10))
    click(view, (15, -15))
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(dimension, {e.entity_id: e for e in view.canvas.entities})
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.mouseDClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.keyClick(view.dimensions.value_editor, Qt.Key.Key_Escape)
    assert view.canvas.undo_last_operation()
    assert not view.canvas.constraints


def test_driving_continuation_remains_active_after_confirming_value(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (20, 0), (40, 20)),
    ]
    view.dimensions.buttons["horizontal"].click()
    click(view, (0, 0))
    click(view, (20, 0))
    click(view, (10, -15))
    view.dimensions.buttons["continue"].click()
    view.dimensions.driving_check.setChecked(True)
    click(view, (40, 20))
    click(view, (30, -15))
    view.dimensions.value_editor.setValue(25)
    view.dimensions.apply_button.click()
    if len(view.canvas.constraints) == 1:
        view.dimensions.apply_button.click()
    assert len(view.canvas.constraints) == 2
    assert view.canvas.constraints[-1].driving
    assert view.dimensions.mode == "continue"
    assert len(view.dimensions.references) == 1


@pytest.mark.parametrize(
    "tool,kind", [("radius", "radius"), ("diameter", "diameter"), ("arc_length", "arc_length")]
)
def test_radial_and_arc_commands(qtbot: QtBot, tool: str, kind: str) -> None:
    view = editor(qtbot)
    view.canvas.entities = [ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)]
    view.dimensions.buttons[tool].click()
    click(view, (0, 10))
    click(view, (20, 20))
    assert len(view.canvas.constraints) == 1
    assert view.canvas.constraints[0].kind == kind


def test_smart_circle_and_inline_value_edit(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 10)]
    view.dimensions.buttons["smart"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    dimension = view.canvas.constraints[0]
    label = view.canvas.dimension_layout(dimension, {e.entity_id: e for e in view.canvas.entities})
    assert label is not None
    QTest.mouseDClick(view.canvas, Qt.MouseButton.LeftButton, pos=label.label.toPoint())
    assert view.dimensions.value_editor.isVisible()
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.value_editor.setValue(30)
    view.dimensions.apply_button.click()
    assert view.canvas.constraints[0].driving
    entity = view.canvas.entities[0]
    assert isinstance(entity, CircleEntity)
    assert entity.radius_mm == pytest.approx(15)


@pytest.mark.parametrize("kind", ("radius", "diameter", "arc_length"))
def test_reference_dimension_on_curved_polyline_arc_segment(qtbot: QtBot, kind: str) -> None:
    view = editor(qtbot)
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1, 0))
    view.canvas.entities = [curved]
    view.dimensions.buttons[kind].click()
    click(view, (5, -5))
    click(view, (15, -10))
    assert len(view.canvas.constraints) == 1
    dimension = view.canvas.constraints[0]
    assert dimension.kind == kind and not dimension.driving
    assert dimension.references[0].kind == "segment" and dimension.references[0].index == 0
    expected = 10 if kind == "diameter" else (5 * 3.141592653589793 if kind == "arc_length" else 5)
    assert dimension.value == pytest.approx(expected)
    assert view.canvas.dimension_layout(dimension, {curved.entity_id: curved}) is not None
    assert view.canvas.entities == [curved]


def test_driving_radius_on_curved_polyline_arc_segment(qtbot: QtBot) -> None:
    from mycad.core.polyline_curves import polyline_arc_segment

    view = editor(qtbot)
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.5, 0))
    view.canvas.entities = [curved]
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.buttons["radius"].click()
    click(view, (5, -2.5))
    click(view, (15, -10))
    view.dimensions.value_editor.setValue(7.5)
    view.dimensions.apply_button.click()
    assert len(view.canvas.constraints) == 1
    assert view.canvas.constraints[0].driving
    moved = view.canvas.entities[0]
    assert isinstance(moved, PolylineEntity)
    assert polyline_arc_segment(moved, 0).radius_mm == pytest.approx(7.5)
    assert view.canvas.undo_last_operation()
    assert view.canvas.entities == [curved] and not view.canvas.constraints


def test_driving_distance_between_curved_polyline_vertices(qtbot: QtBot) -> None:
    view = editor(qtbot)
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.5, 0))
    view.canvas.entities = [curved]
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.buttons["aligned"].click()
    click(view, (0, 0))
    click(view, (10, 0))
    click(view, (5, -10))
    view.dimensions.value_editor.setValue(15)
    view.dimensions.apply_button.click()
    assert len(view.canvas.constraints) == 1
    dimension = view.canvas.constraints[0]
    assert dimension.kind == "distance" and dimension.driving
    moved = view.canvas.entities[0]
    assert isinstance(moved, PolylineEntity)
    assert moved.bulges == curved.bulges
    assert abs(moved.points_mm[1][0] - moved.points_mm[0][0]) == pytest.approx(15)
    assert view.canvas.undo_last_operation()
    assert view.canvas.entities == [curved] and not view.canvas.constraints


def test_driving_dimension_keeps_unrelated_curved_polyline(qtbot: QtBot) -> None:
    view = editor(qtbot)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    curved = PolylineEntity(uuid4().hex, ((30, 0), (32, 0), (32, 2)), bulges=(1, 0))
    assert view.canvas.replace_draft_entities((circle, curved))
    view.dimensions.buttons["smart"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    dimension = view.canvas.constraints[0]
    label = view.canvas.dimension_layout(dimension, {e.entity_id: e for e in view.canvas.entities})
    assert label is not None
    QTest.mouseDClick(view.canvas, Qt.MouseButton.LeftButton, pos=label.label.toPoint())
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.value_editor.setValue(30)
    view.dimensions.apply_button.click()
    assert view.canvas.constraints[0].driving
    assert isinstance(view.canvas.entities[0], CircleEntity)
    assert view.canvas.entities[0].radius_mm == pytest.approx(15)
    assert view.canvas.entities[1] == curved
    assert view.canvas.undo_last_operation()
    assert view.canvas.entities == [circle, curved]


def test_continue_baseline_and_ordinate_use_stable_point_references(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (20, 0), (40, 20)),
    ]
    view.dimensions.buttons["horizontal"].click()
    click(view, (0, 0))
    click(view, (20, 0))
    click(view, (10, -10))
    first = view.canvas.constraints[-1]
    view.dimensions.buttons["continue"].click()
    click(view, (40, 20))
    click(view, (30, -10))
    second = view.canvas.constraints[-1]
    assert second.references[0] == first.references[-1]
    assert second.value == pytest.approx(20)
    view.dimensions.buttons["baseline"].click()
    click(view, (40, 20))
    click(view, (30, -20))
    assert view.canvas.constraints[-1].references[0] == first.references[0]
    view.dimensions.buttons["ordinate"].click()
    click(view, (0, 0))
    click(view, (40, 20))
    click(view, (40, -20))
    assert view.canvas.constraints[-1].axis == "ordinate_x"


def test_angle_picks_two_segments_then_places(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (30, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 30)),
    ]
    view.dimensions.buttons["angle"].click()
    click(view, (15, 0))
    click(view, (0, 15))
    click(view, (12, 12))
    assert view.canvas.constraints[-1].kind == "angle"
    assert abs(view.canvas.constraints[-1].value or 0) == pytest.approx(90)


@pytest.mark.parametrize("bulge", [0.5, -0.5])
def test_driving_angle_on_straight_segment_of_curved_polyline(qtbot: QtBot, bulge: float) -> None:
    view = editor(qtbot)
    path = PolylineEntity(uuid4().hex, ((-20, -20), (-20, 0), (20, 0)), bulges=(bulge, 0))
    line = LineEntity(uuid4().hex, (0, 0), (0, 30))
    view.canvas.entities = [path, line]
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.buttons["angle"].click()
    click(view, (-10, 0))
    click(view, (0, 15))
    click(view, (10, 10))
    assert view.dimensions.value_editor.isVisible(), view.dimensions.prompt.text()
    view.dimensions.value_editor.setValue(45)
    QTest.mouseClick(
        view.canvas,
        Qt.MouseButton.RightButton,
        pos=view.canvas.local_to_screen((10, 10)),
    )
    if not view.canvas.constraints:
        assert "再次确认" in view.dimensions.prompt.text()
        QTest.mouseClick(
            view.canvas,
            Qt.MouseButton.RightButton,
            pos=view.canvas.local_to_screen((10, 10)),
        )
    assert len(view.canvas.constraints) == 1, view.dimensions.prompt.text()
    dimension = view.canvas.constraints[0]
    assert dimension.kind == "angle" and dimension.driving
    assert dimension.references[0].entity_id == path.entity_id
    assert dimension.references[0].kind == "segment" and dimension.references[0].index == 1
    assert dimension.value == pytest.approx(45)
    solved = view.canvas.entities[0]
    assert isinstance(solved, PolylineEntity) and solved.bulges == path.bulges
    QTest.mouseClick(
        view.canvas, Qt.MouseButton.RightButton, pos=view.canvas.local_to_screen((10, 10))
    )
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert not view.canvas.constraints
    assert view.canvas.undo_last_operation()
    assert view.canvas.constraints == [dimension]
    assert view.canvas.undo_last_operation()
    assert view.canvas.entities == [path, line] and not view.canvas.constraints


def test_committed_dimension_uses_canvas_bus_and_undo(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_view_2d.trigger()
    view = window.active_sketch_dialog()
    assert view is not None
    view.dimensions.driving_check.setChecked(False)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 0))
    click(view, (15, -15))
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2, timeout=10000)
    assert loaded.document.commands[-1].id == "sketch.constraint.add"
    assert services.kernel.sketches[0].constraints[0].position_mm == pytest.approx(
        (15, -15), abs=0.2
    )
    assert not view.canvas.entities
    assert QApplication.activeModalWidget() is None
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == ()


def test_dimension_drag_preserves_driving_and_inline_cancel(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 10))
    click(view, (15, -15))
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    dimension = view.canvas.constraints[0]
    before = tuple(view.canvas.entities)
    layout = view.canvas.dimension_layout(dimension, {e.entity_id: e for e in view.canvas.entities})
    assert layout is not None
    start = layout.label.toPoint()
    target = view.canvas.local_to_screen((10, -25))
    QTest.mousePress(view.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.canvas, target)
    QTest.mouseRelease(view.canvas, Qt.MouseButton.LeftButton, pos=target)
    assert view.canvas.constraints[0].text_position_mm == pytest.approx((10, -25), abs=0.2)
    assert tuple(view.canvas.entities) == before
    view.canvas.undo_last_operation()
    assert view.canvas.constraints[0] == dimension


def test_locked_layer_is_reference_only_and_cross_sketch_pick_is_rejected(qtbot: QtBot) -> None:
    from dataclasses import replace

    view = editor(qtbot)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (50, 0), (60, 0)),))
    view.set_context_sketches((sketch,))
    view.dimensions.buttons["aligned"].click()
    click(view, (0, 0))
    click(view, (50, 0))
    assert view.canvas.dimension_candidate is None
    QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    layer = replace(view.layer_table.get("0"), locked=True)
    view.layer_table = view.layer_table.replace(layer)
    view.canvas.set_layer_table(view.layer_table, "0")
    view.dimensions.buttons["horizontal"].click()
    view.dimensions.driving_check.setChecked(True)
    click(view, (15, 10))
    assert not view.dimensions.references


def test_dimension_remains_in_model_coordinates_when_panned(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 10))
    from PySide6.QtCore import QPoint

    center = view.canvas.rect().center()
    QTest.mousePress(view.canvas, Qt.MouseButton.MiddleButton, pos=center)
    QTest.mouseMove(view.canvas, center + QPoint(40, 25))
    QTest.mouseRelease(view.canvas, Qt.MouseButton.MiddleButton, pos=center + QPoint(40, 25))
    click(view, (20, -15))
    assert view.canvas.constraints[-1].position_mm == pytest.approx((20, -15), abs=0.2)


def test_invalid_driving_value_does_not_apply_previous_valid_candidate(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["radius"].click()
    view.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 10)]
    click(view, (10, 0))
    click(view, (20, 20))
    dimension = view.canvas.constraints[0]
    view.dimensions.edit(view.dimension_sources()[0], dimension)
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.value_editor.setValue(-5)
    view.dimensions.apply_edit()
    assert view.canvas.constraints == [dimension]
    assert view.dimensions.candidate is not None
    assert not view.dimensions.apply_button.isEnabled()


def test_cancelling_pending_committed_request_allows_a_new_command(qtbot: QtBot) -> None:
    view = editor(qtbot)
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    view.canvas.entities = []
    view.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    requested: list[object] = []

    def record_request(_sketch: object, constraint: object) -> None:
        requested.append(constraint)

    view.dimensions.committed_requested.connect(record_request)
    for _ in range(2):
        view.dimensions.buttons["horizontal"].click()
        click(view, (15, 0))
        click(view, (15, -15))
        QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    assert len(requested) == 2


def test_cancel_while_committed_solver_runs_leaves_history_untouched(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", source.to_mapping(version=3), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_view_2d.trigger()
    view = window.active_sketch_dialog()
    assert view is not None
    entered, release = threading.Event(), threading.Event()
    real_preview = services.kernel.preview_sketch_constraint

    def delayed(sketch: Sketch, constraint: object) -> object:
        entered.set()
        assert release.wait(5)
        from mycad.core.sketch_constraints import SketchConstraint

        assert isinstance(constraint, SketchConstraint)
        return real_preview(sketch, constraint)

    monkeypatch.setattr(services.kernel, "preview_sketch_constraint", delayed)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 0))
    click(view, (15, -15))
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        QTest.keyClick(view.canvas, Qt.Key.Key_Escape)
    finally:
        release.set()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == 1
    assert services.kernel.sketches[0].constraints == ()


def test_failed_async_preview_has_an_explicit_retry(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import (
        SketchConstraint,
        SketchConstraintSolveResult,
        SketchGeometryReference,
    )

    view = editor(qtbot)
    view.canvas.entities = []
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(20, 20),
    )
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    view.set_context_sketches((source,))
    requests: list[int] = []

    def record(_sketch: object, _constraint: object, generation: int) -> None:
        requests.append(generation)

    view.dimensions.preview_requested.connect(record)
    view.dimensions.edit(source, dimension)
    view.dimensions.driving_check.setChecked(True)
    qtbot.waitUntil(lambda: bool(requests), timeout=2000)
    candidate = view.dimensions.candidate
    assert candidate is not None
    view.dimensions.complete_preview(
        requests[-1],
        source,
        candidate,
        SketchConstraintSolveResult("failed", None, None, message="几何工作线程忙碌"),
    )
    assert view.dimensions.apply_button.isEnabled()
    assert "预览" in view.dimensions.apply_button.text()
    previous = requests[-1]
    view.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: requests[-1] > previous, timeout=2000)
    assert source.constraints == (dimension,)


@pytest.mark.parametrize("finish_with_right_click", [False, True])
def test_dimension_finished_enter_and_right_click_exit_mode(
    qtbot: QtBot, finish_with_right_click: bool
) -> None:
    view = editor(qtbot)
    view.dimensions.buttons["horizontal"].click()
    click(view, (15, 10))
    click(view, (20, -15))
    assert len(view.canvas.constraints) == 1 and view.dimensions.mode == "horizontal"
    if finish_with_right_click:
        QTest.mouseClick(
            view.canvas, Qt.MouseButton.RightButton, pos=view.canvas.local_to_screen((20, -15))
        )
    else:
        QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    assert view.dimensions.mode is None and len(view.canvas.constraints) == 1


@pytest.mark.parametrize(
    "tool",
    [
        "smart",
        "horizontal",
        "vertical",
        "aligned",
        "radius",
        "diameter",
        "arc_length",
        "angle",
        "ordinate",
    ],
)
def test_reference_dimension_right_click_then_select_delete(qtbot: QtBot, tool: str) -> None:
    view = editor(qtbot)
    if tool in ("radius", "diameter", "arc_length"):
        view.canvas.entities = [ArcEntity(uuid4().hex, (0, 0), 10, 0, 180)]
        points = ((0, 10), (20, 20))
    elif tool == "angle":
        view.canvas.entities = [
            LineEntity(uuid4().hex, (0, 0), (30, 0)),
            LineEntity(uuid4().hex, (0, 0), (0, 30)),
        ]
        points = ((15, 0), (0, 15), (12, 12))
    elif tool == "ordinate":
        points = ((0, 0), (30, 20), (40, -20))
    else:
        points = ((15, 10), (20, -15))
    view.dimensions.buttons[tool].click()
    for point in points:
        click(view, point)
    assert len(view.canvas.constraints) == 1, view.status_label.text()
    dimension = view.canvas.constraints[0]
    QTest.mouseClick(
        view.canvas, Qt.MouseButton.RightButton, pos=view.canvas.local_to_screen(points[-1])
    )
    assert view.dimensions.mode is None
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert not view.canvas.constraints
    assert view.canvas.undo_last_operation() and view.canvas.constraints == [dimension]


@pytest.mark.parametrize("tool", ["continue", "baseline"])
def test_chained_dimension_right_click_then_select_delete(qtbot: QtBot, tool: str) -> None:
    view = editor(qtbot)
    view.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (20, 0), (40, 20)),
    ]
    view.dimensions.buttons["horizontal"].click()
    for point in ((0, 0), (20, 0), (10, -10)):
        click(view, point)
    view.dimensions.buttons[tool].click()
    for point in ((40, 20), (30, -20)):
        click(view, point)
    assert len(view.canvas.constraints) == 2
    dimension = view.canvas.constraints[-1]
    QTest.mouseClick(
        view.canvas, Qt.MouseButton.RightButton, pos=view.canvas.local_to_screen((30, -20))
    )
    assert view.dimensions.mode is None
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert len(view.canvas.constraints) == 1
    assert view.canvas.undo_last_operation() and view.canvas.constraints[-1] == dimension


def test_dimension_right_click_applies_entered_driving_value(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 10)]
    view.dimensions.driving_check.setChecked(True)
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    view.dimensions.value_editor.setValue(7)
    QTest.mouseClick(
        view.canvas, Qt.MouseButton.RightButton, pos=view.canvas.local_to_screen((20, 20))
    )
    assert len(view.canvas.constraints) == 1 and view.canvas.constraints[0].driving
    circle = view.canvas.entities[0]
    assert isinstance(circle, CircleEntity) and circle.radius_mm == pytest.approx(7)


@pytest.mark.parametrize("driving", [False, True])
def test_select_dimension_with_single_click_and_delete_undo(qtbot: QtBot, driving: bool) -> None:
    view = editor(qtbot)
    view.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 10)]
    view.dimensions.driving_check.setChecked(driving)
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    if driving:
        view.dimensions.value_editor.setValue(7)
        view.dimensions.apply_button.click()
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(
        dimension, {entity.entity_id: entity for entity in view.canvas.entities}
    )
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert not view.canvas.constraints and len(view.canvas.entities) == 1
    assert view.canvas.undo_last_operation() and view.canvas.constraints == [dimension]


def test_delete_mixed_draft_dimension_and_entity_atomically(qtbot: QtBot) -> None:
    view = editor(qtbot)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    line = LineEntity(uuid4().hex, (40, 0), (60, 0))
    view.canvas.entities = [circle, line]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(
        dimension, {item.entity_id: item for item in view.canvas.entities}
    )
    assert layout is not None
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    QTest.mouseClick(
        view.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=view.canvas.local_to_screen((50, 0)),
    )
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    assert view.canvas.selected_entity_ids == {line.entity_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert view.canvas.entities == [circle] and not view.canvas.constraints
    assert view.canvas.undo_last_operation()
    assert view.canvas.entities == [circle, line] and view.canvas.constraints == [dimension]


def test_crossing_box_selects_and_deletes_dimension(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.select_committed_entities = True
    view.canvas.entities = [CircleEntity(uuid4().hex, (0, 0), 10)]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(
        dimension, {item.entity_id: item for item in view.canvas.entities}
    )
    assert layout is not None
    center = layout.label.toPoint()
    start, end = center + QPoint(45, -25), center + QPoint(-45, 25)
    QTest.mousePress(view.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(view.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    assert not view.canvas.selected_entity_ids
    QTest.keyClick(view.canvas, Qt.Key.Key_Delete)
    assert not view.canvas.constraints and len(view.canvas.entities) == 1
    assert view.canvas.undo_last_operation() and view.canvas.constraints == [dimension]
    QTest.mousePress(
        view.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=start
    )
    QTest.mouseRelease(
        view.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=end
    )
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.mousePress(
        view.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=start
    )
    QTest.mouseRelease(
        view.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=end
    )
    assert not view.canvas.selected_constraint_ids


@pytest.mark.parametrize("hidden", [False, True])
def test_deleting_draft_entity_preserves_locked_dependent_dimension(
    qtbot: QtBot, hidden: bool
) -> None:
    view = editor(qtbot)
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    view.canvas.entities = [circle]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = replace(view.canvas.constraints[0], layer_name="locked")
    view.canvas.constraints = [dimension]
    view.canvas.set_layer_table(
        view.canvas.layer_table.add(SketchLayer("locked", locked=not hidden, visible=not hidden)),
        "0",
    )
    view.canvas.selected_entity_ids = {circle.entity_id}
    assert not view.canvas.delete_selected()
    assert view.canvas.entities == [circle] and view.canvas.constraints == [dimension]


@pytest.mark.parametrize("preselect", [False, True])
def test_erase_command_deletes_dimension(qtbot: QtBot, preselect: bool) -> None:
    view = editor(qtbot)
    view.canvas.select_committed_entities = True
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    view.canvas.entities = [circle]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    if not preselect:
        erase_command(view)
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    if preselect:
        erase_command(view)
    else:
        QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    assert not view.canvas.constraints and view.canvas.entities == [circle]
    assert view.canvas.undo_last_operation() and view.canvas.constraints == [dimension]


def test_erase_command_selects_dimension_and_geometry_together(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.select_committed_entities = True
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    line = LineEntity(uuid4().hex, (40, 0), (60, 0))
    view.canvas.entities = [circle, line]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    erase_command(view)
    click(view, (50, 0))
    QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert view.canvas.selected_entity_ids == {line.entity_id}
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    assert view.canvas.entities == [circle] and not view.canvas.constraints


def test_erase_command_crossing_box_selects_dimension(qtbot: QtBot) -> None:
    view = editor(qtbot)
    view.canvas.select_committed_entities = True
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    view.canvas.entities = [circle]
    view.dimensions.buttons["radius"].click()
    click(view, (10, 0))
    click(view, (20, 20))
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    dimension = view.canvas.constraints[0]
    layout = view.canvas.dimension_layout(dimension, view.canvas.dimension_entities())
    assert layout is not None
    erase_command(view)
    center = layout.label.toPoint()
    QTest.mousePress(view.canvas, Qt.MouseButton.LeftButton, pos=center + QPoint(45, -25))
    QTest.mouseRelease(view.canvas, Qt.MouseButton.LeftButton, pos=center + QPoint(-45, 25))
    assert view.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.keyClick(view.canvas, Qt.Key.Key_Return)
    assert not view.canvas.constraints and view.canvas.entities == [circle]
