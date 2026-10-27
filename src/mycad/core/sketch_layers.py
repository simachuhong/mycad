# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral layer values for 2D drafting."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

SketchLinetype = Literal["CONTINUOUS", "DASHED", "DOTTED", "DASHDOT"]

SKETCH_LINETYPES: tuple[SketchLinetype, ...] = (
    "CONTINUOUS",
    "DASHED",
    "DOTTED",
    "DASHDOT",
)

STANDARD_LINEWEIGHTS_MM: tuple[float, ...] = (
    0.0,
    0.05,
    0.09,
    0.13,
    0.15,
    0.18,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.50,
    0.53,
    0.60,
    0.70,
    0.80,
    0.90,
    1.00,
    1.06,
    1.20,
    1.40,
    1.58,
    2.00,
    2.11,
)

_FORBIDDEN_LAYER_NAME_CHARACTERS = frozenset('<>/\\":;?*|=,')


def _layer_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("layer name must be a string")
    if (
        not value
        or len(value) > 255
        or value != value.strip()
        or any(
            character in _FORBIDDEN_LAYER_NAME_CHARACTERS or ord(character) < 32
            for character in value
        )
    ):
        raise ValueError("layer name must be 1-255 characters without reserved CAD punctuation")
    return value


def _color_rgb(value: object) -> tuple[int, int, int]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("layer color must contain three integers from 0 to 255")
    components = cast("Sequence[object]", value)
    if len(components) != 3 or any(
        isinstance(component, bool)
        or not isinstance(component, int)
        or component < 0
        or component > 255
        for component in components
    ):
        raise ValueError("layer color must contain three integers from 0 to 255")
    return (
        cast("int", components[0]),
        cast("int", components[1]),
        cast("int", components[2]),
    )


def _linetype(value: object) -> SketchLinetype:
    if not isinstance(value, str) or value not in SKETCH_LINETYPES:
        raise ValueError(f"unsupported layer linetype {value!r}")
    return value


def _lineweight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("layer lineweight must be a supported millimetre value")
    weight = float(value)
    if not math.isfinite(weight) or not any(
        math.isclose(weight, supported, rel_tol=0.0, abs_tol=1e-9)
        for supported in STANDARD_LINEWEIGHTS_MM
    ):
        raise ValueError("layer lineweight must be a supported millimetre value")
    return weight


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"layer {field} must be a boolean")
    return value


