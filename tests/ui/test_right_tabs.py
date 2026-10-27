# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Right-panel tab tests (plan todo 7).

Covers the five fixed tabs, structure-tree construction from
feature_history + named_groups, the read-only property table (spec params
vs document metadata fallback), and the live options-editor contract with a
genuine PlanDraftController (todo 12 wires the same component into the
confirmation flow, so the real controller — not a stub — is the honest
falsifiable subject here).
"""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtWidgets import QTableWidget

from mycad.app import AppServices, build_app, new_document
from mycad.core.document import METADATA_KEYS
from mycad.core.groups import NamedGroup
from mycad.core.persistence import LoadedDocument
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow
from mycad.ui.plan_draft import PlanDraftController
from mycad.ui.right_panel import (
    EMPTY_PROMPT,
    FEATURE_GROUP_TITLE,
    ORDINAL_ROLE,
    RIGHT_TAB_TITLES,
    SOLIDS_GROUP_TITLE,
    STRUCTURE_GROUP_TITLES,
    UNTITLED_DOCUMENT,
    RightPanel,
)


def _spec_property_keys(services: AppServices, command_id: str) -> list[str]:
    properties = services.registry.get(command_id).params_schema.get("properties")
    if isinstance(properties, dict):
        return list(cast("dict[str, object]", properties))
    return []


def _cell_text(table: QTableWidget, row: int, column: int) -> str:
    cell = table.item(row, column)
    assert cell is not None
    return cell.text()


def _header_text(table: QTableWidget, column: int) -> str:
    item = table.horizontalHeaderItem(column)
    assert item is not None
    return item.text()


def _three_command_document() -> tuple[AppServices, LoadedDocument]:
    services = build_app()
    loaded = new_document(services)
    bus = loaded.bus
    bus.execute("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 5.0}, "test")
    bus.execute("feature.box", {"size_x": 30.0, "size_y": 8.0, "size_z": 2.0}, "test")
    bus.execute("feature.cylinder", {"radius": 30.0, "height": 15.0}, "test")
    return services, loaded


def _empty_document() -> tuple[AppServices, LoadedDocument]:
    services = build_app()
    return services, new_document(services)


def _group_item(panel: RightPanel, title: str):
    root = panel.structure_tree.topLevelItem(0)
    assert root is not None
    for index in range(root.childCount()):
        child = root.child(index)
        assert child is not None
        if child.text(0) == title:
            return child
    raise AssertionError(f"structure group {title!r} missing")


def test_five_fixed_tabs_present(qapp: object) -> None:
    panel = RightPanel()
    assert panel.tabs.count() == 5
    for index, title in enumerate(RIGHT_TAB_TITLES):
        assert panel.tabs.tabText(index) == title
    display_index = RIGHT_TAB_TITLES.index("显示")
    measure_index = RIGHT_TAB_TITLES.index("测量")
    display_page = panel.tabs.widget(display_index)
    measure_page = panel.tabs.widget(measure_index)
    assert display_page is not None
    assert measure_page is not None
    assert display_page.isEnabled() is False
    assert measure_page.isEnabled() is False


def test_structure_tree_built_from_feature_history(qapp: object) -> None:
    services, loaded = _three_command_document()
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)
    root = panel.structure_tree.topLevelItem(0)
    assert root is not None
    assert root.text(0) == UNTITLED_DOCUMENT
    assert root.childCount() == len(STRUCTURE_GROUP_TITLES)
    group_titles: list[str] = []
    for index in range(root.childCount()):
        child = root.child(index)
        assert child is not None
        group_titles.append(child.text(0))
    assert group_titles == list(STRUCTURE_GROUP_TITLES)
    features = _group_item(panel, FEATURE_GROUP_TITLE)
    assert features.childCount() == 3
    first = features.child(0)
    assert first is not None
    assert first.text(0).startswith("#0")
    assert "长方体" in first.text(0)
    assert "feature.box" in first.toolTip(0)
    solids = _group_item(panel, SOLIDS_GROUP_TITLE)
    assert solids.childCount() == 1
    placeholder = solids.child(0)
    assert placeholder is not None
    assert placeholder.text(0) == EMPTY_PROMPT


def test_sketch_commands_are_grouped_separately_from_solid_features(qapp: object) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame.xy(),
            (CircleEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), 5.0),),
        ).to_mapping(),
        confirmed_by="test",
    )
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": sketch_id},
            "distance": 10.0,
            "mode": "new",
        },
        confirmed_by="test",
        version=2,
    )
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)

    sketches = _group_item(panel, "草图")
    features = _group_item(panel, FEATURE_GROUP_TITLE)
    sketch_node = sketches.child(0)
    feature_node = features.child(0)
    assert sketch_node is not None and feature_node is not None
    assert sketches.childCount() == 1
    assert sketch_node.text(0) == f"草图 #{loaded.document.commands[0].ordinal} · 0a0a0a0a"
    assert sketch_node.data(0, ORDINAL_ROLE) == 0
    assert features.childCount() == 1
    assert feature_node.text(0).startswith("#1")
    assert "拉伸" in feature_node.text(0)


def test_empty_document_groups_show_placeholders(qapp: object) -> None:
    services, loaded = _empty_document()
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)
    for title in STRUCTURE_GROUP_TITLES:
        group = _group_item(panel, title)
        assert group.childCount() == 1
        child = group.child(0)
        assert child is not None
        assert child.text(0) == EMPTY_PROMPT


def test_clicking_feature_leaf_updates_property_table(qapp: object) -> None:
    services, loaded = _three_command_document()
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)
    selected: list[int] = []
    panel.structure_selection_changed.connect(selected.append)
    first = _group_item(panel, FEATURE_GROUP_TITLE).child(0)
    assert first is not None
    panel.structure_tree.itemClicked.emit(first, 0)
    assert selected == [0]
    table = panel.property_table
    expected = _spec_property_keys(services, "feature.box")
    assert table.rowCount() == len(expected)
    assert (_header_text(table, 0), _header_text(table, 1), _header_text(table, 2)) == (
        "参数",
        "类型",
        "当前值",
    )
    keys = [_cell_text(table, row, 0) for row in range(table.rowCount())]
    assert keys == expected
    row = expected.index("size_x")
    assert _cell_text(table, row, 1) == "Positive"
    assert float(_cell_text(table, row, 2)) == pytest.approx(10.0)
    second = _group_item(panel, FEATURE_GROUP_TITLE).child(1)
    assert second is not None
    panel.structure_tree.itemClicked.emit(second, 0)
    assert selected == [0, 1]
    assert float(_cell_text(table, row, 2)) == pytest.approx(30.0)


def test_property_table_falls_back_to_document_metadata(qapp: object) -> None:
    services, loaded = _empty_document()
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)
    table = panel.property_table
    assert table.rowCount() == len(METADATA_KEYS)
    assert [_cell_text(table, row, 0) for row in range(table.rowCount())] == list(METADATA_KEYS)
    assert table.rowCount() > 0
    source_row = METADATA_KEYS.index("source")
    assert _cell_text(table, source_row, 0) == "source"
    assert _cell_text(table, source_row, 2) == "local"


def test_show_spec_params_from_registry(qapp: object) -> None:
    services, loaded = _empty_document()
    panel = RightPanel()
    panel.bind_document(loaded, services.registry)
    panel.show_spec_params("feature.box")
    table = panel.property_table
    expected = _spec_property_keys(services, "feature.box")
    assert table.rowCount() == len(expected)
    assert [_cell_text(table, row, 0) for row in range(table.rowCount())] == expected
    type_row = expected.index("size_x")
    assert _cell_text(table, type_row, 1) == "Positive"


def _explicit_draft(services: AppServices) -> PlanDraftController:
    controller = PlanDraftController(services.registry)
    controller.new_draft("feature.box")
    controller.set_params(controller.steps()[0], {"size_x": 10.0, "size_y": 20.0, "size_z": 5.0})
    return controller


def test_options_table_follows_plan_draft(qapp: object) -> None:
    services, _loaded = _empty_document()
    controller = _explicit_draft(services)
    panel = RightPanel()
    panel.bind_draft(controller)
    table = panel.options_table
    keys = [_cell_text(table, row, 0) for row in range(table.rowCount())]
    assert keys == list(controller.params_of(controller.steps()[0]))
    assert "size_x" in keys
    assert (_header_text(table, 0), _header_text(table, 1)) == ("参数", "当前值")
    size_row = keys.index("size_x")
    assert float(_cell_text(table, size_row, 1)) == pytest.approx(10.0)
    editable = table.item(size_row, 1)
    assert editable is not None
    editable.setText("12")
    assert controller.steps()[0].params["size_x"] == 12
    assert _cell_text(table, size_row, 1) == "12"


def test_options_invalid_edit_reverts_and_reports(qapp: object) -> None:
    services, _loaded = _empty_document()
    controller = _explicit_draft(services)
    panel = RightPanel()
    panel.bind_draft(controller)
    errors: list[str] = []
    panel.options_error.connect(errors.append)
    controller_keys = list(controller.params_of(controller.steps()[0]))
    size_row = controller_keys.index("size_x")
    cell = panel.options_table.item(size_row, 1)
    assert cell is not None
    cell.setText("abc")
    assert len(errors) == 1
    assert "size_x" in errors[0]
    assert float(_cell_text(panel.options_table, size_row, 1)) == pytest.approx(10.0)
    assert controller.steps()[0].params["size_x"] == pytest.approx(10.0)


def test_window_binds_right_panel_and_refreshes_structure_on_signals(qapp: object) -> None:
    services, loaded = _three_command_document()
    window = MainWindow(services=services)
    window.bind_document(loaded)
    panel = window.right_panel
    assert panel is not None
    assert window.right_dock.widget() is panel
    features = _group_item(panel, FEATURE_GROUP_TITLE)
    assert features.childCount() == 3
    loaded.document.add_named_group(NamedGroup(name="top"))
    solids = _group_item(panel, SOLIDS_GROUP_TITLE)
    assert solids.childCount() == 2
    labels: set[str] = set()
    for index in range(2):
        child = solids.child(index)
        assert child is not None
        labels.add(child.text(0))
    assert labels == {"实体 1", "top"}
    loaded.bus.execute("feature.box", {"size_x": 12.0, "size_y": 6.0, "size_z": 3.0}, "test")
    assert _group_item(panel, FEATURE_GROUP_TITLE).childCount() == 4
