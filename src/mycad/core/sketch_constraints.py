# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral sketch constraint values and stable geometry references."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from mycad.core.sketch_layers import SketchLayer

if TYPE_CHECKING:
    from mycad.core.sketch import Sketch

ConstraintKind = Literal[
    "coincident",
    "horizontal",
    "vertical",
    "parallel",
    "perpendicular",
    "tangent",
    "concentric",
    "equal",
    "fixed",
    "length",
    "distance",
    "angle",
    "radius",
    "diameter",
    "arc_length",
]
ReferenceKind = Literal["geometry", "start", "end", "center", "vertex", "segment"]
ConstraintSource = Literal["user", "inferred"]
ConstraintUnit = Literal["mm", "deg"]
ConstraintSolveStatus = Literal["success", "failed", "invalid", "unavailable"]

_CONSTRAINT_COUNTS: dict[str, int] = {
    "coincident": 2,
    "horizontal": 1,
    "vertical": 1,
    "parallel": 2,
    "perpendicular": 2,
    "tangent": 2,
    "concentric": 2,
    "equal": 2,
    "fixed": 1,
    "length": 1,
    "distance": 2,
    "angle": 2,
    "radius": 1,
    "diameter": 1,
    "arc_length": 1,
}
_DIMENSION_UNITS: dict[str, ConstraintUnit] = {
    "length": "mm",
    "distance": "mm",
    "angle": "deg",
    "radius": "mm",
    "diameter": "mm",
    "arc_length": "mm",
}
DIMENSION_KINDS = frozenset(_DIMENSION_UNITS)
DIMENSION_AXES = frozenset({"aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y"})


def _placement_point(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, tuple | list):
        raise ValueError("dimension position must contain two finite coordinates")
    values = cast("Sequence[object]", value)
    if len(values) != 2:
        raise ValueError("dimension position must contain two finite coordinates")
    if any(
        isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x)
        for x in values
    ):
        raise ValueError("dimension position must contain two finite coordinates")
    return (float(cast("float", values[0])), float(cast("float", values[1])))


