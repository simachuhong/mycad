# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Structured, backend-neutral geometric tolerance annotations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
from mycad.core.sketch_constraints import SketchGeometryReference

CHARACTERISTICS = (
    "straightness",
    "flatness",
    "circularity",
    "cylindricity",
    "line_profile",
    "surface_profile",
    "parallelism",
    "perpendicularity",
    "angularity",
    "position",
    "concentricity",
    "symmetry",
    "circular_runout",
    "total_runout",
)


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("identity must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("identity must be a UUID") from exc
    if value not in (parsed.hex, str(parsed)):
        raise ValueError("identity must be a canonical UUID")
    return value


def _label(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 80
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError("invalid datum label")
    return value


def _point(value: object) -> tuple[float, float]:
    if not isinstance(value, tuple | list):
        raise ValueError("point requires two coordinates")
    coordinates = cast("Sequence[object]", value)
    if len(coordinates) != 2:
        raise ValueError("point requires two coordinates")
    result: list[float] = []
    for component in coordinates:
        if isinstance(component, bool) or not isinstance(component, int | float):
            raise ValueError("coordinate must be finite")
        try:
            number = float(component)
        except OverflowError as exc:
            raise ValueError("coordinate must be finite") from exc
        if not math.isfinite(number):
            raise ValueError("coordinate must be finite")
        result.append(number)
    return result[0], result[1]


def _mapping(value: object, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("annotation must contain its known fields")
    mapping = cast("Mapping[str, object]", value)
    if set(mapping) != fields:
        raise ValueError("annotation must contain its known fields")
    return mapping


@dataclass(frozen=True, slots=True)
class DatumReference:
    label: str
    datum_id: str | None = None
    modifier: str = ""

    def __post_init__(self) -> None:
        _label(self.label)
        if self.datum_id is not None:
            _identity(self.datum_id)
        if self.modifier not in ("", "M", "L"):
            raise ValueError("unsupported datum modifier")

    def to_mapping(self) -> dict[str, object]:
        return {"label": self.label, "datum_id": self.datum_id, "modifier": self.modifier}

    @classmethod
    def from_mapping(cls, value: object) -> DatumReference:
        data = _mapping(value, {"label", "datum_id", "modifier"})
        return cls(
            cast("str", data["label"]),
            cast("str | None", data["datum_id"]),
            cast("str", data["modifier"]),
        )


@dataclass(frozen=True, slots=True)
class ToleranceRow:
    characteristic: str
    value: float
    precision: int
    diameter: bool = False
    modifier: str = ""
    datums: tuple[DatumReference, ...] = ()

    @property
    def precision_insufficient(self) -> bool:
        """Whether the configured precision displays a nonzero tolerance as zero."""
        return self.value != 0 and round(self.value, self.precision) == 0

    def __post_init__(self) -> None:
        if self.characteristic not in CHARACTERISTICS:
            raise ValueError("unsupported geometric characteristic")
        raw = cast("object", self.value)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("tolerance value must be nonnegative and finite")
        try:
            value = float(raw)
        except OverflowError as exc:
            raise ValueError("tolerance value must be nonnegative and finite") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError("tolerance value must be nonnegative and finite")
        precision = cast("object", self.precision)
        if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
            raise ValueError("invalid tolerance precision")
        if not isinstance(cast("object", self.diameter), bool) or self.modifier not in (
            "",
            "M",
            "L",
        ):
            raise ValueError("invalid tolerance modifier")
        datums = tuple(self.datums)
        if len(datums) > 3 or any(
            not isinstance(cast("object", item), DatumReference) for item in datums
        ):
            raise ValueError("invalid datum references")
        object.__setattr__(self, "value", 0.0 if value == 0 else value)
        object.__setattr__(self, "datums", datums)

    def to_mapping(self) -> dict[str, object]:
        return {
            "characteristic": self.characteristic,
            "value": self.value,
            "precision": self.precision,
            "diameter": self.diameter,
            "modifier": self.modifier,
            "datums": [datum.to_mapping() for datum in self.datums],
        }

    @classmethod
    def from_mapping(cls, value: object) -> ToleranceRow:
        data = _mapping(
            value, {"characteristic", "value", "precision", "diameter", "modifier", "datums"}
        )
        raw = data["datums"]
        if not isinstance(raw, list | tuple):
            raise ValueError("datums must be an array")
        return cls(
            cast("str", data["characteristic"]),
            cast("float", data["value"]),
            cast("int", data["precision"]),
            cast("bool", data["diameter"]),
            cast("str", data["modifier"]),
            tuple(DatumReference.from_mapping(item) for item in cast("Sequence[object]", raw)),
        )


@dataclass(frozen=True, slots=True)
class AnnotationAttachment:
    """Stable reference to a frame or dimension and a local attachment offset."""

    kind: str
    object_id: str
    offset_mm: tuple[float, float]
    sketch_id: str | None = None
    anchor: str = "position"

    def __post_init__(self) -> None:
        if self.kind not in ("frame", "reference_dimension", "sketch_dimension"):
            raise ValueError("unsupported annotation attachment")
        _identity(self.object_id)
        object.__setattr__(self, "offset_mm", _point(self.offset_mm))
        if self.kind == "sketch_dimension":
            _identity(self.sketch_id)
        elif self.sketch_id is not None:
            raise ValueError("sketch identity only applies to sketch dimensions")
        if self.anchor not in ("position", "text") or (
            self.anchor == "text" and self.kind != "sketch_dimension"
        ):
            raise ValueError("unsupported annotation attachment anchor")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "kind": self.kind,
            "object_id": self.object_id,
            "offset_mm": list(self.offset_mm),
        }
        if self.sketch_id is not None:
            result["sketch_id"] = self.sketch_id
        if self.anchor != "position":
            result["anchor"] = self.anchor
        return result

    @classmethod
    def from_mapping(cls, value: object) -> AnnotationAttachment:
        fields = {"kind", "object_id", "offset_mm"}
        if isinstance(value, Mapping) and "sketch_id" in value:
            fields.add("sketch_id")
        if isinstance(value, Mapping) and "anchor" in value:
            fields.add("anchor")
        data = _mapping(cast("object", value), fields)
        return cls(
            cast("str", data["kind"]),
            cast("str", data["object_id"]),
            _point(data["offset_mm"]),
            cast("str | None", data.get("sketch_id")),
            cast("str", data.get("anchor", "position")),
        )


@dataclass(frozen=True, slots=True)
class SurfaceIndication:
    """Reference line and surface leader offsets relative to the surface target."""

    reference_start_offset_mm: tuple[float, float]
    reference_end_offset_mm: tuple[float, float]
    landing_ratio: float
    leader_offsets_mm: tuple[tuple[float, float], ...] = ()
    arrow_size_mm: float | None = None
    auto_normal: bool = False
    auto_route: bool = False
    route_avoid_crossing: bool = False

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.route_avoid_crossing), bool) or (
            self.route_avoid_crossing and not self.auto_route
        ):
            raise ValueError("invalid route crossing policy")
        start, end = _point(self.reference_start_offset_mm), _point(self.reference_end_offset_mm)
        if math.dist(start, end) <= 1e-9:
            raise ValueError("surface indication reference line must have length")
        raw = cast("object", self.landing_ratio)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("surface indication landing must be within reference line")
        try:
            ratio = float(raw)
        except OverflowError as exc:
            raise ValueError("surface indication landing must be within reference line") from exc
        if not math.isfinite(ratio) or not 0 <= ratio <= 1:
            raise ValueError("surface indication landing must be within reference line")
        if self.arrow_size_mm is not None:
            raw_size = cast("object", self.arrow_size_mm)
            if isinstance(raw_size, bool) or not isinstance(raw_size, int | float):
                raise ValueError("surface indication arrow size must be positive and finite")
            try:
                size = float(raw_size)
            except OverflowError as exc:
                raise ValueError(
                    "surface indication arrow size must be positive and finite"
                ) from exc
            if not math.isfinite(size) or size <= 0:
                raise ValueError("surface indication arrow size must be positive and finite")
            object.__setattr__(self, "arrow_size_mm", size)
        vertices = cast("object", self.leader_offsets_mm)
        if not isinstance(vertices, list | tuple):
            raise ValueError("invalid surface leader vertices")
        if len(cast("Sequence[object]", vertices)) > 64:
            raise ValueError("invalid surface leader vertices")
        points = tuple(_point(p) for p in cast("Sequence[object]", vertices))
        if not isinstance(cast("object", self.auto_normal), bool) or (
            self.auto_normal and not points
        ):
            raise ValueError("surface normal constraint requires a leader vertex")
        if not isinstance(cast("object", self.auto_route), bool) or (
            self.auto_route and not self.auto_normal
        ):
            raise ValueError("automatic surface route requires a normal constraint")
        path = ((0.0, 0.0), *points, start)
        if any(
            math.dist(first, second) <= 1e-9 for first, second in zip(path, path[1:], strict=False)
        ):
            raise ValueError("surface leader segments must have length")
        object.__setattr__(self, "reference_start_offset_mm", start)
        object.__setattr__(self, "reference_end_offset_mm", end)
        object.__setattr__(self, "landing_ratio", ratio)
        object.__setattr__(self, "leader_offsets_mm", points)

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "reference_start_offset_mm": list(self.reference_start_offset_mm),
            "reference_end_offset_mm": list(self.reference_end_offset_mm),
            "landing_ratio": self.landing_ratio,
            "leader_offsets_mm": [list(p) for p in self.leader_offsets_mm],
        }
        if self.arrow_size_mm is not None:
            result["arrow_size_mm"] = self.arrow_size_mm
        if self.auto_normal:
            result["auto_normal"] = True
        if self.auto_route:
            result["auto_route"] = True
        if self.route_avoid_crossing:
            result["route_avoid_crossing"] = True
        return result

    @classmethod
    def from_mapping(cls, value: object) -> SurfaceIndication:
        fields = {
            "reference_start_offset_mm",
            "reference_end_offset_mm",
            "landing_ratio",
            "leader_offsets_mm",
        }
        if isinstance(value, Mapping) and "arrow_size_mm" in value:
            fields.add("arrow_size_mm")
        if isinstance(value, Mapping) and "auto_normal" in value:
            fields.add("auto_normal")
        if isinstance(value, Mapping) and "auto_route" in value:
            fields.add("auto_route")
        if isinstance(value, Mapping) and "route_avoid_crossing" in value:
            fields.add("route_avoid_crossing")
        data = _mapping(cast("object", value), fields)
        vertices = data["leader_offsets_mm"]
        if not isinstance(vertices, list | tuple):
            raise ValueError("invalid surface leader vertices")
        return cls(
            _point(data["reference_start_offset_mm"]),
            _point(data["reference_end_offset_mm"]),
            cast("float", data["landing_ratio"]),
            tuple(_point(p) for p in cast("Sequence[object]", vertices)),
            cast("float | None", data.get("arrow_size_mm")),
            cast("bool", data.get("auto_normal", False)),
            cast("bool", data.get("auto_route", False)),
            cast("bool", data.get("route_avoid_crossing", False)),
        )


