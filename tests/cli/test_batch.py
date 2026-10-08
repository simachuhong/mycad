# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Batch transactions (§3.4): the pinned flange batch, rollback semantics and
the CliSyntaxError structure matrix (nested/missing/empty/unterminated)."""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import pytest

from mycad.app import AppServices, build_app
from mycad.cli.session import CliSession

FLANGE_CYLINDER = "cylinder radius=40 height=8 mode=new"
FLANGE_HOLE = (
    "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
    "position.kind=center diameter=20 depth.kind=through_all"
)
FLANGE_HOLE_PATTERN = (
    "hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z "
    "base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 "
    "base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 "
    "pattern.count=4 pattern.start_angle_deg=0"
)
FLANGE_VOLUME = math.pi * 8.0 * (40.0**2 - 10.0**2 - 4 * 3.0**2)


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def session(services: AppServices) -> CliSession:
    return CliSession(services)


def test_flange_batch_volume_history_and_confirmed_by(
    session: CliSession, services: AppServices, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("begin-batch") == 0
    assert session.execute_line(FLANGE_CYLINDER) == 0
    assert session.execute_line(FLANGE_HOLE) == 0
    assert session.execute_line(FLANGE_HOLE_PATTERN) == 0
    assert session.execute_line("end-batch") == 0
    mass = services.kernel.mass_properties()
    assert mass.volume == pytest.approx(FLANGE_VOLUME, abs=1e-6)
    session.execute_line("history")
    out = capsys.readouterr().out
    assert out.count("[confirmed_by=cli-local]") == 3
    assert ": feature.cylinder " in out
    assert ": feature.hole " in out
    assert ": feature.hole_pattern " in out


def test_batch_rollback_on_second_step_invalid_params(
    session: CliSession, services: AppServices, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("begin-batch")
    session.execute_line(FLANGE_CYLINDER)
    session.execute_line(
        "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
        "position.kind=center diameter=-5 depth.kind=through_all"
    )
    assert session.execute_line("end-batch") == 1
    captured = capsys.readouterr()
    assert "rolled back: 0" in captured.out
    assert "batch failed at step 1" in captured.err
    assert "feature.hole" in captured.err
    assert services.kernel.mass_properties().solid_count == 0  # nothing survived


def test_batch_first_step_failure_has_no_rollback_line(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("begin-batch")
    session.execute_line(
        "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
        "position.kind=center diameter=-5 depth.kind=through_all"
    )
    assert session.execute_line("end-batch") == 1
    captured = capsys.readouterr()
    assert "rolled back" not in captured.out
    assert "batch failed at step 0" in captured.err


def test_nested_begin_batch_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("begin-batch") == 0
    assert session.execute_line("begin-batch") == 2
    assert capsys.readouterr().err.strip() == "nested begin-batch"


def test_end_batch_without_begin_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    assert session.execute_line("end-batch") == 2
    assert capsys.readouterr().err.strip() == "end-batch without begin-batch"


def test_empty_batch_end_is_a_usage_error(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("begin-batch")
    assert session.execute_line("end-batch") == 2
    assert "empty batch" in capsys.readouterr().err


def test_unterminated_batch_in_script_executes_nothing(
    session: CliSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "unterminated.txt"
    script.write_text("new\nbegin-batch\ncylinder radius=5 height=5 mode=new\n", encoding="utf-8")
    assert session.run_script(script) == 2
    capsys.readouterr()
    session.execute_line("history")
    assert ": feature.cylinder" not in capsys.readouterr().out


def test_unknown_command_id_inside_batch_aborts_the_batch(
    session: CliSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session.execute_line("new")
    session.execute_line("begin-batch")
    assert session.execute_line("frobnicate x=1") == 1
    assert session.execute_line("end-batch") == 2  # batch was aborted -> no begin
    assert session.execute_line("box size_x=10 size_y=10 size_z=10") == 0
    session.execute_line("history")
    assert ": feature.box " in capsys.readouterr().out


def test_repl_batch_error_then_continuation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mycad.cli.__main__ import main

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "new\nbegin-batch\nfrobnicate x=1\nbox size_x=10 size_y=10 size_z=10\nhistory\nquit\n"
        ),
    )
    assert main([]) == 1
    out = capsys.readouterr().out
    assert ": feature.box " in out  # executed normally after the batch aborted


def test_unterminated_batch_in_repl_after_quit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mycad.cli.__main__ import main

    monkeypatch.setattr(
        sys, "stdin", io.StringIO("new\nbegin-batch\ncylinder radius=5 height=5 mode=new\nquit\n")
    )
    assert main([]) == 2
    assert capsys.readouterr().err.strip() == "unterminated batch"


def test_flange_script_through_run_script(
    session: CliSession, services: AppServices, tmp_path: Path
) -> None:
    script = tmp_path / "flange.txt"
    script.write_text(
        "\n".join(
            [
                "# flange acceptance script (T10a batch slice)",
                "new",
                "begin-batch",
                FLANGE_CYLINDER,
                FLANGE_HOLE,
                FLANGE_HOLE_PATTERN,
                "end-batch",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert session.run_script(script) == 0
    assert services.kernel.mass_properties().volume == pytest.approx(FLANGE_VOLUME, abs=1e-6)
