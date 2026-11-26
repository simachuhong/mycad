# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Validated drawing-local formatting styles for dimension annotations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.sketch_layers import SKETCH_LINETYPES, STANDARD_LINEWEIGHTS_MM


@dataclass(frozen=True, slots=True)
class DimensionStyle:
    """A named set of supported drawing dimension formatting values."""

    name: str
    precision: int = 2
    scale: float = 1.0
    arrow_first: str = "open"
    arrow_second: str = "open"
    arrow_size: float = 1.4
    dimline_extension: float = 0.0
    extline_extension: float = 0.0
    extline_offset: float = 0.0
    text_height: float = 2.5
    center_mark: str = "none"
    center_size: float = 2.5
    dimension_color: int = 256
    extension_color: int = 256
    text_color: int = 256
    dimension_lineweight: int = -1
    extension_lineweight: int = -1
    dimension_linetype: str = "BYLAYER"
    extension_linetype_first: str = "BYLAYER"
    extension_linetype_second: str = "BYLAYER"
    suppress_extension_first: bool = False
    suppress_extension_second: bool = False
    suppress_dimension_first: bool = False
    suppress_dimension_second: bool = False
    linear_tolerance: DimensionTolerance = DimensionTolerance()
    angular_tolerance: DimensionTolerance = DimensionTolerance()
    text_style_id: str | None = None

    def __post_init__(self) -> None:
        text_style_id = cast("object", self.text_style_id)
        if text_style_id is not None and (
            not isinstance(text_style_id, str)
            or not text_style_id
            or text_style_id != text_style_id.strip()
            or len(text_style_id) > 80
            or not text_style_id.isprintable()
        ):
            raise ValueError("dimension text style ID must be 1–80 printable characters")
        if not isinstance(
            cast("object", self.linear_tolerance), DimensionTolerance
        ) or not isinstance(cast("object", self.angular_tolerance), DimensionTolerance):
            raise ValueError("dimension tolerances must be structured values")
        name = cast("object", self.name)
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or len(name) > 80
            or not name.isprintable()
        ):
            raise ValueError("dimension style name must be 1–80 printable characters")
        precision = cast("object", self.precision)
        if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
            raise ValueError("dimension style precision must be an integer from 0 to 8")
        scale = cast("object", self.scale)
        if (
            isinstance(scale, bool)
            or not isinstance(scale, int | float)
            or not math.isfinite(scale)
            or not 0.1 <= scale <= 100
        ):
            raise ValueError("dimension style scale must be between 0.1 and 100")
        object.__setattr__(self, "scale", float(scale))
        for field in ("arrow_first", "arrow_second"):
            if getattr(self, field) not in ("open", "closed", "filled", "tick", "none"):
                raise ValueError("unsupported dimension arrow type")
        if self.center_mark not in ("none", "mark", "line"):
            raise ValueError("unsupported dimension center mark type")
        for field in ("dimension_color", "extension_color", "text_color"):
            value = cast("object", getattr(self, field))
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 256:
                raise ValueError(f"invalid dimension style {field}")
        for field in ("dimension_lineweight", "extension_lineweight"):
            value = cast("object", getattr(self, field))
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value not in {-1, *(round(weight * 100) for weight in STANDARD_LINEWEIGHTS_MM)}
            ):
                raise ValueError(f"invalid dimension style {field}")
        for field in (
            "dimension_linetype",
            "extension_linetype_first",
            "extension_linetype_second",
        ):
            if getattr(self, field) not in ("BYLAYER", *SKETCH_LINETYPES):
                raise ValueError(f"invalid dimension style {field}")
        for field in (
            "suppress_extension_first",
            "suppress_extension_second",
            "suppress_dimension_first",
            "suppress_dimension_second",
        ):
            if not isinstance(getattr(self, field), bool):
                raise ValueError(f"invalid dimension style {field}")
        for field in (
            "arrow_size",
            "dimline_extension",
            "extline_extension",
            "extline_offset",
            "text_height",
            "center_size",
        ):
            value = cast("object", getattr(self, field))
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or not 0 <= value <= 10000
                or (field in ("arrow_size", "text_height", "center_size") and value == 0)
            ):
                raise ValueError(f"invalid dimension style {field}")
            object.__setattr__(self, field, float(value))

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "name": self.name,
            "precision": self.precision,
            "scale": self.scale,
            "arrow_first": self.arrow_first,
            "arrow_second": self.arrow_second,
            "arrow_size": self.arrow_size,
            "dimline_extension": self.dimline_extension,
            "extline_extension": self.extline_extension,
            "extline_offset": self.extline_offset,
            "text_height": self.text_height,
            "center_mark": self.center_mark,
            "center_size": self.center_size,
            "dimension_color": self.dimension_color,
            "extension_color": self.extension_color,
            "text_color": self.text_color,
            "dimension_lineweight": self.dimension_lineweight,
            "extension_lineweight": self.extension_lineweight,
            "dimension_linetype": self.dimension_linetype,
            "extension_linetype_first": self.extension_linetype_first,
            "extension_linetype_second": self.extension_linetype_second,
            "suppress_extension_first": self.suppress_extension_first,
            "suppress_extension_second": self.suppress_extension_second,
            "suppress_dimension_first": self.suppress_dimension_first,
            "suppress_dimension_second": self.suppress_dimension_second,
        }
        if self.linear_tolerance != DimensionTolerance():
            result["linear_tolerance"] = self.linear_tolerance.to_mapping()
        if self.angular_tolerance != DimensionTolerance():
            result["angular_tolerance"] = self.angular_tolerance.to_mapping()
        if self.text_style_id is not None:
            result["text_style_id"] = self.text_style_id
        return result

    @classmethod
    def from_mapping(cls, value: object) -> DimensionStyle:
        if not isinstance(value, Mapping):
            raise ValueError("dimension style must be an object")
        mapping = cast("Mapping[str, object]", value)
        base = {"name", "precision", "scale"}
        extra = {
            "arrow_first",
            "arrow_second",
            "arrow_size",
            "dimline_extension",
            "extline_extension",
            "extline_offset",
            "text_height",
            "center_mark",
            "center_size",
            "dimension_color",
            "extension_color",
            "text_color",
            "dimension_lineweight",
            "extension_lineweight",
            "dimension_linetype",
            "extension_linetype_first",
            "extension_linetype_second",
            "suppress_extension_first",
            "suppress_extension_second",
            "suppress_dimension_first",
            "suppress_dimension_second",
            "linear_tolerance",
            "angular_tolerance",
            "text_style_id",
        }
        if not base.issubset(mapping) or set(mapping) - base - extra:
            raise ValueError("dimension style must contain name, precision and scale")
        return cls(
            cast("str", mapping["name"]),
            cast("int", mapping["precision"]),
            cast("float", mapping["scale"]),
            cast("str", mapping.get("arrow_first", "open")),
            cast("str", mapping.get("arrow_second", "open")),
            cast("float", mapping.get("arrow_size", 1.4)),
            cast("float", mapping.get("dimline_extension", 0.0)),
            cast("float", mapping.get("extline_extension", 0.0)),
            cast("float", mapping.get("extline_offset", 0.0)),
            cast("float", mapping.get("text_height", 2.5)),
            cast("str", mapping.get("center_mark", "none")),
            cast("float", mapping.get("center_size", 2.5)),
            cast("int", mapping.get("dimension_color", 256)),
            cast("int", mapping.get("extension_color", 256)),
            cast("int", mapping.get("text_color", 256)),
            cast("int", mapping.get("dimension_lineweight", -1)),
            cast("int", mapping.get("extension_lineweight", -1)),
            cast("str", mapping.get("dimension_linetype", "BYLAYER")),
            cast("str", mapping.get("extension_linetype_first", "BYLAYER")),
            cast("str", mapping.get("extension_linetype_second", "BYLAYER")),
            cast("bool", mapping.get("suppress_extension_first", False)),
            cast("bool", mapping.get("suppress_extension_second", False)),
            cast("bool", mapping.get("suppress_dimension_first", False)),
            cast("bool", mapping.get("suppress_dimension_second", False)),
            DimensionTolerance.from_mapping(mapping["linear_tolerance"])
            if "linear_tolerance" in mapping
            else DimensionTolerance(),
            DimensionTolerance.from_mapping(mapping["angular_tolerance"])
            if "angular_tolerance" in mapping
            else DimensionTolerance(),
            cast("str | None", mapping.get("text_style_id")),
        )


