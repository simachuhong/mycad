# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""``run --json`` (Appendix B.1/B.3): plan validation, fresh-document batch
execution, metadata write semantics and output naming."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pytest

from mycad.app import AppServices, build_app
from mycad.cli.__main__ import main
from mycad.cli.plans import validate_plan_dict
from mycad.cli.session import CliSession
from tests.cli._flange import FLANGE_VOLUME, flange_plan, write_plan


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


def _run(services: AppServices, path: Path) -> int:
    return CliSession(services).run_json(path)


def _steps(plan: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", plan["steps"])


def test_missing_plan_file_is_usage_error(tmp_path: Path) -> None:
    assert main(["run", "--json", str(tmp_path / "absent.json")]) == 2


def test_corrupt_json_is_one_line_runtime_error(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert _run(services, path) == 1
    err = capsys.readouterr().err
    assert err.startswith("invalid JSON")
    assert err.count("\n") == 1
    assert "Traceback" not in err


def _mutated(**changes: object) -> dict[str, object]:
    plan = flange_plan()
    for key, value in changes.items():
        if value is None:
            del plan[key]
        else:
            plan[key] = value
    return plan


@pytest.mark.parametrize(
    ("plan", "needle"),
    [
        (_mutated(extra=1), "unknown key"),
        (_mutated(metadata=None), "missing required key 'metadata'"),
        (_mutated(steps=None), "missing required key 'steps'"),
        (_mutated(steps=[]), "non-empty array"),
        (_mutated(plan_id="plan-2026-09-17"), "plan_id"),
        (
            _mutated(
                metadata={"part_no": "", "revision": "", "material": "", "source": "", "x": ""}
            ),
            "metadata: unknown key",
        ),
        (_mutated(metadata={"part_no": "P"}), "missing required key"),
        (_mutated(outputs={"archive": "out.json"}), "outputs.archive"),
    ],
)
def test_plan_shape_violations_exit_1(
    services: AppServices,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    plan: dict[str, object],
    needle: str,
) -> None:
    assert _run(services, write_plan(tmp_path / "p.json", plan)) == 1
    assert needle in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == [tmp_path / "p.json"]


def test_affected_object_mismatch_exit_1(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    _steps(plan)[1]["affected_object"] = "edge"
    assert _run(services, write_plan(tmp_path / "p.json", plan)) == 1
    assert "steps[1].affected_object" in capsys.readouterr().err


def test_invalid_params_report_step_path(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    params = _steps(plan)[0]["params"]
    assert isinstance(params, dict)
    params["radius"] = -1
    assert _run(services, write_plan(tmp_path / "p.json", plan)) == 1
    assert "steps[0].params" in capsys.readouterr().err


def test_unknown_command_id_exit_1(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    _steps(plan)[0]["id"] = "feature.nope"
    assert _run(services, write_plan(tmp_path / "p.json", plan)) == 1
    assert "feature.nope" in capsys.readouterr().err


def test_default_plan_ids_are_fresh_hex(services: AppServices, tmp_path: Path) -> None:
    first = validate_plan_dict(flange_plan(), services.registry, base_dir=tmp_path).plan_id
    second = validate_plan_dict(flange_plan(), services.registry, base_dir=tmp_path).plan_id
    assert first != second
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert re.fullmatch(r"[0-9a-f]{32}", second)


def test_flange_plan_default_outputs(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_plan(tmp_path / "flange_plan.json", flange_plan())
    assert _run(services, path) == 0
    expected = [tmp_path / f"flange_plan{ext}" for ext in (".step", ".stl", ".mc.json")]
    assert capsys.readouterr().out.splitlines() == [str(p) for p in expected]
    assert all(p.is_file() for p in expected)
    mass = services.kernel.mass_properties()
    assert mass.volume == pytest.approx(FLANGE_VOLUME, abs=1e-6)
    assert mass.solid_count == 1
    archive = json.loads(expected[2].read_text(encoding="utf-8"))
    assert archive["metadata"] == flange_plan()["metadata"]
    assert [c["confirmed_by"] for c in archive["commands"]] == ["cli-local"] * 3


def test_optional_metadata_written_only_when_present(services: AppServices, tmp_path: Path) -> None:
    with_optional = flange_plan()
    cast("dict[str, str]", with_optional["metadata"]).update(
        part_name="法兰", notes="", revision=""
    )
    assert _run(services, write_plan(tmp_path / "a.json", with_optional)) == 0
    saved = json.loads((tmp_path / "a.mc.json").read_text(encoding="utf-8"))["metadata"]
    assert saved["part_name"] == "法兰"
    assert saved["notes"] == ""
    assert saved["revision"] == ""

    assert _run(services, write_plan(tmp_path / "b.json", flange_plan())) == 0
    saved = json.loads((tmp_path / "b.mc.json").read_text(encoding="utf-8"))["metadata"]
    assert "part_name" not in saved
    assert "notes" not in saved


def test_partial_outputs_only_produce_declared(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    plan["outputs"] = {"step": "only.step"}
    path = write_plan(tmp_path / "p.json", plan)
    assert _run(services, path) == 0
    assert capsys.readouterr().out.splitlines() == [str(tmp_path / "only.step")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["only.step", "p.json"]


def test_chinese_output_paths(services: AppServices, tmp_path: Path) -> None:
    folder = tmp_path / "法兰目录"
    folder.mkdir()
    plan = flange_plan()
    plan["outputs"] = {"step": "法兰.step", "archive": "法兰.mc.json"}
    assert _run(services, write_plan(folder / "计划.json", plan)) == 0
    assert (folder / "法兰.step").stat().st_size > 10240
    assert (folder / "法兰.mc.json").is_file()


def test_batch_failure_rolls_back_without_outputs(
    services: AppServices, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = flange_plan()
    params = _steps(plan)[1]["params"]
    assert isinstance(params, dict)
    params["target_face"] = {"surface": "plane", "axis": "+Z", "rank": 5}
    assert _run(services, write_plan(tmp_path / "p.json", plan)) == 1
    captured = capsys.readouterr()
    assert captured.out.strip() == "rolled back: 0"
    assert "batch failed at step 1 (feature.hole)" in captured.err
    assert captured.err.count("\n") == 1
    assert list(tmp_path.iterdir()) == [tmp_path / "p.json"]
    assert services.kernel.mass_properties().solid_count == 0


def test_runs_are_independent_documents(services: AppServices, tmp_path: Path) -> None:
    path = write_plan(tmp_path / "p.json", flange_plan())
    session = CliSession(services)
    assert session.run_json(path) == 0
    assert session.run_json(path) == 0
    archive = json.loads((tmp_path / "p.mc.json").read_text(encoding="utf-8"))
    assert [c["ordinal"] for c in archive["commands"]] == [0, 1, 2]
