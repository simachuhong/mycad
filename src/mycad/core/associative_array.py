# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Replayable identities and dependency validation for rectangular arrays."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, cast
from uuid import UUID

from mycad.core.cross_sketch_tangency import (
    CrossSketchTangency,
    closed_polyline_vertex_rotation_index,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import move_entities, rectangular_array_displacement, rotate_entities
from mycad.core.sketch_references import resolve_point_reference

if TYPE_CHECKING:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a canonical UUID") from exc
    if value not in (parsed.hex, str(parsed)):
        raise ValueError(f"{field} must be a canonical UUID")
    return value


def _mapping(value: object, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("关联阵列记录格式无效。")
    data = cast("Mapping[str, object]", value)
    if frozenset(data) != fields:
        raise ValueError("关联阵列记录包含缺失或未知字段。")
    return data


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be finite")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class ArrayEntityRef:
    """Stable identity of an entire sketch entity."""

    sketch_id: str
    entity_id: str

    def __post_init__(self) -> None:
        _identity(self.sketch_id, "sketch_id")
        _identity(self.entity_id, "entity_id")

    def to_mapping(self) -> dict[str, object]:
        return {"sketch_id": self.sketch_id, "entity_id": self.entity_id}

    @classmethod
    def from_mapping(cls, value: object) -> ArrayEntityRef:
        data = _mapping(value, frozenset(("sketch_id", "entity_id")))
        return cls(
            _identity(data["sketch_id"], "sketch_id"), _identity(data["entity_id"], "entity_id")
        )


@dataclass(frozen=True, slots=True)
class ArrayBasePoint:
    """A fixed array-plane point or a point bound to one source entity."""

    point_mm: Point2D | None = None
    source: ArrayEntityRef | None = None
    reference: SketchGeometryReference | None = None

    def __post_init__(self) -> None:
        if self.point_mm is not None:
            if self.source is not None or self.reference is not None:
                raise ValueError("阵列基点不能同时是固定点和关键点。")
            object.__setattr__(self, "point_mm", _grip_point(self.point_mm))
        elif not isinstance(self.source, ArrayEntityRef) or not isinstance(
            self.reference, SketchGeometryReference
        ):
            raise ValueError("阵列基点需要固定坐标或有效源关键点。")
        elif self.reference.entity_id != self.source.entity_id or self.reference.kind not in (
            "start",
            "end",
            "center",
            "vertex",
        ):
            raise ValueError("阵列基点关键点引用无效。")

    def to_mapping(self) -> dict[str, object]:
        if self.point_mm is not None:
            return {"point_mm": list(self.point_mm)}
        assert self.source is not None and self.reference is not None
        return {"source": self.source.to_mapping(), "reference": self.reference.to_mapping()}

    @classmethod
    def from_mapping(cls, value: object) -> ArrayBasePoint:
        if isinstance(value, Mapping) and "point_mm" in value:
            data = _mapping(cast("object", value), frozenset({"point_mm"}))
            point = data["point_mm"]
            if not isinstance(point, list | tuple):
                raise ValueError("阵列基点必须是二维坐标。")
            coordinates = cast("list[object] | tuple[object, ...]", point)
            if len(coordinates) != 2:
                raise ValueError("阵列基点必须是二维坐标。")
            return cls(
                point_mm=(_number(coordinates[0], "base x"), _number(coordinates[1], "base y"))
            )
        data = _mapping(cast("object", value), frozenset({"source", "reference"}))
        return cls(
            source=ArrayEntityRef.from_mapping(data["source"]),
            reference=SketchGeometryReference.from_mapping(data["reference"]),
        )


@dataclass(frozen=True, slots=True)
class ArrayReplacement:
    """A live replacement source and its base offset from the source anchor."""

    source: ArrayEntityRef
    base_offset_mm: Point2D = (0.0, 0.0)
    anchor_source: ArrayEntityRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.source), ArrayEntityRef):
            raise ValueError("阵列替换来源无效。")
        if self.anchor_source is not None and not isinstance(
            cast("object", self.anchor_source), ArrayEntityRef
        ):
            raise ValueError("阵列替换共同锚点来源无效。")
        object.__setattr__(self, "base_offset_mm", _grip_point(self.base_offset_mm))

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source": self.source.to_mapping(),
            "base_offset_mm": list(self.base_offset_mm),
        }
        if self.anchor_source is not None:
            result["anchor_source"] = self.anchor_source.to_mapping()
        return result

    @classmethod
    def from_mapping(cls, value: object) -> ArrayReplacement:
        fields = frozenset(("source", "base_offset_mm"))
        if isinstance(value, Mapping) and "anchor_source" in value:
            fields |= {"anchor_source"}
        data = _mapping(cast("object", value), fields)
        raw = data["base_offset_mm"]
        if not isinstance(raw, list | tuple):
            raise ValueError("阵列替换基点偏移无效。")
        point = cast("tuple[object, ...] | list[object]", raw)
        if len(point) != 2:
            raise ValueError("阵列替换基点偏移无效。")
        return cls(
            ArrayEntityRef.from_mapping(data["source"]),
            (_number(point[0], "base x"), _number(point[1], "base y")),
            ArrayEntityRef.from_mapping(data["anchor_source"]) if "anchor_source" in data else None,
        )


@dataclass(frozen=True, slots=True)
class ArrayExtraOutput:
    """A stable additional entity in a replaced array cell."""

    source: ArrayEntityRef
    target: ArrayEntityRef
    anchor_source: ArrayEntityRef
    row: int
    column: int
    base_offset_mm: Point2D = (0.0, 0.0)
    offset_mm: Point2D = (0.0, 0.0)
    rotation_deg: float = 0.0
    rotation_center_offset_mm: Point2D = (0.0, 0.0)

    def __post_init__(self) -> None:
        if any(
            not isinstance(cast("object", ref), ArrayEntityRef)
            for ref in (self.source, self.target, self.anchor_source)
        ):
            raise ValueError("额外阵列输出引用无效。")
        if self.source == self.target or self.anchor_source == self.target:
            raise ValueError("额外阵列输出不能引用自身。")
        row, column = _integer(self.row, "row"), _integer(self.column, "column")
        if row < 0 or column < 0 or (row == 0 and column == 0):
            raise ValueError("额外阵列输出位置无效。")
        object.__setattr__(self, "base_offset_mm", _grip_point(self.base_offset_mm))
        object.__setattr__(self, "offset_mm", _grip_point(self.offset_mm))
        angle = _number(self.rotation_deg, "rotation_deg")
        center = _grip_point(self.rotation_center_offset_mm)
        if angle == 0 and center != (0.0, 0.0):
            raise ValueError("无旋转时不能指定旋转中心偏移。")
        object.__setattr__(self, "rotation_deg", angle)
        object.__setattr__(self, "rotation_center_offset_mm", center)

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source": self.source.to_mapping(),
            "target": self.target.to_mapping(),
            "anchor_source": self.anchor_source.to_mapping(),
            "row": self.row,
            "column": self.column,
            "base_offset_mm": list(self.base_offset_mm),
        }
        if self.offset_mm != (0.0, 0.0):
            result["offset_mm"] = list(self.offset_mm)
        if self.rotation_deg != 0.0:
            result["rotation_deg"] = self.rotation_deg
            result["rotation_center_offset_mm"] = list(self.rotation_center_offset_mm)
        return result

    @classmethod
    def from_mapping(cls, value: object) -> ArrayExtraOutput:
        fields = frozenset(("source", "target", "anchor_source", "row", "column", "base_offset_mm"))
        if isinstance(value, Mapping) and "offset_mm" in value:
            fields |= {"offset_mm"}
        if isinstance(value, Mapping) and (
            "rotation_deg" in value or "rotation_center_offset_mm" in value
        ):
            fields |= {"rotation_deg", "rotation_center_offset_mm"}
        data = _mapping(cast("object", value), fields)
        raw = data["base_offset_mm"]
        if not isinstance(raw, list | tuple):
            raise ValueError("额外阵列输出基点偏移无效。")
        point = cast("tuple[object, ...] | list[object]", raw)
        if len(point) != 2:
            raise ValueError("额外阵列输出基点偏移无效。")
        raw_offset = data.get("offset_mm", (0.0, 0.0))
        if not isinstance(raw_offset, list | tuple):
            raise ValueError("额外输出偏移必须是二维坐标。")
        offset = cast("tuple[object, ...] | list[object]", raw_offset)
        if len(offset) != 2:
            raise ValueError("额外输出偏移必须是二维坐标。")
        raw_center = data.get("rotation_center_offset_mm", (0.0, 0.0))
        if not isinstance(raw_center, list | tuple):
            raise ValueError("额外输出旋转中心必须是二维坐标。")
        center = cast("tuple[object, ...] | list[object]", raw_center)
        if len(center) != 2:
            raise ValueError("额外输出旋转中心必须是二维坐标。")
        return cls(
            ArrayEntityRef.from_mapping(data["source"]),
            ArrayEntityRef.from_mapping(data["target"]),
            ArrayEntityRef.from_mapping(data["anchor_source"]),
            _integer(data["row"], "row"),
            _integer(data["column"], "column"),
            (_number(point[0], "base x"), _number(point[1], "base y")),
            (_number(offset[0], "offset x"), _number(offset[1], "offset y")),
            _number(data.get("rotation_deg", 0.0), "rotation_deg"),
            (_number(center[0], "center x"), _number(center[1], "center y")),
        )


