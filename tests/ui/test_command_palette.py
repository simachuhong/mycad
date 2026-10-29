# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 6: left-panel command palette + plan-draft controller contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from mycad.app import build_app
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.commands.validation import ValidationError
from mycad.core.exceptions import UnknownCommandError
from mycad.plugins.types import (
    CommandContribution,
    DiscoveredPlugin,
    PluginManifest,
)
from mycad.ui.command_palette import PLUGIN_HINT_TEXT, CommandPalette
from mycad.ui.main_window import MainWindow
from mycad.ui.plan_draft import PlanDraftController

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.plan import Plan

RELEASED_BUILTIN_IDS: frozenset[str] = frozenset(
    {
        "drawing.layers.set",
        "drawing.sheet.create",
        "drawing.sheet.update",
        "drawing.sheet.delete",
        "drawing.view.create",
        "drawing.view.update",
        "drawing.view.delete",
        "drawing.annotation.create",
        "drawing.annotation.update",
        "drawing.annotation.delete",
        "drawing.note.create",
        "drawing.note.update",
        "drawing.note.delete",
        "reference.attach",
        "reference.update",
        "reference.detach",
        "feature.box",
        "feature.cylinder",
        "feature.extrude",
        "feature.revolve",
        "feature.hole",
        "feature.hole_pattern",
        "modify.fillet",
        "modify.boolean_cut",
        "modify.boolean_intersect",
        "modify.boolean_bodies",
        "modify.body_transform",
        "modify.body_pattern",
        "modify.chamfer",
        "sketch.create",
        "sketch.constraint.add",
        "sketch.constraint.update",
    }
)


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture
def palette(services: AppServices, qapp: object) -> CommandPalette:
    return CommandPalette(services.registry)


def _all_leaf_ids(palette: CommandPalette) -> list[str]:
    ids: list[str] = []
    tree = palette.tree
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        if group is None:
            continue
        for j in range(group.childCount()):
            child = group.child(j)
            if child is not None:
                ids.append(str(child.data(0, Qt.ItemDataRole.UserRole)))
    return ids


def _group_titles(palette: CommandPalette) -> set[str]:
    titles: set[str] = set()
    tree = palette.tree
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item is not None:
            titles.add(item.text(0))
    return titles


def test_all_released_builtins_appear_grouped(palette: CommandPalette) -> None:
    assert palette.tree.topLevelItemCount() == 5
    assert _group_titles(palette) == {"图纸", "创建特征", "修改", "草图", "来源关联"}
    ids = _all_leaf_ids(palette)
    assert len(ids) == len(RELEASED_BUILTIN_IDS)
    assert set(ids) == RELEASED_BUILTIN_IDS


def test_independent_drawing_palette_only_shows_drawing_commands(
    palette: CommandPalette,
) -> None:
    palette.set_document_type("drawing2d")
    assert set(_all_leaf_ids(palette)) == {
        command_id
        for command_id in RELEASED_BUILTIN_IDS
        if command_id.startswith(("drawing.", "sketch.", "reference."))
    }
    palette.set_document_type("part")
    assert set(_all_leaf_ids(palette)) == RELEASED_BUILTIN_IDS


def test_leaf_labels_are_zh_with_id(palette: CommandPalette) -> None:
    root = None
    for index in range(palette.tree.topLevelItemCount()):
        group = palette.tree.topLevelItem(index)
        if group is not None and group.toolTip(0) == "feature":
            root = group
            break
    assert root is not None
    box = root.child(0)
    assert box is not None
    assert box.text(0) == "长方体"
    assert "feature.box" in box.toolTip(0)
    assert root.isExpanded()


def test_search_matches_id_and_zh_label(
    palette: CommandPalette,
    qapp: object,
) -> None:
    assert palette.apply_filter("hole") == 2
    visible = [id_ for id_ in _all_leaf_ids(palette) if not _leaf_is_hidden(palette, id_)]
    assert set(visible) == {"feature.hole", "feature.hole_pattern"}
    # The zh query hits the same pair through label_zh (register.search
    # excludes zh by design — the palette is the reason it must work).
    assert palette.apply_filter("孔") == 2
    assert palette.apply_filter("") == len(RELEASED_BUILTIN_IDS)
    assert not any(_leaf_is_hidden(palette, id_) for id_ in _all_leaf_ids(palette))


def _leaf_is_hidden(palette: CommandPalette, command_id: str) -> bool:
    tree = palette.tree
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        if group is None:
            continue
        for j in range(group.childCount()):
            child = group.child(j)
            if child is not None and child.data(0, Qt.ItemDataRole.UserRole) == command_id:
                return child.isHidden()
    raise AssertionError(f"leaf {command_id} not found")


