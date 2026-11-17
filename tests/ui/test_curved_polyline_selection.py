# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Selection follows curved polyline segments rather than their chords."""

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import PolylineEntity
from mycad.ui.sketch_editor import SketchEditorDialog
from mycad.ui.sketch_selection import entity_in_selection_box


def test_selection_box_uses_exact_polyline_arc_bounds_and_crossings() -> None:
    path = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    assert entity_in_selection_box(path, (0.9, -1.1), (1.1, -0.9), crossing=True)
    assert not entity_in_selection_box(path, (-0.1, -0.1), (2.1, 2.1), crossing=False)
    assert entity_in_selection_box(path, (-0.1, -1.1), (2.1, 2.1), crossing=False)


def test_canvas_selects_arc_instead_of_polyline_chord(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)), bulges=(1, 0))
    assert canvas.replace_draft_entities((path,))
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -10)))
    assert canvas.selected_entity_ids == {path.entity_id}


def test_trim_line_uses_curved_polyline_as_boundary(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (-10, 4), (10, 4))
    cutter = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    assert canvas.replace_draft_entities((target, cutter))
    assert canvas.set_tool("修剪")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 4)))
    assert len(canvas.entities) == 3, canvas.message
    first, second = canvas.entities[:2]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == pytest.approx((-3, 4))
    assert second.start_mm == pytest.approx((3, 4))
    assert canvas.entities[2] == cutter
    assert canvas.undo_last_operation() and canvas.entities == [target, cutter]


def test_split_open_curved_polyline_keeps_arc_geometry_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (10, 0)), bulges=(-1, 0))
    boundary = LineEntity(uuid4().hex, (0, 3), (0, 7))
    assert canvas.replace_draft_entities((path, boundary))
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("分割")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-2, 4.58)))
    assert len(canvas.entities) == 3, canvas.message
    first, second = canvas.entities[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((0, 5))
    assert second.points_mm[0] == pytest.approx((0, 5))
    assert first.bulges and second.bulges
    assert canvas.undo_last_operation() and canvas.entities == [path, boundary]


def test_trim_open_curved_polyline_keeps_arc_geometry_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (10, 0)), bulges=(-1, 0))
    boundaries = (
        LineEntity(uuid4().hex, (-3, 2), (-3, 6)),
        LineEntity(uuid4().hex, (3, 2), (3, 6)),
    )
    assert canvas.replace_draft_entities((path, *boundaries))
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("修剪")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    assert len(canvas.entities) == 4, canvas.message
    first, second = canvas.entities[:2]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((-3, 4))
    assert second.points_mm[0] == pytest.approx((3, 4))
    assert first.bulges and second.bulges
    assert canvas.undo_last_operation() and canvas.entities == [path, *boundaries]


def test_quick_trim_curved_polyline_unintersected_segment_preserves_others(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(
        uuid4().hex, ((-20, 0), (-10, 0), (0, 0), (10, 0), (20, 0)), bulges=(0, -1, -1, 0)
    )
    boundary = LineEntity(uuid4().hex, (-5, 3), (-5, 7))
    assert canvas.replace_draft_entities((path, boundary))
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("修剪")
    position = canvas.local_to_screen((5, 5))
    QTest.mouseMove(canvas, position)
    assert len(canvas.previewed_line_edit_entities) == 2
    preview = canvas.previewed_line_edit_entities[0]
    assert isinstance(preview, PolylineEntity)
    assert preview.points_mm == path.points_mm[:3]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=position)
    assert len(canvas.entities) == 3, canvas.message
    result, suffix = canvas.entities[:2]
    assert isinstance(result, PolylineEntity)
    assert result.points_mm == path.points_mm[:3]
    assert result.bulges == path.bulges[:2]
    assert isinstance(suffix, PolylineEntity)
    assert suffix.points_mm == path.points_mm[3:]
    assert not suffix.bulges
    assert canvas.entities[2] == boundary
    assert canvas.undo_last_operation() and canvas.entities == [path, boundary]


def test_quick_trim_saved_curved_polyline_segment_and_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    path = PolylineEntity(
        uuid4().hex, ((-20, 0), (-10, 0), (0, 0), (10, 0), (20, 0)), bulges=(0, -1, -1, 0)
    )
    boundary = LineEntity(uuid4().hex, (-5, 3), (-5, 7))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path, boundary)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.set_tool("修剪")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 5))
    )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    entities = services.kernel.sketches[0].entities
    assert len(entities) == 3
    prefix, suffix = entities[:2]
    assert isinstance(prefix, PolylineEntity) and isinstance(suffix, PolylineEntity)
    assert prefix.points_mm == path.points_mm[:3]
    assert suffix.points_mm == path.points_mm[3:]
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert services.kernel.sketches[0].entities == (path, boundary)


