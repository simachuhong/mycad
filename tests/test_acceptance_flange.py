# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Phase-0 projection of the requirements' acceptance baseline (需求分析书 §8).

The flange (OD80 x 8, bore 20, 4 x d6 on a 50 PCD) is the whole phase-0
acceptance driver. Group A runs the full modeling sequence; Group B is
reached ONLY by ``edit_and_replay`` on that same document, so the
parametric-rebuild claim is tested rather than re-scripted. Expected
volumes are recomputed here from ``math.pi`` and cross-checked against the
hand-written golden constants — never reverse-recorded from output.
"""

from __future__ import annotations

import os

# The UI acceptance below drives the full Qt shell offscreen (todo 13);
# set the platform before pytest-qt materializes any QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import math
from pathlib import Path
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document
from mycad.cli.session import CliSession
from mycad.commands.grammar import parse_line, to_cli
from mycad.commands.validation import validate_params
from mycad.core.document import AFFECTED_OBJECTS, AffectedObject, PlannedCommand
from mycad.core.persistence import save_document
from mycad.core.plan import Plan
from tests.helpers.step_roundtrip import read_step

REPO = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO / "tests" / "golden" / "flange_golden.json"
SCRIPT_PATH = REPO / "examples" / "flange_script.txt"
PLAN_PATH = REPO / "examples" / "flange_plan.json"

#: CLI builtins and batch markers are not modeling commands; the history
#: snapshot compares against the modeling lines of the example script only.
NON_MODELING_HEADS = frozenset(
    {
        "new",
        "open",
        "save",
        "export",
        "meta",
        "undo",
        "redo",
        "history",
        "help",
        "quit",
        "exit",
        "begin-batch",
        "end-batch",
    }
)

#: Group A -> Group B edits: six parameter classes (OD, thickness, bore,
#: hole diameter, hole count, PCD radius), each changed at least once.
TOP_FACE: dict[str, object] = {"surface": "plane", "axis": "+Z", "rank": 0}
GROUP_B_EDITS: tuple[tuple[int, dict[str, object], str], ...] = (
    (0, {"radius": 50, "height": 10, "center": [0, 0, 0], "mode": "new"}, "OD 80->100, thk 8->10"),
    (
        1,
        {
            "target_face": TOP_FACE,
            "position": {"kind": "center"},
            "diameter": 30,
            "depth": {"kind": "through_all"},
        },
        "bore 20->30",
    ),
    (
        2,
        {
            "base_hole": {
                "target_face": TOP_FACE,
                "position": {"kind": "center"},
                "diameter": 8,
                "depth": {"kind": "through_all"},
            },
            "pattern": {"kind": "polar", "radius": 35, "count": 6, "start_angle_deg": 0},
        },
        "hole d6->d8, count 4->6, PCD r25->r35",
    ),
)


def _golden(group: str) -> dict[str, object]:
    data = cast("dict[str, object]", json.loads(GOLDEN_PATH.read_text(encoding="utf-8")))
    groups = cast("dict[str, dict[str, object]]", data["groups"])
    entry = groups[group]
    # The formula is documentation-only: present, but never fed to geometry.
    assert isinstance(entry["_formula"], str)
    return entry


def _expected_volume(group: str) -> float:
    """Recompute the closed-form volume and cross-check the golden constant."""
    g = _golden(group)
    thk = float(cast("float", g["thk_mm"]))
    outer_r = float(cast("float", g["od_mm"])) / 2
    bore_r = float(cast("float", g["bore_mm"])) / 2
    hole_r = float(cast("float", g["hole_d_mm"])) / 2
    count = int(cast("int", g["hole_count"]))
    computed = math.pi * thk * (outer_r**2 - bore_r**2 - count * hole_r**2)
    assert abs(computed - float(cast("float", g["expected_volume_mm3"]))) < 1e-9
    return computed


def _plan_steps() -> list[dict[str, object]]:
    data = cast("dict[str, object]", json.loads(PLAN_PATH.read_text(encoding="utf-8")))
    return cast("list[dict[str, object]]", data["steps"])


def _modeling_lines() -> list[str]:
    """Modeling lines of the example script, in order."""
    lines: list[str] = []
    for raw in SCRIPT_PATH.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split(" ", 1)[0] in NON_MODELING_HEADS:
            continue
        lines.append(stripped)
    return lines


def _assert_geometry(services: AppServices, group: str) -> None:
    g = _golden(group)
    mass = services.kernel.mass_properties()
    assert mass.volume == pytest.approx(_expected_volume(group), abs=1e-6)
    assert mass.solid_count == g["solid_count"]
    assert mass.cylindrical_face_count == g["cylindrical_faces"]
    bbox = mass.bbox
    assert bbox is not None
    size = [bbox.xmax - bbox.xmin, bbox.ymax - bbox.ymin, bbox.zmax - bbox.zmin]
    assert size == pytest.approx(cast("list[float]", g["bbox_size"]), abs=1e-9)


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


# -- §8.1 parametric edit: Group A sequence, Group B by replay only ----------


def test_parameters_are_editable_by_replay(services: AppServices) -> None:
    """Group A full sequence, then six parameter classes edited to Group B.

    Group B is reached on the SAME document through ``edit_and_replay`` —
    not a second document, not a second script.
    """
    loaded = new_document(services)
    for step in _plan_steps():
        loaded.bus.execute(
            cast("str", step["id"]),
            cast("dict[str, object]", step["params"]),
            confirmed_by="acceptance-test",
        )
    _assert_geometry(services, "A")
    before = {c.ordinal: (c.timestamp_utc, dict(c.params)) for c in loaded.document.commands}

    for ordinal, params, reason in GROUP_B_EDITS:
        loaded.bus.edit_and_replay(ordinal, params, actor="acceptance-test", reason=reason)

    # Predicate selectors re-resolved the same semantic faces at new sizes.
    _assert_geometry(services, "B")
    for command in loaded.document.commands:
        original_ts, original_params = before[command.ordinal]
        assert command.timestamp_utc == original_ts
        assert len(command.amendments) == 1
        amendment = command.amendments[0]
        assert amendment.actor == "acceptance-test"
        assert amendment.from_params == original_params


def test_golden_group_b_constant_matches_closed_form() -> None:
    """§8.1b: the Group B constant is only a cross-check, never a second run."""
    assert _expected_volume("B") == pytest.approx(68455.3039217216, abs=1e-9)


# -- §8.2 plan -> confirm -> execute -> STEP readback ------------------------


def test_plan_confirm_execute_and_step_roundtrip(services: AppServices, tmp_path: Path) -> None:
    loaded = new_document(services)
    steps = [
        PlannedCommand(
            id=cast("str", step["id"]),
            version=cast("int", step["version"]),
            params=cast("dict[str, object]", step["params"]),
            summary_en=services.registry.get(cast("str", step["id"])).summary_en,
            affected_object=cast("AffectedObject", AFFECTED_OBJECTS[cast("str", step["id"])]),
        )
        for step in _plan_steps()
    ]
    plan = Plan(steps)
    assert plan.status == "draft"
    loaded.bus.confirm_plan(plan, actor="acceptance-test", scope="cli")
    assert plan.status == "confirmed"
    loaded.bus.execute_batch(plan, scope="cli")
    _assert_geometry(services, "A")

    step_file = tmp_path / "flange.step"
    services.formats.resolve(step_file).write(services.kernel, step_file)
    assert step_file.stat().st_size > 10240
    solid_count, volume = read_step(step_file)
    assert solid_count == 1
    assert volume == pytest.approx(_expected_volume("A"), abs=1e-6)

    # All five holes go through the predicate feature path, never a cut.
    ids = [c.id for c in loaded.document.commands]
    assert ids == ["feature.cylinder", "feature.hole", "feature.hole_pattern"]
    assert "modify.boolean_cut" not in ids
    assert all(c.confirmed_by == "acceptance-test" for c in loaded.document.commands)


# -- §8.3 batch undo inside one persistent session ---------------------------


def _history_json(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> list[dict[str, object]]:
    capsys.readouterr()
    assert session.execute_line("history --json") == 0
    payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    return cast("list[dict[str, object]]", payload["commands"])


def test_batch_undo_in_one_session(
    services: AppServices, capsys: pytest.CaptureFixture[str]
) -> None:
    """Undo granularity is the command; three undos drop the whole batch.

    The sequence stays inside ONE session: ``mycad run`` releases its
    document when the process ends, so a cross-process undo is meaningless.
    """
    session = CliSession(services)
    assert session.execute_line("new") == 0
    assert session.execute_line("begin-batch") == 0
    for line in _modeling_lines():
        assert session.execute_line(line) == 0
    assert session.execute_line("end-batch") == 0
    _assert_geometry(services, "A")

    entries = _history_json(session, capsys)
    replayed = [
        to_cli(cast("str", e["id"]), cast("dict[str, object]", e["params"]), services.registry)
        for e in entries
    ]
    assert replayed == _modeling_lines()
    assert all(e["confirmed_by"] == "cli-local" for e in entries)

    assert session.execute_line("undo 3") == 0
    mass = services.kernel.mass_properties()
    assert mass.solid_count == 0
    assert mass.volume == 0.0
    assert _history_json(session, capsys) == []


def test_script_and_plan_describe_the_same_geometry(services: AppServices) -> None:
    """The two example entry points are parameter-wise equivalent."""
    registry = services.registry
    from_script = [parse_line(line, registry) for line in _modeling_lines()]
    from_plan = [
        (
            cast("str", step["id"]),
            validate_params(
                registry.get(cast("str", step["id"])),
                cast("dict[str, object]", step["params"]),
                defs=registry.schema_defs,
            ),
        )
        for step in _plan_steps()
    ]
    assert [i for i, _ in from_script] == [i for i, _ in from_plan]
    for (_, script_params), (command_id, plan_params) in zip(from_script, from_plan, strict=True):
        filled = validate_params(registry.get(command_id), script_params, defs=registry.schema_defs)
        assert filled == plan_params


# -- §8.4 UI layout: phase 1 -------------------------------------------------


def test_ui_layout_acceptance(
    qapp: object,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Phase-1 UI acceptance (UI初稿 §11 five items) + the todo-13 minimal
    workflow: palette drafting -> six-state confirm -> STEP export ->
    ``bus.undo(len(plan.steps))`` back to the pre-plan state. Fully offscreen.
    """
    del qapp  # pytest-qt's QApplication exists as soon as this fixture resolves
    # The plan execution leaves the document dirty; teardown closes the main
    # window, whose unsaved-changes dialog must never run offscreen (the
    # stale pytest-qt widget close blocks on a modal exec — todo-13 hang).
    from mycad.ui.main_window import MainWindow

    def _discard(self: MainWindow) -> str:  # noqa: ARG001 (Qt receiver shape)
        return "discard"

    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)
    from PySide6.QtCore import Qt

    from mycad.ui.main_window import MainWindow
    from mycad.ui.right_panel import RIGHT_TAB_TITLES
    from mycad.ui.viewport import GLViewport

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    window.bind_document(loaded)

    # §11.1 five-zone skeleton + menu/toolbar/status bar all in place.
    viewport = window.viewport
    palette = window.command_palette
    panel = window.right_panel
    bottom = window.bottom_dock
    assert viewport is not None and isinstance(viewport, GLViewport)
    assert palette is not None
    assert panel is not None
    assert bottom is not None
    assert window.menuBar().actions()
    toolbar = window.main_toolbar
    assert window.status_bar.children()  # permanent widgets + central default child

    # §11.2 toolbar can be hidden and moved to another edge.
    toolbar.hide()
    assert not toolbar.isVisible()
    window.addToolBar(Qt.ToolBarArea.RightToolBarArea, toolbar)
    assert window.toolBarArea(toolbar) == Qt.ToolBarArea.RightToolBarArea
    toolbar.show()

    # The model tree now lives in the left navigator; properties remain on the right.
    tabs = panel.tabs
    titles = [tabs.tabText(i) for i in range(tabs.count())]
    assert window.left_tabs is not None
    assert window.left_tabs.tabText(0) == "模型"
    model_tab = window.left_tabs.widget(0)
    assert model_tab is not None and model_tab.isAncestorOf(panel.structure_tree)
    for title in RIGHT_TAB_TITLES[1:]:
        assert title in titles

    # §11.5 left palette: all registered builtins are discoverable, searchable.
    expected_builtin_count = sum(
        len(specs) for specs in services.registry.list_by_category().values()
    )
    assert palette.apply_filter("") == expected_builtin_count
    assert palette.apply_filter("box") == 1

    # §11.4 Chat page: a drafted plan renders as cards and the model only
    # changes after confirm (execute_plan). Draft via the todo-6 controller.
    draft = window.plan_draft
    cards = window.plan_cards
    assert draft is not None
    assert cards is not None
    assert len(loaded.document.commands) == 0

    draft.set_params(
        draft.new_draft("feature.box"),
        {"size_x": 80.0, "size_y": 80.0, "size_z": 8.0, "center": [0.0, 0.0, 0.0], "mode": "new"},
    )
    step_box = draft.plan().steps[0]
    draft.set_params(
        draft.new_draft("feature.cylinder"),
        {"radius": 10.0, "height": 30.0, "center": [0.0, 0.0, 14.0], "mode": "new"},
    )
    step_cyl = draft.plan().steps[0]
    draft.replace_plan(Plan([step_box, step_cyl]))
    texts = cards.card_texts()
    assert len(texts) == 2 and all("mode=new" in text for text in texts)
    assert draft.plan().status == "draft"

    cards.execute_plan()
    plan = cards.plan
    assert plan is not None
    qtbot.waitUntil(lambda: plan.status == "done" and len(loaded.document.commands) == 2)

    # STEP export of the post-execution state (§8.3 acceptance workflow).
    step_path = tmp_path / "acceptance.step"
    services.formats.resolve(step_path).write(services.kernel, step_path)
    assert step_path.stat().st_size > 0

    # §8.3 batch-level undo semantics: restore the pre-plan state.
    loaded.bus.undo(len(plan.steps))
    assert len(loaded.document.commands) == 0


