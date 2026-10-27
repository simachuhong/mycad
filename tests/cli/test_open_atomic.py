# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Failed CLI opens preserve the active document and its geometry kernel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from mycad.app import build_app, new_document
from mycad.cli.session import CliSession
from mycad.core.persistence import save_document
from tests.helpers.step_roundtrip import read_step

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.persistence import LoadedDocument


def _write_archive(path: Path, *, invalid_second_command: bool = False) -> None:
    source = build_app(discoverers=[])
    candidate = new_document(source)
    for size_x in (20.0, 30.0):
        candidate.bus.execute(
            "feature.box",
            {"size_x": size_x, "size_y": 10.0, "size_z": 10.0},
        )
    save_document(candidate.document, path)
    if invalid_second_command:
        archive = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
        commands = cast("list[object]", archive["commands"])
        second = cast("dict[str, object]", commands[1])
        params = cast("dict[str, object]", second["params"])
        params["size_x"] = -1.0
        path.write_text(json.dumps(archive), encoding="utf-8")


@pytest.fixture
def services() -> AppServices:
    return build_app(discoverers=[])


def test_failed_open_preserves_save_export_and_redo(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original_path = tmp_path / "original.mc.json"
    bad_path = tmp_path / "bad.mc.json"
    step_path = tmp_path / "original.step"
    _write_archive(bad_path, invalid_second_command=True)

    replacements: list[LoadedDocument | None] = []
    session = CliSession(services, on_replace_doc=replacements.append)
    assert session.execute_line("new") == 0
    assert session.execute_line("box size_x=10 size_y=10 size_z=10") == 0
    assert session.execute_line(f"save {original_path}") == 0
    active = replacements[-1]
    assert active is not None
    assert session.execute_line("cylinder radius=1 height=2") == 0
    assert session.execute_line("undo") == 0
    assert active.document.is_dirty
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)

    assert session.execute_line(f"open {bad_path}") == 1
    capsys.readouterr()
    assert replacements == [active]
    assert active.document.is_dirty
    assert len(active.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)

    assert session.execute_line("save") == 0
    saved = cast("dict[str, object]", json.loads(original_path.read_text(encoding="utf-8")))
    commands = cast("list[object]", saved["commands"])
    assert len(commands) == 1
    assert session.execute_line(f"export {step_path}") == 0
    solids, volume = read_step(step_path)
    assert solids == 1
    assert volume == pytest.approx(1000.0, abs=1e-6)

    assert session.execute_line("redo") == 0
    assert services.kernel.mass_properties().volume == pytest.approx(2.0 * 3.141592653589793)


def test_successful_open_commits_one_session_replacement(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "opened.mc.json"
    _write_archive(archive)
    replacements: list[LoadedDocument | None] = []
    session = CliSession(services, on_replace_doc=replacements.append)

    assert session.execute_line(f"open {archive}") == 0
    capsys.readouterr()

    assert len(replacements) == 1
    opened = replacements[0]
    assert opened is not None
    assert len(opened.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(3000.0)
    opened.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(2000.0)