@pytest.mark.parametrize("tool", ("修剪", "分割"))
def test_edit_closed_curved_polyline_and_undo(qtbot: QtBot, tool: str) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(
        uuid4().hex,
        ((-5, 0), (5, 0), (5, -5), (-5, -5)),
        True,
        bulges=(-1, 0, 0, 0),
    )
    boundaries = (
        LineEntity(uuid4().hex, (-3, 2), (-3, 6)),
        LineEntity(uuid4().hex, (3, 2), (3, 6)),
    )
    assert canvas.replace_draft_entities((path, *boundaries))
    editor.snap_check.setChecked(False)
    assert canvas.set_tool(tool)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    fragments = canvas.entities[:-2]
    assert len(fragments) == (1 if tool == "修剪" else 2), canvas.message
    assert all(isinstance(entity, PolylineEntity) and entity.bulges for entity in fragments)
    assert canvas.undo_last_operation() and canvas.entities == [path, *boundaries]


def test_extend_curved_polyline_arc_and_undo(qtbot: QtBot) -> None:
    import math

    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((-5, 0), (0, 5)), bulges=(-math.tan(math.pi / 8),))
    boundary = LineEntity(uuid4().hex, (5, -2), (5, 2))
    assert canvas.replace_draft_entities((path, boundary))
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("延伸")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    assert isinstance(canvas.entities[0], PolylineEntity), canvas.message
    assert canvas.entities[0].points_mm[-1] == pytest.approx((5, 0))
    assert canvas.entities[0].bulges == pytest.approx((-1,))
    assert canvas.undo_last_operation() and canvas.entities == [path, boundary]


def test_offset_tangent_curved_polyline_and_undo(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(
        uuid4().hex, ((-5, 0), (0, 5), (5, 5)), bulges=(-math.tan(math.pi / 8), 0)
    )
    assert canvas.replace_draft_entities((path,))
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-3.54, 3.54)))
    editor.offset_distance_field.setValue(1)
    editor.transform_buttons["offset"].click()
    assert len(canvas.entities) == 2, canvas.message
    offset = canvas.entities[1]
    assert isinstance(offset, PolylineEntity)
    assert offset.points_mm[0] == pytest.approx((-6, 0))
    assert offset.bulges == pytest.approx(path.bulges)
    assert canvas.undo_last_operation() and canvas.entities == [path]


def test_offset_curved_polyline_through_point_command(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(
        uuid4().hex, ((-5, 0), (0, 5), (5, 5)), bulges=(-math.tan(math.pi / 8), 0)
    )
    assert canvas.replace_draft_entities((path,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-3.54, 3.54)))
    coordinate = 6 / math.sqrt(2)
    command.setText(f"{-coordinate},{coordinate}")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2, canvas.message
    offset = canvas.entities[1]
    assert isinstance(offset, PolylineEntity)
    assert offset.points_mm[0] == pytest.approx((-6, 0))
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert canvas.undo_last_operation() and canvas.entities == [path]


def test_part_sketch_workbench_displays_curved_polyline(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.part_sketch_workbench import PartSketchWorkbench
    from mycad.ui.viewport import GLViewport

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    entity = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    calls: list[object] = []

    def capture(curves: object, **_kwargs: object) -> None:
        calls.append(curves)

    monkeypatch.setattr(view, "set_draft_sketch_curves", capture)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    assert calls
    curves = cast("tuple[tuple[tuple[float, float, float], ...], ...]", calls[-1])
    points = curves[0]
    assert min(point[1] for point in points) == pytest.approx(-10)


def test_part_sketch_curved_polyline_move_preserves_bulges_and_replays(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_edit import move_entities
    from mycad.ui.part_sketch_workbench import PartSketchWorkbench
    from mycad.ui.viewport import GLViewport

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    entity = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    moved = move_entities(sketch.entities, (entity.entity_id,), (3, 4))
    task.session.replace_sketch(replace(sketch, entities=moved))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].entities == moved
    assert loaded.document.commands[-1].version == 3
    loaded.bus.undo()
    assert services.kernel.sketches[0] == sketch


def test_curved_polyline_snap_uses_arc_midpoint_not_chord(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)), bulges=(1, 0))
    assert canvas.replace_draft_entities((path,))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((30, -10))
    canvas.add_coordinate_point((10.1, -10.1))
    result = canvas.entities[-1]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((10, -10))
    assert canvas.current_snap_kind == "中点"


