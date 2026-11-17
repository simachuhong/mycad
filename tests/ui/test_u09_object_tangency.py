# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Direct object tangency in a 2D drawing."""

from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import CircleEntity, LineEntity
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow

_TEST_SCALE_ATTRIBUTE = "_scale"
_TEST_CONSTRAINT_CHECK = "_reject_user_constraint_reference_edits"


@pytest.mark.parametrize(
    "mode, cutter_x, click, expected_end", [("修剪", 8, (9, 0), 8), ("延伸", 15, (10, 0), 15)]
)
def test_tangent_draft_line_edit_retains_constraint(
    qtbot: QtBot, mode: str, cutter_x: int, click: tuple[int, int], expected_end: int
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (cutter_x, -4), (cutter_x, 4))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas.entities = [line, circle, cutter]
    canvas.constraints = [constraint]
    canvas.set_tool(mode)
    canvas.add_coordinate_point(click, exact_point=True)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == (expected_end, 0)
    assert canvas.constraints == [constraint]
    assert canvas.undo_last_operation()
    assert canvas.entities[0] == line
    assert canvas.constraints == [constraint]
    canvas.entities.clear()


def test_tangent_draft_arc_trim_retains_contact(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    arc = ArcEntity(uuid4().hex, (10, 0), 5, 90, 180)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(arc.entity_id, "geometry"),
        ),
    )
    canvas.entities = [arc, circle]
    canvas.constraints = [constraint]
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((6.464466, 3.535534), exact_point=True)
    assert isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].start_angle_deg == pytest.approx(180)
    assert canvas.entities[0].sweep_angle_deg == pytest.approx(90)
    assert canvas.constraints == [constraint]
    assert canvas.undo_last_operation()
    assert canvas.entities[0] == arc
    canvas.entities.clear()


@pytest.mark.parametrize("separate_records", [False, True])
def test_saved_tangent_circle_trim_retains_relation(
    qtbot: QtBot, tmp_path: Path, separate_records: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (-10, 5), (10, 5))
    cutter = LineEntity(uuid4().hex, (0, -10), (0, 10))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    first = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (circle, cutter) if separate_records else (circle, line, cutter),
        constraints=() if separate_records else (constraint,),
    )
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    if separate_records:
        second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
        app.commit_new_sketch(services, loaded, second, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, line.entity_id),
            CrossSketchRef(first.sketch_id, circle.entity_id),
            "line_right",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((-5, 0), exact_point=True)
    qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, ArcEntity)
    assert result.entity_id == circle.entity_id
    if separate_records:
        assert len(services.kernel.cross_sketch_tangencies) == 1
    else:
        assert services.kernel.sketches[0].constraints == (constraint,)
    changed = services.kernel.sketches
    path = tmp_path / "trimmed-tangent-circle.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == before
    reopened.bus.redo()
    assert restored.kernel.sketches == changed


