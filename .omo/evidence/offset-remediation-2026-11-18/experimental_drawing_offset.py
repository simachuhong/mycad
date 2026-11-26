# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Experimental exact straight-segment offsets with multiple closed results."""

from __future__ import annotations

import math
from uuid import uuid4

from build123d import Edge, Wire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_Intersection
from OCP.TopAbs import TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from mycad.core.sketch import PolylineEntity


def offset_closed_polyline(
    source: PolylineEntity, distance_mm: float
) -> tuple[PolylineEntity, ...]:
    """Offset straight closed paths; positive distance points to the directed left side."""
    if not source.closed or source.bulges:
        raise ValueError("仅支持闭合直线多段线。")
    if not math.isfinite(distance_mm) or abs(distance_mm) <= 1e-9:
        raise ValueError("偏置距离须为非零有限值。")
    points = source.points_mm
    area = sum(
        x * yy - xx * y for (x, y), (xx, yy) in zip(points, (*points[1:], points[0]), strict=True)
    )
    edges = [
        Edge.make_line((*a, 0), (*b, 0))
        for a, b in zip(points, (*points[1:], points[0]), strict=True)
    ]
    wire = Wire(edges)
    try:
        builder = BRepOffsetAPI_MakeOffset(wire.wrapped, GeomAbs_Intersection, False)
        builder.Perform(-math.copysign(1.0, area) * distance_mm)
        if not builder.IsDone():
            raise ValueError("偏置无法完成。")
        explorer = TopExp_Explorer(builder.Shape(), TopAbs_WIRE)
        result: list[PolylineEntity] = []
        while explorer.More():
            output = Wire(TopoDS.Wire_s(explorer.Current()))
            if not output.is_closed:
                raise ValueError("偏置产生开放轮廓。")
            ordered = output.order_edges()
            vertices = tuple((edge.position_at(0).X, edge.position_at(0).Y) for edge in ordered)
            result.append(
                PolylineEntity(uuid4().hex, vertices, True, source.construction, source.layer_name)
            )
            explorer.Next()
        if not result:
            raise ValueError("偏置后没有剩余轮廓。")
        return tuple(result)
    except RuntimeError as exc:
        raise ValueError("偏置几何计算失败。") from exc