@dataclass(frozen=True, slots=True)
class FeatureControlFrame:
    frame_id: str
    rows: tuple[ToleranceRow, ...]
    position_mm: tuple[float, float]
    rotation_deg: float = 0.0
    layer_name: str = "0"
    text_style_id: str | None = None
    leader_target_mm: tuple[float, float] | None = None
    leader_offsets: tuple[tuple[float, float], ...] = ()
    leader_anchor_offset: tuple[float, float] | None = None
    leader_attachment: DatumAttachment | None = None
    leader_annotation_attachment: AnnotationAttachment | None = None
    surface_indication: SurfaceIndication | None = None
    leader_auto_normal: bool = False
    leader_auto_route: bool = False
    route_avoid_crossing: bool = False
    route_track_target: bool = False
    route_algorithm_version: int = 1
    leader_arrow_style: str = "legacy"

    def __post_init__(self) -> None:
        if self.leader_arrow_style not in ("legacy", "closed_filled"):
            raise ValueError("invalid frame leader arrow style")
        if (
            type(self.route_algorithm_version) is not int
            or self.route_algorithm_version not in (1, 2)
            or (self.route_algorithm_version == 2 and not self.route_track_target)
        ):
            raise ValueError("invalid automatic route algorithm version")
        if not isinstance(cast("object", self.route_track_target), bool) or (
            self.route_track_target and not self.route_avoid_crossing
        ):
            raise ValueError("target tracking requires crossing-safe routing")
        if not isinstance(cast("object", self.route_avoid_crossing), bool) or (
            self.route_avoid_crossing and not self.leader_auto_route
        ):
            raise ValueError("invalid route crossing policy")
        _identity(self.frame_id)
        rows = tuple(self.rows)
        if (
            not rows
            or len(rows) > 16
            or any(not isinstance(cast("object", item), ToleranceRow) for item in rows)
        ):
            raise ValueError("a frame requires 1–16 tolerance rows")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "position_mm", _point(self.position_mm))
        if self.leader_target_mm is not None:
            object.__setattr__(self, "leader_target_mm", _point(self.leader_target_mm))
        if self.surface_indication is not None and (
            not isinstance(cast("object", self.surface_indication), SurfaceIndication)
            or self.leader_target_mm is None
        ):
            raise ValueError("surface indication requires a leader target")
        if (
            self.surface_indication is not None
            and self.surface_indication.auto_normal
            and self.leader_attachment is None
        ):
            raise ValueError("surface normal requires a geometry attachment")
        if self.leader_attachment is not None and (
            not isinstance(cast("object", self.leader_attachment), DatumAttachment)
            or self.leader_target_mm is None
        ):
            raise ValueError("frame attachment requires a leader target")
        if self.leader_annotation_attachment is not None and (
            not isinstance(cast("object", self.leader_annotation_attachment), AnnotationAttachment)
            or self.leader_target_mm is None
            or self.leader_attachment is not None
        ):
            raise ValueError("frame leader requires a single attachment target")
        if self.leader_anchor_offset is not None:
            if self.leader_target_mm is None:
                raise ValueError("frame leader anchor requires a target")
            object.__setattr__(self, "leader_anchor_offset", _point(self.leader_anchor_offset))
        raw_offsets = cast("object", self.leader_offsets)
        if not isinstance(raw_offsets, list | tuple):
            raise ValueError("invalid frame leader vertices")
        points = cast("Sequence[object]", raw_offsets)
        if len(points) > 64 or (points and self.leader_target_mm is None):
            raise ValueError("frame leader vertices require a target")
        object.__setattr__(self, "leader_offsets", tuple(_point(point) for point in points))
        if not isinstance(cast("object", self.leader_auto_normal), bool) or (
            self.leader_auto_normal
            and (
                self.leader_attachment is None or not points or self.surface_indication is not None
            )
        ):
            raise ValueError(
                "frame normal constraint requires geometry attachment and edge leader vertex"
            )
        if not isinstance(cast("object", self.leader_auto_route), bool) or (
            self.leader_auto_route and not self.leader_auto_normal
        ):
            raise ValueError("automatic leader route requires a normal constraint")
        if self.leader_auto_normal and self.leader_target_mm is not None:
            last = self.leader_offsets[-1]
            vertex = (self.position_mm[0] + last[0], self.position_mm[1] + last[1])
            if math.dist(vertex, self.leader_target_mm) <= 1e-9:
                raise ValueError("frame normal leader segment must have length")
        raw = cast("object", self.rotation_deg)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("rotation must be finite")
        try:
            rotation = float(raw)
        except OverflowError as exc:
            raise ValueError("rotation must be finite") from exc
        if not math.isfinite(rotation):
            raise ValueError("rotation must be finite")
        object.__setattr__(self, "rotation_deg", rotation)
        _label(self.layer_name)
        if self.text_style_id is not None:
            _label(self.text_style_id)

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "frame_id": self.frame_id,
            "rows": [row.to_mapping() for row in self.rows],
            "position_mm": list(self.position_mm),
            "rotation_deg": self.rotation_deg,
            "layer_name": self.layer_name,
        }
        if self.text_style_id is not None:
            result["text_style_id"] = self.text_style_id
        if self.leader_target_mm is not None:
            result["leader_target_mm"] = list(self.leader_target_mm)
        if self.leader_offsets:
            result["leader_offsets"] = [list(point) for point in self.leader_offsets]
        if self.leader_anchor_offset is not None:
            result["leader_anchor_offset"] = list(self.leader_anchor_offset)
        if self.leader_attachment is not None:
            result["leader_attachment"] = self.leader_attachment.to_mapping()
        if self.leader_annotation_attachment is not None:
            result["leader_annotation_attachment"] = self.leader_annotation_attachment.to_mapping()
        if self.surface_indication is not None:
            result["surface_indication"] = self.surface_indication.to_mapping()
        if self.leader_auto_normal:
            result["leader_auto_normal"] = True
        if self.leader_auto_route:
            result["leader_auto_route"] = True
        if self.route_avoid_crossing:
            result["route_avoid_crossing"] = True
        if self.route_track_target:
            result["route_track_target"] = True
        if self.route_algorithm_version != 1:
            result["route_algorithm_version"] = self.route_algorithm_version
        if self.leader_arrow_style != "legacy":
            result["leader_arrow_style"] = self.leader_arrow_style
        return result

    @classmethod
    def from_mapping(cls, value: object) -> FeatureControlFrame:
        fields = {"frame_id", "rows", "position_mm", "rotation_deg", "layer_name"}
        if isinstance(value, Mapping) and "text_style_id" in value:
            fields.add("text_style_id")
        if isinstance(value, Mapping) and "leader_target_mm" in value:
            fields.add("leader_target_mm")
        if isinstance(value, Mapping) and "leader_offsets" in value:
            fields.add("leader_offsets")
        if isinstance(value, Mapping) and "leader_anchor_offset" in value:
            fields.add("leader_anchor_offset")
        if isinstance(value, Mapping) and "leader_attachment" in value:
            fields.add("leader_attachment")
        if isinstance(value, Mapping) and "leader_annotation_attachment" in value:
            fields.add("leader_annotation_attachment")
        if isinstance(value, Mapping) and "surface_indication" in value:
            fields.add("surface_indication")
        if isinstance(value, Mapping) and "leader_auto_normal" in value:
            fields.add("leader_auto_normal")
        if isinstance(value, Mapping) and "leader_auto_route" in value:
            fields.add("leader_auto_route")
        if isinstance(value, Mapping) and "route_avoid_crossing" in value:
            fields.add("route_avoid_crossing")
        if isinstance(value, Mapping) and "route_track_target" in value:
            fields.add("route_track_target")
        if isinstance(value, Mapping) and "route_algorithm_version" in value:
            fields.add("route_algorithm_version")
        if isinstance(value, Mapping) and "leader_arrow_style" in value:
            fields.add("leader_arrow_style")
        data = _mapping(cast("object", value), fields)
        rows = data["rows"]
        if not isinstance(rows, list | tuple):
            raise ValueError("rows must be an array")
        offsets = data.get("leader_offsets", ())
        if not isinstance(offsets, list | tuple):
            raise ValueError("invalid frame leader vertices")
        return cls(
            cast("str", data["frame_id"]),
            tuple(ToleranceRow.from_mapping(item) for item in cast("Sequence[object]", rows)),
            _point(data["position_mm"]),
            cast("float", data["rotation_deg"]),
            cast("str", data["layer_name"]),
            cast("str | None", data.get("text_style_id")),
            _point(data["leader_target_mm"]) if "leader_target_mm" in data else None,
            tuple(_point(point) for point in cast("Sequence[object]", offsets)),
            _point(data["leader_anchor_offset"]) if "leader_anchor_offset" in data else None,
            DatumAttachment.from_mapping(data["leader_attachment"])
            if "leader_attachment" in data
            else None,
            AnnotationAttachment.from_mapping(data["leader_annotation_attachment"])
            if "leader_annotation_attachment" in data
            else None,
            SurfaceIndication.from_mapping(data["surface_indication"])
            if "surface_indication" in data
            else None,
            cast("bool", data.get("leader_auto_normal", False)),
            cast("bool", data.get("leader_auto_route", False)),
            cast("bool", data.get("route_avoid_crossing", False)),
            cast("bool", data.get("route_track_target", False)),
            cast("int", data.get("route_algorithm_version", 1)),
            cast("str", data.get("leader_arrow_style", "legacy")),
        )