def test_saved_tangent_circle_trim_with_draft_commits(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (-10, 5), (10, 5))
    cutter = LineEntity(uuid4().hex, (0, -10), (0, 10))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(second.sketch_id, line.entity_id),
        CrossSketchRef(first.sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.entities = [LineEntity(uuid4().hex, (30, 30), (40, 30))]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((-5, 0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert isinstance(services.kernel.sketches[0].entities[0], ArcEntity)
    assert services.kernel.sketches[0].entities[0].entity_id == circle.entity_id
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_tangent_draft_trim_rejects_removing_contact(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas.entities = [line, circle]
    canvas.constraints = [constraint]
    shortened = LineEntity(line.entity_id, (0, 0), (4, 0))
    with pytest.raises(ValueError, match="用户约束"):
        cast("Callable[..., None]", getattr(canvas, _TEST_CONSTRAINT_CHECK))(
            (shortened, circle), allow_satisfied_tangency=True
        )
    assert canvas.entities[0] == line
    assert canvas.constraints == [constraint]
    canvas.entities.clear()


def test_tangent_trim_does_not_rebind_to_different_polyline_segment(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((10, 10), (-5, 0), (5, 0), (5, 4), (-5, 4)))
    circle = CircleEntity(uuid4().hex, (3, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 1),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas.entities = [polyline, circle]
    canvas.constraints = [constraint]
    shortened = PolylineEntity(polyline.entity_id, polyline.points_mm[1:])
    with pytest.raises(ValueError, match="用户约束"):
        cast("Callable[..., None]", getattr(canvas, _TEST_CONSTRAINT_CHECK))(
            (shortened, circle), allow_satisfied_tangency=True
        )
    same_segment = PolylineEntity(polyline.entity_id, (*polyline.points_mm[:-1], (-4, 4)))
    cast("Callable[..., None]", getattr(canvas, _TEST_CONSTRAINT_CHECK))(
        (same_segment, circle), allow_satisfied_tangency=True
    )
    shortened_segment = PolylineEntity(
        polyline.entity_id, (polyline.points_mm[0], (-4, 0), *polyline.points_mm[2:])
    )
    cast("Callable[..., None]", getattr(canvas, _TEST_CONSTRAINT_CHECK))(
        (shortened_segment, circle), allow_satisfied_tangency=True
    )
    canvas.entities.clear()


@pytest.mark.parametrize("drag", [False, True])
def test_draft_closed_polyline_trim_retains_local_tangent(qtbot: QtBot, drag: bool) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 40)
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    cutter = LineEntity(uuid4().hex, (8, -1), (8, 11))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas.entities = [polyline, circle, cutter]
    canvas.constraints = [constraint]
    canvas.set_tool("修剪")
    if drag:
        start = canvas.local_to_screen((6.5, -0.15))
        end = canvas.local_to_screen((6.5, 0.15))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        preview = tuple(canvas.entities)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        canvas.add_coordinate_point((6.5, 0), exact_point=True)
        preview = ()
    assert isinstance(canvas.entities[0], PolylineEntity) and not canvas.entities[0].closed, (
        canvas.message,
        preview,
    )
    assert canvas.constraints[0].references[0].index != 0
    assert canvas.undo_last_operation()
    assert canvas.entities[0] == polyline
    assert canvas.constraints == [constraint]
    canvas.entities.clear()


@pytest.mark.parametrize("mode", ["draft", "saved", "mixed"])
def test_tangent_polyline_trim_rebinds_to_new_fragment(
    qtbot: QtBot, tmp_path: Path, mode: str
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    original = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle, cutter), constraints=(constraint,)
    )
    canvas = editor.canvas
    if mode != "draft":
        app.commit_new_sketch(services, loaded, original, session_identity=0)
        editor.set_context_sketches(services.kernel.sketches)
        if mode == "mixed":
            canvas.entities = [LineEntity(uuid4().hex, (30, 30), (40, 30))]
    else:
        canvas.entities = list(original.entities)
        canvas.constraints = [constraint]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    if mode == "mixed":
        qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    if mode != "draft":
        qtbot.waitUntil(lambda: services.kernel.sketches[0] != original, timeout=10000)
        entities = services.kernel.sketches[0].entities
        constraints = services.kernel.sketches[0].constraints
    else:
        entities, constraints = tuple(canvas.entities), tuple(canvas.constraints)
    assert len(entities) == 4
    assert constraints[0].references[0].entity_id != polyline.entity_id
    fragment = next(
        item for item in entities if item.entity_id == constraints[0].references[0].entity_id
    )
    assert isinstance(fragment, PolylineEntity)
    assert fragment.points_mm[0] == pytest.approx((5, 0))
    if mode != "draft":
        changed = services.kernel.sketches
        path = tmp_path / "fragment-tangent.my2d"
        save_document(loaded.document, path)
        restored = app.build_app(discoverers=[])
        reopened = app.open_app_document(restored, path)
        assert restored.kernel.sketches == changed
        reopened.bus.undo()
        assert restored.kernel.sketches[0] == original
        reopened.bus.redo()
        assert restored.kernel.sketches == changed
    else:
        assert canvas.undo_last_operation()
        assert canvas.entities == list(original.entities)
        canvas.entities.clear()


def test_tangent_polyline_segment_trim_preserves_contact(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    polyline = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (5, 4), (-5, 4)))
    circle = CircleEntity(uuid4().hex, (1, 2), 2)
    cutter = LineEntity(uuid4().hex, (4, -2), (4, 2))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    canvas.entities = [polyline, circle, cutter]
    canvas.constraints = [constraint]
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((4.5, 0), exact_point=True)
    assert isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].points_mm[-1] == pytest.approx((4, 0))
    assert canvas.constraints == [constraint]
    assert canvas.undo_last_operation()
    assert canvas.entities[0] == polyline
    canvas.entities.clear()


@pytest.mark.parametrize("with_draft", [False, True])
def test_saved_tangent_polyline_trim_replays(
    qtbot: QtBot, tmp_path: Path, with_draft: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, -5), (0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (8, -4), (8, 4))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    if with_draft:
        canvas.entities = [LineEntity(uuid4().hex, (30, 30), (40, 30))]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((9, 0), exact_point=True)
    if with_draft:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    changed = services.kernel.sketches
    assert isinstance(changed[0].entities[0], PolylineEntity)
    assert changed[0].entities[0].points_mm[-1] == pytest.approx((8, 0))
    assert services.kernel.cross_sketch_tangencies == (relation,)
    path = tmp_path / "trimmed-polyline.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert (
        restored.kernel.sketches == before
        if not with_draft
        else restored.kernel.sketches[0:2] == before
    )
    reopened.bus.redo()
    assert restored.kernel.sketches == changed