# -- §8.5 licensing artifacts ------------------------------------------------


def test_license_and_notice_present() -> None:
    assert (REPO / "LICENSE").is_file()
    assert (REPO / "NOTICE").is_file()
    assert "Apache" in (REPO / "README.md").read_text(encoding="utf-8")


# -- platform / encoding -----------------------------------------------------


def test_chinese_paths_and_metadata_round_trip(services: AppServices, tmp_path: Path) -> None:
    """Non-ASCII paths and metadata survive export and archive round-trips."""
    folder = tmp_path / "法兰目录"
    folder.mkdir()
    loaded = new_document(services)
    for step in _plan_steps():
        loaded.bus.execute(
            cast("str", step["id"]),
            cast("dict[str, object]", step["params"]),
            confirmed_by="acceptance-test",
        )
    loaded.document.set_metadata("part_no", "法兰-001")
    loaded.document.set_metadata("notes", "中文备注：含标点。")

    step_file = folder / "法兰.step"
    services.formats.resolve(step_file).write(services.kernel, step_file)
    assert read_step(step_file)[1] == pytest.approx(_expected_volume("A"), abs=1e-6)

    archive = folder / "法兰.mc.json"
    save_document(loaded.document, archive)
    metadata = cast(
        "dict[str, str]",
        cast("dict[str, object]", json.loads(archive.read_text(encoding="utf-8")))["metadata"],
    )
    assert metadata["part_no"] == "法兰-001"
    assert metadata["notes"] == "中文备注：含标点。"
