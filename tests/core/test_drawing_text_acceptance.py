# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Acceptance gaps U01–U06 for independent drawing text values."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.drawing_text import (
    DrawingText,
    TextStyle,
    TextStyleTable,
    effective_text,
    mirror_text,
    move_text,
    rotate_text,
    scale_text,
)


def test_full_mtext_mapping_and_inherited_and_explicit_metrics() -> None:
    styles = TextStyleTable(
        (TextStyle("cn", "中文", "Noto Sans", height_mm=4, width_factor=0.8),), "cn"
    )
    item = DrawingText(
        uuid4().hex,
        "第一行 ABC\n\n第三行 123",
        (10, 20),
        kind="mtext",
        style_id="cn",
        rotation_deg=30,
        align="middle_right",
        box_width_mm=40,
        line_spacing=1.5,
        layer_name="文字",
    )
    assert TextStyleTable.from_mapping(styles.to_mapping()) == styles
    assert DrawingText.from_mapping(item.to_mapping()) == item
    assert (effective_text(item, styles).height_mm, effective_text(item, styles).width_factor) == (
        4,
        0.8,
    )
    overridden = replace(item, height_mm=6, width_factor=1.25)
    assert (
        effective_text(overridden, styles).height_mm,
        effective_text(overridden, styles).width_factor,
    ) == (6, 1.25)
    assert item.height_mm is None and item.width_factor is None


@pytest.mark.parametrize(
    "patch,removed",
    [
        ({}, "text"),
        ({"unknown": 1}, ""),
        ({"text": 1}, ""),
        ({"text_id": "bad"}, ""),
        ({"position_mm": [float("nan"), 0]}, ""),
        ({"rotation_deg": float("inf")}, ""),
        ({"height_mm": True}, ""),
        ({"kind": "unknown"}, ""),
        ({"align": "unknown"}, ""),
        ({"text": ""}, ""),
        ({"text": "a\x01b"}, ""),
        ({"text": "a\nb"}, ""),
    ],
)
def test_invalid_mapping_is_rejected(patch: dict[str, object], removed: str) -> None:
    data = DrawingText(uuid4().hex, "A", (0, 0)).to_mapping() | patch
    if removed:
        del data[removed]
    with pytest.raises(ValueError):
        DrawingText.from_mapping(data)


@pytest.mark.parametrize("name", ["height_mm", "width_factor", "line_spacing"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_metric_rejects_nonpositive(name: str, value: float) -> None:
    item = DrawingText(uuid4().hex, "A", (0, 0))
    with pytest.raises(ValueError):
        DrawingText.from_mapping(item.to_mapping() | {name: value})


def test_text_and_style_bounds() -> None:
    item = DrawingText(uuid4().hex, "A", (0, 0), box_width_mm=0, line_spacing=0.5)
    assert replace(item, box_width_mm=1).box_width_mm == 1
    with pytest.raises(ValueError):
        replace(item, box_width_mm=-1)
    assert len(replace(item, text="x" * 1_000_000).text) == 1_000_000
    with pytest.raises(ValueError):
        replace(item, text="x" * 1_000_001)
    styles = tuple(TextStyle(f"id{i}", f"style{i}") for i in range(500))
    assert len(TextStyleTable(styles, "id0").styles) == 500
    with pytest.raises(ValueError):
        TextStyleTable((), "id0")
    with pytest.raises(ValueError):
        TextStyleTable((*styles, TextStyle("extra", "extra")), "id0")


def test_style_identity_and_casefold_rules() -> None:
    first = TextStyle("s1", "Technical")
    with pytest.raises(ValueError):
        TextStyleTable((first, TextStyle("s1", "Other")), "s1")
    with pytest.raises(ValueError):
        TextStyleTable((first, TextStyle("s2", "technical")), "s1")
    with pytest.raises(ValueError):
        TextStyleTable((first,), "missing")
    renamed = replace(first, name="Renamed")
    assert TextStyleTable((renamed,), "s1").current == renamed


def test_transforms_against_independent_coordinates_and_do_not_mutate() -> None:
    styles = TextStyleTable((TextStyle("cn", "中文", height_mm=4),), "cn")
    original = DrawingText(
        uuid4().hex, "A\nB", (3, 4), kind="mtext", style_id="cn", rotation_deg=30, box_width_mm=40
    )
    before = original.to_mapping()
    assert move_text(original, (5, -2)).position_mm == (8, 2)
    rotated = rotate_text(original, 90, (1, 1))
    assert rotated.position_mm == pytest.approx((-2, 3), abs=1e-8, rel=1e-9)
    assert rotated.rotation_deg == pytest.approx(120, abs=1e-8)
    scaled = scale_text(original, 2, (1, 1), styles)
    assert scaled.position_mm == pytest.approx((5, 7), abs=1e-8, rel=1e-9)
    assert (scaled.height_mm, scaled.box_width_mm) == (8, 80)
    mirrored = mirror_text(original, (0, 0), (1, 0))
    assert mirrored.position_mm == pytest.approx((3, -4), abs=1e-8, rel=1e-9)
    assert mirrored.rotation_deg == pytest.approx(330, abs=1e-8)
    assert original.to_mapping() == before


@pytest.mark.parametrize("factor", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_scale_does_not_change_text(factor: float) -> None:
    original = DrawingText(uuid4().hex, "A", (3, 4))
    before = original.to_mapping()
    with pytest.raises(ValueError):
        scale_text(original, factor)
    assert original.to_mapping() == before


def test_invalid_mirror_and_rotation_do_not_change_text() -> None:
    original = DrawingText(uuid4().hex, "A", (3, 4))
    before = original.to_mapping()
    with pytest.raises(ValueError):
        mirror_text(original, (1, 1), (1, 1))
    with pytest.raises(ValueError):
        rotate_text(original, float("nan"))
    assert original.to_mapping() == before