@pytest.mark.parametrize("with_draft", [False, True])
def test_saved_closed_polyline_trim_retains_local_tangent(
    qtbot: QtBot, tmp_path: Path, with_draft: bool
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    cutter = LineEntity(uuid4().hex, (8, -1), (8, 11))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle, cutter), constraints=(constraint,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    if with_draft:
        canvas.entities = [LineEntity(uuid4().hex, (30, 30), (40, 30))]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((6.5, 0), exact_point=True)
    if with_draft:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    revised = services.kernel.sketches[0]
    assert isinstance(revised.entities[0], PolylineEntity)
    assert not revised.entities[0].closed
    assert revised.constraints[0].references[0].index != 0
    changed = services.kernel.sketches
    path = tmp_path / "closed-tangent-trim.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches[0] == before[0]
    reopened.bus.redo()
    assert restored.kernel.sketches == changed


def test_saved_closed_polyline_drag_trim_retains_local_tangent(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    cutter = LineEntity(uuid4().hex, (8, -1), (8, 11))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle, cutter), constraints=(constraint,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 40)
    canvas.set_tool("修剪")
    start, end = canvas.local_to_screen((6.5, -0.15)), canvas.local_to_screen((6.5, 0.15))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    revised = services.kernel.sketches[0]
    assert isinstance(revised.entities[0], PolylineEntity) and not revised.entities[0].closed
    assert revised.constraints[0].references[0].index != 0
    loaded.bus.undo()
    assert services.kernel.sketches == before


@pytest.mark.parametrize("with_draft", [False, True])
def test_saved_tangency_follows_new_polyline_fragment(
    qtbot: QtBot, tmp_path: Path, with_draft: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    if with_draft:
        canvas.entities = [LineEntity(uuid4().hex, (30, 30), (40, 30))]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    if with_draft:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    changed = services.kernel.sketches
    new_relation = services.kernel.cross_sketch_tangencies[0]
    assert new_relation.relation_id == relation.relation_id
    assert new_relation.first.entity_id != polyline.entity_id
    path = tmp_path / "saved-fragment-tangent.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    assert restored.kernel.cross_sketch_tangencies == (new_relation,)
    reopened.bus.undo()
    assert restored.kernel.sketches[:2] == before
    assert restored.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.redo()
    assert restored.kernel.sketches == changed
    assert restored.kernel.cross_sketch_tangencies == (new_relation,)


def test_pending_tangency_follows_new_draft_fragment(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    source_ref = SketchGeometryReference(circle.entity_id, "geometry")
    draft_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    canvas.entities = [polyline, cutter]
    canvas.pending_cross_tangencies = [(source_ref, draft_ref)]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    assert len(canvas.pending_cross_tangencies) == 1
    new_ref = canvas.pending_cross_tangencies[0][1]
    assert isinstance(new_ref, SketchGeometryReference) and new_ref.entity_id != polyline.entity_id
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [(source_ref, draft_ref)]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    path = tmp_path / "pending-fragment.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.cross_sketch_tangencies == services.kernel.cross_sketch_tangencies
    reopened.bus.undo()
    assert not restored.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert restored.kernel.cross_sketch_tangencies == services.kernel.cross_sketch_tangencies


def test_pending_tangent_fragment_survives_existing_mixed_timeline(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    saved_line = LineEntity(uuid4().hex, (0, 20), (10, 20))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, saved_line))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    other_cutter = LineEntity(uuid4().hex, (8, 18), (8, 22))
    source_ref = SketchGeometryReference(circle.entity_id, "geometry")
    draft_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    pair = (source_ref, draft_ref)
    canvas.entities = [polyline, cutter, other_cutter]
    canvas.pending_cross_tangencies = [pair]
    original_draft = Sketch(editor.draft_sketch_id, editor.current_frame(), tuple(canvas.entities))
    original_relation = app.draft_cross_relations((saved,), original_draft, (pair,))[0]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((9, 20), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    assert len(canvas.pending_cross_tangencies) == 1
    new_ref = canvas.pending_cross_tangencies[0][1]
    assert isinstance(new_ref, SketchGeometryReference) and new_ref.entity_id != polyline.entity_id
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    relation = services.kernel.cross_sketch_tangencies[0]
    assert relation.relation_id == original_relation.relation_id
    assert relation.second.entity_id == new_ref.entity_id
    path = tmp_path / "mixed-pending-fragment.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo()
    assert restored.kernel.cross_sketch_tangencies == (original_relation,)
    reopened.bus.redo()
    assert restored.kernel.cross_sketch_tangencies == (relation,)


def test_pending_tangency_follows_saved_source_fragment(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    source_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    draft_ref = SketchGeometryReference(circle.entity_id, "geometry")
    pair = (source_ref, draft_ref)
    canvas.entities = [circle, cutter]
    canvas.pending_cross_tangencies = [pair]
    original_draft = Sketch(editor.draft_sketch_id, editor.current_frame(), tuple(canvas.entities))
    original_relation = app.draft_cross_relations((saved,), original_draft, (pair,))[0]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
    assert len(canvas.pending_cross_tangencies) == 1
    new_ref = canvas.pending_cross_tangencies[0][0]
    assert isinstance(new_ref, SketchGeometryReference) and new_ref.entity_id != polyline.entity_id
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    relation = services.kernel.cross_sketch_tangencies[0]
    assert relation.relation_id == original_relation.relation_id
    assert relation.first.entity_id == new_ref.entity_id
    path = tmp_path / "pending-saved-fragment.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo()
    assert restored.kernel.cross_sketch_tangencies == (original_relation,)
    reopened.bus.redo()
    assert restored.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("saved_source", [False, True])
def test_pending_arc_tangency_follows_new_fragment(
    qtbot: QtBot, tmp_path: Path, saved_source: bool
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (5, 5)), bulges=(1, 0))
    circle = CircleEntity(uuid4().hex, (0, -7), 2)
    cutter = LineEntity(uuid4().hex, (-3, -6), (-3, 0))
    saved_entity, draft_entity = (polyline, circle) if saved_source else (circle, polyline)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_entity,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    arc_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    circle_ref = SketchGeometryReference(circle.entity_id, "geometry")
    pair = (arc_ref, circle_ref) if saved_source else (circle_ref, arc_ref)
    canvas.entities = [draft_entity, cutter]
    canvas.pending_cross_tangencies = [pair]
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((-1.71, -4.7), exact_point=True)
    if saved_source:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None, timeout=10000)
    assert len(canvas.pending_cross_tangencies) == 1
    new_ref = canvas.pending_cross_tangencies[0][0 if saved_source else 1]
    assert isinstance(new_ref, SketchGeometryReference) and new_ref.entity_id != polyline.entity_id
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    path = tmp_path / "pending-arc-fragment.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.cross_sketch_tangencies == relations


def test_rebound_fragment_tangency_remains_live_on_drag(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        resolve_tangent_curve,
    )
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 100)
    canvas.set_tool("修剪")
    before_trim = services.kernel.sketches
    canvas.add_coordinate_point((3.5, 0), exact_point=True)
    qtbot.waitUntil(lambda: services.kernel.sketches != before_trim, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    before_drag = services.kernel.sketches
    rebound = services.kernel.cross_sketch_tangencies[0]
    assert rebound.first.entity_id != polyline.entity_id
    canvas.set_tool("选择元素")
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 20)
    canvas.selected_entity_ids = {circle.entity_id}
    command_count = loaded.document.command_count
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2)))
    QTest.mouseMove(canvas, canvas.local_to_screen((5, 3)), delay=20)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 3)))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    after = services.kernel.sketches
    assert after != before_drag, (canvas.message, window.status_command.text(), command_count)
    updated_relation = services.kernel.cross_sketch_tangencies[0]
    assert updated_relation.relation_id == relation.relation_id
    owners = {sketch.sketch_id: sketch for sketch in after}
    assert tangent_on_curves(
        resolve_tangent_curve(owners[updated_relation.first.sketch_id], updated_relation.first),
        resolve_tangent_curve(owners[updated_relation.second.sketch_id], updated_relation.second),
    )
    loaded.bus.undo()
    assert services.kernel.sketches == before_drag