@dataclass(frozen=True, slots=True)
class ArrayMember:
    """One stable generated entity at a non-origin array position."""

    source: ArrayEntityRef
    target: ArrayEntityRef
    row: int
    column: int
    offset_mm: Point2D = (0.0, 0.0)
    rotation_deg: float = 0.0
    rotation_center_offset_mm: Point2D = (0.0, 0.0)
    erased_index: int | None = None
    erased_neighbors: tuple[str | None, str | None] | None = None
    replacement: ArrayReplacement | None = None

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.source), ArrayEntityRef) or not isinstance(
            cast("object", self.target), ArrayEntityRef
        ):
            raise ValueError("阵列成员必须包含有效的源和目标引用。")
        row, column = _integer(self.row, "row"), _integer(self.column, "column")
        if row < 0 or column < 0 or (row == 0 and column == 0):
            raise ValueError("阵列成员位置无效。")
        object.__setattr__(self, "offset_mm", _grip_point(self.offset_mm))
        angle = _number(self.rotation_deg, "rotation_deg")
        center = _grip_point(self.rotation_center_offset_mm)
        if angle == 0 and center != (0.0, 0.0):
            raise ValueError("无旋转时不能指定旋转中心偏移。")
        object.__setattr__(self, "rotation_deg", angle)
        object.__setattr__(self, "rotation_center_offset_mm", center)
        if self.erased_index is not None and _integer(self.erased_index, "erased_index") < 0:
            raise ValueError("擦除位置不能为负数。")
        if self.erased_neighbors is not None:
            if (
                self.erased_index is None
                or not isinstance(cast("object", self.erased_neighbors), tuple)
                or len(self.erased_neighbors) != 2
            ):
                raise ValueError("擦除邻接记录无效。")
            for neighbor in self.erased_neighbors:
                if neighbor is not None:
                    _identity(neighbor, "erased neighbor")
                    if neighbor == self.target.entity_id:
                        raise ValueError("擦除成员不能是自己的邻居。")
            if (
                self.erased_neighbors[0] is not None
                and self.erased_neighbors[0] == self.erased_neighbors[1]
            ):
                raise ValueError("擦除成员的邻居不能重复。")
        if self.replacement is not None and (
            not isinstance(cast("object", self.replacement), ArrayReplacement)
            or self.replacement.source == self.target
        ):
            raise ValueError("阵列替换来源无效或自引用。")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source": self.source.to_mapping(),
            "target": self.target.to_mapping(),
            "row": self.row,
            "column": self.column,
        }
        if self.offset_mm != (0.0, 0.0):
            result["offset_mm"] = list(self.offset_mm)
        if self.rotation_deg != 0.0:
            result["rotation_deg"] = self.rotation_deg
            if self.rotation_center_offset_mm != (0.0, 0.0):
                result["rotation_center_offset_mm"] = list(self.rotation_center_offset_mm)
        if self.erased_index is not None:
            result["erased_index"] = self.erased_index
        if self.erased_neighbors is not None:
            neighbors: dict[str, str] = {}
            if self.erased_neighbors[0] is not None:
                neighbors["before"] = self.erased_neighbors[0]
            if self.erased_neighbors[1] is not None:
                neighbors["after"] = self.erased_neighbors[1]
            result["erased_neighbors"] = neighbors
        if self.replacement is not None:
            result["replacement"] = self.replacement.to_mapping()
        return result

    @classmethod
    def from_mapping(cls, value: object) -> ArrayMember:
        keys = frozenset(("source", "target", "row", "column"))
        if isinstance(value, Mapping) and "offset_mm" in value:
            keys |= {"offset_mm"}
        if isinstance(value, Mapping) and "rotation_deg" in value:
            keys |= {"rotation_deg"}
        if isinstance(value, Mapping) and "rotation_center_offset_mm" in value:
            keys |= {"rotation_center_offset_mm"}
        if isinstance(value, Mapping) and "erased_index" in value:
            keys |= {"erased_index"}
        if isinstance(value, Mapping) and "erased_neighbors" in value:
            keys |= {"erased_neighbors"}
        if isinstance(value, Mapping) and "replacement" in value:
            keys |= {"replacement"}
        data = _mapping(cast("object", value), keys)
        raw_offset = data.get("offset_mm", (0.0, 0.0))
        if not isinstance(raw_offset, list | tuple):
            raise ValueError("阵列成员偏移必须是二维坐标。")
        coordinates = cast("tuple[object, ...] | list[object]", raw_offset)
        if len(coordinates) != 2:
            raise ValueError("阵列成员偏移必须是二维坐标。")
        raw_center = data.get("rotation_center_offset_mm", (0.0, 0.0))
        if not isinstance(raw_center, list | tuple):
            raise ValueError("阵列成员旋转中心偏移必须是二维坐标。")
        center = cast("tuple[object, ...] | list[object]", raw_center)
        if len(center) != 2:
            raise ValueError("阵列成员旋转中心偏移必须是二维坐标。")
        neighbors: tuple[str | None, str | None] | None = None
        if "erased_neighbors" in data:
            raw_neighbors = data["erased_neighbors"]
            if not isinstance(raw_neighbors, Mapping):
                raise ValueError("擦除邻接记录无效。")
            mapping = cast("Mapping[str, object]", raw_neighbors)
            if not set(mapping).issubset({"before", "after"}):
                raise ValueError("擦除邻接记录无效。")
            neighbors = (
                _identity(mapping["before"], "before") if "before" in mapping else None,
                _identity(mapping["after"], "after") if "after" in mapping else None,
            )
        return cls(
            ArrayEntityRef.from_mapping(data["source"]),
            ArrayEntityRef.from_mapping(data["target"]),
            _integer(data["row"], "row"),
            _integer(data["column"], "column"),
            (_number(coordinates[0], "offset x"), _number(coordinates[1], "offset y")),
            _number(data.get("rotation_deg", 0.0), "rotation_deg"),
            (_number(center[0], "rotation center x"), _number(center[1], "rotation center y")),
            _integer(data["erased_index"], "erased_index") if "erased_index" in data else None,
            neighbors,
            ArrayReplacement.from_mapping(data["replacement"]) if "replacement" in data else None,
        )


@dataclass(frozen=True, slots=True)
class AssociativeRectArray:
    """A complete source-to-member grid with deterministic identities."""

    array_id: str
    frame: WorkPlaneFrame
    rows: int
    columns: int
    row_spacing: float
    column_spacing: float
    sources: tuple[ArrayEntityRef, ...]
    members: tuple[ArrayMember, ...]
    angle_deg: float = 0.0
    base_point: ArrayBasePoint | None = None
    extra_outputs: tuple[ArrayExtraOutput, ...] = ()

    def __post_init__(self) -> None:
        _identity(self.array_id, "array_id")
        if not isinstance(cast("object", self.frame), WorkPlaneFrame):
            raise ValueError("关联阵列需要有效工作平面。")
        rows, columns = _integer(self.rows, "rows"), _integer(self.columns, "columns")
        dy = _number(self.row_spacing, "row_spacing")
        dx = _number(self.column_spacing, "column_spacing")
        angle = _number(self.angle_deg, "angle_deg")
        if rows < 1 or columns < 1 or not 2 <= rows * columns <= 1000:
            raise ValueError("关联阵列的位置数必须为 2 到 1000。")
        if (rows > 1 and abs(dy) <= 1e-9) or (columns > 1 and abs(dx) <= 1e-9):
            raise ValueError("关联阵列活动方向的间距不能为零。")
        sources = tuple(self.sources)
        members = tuple(self.members)
        if not sources or any(
            not isinstance(cast("object", ref), ArrayEntityRef) for ref in sources
        ):
            raise ValueError("关联阵列至少需要一个有效源。")
        if len(set(sources)) != len(sources):
            raise ValueError("关联阵列源引用重复。")
        if self.base_point is not None and (
            not isinstance(cast("object", self.base_point), ArrayBasePoint)
            or (self.base_point.source is not None and self.base_point.source not in sources)
        ):
            raise ValueError("阵列基点必须引用阵列源。")
        if any(not isinstance(cast("object", member), ArrayMember) for member in members):
            raise ValueError("关联阵列成员无效。")
        if any(
            member.replacement is not None
            and member.replacement.anchor_source is not None
            and member.replacement.anchor_source not in sources
            for member in members
        ):
            raise ValueError("替换共同锚点必须引用阵列来源。")
        if len(members) > 10000 or (rows * columns - 1) * len(sources) > 10000:
            raise ValueError("关联阵列成员超过 10000 个。")
        expected = {
            (source, row, column)
            for source in sources
            for row in range(rows)
            for column in range(columns)
            if row or column
        }
        actual = {(member.source, member.row, member.column) for member in members}
        targets = [member.target for member in members]
        if actual != expected or len(actual) != len(members):
            raise ValueError("关联阵列成员位置缺失、重复或越界。")
        if len(set(targets)) != len(targets) or set(targets) & set(sources):
            raise ValueError("关联阵列目标重复或与源重合。")
        extras = tuple(self.extra_outputs)
        if any(not isinstance(cast("object", item), ArrayExtraOutput) for item in extras):
            raise ValueError("额外阵列输出记录无效。")
        extra_targets = [item.target for item in extras]
        if (
            len(members) + len(extras) > 10000
            or len(set(extra_targets)) != len(extra_targets)
            or set(extra_targets) & (set(targets) | set(sources))
            or any(
                item.row >= rows or item.column >= columns or item.anchor_source not in sources
                for item in extras
            )
        ):
            raise ValueError("额外阵列输出身份、位置或锚点无效。")
        object.__setattr__(self, "row_spacing", dy)
        object.__setattr__(self, "column_spacing", dx)
        object.__setattr__(self, "angle_deg", angle)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "extra_outputs", extras)

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "array_id": self.array_id,
            "frame": self.frame.to_mapping(),
            "rows": self.rows,
            "columns": self.columns,
            "row_spacing": self.row_spacing,
            "column_spacing": self.column_spacing,
            "sources": [source.to_mapping() for source in self.sources],
            "members": [member.to_mapping() for member in self.members],
        }
        if self.angle_deg != 0:
            result["angle_deg"] = self.angle_deg
        if self.base_point is not None:
            result["base_point"] = self.base_point.to_mapping()
        if self.extra_outputs:
            result["extra_outputs"] = [output.to_mapping() for output in self.extra_outputs]
        return result

    @classmethod
    def from_mapping(cls, value: object) -> AssociativeRectArray:
        expected = frozenset(
            (
                "array_id",
                "frame",
                "rows",
                "columns",
                "row_spacing",
                "column_spacing",
                "sources",
                "members",
            )
        )
        if isinstance(value, Mapping) and "angle_deg" in value:
            expected |= {"angle_deg"}
        if isinstance(value, Mapping) and "base_point" in value:
            expected |= {"base_point"}
        if isinstance(value, Mapping) and "extra_outputs" in value:
            expected |= {"extra_outputs"}
        data = _mapping(cast("object", value), expected)
        sources, members = data["sources"], data["members"]
        if not isinstance(sources, list | tuple) or not isinstance(members, list | tuple):
            raise ValueError("关联阵列源和成员必须是数组。")
        extras = data.get("extra_outputs", ())
        if not isinstance(extras, list | tuple):
            raise ValueError("额外阵列输出必须是数组。")
        return cls(
            _identity(data["array_id"], "array_id"),
            WorkPlaneFrame.from_mapping(data["frame"]),
            _integer(data["rows"], "rows"),
            _integer(data["columns"], "columns"),
            _number(data["row_spacing"], "row_spacing"),
            _number(data["column_spacing"], "column_spacing"),
            tuple(
                ArrayEntityRef.from_mapping(item)
                for item in cast("tuple[object, ...] | list[object]", sources)
            ),
            tuple(
                ArrayMember.from_mapping(item)
                for item in cast("tuple[object, ...] | list[object]", members)
            ),
            _number(data.get("angle_deg", 0), "angle_deg"),
            ArrayBasePoint.from_mapping(data["base_point"]) if "base_point" in data else None,
            tuple(
                ArrayExtraOutput.from_mapping(item)
                for item in cast("tuple[object, ...] | list[object]", extras)
            ),
        )


def _spacing_grip_axis(array: AssociativeRectArray, axis: str) -> tuple[float, float, int]:
    if axis not in ("row", "column"):
        raise ValueError("阵列夹点方向无效。")
    count = array.rows if axis == "row" else array.columns
    if count <= 1:
        raise ValueError(
            "阵列行方向没有间距夹点。" if axis == "row" else "阵列列方向没有间距夹点。"
        )
    angle = math.radians(array.angle_deg % 360.0)
    cosine, sine = math.cos(angle), math.sin(angle)
    return (-sine, cosine, count - 1) if axis == "row" else (cosine, sine, count - 1)


def _grip_point(point: Point2D) -> Point2D:
    value = cast("object", point)
    if not isinstance(value, tuple) or len(cast("tuple[object, ...]", value)) != 2:
        raise ValueError("阵列夹点必须是二维坐标。")
    return (_number(point[0], "grip x"), _number(point[1], "grip y"))


def array_spacing_grip(array: AssociativeRectArray, anchor: Point2D, axis: str) -> Point2D:
    """Return the outer spacing grip in array-plane coordinates."""
    anchor = _grip_point(anchor)
    unit_x, unit_y, intervals = _spacing_grip_axis(array, axis)
    spacing = array.row_spacing if axis == "row" else array.column_spacing
    return (
        _number(anchor[0] + intervals * spacing * unit_x, "grip x"),
        _number(anchor[1] + intervals * spacing * unit_y, "grip y"),
    )


def array_spacing_from_grip(
    array: AssociativeRectArray, anchor: Point2D, axis: str, target: Point2D
) -> float:
    """Project a grip target onto its array axis and return signed spacing."""
    anchor, target = _grip_point(anchor), _grip_point(target)
    unit_x, unit_y, intervals = _spacing_grip_axis(array, axis)
    spacing = _number(
        ((target[0] - anchor[0]) * unit_x + (target[1] - anchor[1]) * unit_y) / intervals,
        "grip spacing",
    )
    if abs(spacing) <= 1e-9:
        raise ValueError("阵列活动方向的间距必须非零。")
    return spacing


def array_counts_from_grip(
    array: AssociativeRectArray, anchor: Point2D, target: Point2D
) -> tuple[int, int, float, float]:
    """Project a corner grip onto the grid and return counts and effective spacing."""
    anchor, target = _grip_point(anchor), _grip_point(target)
    angle = math.radians(array.angle_deg % 360.0)
    cosine, sine = math.cos(angle), math.sin(angle)
    dx, dy = target[0] - anchor[0], target[1] - anchor[1]
    row_step = array.row_spacing
    column_step = array.column_spacing
    if abs(row_step) <= 1e-9:
        row_step = abs(column_step)
    if abs(column_step) <= 1e-9:
        column_step = abs(row_step)
    row_position = _number((-dx * sine + dy * cosine) / row_step, "row count")
    column_position = _number((dx * cosine + dy * sine) / column_step, "column count")
    rows = max(1, math.floor(row_position + 0.5) + 1)
    columns = max(1, math.floor(column_position + 0.5) + 1)
    if not 2 <= rows * columns <= 1000:
        raise ValueError("阵列位置数必须为 2 到 1000。")
    if (rows * columns - 1) * len(array.sources) > 10000:
        raise ValueError("关联阵列成员超过 10000 个。")
    return (
        rows,
        columns,
        row_step if rows > 1 else array.row_spacing,
        column_step if columns > 1 else array.column_spacing,
    )


