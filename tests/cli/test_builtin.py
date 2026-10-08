# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Builtin document commands (§3.3): new/open/save/export/meta/undo/redo/
history driven through ``CliSession.execute_line``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycad.app import AppServices, build_app
from mycad.cli.session import CliSession

BOX_LINE = "box size_x=10 size_y=10 size_z=10"


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def session(services: AppServices) -> CliSession:
    return CliSession(services)


def test_new_then_modeling_line_succeeds(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.execute_line("new") == 0
    assert session.execute_line("cylinder radius=5 height=10 mode=new") == 0
    assert "new document" in capsys.readouterr().out


def test_meta_roundtrip_and_echo(session: CliSession, capsys: pytest.CaptureFixture[str]) -> None:
    session.execute_line("new")
    assert session.execute_line("meta part_no=ABC-123") == 0
    assert "part_no=ABC-123" in capsys.readouterr().out


def test_meta_strips_surrounding_quotes(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line('meta material="Steel 42CrMo4"') == 0
    assert "material=Steel 42CrMo4" in capsys.readouterr().out


def test_meta_unknown_key_is_a_runtime_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("meta color=red") == 1
    assert "unknown metadata key" in capsys.readouterr().err


def test_meta_missing_equals_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("meta part_no") == 2
    assert capsys.readouterr().err.strip() == "usage: meta <key>=<value>"


def test_save_without_path_and_no_archive(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("save") == 2
    assert capsys.readouterr().err.strip() == "save requires a path for an unsaved document"


def test_save_explicit_path_then_implicit_overwrite(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "part.mc.json"
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    assert session.execute_line(f"save {archive}") == 0
    assert str(archive) in capsys.readouterr().out
    session.execute_line(BOX_LINE)
    assert session.execute_line("save") == 0  # implicit overwrite of the archive
    payload = json.loads(archive.read_text(encoding="utf-8"))
    assert len(payload["commands"]) == 2


def test_save_wrong_extension_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("save /tmp/whatever.step") == 2
    assert "save only supports .mc.json" in capsys.readouterr().err


def test_open_wrong_extension_never_touches_the_format_resolver(
    services: AppServices,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resolve_calls: list[Path] = []
    real_resolve = services.formats.resolve

    def spy(path: Path) -> object:
        resolve_calls.append(path)
        return real_resolve(path)

    monkeypatch.setattr(services.formats, "resolve", spy)
    session = CliSession(services)
    assert session.execute_line("open /tmp/whatever.step") == 2
    assert resolve_calls == []
    assert capsys.readouterr().err.strip() == "open only supports .mc.json archives"


def test_open_missing_file_is_a_usage_error(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert session.execute_line(f"open {tmp_path / 'nope.mc.json'}") == 2
    assert "file not found" in capsys.readouterr().err


def test_open_roundtrip_preserves_history(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "round.mc.json"
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    session.execute_line(f"save {archive}")
    session.execute_line("new")  # wipe the in-memory document
    assert session.execute_line(f"open {archive}") == 0
    session.execute_line("history")
    out = capsys.readouterr().out
    assert "opened" in out
    assert out.count(": feature.box ") == 1


def test_export_step_and_stl_produce_files(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("cylinder radius=5 height=10 mode=new")
    for name in ("part.step", "part.stl"):
        target = tmp_path / name
        assert session.execute_line(f"export {target}") == 0
        assert target.is_file()
        assert target.stat().st_size > 0
        assert str(target) in capsys.readouterr().out


def test_export_unknown_extension_is_a_runtime_error(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("cylinder radius=5 height=10 mode=new")
    assert session.execute_line(f"export {tmp_path / 'part.obj'}") == 1
    assert "obj" in capsys.readouterr().err


def test_undo_redo_counts_and_invalid_history(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    assert session.execute_line("undo") == 0
    session.execute_line("history")
    assert ": feature.box" not in capsys.readouterr().out
    assert session.execute_line("redo") == 0
    session.execute_line("history")
    assert ": feature.box" in capsys.readouterr().out
    assert session.execute_line("undo 5") == 1  # history has 1, requested 5
    assert session.execute_line("undo abc") == 1  # malformed count
    assert session.execute_line("redo 0") == 1
    assert capsys.readouterr().err != ""


def test_history_line_format(session: CliSession, capsys: pytest.CaptureFixture[str]) -> None:
    session.execute_line("new")
    session.execute_line(BOX_LINE)
    session.execute_line("history")
    (history_line,) = [
        line for line in capsys.readouterr().out.splitlines() if ": feature.box " in line
    ]
    assert history_line.startswith("0: feature.box box ")
    assert "center=[0,0,0]" in history_line
    assert history_line.endswith("  [confirmed_by=cli-local]")


def test_history_is_empty_for_a_fresh_document(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("history") == 0
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if ": feature." in line] == []