def test_saved_tangent_line_extend_retains_constraint(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (15, -4), (15, 4))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line, circle, cutter), constraints=(constraint,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    canvas.set_tool("延伸")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    qtbot.waitUntil(lambda: services.kernel.sketches[0].entities[0] != line, timeout=10000)
    assert isinstance(services.kernel.sketches[0].entities[0], LineEntity)
    assert services.kernel.sketches[0].entities[0].end_mm == (15, 0)
    assert services.kernel.sketches[0].constraints == (constraint,)
    loaded.bus.undo()
    assert services.kernel.sketches[0] == sketch


@pytest.mark.parametrize("mode", ["修剪", "延伸"])
def test_tangent_saved_objects_in_separate_records_can_be_edited(qtbot: QtBot, mode: str) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    if mode == "修剪":
        target = ArcEntity(uuid4().hex, (10, 0), 5, 90, 180)
        circle = CircleEntity(uuid4().hex, (0, 0), 5)
        extras = ()
        click = (6.464466, 3.535534)
        branch = "external"
    else:
        target = LineEntity(uuid4().hex, (0, 0), (10, 0))
        circle = CircleEntity(uuid4().hex, (5, 2), 2)
        extras = (LineEntity(uuid4().hex, (15, -4), (15, 4)),)
        click = (10, 0)
        branch = "line_left"
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target, *extras))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, target.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        branch,
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    editor.set_context_sketches(before)
    canvas = editor.canvas
    setattr(canvas, _TEST_SCALE_ATTRIBUTE, 10)
    canvas.set_tool(mode)
    canvas.add_coordinate_point(click, exact_point=True)
    qtbot.waitUntil(lambda: services.kernel.sketches != before, timeout=10000)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_selected_draft_objects_tangent_and_undo(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas = editor.canvas
    canvas.entities = [line, circle]
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    assert canvas.constraints[0].kind == "tangent"
    assert canvas.undo_last_operation()
    assert not canvas.constraints
    canvas.entities.clear()


def test_selected_saved_objects_tangent_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle))
    assert window.document_session is not None and window.document_session.active is not None
    active_services = window.document_session.active.services
    app.commit_new_sketch(active_services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(active_services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    count = loaded.document.command_count
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    assert active_services.kernel.sketches[0].constraints[0].kind == "tangent"
    loaded.bus.undo()
    assert not active_services.kernel.sketches[0].constraints


def test_tangency_dialog_describes_objects_without_internal_ids(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    first_id, second_id = uuid4().hex, uuid4().hex
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    sketches = (
        Sketch(first_id, WorkPlaneFrame.xy(), (line,)),
        Sketch(second_id, WorkPlaneFrame.xy(), (circle,)),
    )
    dialog = CrossSketchTangencyDialog(sketches, ())
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "对象相切"
    assert "直线" in dialog.first_combo.itemText(0)
    assert "圆" in dialog.first_combo.itemText(1)
    for index in range(dialog.first_combo.count()):
        assert first_id[:8] not in dialog.first_combo.itemText(index)
        assert second_id[:8] not in dialog.first_combo.itemText(index)


def test_selected_tangent_objects_choose_existing_side(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),
    )
    dialog = CrossSketchTangencyDialog(
        sketches, (), selected_entity_ids=frozenset((line.entity_id, circle.entity_id))
    )
    qtbot.addWidget(dialog)
    assert dialog.branch_combo.currentData() == "line_right"


def test_polyline_click_preselects_specific_segment(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    assert window.document_session is not None and window.document_session.active is not None
    active_services = window.document_session.active.services
    for entity in (polyline, circle):
        app.commit_new_sketch(
            active_services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(active_services.kernel.sketches)
    canvas = editor.canvas
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    assert canvas.selected_segment_indices[polyline.entity_id] == 1
    window.act_manage_tangencies.trigger()
    dialog_attribute = "_cross_tangency_dialog"
    dialog = cast("CrossSketchTangencyDialog | None", getattr(window, dialog_attribute))
    assert dialog is not None
    assert dialog.first_combo.currentData().entity_id == polyline.entity_id
    assert dialog.first_combo.currentData().segment_index == 1
    assert dialog.second_combo.currentData().entity_id == circle.entity_id
    dialog.reject()


def test_draft_polyline_segment_tangency_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    canvas = editor.canvas
    canvas.entities = [polyline, circle]
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    constraint = canvas.constraints[0]
    assert constraint.kind == "tangent"
    assert constraint.references[0].entity_id == polyline.entity_id
    assert constraint.references[0].index == 1
    assert canvas.undo_last_operation()
    assert not canvas.constraints
    canvas.entities.clear()


def test_saved_polyline_segment_tangency_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    count = loaded.document.command_count
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    constraint = services.kernel.sketches[0].constraints[0]
    assert constraint.kind == "tangent"
    assert constraint.references[0].entity_id == polyline.entity_id
    assert constraint.references[0].index == 1
    loaded.bus.undo()
    assert not services.kernel.sketches[0].constraints


def test_mouse_selects_polyline_segment_for_tangency(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    canvas.entities = [polyline, circle]
    canvas.set_tool("选择元素")
    scale_attribute = "_scale"
    setattr(canvas, scale_attribute, 20.0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 8)))
    assert canvas.selected_segment_indices.get(polyline.entity_id) == 1, (
        canvas.message,
        canvas.selected_entity_ids,
    )
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=canvas.local_to_screen((14, 5)),
    )
    assert canvas.selected_entity_ids == {polyline.entity_id, circle.entity_id}
    assert canvas.selected_segment_indices[polyline.entity_id] == 1
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    assert canvas.constraints[0].references[0].index == 1
    assert canvas.undo_last_operation()
    canvas.entities.clear()


def test_new_tangency_preserves_existing_relation(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 2), 2)
    second_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_circle,))
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    app.commit_new_sketch(services, loaded, second, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, second_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}
    count = loaded.document.command_count
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.sketches[0].constraints[0].kind == "tangent"
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert not services.kernel.sketches[0].constraints