def validate_array_network(arrays: tuple[AssociativeRectArray, ...]) -> None:
    """Reject duplicate identities, multiple owners and dependency cycles."""
    ids = [array.array_id for array in arrays]
    if len(ids) != len(set(ids)):
        raise ValueError("关联阵列身份重复。")
    erased = {
        member.target
        for array in arrays
        for member in array.members
        if member.erased_index is not None
    }
    positions = [
        (member.target.sketch_id, member.erased_index)
        for array in arrays
        for member in array.members
        if member.erased_index is not None
    ]
    if len(positions) != len(set(positions)):
        raise ValueError("已擦除阵列副本的恢复位置重复。")
    if any(source in erased for array in arrays for source in array.sources):
        raise ValueError("已擦除的阵列副本不能作为下游阵列来源。")
    if any(
        member.replacement is not None and member.replacement.source in erased
        for array in arrays
        for member in array.members
    ):
        raise ValueError("已擦除的阵列副本不能作为替换来源。")
    if any(output.source in erased for array in arrays for output in array.extra_outputs):
        raise ValueError("已擦除的阵列副本不能作为额外输出来源。")
    targets: set[ArrayEntityRef] = set()
    graph: dict[ArrayEntityRef, set[ArrayEntityRef]] = {}
    for array in arrays:
        for member in array.members:
            if member.target in targets:
                raise ValueError("关联阵列目标重复。")
            targets.add(member.target)
            graph.setdefault(member.source, set()).add(member.target)
            if member.replacement is not None:
                graph.setdefault(member.replacement.source, set()).add(member.target)
                if member.replacement.anchor_source is not None:
                    graph.setdefault(member.replacement.anchor_source, set()).add(member.target)
        for output in array.extra_outputs:
            if output.target in targets:
                raise ValueError("关联阵列目标重复。")
            targets.add(output.target)
            graph.setdefault(output.source, set()).add(output.target)
            graph.setdefault(output.anchor_source, set()).add(output.target)
    incoming: dict[ArrayEntityRef, int] = {}
    for source, children in graph.items():
        incoming.setdefault(source, 0)
        for child in children:
            incoming[child] = incoming.get(child, 0) + 1
    pending = [node for node, count in incoming.items() if count == 0]
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        for child in graph.get(node, ()):
            incoming[child] -= 1
            if incoming[child] == 0:
                pending.append(child)
    if visited != len(incoming):
        raise ValueError("关联阵列依赖存在环。")


def _ordered_array_members(array: AssociativeRectArray) -> tuple[ArrayMember, ...]:
    """Order members so a replacement member is evaluated after its source."""
    by_target = {member.target: member for member in array.members}
    dependents: dict[ArrayEntityRef, list[ArrayEntityRef]] = {ref: [] for ref in by_target}
    incoming = dict.fromkeys(by_target, 0)
    for member in array.members:
        if member.replacement is not None and member.replacement.source in by_target:
            dependents[member.replacement.source].append(member.target)
            incoming[member.target] += 1
    pending = [member.target for member in array.members if incoming[member.target] == 0]
    result: list[ArrayMember] = []
    while pending:
        target = pending.pop()
        result.append(by_target[target])
        for dependent in dependents[target]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                pending.append(dependent)
    if len(result) != len(array.members):
        raise ValueError("关联阵列依赖存在环。")
    return tuple(result)


def _generated_members(array: AssociativeRectArray) -> tuple[ArrayMember, ...]:
    return (
        *array.members,
        *(
            ArrayMember(
                output.anchor_source,
                output.target,
                output.row,
                output.column,
                offset_mm=output.offset_mm,
                rotation_deg=output.rotation_deg,
                rotation_center_offset_mm=output.rotation_center_offset_mm,
                replacement=ArrayReplacement(
                    output.source, output.base_offset_mm, output.anchor_source
                ),
            )
            for output in array.extra_outputs
        ),
    )


def _ordered_network_members(
    arrays: tuple[AssociativeRectArray, ...],
) -> tuple[tuple[AssociativeRectArray, ArrayMember], ...]:
    """Order all generated entities by their actual source dependencies."""
    by_target = {
        member.target: (array, member) for array in arrays for member in _generated_members(array)
    }
    dependents: dict[ArrayEntityRef, list[ArrayEntityRef]] = {target: [] for target in by_target}
    incoming = dict.fromkeys(by_target, 0)
    for target, (_array, member) in by_target.items():
        sources = {member.source}
        if member.replacement is not None:
            sources.add(member.replacement.source)
            if member.replacement.anchor_source is not None:
                sources.add(member.replacement.anchor_source)
        for source in sources & by_target.keys():
            dependents[source].append(target)
            incoming[target] += 1
    pending = [target for target in by_target if incoming[target] == 0]
    result: list[tuple[AssociativeRectArray, ArrayMember]] = []
    while pending:
        target = pending.pop()
        result.append(by_target[target])
        for dependent in dependents[target]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                pending.append(dependent)
    if len(result) != len(by_target):
        raise ValueError("关联阵列依赖存在环。")
    return tuple(result)


def has_shared_replacement_anchor(array: AssociativeRectArray) -> bool:
    """Whether any member uses a versioned shared replacement anchor."""
    return any(
        member.replacement is not None and member.replacement.anchor_source is not None
        for member in array.members
    )


def has_internal_replacements(array: AssociativeRectArray) -> bool:
    """Return whether any replacement source is a member of this array."""
    targets = {member.target for member in _generated_members(array)}
    return any(
        member.replacement is not None and member.replacement.source in targets
        for member in _generated_members(array)
    )


def has_interleaved_array_dependencies(arrays: tuple[AssociativeRectArray, ...]) -> bool:
    """Return whether array-level dependencies form a cycle, ignoring self edges."""
    owner = {
        member.target: array.array_id for array in arrays for member in _generated_members(array)
    }
    dependencies = {
        array.array_id: {
            owner[source]
            for source in (
                *array.sources,
                *(
                    member.replacement.source
                    for member in _generated_members(array)
                    if member.replacement is not None
                ),
            )
            if source in owner and owner[source] != array.array_id
        }
        for array in arrays
    }
    dependents: dict[str, set[str]] = {identity: set() for identity in dependencies}
    for identity, sources in dependencies.items():
        for source in sources:
            dependents[source].add(identity)
    pending = [identity for identity, sources in dependencies.items() if not sources]
    completed = 0
    while pending:
        identity = pending.pop()
        completed += 1
        for dependent in dependents[identity]:
            dependencies[dependent].remove(identity)
            if not dependencies[dependent]:
                pending.append(dependent)
    return completed != len(dependencies)


def _sketch_index(sketches: tuple[Sketch, ...]) -> dict[str, Sketch]:
    result = {sketch.sketch_id: sketch for sketch in sketches}
    if len(result) != len(sketches):
        raise ValueError("草图身份重复，无法处理关联阵列。")
    return result


def _entity_index(sketches: tuple[Sketch, ...]) -> dict[ArrayEntityRef, SketchEntity]:
    return {
        ArrayEntityRef(sketch.sketch_id, entity.entity_id): entity
        for sketch in sketches
        for entity in sketch.entities
    }


def _resolve_entity(
    sketches: Mapping[str, Sketch],
    entities: Mapping[ArrayEntityRef, SketchEntity],
    ref: ArrayEntityRef,
) -> tuple[Sketch, SketchEntity]:
    sketch = sketches.get(ref.sketch_id)
    if sketch is None:
        raise ValueError("关联阵列引用的草图不存在。")
    entity = entities.get(ref)
    if entity is None:
        raise ValueError("关联阵列引用的图元不存在或不唯一。")
    return sketch, entity


def _same_array_plane(frame: WorkPlaneFrame, reference: WorkPlaneFrame) -> bool:
    if any(abs(a - b) > 1e-9 for a, b in zip(frame.u_axis, reference.u_axis, strict=True)):
        return False
    if any(abs(a - b) > 1e-9 for a, b in zip(frame.v_axis, reference.v_axis, strict=True)):
        return False
    displacement = tuple(a - b for a, b in zip(frame.origin_mm, reference.origin_mm, strict=True))
    return abs(sum(a * b for a, b in zip(displacement, reference.normal, strict=True))) <= 1e-7


def resolve_array_base_point(
    array: AssociativeRectArray, sketches: tuple[Sketch, ...]
) -> Point2D | None:
    """Resolve the explicit base in array coordinates; None denotes the legacy default."""
    base = array.base_point
    if base is None:
        return None
    if base.point_mm is not None:
        return base.point_mm
    assert base.source is not None and base.reference is not None
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    try:
        sketch, entity = _resolve_entity(indexed, entities, base.source)
    except ValueError as exc:
        raise ValueError("阵列基点的源图元不存在。") from exc
    if not _same_array_plane(sketch.frame, array.frame):
        raise ValueError("阵列基点的源不在阵列工作平面。")
    point = resolve_point_reference(base.reference, {entity.entity_id: entity})
    if point is None:
        raise ValueError("阵列基点关键点已失效。")
    return array.frame.world_to_local(sketch.frame.local_to_world(point))


def _validate_base_source_change(
    array: AssociativeRectArray,
    before: Mapping[ArrayEntityRef, SketchEntity],
    after: Mapping[ArrayEntityRef, SketchEntity],
) -> None:
    base = array.base_point
    if base is None or base.source is None or base.reference is None:
        return
    old, new = before.get(base.source), after.get(base.source)
    if old is None or new is None or type(old) is not type(new):
        raise ValueError("阵列基点的源图元类型已变化。")
    if base.reference.kind == "vertex" and (
        isinstance(old, PolylineEntity)
        and isinstance(new, PolylineEntity)
        and (len(old.points_mm) != len(new.points_mm) or old.closed != new.closed)
        or isinstance(old, SplineEntity)
        and isinstance(new, SplineEntity)
        and len(old.control_points_mm) != len(new.control_points_mm)
    ):
        raise ValueError("阵列基点的源顶点拓扑已变化。")
    if (
        base.reference.kind == "vertex"
        and base.reference.index is not None
        and isinstance(old, PolylineEntity)
        and isinstance(new, PolylineEntity)
    ):
        rotated = closed_polyline_vertex_rotation_index(old, new, base.reference.index)
        if rotated is not None and rotated != base.reference.index:
            raise ValueError("阵列基点的源顶点顺序已变化。")
    if base.reference.kind == "vertex" and base.reference.index is not None:
        old_points: tuple[Point2D, ...] | None = None
        new_points: tuple[Point2D, ...] | None = None
        if isinstance(old, PolylineEntity) and isinstance(new, PolylineEntity):
            old_points, new_points = old.points_mm, new.points_mm
        elif isinstance(old, SplineEntity) and isinstance(new, SplineEntity):
            old_points, new_points = old.control_points_mm, new.control_points_mm
        index = base.reference.index
        uniformly_translated = False
        if old_points is not None and new_points is not None and len(old_points) == len(new_points):
            dx = new_points[0][0] - old_points[0][0]
            dy = new_points[0][1] - old_points[0][1]
            uniformly_translated = all(
                math.isclose(after[0] - before[0], dx, rel_tol=1e-12, abs_tol=1e-9)
                and math.isclose(after[1] - before[1], dy, rel_tol=1e-12, abs_tol=1e-9)
                for before, after in zip(old_points, new_points, strict=True)
            )
        if (
            old_points is not None
            and new_points is not None
            and not uniformly_translated
            and index < len(old_points)
            and index < len(new_points)
            and old_points[index] != new_points[index]
            and old_points[index] in new_points
        ):
            raise ValueError("阵列基点的源顶点顺序不明确。")


