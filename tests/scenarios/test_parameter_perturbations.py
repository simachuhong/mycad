# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit perturbation cases and executable replay/restore evidence."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from mycad.app import build_app, new_document, open_app_document
from mycad.core.exceptions import ValidationError
from mycad.core.measurements import MeasurementRequest
from mycad.core.persistence import save_document
from tests.helpers.step_roundtrip import read_step, read_step_geometry

CATALOG_PATH = Path(__file__).parents[2] / "examples" / "representative_parts.json"
PERTURBATION_PATH = Path(__file__).parents[2] / "examples" / "parameter_perturbations.json"


def _read_records(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return cast("list[dict[str, object]]", data)


def _parameter_value(params: dict[str, object], path: str) -> object:
    current: object = params
    for token in re.findall(r"[^.\[\]]+", path):
        if isinstance(current, dict):
            assert token in current
            current = cast("Mapping[str, object]", current)[token]
        else:
            assert isinstance(current, list)
            current = cast("list[object]", current)[int(token)]
    return current


def _set_parameter(params: dict[str, object], path: str, value: object) -> None:
    tokens = re.findall(r"[^.\[\]]+", path)
    current: object = params
    for token in tokens[:-1]:
        if isinstance(current, dict):
            current = cast("Mapping[str, object]", current)[token]
        else:
            assert isinstance(current, list)
            current = cast("list[object]", current)[int(token)]
    if isinstance(current, dict):
        current[tokens[-1]] = value
    else:
        assert isinstance(current, list)
        current[int(tokens[-1])] = value


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
    assert check.volume_mm3 == pytest.approx(
        record["volume_mm3"], abs=cast("float", record.get("volume_tolerance_mm3", 1e-7))
    )
    mass = kernel.mass_properties()
    assert mass.bbox is not None
    bbox_tol = cast("float", record.get("bbox_tolerance_mm", 1e-7))
    assert mass.bbox.size == pytest.approx(record["bbox_size_mm"], abs=bbox_tol)
    assert mass.bbox.center == pytest.approx(record["bbox_center_mm"], abs=bbox_tol)
    assert kernel.measurement_targets("parallel_plane_separation") or kernel.measurement_targets(
        "cylindrical_face_diameter"
    )
    expected_diameters = cast("list[float]", record["cylindrical_face_diameters_mm"])
    assert set(expected_diameters) <= set(_kernel_cylinder_diameters(kernel))


def _kernel_cylinder_diameters(kernel: object) -> tuple[float, ...]:
    from mycad.geom.kernel import BuildKernel

    adapter = cast("BuildKernel", kernel)
    values: set[float] = set()
    for target in adapter.measurement_targets("cylindrical_face_diameter"):
        result = adapter.measure(
            MeasurementRequest(
                kind="cylindrical_face_diameter",
                references=(target.reference,),
                revision=adapter.geometry_revision,
            )
        )
        assert result.error is None and result.value is not None
        values.add(round(result.value, 7))
    return tuple(sorted(values))


def _assert_same_kernel_geometry(first: object, second: object) -> None:
    from mycad.geom.kernel import BuildKernel

    actual = cast("BuildKernel", first)
    expected = cast("BuildKernel", second)
    actual_check = actual.geometry_check()
    expected_check = expected.geometry_check()
    assert actual_check.is_valid == expected_check.is_valid
    assert actual_check.solid_count == expected_check.solid_count
    assert actual_check.volume_mm3 == pytest.approx(expected_check.volume_mm3, abs=1e-7)
    actual_mass = actual.mass_properties()
    expected_mass = expected.mass_properties()
    if actual_mass.bbox is None or expected_mass.bbox is None:
        assert actual_mass.bbox is None and expected_mass.bbox is None
    else:
        assert actual_mass.bbox.size == pytest.approx(expected_mass.bbox.size, abs=1e-7)
        assert actual_mass.bbox.center == pytest.approx(expected_mass.bbox.center, abs=1e-7)
    assert _kernel_cylinder_diameters(actual) == _kernel_cylinder_diameters(expected)


def test_perturbation_catalog_has_108_linked_explicit_cases() -> None:
    catalog = _read_records(CATALOG_PATH)
    perturbations = _read_records(PERTURBATION_PATH)
    case_ids = {str(case["id"]) for case in catalog}
    perturbation_ids = [str(record["id"]) for record in perturbations]

    assert len(perturbations) >= 100
    assert len(perturbation_ids) == len(set(perturbation_ids))
    assert {record["catalog_case_id"] for record in perturbations} <= case_ids
    assert {record["status"] for record in perturbations} == {"executable"}
    catalog_by_id = {str(case["id"]): case for case in catalog}
    for record in perturbations:
        chain = cast("list[dict[str, object]]", record["command_chain"])
        assert [entry["id"] for entry in chain] == catalog_by_id[str(record["catalog_case_id"])][
            "commands"
        ]
        assert all(isinstance(entry["params"], dict) for entry in chain)
        assert all(isinstance(entry["version"], int) for entry in chain)
        ordinal = cast("int", record["target_ordinal"])
        assert 0 <= ordinal < len(chain)
        assert chain[ordinal]["id"] == record["target_command_id"]
        params = cast("dict[str, object]", chain[ordinal]["params"])
        assert isinstance(record["parameter_path"], str) and record["parameter_path"]
        assert _parameter_value(params, record["parameter_path"]) == record["baseline_value"]
        assert record["baseline_value"] != record["perturbation_value"]
        for key in ("expected", "baseline_expected"):
            expected = cast("dict[str, object]", record[key])
            assert all(
                name in expected for name in ("volume_mm3", "bbox_size_mm", "bbox_center_mm")
            )
        assert isinstance(record["restore_action"], str) and record["restore_action"]
    for case in catalog:
        linked = cast("list[str]", case.get("perturbation_ids", []))
        assert len(linked) == (6 if case["status"] == "supported" else 0)
        assert set(linked) <= set(perturbation_ids)


@pytest.mark.parametrize(
    "scenario",
    _read_records(PERTURBATION_PATH),
    ids=lambda record: str(record["id"]),
)
def test_perturbation_replays_and_restores(scenario: dict[str, object]) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    chain = cast("list[dict[str, object]]", scenario["command_chain"])
    for command in chain:
        loaded.bus.execute(
            cast("str", command["id"]),
            deepcopy(cast("dict[str, object]", command["params"])),
            "scenario",
            version=cast("int", command["version"]),
        )
    ordinal = cast("int", scenario["target_ordinal"])
    baseline = deepcopy(loaded.document.commands[ordinal].params)
    _assert_expected_geometry(services.kernel, scenario["baseline_expected"])

    changed = deepcopy(baseline)
    _set_parameter(changed, cast("str", scenario["parameter_path"]), scenario["perturbation_value"])
    timestamp = loaded.document.commands[ordinal].timestamp_utc
    loaded.bus.edit_and_replay(ordinal, changed, "scenario", cast("str", scenario["id"]))
    _assert_expected_geometry(services.kernel, scenario["expected"])
    assert loaded.document.commands[ordinal].timestamp_utc == timestamp
    assert len(loaded.document.commands[ordinal].amendments) == 1

    loaded.bus.edit_and_replay(ordinal, baseline, "scenario", "restore declared baseline")
    _assert_expected_geometry(services.kernel, scenario["baseline_expected"])


@pytest.mark.parametrize(
    "case",
    [case for case in _read_records(CATALOG_PATH) if case["status"] == "supported"],
    ids=lambda case: str(case["id"]),
)
def test_supported_part_lifecycle_roundtrip(case: dict[str, object], tmp_path: Path) -> None:
    scenario = next(
        record
        for record in _read_records(PERTURBATION_PATH)
        if record["catalog_case_id"] == case["id"]
    )
    services = build_app(discoverers=[])
    loaded = new_document(services)
    chain = cast("list[dict[str, object]]", scenario["command_chain"])
    for command in chain:
        loaded.bus.execute(
            cast("str", command["id"]),
            deepcopy(cast("dict[str, object]", command["params"])),
            "scenario",
            version=cast("int", command["version"]),
        )
    assert services.kernel.measurement_targets(
        "parallel_plane_separation"
    ) or services.kernel.measurement_targets("cylindrical_face_diameter")
    ordinal = cast("int", scenario["target_ordinal"])
    changed = deepcopy(loaded.document.commands[ordinal].params)
    _set_parameter(changed, cast("str", scenario["parameter_path"]), scenario["perturbation_value"])
    loaded.bus.edit_and_replay(ordinal, changed, "scenario", "supported part lifecycle")
    _assert_expected_geometry(services.kernel, scenario["expected"])
    measured = services.kernel.measure(
        MeasurementRequest(kind="body_volume", revision=services.kernel.geometry_revision)
    )
    assert measured.error is None
    expected = cast("dict[str, object]", scenario["expected"])
    assert measured.value == pytest.approx(
        expected["volume_mm3"], abs=cast("float", expected.get("volume_tolerance_mm3", 1e-7))
    )

    loaded.bus.undo()
    prefix_services = build_app(discoverers=[])
    prefix_document = new_document(prefix_services)
    for prefix_ordinal, command in enumerate(chain[:-1]):
        params = (
            changed if prefix_ordinal == ordinal else cast("dict[str, object]", command["params"])
        )
        prefix_document.bus.execute(
            cast("str", command["id"]),
            deepcopy(params),
            "scenario",
            version=cast("int", command["version"]),
        )
    _assert_same_kernel_geometry(services.kernel, prefix_services.kernel)
    loaded.bus.redo()
    _assert_expected_geometry(services.kernel, expected)

    archive = tmp_path / f"{case['id']}.mc.json"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    _assert_expected_geometry(services.kernel, expected)
    assert len(reopened.document.commands) == len(chain)

    step_path = tmp_path / f"{case['id']}.step"
    services.formats.resolve(step_path).write(services.kernel, step_path)
    solids, step_volume = read_step(step_path)
    assert solids == 1
    assert step_volume == pytest.approx(
        expected["volume_mm3"],
        abs=max(1e-5, cast("float", expected.get("volume_tolerance_mm3", 0.0))),
    )
    step_geometry = read_step_geometry(step_path)
    assert step_geometry.is_valid
    assert step_geometry.bbox_size_mm == pytest.approx(expected["bbox_size_mm"], abs=1e-5)
    assert step_geometry.bbox_center_mm == pytest.approx(expected["bbox_center_mm"], abs=1e-5)
    expected_diameters = cast("list[float]", expected["cylindrical_face_diameters_mm"])
    assert set(expected_diameters) <= set(step_geometry.cylindrical_face_diameters_mm)


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
