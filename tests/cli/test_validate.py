# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``validate <file>``: plan (.json) and script (.txt) checks that never
execute, the modeling-line step count, and the shared batch-structure rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from mycad.app import AppServices, build_app
from mycad.cli.__main__ import main
from mycad.cli.session import CliSession
from tests.cli._flange import flange_plan, write_plan

CYLINDER = "cylinder radius=40 height=8 mode=new"
HOLE = (
    "hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 "
    "position.kind=center diameter=20 depth.kind=through_all"
)
BOX = "box size_x=10 size_y=10 size_z=10"


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


def _validate(services: AppServices, path: Path) -> int:
    return CliSession(services).validate_file(path)


def _script(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "s.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_plan(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _validate(services, write_plan(tmp_path / "p.json", flange_plan())) == 0
    assert capsys.readouterr().out.strip() == "valid: plan 3 step(s)"
    assert services.kernel.mass_properties().solid_count == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.json"]


def test_invalid_plan_exit_1(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    plan["steps"] = []
    assert _validate(services, write_plan(tmp_path / "p.json", plan)) == 1
    assert "steps" in capsys.readouterr().err


def test_valid_script_counts_only_modeling_lines(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _script(
        tmp_path,
        "# flange",
        "new",
        "meta part_no=X",
        "begin-batch",
        CYLINDER,
        HOLE,
        "end-batch",
        "",
        BOX,
        "history --json",
        "save out.mc.json",
    )
    assert _validate(services, path) == 0
    assert capsys.readouterr().out.strip() == "valid: script 3 step(s)"
    assert services.kernel.mass_properties().solid_count == 0


@pytest.mark.parametrize(
    ("lines", "code", "needle"),
    [
        (("end-batch",), 2, "end-batch without begin-batch"),
        (("begin-batch", CYLINDER), 2, "unterminated batch"),
        (("begin-batch", "begin-batch"), 2, "nested begin-batch"),
        (("begin-batch", "end-batch"), 2, "empty batch"),
        (("meta part_no",), 2, "usage: meta"),
        (("open model.step",), 2, ".mc.json"),
        (("begin-batch", "cylinder radius=-1 height=8", "end-batch"), 1, "radius"),
        (("frobnicate x=1",), 1, "frobnicate"),
    ],
)
def test_script_errors(
    services: AppServices,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    lines: tuple[str, ...],
    code: int,
    needle: str,
) -> None:
    assert _validate(services, _script(tmp_path, *lines)) == code
    err = capsys.readouterr().err
    assert needle in err
    assert err.count("\n") == 1


def test_unsupported_extension_and_missing_file(tmp_path: Path) -> None:
    other = tmp_path / "model.x_t"
    other.write_text("", encoding="utf-8")
    assert main(["validate", str(other)]) == 2
    assert main(["validate", str(tmp_path / "absent.txt")]) == 2
    assert main(["validate"]) == 2


def test_no_state_leaks_between_invocations(tmp_path: Path) -> None:
    bad = _script(tmp_path, "begin-batch")
    good = write_plan(tmp_path / "p.json", flange_plan())
    assert main(["validate", str(bad)]) == 2
    assert main(["validate", str(good)]) == 0
