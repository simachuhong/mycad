# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Layer controls apply to annotations independently of referenced geometry."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def drawing(qtbot: QtBot) -> SketchEditorDialog:
    services = build_app(discoverers=())
    editor = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.resize(1300, 850)
    editor.show()
    editor.canvas.entities = [LineEntity(uuid4().hex, (0, 0), (30, 0))]
    editor.canvas.changed.emit()
    return editor


def place(editor: SketchEditorDialog) -> None:
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((15, 0), (15, -15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)


def test_default_dim_layer_and_independent_visibility(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    place(editor)
    assert editor.canvas.constraints[0].layer_name == "DIM"
    assert editor.canvas.entities[0].layer_name == "0"
    table = editor.layer_table.replace(replace(editor.layer_table.get("0"), visible=False))
    editor.set_document_layers(table, "DIM")
    assert len(editor.canvas.visible_dimensions()) == 1
    assert not editor.canvas.visible_snap_entities()
    table = table.replace(replace(table.get("DIM"), visible=False))
    editor.set_document_layers(table, "DIM")
    assert not editor.canvas.visible_dimensions()
    assert len(editor.canvas.constraints) == 1


def test_freeze_excludes_snaps_and_extents_off_does_not_exclude_extents(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    layer = SketchLayer("far", visible=False)
    table = editor.layer_table.add(layer)
    far = LineEntity(uuid4().hex, (1000, 0), (1100, 0), layer_name="far")
    editor.canvas.entities.append(far)
    editor.set_document_layers(table, "DIM")
    editor.canvas.fit_view()
    off_scale = editor.canvas.view_scale
    assert far not in editor.canvas.visible_snap_entities()
    editor.set_document_layers(table.replace(replace(layer, frozen=True)), "DIM")
    editor.canvas.fit_view()
    assert editor.canvas.view_scale > off_scale * 5


def test_layer_manager_is_modeless_and_current_layer_cannot_freeze(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.layer_manager_button.click()
    manager = editor.active_layer_manager
    assert manager is not None
    assert not manager.isModal()
    assert manager.set_layer_state("DIM", visible=False, frozen=True)
    assert not editor.layer_table.get("DIM").displayed
    assert manager.set_layer_state("DIM", frozen=False)
    assert not editor.layer_table.get("DIM").visible
    assert not manager.set_layer_state("0", frozen=True)
    assert not editor.layer_table.get("0").frozen


def test_locked_dim_blocks_drag_and_new_placement(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    place(editor)
    before = tuple(editor.canvas.constraints)
    table = editor.layer_table.replace(replace(editor.layer_table.get("DIM"), locked=True))
    editor.set_document_layers(table, "DIM")
    place(editor)
    assert tuple(editor.canvas.constraints) == before


def test_legacy_migration_is_undoable_and_target_is_selectable(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    place(editor)
    original = replace(editor.canvas.constraints[0], layer_name=None)
    editor.canvas.constraints = [original]
    editor.migrate_legacy_dimensions()
    assert editor.canvas.constraints[0].layer_name == "DIM"
    editor.canvas.undo_last_operation()
    assert editor.canvas.constraints[0].layer_name is None
    table = editor.layer_table.add(SketchLayer("annotation"))
    editor.set_document_layers(table, "annotation")
    place(editor)
    assert editor.canvas.constraints[-1].layer_name == "annotation"


def test_global_layer_changes_preserve_draft_and_undo_through_bus(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", source.to_mapping(version=3), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 20), (30, 20)),))
    before = tuple(editor.canvas.entities)
    table = editor.layer_table.replace(replace(editor.layer_table.get("0"), visible=False))
    editor.request_layer_update(table, "DIM")
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    assert tuple(editor.canvas.entities) == before
    assert not editor.canvas.visible_snap_entities()
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 1, timeout=10000)
    assert tuple(editor.canvas.entities) == before
    assert len(editor.canvas.visible_snap_entities()) == 2
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    path = tmp_path / "layers.my2d"
    save_document(loaded.document, path)
    open_app_document(services, path)
    assert not services.kernel.drawing_layers.get("0").visible


def test_modeless_manager_tracks_toolbar_current_layer(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.request_layer_update(editor.layer_table.add(SketchLayer("X")), "DIM")
    editor.layer_manager_button.click()
    manager = editor.active_layer_manager
    assert manager is not None
    editor.layer_combo.setCurrentText("X")
    assert manager.current_layer == "X"
    assert manager.set_layer_state("0", frozen=True)
    assert editor.layer_table.get("0").frozen
    assert not manager.set_layer_state("X", frozen=True)
    assert not manager.layer_table.get("X").frozen


def test_interleaved_global_and_draft_history_keeps_layer_references(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    unit = window.execution_unit
    assert unit is not None

    def settled() -> None:
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)

    editor.request_layer_update(editor.layer_table.add(SketchLayer("X")), "DIM")
    settled()
    editor.layer_combo.setCurrentText("X")
    line = LineEntity(uuid4().hex, (0, 0), (30, 0), layer_name="X")
    editor.canvas.replace_draft_entities((line,))
    editor.canvas.replace_draft_entities(())
    editor.layer_combo.setCurrentText("0")
    editor.request_layer_update(editor.layer_table.remove("X"), "DIM")
    settled()
    window.request_undo()
    settled()
    assert len(loaded.document.commands) == 1
    window.request_undo()
    settled()
    assert tuple(editor.canvas.entities) == (line,)
    assert editor.layer_table.get("X").name == "X"
    assert len(loaded.document.commands) == 1
    window.request_undo()
    assert not editor.canvas.entities
    window.request_undo()
    settled()
    assert not loaded.document.commands
    for _ in range(4):
        window.request_redo()
        settled()
    assert len(loaded.document.commands) == 2
    assert not editor.canvas.entities
    assert "X" not in {layer.name for layer in editor.layer_table.layers}


def test_off_dimension_extents_are_included_until_layer_is_frozen(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    place(editor)
    editor.canvas.constraints = [replace(editor.canvas.constraints[0], position_mm=(15, 1000))]
    table = editor.layer_table.replace(replace(editor.layer_table.get("DIM"), visible=False))
    editor.set_document_layers(table, "DIM")
    editor.canvas.fit_view()
    off_scale = editor.canvas.view_scale
    editor.set_document_layers(table.replace(replace(table.get("DIM"), frozen=True)), "DIM")
    editor.canvas.fit_view()
    assert editor.canvas.view_scale > off_scale * 5


def test_palette_layer_command_opens_modeless_manager(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("drawing.layers.set")
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.active_layer_manager is not None
    assert not editor.active_layer_manager.isModal()
    assert window.plan_draft is not None
    assert not window.plan_draft.steps()


def test_new_global_layer_edit_discards_abandoned_draft_redo(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    unit = window.execution_unit
    assert unit is not None
    editor.request_layer_update(editor.layer_table.add(SketchLayer("X")), "DIM")
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    editor.canvas.replace_draft_entities(
        (LineEntity(uuid4().hex, (0, 0), (30, 0), layer_name="X"),)
    )
    window.request_undo()
    assert editor.canvas.can_redo
    editor.request_layer_update(editor.layer_table.remove("X"), "DIM")
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert not editor.canvas.can_redo
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert not editor.canvas.entities
    assert len(loaded.document.commands) == 2


@pytest.mark.parametrize("tool", ["直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"])
def test_drawing_after_dimension_returns_current_dim_layer_to_zero(qtbot: QtBot, tool: str) -> None:
    editor = drawing(qtbot)
    editor.layer_combo.setCurrentText("DIM")
    place(editor)
    dimensions = tuple(editor.canvas.constraints)
    editor.layer_manager_button.click()
    manager = editor.active_layer_manager
    assert manager is not None
    editor.tool_buttons[tool].click()
    assert editor.canvas.tool == tool
    assert editor.layer_combo.currentText() == "0"
    assert editor.canvas.active_layer_name == "0"
    assert manager.current_layer == "0"
    assert tuple(editor.canvas.constraints) == dimensions
    assert dimensions[0].layer_name == "DIM"
    assert editor.dimension_layer == "DIM"
    if tool == "直线":
        editor.canvas.add_coordinate_point((0, 30), exact_point=True)
        editor.canvas.add_coordinate_point((30, 30), exact_point=True)
        assert editor.canvas.entities[-1].layer_name == "0"


def test_drawing_tool_preserves_user_selected_non_dim_layer(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.set_document_layers(editor.layer_table.add(SketchLayer("OUTLINE")), "DIM")
    editor.layer_combo.setCurrentText("OUTLINE")
    place(editor)
    editor.tool_buttons["圆"].click()
    assert editor.canvas.active_layer_name == "OUTLINE"


def test_selection_and_rejected_tool_switch_do_not_reset_dim_layer(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.layer_combo.setCurrentText("DIM")
    place(editor)
    editor.tool_buttons["选择元素"].click()
    assert editor.canvas.active_layer_name == "DIM"
    # A refused switch while drawing must not change the in-progress object's layer.
    editor.tool_buttons["直线"].click()
    editor.layer_combo.setCurrentText("DIM")
    editor.canvas.add_coordinate_point((0, 30), exact_point=True)
    editor.tool_buttons["圆"].click()
    assert editor.canvas.tool == "直线"
    assert editor.canvas.active_layer_name == "DIM"


def test_drawing_from_dim_requires_thawing_frozen_zero_layer(qtbot: QtBot) -> None:
    editor = drawing(qtbot)
    editor.layer_combo.setCurrentText("DIM")
    place(editor)
    editor.set_document_layers(
        editor.layer_table.replace(replace(editor.layer_table.get("0"), frozen=True)), "DIM"
    )
    editor.tool_buttons["圆"].click()
    assert editor.canvas.tool == "选择元素"
    assert editor.canvas.active_layer_name == "DIM"
    assert editor.layer_table.get("0").frozen
    assert "解冻" in editor.status_label.text()