@dataclass(frozen=True, slots=True)
class DatumAttachment:
    """Stable point reference or normalized position on a curve."""

    sketch_id: str
    reference: SketchGeometryReference
    parameter: float | None = None
    segment_count: int | None = None
    segment_kind: str | None = None
    curve_kind: str | None = None
    control_count: int | None = None
    surface_extension: SurfaceExtensionSpec | None = None

    def __post_init__(self) -> None:
        _identity(self.sketch_id)
        if not isinstance(cast("object", self.reference), SketchGeometryReference):
            raise ValueError("invalid datum reference")
        if self.reference.kind in ("start", "end", "center", "vertex"):
            if self.parameter is not None:
                raise ValueError("point reference does not accept a parameter")
        elif self.reference.kind in ("geometry", "segment"):
            raw = cast("object", self.parameter)
            if isinstance(raw, bool) or not isinstance(raw, int | float) or not 0 <= raw <= 1:
                raise ValueError("curve attachment requires a normalized parameter")
            object.__setattr__(self, "parameter", float(raw))
        else:
            raise ValueError("unsupported datum attachment reference")
        count = cast("object", self.segment_count)
        if self.reference.kind == "segment":
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count <= 0
                or self.reference.index is None
                or self.reference.index >= count
            ):
                raise ValueError("polyline attachment requires its original segment count")
        elif count is not None:
            raise ValueError("segment count applies only to polyline segments")
        if self.segment_kind is not None and (
            self.segment_kind != "rectangle"
            or self.reference.kind != "segment"
            or self.segment_count != 4
        ):
            raise ValueError("invalid datum attachment segment kind")
        if self.curve_kind == "spline":
            count = cast("object", self.control_count)
            if (
                self.reference.kind != "geometry"
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 4
            ):
                raise ValueError("spline attachment requires its original control point count")
        elif self.curve_kind == "ellipse":
            if self.reference.kind != "geometry" or self.control_count is not None:
                raise ValueError("ellipse attachment requires a curve parameter")
        elif self.curve_kind is not None or self.control_count is not None:
            raise ValueError("invalid datum attachment curve kind")
        if self.surface_extension is not None and (
            not isinstance(cast("object", self.surface_extension), SurfaceExtensionSpec)
            or self.reference.kind != "geometry"
            or self.curve_kind is not None
            or self.parameter != (0.0 if self.surface_extension.side == "start" else 1.0)
        ):
            raise ValueError("invalid surface extension attachment")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "sketch_id": self.sketch_id,
            "reference": self.reference.to_mapping(),
        }
        if self.parameter is not None:
            result["parameter"] = self.parameter
        if self.segment_count is not None:
            result["segment_count"] = self.segment_count
        if self.segment_kind is not None:
            result["segment_kind"] = self.segment_kind
        if self.curve_kind is not None:
            result["curve_kind"] = self.curve_kind
        if self.control_count is not None:
            result["control_count"] = self.control_count
        if self.surface_extension is not None:
            result["surface_extension"] = self.surface_extension.to_mapping()
        return result

    @classmethod
    def from_mapping(cls, value: object) -> DatumAttachment:
        if not isinstance(value, Mapping):
            raise ValueError("invalid datum attachment")
        fields = {"sketch_id", "reference"}
        if "parameter" in value:
            fields.add("parameter")
        if "segment_count" in value:
            fields.add("segment_count")
        if "segment_kind" in value:
            fields.add("segment_kind")
        if "curve_kind" in value:
            fields.add("curve_kind")
        if "control_count" in value:
            fields.add("control_count")
        if "surface_extension" in value:
            fields.add("surface_extension")
        data = _mapping(cast("object", value), fields)
        return cls(
            cast("str", data["sketch_id"]),
            SketchGeometryReference.from_mapping(data["reference"]),
            cast("float | None", data.get("parameter")),
            cast("int | None", data.get("segment_count")),
            cast("str | None", data.get("segment_kind")),
            cast("str | None", data.get("curve_kind")),
            cast("int | None", data.get("control_count")),
            SurfaceExtensionSpec.from_mapping(data["surface_extension"])
            if "surface_extension" in data
            else None,
        )