def _expected_array_member(
    array: AssociativeRectArray,
    member: ArrayMember,
    sketches: Mapping[str, Sketch],
    entities: Mapping[ArrayEntityRef, SketchEntity],
) -> SketchEntity:
    source_sketch, source = _resolve_entity(sketches, entities, member.source)
    target_sketch = sketches.get(member.target.sketch_id)
    if target_sketch is None:
        raise ValueError("关联阵列目标草图不存在。")
    if not _same_array_plane(source_sketch.frame, array.frame) or not _same_array_plane(
        target_sketch.frame, array.frame
    ):
        raise ValueError("关联阵列要求工作平面共面且轴向一致。")
    source_origin = array.frame.world_to_local(source_sketch.frame.origin_mm)
    target_origin = array.frame.world_to_local(target_sketch.frame.origin_mm)
    shift = rectangular_array_displacement(
        member.row, member.column, array.row_spacing, array.column_spacing, array.angle_deg
    )
    delta = (
        source_origin[0] - target_origin[0] + shift[0] + member.offset_mm[0],
        source_origin[1] - target_origin[1] + shift[1] + member.offset_mm[1],
    )
    anchor = _entity_anchor(source)
    if member.replacement is not None and member.replacement.anchor_source is not None:
        anchor_sketch, anchor_entity = _resolve_entity(
            sketches, entities, member.replacement.anchor_source
        )
        anchor = source_sketch.frame.world_to_local(
            anchor_sketch.frame.local_to_world(_entity_anchor(anchor_entity))
        )
    if member.replacement is not None:
        replacement_sketch, replacement = _resolve_entity(
            sketches, entities, member.replacement.source
        )
        if not _same_array_plane(replacement_sketch.frame, array.frame):
            raise ValueError("阵列替换来源不在阵列工作平面。")
        base = _entity_anchor(replacement)
        shift_to_anchor = (
            anchor[0] - base[0] - member.replacement.base_offset_mm[0],
            anchor[1] - base[1] - member.replacement.base_offset_mm[1],
        )
        source = move_entities((replacement,), (replacement.entity_id,), shift_to_anchor)[0]
    if member.rotation_deg:
        center = (
            anchor[0] + member.rotation_center_offset_mm[0],
            anchor[1] + member.rotation_center_offset_mm[1],
        )
        source = rotate_entities((source,), (source.entity_id,), center, member.rotation_deg)[0]
    transformed = move_entities((source,), (source.entity_id,), delta)[0]
    if isinstance(transformed, PolylineEntity | SplineEntity):
        existing = entities.get(member.target)
        if isinstance(existing, type(transformed)):
            return replace(
                transformed, entity_id=member.target.entity_id, point_ids=existing.point_ids
            )
        if existing is not None and (
            transformed.point_ids
            or (isinstance(existing, PolylineEntity | SplineEntity) and existing.point_ids)
        ):
            raise ValueError("阵列成员曲线类型改变，点身份无法保留。")
        from mycad.core.geometric_tolerance_topology import new_curve_point_identities

        kind = "polyline" if isinstance(transformed, PolylineEntity) else "spline"
        point_ids = (
            new_curve_point_identities(member.target.entity_id, kind, len(transformed.point_ids))
            if transformed.point_ids
            else ()
        )
        return replace(transformed, entity_id=member.target.entity_id, point_ids=point_ids)
    existing = entities.get(member.target)
    if isinstance(existing, PolylineEntity | SplineEntity) and existing.point_ids:
        raise ValueError("阵列成员曲线类型改变，点身份无法保留。")
    return replace(transformed, entity_id=member.target.entity_id)


