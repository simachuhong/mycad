# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Three permanent workspaces preserve drafts and route commands by active page."""

from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import LineEntity
from mycad.ui.main_window import MainWindow


def test_three_pages_keep_identity_and_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    window.show()
    tabs = window.workspace_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["平面草图", "工程图", "3D图"]
    pages = tuple(tabs.widget(i) for i in range(3))
    tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    entity = LineEntity("1234567890ab4cde8f001234567890ab", (0, 0), (10, 0))
    draft.canvas.entities.append(entity)
    draft.canvas.selected_entity_ids.add(entity.entity_id)
    draft.canvas.fit_view()
    scale = draft.canvas.view_scale
    assert window.viewport is not None
    window.viewport.set_orientation("left")
    camera = window.viewport.camera_state()
    before = tuple(draft.canvas.entities)
    tabs.activate("drawing")
    assert window.active_workspace == "drawing"
    tabs.activate("model")
    tabs.activate("sketch")
    assert window.active_sketch_dialog() is draft
    assert tuple(draft.canvas.entities) == before
    assert draft.canvas.selected_entity_ids == {entity.entity_id}
    assert draft.canvas.view_scale == scale
    assert window.viewport.camera_state() == camera
    assert window.viewport.orientation() == "left"
    assert tuple(tabs.widget(i) for i in range(3)) == pages
    loaded = window.loaded_document()
    assert loaded is not None
    assert not loaded.document.commands


def test_switch_hides_floating_drafting_dock(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services))
    window.show()
    window.workspace_tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.parameter_dock.setFloating(True)
    draft.parameter_dock.show()
    draft.canvas.grabMouse()
    window.workspace_tabs.activate("drawing")
    assert QWidget.mouseGrabber() is None
    assert not draft.parameter_dock.isVisible()
    window.workspace_tabs.activate("sketch")
    assert draft.parameter_dock.isFloating()
    assert draft.parameter_dock.isVisible()


def test_drawing2d_does_not_offer_solid_projection(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(new_document(services, document_type="drawing2d"))
    window.workspace_tabs.activate("drawing")
    assert not window.drawing_workbench.base_action.isEnabled()
    assert window.workspace_tabs.isTabEnabled(2)
    window.workspace_tabs.activate("model")
    assert window.active_workspace == "model"
    assert not window.drawing_workbench.base_action.isEnabled()


def test_global_undo_does_not_edit_hidden_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8})
    window.bind_document(loaded)
    window.workspace_tabs.activate("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((10, 0))
    before = tuple(draft.canvas.entities)
    assert before
    window.workspace_tabs.activate("drawing")
    window.request_undo()
    qtbot.waitUntil(lambda: not loaded.document.commands)
    assert tuple(draft.canvas.entities) == before