def test_fillet_polyline_trim_replaces_draft_as_one_entity(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert len(canvas.entities) == 1
    rounded = canvas.entities[0]
    assert isinstance(rounded, PolylineEntity)
    assert rounded.entity_id == source.entity_id and rounded.bulges
    assert canvas.undo_last_operation() and canvas.entities == [source]
    assert canvas.redo_last_operation() and canvas.entities == [rounded]


def test_polyline_fillet_rejects_existing_user_constraint_atomically(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    constraint = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(source.entity_id, "segment", 0),)
    )
    canvas.constraints = [constraint]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert canvas.entities == [source] and canvas.constraints == [constraint]
    assert "约束" in canvas.message


@pytest.mark.parametrize("vertex_index", [0, 2])
def test_polyline_fillet_preserves_unchanged_fixed_endpoint(
    qtbot: QtBot, tmp_path: Path, vertex_index: int
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", vertex_index),)
    )
    canvas.constraints = [constraint]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    rounded = canvas.entities[0]
    assert isinstance(rounded, PolylineEntity) and rounded != source, canvas.message
    fixed = canvas.constraints[0]
    index = fixed.references[0].index
    assert index is not None and rounded.points_mm[index] == source.points_mm[vertex_index]
    assert fixed.constraint_id == constraint.constraint_id
    assert canvas.undo_last_operation()
    assert canvas.entities == [source] and canvas.constraints == [constraint]
    assert canvas.redo_last_operation()
    assert canvas.entities == [rounded] and canvas.constraints == [fixed]
    editor.finish_sketch()
    assert editor.result_sketch is not None
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, editor.result_sketch, session_identity=1)
    saved = services.kernel.sketches
    path = tmp_path / f"fillet-fixed-{vertex_index}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == saved
    reopened.bus.undo()
    assert not services.kernel.sketches
    reopened.bus.redo()
    assert services.kernel.sketches == saved


def test_polyline_fillet_rebinds_unchanged_constrained_segment(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (10, 20), (10, 30)))
    assert canvas.replace_draft_entities((source,))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(source.entity_id, "segment", 3),),
        10,
        "mm",
    )
    canvas.constraints = [constraint]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result != source, canvas.message
    rebound = canvas.constraints[0]
    index = rebound.references[0].index
    assert index is not None and index != 3
    assert result.points_mm[index : index + 2] == source.points_mm[3:5]
    assert rebound.value == 10
    assert canvas.undo_last_operation() and canvas.constraints == [constraint]
    assert canvas.redo_last_operation() and canvas.constraints == [rebound]


def test_unchanged_user_polyline_reference_rejects_ambiguous_vertex(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 0), (0, 10)))
    assert canvas.replace_draft_entities((source,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 0),)
    )
    canvas.constraints = [constraint]
    changed = PolylineEntity(source.entity_id, ((0, 0), (5, 0), (10, 0), (10, 10), (0, 0), (0, 10)))
    assert not canvas.replace_draft_entities(
        (changed,), preserve_unchanged_polyline_references=True
    )
    assert canvas.entities == [source] and canvas.constraints == [constraint]
    assert "不唯一" in canvas.message