def _equivalent_value(first: object, second: object) -> bool:
    if isinstance(first, bool) or isinstance(second, bool):
        return type(first) is type(second) and first == second
    if isinstance(first, int | float) and isinstance(second, int | float):
        return math.isclose(first, second, rel_tol=1e-10, abs_tol=1e-7)
    if isinstance(first, tuple) and isinstance(second, tuple):
        left = cast("tuple[object, ...]", first)
        right = cast("tuple[object, ...]", second)
        return len(left) == len(right) and all(
            _equivalent_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return first == second


def _equivalent_entity(first: SketchEntity, second: SketchEntity) -> bool:
    if type(first) is not type(second):
        return False
    return all(
        _equivalent_value(getattr(first, field.name), getattr(second, field.name))
        for field in fields(first)
    )


def _entity_anchor(entity: SketchEntity) -> Point2D:
    if isinstance(entity, PointEntity):
        return entity.position_mm
    if isinstance(entity, LineEntity):
        return entity.start_mm
    if isinstance(entity, ArcEntity | CircleEntity | EllipseEntity):
        return entity.center_mm
    if isinstance(entity, RectangleEntity):
        return entity.first_corner_mm
    if isinstance(entity, PolylineEntity):
        return entity.points_mm[0]
    return entity.control_points_mm[0]


def array_member_rotation_anchor(
    array: AssociativeRectArray,
    member: ArrayMember | ArrayExtraOutput,
    sketches: tuple[Sketch, ...],
) -> Point2D:
    """Return the unrotated source anchor at the member's target in local coordinates."""
    if isinstance(member, ArrayExtraOutput):
        if member not in array.extra_outputs:
            raise ValueError("阵列额外输出不存在。")
        member = next(item for item in _generated_members(array) if item.target == member.target)
    if member not in _generated_members(array):
        raise ValueError("阵列成员不存在。")
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    source_sketch, source = _resolve_entity(indexed, entities, member.source)
    target_sketch, _ = _resolve_entity(indexed, entities, member.target)
    if not _same_array_plane(source_sketch.frame, array.frame) or not _same_array_plane(
        target_sketch.frame, array.frame
    ):
        raise ValueError("关联阵列要求工作平面共面且轴向一致。")
    origin = target_sketch.frame.world_to_local(
        source_sketch.frame.local_to_world(_entity_anchor(source))
    )
    shift = rectangular_array_displacement(
        member.row, member.column, array.row_spacing, array.column_spacing, array.angle_deg
    )
    return (origin[0] + shift[0] + member.offset_mm[0], origin[1] + shift[1] + member.offset_mm[1])


def _translation_between(first: SketchEntity, second: SketchEntity) -> Point2D | None:

    if type(first) is not type(second):
        return None
    start, end = _entity_anchor(first), _entity_anchor(second)
    delta = (end[0] - start[0], end[1] - start[1])
    translated = move_entities((first,), (first.entity_id,), delta)[0]
    return delta if _equivalent_entity(translated, second) else None


def _translate_offset_constraints(
    original: tuple[Sketch, ...], result: tuple[Sketch, ...]
) -> tuple[Sketch, ...]:
    before = _sketch_index(original)
    revised: list[Sketch] = []
    for sketch in result:
        old = before[sketch.sketch_id]
        old_entities = {entity.entity_id: entity for entity in old.entities}
        changes = {
            entity.entity_id: _translation_between(old_entities[entity.entity_id], entity)
            for entity in sketch.entities
            if old_entities[entity.entity_id] != entity
        }
        constraints: list[SketchConstraint] = []
        for constraint in sketch.constraints:
            referenced = {ref.entity_id for ref in constraint.references}
            affected = referenced & changes.keys()
            if not affected:
                constraints.append(constraint)
                continue
            deltas = [changes[entity_id] for entity_id in affected]
            if any(delta is None for delta in deltas) or constraint.kind == "fixed":
                raise ValueError("阵列成员偏移会改变已有约束；请先处理约束。")
            delta = deltas[0]
            assert delta is not None
            together = affected == referenced and all(
                item is not None
                and math.isclose(item[0], delta[0], rel_tol=1e-12, abs_tol=1e-9)
                and math.isclose(item[1], delta[1], rel_tol=1e-12, abs_tol=1e-9)
                for item in deltas
            )
            if not together and constraint.kind not in {
                "parallel",
                "perpendicular",
                "equal",
                "angle",
            }:
                raise ValueError("阵列成员偏移会改变已有约束；请先处理约束。")
            if together and (
                constraint.position_mm is not None or constraint.text_position_mm is not None
            ):
                first = old_entities[constraint.references[0].entity_id]
                layer = old.layers.get(constraint.layer_name or first.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("关联尺寸图层已锁定或隐藏。")

                def translate(point: Point2D | None, shift: Point2D = delta) -> Point2D | None:
                    return None if point is None else (point[0] + shift[0], point[1] + shift[1])

                constraint = replace(
                    constraint,
                    position_mm=translate(constraint.position_mm),
                    text_position_mm=translate(constraint.text_position_mm),
                )
            constraints.append(constraint)
        revised.append(replace(sketch, constraints=tuple(constraints)))
    return tuple(revised)


def predict_chain_reorder(
    original: tuple[Sketch, ...],
    proposed: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    edges: tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...],
    input_maps: Mapping[tuple[str, str], PolylineTopologyMap],
    *,
    allow_unchanged_replacements: bool = False,
    allow_reordered_replacements: bool = False,
    allow_extra_outputs: bool = False,
) -> tuple[tuple[Sketch, ...], dict[tuple[str, str], PolylineTopologyMap]]:
    """Predict a simple chain on isolated snapshots, checking every topology edge."""
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    validate_array_network(arrays)
    before = _entity_index(original)
    sketches = _sketch_index(proposed)
    current = _entity_index(proposed)
    maps = dict(input_maps)
    for key, mapping in maps.items():
        ref = ArrayEntityRef(*key)
        old, new = before.get(ref), current.get(ref)
        if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
            raise ValueError("链式拓扑映射来源不是同一多段线。")
        mapping.validate_exact_reorder(old, new)
    owners = {
        member.target: (array, member)
        for array in arrays
        for member in (_generated_members(array) if allow_extra_outputs else array.members)
        if member.erased_index is None
    }
    seen_targets: set[ArrayEntityRef] = set()
    unchanged_sources: set[ArrayEntityRef] = set()
    for source, target in edges:
        if target in seen_targets:
            raise ValueError("链式拓扑映射目标重复。")
        seen_targets.add(target)
        source_map = maps.get((source.sketch_id, source.entity_id))
        owner = owners.get(target)
        old = before.get(target)
        replacement_source = (
            allow_reordered_replacements
            and owner is not None
            and owner[1].replacement is not None
            and owner[1].replacement.source == source
        )
        if (
            (source_map is None and source not in unchanged_sources)
            or owner is None
            or (owner[1].source != source and not replacement_source)
            or old is None
        ):
            raise ValueError("链式拓扑映射或传播顺序无效。")
        array, member = owner
        candidate = _expected_array_member(array, member, sketches, current)
        if (
            member.replacement is not None and not replacement_source
        ) or source in unchanged_sources:
            if not allow_unchanged_replacements or not _equivalent_entity(old, candidate):
                raise ValueError("链式替换成员及其下游几何必须保持不变。")
            current[target] = old
            unchanged_sources.add(target)
            continue
        if not isinstance(old, PolylineEntity) or source_map is None:
            raise ValueError("链式非多段线成员需要单独验证。")
        if not isinstance(candidate, PolylineEntity):
            raise ValueError("链式成员类型发生变化。")
        target_map = PolylineTopologyMap(
            target.entity_id, source_map.old_to_new, len(candidate.points_mm), candidate.closed
        )
        if old.point_ids:
            if candidate.point_ids != old.point_ids:
                raise ValueError("链式成员点身份在传播中意外改变。")
            ordered: list[str | None] = [None] * len(old.point_ids)
            for old_index, new_index in enumerate(target_map.old_to_new):
                if new_index is None or new_index >= len(ordered):
                    raise ValueError("链式拓扑映射缺少点身份。")
                ordered[new_index] = old.point_ids[old_index]
            if any(item is None for item in ordered):
                raise ValueError("链式拓扑映射缺少点身份。")
            candidate = replace(candidate, point_ids=tuple(cast("list[str]", ordered)))
        target_map.validate_exact_reorder(old, candidate)
        current[target] = candidate
        maps[(target.sketch_id, target.entity_id)] = target_map
    result = tuple(
        replace(
            sketch,
            entities=tuple(
                current[ArrayEntityRef(sketch.sketch_id, item.entity_id)]
                for item in sketch.entities
            ),
        )
        for sketch in proposed
    )
    return result, maps


def propagate_array_changes(
    original: tuple[Sketch, ...],
    proposed: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    *,
    constrained_translation: Point2D | None = None,
    allow_constrained_translation: bool = False,
    allow_rotation_override: bool = False,
    allow_replacement_override: bool = False,
    allow_grid_update: bool = False,
    allow_extra_offsets: bool = False,
    allow_extra_position_overrides: bool = False,
    allow_extra_rotation_overrides: bool = False,
    resulting_arrays: tuple[AssociativeRectArray, ...] | None = None,
    base_rebind_maps: Mapping[tuple[str, str], PolylineTopologyMap] | None = None,
    base_rebind_proofs: tuple[Sketch, ...] | None = None,
) -> tuple[Sketch, ...]:
    """Regenerate linked members on isolated sketches, or reject the complete proposal."""
    validate_array_network(arrays)
    before, requested = _sketch_index(original), _sketch_index(proposed)
    proof_sketches = (
        _sketch_index(base_rebind_proofs) if base_rebind_proofs is not None else requested
    )
    before_entities, requested_entities = _entity_index(original), _entity_index(proposed)
    proof_entities = (
        _entity_index(base_rebind_proofs) if base_rebind_proofs is not None else requested_entities
    )
    current_entities = dict(requested_entities)
    occupied_ids = {ref.entity_id for ref in (*before_entities, *requested_entities)}
    constraint_refs = {
        ArrayEntityRef(sketch.sketch_id, ref.entity_id)
        for sketch in (*original, *proposed)
        for constraint in sketch.constraints
        for ref in constraint.references
    }
    rebound_bases: dict[str, AssociativeRectArray] = {}
    if base_rebind_maps is not None:
        from mycad.core.geometric_tolerance_topology import rebind_array_base

        if resulting_arrays is None or len(resulting_arrays) != len(arrays):
            raise ValueError("阵列基点重绑定缺少完整阵列状态。")
        for old, new in zip(arrays, resulting_arrays, strict=True):
            if old.base_point == new.base_point:
                continue
            base = old.base_point
            if base is None or base.source is None:
                raise ValueError("阵列基点重绑定缺少来源。")
            key = (base.source.sketch_id, base.source.entity_id)
            mapping = base_rebind_maps.get(key)
            if (
                mapping is None
                or base.source.sketch_id not in before
                or base.source.sketch_id not in proof_sketches
            ):
                raise ValueError("阵列基点重绑定缺少拓扑证明。")
            expected = rebind_array_base(
                old, before[base.source.sketch_id], proof_sketches[base.source.sketch_id], mapping
            )
            if expected != new:
                raise ValueError("阵列基点重绑定包含其他修改。")
            rebound_bases[old.array_id] = new
    for array in arrays:
        if array.base_point is not None:
            resolve_array_base_point(array, original)
            if array.array_id in rebound_bases:
                resolve_array_base_point(
                    rebound_bases[array.array_id],
                    base_rebind_proofs if base_rebind_proofs is not None else proposed,
                )
            else:
                resolve_array_base_point(array, proposed)
                _validate_base_source_change(array, before_entities, requested_entities)
        for member in _generated_members(array):
            if member.erased_index is not None:
                old_sketch = before.get(member.target.sketch_id)
                proposed_sketch = requested.get(member.target.sketch_id)
                if (
                    old_sketch is None
                    or proposed_sketch is None
                    or old_sketch.frame != proposed_sketch.frame
                ):
                    raise ValueError("关联阵列目标工作平面已变化。")
                if member.target.entity_id in occupied_ids:
                    raise ValueError("已擦除阵列副本的身份被占用。")
                if member.target in constraint_refs:
                    raise ValueError("已擦除阵列副本不能被约束引用。")
                _resolve_entity(before, before_entities, member.source)
                _resolve_entity(requested, requested_entities, member.source)
                if member.replacement is not None:
                    _resolve_entity(before, before_entities, member.replacement.source)
                    _resolve_entity(requested, requested_entities, member.replacement.source)
                continue
            old_sketch, old_target = _resolve_entity(before, before_entities, member.target)
            proposed_sketch, proposed_target = _resolve_entity(
                requested, requested_entities, member.target
            )
            expected = _expected_array_member(array, member, before, before_entities)
            if not _equivalent_entity(old_target, expected):
                raise ValueError("关联阵列原始快照不一致；请先修复或解除关联。")
            if not _equivalent_entity(old_target, proposed_target):
                raise ValueError("关联阵列副本不能直接修改；请先解除关联。")
            if proposed_sketch.frame != old_sketch.frame:
                raise ValueError("关联阵列目标工作平面已变化。")
            _resolve_entity(requested, requested_entities, member.source)
    if resulting_arrays is not None:
        if len(resulting_arrays) != len(arrays):
            raise ValueError("关联阵列覆盖数量不一致。")
        for old, new in zip(arrays, resulting_arrays, strict=True):
            if (
                allow_extra_offsets
                or allow_extra_position_overrides
                or allow_extra_rotation_overrides
            ) and (
                len(old.extra_outputs) != len(new.extra_outputs)
                or any(
                    replace(
                        after,
                        base_offset_mm=before.base_offset_mm
                        if allow_extra_offsets
                        else after.base_offset_mm,
                        offset_mm=before.offset_mm
                        if allow_extra_position_overrides
                        else after.offset_mm,
                        rotation_deg=before.rotation_deg
                        if allow_extra_rotation_overrides
                        else after.rotation_deg,
                        rotation_center_offset_mm=before.rotation_center_offset_mm
                        if allow_extra_rotation_overrides
                        else after.rotation_center_offset_mm,
                    )
                    != before
                    for before, after in zip(old.extra_outputs, new.extra_outputs, strict=True)
                )
            ):
                raise ValueError("额外输出覆盖包含不允许的修改。")
            normalized = (
                replace(new, extra_outputs=old.extra_outputs)
                if allow_extra_offsets
                or allow_extra_position_overrides
                or allow_extra_rotation_overrides
                else new
            )
            if old.array_id in rebound_bases:
                normalized = replace(normalized, base_point=old.base_point)
            if (
                len(old.members) != len(new.members)
                or (
                    replace(
                        normalized,
                        members=old.members,
                        row_spacing=old.row_spacing,
                        column_spacing=old.column_spacing,
                        angle_deg=old.angle_deg,
                        base_point=old.base_point,
                    )
                    != old
                    if allow_grid_update
                    else replace(normalized, members=old.members) != old
                )
                or (allow_grid_update and new.members != old.members)
                or any(
                    replace(
                        after,
                        offset_mm=before_member.offset_mm,
                        rotation_deg=before_member.rotation_deg
                        if allow_rotation_override
                        else after.rotation_deg,
                        rotation_center_offset_mm=before_member.rotation_center_offset_mm
                        if allow_rotation_override
                        else after.rotation_center_offset_mm,
                        replacement=before_member.replacement
                        if allow_replacement_override
                        else after.replacement,
                    )
                    != before_member
                    for before_member, after in zip(old.members, new.members, strict=True)
                )
            ):
                raise ValueError("关联阵列覆盖只能修改成员偏移。")
        arrays = resulting_arrays
        validate_array_network(arrays)
    constrained = {
        sketch.sketch_id: {
            ref.entity_id for constraint in sketch.constraints for ref in constraint.references
        }
        for sketch in proposed
    }
    changed_sketches: set[str] = set()
    for array, member in _ordered_network_members(arrays):
        if member.erased_index is not None:
            continue
        target_sketch, old_target = _resolve_entity(requested, current_entities, member.target)
        expected = _expected_array_member(array, member, requested, current_entities)
        if _equivalent_entity(old_target, expected):
            continue
        source_sketch, source = _resolve_entity(requested, current_entities, member.source)
        source_layer = source_sketch.layers.get(source.layer_name)
        if member.replacement is not None:
            replacement_sketch, replacement = _resolve_entity(
                requested, current_entities, member.replacement.source
            )
            replacement_layer = replacement_sketch.layers.get(replacement.layer_name)
            if replacement_layer.locked or not replacement_layer.displayed:
                raise ValueError("关联阵列替换来源图层已锁定或隐藏。")
            if member.replacement.anchor_source is not None:
                anchor_sketch, anchor_entity = _resolve_entity(
                    requested, current_entities, member.replacement.anchor_source
                )
                anchor_layer = anchor_sketch.layers.get(anchor_entity.layer_name)
                if anchor_layer.locked or not anchor_layer.displayed:
                    raise ValueError("关联阵列共同锚点图层已锁定或隐藏。")
        target_layer = target_sketch.layers.get(old_target.layer_name)
        try:
            destination_layer = target_sketch.layers.get(expected.layer_name)
        except KeyError as exc:
            raise ValueError("关联阵列目标草图缺少源图层。") from exc
        if (
            source_layer.locked
            or target_layer.locked
            or destination_layer.locked
            or not source_layer.displayed
            or not target_layer.displayed
            or not destination_layer.displayed
        ):
            raise ValueError("关联阵列源或副本图层已锁定或隐藏。")
        if old_target.entity_id in constrained[target_sketch.sketch_id]:
            translated = (
                move_entities((old_target,), (old_target.entity_id,), constrained_translation)[0]
                if constrained_translation is not None
                else None
            )
            if not (
                translated is not None
                and _equivalent_entity(translated, expected)
                or allow_constrained_translation
                and _translation_between(old_target, expected) is not None
            ):
                raise ValueError("关联阵列副本有关联约束；请先处理约束。")
        current_entities[member.target] = expected
        changed_sketches.add(target_sketch.sketch_id)
    for array in arrays:
        base = array.base_point
        if base is not None and base.source is not None and base.reference is not None:
            if array.array_id in rebound_bases:
                proof = proof_entities.get(base.source)
                actual = current_entities.get(base.source)
                if (
                    base_rebind_proofs is not None
                    and isinstance(proof, PolylineEntity)
                    and isinstance(actual, PolylineEntity)
                ):
                    proof = replace(proof, point_ids=actual.point_ids)
                if proof != actual:
                    raise ValueError("阵列基点来源在传播时发生额外变化。")
            else:
                _validate_base_source_change(array, before_entities, current_entities)
            source = current_entities.get(base.source)
            if (
                source is None
                or resolve_point_reference(base.reference, {source.entity_id: source}) is None
            ):
                raise ValueError("阵列基点关键点已失效。")
    return tuple(
        replace(
            sketch,
            entities=tuple(
                current_entities[ArrayEntityRef(sketch.sketch_id, entity.entity_id)]
                for entity in sketch.entities
            ),
        )
        if sketch.sketch_id in changed_sketches
        else sketch
        for sketch in proposed
    )


def validate_array_cross_changes(
    original: Mapping[str, Sketch],
    updated: Mapping[str, Sketch],
    arrays: tuple[AssociativeRectArray, ...],
    relations: tuple[CrossSketchTangency, ...],
    *,
    proven_reorder_targets: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    """Reject moving an array member referenced by a cross-sketch tangency."""
    targets = {
        (member.target.sketch_id, member.target.entity_id)
        for array in arrays
        for member in _generated_members(array)
    }
    for relation in relations:
        for ref in (relation.first, relation.second):
            if (ref.sketch_id, ref.entity_id) not in targets:
                continue
            old_sketch, new_sketch = original[ref.sketch_id], updated[ref.sketch_id]
            old = next(
                entity for entity in old_sketch.entities if entity.entity_id == ref.entity_id
            )
            new = next(
                (entity for entity in new_sketch.entities if entity.entity_id == ref.entity_id),
                None,
            )
            if old != new and (ref.sketch_id, ref.entity_id) not in proven_reorder_targets:
                raise ValueError("关联阵列副本具有跨草图相切关系；请先移除该关系。")


def set_array_offsets_batch(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    groups: Mapping[str, Mapping[ArrayEntityRef, Point2D]],
) -> tuple[tuple[Sketch, ...], tuple[AssociativeRectArray, ...]]:
    """Apply offsets across arrays on one isolated network snapshot."""
    propagate_array_changes(sketches, sketches, arrays)
    indexed = {array.array_id: array for array in arrays}
    if not groups or not set(groups).issubset(indexed):
        raise ValueError("批量偏移包含无效阵列。")
    updated: list[AssociativeRectArray] = []
    for array in arrays:
        offsets = groups.get(array.array_id)
        if offsets is None:
            updated.append(array)
            continue
        targets = {member.target for member in array.members} | {
            output.target for output in array.extra_outputs
        }
        if not offsets or not set(offsets).issubset(targets):
            raise ValueError("批量偏移包含无效阵列成员。")
        updated.append(
            replace(
                array,
                members=tuple(
                    replace(member, offset_mm=offsets.get(member.target, member.offset_mm))
                    for member in array.members
                ),
                extra_outputs=tuple(
                    replace(output, offset_mm=offsets.get(output.target, output.offset_mm))
                    for output in array.extra_outputs
                ),
            )
        )
    revised = tuple(updated)
    if revised == arrays:
        raise ValueError("阵列成员偏移未变化。")
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        resulting_arrays=revised,
        allow_constrained_translation=True,
        allow_extra_position_overrides=True,
    )
    result = _translate_offset_constraints(sketches, result)
    propagate_array_changes(result, result, revised)
    return result, revised


def set_array_rotations_batch(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    groups: Mapping[str, Mapping[ArrayEntityRef, tuple[float, Point2D]]],
) -> tuple[tuple[Sketch, ...], tuple[AssociativeRectArray, ...]]:
    """Apply rotations across arrays on one isolated network snapshot."""
    propagate_array_changes(sketches, sketches, arrays)
    indexed = {array.array_id: array for array in arrays}
    if not groups or not set(groups).issubset(indexed):
        raise ValueError("批量旋转包含无效阵列。")
    updated: list[AssociativeRectArray] = []
    for array in arrays:
        rotations = groups.get(array.array_id)
        if rotations is None:
            updated.append(array)
            continue
        targets = {member.target for member in array.members} | {
            output.target for output in array.extra_outputs
        }
        if not rotations or not set(rotations).issubset(targets):
            raise ValueError("批量旋转包含无效阵列成员。")
        updated.append(
            replace(
                array,
                members=tuple(
                    replace(
                        member,
                        rotation_deg=rotations[member.target][0],
                        rotation_center_offset_mm=rotations[member.target][1],
                    )
                    if member.target in rotations
                    else member
                    for member in array.members
                ),
                extra_outputs=tuple(
                    replace(
                        output,
                        rotation_deg=rotations[output.target][0],
                        rotation_center_offset_mm=rotations[output.target][1],
                    )
                    if output.target in rotations
                    else output
                    for output in array.extra_outputs
                ),
            )
        )
    revised = tuple(updated)
    if revised == arrays:
        raise ValueError("阵列成员旋转未变化。")
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        resulting_arrays=revised,
        allow_constrained_translation=True,
        allow_rotation_override=True,
        allow_extra_rotation_overrides=True,
    )
    result = _translate_offset_constraints(sketches, result)
    propagate_array_changes(result, result, revised)
    return result, revised