_POINT_REFERENCES = frozenset({"start", "end", "center", "vertex"})


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a canonical UUID") from exc
    if value not in (parsed.hex, str(parsed)):
        raise ValueError(f"{name} must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class SketchGeometryReference:
    """Stable entity/sub-entity identity, independent of solver-internal IDs."""

    entity_id: str
    kind: ReferenceKind
    index: int | None = None

    def __post_init__(self) -> None:
        _identity(self.entity_id, "entity_id")
        if self.kind not in ("geometry", "start", "end", "center", "vertex", "segment"):
            raise ValueError("reference kind is unsupported")
        if self.kind in ("vertex", "segment"):
            if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
                raise ValueError(f"{self.kind} reference requires a nonnegative index")
        elif self.index is not None:
            raise ValueError(f"{self.kind} reference cannot carry an index")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {"entity_id": self.entity_id, "kind": self.kind}
        if self.index is not None:
            result["index"] = self.index
        return result

    @classmethod
    def from_mapping(cls, value: object) -> SketchGeometryReference:
        if not isinstance(value, Mapping):
            raise ValueError("geometry reference must be an object")
        record = cast("Mapping[str, object]", value)
        keys = tuple(record)
        if set(keys) not in ({"entity_id", "kind"}, {"entity_id", "kind", "index"}):
            raise ValueError("geometry reference must contain entity_id, kind, and optional index")
        identity = _identity(record["entity_id"], "entity_id")
        kind = record["kind"]
        if kind not in ("geometry", "start", "end", "center", "vertex", "segment"):
            raise ValueError("reference kind is unsupported")
        index = record.get("index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise ValueError("reference index must be a nonnegative integer")
        return cls(identity, kind, index)


@dataclass(frozen=True, slots=True)
class SketchConstraint:
    """Serializable geometric relation or dimension in local sketch units."""

    constraint_id: str
    kind: ConstraintKind
    references: tuple[SketchGeometryReference, ...]
    value: float | None = None
    unit: ConstraintUnit | None = None
    driving: bool = True
    source: ConstraintSource = "user"
    precision: int = 2
    scale: float = 1.0
    position_mm: tuple[float, float] | None = None
    text_position_mm: tuple[float, float] | None = None
    axis: str = "aligned"
    layer_name: str | None = None
    anchor_mode: str = "auto"

    def __post_init__(self) -> None:
        _identity(self.constraint_id, "constraint_id")
        if self.kind not in _CONSTRAINT_COUNTS:
            raise ValueError("constraint kind is unsupported")
        references = tuple(self.references)
        if len(references) != _CONSTRAINT_COUNTS[self.kind]:
            raise ValueError(f"{self.kind} requires {_CONSTRAINT_COUNTS[self.kind]} references")
        if any(
            not isinstance(cast("object", reference), SketchGeometryReference)
            for reference in references
        ):
            raise ValueError("constraint references must be stable geometry references")
        if len(set(references)) != len(references):
            raise ValueError("constraint references must be distinct")
        if not isinstance(cast("object", self.driving), bool):
            raise ValueError("driving must be a boolean")
        if self.anchor_mode not in ("auto", "start", "end", "symmetric"):
            raise ValueError("dimension anchor mode is unsupported")
        if self.anchor_mode != "auto" and self.kind not in ("length", "distance"):
            raise ValueError("only linear dimensions accept an anchor mode")
        if self.axis not in DIMENSION_AXES:
            raise ValueError("dimension axis is unsupported")
        if self.axis != "aligned" and self.kind not in ("length", "distance"):
            raise ValueError("only linear dimensions accept a projection axis")
        object.__setattr__(self, "position_mm", _placement_point(self.position_mm))
        object.__setattr__(self, "text_position_mm", _placement_point(self.text_position_mm))
        if self.layer_name is not None:
            object.__setattr__(self, "layer_name", SketchLayer(self.layer_name).name)
            if self.kind not in DIMENSION_KINDS:
                raise ValueError("only a dimension can carry an annotation layer")
        numeric_unit = _DIMENSION_UNITS.get(self.kind)
        value = self.value
        if numeric_unit is None:
            if value is not None or self.unit is not None:
                raise ValueError(f"{self.kind} does not accept a value or unit")
        else:
            if self.unit != numeric_unit:
                raise ValueError(f"{self.kind} value unit must be {numeric_unit!r}")
            if value is None:
                if self.driving:
                    raise ValueError(f"driving {self.kind} requires a finite numeric value")
            else:
                if isinstance(cast("object", value), bool) or not isinstance(
                    cast("object", value), int | float
                ):
                    raise ValueError(f"{self.kind} requires a finite numeric value")
                if not math.isfinite(value):
                    raise ValueError(f"{self.kind} requires a finite numeric value")
                if (
                    self.driving
                    and self.kind != "angle"
                    and not self.axis.startswith("ordinate_")
                    and value <= 0.0
                ):
                    raise ValueError(f"{self.kind} value must be positive")
        if self.source not in ("user", "inferred"):
            raise ValueError("constraint source must be 'user' or 'inferred'")
        precision = cast("object", self.precision)
        if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
            raise ValueError("dimension precision must be an integer from 0 to 8")
        scale = cast("object", self.scale)
        if (
            isinstance(scale, bool)
            or not isinstance(scale, int | float)
            or not math.isfinite(scale)
            or scale < 0.1
            or scale > 100.0
        ):
            raise ValueError("dimension scale must be between 0.1 and 100")
        if numeric_unit is None and (
            precision != 2
            or scale != 1.0
            or self.position_mm is not None
            or self.text_position_mm is not None
        ):
            raise ValueError("geometric relations cannot carry dimension formatting")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "constraint_id": self.constraint_id,
            "kind": self.kind,
            "references": [reference.to_mapping() for reference in self.references],
            "driving": self.driving,
            "source": self.source,
        }
        if self.unit is not None:
            result["unit"] = self.unit
        if self.value is not None:
            result["value"] = self.value
        if self.precision != 2:
            result["precision"] = self.precision
        if self.scale != 1.0:
            result["scale"] = self.scale
        if self.position_mm is not None:
            result["position_mm"] = list(self.position_mm)
        if self.text_position_mm is not None:
            result["text_position_mm"] = list(self.text_position_mm)
        if self.axis != "aligned":
            result["axis"] = self.axis
        if self.layer_name is not None:
            result["layer_name"] = self.layer_name
        if self.anchor_mode != "auto":
            result["anchor_mode"] = self.anchor_mode
        return result

    @classmethod
    def from_mapping(cls, value: object) -> SketchConstraint:
        if not isinstance(value, Mapping):
            raise ValueError("constraint must be an object")
        mapping = cast("Mapping[str, object]", value)
        base = {"constraint_id", "kind", "references", "driving", "source"}
        allowed = base | {
            "unit",
            "value",
            "precision",
            "scale",
            "position_mm",
            "text_position_mm",
            "axis",
            "layer_name",
            "anchor_mode",
        }
        if not base.issubset(mapping) or any(key not in allowed for key in mapping):
            raise ValueError(
                "constraint must contain its required fields and known optional values"
            )
        identity = _identity(mapping["constraint_id"], "constraint_id")
        kind = mapping["kind"]
        if kind not in _CONSTRAINT_COUNTS:
            raise ValueError("constraint kind is unsupported")
        raw_references = mapping["references"]
        if not isinstance(raw_references, Sequence) or isinstance(raw_references, str | bytes):
            raise ValueError("constraint references must be an array")
        reference_sequence = cast("Sequence[object]", raw_references)
        references = tuple(
            SketchGeometryReference.from_mapping(item) for item in reference_sequence
        )
        value_number = mapping.get("value")
        if "value" in mapping and (
            isinstance(value_number, bool) or not isinstance(value_number, int | float)
        ):
            raise ValueError("constraint value must be a finite number")
        unit = mapping.get("unit")
        if unit not in (None, "mm", "deg"):
            raise ValueError("constraint unit must be 'mm' or 'deg'")
        driving = mapping["driving"]
        source = mapping["source"]
        precision = mapping.get("precision", 2)
        scale = mapping.get("scale", 1.0)
        if not isinstance(driving, bool):
            raise ValueError("driving must be a boolean")
        if source not in ("user", "inferred"):
            raise ValueError("constraint source must be 'user' or 'inferred'")
        if isinstance(precision, bool) or not isinstance(precision, int):
            raise ValueError("dimension precision must be an integer from 0 to 8")
        if isinstance(scale, bool) or not isinstance(scale, int | float):
            raise ValueError("dimension scale must be between 0.1 and 100")
        return cls(
            identity,
            cast("ConstraintKind", kind),
            references,
            cast("float | None", value_number),
            unit,
            driving,
            source,
            precision,
            float(scale),
            _placement_point(mapping.get("position_mm")),
            _placement_point(mapping.get("text_position_mm")),
            str(mapping.get("axis", "aligned")),
            cast("str | None", mapping.get("layer_name")),
            cast("str", mapping.get("anchor_mode", "auto")),
        )


BranchChangeKind = Literal[
    "direction", "side", "degeneracy", "tangency", "nesting", "arc_sweep", "arc_span"
]


@dataclass(frozen=True, slots=True)
class SketchBranchChange:
    """Observed geometric branch/orientation change in a disposable solve."""

    kind: BranchChangeKind
    entity_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class SketchConstraintSolveResult:
    """Backend-neutral result from a disposable constraint preview."""

    status: ConstraintSolveStatus
    sketch: Sketch | None
    degrees_of_freedom: int | None
    conflicting_constraint_ids: tuple[str, ...] = ()
    redundant_constraint_ids: tuple[str, ...] = ()
    message: str | None = None
    solver_id: str = "planegcs"
    solver_version: str | None = None
    branch_changes: tuple[SketchBranchChange, ...] = ()

    def command_params(
        self, base_sketch: Sketch, constraint: SketchConstraint
    ) -> dict[str, object]:
        """Return replay inputs for an explicit Bus confirmation."""
        if self.status != "success" or self.sketch is None or self.solver_version is None:
            raise ValueError("only a successful solve can be confirmed")
        solved_constraint = next(
            (
                item
                for item in self.sketch.constraints
                if item.constraint_id == constraint.constraint_id
            ),
            None,
        )
        if solved_constraint is None:
            raise ValueError("successful sketch result is missing the confirmed constraint")
        solution_entities = self.sketch.to_mapping(version=3)["entities"]
        return {
            "sketch_id": base_sketch.sketch_id,
            "base_state_sha256": base_sketch.state_digest(),
            "constraint": solved_constraint.to_mapping(),
            "solver_id": self.solver_id,
            "solver_version": self.solver_version,
            "degrees_of_freedom": self.degrees_of_freedom,
            "solution_entities": solution_entities,
        }