def test_plugin_hint_is_verbatim(palette: CommandPalette) -> None:
    assert palette.hint.text() == PLUGIN_HINT_TEXT


def test_plan_draft_controller_contract(
    services: AppServices,
    qapp: object,
) -> None:
    controller = PlanDraftController(services.registry)
    replaced: list[Plan] = []
    controller.plan_replaced.connect(lambda: replaced.append(controller.plan()))
    assert replaced == []

    step = controller.new_draft("feature.cylinder")
    assert controller.plan().status == "draft"
    assert [s.id for s in controller.steps()] == ["feature.cylinder"]
    assert controller.selected_step_index() == 0
    assert len(replaced) == 1

    changed: list[tuple[int, dict[str, object]]] = []

    def capture(index: int, params: dict[str, object]) -> None:
        changed.append((index, params))

    controller.params_changed.connect(capture)
    validated = controller.set_params(step, {"radius": 10.0, "height": 5.0})
    assert validated["radius"] == 10.0
    # PlannedCommand is frozen: the edited step is replaced in the steps
    # list, the returned params are the validated (default-filled) dict.
    new_step = controller.steps()[0]
    assert new_step is not step
    assert "radius" in new_step.params and "center" in new_step.params
    assert changed == [(0, validated)]

    bad: dict[str, object] = {"radius": -1.0, "height": 5.0}
    with pytest.raises(ValidationError):
        controller.set_params(step, bad)
    assert controller.steps()[0] is new_step

    with pytest.raises(UnknownCommandError):
        controller.new_draft("missing.command")
    assert len(replaced) == 1

    controller.select_step(0)
    with pytest.raises(IndexError):
        controller.select_step(1)


def test_unplannable_plugin_command_raises_value_error() -> None:
    services = build_app(discoverers=(_PluginOnlyDiscoverer(),))
    controller = PlanDraftController(services.registry)
    with pytest.raises(ValueError, match="cannot be planned"):
        controller.new_draft("demo.widget")


@dataclass(frozen=True)
class _PluginOnlyDiscoverer:
    """A discoverer shape used directly (same-source in-process plugin)."""

    def discover(self) -> tuple[DiscoveredPlugin, ...]:
        spec = CommandSpec(
            id="demo.widget",
            version=1,
            summary_en="Plugin demo command",
            label_zh="插件控件",
            params_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            cli=CliSyntax(verb_aliases=("widget",)),
        )
        plugin = DiscoveredPlugin(
            distribution_name="mycad_plugin_demo",
            entrypoint=("mycad.commands:mycad_plugin_demo",),
            manifest=PluginManifest(id="demo", version="1.0", api_version="1.0"),
            commands=(CommandContribution(spec=spec, handler_factory=None),),
        )
        return (plugin,)


def test_plugin_command_appears_via_discovery(qapp: object) -> None:
    services = build_app(discoverers=(_PluginOnlyDiscoverer(),))
    palette = CommandPalette(services.registry)
    assert "demo.widget" in _all_leaf_ids(palette)
    assert _group_titles(palette) == {"demo", "图纸", "创建特征", "修改", "草图", "来源关联"}


def test_refresh_pickups_later_registration(
    services: AppServices,
    palette: CommandPalette,
    qapp: object,
) -> None:
    assert "late.plugin" not in _all_leaf_ids(palette)
    late = CommandSpec(
        id="late.plugin",
        version=1,
        summary_en="Registered after palette construction",
        label_zh="迟来插件",
        params_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        cli=CliSyntax(verb_aliases=("late",)),
    )
    services.registry.register(late)
    palette.refresh()
    ids = _all_leaf_ids(palette)
    assert ids.count("late.plugin") == 1
    assert palette.apply_filter("迟来") == 1


def test_main_window_binds_palette_and_draft(qapp: object) -> None:
    services = build_app(discoverers=(_PluginOnlyDiscoverer(),))
    window = MainWindow(services=services)
    assert window.left_dock.widget() is window.command_palette
    assert window.plan_draft is not None
    assert window.command_palette is not None

    window.command_palette.command_activated.emit("feature.box")
    controller = window.plan_draft
    steps = controller.steps()
    assert [s.id for s in steps] == ["feature.box"]
    assert "XY 工作平面" in window.status_command.text()

    window.command_palette.command_activated.emit("demo.widget")
    assert "cannot be planned" in window.status_command.text()