def set_array_member_offsets(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    offsets: Mapping[ArrayEntityRef, Point2D],
    *,
    reset_all: bool = False,
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Set individual member offsets or reset all offsets with dependent regeneration."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    if reset_all and offsets:
        raise ValueError("不能同时重置全部和指定成员偏移。")
    targets = {member.target for member in array.members} | {
        output.target for output in array.extra_outputs
    }
    if not reset_all and (not offsets or not set(offsets).issubset(targets)):
        raise ValueError("偏移必须指定该阵列的有效成员。")
    updated = replace(
        array,
        members=tuple(
            replace(
                member,
                offset_mm=(0.0, 0.0) if reset_all else offsets.get(member.target, member.offset_mm),
            )
            for member in array.members
        ),
        extra_outputs=tuple(
            replace(
                output,
                offset_mm=(0.0, 0.0) if reset_all else offsets.get(output.target, output.offset_mm),
            )
            for output in array.extra_outputs
        ),
    )
    if updated == array:
        raise ValueError("阵列成员偏移未变化。")
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        resulting_arrays=updated_arrays,
        allow_constrained_translation=True,
        allow_extra_position_overrides=True,
    )
    result = _translate_offset_constraints(sketches, result)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def set_array_member_rotations(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    rotations: Mapping[ArrayEntityRef, tuple[float, Point2D]],
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Set member rotation relative to each source anchor, regenerating dependents."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    targets = {member.target for member in array.members} | {
        output.target for output in array.extra_outputs
    }
    if not rotations or not set(rotations).issubset(targets):
        raise ValueError("旋转必须指定该阵列的有效成员。")
    updated = replace(
        array,
        members=tuple(
            replace(
                member,
                rotation_deg=rotations[member.target][0],
                rotation_center_offset_mm=rotations[member.target][1],
            )
            if member.target in rotations
            else member
            for member in array.members
        ),
        extra_outputs=tuple(
            replace(
                output,
                rotation_deg=rotations[output.target][0],
                rotation_center_offset_mm=rotations[output.target][1],
            )
            if output.target in rotations
            else output
            for output in array.extra_outputs
        ),
    )
    if updated == array:
        raise ValueError("阵列成员旋转未变化。")
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        allow_rotation_override=True,
        allow_extra_rotation_overrides=True,
        allow_constrained_translation=True,
        resulting_arrays=updated_arrays,
    )
    result = _translate_offset_constraints(sketches, result)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def erase_array_members(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    targets: tuple[ArrayEntityRef, ...],
    *,
    preserve_order: bool = True,
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Erase selected members while reserving their identities and restoration order."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    selected = set(targets)
    available = {member.target for member in array.members if member.erased_index is None}
    if not selected or len(selected) != len(targets) or not selected.issubset(available):
        raise ValueError("请选择该阵列中尚未擦除的有效成员。")
    if any(ref in selected for item in arrays for ref in item.sources) or any(
        member.replacement is not None and member.replacement.source in selected
        for item in arrays
        for member in item.members
    ):
        raise ValueError("待擦除副本是下游阵列的来源。")
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    entity_positions = {
        ArrayEntityRef(sketch.sketch_id, entity.entity_id): index
        for sketch in sketches
        for index, entity in enumerate(sketch.entities)
    }
    erased_positions: dict[str, list[int]] = {}
    for item in arrays:
        for member in item.members:
            if member.erased_index is not None:
                erased_positions.setdefault(member.target.sketch_id, []).append(member.erased_index)
    for values in erased_positions.values():
        values.sort()
    positions: dict[ArrayEntityRef, int] = {}
    neighbors: dict[ArrayEntityRef, tuple[str | None, str | None]] = {}
    for ref in selected:
        sketch, entity = _resolve_entity(indexed, entities, ref)
        layer = sketch.layers.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("关联阵列副本图层已锁定或隐藏。")
        if any(
            ref.entity_id == item.entity_id for c in sketch.constraints for item in c.references
        ):
            raise ValueError("待擦除副本有关联约束；请先处理约束。")
        position = entity_positions[ref]
        neighbors[ref] = (
            sketch.entities[position - 1].entity_id if position > 0 else None,
            sketch.entities[position + 1].entity_id
            if position + 1 < len(sketch.entities)
            else None,
        )
        previous = erased_positions.get(ref.sketch_id, [])
        lower, upper = position, position + len(previous)
        while lower < upper:
            middle = (lower + upper) // 2
            if middle - bisect_right(previous, middle) < position:
                lower = middle + 1
            else:
                upper = middle
        positions[ref] = lower
    updated = replace(
        array,
        members=tuple(
            replace(
                member,
                erased_index=positions[member.target],
                erased_neighbors=neighbors[member.target] if preserve_order else None,
            )
            if member.target in selected
            else member
            for member in array.members
        ),
    )
    result = tuple(
        replace(
            sketch,
            entities=tuple(
                entity
                for entity in sketch.entities
                if ArrayEntityRef(sketch.sketch_id, entity.entity_id) not in selected
            ),
        )
        for sketch in sketches
    )
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def strip_erased_member_dimensions(
    before: tuple[Sketch, ...], after: tuple[Sketch, ...], targets: tuple[ArrayEntityRef, ...]
) -> tuple[Sketch, ...]:
    """Remove explicitly deleted editable dimensions before validating member erasure."""
    revised = {sketch.sketch_id: sketch for sketch in after}
    selected = set(targets)
    result: list[Sketch] = []
    for sketch in before:
        current = revised.get(sketch.sketch_id, sketch)
        retained_ids = {constraint.constraint_id for constraint in current.constraints}
        removed: set[str] = set()
        entities = {entity.entity_id: entity for entity in sketch.entities}
        for constraint in sketch.constraints:
            if (
                constraint.kind not in DIMENSION_KINDS
                or constraint.constraint_id in retained_ids
                or not any(
                    ArrayEntityRef(sketch.sketch_id, ref.entity_id) in selected
                    for ref in constraint.references
                )
            ):
                continue
            source = entities[constraint.references[0].entity_id]
            layer = sketch.layers.get(constraint.layer_name or source.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("关联标注图层已锁定或隐藏。")
            removed.add(constraint.constraint_id)
        result.append(
            replace(
                sketch,
                constraints=tuple(
                    constraint
                    for constraint in sketch.constraints
                    if constraint.constraint_id not in removed
                ),
            )
        )
    return tuple(result)


def erase_drawing_entities(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    targets: tuple[ArrayEntityRef, ...],
) -> tuple[tuple[Sketch, ...], tuple[AssociativeRectArray, ...]]:
    """Erase ordinary entities and array members together on an isolated candidate."""
    propagate_array_changes(sketches, sketches, arrays)
    selected = set(targets)
    if not selected or len(selected) != len(targets):
        raise ValueError("删除对象为空或引用重复。")
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    for ref in selected:
        _resolve_entity(indexed, entities, ref)
    extra_refs = {output.target for array in arrays for output in array.extra_outputs}
    removed_extras = selected & extra_refs
    if removed_extras:
        if (
            any(source in removed_extras for array in arrays for source in array.sources)
            or any(
                member.replacement is not None and member.replacement.source in removed_extras
                for array in arrays
                for member in array.members
            )
            or any(
                output.source in removed_extras
                for array in arrays
                for output in array.extra_outputs
                if output.target not in removed_extras
            )
        ):
            raise ValueError("额外输出仍被关联阵列引用。")
        if any(
            ArrayEntityRef(sketch.sketch_id, ref.entity_id) in removed_extras
            for sketch in sketches
            for constraint in sketch.constraints
            for ref in constraint.references
        ):
            raise ValueError("额外输出仍被草图约束引用。")
        for ref in removed_extras:
            sketch, entity = _resolve_entity(indexed, entities, ref)
            layer = sketch.layers.get(entity.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("额外输出位于锁定或隐藏图层。")
        sketches = tuple(
            replace(
                sketch,
                entities=tuple(
                    entity
                    for entity in sketch.entities
                    if ArrayEntityRef(sketch.sketch_id, entity.entity_id) not in removed_extras
                ),
            )
            for sketch in sketches
        )
        arrays = tuple(
            replace(
                array,
                extra_outputs=tuple(
                    output for output in array.extra_outputs if output.target not in removed_extras
                ),
            )
            for array in arrays
        )
        propagate_array_changes(sketches, sketches, arrays)
        selected -= removed_extras
        if not selected:
            return sketches, arrays
        indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    member_refs = {member.target for array in arrays for member in array.members}
    ordinary = selected - member_refs
    sources = {source for array in arrays for source in array.sources}
    sources.update(
        member.replacement.source
        for array in arrays
        for member in array.members
        if member.replacement is not None
    )
    if ordinary & sources:
        raise ValueError("待删除对象仍被关联阵列作为来源。")
    proposed: list[Sketch] = []
    for sketch in sketches:
        chosen = {ref.entity_id for ref in ordinary if ref.sketch_id == sketch.sketch_id}
        if not chosen:
            proposed.append(sketch)
            continue
        by_id = {entity.entity_id: entity for entity in sketch.entities}
        for identity in chosen:
            layer = sketch.layers.get(by_id[identity].layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("待删除对象位于锁定或隐藏图层。")
        kept: list[SketchConstraint] = []
        for constraint in sketch.constraints:
            if not any(ref.entity_id in chosen for ref in constraint.references):
                kept.append(constraint)
                continue
            first = by_id.get(constraint.references[0].entity_id)
            layer = sketch.layers.get(constraint.layer_name or (first.layer_name if first else "0"))
            if layer.locked or not layer.displayed:
                raise ValueError("相关约束位于锁定或隐藏图层。")
        proposed.append(
            replace(
                sketch,
                entities=tuple(
                    entity for entity in sketch.entities if entity.entity_id not in chosen
                ),
                constraints=tuple(kept),
            )
        )
    result = propagate_array_changes(sketches, tuple(proposed), arrays)
    current = arrays
    for array in arrays:
        group = tuple(member.target for member in array.members if member.target in selected)
        if not group:
            continue
        result, updated = erase_array_members(result, current, array.array_id, group)
        current = tuple(updated if item.array_id == updated.array_id else item for item in current)
    return result, current


def reset_array_member_overrides(
    sketches: tuple[Sketch, ...], arrays: tuple[AssociativeRectArray, ...], array_id: str
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Reset position and rotation overrides together in one isolated proposal."""
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    if array.extra_outputs:
        propagate_array_changes(sketches, sketches, arrays)
        removed = {output.target for output in array.extra_outputs}
        if (
            any(source in removed for item in arrays for source in item.sources)
            or any(
                member.replacement is not None and member.replacement.source in removed
                for item in arrays
                for member in item.members
            )
            or any(
                output.source in removed
                for item in arrays
                if item.array_id != array_id
                for output in item.extra_outputs
            )
        ):
            raise ValueError("额外输出仍被关联阵列引用。")
        if any(
            ArrayEntityRef(sketch.sketch_id, ref.entity_id) in removed
            for sketch in sketches
            for constraint in sketch.constraints
            for ref in constraint.references
        ):
            raise ValueError("额外输出仍被草图约束引用。")
        indexed, entities = _sketch_index(sketches), _entity_index(sketches)
        for target in removed:
            target_sketch, entity = _resolve_entity(indexed, entities, target)
            layer = target_sketch.layers.get(entity.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("额外输出位于锁定或隐藏图层。")
        stripped = tuple(
            replace(
                sketch,
                entities=tuple(
                    entity
                    for entity in sketch.entities
                    if ArrayEntityRef(sketch.sketch_id, entity.entity_id) not in removed
                ),
            )
            for sketch in sketches
        )
        cleared = replace(array, extra_outputs=())
        remaining = tuple(cleared if item.array_id == array_id else item for item in arrays)
        propagate_array_changes(stripped, stripped, remaining)
        if any(
            member.offset_mm != (0, 0)
            or member.rotation_deg
            or member.erased_index is not None
            or member.replacement is not None
            for member in cleared.members
        ):
            return reset_array_member_overrides(stripped, remaining, array_id)
        return stripped, cleared
    if not any(
        member.rotation_deg or member.erased_index is not None or member.replacement is not None
        for member in array.members
    ):
        return set_array_member_offsets(sketches, arrays, array_id, {}, reset_all=True)
    updated = replace(
        array,
        members=tuple(
            replace(
                member,
                offset_mm=(0, 0),
                rotation_deg=0,
                rotation_center_offset_mm=(0, 0),
                replacement=None,
            )
            for member in array.members
        ),
    )
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        allow_rotation_override=True,
        allow_replacement_override=True,
        allow_constrained_translation=True,
        resulting_arrays=updated_arrays,
    )
    result = _translate_offset_constraints(sketches, result)
    erased = tuple(member for member in updated.members if member.erased_index is not None)
    indexed, entities = _sketch_index(result), _entity_index(result)
    additions: dict[str, list[tuple[int, SketchEntity, tuple[str | None, str | None] | None]]] = {}
    for member in erased:
        assert member.erased_index is not None
        source_sketch, source = _resolve_entity(indexed, entities, member.source)
        target_sketch = indexed.get(member.target.sketch_id)
        if target_sketch is None:
            raise ValueError("关联阵列目标草图不存在。")
        for layer in (
            source_sketch.layers.get(source.layer_name),
            target_sketch.layers.get(source.layer_name),
        ):
            if layer.locked or not layer.displayed:
                raise ValueError("关联阵列源或副本图层已锁定或隐藏。")
        entity = _expected_array_member(updated, member, indexed, entities)
        additions.setdefault(member.target.sketch_id, []).append(
            (member.erased_index, entity, member.erased_neighbors)
        )
    tombstones = {
        (member.target.sketch_id, member.target.entity_id): member
        for item in arrays
        for member in item.members
        if member.erased_index is not None
    }
    restored: list[Sketch] = []
    for sketch in result:
        values = list(sketch.entities)
        other_erased = sorted(
            member.erased_index
            for item in arrays
            if item.array_id != array_id
            for member in item.members
            if member.target.sketch_id == sketch.sketch_id and member.erased_index is not None
        )
        for index, entity, neighbors in sorted(
            additions.get(sketch.sketch_id, ()), key=lambda item: item[0]
        ):
            physical_index = index - bisect_left(other_erased, index)
            if neighbors is not None:
                ids = [item.entity_id for item in values]

                def find_neighbor(
                    identity: str | None,
                    direction: int,
                    live_ids: list[str] = ids,
                    sketch_id: str = sketch.sketch_id,
                ) -> int | None:
                    seen: set[str] = set()
                    while identity is not None:
                        if identity in seen:
                            raise ValueError("擦除成员的邻接关系存在环。")
                        seen.add(identity)
                        if identity in live_ids:
                            return live_ids.index(identity)
                        missing = tombstones.get((sketch_id, identity))
                        if missing is None or missing.erased_neighbors is None:
                            return None
                        identity = missing.erased_neighbors[direction]
                    return None

                before = find_neighbor(neighbors[0], 0)
                after = find_neighbor(neighbors[1], 1)
                if before is not None and after is not None and before >= after:
                    raise ValueError("擦除成员的邻接顺序已变化，无法安全恢复。")
                if after is not None:
                    physical_index = after
                elif before is not None:
                    physical_index = before + 1
                elif any(neighbors) and values:
                    raise ValueError("擦除成员的邻接图元已缺失，无法安全恢复。")
            values.insert(min(max(physical_index, 0), len(values)), entity)
        restored.append(replace(sketch, entities=tuple(values)))
    updated = replace(
        updated,
        members=tuple(
            replace(member, erased_index=None, erased_neighbors=None) for member in updated.members
        ),
    )
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    result = tuple(restored)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def set_array_member_replacements(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    replacements: Mapping[ArrayEntityRef, ArrayReplacement],
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Replace selected members with live, base-aligned geometry sources."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    available = {member.target for member in array.members if member.erased_index is None}
    if not replacements or not set(replacements).issubset(available):
        raise ValueError("请选择该阵列中可见的有效成员。")
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    for replacement in replacements.values():
        if not isinstance(cast("object", replacement), ArrayReplacement):
            raise ValueError("阵列替换来源无效。")
        replacement_sketch, entity = _resolve_entity(indexed, entities, replacement.source)
        if not _same_array_plane(replacement_sketch.frame, array.frame):
            raise ValueError("阵列替换来源不在阵列工作平面。")
        layer = replacement_sketch.layers.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("关联阵列替换来源图层已锁定或隐藏。")
    updated = replace(
        array,
        members=tuple(
            replace(member, replacement=replacements[member.target])
            if member.target in replacements
            else member
            for member in array.members
        ),
    )
    if updated == array:
        raise ValueError("阵列成员替换未变化。")
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    result = propagate_array_changes(
        sketches,
        sketches,
        arrays,
        allow_replacement_override=True,
        allow_constrained_translation=True,
        resulting_arrays=updated_arrays,
    )
    result = _translate_offset_constraints(sketches, result)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def replace_array_cell_with_extra_outputs(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    replacements: Mapping[ArrayEntityRef, ArrayReplacement],
    extras: tuple[ArrayExtraOutput, ...],
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Replace one complete cell and create additional stable outputs."""
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1 or not replacements or not extras:
        raise ValueError("阵列单元替换对象无效。")
    array = matches[0]
    members = tuple(member for member in array.members if member.target in replacements)
    positions = {(member.row, member.column) for member in members}
    if len(members) != len(replacements) or len(positions) != 1:
        raise ValueError("请选择同一阵列单元的全部成员。")
    position = next(iter(positions))
    if set(replacements) != {
        member.target for member in array.members if (member.row, member.column) == position
    }:
        raise ValueError("请选择同一阵列单元的全部成员。")
    if any(
        (output.row, output.column) != position
        or output.target.sketch_id not in {member.target.sketch_id for member in members}
        for output in extras
    ):
        raise ValueError("额外输出必须属于所选单元及目标草图。")
    if any((output.row, output.column) == position for output in array.extra_outputs):
        raise ValueError("该单元已有额外输出，请先重置。")
    if all(member.replacement == replacements[member.target] for member in members):
        propagate_array_changes(sketches, sketches, arrays)
        proposed, replaced = sketches, array
    else:
        proposed, replaced = set_array_member_replacements(sketches, arrays, array_id, replacements)
    updated = replace(replaced, extra_outputs=(*replaced.extra_outputs, *extras))
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in arrays)
    validate_array_network(updated_arrays)
    indexed, entities = _sketch_index(proposed), _entity_index(proposed)
    occupied = {entity.entity_id for sketch in proposed for entity in sketch.entities}
    if any(output.target.entity_id in occupied for output in extras) or len(
        {output.target.entity_id for output in extras}
    ) != len(extras):
        raise ValueError("额外输出身份已被占用。")
    additions: dict[str, list[SketchEntity]] = {}
    for output in extras:
        source_sketch, source = _resolve_entity(indexed, entities, output.source)
        anchor_sketch, anchor = _resolve_entity(indexed, entities, output.anchor_source)
        target_sketch = indexed.get(output.target.sketch_id)
        if target_sketch is None:
            raise ValueError("额外输出目标草图不存在。")
        for layer in (
            source_sketch.layers.get(source.layer_name),
            anchor_sketch.layers.get(anchor.layer_name),
            target_sketch.layers.get(source.layer_name),
        ):
            if layer.locked or not layer.displayed:
                raise ValueError("额外输出来源或目标图层已锁定或隐藏。")
        member = ArrayMember(
            output.anchor_source,
            output.target,
            output.row,
            output.column,
            offset_mm=output.offset_mm,
            rotation_deg=output.rotation_deg,
            rotation_center_offset_mm=output.rotation_center_offset_mm,
            replacement=ArrayReplacement(
                output.source, output.base_offset_mm, output.anchor_source
            ),
        )
        entity = _expected_array_member(updated, member, indexed, entities)
        additions.setdefault(output.target.sketch_id, []).append(entity)
    result = tuple(
        replace(sketch, entities=(*sketch.entities, *additions.get(sketch.sketch_id, ())))
        for sketch in proposed
    )
    propagate_array_changes(result, result, updated_arrays)
    return result, updated


def replace_and_erase_array_members(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    replacements: Mapping[ArrayEntityRef, ArrayReplacement],
    erased: tuple[ArrayEntityRef, ...],
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Replace a complete array cell and retain surplus members for reset."""
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1 or not replacements or not erased or len(set(erased)) != len(erased):
        raise ValueError("阵列单元替换对象无效。")
    array = matches[0]
    selected = set(replacements) | set(erased)
    if set(replacements) & set(erased):
        raise ValueError("阵列成员不能同时替换和擦除。")
    members = tuple(member for member in array.members if member.target in selected)
    positions = {(member.row, member.column) for member in members}
    if len(members) != len(selected) or len(positions) != 1:
        raise ValueError("请选择同一阵列单元的全部成员。")
    position = next(iter(positions))
    if selected != {
        member.target for member in array.members if (member.row, member.column) == position
    }:
        raise ValueError("请选择同一阵列单元的全部成员。")
    proposed, erased_array = erase_array_members(sketches, arrays, array_id, erased)
    erased_arrays = tuple(erased_array if item.array_id == array_id else item for item in arrays)
    if all(
        member.replacement == replacements[member.target]
        for member in erased_array.members
        if member.target in replacements
    ):
        return proposed, erased_array
    return set_array_member_replacements(proposed, erased_arrays, array_id, replacements)


def move_associative_array(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    displacement: Point2D,
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Move every source, regenerate dependent members, and translate a fixed base."""
    result, updated = _move_associative_array(sketches, arrays, array_id, displacement, False)
    return result, next(array for array in updated if array.array_id == array_id)


def move_associative_array_with_offsets(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    displacement: Point2D,
) -> tuple[tuple[Sketch, ...], tuple[AssociativeRectArray, ...]]:
    """Move a grid using member offsets when a source belongs to an upstream grid."""
    return _move_associative_array(sketches, arrays, array_id, displacement, True)


def _move_associative_array(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    displacement: Point2D,
    allow_member_sources: bool,
) -> tuple[tuple[Sketch, ...], tuple[AssociativeRectArray, ...]]:
    delta = _grip_point(displacement)
    if math.hypot(*delta) <= 1e-9:
        raise ValueError("阵列移动距离必须非零。")
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    array = matches[0]
    owners = {member.target: member for item in arrays for member in _generated_members(item)}
    if not allow_member_sources and any(source in owners for source in array.sources):
        raise ValueError("阵列源是其他关联阵列的副本；请先解除上游关联。")
    indexed, entities = _sketch_index(sketches), _entity_index(sketches)
    for source in array.sources:
        sketch, entity = _resolve_entity(indexed, entities, source)
        if not _same_array_plane(sketch.frame, array.frame):
            raise ValueError("关联阵列源不在阵列工作平面。")
        layer = sketch.layers.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("关联阵列源图层已锁定或隐藏。")
    sources = set(array.sources)
    generated_to_move: set[ArrayEntityRef] = set()
    for source in sources & owners.keys():
        ancestor = owners[source].source
        while ancestor in owners and ancestor not in sources:
            ancestor = owners[ancestor].source
        if ancestor not in sources:
            generated_to_move.add(source)
    direct_sources = sources - owners.keys()
    world_origin = array.frame.local_to_world((0, 0))
    world_target = array.frame.local_to_world(delta)
    changed_arrays: list[AssociativeRectArray] = []
    for item in arrays:
        origin = item.frame.world_to_local(world_origin)
        target = item.frame.world_to_local(world_target)
        offset = (target[0] - origin[0], target[1] - origin[1])
        changed_arrays.append(
            replace(
                item,
                members=tuple(
                    replace(
                        member,
                        offset_mm=(
                            member.offset_mm[0] + offset[0],
                            member.offset_mm[1] + offset[1],
                        ),
                    )
                    if member.target in generated_to_move
                    else member
                    for member in item.members
                ),
                extra_outputs=tuple(
                    replace(
                        output,
                        base_offset_mm=(
                            output.base_offset_mm[0] - offset[0],
                            output.base_offset_mm[1] - offset[1],
                        ),
                    )
                    if output.target in generated_to_move
                    else output
                    for output in item.extra_outputs
                ),
            )
        )
    intermediate = tuple(changed_arrays)
    proposed = tuple(
        replace(
            sketch,
            entities=move_entities(
                sketch.entities,
                tuple(
                    entity.entity_id
                    for entity in sketch.entities
                    if ArrayEntityRef(sketch.sketch_id, entity.entity_id) in direct_sources
                ),
                delta,
            ),
        )
        if any(
            ArrayEntityRef(sketch.sketch_id, entity.entity_id) in direct_sources
            for entity in sketch.entities
        )
        else sketch
        for sketch in sketches
    )
    result = propagate_array_changes(
        sketches,
        proposed,
        arrays,
        constrained_translation=delta,
        resulting_arrays=intermediate,
        allow_extra_offsets=allow_member_sources,
    )
    before = _sketch_index(sketches)
    revised: list[Sketch] = []
    for sketch in result:
        old = before[sketch.sketch_id]
        old_entities = {entity.entity_id: entity for entity in old.entities}
        moved_ids = {
            entity.entity_id
            for entity in sketch.entities
            if old_entities.get(entity.entity_id) != entity
        }
        constraints: list[SketchConstraint] = []
        for constraint in sketch.constraints:
            referenced = {ref.entity_id for ref in constraint.references}
            affected = referenced & moved_ids
            if not affected:
                constraints.append(constraint)
                continue
            if constraint.kind == "fixed" or (
                affected != referenced
                and constraint.kind not in {"parallel", "perpendicular", "equal", "angle"}
            ):
                raise ValueError("阵列移动会改变已有约束；请先处理约束。")
            if affected == referenced and (
                constraint.position_mm is not None or constraint.text_position_mm is not None
            ):
                first = old_entities[constraint.references[0].entity_id]
                layer = old.layers.get(constraint.layer_name or first.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("关联尺寸图层已锁定或隐藏。")

                def translate(point: Point2D | None) -> Point2D | None:
                    return None if point is None else (point[0] + delta[0], point[1] + delta[1])

                constraint = replace(
                    constraint,
                    position_mm=translate(constraint.position_mm),
                    text_position_mm=translate(constraint.text_position_mm),
                )
            constraints.append(constraint)
        revised.append(replace(sketch, constraints=tuple(constraints)))
    result = tuple(revised)
    base = array.base_point
    if base is not None and base.point_mm is not None:
        base = ArrayBasePoint(point_mm=(base.point_mm[0] + delta[0], base.point_mm[1] + delta[1]))
    updated = replace(array, base_point=base)
    updated_arrays = tuple(updated if item.array_id == array_id else item for item in intermediate)
    propagate_array_changes(result, result, updated_arrays)
    return result, updated_arrays


def update_array_spacing(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    array_id: str,
    row_spacing: float,
    column_spacing: float,
    *,
    angle_deg: float | None = None,
    base_point: ArrayBasePoint | None = None,
    reset_base_point: bool = False,
) -> tuple[tuple[Sketch, ...], AssociativeRectArray]:
    """Update fixed-grid spacing and dependent arrays on an isolated candidate."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    old = matches[0]
    if reset_base_point and base_point is not None:
        raise ValueError("不能同时设置和重置阵列基点。")
    updated = replace(
        old,
        row_spacing=row_spacing,
        column_spacing=column_spacing,
        angle_deg=old.angle_deg if angle_deg is None else angle_deg,
        base_point=None
        if reset_base_point
        else base_point
        if base_point is not None
        else old.base_point,
    )
    resolve_array_base_point(updated, sketches)
    updated_arrays = tuple(updated if array.array_id == array_id else array for array in arrays)
    result = propagate_array_changes(
        sketches, sketches, arrays, resulting_arrays=updated_arrays, allow_grid_update=True
    )
    return result, updated


def resize_array(
    sketches: tuple[Sketch, ...],
    arrays: tuple[AssociativeRectArray, ...],
    updated: AssociativeRectArray,
) -> tuple[Sketch, ...]:
    """Resize one fixed-spacing grid using caller-supplied stable identities."""
    propagate_array_changes(sketches, sketches, arrays)
    matches = tuple(array for array in arrays if array.array_id == updated.array_id)
    if len(matches) != 1:
        raise ValueError("关联阵列不存在或身份不唯一。")
    old = matches[0]
    if (
        updated.frame != old.frame
        or updated.sources != old.sources
        or updated.angle_deg != old.angle_deg
        or updated.base_point != old.base_point
        or updated.extra_outputs
        != tuple(
            output
            for output in old.extra_outputs
            if output.row < updated.rows and output.column < updated.columns
        )
        or (old.rows > 1 and updated.row_spacing != old.row_spacing)
        or (old.columns > 1 and updated.column_spacing != old.column_spacing)
    ):
        raise ValueError("调整数量时不能改变来源、工作平面、方向或间距。")
    target_sketches = {member.target.sketch_id for member in (*old.members, *updated.members)}
    if len(target_sketches) != 1:
        raise ValueError("调整数量仅支持同一目标草图中的阵列副本。")
    previous = {(item.source, item.row, item.column): item for item in old.members}
    current = {(item.source, item.row, item.column): item for item in updated.members}
    if any(current[key] != previous[key] for key in previous.keys() & current.keys()):
        raise ValueError("已有阵列格位的身份或覆盖不能改变。")
    removed = {previous[key].target for key in previous.keys() - current.keys()}
    removed.update(
        output.target for output in old.extra_outputs if output not in updated.extra_outputs
    )
    removed_erased = {
        previous[key].target
        for key in previous.keys() - current.keys()
        if previous[key].erased_index is not None
    }
    added = [item for key, item in current.items() if key not in previous]
    remaining = tuple(array for array in arrays if array.array_id != old.array_id)
    if (
        any(ref in removed for array in remaining for ref in array.sources)
        or any(
            member.replacement is not None and member.replacement.source in removed
            for array in (*remaining, updated)
            for member in array.members
        )
        or any(
            output.source in removed
            for array in (*remaining, updated)
            for output in array.extra_outputs
        )
    ):
        raise ValueError("待删除副本是其他关联阵列的来源；请先解除下游关系。")
    validate_array_network((*remaining, updated))
    indexed = _sketch_index(sketches)
    entities = _entity_index(sketches)
    all_entity_ids = {entity.entity_id for sketch in sketches for entity in sketch.entities}
    constrained = {
        ArrayEntityRef(sketch.sketch_id, ref.entity_id)
        for sketch in sketches
        for constraint in sketch.constraints
        for ref in constraint.references
    }
    if removed or added:
        for ref in old.sources:
            sketch, entity = _resolve_entity(indexed, entities, ref)
            layer = sketch.layers.get(entity.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("关联阵列源图层已锁定或隐藏。")
    for ref in removed:
        if ref in removed_erased:
            continue
        sketch, entity = _resolve_entity(indexed, entities, ref)
        layer = sketch.layers.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("关联阵列副本图层已锁定或隐藏。")
        if ref in constrained:
            raise ValueError("待删除副本有关联约束；请先处理约束。")
    additions: dict[ArrayEntityRef, SketchEntity] = {}
    added_targets = {member.target for member in added}
    for member in _ordered_array_members(updated):
        if member.target not in added_targets:
            continue
        if member.erased_index is not None:
            raise ValueError("调整数量时不能新增已擦除的阵列成员。")
        if member.target.entity_id in all_entity_ids:
            raise ValueError("新增阵列副本身份已存在。")
        all_entity_ids.add(member.target.entity_id)
        source_sketch, source = _resolve_entity(indexed, entities, member.source)
        target_sketch = indexed.get(member.target.sketch_id)
        if target_sketch is None:
            raise ValueError("关联阵列目标草图不存在。")
        for layer in (
            source_sketch.layers.get(source.layer_name),
            target_sketch.layers.get(source.layer_name),
        ):
            if layer.locked or not layer.displayed:
                raise ValueError("关联阵列源或目标图层已锁定或隐藏。")
        if isinstance(source, PolylineEntity | SplineEntity) and source.point_ids:
            from mycad.core.geometric_tolerance_topology import new_curve_point_identities

            kind = "polyline" if isinstance(source, PolylineEntity) else "spline"
            entities[member.target] = replace(
                source,
                entity_id=member.target.entity_id,
                point_ids=new_curve_point_identities(
                    member.target.entity_id, kind, len(source.point_ids)
                ),
            )
        else:
            entities[member.target] = replace(source, entity_id=member.target.entity_id)
        additions[member.target] = _expected_array_member(updated, member, indexed, entities)
        entities[member.target] = additions[member.target]
        if member.replacement is not None:
            replacement_sketch, replacement = _resolve_entity(
                indexed, entities, member.replacement.source
            )
            replacement_layer = replacement_sketch.layers.get(replacement.layer_name)
            destination_layer = target_sketch.layers.get(additions[member.target].layer_name)
            if (
                replacement_layer.locked
                or not replacement_layer.displayed
                or destination_layer.locked
                or not destination_layer.displayed
            ):
                raise ValueError("关联阵列替换来源或目标图层已锁定或隐藏。")
    proposed = tuple(
        replace(
            sketch,
            entities=(
                *(
                    entity
                    for entity in sketch.entities
                    if ArrayEntityRef(sketch.sketch_id, entity.entity_id) not in removed
                ),
                *(
                    additions[member.target]
                    for member in added
                    if member.target.sketch_id == sketch.sketch_id
                ),
            ),
        )
        for sketch in sketches
    )
    result = propagate_array_changes(sketches, proposed, remaining)
    propagate_array_changes(result, result, (*remaining, updated))
    return result
