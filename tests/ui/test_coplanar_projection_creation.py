# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""View-axis dimensions persist correctly on rotated sketch sources."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    project_coplanar_entity,
    validate_tangency_component,
)
from mycad.core.persistence import save_document
from mycad.core.sketch import ArcEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize(
    ("mode", "axis", "value"),
    [
        ("horizontal", "horizontal", 20),
        ("vertical", "vertical", 10),
        ("smart", "horizontal", 20),
        ("ordinate", "ordinate_x", 20),
    ],
)
def test_create_view_projection_on_rotated_sketch(
    qtbot: QtBot, tmp_path: Path, opposite: bool, mode: str, axis: str, value: int
) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (0, 0), (20, 10)), WorkPlaneFrame.xy(), frame
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    sketch = Sketch(uuid4().hex, frame, (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.archive_version == 8
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons[mode].click()
    canvas = editor.canvas
    points = ((0, 0), (20, 10), (10, 20)) if mode == "ordinate" else ((10, 5), (10, 20))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    assert loaded.document.archive_version == 8
    dimension = services.kernel.sketches[0].constraints[0]
    assert dimension.axis == axis and dimension.value == pytest.approx(value)
    assert dimension.projection_axis is not None
    direction = dimension.projection_axis
    world = tuple(direction[0] * frame.u_axis[i] + direction[1] * frame.v_axis[i] for i in range(3))
    assert world == pytest.approx((0, 1, 0) if axis == "vertical" else (1, 0, 0))
    path = tmp_path / "view-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches[0].constraints == ()
    loaded.bus.redo()
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("mode", ["horizontal", "vertical", "ordinate"])
def test_drive_view_projection_on_rotated_sketch(qtbot: QtBot, opposite: bool, mode: str) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (0, 0), (20, 10)), WorkPlaneFrame.xy(), frame
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    sketch = Sketch(uuid4().hex, frame, (line,))
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
    editor.dimensions.buttons[mode].click()
    canvas = editor.canvas
    points = ((20, 10), (0, 0), (10, 20)) if mode == "ordinate" else ((10, 5), (10, 20))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    target = -15 if mode == "ordinate" else 15 if mode == "horizontal" else 8
    editor.dimensions.value_editor.setValue(target)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", preview.message if preview else ""
    assert loaded.document.archive_version == 8 and canvas.dimension_preview is not None
    editor.dimensions.apply_button.click()
    if preview.branch_changes:
        editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    result = services.kernel.sketches[0]
    dimension = result.constraints[0]
    assert dimension.value == pytest.approx(target)
    changed = result.entities[0]
    assert isinstance(changed, LineEntity)
    start, end = frame.local_to_world(changed.start_mm), frame.local_to_world(changed.end_mm)
    projected = (end[1] - start[1]) if mode == "vertical" else (end[0] - start[0])
    if mode == "ordinate":
        projected = -projected
    assert projected == pytest.approx(target, abs=1e-6)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_shift_cycles_view_axes_on_rotated_sketch(qtbot: QtBot) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-q, q, 0), (0, 0, 1))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (0, 0), (20, 10)), WorkPlaneFrame.xy(), frame
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, (line,)), session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["aligned"].click()
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert editor.dimensions.candidate is not None
    QTest.keyClick(canvas, Qt.Key.Key_Shift)
    candidate = editor.dimensions.candidate
    assert candidate is not None and candidate.axis == "horizontal"
    assert candidate.value == pytest.approx(20)
    QTest.keyClick(canvas, Qt.Key.Key_Shift)
    candidate = editor.dimensions.candidate
    assert candidate is not None and candidate.axis == "vertical"
    assert candidate.value == pytest.approx(10)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 20)))
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].axis == "vertical"


