# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing dimension styles are validated independently of UI preferences."""

import math
from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_dimension_component_colors_roundtrip_and_validate() -> None:
    style = DimensionStyle("颜色", dimension_color=1, extension_color=3, text_color=5)
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    old = style.to_mapping()
    for field in ("dimension_color", "extension_color", "text_color"):
        old.pop(field)
    restored = DimensionStyle.from_mapping(old)
    assert (restored.dimension_color, restored.extension_color, restored.text_color) == (
        256,
        256,
        256,
    )
    with pytest.raises(ValueError):
        DimensionStyle("错误", dimension_color=0)


def test_dimension_component_lineweights_roundtrip_and_validate() -> None:
    style = DimensionStyle("线宽", dimension_lineweight=35, extension_lineweight=70)
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    old = style.to_mapping()
    old.pop("dimension_lineweight")
    old.pop("extension_lineweight")
    restored = DimensionStyle.from_mapping(old)
    assert (restored.dimension_lineweight, restored.extension_lineweight) == (-1, -1)
    with pytest.raises(ValueError):
        DimensionStyle("错误", dimension_lineweight=12)


def test_dimension_component_linetypes_roundtrip_and_validate() -> None:
    style = DimensionStyle(
        "线型",
        dimension_linetype="DASHED",
        extension_linetype_first="DOTTED",
        extension_linetype_second="DASHDOT",
    )
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    old = style.to_mapping()
    for field in ("dimension_linetype", "extension_linetype_first", "extension_linetype_second"):
        old.pop(field)
    restored = DimensionStyle.from_mapping(old)
    assert (
        restored.dimension_linetype,
        restored.extension_linetype_first,
        restored.extension_linetype_second,
    ) == ("BYLAYER", "BYLAYER", "BYLAYER")
    with pytest.raises(ValueError):
        DimensionStyle("错误", dimension_linetype="INVALID")


def test_extension_line_visibility_roundtrip_and_validate() -> None:
    style = DimensionStyle("界线", suppress_extension_first=True, suppress_extension_second=False)
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    old = style.to_mapping()
    old.pop("suppress_extension_first")
    old.pop("suppress_extension_second")
    assert not DimensionStyle.from_mapping(old).suppress_extension_first
    with pytest.raises(ValueError):
        DimensionStyle.from_mapping(style.to_mapping() | {"suppress_extension_first": 1})


def test_dimension_line_visibility_roundtrip_and_validate() -> None:
    style = DimensionStyle("尺寸线", suppress_dimension_first=True, suppress_dimension_second=False)
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    old = style.to_mapping()
    old.pop("suppress_dimension_first")
    old.pop("suppress_dimension_second")
    assert not DimensionStyle.from_mapping(old).suppress_dimension_first
    with pytest.raises(ValueError):
        DimensionStyle.from_mapping(style.to_mapping() | {"suppress_dimension_first": 1})


def test_dimension_style_arrow_and_line_settings_roundtrip_and_legacy() -> None:
    style = DimensionStyle(
        "机械",
        arrow_first="closed",
        arrow_second="tick",
        arrow_size=2.5,
        dimline_extension=1.5,
        extline_extension=2.0,
        extline_offset=0.75,
        text_height=3.5,
    )
    assert DimensionStyle.from_mapping(style.to_mapping()) == style
    legacy = DimensionStyle.from_mapping({"name": "标准", "precision": 2, "scale": 1})
    assert legacy.arrow_first == legacy.arrow_second == "open"
    assert legacy.dimline_extension == legacy.extline_extension == legacy.extline_offset == 0


def test_dimension_style_table_roundtrips_and_finds_current_style() -> None:
    table = DimensionStyleTable(
        (DimensionStyle("标准", 2, 1), DimensionStyle("加工图", 3, 2)), "加工图"
    )
    assert table.current == DimensionStyle("加工图", 3, 2)
    assert DimensionStyleTable.from_mapping(table.to_mapping()) == table


@pytest.mark.parametrize(
    ("name", "precision", "scale"),
    [
        ("", 2, 1),
        (" a ", 2, 1),
        ("x" * 81, 2, 1),
        ("a\nb", 2, 1),
        ("ok", -1, 1),
        ("ok", 9, 1),
        ("ok", 2, 0),
        ("ok", 2, math.inf),
    ],
)
def test_dimension_style_rejects_invalid_data(name: str, precision: int, scale: float) -> None:
    with pytest.raises(ValueError):
        DimensionStyle(name, precision, scale)


def test_style_table_rejects_ambiguous_or_missing_current() -> None:
    with pytest.raises(ValueError):
        DimensionStyleTable((DimensionStyle("A", 2, 1), DimensionStyle("a", 3, 2)), "A")
    with pytest.raises(ValueError):
        DimensionStyleTable((DimensionStyle("A", 2, 1),), "missing")


def test_dimension_style_reference_roundtrips_and_old_records_remain_unchanged() -> None:
    ref = SketchGeometryReference(uuid4().hex, "geometry")
    old = SketchConstraint(uuid4().hex, "length", (ref,), 10, "mm")
    assert "style_name" not in old.to_mapping()
    styled = replace(old, style_name="加工图")
    assert SketchConstraint.from_mapping(styled.to_mapping()) == styled
    assert SketchConstraint.from_mapping(old.to_mapping()) == old
    with pytest.raises(ValueError):
        SketchConstraint(uuid4().hex, "horizontal", (ref,), style_name="加工图")


@pytest.mark.parametrize(
    ("command", "version"),
    [
        ("sketch.create", 32),
        ("sketch.create", 33),
        ("sketch.constraint.add", 8),
        ("sketch.constraint.update", 6),
        ("sketch.revise", 8),
        ("drawing.sketch.revise", 50),
        ("drawing.sketch.revise", 51),
        ("drawing.tangency.add", 9),
    ],
)
def test_style_reference_uses_new_command_schema(command: str, version: int) -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS

    spec = next(s for s in BUILTIN_COMMAND_SPECS if s.id == command and s.version == version)

    def constraints(value: object) -> list[dict[str, object]]:
        if isinstance(value, dict):
            mapping = cast("dict[str, object]", value)
            properties = mapping.get("properties")
            result = (
                [cast("dict[str, object]", properties)]
                if isinstance(properties, dict)
                and {"constraint_id", "kind", "references", "driving", "source"}
                <= cast("dict[str, object]", properties).keys()
                else []
            )
            return result + [item for child in mapping.values() for item in constraints(child)]
        if isinstance(value, list):
            return [item for child in cast("list[object]", value) for item in constraints(child)]
        return []

    found = constraints(spec.params_schema)
    assert found and all("style_name" in properties for properties in found)
