# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded curve identity metadata tied to the exact exported curve geometry."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import cast

from mycad.core.geometric_tolerance_topology import CurvePointIdentities
from mycad.core.sketch import PolylineEntity, SplineEntity
from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

CURVE_IDENTITY_APPID = "MYCAD_CURVE_POINT_IDS"
CURVE_IDENTITY_MARKER = "CURVE_IDS_V1"


def pack_curve_identities(entity: PolylineEntity | SplineEntity) -> tuple[str, ...]:
    """Save IDs with the complete local point sequence and segment semantics."""
    if not entity.point_ids:
        raise ValueError("曲线没有点身份。")
    kind = "polyline" if isinstance(entity, PolylineEntity) else "spline"
    points = entity.points_mm if isinstance(entity, PolylineEntity) else entity.control_points_mm
    record = CurvePointIdentities(entity.entity_id, kind, entity.point_ids)
    value = {
        "version": 1,
        "identities": record.to_mapping(),
        "points": [list(point) for point in points],
        "closed": entity.closed if isinstance(entity, PolylineEntity) else False,
        "bulges": list(entity.bulges) if isinstance(entity, PolylineEntity) else [],
    }
    return pack_annotation_metadata(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def restore_curve_identities(
    entity: PolylineEntity | SplineEntity, parts: tuple[str, ...], scale: float
) -> PolylineEntity | SplineEntity:
    """Restore IDs only when every exported point and segment is unchanged."""
    try:
        payload: object = json.loads(unpack_annotation_metadata(parts))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("曲线点身份元数据无法读取。") from exc
    if not isinstance(payload, dict):
        raise ValueError("曲线点身份元数据格式无效。")
    data = cast("dict[str, object]", payload)
    if set(data) != {"version", "identities", "points", "closed", "bulges"}:
        raise ValueError("曲线点身份元数据字段无效。")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("曲线点身份元数据版本无效。")
    record = CurvePointIdentities.from_mapping(data["identities"])
    record.validate_entity(entity)
    raw_points = data["points"]
    raw_bulges = data["bulges"]
    if not isinstance(raw_points, list) or not isinstance(raw_bulges, list):
        raise ValueError("曲线点身份几何快照无效。")
    points: list[tuple[float, float]] = []
    for raw in cast("list[object]", raw_points):
        if not isinstance(raw, list):
            raise ValueError("曲线点身份几何快照无效。")
        values = cast("list[object]", raw)
        if len(values) != 2:
            raise ValueError("曲线点身份几何快照无效。")
        if any(isinstance(value, bool) or not isinstance(value, int | float) for value in values):
            raise ValueError("曲线点身份几何快照无效。")
        try:
            point = tuple(float(cast("float", value)) * scale for value in values)
        except OverflowError as exc:
            raise ValueError("曲线点身份几何快照无效。") from exc
        if not all(math.isfinite(value) for value in point):
            raise ValueError("曲线点身份几何快照无效。")
        points.append((point[0], point[1]))
    current = entity.points_mm if isinstance(entity, PolylineEntity) else entity.control_points_mm
    if tuple(points) != current or len(set(points)) != len(points):
        raise ValueError("曲线点顺序或坐标已改变，身份无法核对。")
    if type(data["closed"]) is not bool or data["closed"] != (
        entity.closed if isinstance(entity, PolylineEntity) else False
    ):
        raise ValueError("曲线闭合状态已改变。")
    if any(
        isinstance(value, bool) or not isinstance(value, int | float)
        for value in cast("list[object]", raw_bulges)
    ):
        raise ValueError("曲线段快照无效。")
    try:
        bulges = tuple(float(cast("float", value)) for value in cast("list[object]", raw_bulges))
    except OverflowError as exc:
        raise ValueError("曲线段快照无效。") from exc
    if bulges != (entity.bulges if isinstance(entity, PolylineEntity) else ()):
        raise ValueError("曲线段曲率已改变。")
    return replace(entity, point_ids=record.point_ids)