def test_separated_objects_default_to_current_side(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, -4), 2)
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),
    )
    dialog = CrossSketchTangencyDialog(
        sketches, (), selected_entity_ids=frozenset((line.entity_id, circle.entity_id))
    )
    qtbot.addWidget(dialog)
    assert dialog.branch_combo.currentData() == "line_right"


def test_linked_tangency_atomic_commit_and_undo(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    second_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, second_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, constraint, session_identity=0
    )
    result = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == first.sketch_id
    )
    solved_line, solved_circle = result.entities
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert tangent_on_curves(solved_line, solved_circle)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches == original
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_linked_tangency_from_ui_survives_reopen_and_undo(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    second_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, second_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    editor.set_context_sketches(original)
    editor.canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: "相切约束已写入历史" in window.status_command.text(), timeout=10000)
    changed = services.kernel.sketches
    assert changed != original
    assert changed[0].constraints[0].kind == "tangent"
    path = tmp_path / "linked-tangency.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    assert restored.kernel.sketches == original
    assert restored.kernel.cross_sketch_tangencies == (relation,)


def test_changed_polyline_invalidates_selected_segment(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch import PolylineEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    canvas.entities = [polyline]
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    assert canvas.selected_tangent_segments() == {polyline.entity_id: 1}
    canvas.entities = [replace(polyline, points_mm=((0, 0), (10, 0), (15, 0), (15, 10)))]
    assert canvas.selected_tangent_segments() == {}
    canvas.entities.clear()


def test_tangency_preview_avoids_internal_sketch_terms() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import tangent_preview_summary

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    summary = tangent_preview_summary(relation, (first, second), (first, second))
    assert "对象的坐标系" in summary
    assert "草图" not in summary


def test_separated_circles_default_to_nearest_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    for first_radius, second_radius, distance, expected in (
        (5.0, 2.0, 8.0, "external"),
        (5.0, 2.0, 3.4, "first_contains_second"),
        (2.0, 5.0, 3.4, "second_contains_first"),
    ):
        first = CircleEntity(uuid4().hex, (0, 0), first_radius)
        second = CircleEntity(uuid4().hex, (distance, 0), second_radius)
        sketches = (
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,)),
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,)),
        )
        dialog = CrossSketchTangencyDialog(
            sketches, (), selected_entity_ids=frozenset((first.entity_id, second.entity_id))
        )
        qtbot.addWidget(dialog)
        assert dialog.branch_combo.currentData() == expected


