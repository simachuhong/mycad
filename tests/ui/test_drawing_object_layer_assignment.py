# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Moving selected drawing entities to the current layer."""

from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.main_window import MainWindow
from mycad.ui.quick_select import QuickSelectDialog


@pytest.mark.parametrize("with_dimensions", [False, True])
def test_qselect_multiple_move_to_current_layer(qtbot: QtBot, with_dimensions: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    lines = (
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        LineEntity(uuid4().hex, (0, 5), (20, 5)),
    )
    assert editor.canvas.replace_draft_entities(lines)
    if with_dimensions:
        editor.canvas.constraints = [
            SketchConstraint(
                uuid4().hex,
                "length",
                (SketchGeometryReference(line.entity_id, "geometry"),),
                value,
                "mm",
                layer_name="0",
            )
            for line, value in zip(lines, (10, 20), strict=True)
        ]

    def accept_all() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.accept()

    QTimer.singleShot(100, accept_all)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.selected_entity_ids == {line.entity_id for line in lines}
    editor.layer_combo.setCurrentText("目标")
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(line.layer_name == "目标" for line in editor.canvas.entities), (
        editor.status_label.text()
    )
    assert all(item.layer_name == "目标" for item in editor.canvas.constraints)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(line.layer_name == "0" for line in editor.canvas.entities)
    assert all(item.layer_name == "0" for item in editor.canvas.constraints)


@pytest.mark.parametrize("with_image", [False, True])
def test_qselect_mixed_saved_draft_dimensions_and_image_move_atomically(
    qtbot: QtBot, with_image: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
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
    saved_line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(saved_line.entity_id, "geometry"),),
        10,
        "mm",
        layer_name="0",
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,), (saved_dim,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    if with_image:
        image = QImage(4, 2, QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        QApplication.clipboard().setImage(image)
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    draft_line = LineEntity(uuid4().hex, (0, 5), (20, 5))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(draft_line.entity_id, "geometry"),),
        20,
        "mm",
        layer_name="0",
    )
    editor.canvas.constraints = [draft_dim]

    def accept_all() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.accept()

    QTimer.singleShot(100, accept_all)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.layer_combo.setCurrentText("目标")
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "目标", editor.status_label.text()
    assert services.kernel.sketches[0].constraints[0].layer_name == "目标"
    assert editor.canvas.entities[0].layer_name == "目标"
    assert editor.canvas.constraints[0].layer_name == "目标"
    if with_image:
        assert services.kernel.drawing_rasters[0].layer_name == "目标"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "0"
    assert services.kernel.sketches[0].constraints[0].layer_name == "0"
    assert editor.canvas.entities[0].layer_name == "0"
    assert editor.canvas.constraints[0].layer_name == "0"
    if with_image:
        assert services.kernel.drawing_rasters[0].layer_name == "0"
    window.hide()
    editor.reject()