@dataclass(frozen=True, slots=True)
class DatumIdentifier:
    datum_id: str
    label: str
    position_mm: tuple[float, float]
    target_mm: tuple[float, float]
    layer_name: str = "0"
    attachment: DatumAttachment | None = None
    text_style_id: str | None = None
    leader_offsets: tuple[tuple[float, float], ...] = ()
    leader_auto_normal: bool = False
    leader_visible: bool = True
    layout_mode: str = "legacy"
    annotation_attachment: AnnotationAttachment | None = None
    surface_indication: SurfaceIndication | None = None
    spline_normal_enabled: bool = False
    leader_auto_route: bool = False
    route_avoid_crossing: bool = False
    route_track_target: bool = False
    route_algorithm_version: int = 1
    box_size_mm: tuple[float, float] | None = None
    arrow_style: str = "filled"
    symbol_style: str = "rectangle"
    bar_direction: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.bar_direction is not None:
            direction = _point(self.bar_direction)
            length = math.hypot(*direction)
            if not math.isfinite(length) or length <= 1e-12:
                raise ValueError("invalid datum bar direction")
            object.__setattr__(
                self, "bar_direction", (direction[0] / length, direction[1] / length)
            )
        if self.symbol_style not in ("rectangle", "circle"):
            raise ValueError("invalid datum symbol style")
        if self.symbol_style == "circle" and (
            not self.leader_visible or self.surface_indication is not None
        ):
            raise ValueError("circular datum requires a regular leader")
        if self.arrow_style not in ("filled", "open", "none"):
            raise ValueError("invalid datum arrow style")
        if (
            type(self.route_algorithm_version) is not int
            or self.route_algorithm_version not in (1, 2, 3, 4)
            or (self.route_algorithm_version >= 2 and not self.route_track_target)
            or (self.route_algorithm_version >= 3 and self.box_size_mm is None)
        ):
            raise ValueError("invalid automatic route algorithm version")
        if not isinstance(cast("object", self.route_track_target), bool) or (
            self.route_track_target and not self.route_avoid_crossing
        ):
            raise ValueError("target tracking requires crossing-safe routing")
        if not isinstance(cast("object", self.route_avoid_crossing), bool) or (
            self.route_avoid_crossing and not self.leader_auto_route
        ):
            raise ValueError("invalid route crossing policy")
        _identity(self.datum_id)
        _label(self.label)
        _label(self.layer_name)
        if self.text_style_id is not None:
            _label(self.text_style_id)
        object.__setattr__(self, "position_mm", _point(self.position_mm))
        object.__setattr__(self, "target_mm", _point(self.target_mm))
        raw_offsets = cast("object", self.leader_offsets)
        if not isinstance(raw_offsets, (list, tuple)):
            raise ValueError("invalid datum leader vertices")
        points = cast("Sequence[object]", raw_offsets)
        if len(points) > 64:
            raise ValueError("invalid datum leader vertices")
        object.__setattr__(self, "leader_offsets", tuple(_point(p) for p in points))
        if not isinstance(cast("object", self.leader_auto_normal), bool):
            raise ValueError("invalid datum normal constraint")
        if not isinstance(cast("object", self.spline_normal_enabled), bool):
            raise ValueError("invalid spline normal flag")
        if self.leader_auto_normal and (self.attachment is None or not self.leader_offsets):
            raise ValueError("normal constraint requires an attached leader vertex")
        if not isinstance(cast("object", self.leader_auto_route), bool) or (
            self.leader_auto_route and not self.leader_auto_normal
        ):
            raise ValueError("automatic leader route requires a normal constraint")
        if not isinstance(cast("object", self.leader_visible), bool):
            raise ValueError("invalid datum leader visibility")
        if self.layout_mode not in ("legacy", "shared"):
            raise ValueError("invalid datum layout mode")
        if self.box_size_mm is not None:
            try:
                box_size = _point(self.box_size_mm)
            except ValueError as exc:
                raise ValueError("invalid datum box size") from exc
            if self.layout_mode != "shared" or min(box_size) <= 0:
                raise ValueError("invalid datum box size")
            object.__setattr__(self, "box_size_mm", box_size)
        if not self.leader_visible and (
            self.attachment is not None
            or self.annotation_attachment is not None
            or self.leader_offsets
            or self.leader_auto_normal
            or self.surface_indication is not None
        ):
            raise ValueError("a datum without a leader cannot have a leader attachment or vertices")
        if self.surface_indication is not None and not isinstance(
            cast("object", self.surface_indication), SurfaceIndication
        ):
            raise ValueError("invalid surface indication")
        if (
            self.surface_indication is not None
            and self.surface_indication.auto_normal
            and self.attachment is None
        ):
            raise ValueError("surface normal requires a geometry attachment")
        if (
            self.surface_indication is not None
            and self.surface_indication.auto_normal
            and self.leader_auto_normal
        ):
            raise ValueError("normal constraint cannot apply to both leaders")
        if self.attachment is not None and not isinstance(
            cast("object", self.attachment), DatumAttachment
        ):
            raise ValueError("invalid datum attachment")
        if self.annotation_attachment is not None and (
            not isinstance(cast("object", self.annotation_attachment), AnnotationAttachment)
            or self.attachment is not None
            or self.leader_auto_normal
        ):
            raise ValueError("datum leader requires a single valid attachment")

    def to_mapping(self) -> dict[str, object]:
        data: dict[str, object] = {
            "datum_id": self.datum_id,
            "label": self.label,
            "position_mm": list(self.position_mm),
            "target_mm": list(self.target_mm),
            "layer_name": self.layer_name,
        }
        if self.attachment is not None:
            data["attachment"] = self.attachment.to_mapping()
        if self.text_style_id is not None:
            data["text_style_id"] = self.text_style_id
        if self.leader_offsets:
            data["leader_offsets"] = [list(point) for point in self.leader_offsets]
        if self.leader_auto_normal:
            data["leader_auto_normal"] = True
        if self.leader_auto_route:
            data["leader_auto_route"] = True
        if self.route_avoid_crossing:
            data["route_avoid_crossing"] = True
        if self.route_track_target:
            data["route_track_target"] = True
        if self.route_algorithm_version != 1:
            data["route_algorithm_version"] = self.route_algorithm_version
        if self.box_size_mm is not None:
            data["box_size_mm"] = list(self.box_size_mm)
        if self.arrow_style != "filled":
            data["arrow_style"] = self.arrow_style
        if self.symbol_style != "rectangle":
            data["symbol_style"] = self.symbol_style
        if self.bar_direction is not None:
            data["bar_direction"] = list(self.bar_direction)
        if not self.leader_visible:
            data["leader_visible"] = False
        if self.layout_mode != "legacy":
            data["layout_mode"] = self.layout_mode
        if self.annotation_attachment is not None:
            data["annotation_attachment"] = self.annotation_attachment.to_mapping()
        if self.surface_indication is not None:
            data["surface_indication"] = self.surface_indication.to_mapping()
        if self.spline_normal_enabled:
            data["spline_normal_enabled"] = True
        return data

    @classmethod
    def from_mapping(cls, value: object) -> DatumIdentifier:
        if not isinstance(value, Mapping):
            raise ValueError("invalid datum identifier")
        fields = {"datum_id", "label", "position_mm", "target_mm", "layer_name"}
        if "attachment" in value:
            fields.add("attachment")
        if "text_style_id" in value:
            fields.add("text_style_id")
        if "leader_offsets" in value:
            fields.add("leader_offsets")
        if "leader_auto_normal" in value:
            fields.add("leader_auto_normal")
        if "leader_auto_route" in value:
            fields.add("leader_auto_route")
        if "leader_visible" in value:
            fields.add("leader_visible")
        if "layout_mode" in value:
            fields.add("layout_mode")
        if "annotation_attachment" in value:
            fields.add("annotation_attachment")
        if "surface_indication" in value:
            fields.add("surface_indication")
        if "spline_normal_enabled" in value:
            fields.add("spline_normal_enabled")
        if "route_avoid_crossing" in value:
            fields.add("route_avoid_crossing")
        if "route_track_target" in value:
            fields.add("route_track_target")
        if "route_algorithm_version" in value:
            fields.add("route_algorithm_version")
        if "box_size_mm" in value:
            fields.add("box_size_mm")
        if "arrow_style" in value:
            fields.add("arrow_style")
        if "symbol_style" in value:
            fields.add("symbol_style")
        if "bar_direction" in value:
            fields.add("bar_direction")
        data = _mapping(cast("object", value), fields)
        offsets = data.get("leader_offsets", ())
        if not isinstance(offsets, list | tuple):
            raise ValueError("invalid datum leader vertices")
        return cls(
            cast("str", data["datum_id"]),
            cast("str", data["label"]),
            _point(data["position_mm"]),
            _point(data["target_mm"]),
            cast("str", data["layer_name"]),
            DatumAttachment.from_mapping(data["attachment"]) if "attachment" in data else None,
            cast("str | None", data.get("text_style_id")),
            tuple(_point(point) for point in cast("Sequence[object]", offsets)),
            cast("bool", data.get("leader_auto_normal", False)),
            cast("bool", data.get("leader_visible", True)),
            cast("str", data.get("layout_mode", "legacy")),
            AnnotationAttachment.from_mapping(data["annotation_attachment"])
            if "annotation_attachment" in data
            else None,
            SurfaceIndication.from_mapping(data["surface_indication"])
            if "surface_indication" in data
            else None,
            cast("bool", data.get("spline_normal_enabled", False)),
            cast("bool", data.get("leader_auto_route", False)),
            cast("bool", data.get("route_avoid_crossing", False)),
            cast("bool", data.get("route_track_target", False)),
            cast("int", data.get("route_algorithm_version", 1)),
            _point(data["box_size_mm"]) if "box_size_mm" in data else None,
            cast("str", data.get("arrow_style", "filled")),
            cast("str", data.get("symbol_style", "rectangle")),
            _point(data["bar_direction"]) if "bar_direction" in data else None,
        )