def test_mixed_local_tangency_stages_atomically(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    pairs = ((linked_circle.entity_id, line.entity_id),)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    saved_result, draft_result = app.prepare_mixed_draft_local_tangency(
        services, (saved,), draft, pairs, constraint
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        ((saved_result, draft_result),),
        session_identity=0,
        initial_cross_pairs=pairs,
        cross_pairs_by_step=(pairs,),
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    result = next(item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id)
    assert constraint in result.constraints
    loaded.bus.undo()
    result = next(item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id)
    assert not result.constraints
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_mixed_draft_tangency_from_ui_can_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.entities = [line, first_circle]
    canvas.pending_cross_tangencies = [(linked_circle.entity_id, line.entity_id)]
    canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    assert canvas.mixed_move is not None
    assert canvas.constraints[0].kind == "tangent"
    assert canvas.undo_last_operation()
    assert not canvas.constraints
    assert canvas.pending_cross_tangencies == [(linked_circle.entity_id, line.entity_id)]
    canvas.pending_cross_tangencies.clear()
    canvas.entities.clear()


def test_mixed_local_tangency_ui_commit_reopen_undo(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.entities = [line, first_circle]
    canvas.pending_cross_tangencies = [(linked_circle.entity_id, line.entity_id)]
    canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    draft_id = editor.draft_sketch_id
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    changed = services.kernel.sketches
    draft = next(item for item in changed if item.sketch_id == draft_id)
    assert draft.constraints[0].kind == "tangent"
    assert len(services.kernel.cross_sketch_tangencies) == 1
    path = tmp_path / "mixed-local-tangency.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == changed
    reopened.bus.undo()
    before = next(item for item in restored.kernel.sketches if item.sketch_id == draft_id)
    assert not before.constraints
    assert len(restored.kernel.cross_sketch_tangencies) == 1
    reopened.bus.redo()
    assert restored.kernel.sketches == changed
    assert len(restored.kernel.cross_sketch_tangencies) == 1


def test_unlinked_mixed_edit_then_local_tangency(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    saved_circle = CircleEntity(uuid4().hex, (30, 10), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    moved = replace(saved, entities=(replace(saved_circle, center_mm=(31, 10)),))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    saved_result, draft_result = app.prepare_mixed_draft_local_tangency(
        services, (moved,), draft, (), constraint
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved,), draft), (saved_result, draft_result)),
        session_identity=0,
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    result = next(item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id)
    assert constraint in result.constraints
    loaded.bus.undo()
    result = next(item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id)
    assert not result.constraints


def test_tampered_linked_tangency_is_rejected(qtbot: QtBot) -> None:
    import pytest

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, linked_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    params, _solved, _branches = app.prepare_cross_sketch_dimension(
        services, first.sketch_id, constraint
    )
    revisions = cast("list[dict[str, object]]", params["revisions"])
    revision = next(item for item in revisions if item["sketch_id"] == first.sketch_id)
    revision["entities"] = first.to_state_mapping()["entities"]
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, confirmed_by="local", version=38)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == original
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_concentric_circles_report_ambiguous_tangent_direction(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    first = CircleEntity(uuid4().hex, (0, 0), 5)
    second = CircleEntity(uuid4().hex, (0, 0), 2)
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,)),
    )
    dialog = CrossSketchTangencyDialog(
        sketches, (), selected_entity_ids=frozenset((first.entity_id, second.entity_id))
    )
    qtbot.addWidget(dialog)
    assert "同心" in dialog.status_label.text()
    assert dialog.branch_combo.currentIndex() == -1
    dialog.preview_button.click()
    assert "请选择相切分支" in dialog.status_label.text()