@pytest.mark.parametrize("entry", ["layer_bar", "properties"])
def test_draft_dimension_layer_change_waits_for_worker(qtbot: QtBot, entry: str) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
    )
    editor.canvas.constraints = [dimension]
    editor.layer_combo.setCurrentText("目标")
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    entered, release = Event(), Event()

    def blocking_work() -> None:
        entered.set()
        assert release.wait(10)

    assert unit.submit(blocking_work, operation="test-layer-busy", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        if entry == "layer_bar":
            editor.assign_selection_layer_button.clicked.emit()
        else:
            combo = editor.property_layer_combo
            assert combo is not None
            combo.activated.emit(combo.findData("目标"))
        assert editor.canvas.constraints == [dimension]
        assert "忙" in editor.status_label.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    editor.assign_selection_layer_button.click()
    assert editor.canvas.constraints[0].layer_name == "目标"


@pytest.mark.parametrize("saved", [False, True])
def test_current_layer_button_moves_dimension_without_moving_geometry(
    qtbot: QtBot, saved: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
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
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
    )
    if saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
            session_identity=0,
        )
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.constraints = [dimension]
    layers = editor.layer_table.add(SketchLayer("标注层"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.layer_combo.setCurrentText("标注层")
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    constraints = services.kernel.sketches[0].constraints if saved else editor.canvas.constraints
    assert constraints[0].layer_name == "标注层", editor.status_label.text()
    assert constraints[0].value == 5 and constraints[0].driving
    assert (services.kernel.sketches[0].entities if saved else tuple(editor.canvas.entities)) == (
        line,
    )
    if saved:
        commands = tuple(loaded.document.commands)
        editor.assign_selection_layer_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert tuple(loaded.document.commands) == commands
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    constraints = services.kernel.sketches[0].constraints if saved else editor.canvas.constraints
    assert constraints[0] == dimension


@pytest.mark.parametrize("with_line", [False, True])
def test_current_layer_button_moves_selected_image_with_optional_line(
    qtbot: QtBot, with_line: bool
) -> None:
    services = app.build_app(discoverers=[])
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    if with_line:
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
        )
        editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    try:
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((20, 20), exact_point=True)
        raster = services.kernel.drawing_rasters[0]
        editor.layer_combo.setCurrentText("目标")
        editor.canvas.selected_raster_ids = {raster.image_id}
        editor.canvas.selected_entity_ids = {line.entity_id} if with_line else set()
        editor.assign_selection_layer_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.drawing_rasters[0].layer_name == "目标", editor.status_label.text()
        if with_line:
            assert services.kernel.sketches[0].entities[0].layer_name == "目标"
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.drawing_rasters[0].layer_name == "0"
        if with_line:
            assert services.kernel.sketches[0].entities[0].layer_name == "0"
    finally:
        QApplication.clipboard().clear()


def test_assign_saved_and_draft_lines_to_current_layer(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
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
    saved = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("轮廓"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.layer_combo.setCurrentText("轮廓")
    draft = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "轮廓", editor.status_label.text()
    assert editor.canvas.entities[0].layer_name == "轮廓"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "0"
    assert editor.canvas.entities[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "轮廓"
    assert editor.canvas.entities[0].layer_name == "轮廓"
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "assigned-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert {
        entity.layer_name for sketch in reopened.kernel.sketches for entity in sketch.entities
    } == {"轮廓"}


def test_assign_draft_line_with_user_dimension_to_current_layer(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("轮廓"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    editor.canvas.constraints = [dimension]
    editor.layer_combo.setCurrentText("轮廓")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.assign_selection_layer_button.click()
    assert editor.canvas.entities[0].layer_name == "轮廓", editor.status_label.text()
    assert editor.canvas.constraints == [dimension]
    window.request_undo()
    assert editor.canvas.entities[0].layer_name == "0"
    assert editor.canvas.constraints == [dimension]


@pytest.mark.parametrize("driving", [False, True])
def test_assign_saved_line_with_dimension_to_current_layer(qtbot: QtBot, driving: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=driving,
        layer_name="0",
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.layer_combo.setCurrentText("目标")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "目标", editor.status_label.text()
    assert services.kernel.sketches[0].constraints == (dimension,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "0"
    assert services.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("saved", [False, True])
def test_assign_unrelated_line_when_other_line_has_dimension(qtbot: QtBot, saved: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
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
    measured = LineEntity(uuid4().hex, (0, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 10), (10, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(measured.entity_id, "geometry"),),
        10,
        "mm",
        layer_name="0",
    )
    if saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (measured, other), (dimension,)),
            session_identity=0,
        )
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert editor.canvas.replace_draft_entities((measured, other))
        editor.canvas.constraints = [dimension]
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.layer_combo.setCurrentText("目标")
    editor.canvas.selected_entity_ids = {other.entity_id}
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    entities = services.kernel.sketches[0].entities if saved else editor.canvas.entities
    assert entities[1].layer_name == "目标", editor.status_label.text()
    assert entities[0] == measured


@pytest.mark.parametrize("saved", [False, True])
def test_layer_button_after_document_switch(qtbot: QtBot, saved: bool) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    if saved:
        app.commit_new_sketch(
            first.services,
            first.loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
            session_identity=0,
        )
        editor.set_context_sketches(first.services.kernel.sketches)
        qtbot.waitUntil(
            lambda: editor.canvas.source_context_revision == first.loaded.document.revision,
            timeout=10000,
        )
    else:
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.constraints = [dimension]
    second = window.new_session_document("sketch")
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    editor.layer_combo.setCurrentText("目标")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.assign_selection_layer_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    current = first.services.kernel.sketches[0] if saved else None
    assert (current.entities[0] if current else editor.canvas.entities[0]).layer_name == "目标", (
        editor.status_label.text()
    )
    assert (current.constraints if current else tuple(editor.canvas.constraints)) == (dimension,)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    current = first.services.kernel.sketches[0] if saved else None
    assert (current.entities[0] if current else editor.canvas.entities[0]).layer_name == "0"
    window.activate_session_document(second.loaded.document.document_id)
    active = window.active_sketch_dialog()
    assert active is not None and active is not editor
    active_layers = active.layer_table.add(SketchLayer("目标"))
    active.request_layer_update(active_layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and active.layer_table == active_layers, timeout=10000)
    assert active.canvas.replace_draft_entities((line,))
    editor.assign_selection_layer_requested.emit((line.entity_id,), "目标")
    assert active.canvas.entities == [line]


def test_layer_change_exception_does_not_allow_constrained_geometry_edit(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    canvas.constraints = [dimension]
    changed = replace(line, end_mm=(20, 0), layer_name="其他层")
    assert not canvas.replace_draft_entities((changed,))
    assert canvas.entities == [line]
    assert canvas.constraints == [dimension]


def test_frozen_layer_visible_and_thawed_from_layer_bar(qtbot: QtBot) -> None:
    from dataclasses import replace

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("轮廓"))
    layers = layers.replace(replace(layers.get("轮廓"), frozen=True))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    assert editor.layer_combo.findText("轮廓") >= 0
    editor.layer_combo.setCurrentText("轮廓")
    assert editor.layer_combo.currentText() == "0"
    assert editor.canvas.active_layer_name == "0"
    menu = editor.thaw_layer_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    action = next(action for action in menu.actions() if action.text() == "轮廓")
    action.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.layer_table.get("轮廓").frozen, timeout=10000
    )
    assert editor.layer_combo.currentText() == "0"
    editor.layer_combo.setCurrentText("轮廓")
    assert editor.canvas.active_layer_name == "轮廓"
    editor.layer_combo.setCurrentText("0")
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and editor.layer_table.get("轮廓").frozen, timeout=10000
    )
    assert editor.layer_combo.findText("轮廓") >= 0
