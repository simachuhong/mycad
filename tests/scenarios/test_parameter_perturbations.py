# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit perturbation cases and executable replay/restore evidence."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import ValidationError
from mycad.core.measurements import MeasurementRequest
from mycad.core.persistence import save_document
from tests.helpers.step_roundtrip import read_step

CATALOG_PATH = Path(__file__).parents[2] / "examples" / "representative_parts.json"
PERTURBATION_PATH = Path(__file__).parents[2] / "examples" / "parameter_perturbations.json"
GATED_PHASE2_TASKS = {f"P2-{number}" for number in range(32, 38)}


def _read_records(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return cast("list[dict[str, object]]", data)


def _set_parameter(params: dict[str, object], path: str, value: object) -> None:
    if "[" not in path:
        params[path] = value
        return
    key, raw_index = path[:-1].split("[")
    vector = params[key]
    assert isinstance(vector, list)
    vector[int(raw_index)] = value


def _assert_expected_geometry(kernel: object, expected: object) -> None:
    from mycad.geom.kernel import BuildKernel

    # test_kernel_version deliberately reloads the geom module; the app's
    # already-created adapter may therefore have the prior class identity.
    # Keep this as a structural probe instead of a runtime identity check.
    kernel = cast("BuildKernel", kernel)
    assert isinstance(expected, dict)
    record = cast("dict[str, object]", expected)
    check = kernel.geometry_check()
    assert check.is_valid
    assert check.solid_count == 1
    assert check.volume_mm3 == pytest.approx(record["volume_mm3"], abs=1e-7)
    mass = kernel.mass_properties()
    assert mass.bbox is not None
    assert mass.bbox.size == pytest.approx(record["bbox_size_mm"], abs=1e-7)
    assert mass.bbox.center == pytest.approx(record["bbox_center_mm"], abs=1e-7)


def test_perturbation_catalog_has_108_linked_explicit_cases() -> None:
    catalog = _read_records(CATALOG_PATH)
    perturbations = _read_records(PERTURBATION_PATH)
    case_ids = {str(case["id"]) for case in catalog}
    perturbation_ids = [str(record["id"]) for record in perturbations]

    assert len(perturbations) >= 100
    assert len(perturbation_ids) == len(set(perturbation_ids))
    assert {record["catalog_case_id"] for record in perturbations} <= case_ids
    assert {record["status"] for record in perturbations} == {"executable", "gated"}
    for record in perturbations:
        assert isinstance(record["parameter_path"], str) and record["parameter_path"]
        assert record["baseline_value"] != record["perturbation_value"]
        assert isinstance(record["expected"], dict) and record["expected"]
        assert isinstance(record["restore_action"], str) and record["restore_action"]
        if record["status"] == "gated":
            assert set(cast("list[str]", record["gated_by"])) == GATED_PHASE2_TASKS
    for case in catalog:
        linked = cast("list[str]", case.get("perturbation_ids", []))
        assert len(linked) == (6 if case["status"] == "supported" else 0)
        assert set(linked) <= set(perturbation_ids)


@pytest.mark.parametrize(
    "scenario",
    [record for record in _read_records(PERTURBATION_PATH) if record["status"] == "executable"],
    ids=lambda record: str(record["id"]),
)
def test_primitive_perturbation_replays_and_restores(scenario: dict[str, object]) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    command = cast("dict[str, object]", cast("list[object]", scenario["command_chain"])[0])
    baseline = deepcopy(cast("dict[str, object]", command["params"]))
    command_id = cast("str", command["id"])
    loaded.bus.execute(command_id, baseline, "scenario")
    _assert_expected_geometry(services.kernel, scenario["baseline_expected"])

    changed = deepcopy(baseline)
    _set_parameter(changed, cast("str", scenario["parameter_path"]), scenario["perturbation_value"])
    timestamp = loaded.document.commands[0].timestamp_utc
    loaded.bus.edit_and_replay(0, changed, "scenario", cast("str", scenario["id"]))
    _assert_expected_geometry(services.kernel, scenario["expected"])
    assert loaded.document.commands[0].timestamp_utc == timestamp
    assert len(loaded.document.commands[0].amendments) == 1

    loaded.bus.edit_and_replay(0, baseline, "scenario", "restore declared baseline")
    _assert_expected_geometry(services.kernel, scenario["baseline_expected"])


def test_zero_thickness_catalog_case_is_rejected_without_history_mutation() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)

    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "feature.box", {"size_x": 20.0, "size_y": 10.0, "size_z": 0.0}, "scenario"
        )

    assert loaded.document.commands == ()
    assert services.kernel.geometry_check().solid_count == 0


def test_flange_edit_undo_redo_archive_and_step_roundtrip(tmp_path: Path) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    flange_commands: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "feature.cylinder",
            {"radius": 40.0, "height": 8.0, "center": [0.0, 0.0, 0.0], "mode": "new"},
        ),
        (
            "feature.hole",
            {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                "position": {"kind": "center"},
                "diameter": 20.0,
                "depth": {"kind": "through_all"},
            },
        ),
        (
            "feature.hole_pattern",
            {
                "base_hole": {
                    "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                    "position": {"kind": "center"},
                    "diameter": 6.0,
                    "depth": {"kind": "through_all"},
                },
                "pattern": {
                    "kind": "polar",
                    "radius": 25.0,
                    "count": 4,
                    "start_angle_deg": 0.0,
                },
            },
        ),
    )
    for command_id, params in flange_commands:
        loaded.bus.execute(command_id, params, "scenario")
    original_volume = math.pi * 8.0 * (40.0**2 - 10.0**2 - 4 * 3.0**2)
    assert services.kernel.geometry_check().volume_mm3 == pytest.approx(original_volume, abs=1e-7)
    diameter_target = next(
        target
        for target in services.kernel.measurement_targets("cylindrical_face_diameter")
        if "d=6 mm" in target.label
    )
    diameter = services.kernel.measure(
        MeasurementRequest(
            kind="cylindrical_face_diameter",
            references=(diameter_target.reference,),
            revision=services.kernel.geometry_revision,
        )
    )
    assert diameter.value == pytest.approx(6.0)

    edited_params = loaded.document.commands[0].params
    edited_params["radius"] = 42.0
    loaded.bus.edit_and_replay(0, edited_params, "scenario", "outer diameter perturbation")
    edited_volume = math.pi * 8.0 * (42.0**2 - 10.0**2 - 4 * 3.0**2)
    assert services.kernel.geometry_check().volume_mm3 == pytest.approx(edited_volume, abs=1e-7)
    loaded.bus.undo()
    without_pattern_volume = math.pi * 8.0 * (42.0**2 - 10.0**2)
    assert services.kernel.geometry_check().volume_mm3 == pytest.approx(
        without_pattern_volume, abs=1e-7
    )
    loaded.bus.redo()
    assert services.kernel.geometry_check().volume_mm3 == pytest.approx(edited_volume, abs=1e-7)

    archive = tmp_path / "perturbed-flange.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert services.kernel.geometry_check().volume_mm3 == pytest.approx(edited_volume, abs=1e-7)
    assert reopened.document.commands[0].amendments == loaded.document.commands[0].amendments
    step_path = tmp_path / "perturbed-flange.step"
    services.formats.resolve(step_path).write(services.kernel, step_path)
    solids, step_volume = read_step(step_path)
    assert solids == 1
    assert step_volume == pytest.approx(edited_volume, abs=1e-6)
