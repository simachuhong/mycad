# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing text values preserve layout intent without UI dependencies."""

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


def test_mapping_inheritance_and_transforms() -> None:
    style = TextStyle(height_mm=4, width_factor=0.8)
    styles = TextStyleTable((style,))
    text = DrawingText(uuid4().hex, "中文 AB", (1, 2))
    assert DrawingText.from_mapping(text.to_mapping()) == text
    assert TextStyleTable.from_mapping(styles.to_mapping()) == styles
    resolved = effective_text(text, styles)
    assert (resolved.height_mm, resolved.width_factor) == (4, 0.8)
    assert move_text(text, (2, 3)).position_mm == (3, 5)
    assert rotate_text(text, 90).position_mm == pytest.approx((-2, 1))
    scaled = scale_text(resolved, 2)
    assert (scaled.position_mm, scaled.height_mm) == ((2, 4), 8)
    assert mirror_text(text, (0, 0), (1, 0)).position_mm == (1, -2)
    assert text.height_mm is None


@pytest.mark.parametrize(
    "patch",
    [
        {"height_mm": True},
        {"rotation_deg": float("nan")},
        {"kind": "unknown"},
        {"position_mm": (1,)},
        {"text_id": "bad"},
        {"text": "line\nline"},
    ],
)
def test_invalid_text_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        DrawingText.from_mapping(DrawingText(uuid4().hex, "a", (0, 0)).to_mapping() | patch)


def test_styles_are_unique_and_mapping_is_strict() -> None:
    with pytest.raises(ValueError):
        TextStyleTable((TextStyle(), replace(TextStyle(), style_id="other", name="标准")))
    with pytest.raises(ValueError):
        TextStyle.from_mapping(TextStyle().to_mapping() | {"unknown": 1})
    with pytest.raises(ValueError):
        TextStyleTable((TextStyle(),), current_id="missing")