@pytest.mark.parametrize("mode, expected", [("continue", 20), ("baseline", 40)])
@pytest.mark.parametrize("reopen", [False, True])
def test_chain_dimensions_keep_rotated_source_projection(
    qtbot: QtBot, tmp_path: Path, mode: str, expected: int, reopen: bool
) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (q, -q, 0), (0, 0, -1))
    lines = tuple(
        project_coplanar_entity(LineEntity(uuid4().hex, start, end), WorkPlaneFrame.xy(), frame)
        for start, end in (((0, 0), (20, 0)), ((20, 0), (40, 20)))
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, Sketch(uuid4().hex, frame, lines), session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    canvas = editor.canvas
    for point in ((0, 0), (20, 0), (10, -10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(
        lambda: unit is not None and not unit.is_busy and len(loaded.document.commands) == 2,
        timeout=10000,
    )
    first = services.kernel.sketches[0].constraints[0]
    if reopen:
        path = tmp_path / "chain.my2d"
        save_document(loaded.document, path)
        window.close()
        services = app.build_app(discoverers=())
        loaded = app.open_app_document(services, path)
        window = MainWindow(services=services)
        qtbot.addWidget(window)
        window.bind_document(loaded)
        window.resize(1400, 900)
        window.show()
        window.workspace_tabs.activate("sketch")
        editor, unit = window.active_sketch_dialog(), window.execution_unit
        assert editor is not None and unit is not None
        canvas = editor.canvas
        editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons[mode].click()
    if reopen:
        shown = next(
            c for c in canvas.visible_dimensions() if c.constraint_id == first.constraint_id
        )
        layout = canvas.dimension_layout(shown, canvas.dimension_entities())
        assert layout is not None
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
        assert editor.dimensions.references
    for point in ((40, 20), (30, -20)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 3, timeout=10000)
    second = services.kernel.sketches[0].constraints[-1]
    assert second.value == pytest.approx(expected)
    assert second.projection_axis == first.projection_axis
    assert second.references[0] == first.references[-1 if mode == "continue" else 0]


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("unrelated_fixed", [False, True])
@pytest.mark.parametrize("extra_mode", ["none", "direct", "chain"])
@pytest.mark.parametrize("arc_partner", [False, True])
def test_driving_view_projection_with_cross_sketch_tangency(
    qtbot: QtBot,
    tmp_path: Path,
    opposite: bool,
    unrelated_fixed: bool,
    extra_mode: str,
    arc_partner: bool,
) -> None:
    from mycad.core.sketch import CircleEntity

    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = (
        ArcEntity(uuid4().hex, (0, 2), 2, 180, 180)
        if arc_partner
        else CircleEntity(uuid4().hex, (0, 2), 2)
    )
    first = Sketch(uuid4().hex, frame, (line,))
    other = LineEntity(uuid4().hex, (30, 30), (40, 30), construction=True)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(other.entity_id, "start"),)
    )
    second = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (circle, other) if unrelated_fixed else (circle,),
        (fixed,) if unrelated_fixed else (),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    extra_circle = CircleEntity(
        uuid4().hex,
        (0, -2 if arc_partner else 6) if extra_mode == "chain" else (-5, 2),
        2,
    )
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (extra_circle,))
    for sketch in (first, second, third) if extra_mode != "none" else (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right" if opposite else "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    if extra_mode != "none":
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(
                second.sketch_id if extra_mode == "chain" else first.sketch_id,
                circle.entity_id if extra_mode == "chain" else line.entity_id,
            ),
            CrossSketchRef(third.sketch_id, extra_circle.entity_id),
            "external" if extra_mode == "chain" else "line_right" if opposite else "line_left",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["horizontal"].click()
    canvas = editor.canvas
    for point in ((6, 0), (6, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    editor.dimensions.value_editor.setValue(15)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", preview.message if preview else ""
    count = len(loaded.document.commands)
    editor.dimensions.apply_button.click()
    if preview.branch_changes:
        editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 31
    after = services.kernel.sketches
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    path = tmp_path / "cross-view-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches == after


def test_driving_projection_preserves_fixed_endpoint_with_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    q = math.sqrt(0.5)
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (q, -q, 0), (0, 0, -1))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    assert isinstance(line, LineEntity)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    first = Sketch(uuid4().hex, frame, (line,), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["horizontal"].click()
    canvas = editor.canvas
    for point in ((6, 0), (6, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    editor.dimensions.value_editor.setValue(15)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", preview.message if preview else ""
    count = len(loaded.document.commands)
    editor.dimensions.apply_button.click()
    if preview.branch_changes:
        editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    after = services.kernel.sketches
    result = next(sketch for sketch in after if sketch.sketch_id == first.sketch_id).entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx(line.end_mm)
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before