def test_drag_after_local_tangency_preserves_relation(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.fillet_curves import tangent_on_curves

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas.entities = [line, circle]
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    canvas.set_tool("选择元素")
    scale_attribute = "_scale"
    setattr(canvas, scale_attribute, 20.0)
    canvas.selected_entity_ids = {circle.entity_id}
    before = tuple(canvas.entities)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2)))
    QTest.mouseMove(canvas, canvas.local_to_screen((5, 3)), delay=20)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 3)))
    assert tuple(canvas.entities) != before, canvas.message
    new_line, new_circle = canvas.entities
    assert isinstance(new_line, LineEntity) and isinstance(new_circle, CircleEntity)
    assert tangent_on_curves(new_line, new_circle)
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == before
    canvas.constraints.clear()
    canvas.entities.clear()


def test_rectangle_edge_preselected_for_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    for entity in (rectangle, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    assert canvas.selected_tangent_segments()[rectangle.entity_id] == 1
    window.act_manage_tangencies.trigger()
    dialog_attribute = "_cross_tangency_dialog"
    dialog = cast("CrossSketchTangencyDialog | None", getattr(window, dialog_attribute))
    assert dialog is not None
    assert dialog.first_combo.currentData().entity_id == rectangle.entity_id
    assert dialog.first_combo.currentData().segment_index == 1
    dialog.reject()


def test_saved_rectangle_edge_tangency_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, circle))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    count = loaded.document.command_count
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    constraint = services.kernel.sketches[0].constraints[0]
    assert constraint.kind == "tangent"
    assert constraint.references[0].entity_id == rectangle.entity_id
    assert constraint.references[0].index == 1
    loaded.bus.undo()
    assert not services.kernel.sketches[0].constraints


def test_draft_rectangle_tangency_commit_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    canvas = editor.canvas
    canvas.entities = [rectangle, circle]
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    assert canvas.constraints[0].references[0].index == 1
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved = services.kernel.sketches
    path = tmp_path / "rectangle-tangent.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == saved
    assert saved[0].constraints[0].kind == "tangent"
    reopened.bus.undo()
    assert not restored.kernel.sketches


def test_rectangle_edge_cross_object_tangency_commit(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    for entity in (rectangle, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    cast("Callable[..., None]", getattr(canvas, select_method))((14, 5), additive=True)
    window.act_manage_tangencies.trigger()
    dialog_attribute = "_cross_tangency_dialog"
    dialog = cast("CrossSketchTangencyDialog | None", getattr(window, dialog_attribute))
    assert dialog is not None
    dialog.preview_button.click()
    qtbot.waitUntil(dialog.commit_button.isEnabled, timeout=10000)
    count = loaded.document.command_count
    dialog.commit_button.click()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    relation = services.kernel.cross_sketch_tangencies[0]
    assert relation.first.entity_id == rectangle.entity_id and relation.first.segment_index == 1
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies


def test_old_revision_version_rejects_new_tangency_operation(qtbot: QtBot) -> None:
    import pytest

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, linked_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    params, _solved, _branches = app.prepare_cross_sketch_dimension(
        services, first.sketch_id, constraint
    )
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, confirmed_by="local", version=37)
    assert loaded.document.command_count == count
    assert services.kernel.sketches == original


def test_mixed_tangency_reports_failed_staging(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.entities = [line, first_circle]
    canvas.pending_cross_tangencies = [(linked_circle.entity_id, line.entity_id)]
    canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}

    def fail_staging(*_args: object, **_kwargs: object) -> None:
        raise ValueError("暂存状态异常")

    monkeypatch.setattr(canvas, "apply_mixed_move", fail_staging)
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: "对象相切未暂存" in window.status_command.text(), timeout=10000)
    assert "暂存状态异常" in window.status_command.text()
    assert not canvas.constraints and canvas.mixed_move is None
    canvas.pending_cross_tangencies.clear()
    canvas.entities.clear()