def _strict_mapping(
    value: object, name: str, keys: tuple[str, ...], optional: tuple[str, ...] = ()
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    mapping = cast("Mapping[str, object]", value)
    unknown = tuple(key for key in mapping if key not in (*keys, *optional))
    missing = tuple(key for key in keys if key not in mapping)
    if unknown or missing:
        raise ValueError(f"{name} has unknown fields {unknown} or missing fields {missing}")
    return mapping


@dataclass(frozen=True, slots=True)
class SketchLayer:
    """A CAD layer with explicit display, lock, color and plotted-line properties."""

    name: str
    color_rgb: tuple[int, int, int] = (40, 46, 52)
    linetype: SketchLinetype = "CONTINUOUS"
    lineweight_mm: float = 0.25
    visible: bool = True
    locked: bool = False
    frozen: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _layer_name(self.name))
        object.__setattr__(self, "color_rgb", _color_rgb(self.color_rgb))
        object.__setattr__(self, "linetype", _linetype(self.linetype))
        object.__setattr__(self, "lineweight_mm", _lineweight(self.lineweight_mm))
        object.__setattr__(self, "visible", _boolean(self.visible, "visibility"))
        object.__setattr__(self, "locked", _boolean(self.locked, "lock state"))
        object.__setattr__(self, "frozen", _boolean(self.frozen, "freeze state"))

    @property
    def displayed(self) -> bool:
        """Whether this layer participates in visible drawing and picking."""
        return self.visible and not self.frozen

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical JSON-compatible layer definition."""
        result: dict[str, object] = {
            "name": self.name,
            "color_rgb": list(self.color_rgb),
            "linetype": self.linetype,
            "lineweight_mm": self.lineweight_mm,
            "visible": self.visible,
            "locked": self.locked,
        }
        if self.frozen:
            result["frozen"] = True
        return result

    @classmethod
    def from_mapping(cls, value: object) -> SketchLayer:
        """Parse a strict layer definition from command or archive data."""
        mapping = _strict_mapping(
            value,
            "sketch layer",
            ("name", "color_rgb", "linetype", "lineweight_mm", "visible", "locked"),
            ("frozen",),
        )
        return cls(
            cast("str", mapping["name"]),
            _color_rgb(mapping["color_rgb"]),
            _linetype(mapping["linetype"]),
            _lineweight(mapping["lineweight_mm"]),
            _boolean(mapping["visible"], "visibility"),
            _boolean(mapping["locked"], "lock state"),
            _boolean(mapping.get("frozen", False), "freeze state"),
        )


DEFAULT_SKETCH_LAYER = SketchLayer("0")
DEFAULT_DIM_LAYER = SketchLayer("DIM", color_rgb=(21, 94, 117), lineweight_mm=0.18)


@dataclass(frozen=True, slots=True)
class SketchLayerTable:
    """Immutable layer table with CAD-style case-insensitive name lookup."""

    layers: tuple[SketchLayer, ...] = (DEFAULT_SKETCH_LAYER,)

    def __post_init__(self) -> None:
        layers = tuple(self.layers)
        if not layers or any(
            not isinstance(cast("object", layer), SketchLayer) for layer in layers
        ):
            raise ValueError("layer table must contain at least one SketchLayer")
        names = tuple(layer.name.casefold() for layer in layers)
        if len(names) != len(set(names)):
            raise ValueError("layer name already exists (names are case-insensitive)")
        if "0" not in names:
            raise ValueError("layer table must contain required layer '0'")
        object.__setattr__(self, "layers", layers)

    def get(self, name: str) -> SketchLayer:
        """Return a layer by case-insensitive drawing name."""
        normalized = _layer_name(name).casefold()
        for layer in self.layers:
            if layer.name.casefold() == normalized:
                return layer
        raise KeyError(name)

    def add(self, layer: SketchLayer) -> SketchLayerTable:
        """Return a table with one new layer; existing names cannot be shadowed."""
        if any(existing.name.casefold() == layer.name.casefold() for existing in self.layers):
            raise ValueError(f"layer {layer.name!r} already exists")
        return SketchLayerTable((*self.layers, layer))

    def replace(self, layer: SketchLayer) -> SketchLayerTable:
        """Return a table with updated properties for an existing same-name layer."""
        for index, existing in enumerate(self.layers):
            if existing.name.casefold() == layer.name.casefold():
                updated = list(self.layers)
                updated[index] = layer
                return SketchLayerTable(tuple(updated))
        raise KeyError(layer.name)

    def remove(self, name: str, *, used_names: Sequence[str] = ()) -> SketchLayerTable:
        """Remove an unused non-default layer, preserving every referenced layer."""
        target = self.get(name)
        if target.name == "0":
            raise ValueError("default layer '0' cannot be deleted")
        if any(used.casefold() == target.name.casefold() for used in used_names):
            raise ValueError(f"layer {target.name!r} is used by sketch geometry")
        return SketchLayerTable(tuple(layer for layer in self.layers if layer != target))

    def to_mapping(self) -> list[dict[str, object]]:
        """Return the ordered JSON-compatible layer table."""
        return [layer.to_mapping() for layer in self.layers]

    @classmethod
    def from_mapping(cls, value: object) -> SketchLayerTable:
        """Parse an ordered layer table and require the standard layer zero."""
        if not isinstance(value, list | tuple):
            raise ValueError("sketch layers must be an array")
        layers = cast("Sequence[object]", value)
        return cls(tuple(SketchLayer.from_mapping(item) for item in layers))


__all__ = [
    "DEFAULT_SKETCH_LAYER",
    "DEFAULT_DIM_LAYER",
    "STANDARD_LINEWEIGHTS_MM",
    "SKETCH_LINETYPES",
    "SketchLayer",
    "SketchLayerTable",
    "SketchLinetype",
]


def merge_layer_tables(*tables: SketchLayerTable, include_dim: bool = False) -> SketchLayerTable:
    """Merge by drawing name; later tables supply authoritative shared properties."""
    layers = {"0": DEFAULT_SKETCH_LAYER}
    if include_dim:
        layers["dim"] = DEFAULT_DIM_LAYER
    for table in tables:
        for layer in table.layers:
            layers[layer.name.casefold()] = layer
    return SketchLayerTable(tuple(layers.values()))
