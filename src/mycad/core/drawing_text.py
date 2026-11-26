# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Immutable model-space text, named styles and backend-neutral transformations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from typing import cast
from uuid import UUID

from mycad.core.sketch import Point2D
from mycad.core.sketch_layers import SketchLayer

TEXT_ALIGNMENTS = (
    "left",
    "center",
    "right",
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _point2(value: object, name: str) -> Point2D:
    if not isinstance(value, tuple | list):
        raise ValueError(f"{name} requires two coordinates")
    coordinates = cast("Sequence[object]", value)
    if len(coordinates) != 2:
        raise ValueError(f"{name} requires two coordinates")
    return (_finite_number(coordinates[0], name), _finite_number(coordinates[1], name))


def _validate_identity(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"invalid {name}")
    try:
        identity = UUID(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    if value not in (identity.hex, str(identity)):
        raise ValueError(f"invalid {name}")


def _label(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or len(value) > 500:
        raise ValueError(f"invalid {name}")
    if value and (value != value.strip() or not value.isprintable()):
        raise ValueError(f"invalid {name}")
    return value


def _positive(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _mapping(value: object, allowed: set[str], required: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("text record must be an object")
    mapping = cast("Mapping[str, object]", value)
    if set(mapping) - allowed or not required.issubset(mapping):
        raise ValueError("text record contains unknown or missing fields")
    return mapping


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Document request for a font and default text metrics in millimetres."""

    style_id: str = "standard"
    name: str = "标准"
    font_family: str = ""
    font_style: str = "Regular"
    font_file: str = ""
    height_mm: float = 3.5
    width_factor: float = 1.0

    def __post_init__(self) -> None:
        for name in ("style_id", "name", "font_family", "font_style", "font_file"):
            _label(getattr(self, name), name, empty=name in ("font_family", "font_file"))
        for name in ("height_mm", "width_factor"):
            object.__setattr__(self, name, _positive(getattr(self, name), name))

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_mapping(cls, value: object) -> TextStyle:
        data = _mapping(value, {field.name for field in fields(cls)}, {"style_id", "name"})
        return cls(
            style_id=cast("str", data["style_id"]),
            name=cast("str", data["name"]),
            font_family=cast("str", data.get("font_family", "")),
            font_style=cast("str", data.get("font_style", "Regular")),
            font_file=cast("str", data.get("font_file", "")),
            height_mm=cast("float", data.get("height_mm", 3.5)),
            width_factor=cast("float", data.get("width_factor", 1.0)),
        )


def text_style_geometry_signature(style: TextStyle) -> tuple[object, ...]:
    """Fields affecting measured datum-box geometry, excluding display names."""
    return (
        style.font_family,
        style.font_style,
        style.font_file,
        style.height_mm,
        style.width_factor,
    )


@dataclass(frozen=True, slots=True)
class TextStyleTable:
    """Unique style identities and names plus the active creation style."""

    styles: tuple[TextStyle, ...] = (TextStyle(),)
    current_id: str = "standard"

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.styles), tuple | list):
            raise ValueError("styles must be an array")
        styles = tuple(self.styles)
        if (
            not styles
            or len(styles) > 500
            or any(not isinstance(cast("object", item), TextStyle) for item in styles)
        ):
            raise ValueError("a drawing requires 1–500 text styles")
        identities = [style.style_id for style in styles]
        names = [style.name.casefold() for style in styles]
        if len(set(identities)) != len(styles) or len(set(names)) != len(styles):
            raise ValueError("text style IDs and names must be unique")
        _label(self.current_id, "current style")
        if self.current_id not in identities:
            raise ValueError("current text style must exist")
        object.__setattr__(self, "styles", styles)

    def get(self, identity: str) -> TextStyle:
        for style in self.styles:
            if style.style_id == identity:
                return style
        raise KeyError(identity)

    @property
    def current(self) -> TextStyle:
        return self.get(self.current_id)

    def to_mapping(self) -> dict[str, object]:
        return {
            "styles": [style.to_mapping() for style in self.styles],
            "current_id": self.current_id,
        }

    @classmethod
    def from_mapping(cls, value: object) -> TextStyleTable:
        data = _mapping(value, {"styles", "current_id"}, {"styles", "current_id"})
        raw = data["styles"]
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
            raise ValueError("text styles must be an array")
        return cls(
            tuple(TextStyle.from_mapping(item) for item in cast("Sequence[object]", raw)),
            cast("str", data["current_id"]),
        )


@dataclass(frozen=True, slots=True)
class DrawingText:
    """Editable TEXT/MTEXT independent of geometry and paper sheets."""

    text_id: str
    text: str
    position_mm: Point2D
    kind: str = "text"
    style_id: str = "standard"
    height_mm: float | None = None
    width_factor: float | None = None
    rotation_deg: float = 0.0
    align: str = "left"
    box_width_mm: float = 0.0
    line_spacing: float = 1.0
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.text_id, "text_id")
        _label(self.style_id, "style_id")
        if self.kind not in ("text", "mtext") or self.align not in TEXT_ALIGNMENTS:
            raise ValueError("invalid text kind or alignment")
        content = cast("object", self.text)
        if not isinstance(content, str) or not content or len(content) > 1_000_000:
            raise ValueError("text content must be a nonempty bounded string")
        if any(ord(char) < 32 and char not in "\n\t" for char in content):
            raise ValueError("text contains unsupported control characters")
        if self.kind == "text" and "\n" in content:
            raise ValueError("single-line TEXT cannot contain a newline")
        object.__setattr__(self, "position_mm", _point2(self.position_mm, "text position"))
        for name in ("height_mm", "width_factor"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive(value, name))
        object.__setattr__(self, "rotation_deg", _finite_number(self.rotation_deg, "rotation_deg"))
        width = _finite_number(self.box_width_mm, "box_width_mm")
        if width < 0:
            raise ValueError("text box width cannot be negative")
        object.__setattr__(self, "box_width_mm", width)
        object.__setattr__(self, "line_spacing", _positive(self.line_spacing, "line_spacing"))
        SketchLayer(self.layer_name)

    def to_mapping(self) -> dict[str, object]:
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result["position_mm"] = list(self.position_mm)
        return result

    @classmethod
    def from_mapping(cls, value: object) -> DrawingText:
        data = _mapping(
            value, {field.name for field in fields(cls)}, {"text_id", "text", "position_mm"}
        )
        return cls(
            cast("str", data["text_id"]),
            cast("str", data["text"]),
            _point2(data["position_mm"], "text position"),
            kind=cast("str", data.get("kind", "text")),
            style_id=cast("str", data.get("style_id", "standard")),
            height_mm=cast("float | None", data.get("height_mm")),
            width_factor=cast("float | None", data.get("width_factor")),
            rotation_deg=cast("float", data.get("rotation_deg", 0)),
            align=cast("str", data.get("align", "left")),
            box_width_mm=cast("float", data.get("box_width_mm", 0)),
            line_spacing=cast("float", data.get("line_spacing", 1)),
            layer_name=cast("str", data.get("layer_name", "0")),
        )


def effective_text(text: DrawingText, styles: TextStyleTable) -> DrawingText:
    style = styles.get(text.style_id)
    return replace(
        text,
        height_mm=text.height_mm if text.height_mm is not None else style.height_mm,
        width_factor=text.width_factor if text.width_factor is not None else style.width_factor,
    )


def move_text(text: DrawingText, delta_mm: Point2D) -> DrawingText:
    dx, dy = _point2(delta_mm, "translation")
    x, y = text.position_mm
    return replace(text, position_mm=(x + dx, y + dy))


def rotate_text(text: DrawingText, angle_deg: float, origin_mm: Point2D = (0, 0)) -> DrawingText:
    angle = _finite_number(angle_deg, "angle")
    ox, oy = _point2(origin_mm, "rotation origin")
    x, y = text.position_mm[0] - ox, text.position_mm[1] - oy
    sine, cosine = math.sin(math.radians(angle)), math.cos(math.radians(angle))
    return replace(
        text,
        position_mm=(ox + x * cosine - y * sine, oy + x * sine + y * cosine),
        rotation_deg=(text.rotation_deg + angle) % 360,
    )


def scale_text(
    text: DrawingText,
    factor: float,
    origin_mm: Point2D = (0, 0),
    styles: TextStyleTable | None = None,
) -> DrawingText:
    factor = _positive(factor, "scale factor")
    resolved = effective_text(text, styles or TextStyleTable())
    ox, oy = _point2(origin_mm, "scale origin")
    return replace(
        text,
        position_mm=(
            ox + (text.position_mm[0] - ox) * factor,
            oy + (text.position_mm[1] - oy) * factor,
        ),
        height_mm=cast("float", resolved.height_mm) * factor,
        box_width_mm=text.box_width_mm * factor,
    )


def mirror_text(text: DrawingText, first_mm: Point2D, second_mm: Point2D) -> DrawingText:
    ax, ay = _point2(first_mm, "mirror start")
    bx, by = _point2(second_mm, "mirror end")
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-24:
        raise ValueError("mirror axis requires two distinct points")
    x, y = text.position_mm
    projection = ((x - ax) * dx + (y - ay) * dy) / length2
    angle = (2 * math.degrees(math.atan2(dy, dx)) - text.rotation_deg) % 360
    if 90 < angle < 270:
        angle = (angle + 180) % 360
    return replace(
        text,
        position_mm=(2 * (ax + projection * dx) - x, 2 * (ay + projection * dy) - y),
        rotation_deg=angle,
    )