@pytest.mark.parametrize("vertex_index", [0, 1, 2])
def test_saved_polyline_fillet_preserves_fixed_start_and_replays(
    qtbot: QtBot, tmp_path: Path, vertex_index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QSettings

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
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
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", vertex_index),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "T", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before_fillet_count = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    if vertex_index == 1:
        assert "约束" in editor.canvas.message
        assert (
            len(loaded.document.commands) == before_fillet_count
            and services.kernel.sketches == before
        )
        return
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before_fillet_count + 1 and not unit.is_busy,
        timeout=10000,
    )
    if vertex_index == 2:
        assert loaded.document.commands[-1].id == "sketch.revise"
        assert loaded.document.commands[-1].version == 6
    after = services.kernel.sketches
    rounded = after[0].entities[0]
    assert isinstance(rounded, PolylineEntity) and rounded.points_mm[0] == source.points_mm[0]
    fixed = after[0].constraints[0]
    index = fixed.references[0].index
    assert index is not None and rounded.points_mm[index] == source.points_mm[vertex_index]
    assert fixed.constraint_id == constraint.constraint_id
    save_path = tmp_path / "saved-fixed-polyline.my2d"
    save_document(loaded.document, save_path)
    reopened = app.open_app_document(services, save_path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("command_undo", [False, True])
def test_saved_polyline_fillet_rebinds_user_length_and_cross_tangency(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command_undo: bool
) -> None:
    from PySide6.QtCore import QSettings

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
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
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (10, 20), (10, 30)))
    length = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(source.entity_id, "segment", 3),), 10, "mm"
    )
    circle = CircleEntity(uuid4().hex, (12, 25), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (length,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 3),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, before_relation = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    count = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "T", "R", "2", *(("M",) if command_undo else ()), "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == count + 1 and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.sketch.revise"
    assert loaded.document.commands[-1].version == 32
    after, after_relation = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert after[0].constraints[0].references[0].index == 4
    assert after_relation[0].first.segment_index == 4
    if command_undo:
        qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
        for value in ("R", "3", "U"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and services.kernel.sketches == before
                and services.kernel.cross_sketch_tangencies == before_relation
            ),
            timeout=10000,
        )
        assert services.kernel.drawing_fillet_radius == 3
        command.clear()
        QTest.keyClick(command, Qt.Key.Key_Return)
        window.request_undo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and services.kernel.sketches == after
                and services.kernel.cross_sketch_tangencies == after_relation
            ),
            timeout=10000,
        )
        window.request_redo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and services.kernel.sketches == before
                and services.kernel.cross_sketch_tangencies == before_relation
            ),
            timeout=10000,
        )
        path = tmp_path / "saved-polyline-cross-command-undo.my2d"
        save_document(loaded.document, path)
        restored = app.build_app(discoverers=[])
        app.open_app_document(restored, path)
        assert restored.kernel.sketches == before
        assert restored.kernel.cross_sketch_tangencies == before_relation
        assert restored.kernel.drawing_fillet_radius == 3
        return
    save_path = tmp_path / "saved-polyline-user-and-cross.my2d"
    save_document(loaded.document, save_path)
    reopened = app.open_app_document(services, save_path)
    assert (
        services.kernel.sketches == after
        and services.kernel.cross_sketch_tangencies == after_relation
    )
    reopened.bus.undo()
    assert (
        services.kernel.sketches == before
        and services.kernel.cross_sketch_tangencies == before_relation
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after
        and services.kernel.cross_sketch_tangencies == after_relation
    )


@pytest.mark.parametrize("with_tangency", [False, True])
def test_saved_polyline_fillet_rebinds_user_constraint_with_existing_draft(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_tangency: bool
) -> None:
    from PySide6.QtCore import QSettings

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
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
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (10, 20), (10, 30)))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 4),)
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (fixed,))
    app.commit_new_sketch(services, loaded, original, session_identity=0)
    if with_tangency:
        circle = CircleEntity(uuid4().hex, (12, 25), 2)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(original.sketch_id, source.entity_id, 3),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "line_right",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    draft = LineEntity(uuid4().hex, (30, 0), (40, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    before = services.kernel.sketches
    before_relations = services.kernel.cross_sketch_tangencies
    count = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "T", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert services.kernel.sketches == before and len(loaded.document.commands) == count
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) > count, timeout=10000
    )
    after = services.kernel.sketches
    after_relations = services.kernel.cross_sketch_tangencies
    revised = next(sketch for sketch in after if sketch.sketch_id == original.sketch_id)
    assert revised.constraints[0].references[0].index == 5
    if with_tangency:
        assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 4
    assert any(
        command.id == "drawing.sketch.revise" and command.version == 32
        for command in loaded.document.commands
    )
    save_path = tmp_path / "mixed-user-rebind.my2d"
    save_document(loaded.document, save_path)
    reopened = app.open_app_document(services, save_path)
    assert services.kernel.sketches == after
    assert services.kernel.cross_sketch_tangencies == after_relations
    reopened.bus.undo()
    assert next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == original.sketch_id
    ) == next(sketch for sketch in before if sketch.sketch_id == original.sketch_id)
    assert services.kernel.cross_sketch_tangencies == before_relations
    reopened.bus.redo()
    assert services.kernel.sketches == after
    assert services.kernel.cross_sketch_tangencies == after_relations


