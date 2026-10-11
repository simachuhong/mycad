# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``history --json``: archive-aligned audit view and the text <-> JSON
equivalence loop (to_cli of each entry parses back to the same params)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from mycad.app import AppServices, build_app, new_document
from mycad.cli.session import CliSession
from mycad.commands.grammar import parse_line, to_cli
from mycad.commands.validation import normalize_params, validate_params
from mycad.core.persistence import save_document

FLANGE_LINES = (
    "cylinder radius=40 height=8 mode=new",
    "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
    "position.kind=center diameter=20 depth.kind=through_all",
    "hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z "
    "base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 "
    "base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 "
    "pattern.count=4 pattern.start_angle_deg=0",
)
SEVEN_KEYS = {"ordinal", "id", "version", "params", "timestamp_utc", "confirmed_by"}
HOLE_PARAMS: dict[str, object] = {
    "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
    "position": {"kind": "center"},
    "diameter": 20,
    "depth": {"kind": "through_all"},
}


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def session(services: AppServices) -> CliSession:
    return CliSession(services)


def _history(session: CliSession, capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    capsys.readouterr()
    assert session.execute_line("history --json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"commands"}
    return cast("list[dict[str, object]]", payload["commands"])


def test_empty_history(session: CliSession, capsys: pytest.CaptureFixture[str]) -> None:
    assert _history(session, capsys) == []
    session.execute_line("new")
    assert _history(session, capsys) == []


def test_cli_entries_shape_and_order(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    for line in FLANGE_LINES:
        assert session.execute_line(line) == 0
    entries = _history(session, capsys)
    assert [e["ordinal"] for e in entries] == [0, 1, 2]
    assert [e["id"] for e in entries] == [
        "feature.cylinder",
        "feature.hole",
        "feature.hole_pattern",
    ]
    for entry in entries:
        assert set(entry) == SEVEN_KEYS
        assert entry["confirmed_by"] == "cli-local"
        assert isinstance(entry["version"], int)


def test_python_api_actor_null_and_amendments_only_when_present(
    session: CliSession,
    services: AppServices,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 40, "height": 8})
    loaded.bus.execute("feature.hole", HOLE_PARAMS)
    loaded.bus.edit_and_replay(0, {"radius": 50, "height": 10}, actor="history-test", reason="r")
    archive = tmp_path / "doc.mc.json"
    save_document(loaded.document, archive)
    assert session.execute_line(f"open {archive}") == 0
    first, second = _history(session, capsys)
    assert first["confirmed_by"] is None
    assert set(first) == SEVEN_KEYS | {"amendments"}
    (amendment,) = cast("list[dict[str, object]]", first["amendments"])
    assert amendment["actor"] == "history-test"
    assert amendment["reason"] == "r"
    assert cast("dict[str, object]", amendment["from_params"])["radius"] == 40
    assert set(second) == SEVEN_KEYS


def test_bad_history_argument_is_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.execute_line("history --xml") == 2
    assert "history [--json]" in capsys.readouterr().err


def test_text_json_round_trip(
    session: CliSession, services: AppServices, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = services.registry
    for line in FLANGE_LINES:
        session.execute_line(line)
    texts: list[str] = []
    for entry, original in zip(_history(session, capsys), FLANGE_LINES, strict=True):
        command_id = cast("str", entry["id"])
        params = cast("dict[str, object]", entry["params"])
        text = to_cli(command_id, params, registry)
        texts.append(text)
        parsed_id, parsed = parse_line(text, registry)
        assert parsed_id == command_id
        assert normalize_params(parsed) == normalize_params(params)
        original_id, original_params = parse_line(original, registry)
        filled = validate_params(
            registry.get(original_id), original_params, defs=registry.schema_defs
        )
        assert normalize_params(filled) == normalize_params(params)
    assert "center=" in texts[0]
    assert "mode=new" in texts[0]