def test_saved_tangent_drag_preserves_relation(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: "相切约束已写入历史" in window.status_command.text(), timeout=10000)
    before = services.kernel.sketches
    current_circle = cast("CircleEntity", before[0].entities[1])
    canvas.set_tool("选择元素")
    scale_attribute = "_scale"
    setattr(canvas, scale_attribute, 20.0)
    canvas.selected_entity_ids = {circle.entity_id}
    start = current_circle.center_mm
    finish = (start[0], start[1] + 1)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(start))
    QTest.mouseMove(canvas, canvas.local_to_screen(finish), delay=20)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(finish))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches
    assert result != before, canvas.message
    result_line, result_circle = result[0].entities
    assert isinstance(result_line, LineEntity) and isinstance(result_circle, CircleEntity)
    assert tangent_on_curves(result_line, result_circle)
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_dialog_same_record_explains_canvas_selection(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = CircleEntity(uuid4().hex, (5, 2), 2)
    other = CircleEntity(uuid4().hex, (20, 2), 2)
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,)),
    )
    dialog = CrossSketchTangencyDialog(sketches, ())
    qtbot.addWidget(dialog)
    dialog.first_combo.setCurrentIndex(0)
    dialog.second_combo.setCurrentIndex(1)
    dialog.preview_button.click()
    assert "画布中选择这两个对象" in dialog.status_label.text()


def test_saved_tangency_can_be_deleted_from_navigation(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: "相切约束已写入历史" in window.status_command.text(), timeout=10000)
    before = services.kernel.sketches
    constraint_id = before[0].constraints[0].constraint_id
    editor.navigator.selection_requested.emit(frozenset(), frozenset((constraint_id,)))
    assert constraint_id in canvas.selected_constraint_ids
    count = loaded.document.command_count
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].constraints
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_navigator_selection_does_not_reuse_old_edge_pick(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    canvas.entities = [polyline]
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    assert canvas.selected_tangent_segments() == {polyline.entity_id: 1}
    editor.navigator.selection_requested.emit(frozenset((polyline.entity_id,)), frozenset())
    assert canvas.selected_entity_ids == {polyline.entity_id}
    assert canvas.selected_tangent_segments() == {}
    canvas.entities.clear()


def test_separated_saved_objects_become_tangent(qtbot: QtBot) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (10, -5), 2)
    for entity in (line, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    before = services.kernel.sketches
    window.act_manage_tangencies.trigger()
    dialog_attribute = "_cross_tangency_dialog"
    dialog = cast("CrossSketchTangencyDialog | None", getattr(window, dialog_attribute))
    assert dialog is not None and dialog.branch_combo.currentData() == "line_right"
    dialog.preview_button.click()
    qtbot.waitUntil(dialog.commit_button.isEnabled, timeout=10000)
    dialog.commit_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches
    solved_line, solved_circle = result[0].entities[0], result[1].entities[0]
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert tangent_on_curves(solved_line, solved_circle)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    loaded.bus.undo()
    assert services.kernel.sketches == before
    assert not services.kernel.cross_sketch_tangencies


def test_tangency_dialog_translates_backend_errors(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dialog = CrossSketchTangencyDialog((first, second), ())
    qtbot.addWidget(dialog)
    dialog.complete_preview(relation, "跨草图相切求解失败", success=False)
    assert dialog.status_label.text() == "对象相切求解失败"
    dialog.submission_failed("跨草图相切提交失败")
    assert dialog.status_label.text() == "对象相切提交失败"


def test_delete_local_tangency_preserves_other_relation(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 2), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, linked_circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {line.entity_id, first_circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: "相切约束已写入历史" in window.status_command.text(), timeout=10000)
    before = services.kernel.sketches
    local_id = before[0].constraints[0].constraint_id
    editor.navigator.selection_requested.emit(frozenset(), frozenset((local_id,)))
    count = loaded.document.command_count
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].constraints
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_escape_discards_edge_selection(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    canvas.entities = [polyline]
    select_method = "_select_at"
    cast("Callable[..., None]", getattr(canvas, select_method))((10, 9), additive=False)
    assert canvas.selected_tangent_segments() == {polyline.entity_id: 1}
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.selected_entity_ids
    assert not canvas.selected_segment_indices
    canvas.entities.clear()


def test_linked_rectangle_edge_accepts_new_tangency(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 20))
    local_circle = CircleEntity(uuid4().hex, (14, 5), 2)
    linked_circle = CircleEntity(uuid4().hex, (12, 15), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, local_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 1),
        CrossSketchRef(second.sketch_id, linked_circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    original = services.kernel.sketches
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(rectangle.entity_id, "segment", 1),
            SketchGeometryReference(local_circle.entity_id, "geometry"),
        ),
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, constraint, session_identity=0
    )
    assert constraint in services.kernel.sketches[0].constraints
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches == original