@pytest.mark.parametrize("with_draft", [False, True])
@pytest.mark.parametrize("relation_kind", ["tangent", "coincident"])
def test_saved_polyline_fillet_preserves_inferred_tangency_and_user_fixed_endpoint(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_draft: bool,
    relation_kind: str,
) -> None:
    from PySide6.QtCore import QSettings

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
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
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (10, 20), (10, 30)))
    other = (
        CircleEntity(uuid4().hex, (12, 25), 2)
        if relation_kind == "tangent"
        else LineEntity(uuid4().hex, (10, 30), (20, 30))
    )
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent" if relation_kind == "tangent" else "coincident",
        (
            SketchGeometryReference(
                source.entity_id,
                "segment" if relation_kind == "tangent" else "vertex",
                3 if relation_kind == "tangent" else 4,
            ),
            SketchGeometryReference(
                other.entity_id, "geometry" if relation_kind == "tangent" else "start"
            ),
        ),
        source="inferred",
    )
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 4),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, other), (tangent, fixed))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    if with_draft:
        assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (30, 0), (40, 0)),))
    before = services.kernel.sketches
    count = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "T", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if with_draft:
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        editor.finish_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) > count, editor.status_label.text()
    revised = next(item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id)
    assert revised.constraints[0].references[0].index == (4 if relation_kind == "tangent" else 5)
    assert revised.constraints[1].references[0].index == 5
    after = services.kernel.sketches
    path = tmp_path / "saved-inferred-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert (
        next(item for item in services.kernel.sketches if item.sketch_id == sketch.sketch_id)
        == before[0]
    )
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_polyline_fillet_can_change_radius_and_remove_existing_arcs(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for radius in ("2", "1", "0"):
        for value in ("FILLET", "R", radius, "P"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 0)))
        assert len(canvas.entities) == 1
        result = canvas.entities[0]
        assert isinstance(result, PolylineEntity) and result.entity_id == source.entity_id
        if radius == "0":
            assert not result.bulges
            for actual, expected in zip(result.points_mm, source.points_mm, strict=True):
                assert actual == pytest.approx(expected)
        else:
            assert result.bulges
    assert canvas.undo_last_operation()
    assert isinstance(canvas.entities[0], PolylineEntity) and canvas.entities[0].bulges


def test_polyline_fillet_multiple_supports_command_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    second = PolylineEntity(uuid4().hex, ((20, 0), (30, 0), (30, 10)))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 0)))
    assert all(isinstance(entity, PolylineEntity) and entity.bulges for entity in canvas.entities)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], PolylineEntity) and canvas.entities[0].bulges
    assert canvas.entities[1] == second


def test_polyline_fillet_rounds_existing_line_arc_corner(qtbot: QtBot) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id == source.entity_id
    segments = polyline_curve_segments(
        result.points_mm, result.bulges, result.closed, result.entity_id
    )
    assert len(segments) == 3
    assert sum(isinstance(segment, ArcEntity) for segment in segments) == 2
    for value in ("FILLET", "R", "0.5", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    revised = canvas.entities[0]
    assert isinstance(revised, PolylineEntity) and revised.entity_id == source.entity_id
    revised_segments = polyline_curve_segments(
        revised.points_mm, revised.bulges, revised.closed, revised.entity_id
    )
    radii = sorted(
        segment.radius_mm for segment in revised_segments if isinstance(segment, ArcEntity)
    )
    assert radii == pytest.approx([0.5, 5.0])
    assert canvas.undo_last_operation() and canvas.entities == [result]
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_fillet_polyline_trim_saved_replays_as_one_edit(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = services.kernel.sketches
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.bulges, editor.status_label.text()
    assert result.entity_id == source.entity_id
    assert editor.canvas.tool == "选择元素" and not editor.canvas.circle_fillet_polyline_pending
    path = tmp_path / "rounded.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == (result,)
    reopened_services = app.build_app(discoverers=[])
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (result,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == before


def test_fillet_saved_polyline_with_draft_preserves_mixed_history(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    extra = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert editor.canvas.replace_draft_entities((extra,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    source_sketch = next(
        s
        for s in services.kernel.sketches
        if any(e.entity_id == source.entity_id for e in s.entities)
    )
    rounded = source_sketch.entities[0]
    assert isinstance(rounded, PolylineEntity) and rounded.bulges
    loaded.bus.undo()
    assert any(source in sketch.entities for sketch in services.kernel.sketches)
    loaded.bus.redo()
    assert any(rounded in sketch.entities for sketch in services.kernel.sketches)


def test_saved_polyline_can_refillet_then_remove_arcs(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    command = editor.drawing_command_bar.input
    for radius in ("2", "1", "0"):
        for value in ("FILLET", "R", radius, "P"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((4, 0))
        )
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        result = services.kernel.sketches[0].entities[0]
        assert isinstance(result, PolylineEntity)
        assert bool(result.bulges) == (radius != "0"), editor.status_label.text()
    loaded.bus.undo()
    previous = services.kernel.sketches[0].entities[0]
    assert isinstance(previous, PolylineEntity) and previous.bulges