@dataclass(frozen=True, slots=True)
class DimensionStyleTable:
    """Unique named styles and the one used for newly created dimensions."""

    styles: tuple[DimensionStyle, ...]
    current_name: str

    def __post_init__(self) -> None:
        styles = tuple(self.styles)
        if (
            not styles
            or len(styles) > 500
            or any(not isinstance(cast("object", style), DimensionStyle) for style in styles)
        ):
            raise ValueError("a drawing must contain 1–500 dimension styles")
        names = [style.name.casefold() for style in styles]
        if len(names) != len(set(names)):
            raise ValueError("dimension style names must be unique")
        current_name = cast("object", self.current_name)
        if not isinstance(current_name, str) or current_name.casefold() not in names:
            raise ValueError("current dimension style must exist")
        object.__setattr__(self, "styles", styles)
        object.__setattr__(self, "current_name", styles[names.index(current_name.casefold())].name)

    @property
    def current(self) -> DimensionStyle:
        return self.get(self.current_name)

    def get(self, name: str) -> DimensionStyle:
        for style in self.styles:
            if style.name.casefold() == name.casefold():
                return style
        raise KeyError(name)

    def to_mapping(self) -> dict[str, object]:
        return {
            "styles": [style.to_mapping() for style in self.styles],
            "current": self.current_name,
        }

    @classmethod
    def from_mapping(cls, value: object) -> DimensionStyleTable:
        if not isinstance(value, Mapping):
            raise ValueError("dimension style table must be an object")
        mapping = cast("Mapping[str, object]", value)
        if set(mapping) != {"styles", "current"}:
            raise ValueError("dimension style table must contain styles and current")
        raw = mapping["styles"]
        current = mapping["current"]
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
            raise ValueError("dimension styles must be an array")
        if not isinstance(current, str):
            raise ValueError("current dimension style must be a name")
        return cls(
            tuple(DimensionStyle.from_mapping(item) for item in cast("Sequence[object]", raw)),
            current,
        )
