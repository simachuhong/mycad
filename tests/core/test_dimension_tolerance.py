# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Structured size tolerances preserve signed deviations and formatting."""

import math
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.dimension_styles import DimensionStyle
from mycad.core.dimension_tolerance import DimensionTolerance, effective_tolerance, tolerance_parts
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_signed_deviations_roundtrip_and_limits() -> None:
    tolerance = DimensionTolerance("limits", 0.03, 0.01, precision=3)
    assert DimensionTolerance.from_mapping(tolerance.to_mapping()) == tolerance
    assert tolerance.limits(20) == pytest.approx((20.03, 20.01))


def test_dimension_style_preserves_explicit_text_style_reference() -> None:
    style = DimensionStyle("精密", text_style_id="inspection")
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    assert DimensionStyle.from_mapping(DimensionStyle("旧样式").to_mapping()).text_style_id is None
    with pytest.raises(ValueError):
        DimensionStyle("无效", text_style_id="")


def test_reconcile_font_style_ids_does_not_reuse_conflicting_identity() -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.text_interchange import reconcile_text_style_ids

    source = TextStyleTable((TextStyle("inspect", "检验", "Font A"),), "inspect")
    target = TextStyleTable((TextStyle("inspect", "检验", "Font B"),), "inspect")
    table, mapping = reconcile_text_style_ids(("inspect",), source, target)
    assert mapping["inspect"] != "inspect"
    assert table.get(mapping["inspect"]).font_family == "Font A"
    assert table.get("inspect").font_family == "Font B"


def test_override_including_disabled_takes_precedence() -> None:
    inherited = DimensionTolerance("deviation", 0.02, -0.01)
    disabled = DimensionTolerance("none", 0, 0)
    assert effective_tolerance(inherited, None) == inherited
    assert effective_tolerance(inherited, disabled) == disabled


def test_parts_format_limits_and_remove_negative_zero() -> None:
    assert tolerance_parts(20, DimensionTolerance("limits", 0.02, -0.01, 2)) == ("20.02", "19.99")
    assert tolerance_parts(20, DimensionTolerance("deviation", 0.001, -0.001, 2)) == (
        "+0.00",
        "0.00",
    )


def test_parts_format_symmetric() -> None:
    assert tolerance_parts(20, DimensionTolerance("symmetric", 0.02, -0.02, 2)) == ("±0.02",)


def test_symmetric_tolerance_does_not_display_negative_zero() -> None:
    tolerance = DimensionTolerance("symmetric", -0.0, 0.0, 2)
    assert tolerance_parts(20, tolerance) == ("±0.00",)


@pytest.mark.parametrize(
    ("tolerance", "expected"),
    [
        (DimensionTolerance("none", 1e-10, -1e-10, 8), False),
        (DimensionTolerance("symmetric", 1e-10, -1e-10, 8), True),
        (DimensionTolerance("deviation", 0.1, -1e-10, 8), True),
        (DimensionTolerance("deviation", 0.1, 0, 8), False),
        (DimensionTolerance("deviation", 0.0124, 0.0116, 2), True),
        (DimensionTolerance("deviation", -0.0116, -0.0124, 2), True),
        (DimensionTolerance("deviation", 0.01, 0.01, 2), False),
        (DimensionTolerance("limits", 1e-10, -1e-10, 8), True),
        (DimensionTolerance("limits", 0, 0, 8), False),
    ],
)
def test_tolerance_reports_when_precision_hides_nonzero_values(
    tolerance: DimensionTolerance, expected: bool
) -> None:
    from mycad.core.dimension_tolerance import tolerance_values_hidden_by_precision

    assert tolerance_values_hidden_by_precision(90, tolerance) is expected


@pytest.mark.parametrize(
    ("mode", "upper", "lower"),
    [
        ("invalid", 1, 0),
        ("deviation", 0, 1),
        ("limits", math.inf, 0),
        ("symmetric", 0.1, -0.2),
        ("symmetric", -0.1, 0.1),
    ],
)
def test_rejects_invalid_modes_and_deviations(mode: str, upper: float, lower: float) -> None:
    with pytest.raises(ValueError):
        DimensionTolerance(mode, upper, lower)


def test_mapping_rejects_unknown_or_invalid_fields() -> None:
    data = DimensionTolerance("deviation", 0.02, -0.01).to_mapping()
    for changed in (
        {"precision": True},
        {"text_factor": 0},
        {"alignment": "unknown"},
        {"extra": 1},
        {"upper_deviation": True},
    ):
        with pytest.raises(ValueError):
            DimensionTolerance.from_mapping(data | changed)


def test_style_separates_length_and_angle_and_reads_legacy() -> None:
    length = DimensionTolerance("deviation", 0.02, -0.01)
    angle = DimensionTolerance("symmetric", 0.5, -0.5)
    style = DimensionStyle("test", linear_tolerance=length, angular_tolerance=angle)
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    legacy = DimensionStyle.from_mapping({"name": "old", "precision": 2, "scale": 1})
    assert legacy.linear_tolerance.mode == legacy.angular_tolerance.mode == "none"


def test_dimension_override_roundtrip_preserves_old_records() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    old = SketchConstraint(uuid4().hex, "length", (ref,), 20, "mm")
    changed = replace(old, tolerance=DimensionTolerance("deviation", 0.02, -0.01))
    assert "tolerance" not in old.to_mapping()
    assert SketchConstraint.from_mapping(old.to_mapping()) == old
    assert SketchConstraint.from_mapping(changed.to_mapping()) == changed
    assert changed.value == old.value
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "horizontal", (ref,), tolerance=changed.tolerance)


@pytest.mark.parametrize(
    ("command", "version"),
    [
        ("sketch.constraint.add", 9),
        ("sketch.constraint.update", 7),
        ("sketch.revise", 9),
        ("drawing.sketch.revise", 53),
        ("drawing.tangency.add", 10),
    ],
)
def test_new_constraint_command_versions_support_tolerance(command: str, version: int) -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS

    spec = next(
        item for item in BUILTIN_COMMAND_SPECS if item.id == command and item.version == version
    )

    def count(value: object) -> int:
        if isinstance(value, dict):
            data = cast("dict[str, object]", value)
            properties = data.get("properties")
            own = int(
                isinstance(properties, dict)
                and {"constraint_id", "kind", "references", "driving", "source", "tolerance"}
                <= set(cast("dict[str, object]", properties))
            )
            return own + sum(count(child) for child in data.values())
        if isinstance(value, list):
            return sum(count(child) for child in cast("list[object]", value))
        return 0

    assert count(spec.params_schema) > 0
