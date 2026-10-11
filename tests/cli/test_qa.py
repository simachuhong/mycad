# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""QA matrix (T10 QA scenarios): the full flange REPL sequence end to end,
plus the failure-side exit-code contract."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from mycad.app import build_app
from mycad.cli.__main__ import main
from mycad.cli.session import CliSession

FLANGE_SEQUENCE = """new
begin-batch
cylinder radius=40 height=8 mode=new
hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 position.kind=center diameter=20 depth.kind=through_all
hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 pattern.count=4 pattern.start_angle_deg=0
end-batch
export {tmp}/flange.step
export {tmp}/flange.stl
save {tmp}/flange.mc.json
history --json
undo 3
save {tmp}/after_undo.mc.json
quit
"""


def test_happy_flange_repl_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(FLANGE_SEQUENCE.format(tmp=tmp_path)))
    assert main([]) == 0
    out = capsys.readouterr().out
    step_path = tmp_path / "flange.step"
    assert step_path.stat().st_size > 10240
    assert (tmp_path / "flange.stl").stat().st_size > 1024
    history_line = next(line for line in out.splitlines() if line.startswith('{"commands"'))
    commands = json.loads(history_line)["commands"]
    assert [c["id"] for c in commands] == [
        "feature.cylinder",
        "feature.hole",
        "feature.hole_pattern",
    ]
    assert all(c["confirmed_by"] == "cli-local" for c in commands)

    reader = CliSession(services_a := build_app(discoverers=[]))
    assert reader.execute_line(f"open {tmp_path / 'flange.mc.json'}") == 0
    mass = services_a.kernel.mass_properties()
    assert mass.volume == pytest.approx(36794.3331588437, abs=1e-6)
    assert mass.solid_count == 1

    reader = CliSession(services_b := build_app(discoverers=[]))
    assert reader.execute_line(f"open {tmp_path / 'after_undo.mc.json'}") == 0
    mass = services_b.kernel.mass_properties()
    assert mass.volume == 0.0
    assert mass.solid_count == 0


def test_failure_unknown_subcommand() -> None:
    assert main(["frobnicate"]) == 2


def test_failure_open_missing_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = CliSession(build_app(discoverers=[]))
    assert session.execute_line("open /nonexistent/doc.mc.json") == 2
    assert "file not found" in capsys.readouterr().err


def _script(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "s.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_failure_batch_rollback_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script = _script(
        tmp_path,
        "new",
        "begin-batch",
        "cylinder radius=40 height=8 mode=new",
        "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
        "position.kind=center diameter=-5 depth.kind=through_all",
        "end-batch",
    )
    assert main(["run", str(script)]) == 1
    captured = capsys.readouterr()
    assert "rolled back: 0" in captured.out
    assert "batch failed at step 1" in captured.err
    assert "feature.hole" in captured.err
    assert list(tmp_path.iterdir()) == [script]


def test_failure_unknown_modeling_id_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script(tmp_path, "frobnicate x=1")
    assert main(["run", str(script)]) == 1
    assert "frobnicate" in capsys.readouterr().err


def test_failure_run_json_corrupt_is_single_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    assert main(["run", "--json", str(path)]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.count("\n") == 1
