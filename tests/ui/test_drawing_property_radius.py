# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Radius properties reuse the drawing's constrained transform transaction."""

from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QInputDialog
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def edit_radius(editor: SketchEditorDialog) -> None:
    table = editor.properties_table
    labels = [table.item(i, 0) for i in range(table.rowCount())]
    row = next(i for i, item in enumerate(labels) if item is not None and item.text() == "半径")
    field = table.item(row, 1)
    assert field is not None
    table.itemDoubleClicked.emit(field)


def test_draft_circle_radius_property_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()
    table = editor.properties_table
    labels = [table.item(row, 0) for row in range(table.rowCount())]
    row = next(
        index for index, item in enumerate(labels) if item is not None and item.text() == "半径"
    )
    field = table.item(row, 1)
    assert field is not None
    previous_default = editor.canvas.scale_default_factor

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    table.itemDoubleClicked.emit(field)
    assert editor.canvas.entities[0] == CircleEntity(circle.entity_id, (2, 3), 8)
    assert editor.canvas.scale_default_factor == previous_default
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == circle


def test_draft_radius_refreshes_reference_dimension_and_undo(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = build_app(discoverers=())
    editor = SketchEditorDialog(constraint_preview=services.kernel.preview_sketch_constraint)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    editor.canvas.entities = [circle]
    editor.canvas.constraints = [dimension]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    updated = editor.canvas.entities[0]
    assert isinstance(updated, CircleEntity)
    assert updated.radius_mm == 8
    assert editor.canvas.constraints[0].value == 8
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [circle]
    assert editor.canvas.constraints == [dimension]


def test_draft_driving_radius_rejects_conflict(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = build_app(discoverers=())
    editor = SketchEditorDialog(constraint_preview=services.kernel.preview_sketch_constraint)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 5, "mm"
    )
    editor.canvas.entities = [circle]
    editor.canvas.constraints = [dimension]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    assert editor.canvas.entities == [circle]
    assert editor.canvas.constraints == [dimension]
    assert editor.status_label.text()


def test_saved_radius_refreshes_reference_dimension_and_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
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
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    changed = services.kernel.sketches[0]
    assert changed.entities[0] == CircleEntity(circle.entity_id, (2, 3), 8)
    assert changed.constraints[0].value == 8
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == circle
    assert services.kernel.sketches[0].constraints[0] == dimension


def test_radius_preserves_pending_tangency(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    editor.canvas.entities = [circle]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()
    relation = (uuid4().hex, circle.entity_id)
    editor.canvas.pending_cross_tangencies = [relation]

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    assert editor.canvas.entities == [circle]
    assert editor.canvas.pending_cross_tangencies == [relation]
    assert "暂存关联" in editor.status_label.text()


def test_radius_rejects_solver_branch_change(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.app import build_app
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import (
        SketchBranchChange,
        SketchConstraint,
        SketchConstraintSolveResult,
        SketchGeometryReference,
    )

    services = build_app(discoverers=())

    def preview(sketch: Sketch, candidate: SketchConstraint) -> SketchConstraintSolveResult:
        result = services.kernel.preview_sketch_constraint(sketch, candidate)
        return replace(
            result,
            branch_changes=(
                SketchBranchChange(
                    "tangency", (candidate.references[0].entity_id,), "切换相切分支"
                ),
            ),
        )

    editor = SketchEditorDialog(constraint_preview=preview)
    qtbot.addWidget(editor)
    editor.show()
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    editor.canvas.entities = [circle]
    editor.canvas.constraints = [dimension]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    assert editor.canvas.entities == [circle]
    assert editor.canvas.constraints == [dimension]
    assert "分支" in editor.status_label.text()


def test_draft_arc_radius_refreshes_reference_dimension(qtbot: QtBot) -> None:
    from mycad.app import build_app
    from mycad.core.sketch import ArcEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = build_app(discoverers=())
    editor = SketchEditorDialog(constraint_preview=services.kernel.preview_sketch_constraint)
    qtbot.addWidget(editor)
    editor.show()
    arc = ArcEntity(uuid4().hex, (2, 3), 5, 20, 90)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    editor.canvas.entities = [arc]
    editor.canvas.constraints = [dimension]
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {arc.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    updated = editor.canvas.entities[0]
    assert isinstance(updated, ArcEntity)
    assert updated.radius_mm == 8
    assert editor.canvas.constraints[0].value == 8
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [arc]
    assert editor.canvas.constraints == [dimension]


def test_saved_arc_radius_updates_reference_and_replays(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
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
    arc = ArcEntity(uuid4().hex, (2, 3), 5, 20, 90)
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {arc.entity_id}
    editor.canvas.changed.emit()

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    revised = services.kernel.sketches[0]
    assert revised.entities[0] == ArcEntity(arc.entity_id, (2, 3), 8, 20, 90)
    assert revised.constraints[0].value == 8
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == arc
    assert services.kernel.sketches[0].constraints[0] == dimension
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0] == revised


def test_saved_driving_radius_conflict_preserves_document(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
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
    circle = CircleEntity(uuid4().hex, (2, 3), 5)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 5, "mm"
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    editor.canvas.changed.emit()
    before = tuple(loaded.document.commands)

    def enter_radius() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("8")
        dialog.accept()

    QTimer.singleShot(100, enter_radius)
    edit_radius(editor)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches[0].entities[0] == circle
    assert services.kernel.sketches[0].constraints[0] == dimension
    assert "约束" in editor.status_label.text()
