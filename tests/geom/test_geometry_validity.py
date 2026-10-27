# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""BREP validity contract at the geometry-kernel commit boundary."""

from __future__ import annotations

import pytest
from build123d import Box, Compound, Part, Pos

from mycad.core.exceptions import GeometryBuildError
from mycad.core.geometry_checks import GeometryCheckIssue, GeometryCheckResult
from mycad.geom import kernel as kernel_module
from mycad.geom.kernel import BuildKernel
from mycad.geom.query import validate_result


def test_empty_result_is_valid_and_distinct_from_invalid_geometry() -> None:
    result = validate_result(None, "modify.boolean_cut")

    assert result == GeometryCheckResult(
        is_valid=True,
        solid_count=0,
        volume_mm3=0.0,
        issues=(),
    )


def test_valid_single_solid_reports_volume() -> None:
    result = validate_result(Box(10, 10, 10), "feature.box", require_single_solid=True)

    assert result.is_valid
    assert result.solid_count == 1
    assert result.volume_mm3 == pytest.approx(1000.0)
    assert result.issues == ()


def test_valid_multiple_solids_are_not_rejected_for_count_alone() -> None:
    part = Compound(children=[Box(2, 2, 2), Pos(5, 0, 0) * Box(3, 3, 3)])

    result = validate_result(part, "feature.box", require_single_solid=False)

    assert result.is_valid
    assert result.solid_count == 2
    assert result.volume_mm3 == pytest.approx(35.0)


def test_invalid_brep_returns_issue_with_command_and_check_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part = Box(2, 2, 2)
    monkeypatch.setattr(type(part), "is_valid", property(lambda _part: False))

    result = validate_result(part, "feature.hole")

    assert not result.is_valid
    assert result.issues == (
        GeometryCheckIssue(
            code="invalid-brep",
            message="BREP validity check failed",
            command_id="feature.hole",
            parameter_path=None,
        ),
    )


def test_invalid_result_is_rejected_before_kernel_snapshot_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = BuildKernel()
    part = Box(2, 2, 2)
    monkeypatch.setattr(type(part), "is_valid", property(lambda _part: False))

    def invalid_primitive_result(*_args: object, **_kwargs: object) -> Part:
        return part

    monkeypatch.setattr(kernel_module, "apply_primitive", invalid_primitive_result)

    with pytest.raises(GeometryBuildError, match="invalid-brep") as excinfo:
        kernel.apply("feature.box", {"size_x": 2, "size_y": 2, "size_z": 2})

    assert excinfo.value.command_id == "feature.box"
    assert kernel.viewport_state_ids() == ()


def test_new_primitive_requires_one_solid_but_empty_cut_is_allowed() -> None:
    multiple = Compound(children=[Box(2, 2, 2), Pos(5, 0, 0) * Box(3, 3, 3)])
    new_result = validate_result(multiple, "feature.box", require_single_solid=True)
    empty_cut = validate_result(None, "modify.boolean_cut")

    assert not new_result.is_valid
    assert new_result.issues[0].code == "solid-count"
    assert empty_cut.is_valid


def test_near_tangent_addition_keeps_valid_brep() -> None:
    kernel = BuildKernel()
    kernel.apply(
        "feature.cylinder",
        {"radius": 5, "height": 10, "mode": "new", "center": [0, 0, 0]},
    )

    kernel.apply(
        "feature.cylinder",
        {"radius": 5, "height": 10, "mode": "add", "center": [9.999, 0, 0]},
    )

    assert kernel.geometry_check().is_valid


def test_coplanar_touching_cut_keeps_original_valid_brep() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})

    kernel.apply(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 10, "size_y": 10, "size_z": 10, "center": [10, 0, 0]}},
    )

    check = kernel.geometry_check()
    assert check.is_valid
    assert check.volume_mm3 == pytest.approx(1000)


def test_thin_positive_wall_and_tiny_solid_are_valid() -> None:
    thin_wall = BuildKernel()
    thin_wall.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    thin_wall.apply(
        "modify.boolean_cut",
        {
            "tool": {
                "type": "box",
                "size_x": 9.98,
                "size_y": 9.98,
                "size_z": 20,
            }
        },
    )
    tiny = BuildKernel()
    tiny.apply("feature.box", {"size_x": 0.001, "size_y": 0.001, "size_z": 0.001})

    assert thin_wall.geometry_check().is_valid
    assert thin_wall.geometry_check().volume_mm3 > 0
    assert tiny.geometry_check().is_valid


def test_complete_cut_is_valid_empty_geometry() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})

    kernel.apply(
        "modify.boolean_cut",
        {"tool": {"type": "box", "size_x": 10, "size_y": 10, "size_z": 10}},
    )

    check = kernel.geometry_check()
    assert check.is_valid
    assert check.solid_count == 0
    assert check.volume_mm3 == 0
