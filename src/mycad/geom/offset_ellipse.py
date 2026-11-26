# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact ellipse construction and bounded-error OCCT offset conversion."""

from __future__ import annotations

import math
from collections.abc import Callable
from importlib import import_module
from typing import cast
from uuid import uuid4

from build123d import AngularDirection, Edge, Plane, Wire

from mycad.core.sketch import EllipseEntity, Point2D, SplineEntity, WorkPlaneFrame
from mycad.geom.offset_spline import approximate_offset_edge


def _member(value: object, name: str) -> object:
    return getattr(value, name)


def ellipse_edge(source: EllipseEntity, *, frame: WorkPlaneFrame | None = None) -> Edge:
    """Build the exact planar ellipse edge, preserving parameter direction."""
    rotation = math.radians(source.rotation_deg)
    frame = frame or WorkPlaneFrame.xy()
    cosine, sine = math.cos(rotation), math.sin(rotation)
    major_axis = tuple(
        cosine * u + sine * v for u, v in zip(frame.u_axis, frame.v_axis, strict=True)
    )
    plane = Plane(
        origin=frame.local_to_world(source.center_mm),
        x_dir=major_axis,
        z_dir=frame.normal,
    )
    direction = (
        AngularDirection.COUNTER_CLOCKWISE
        if source.sweep_angle_deg > 0
        else AngularDirection.CLOCKWISE
    )
    return Edge.make_ellipse(
        source.major_radius_mm,
        source.minor_radius_mm,
        plane,
        source.start_angle_deg,
        source.start_angle_deg + source.sweep_angle_deg,
        direction,
    )


def offset_ellipse(source: EllipseEntity, distance: float) -> tuple[SplineEntity, ...]:
    """Offset an ellipse; fit output as cubic pieces within 0.001 mm."""
    if not math.isfinite(distance) or abs(distance) <= 1e-9:
        raise ValueError("偏置距离须为非零有限值。")
    if distance * source.sweep_angle_deg > 0:
        start = source.start_angle_deg % 180
        sweep = source.sweep_angle_deg
        angles = [start, start + sweep]
        to_minimum = (-start % 180) if sweep > 0 else start
        if to_minimum <= abs(sweep):
            angles.append(0.0)
        major, minor = source.major_radius_mm, source.minor_radius_mm
        minimum_radius = min(
            math.hypot(major * math.sin(math.radians(angle)), minor * math.cos(math.radians(angle)))
            ** 3
            / (major * minor)
            for angle in angles
        )
        if abs(distance) >= minimum_radius - 1e-9:
            raise ValueError("偏置距离达到曲率半径，椭圆路径会退化或自相交。")
    make_offset = cast(
        "Callable[[object, object, bool], object]",
        import_module("OCP.BRepOffsetAPI").BRepOffsetAPI_MakeOffset,
    )
    intersection = cast("object", import_module("OCP.GeomAbs").GeomAbs_Intersection)
    explorer_factory = cast(
        "Callable[[object, object], object]", import_module("OCP.TopExp").TopExp_Explorer
    )
    wire_kind = cast("object", import_module("OCP.TopAbs").TopAbs_WIRE)
    wire_cast = cast("Callable[[object], object]", import_module("OCP.TopoDS").TopoDS.Wire_s)
    wrap_wire = cast("Callable[[object], Wire]", Wire)
    try:
        wire = Wire([ellipse_edge(source)])
        builder = make_offset(wire.wrapped, intersection, not source.closed)
        cast("Callable[[float], None]", _member(builder, "Perform"))(-distance)
        if not cast("Callable[[], bool]", _member(builder, "IsDone"))():
            raise ValueError("椭圆偏置无法完成。")
        shape = cast("Callable[[], object]", _member(builder, "Shape"))()
        explorer = explorer_factory(shape, wire_kind)
        more = cast("Callable[[], bool]", _member(explorer, "More"))
        current = cast("Callable[[], object]", _member(explorer, "Current"))
        advance = cast("Callable[[], None]", _member(explorer, "Next"))
        branches: list[list[tuple[Point2D, ...]]] = []
        while more():
            output = wrap_wire(wire_cast(current()))
            pieces = [
                piece for edge in output.order_edges() for piece in approximate_offset_edge(edge)
            ]
            if not pieces or output.is_closed != source.closed:
                raise ValueError("椭圆偏置产生不支持的分支。")
            branches.append(pieces)
            advance()
        if len(branches) != 1:
            raise ValueError("椭圆偏置结果为空或存在多个分支。")
        pieces = branches[0]
        first = source.point_at(0)
        nearby = source.point_at(1e-6)
        tangent = (nearby[0] - first[0], nearby[1] - first[1])
        length = math.hypot(*tangent)
        expected = (
            first[0] - distance * tangent[1] / length,
            first[1] + distance * tangent[0] / length,
        )
        if math.dist(pieces[-1][-1], expected) < math.dist(pieces[0][0], expected):
            pieces = [tuple(reversed(piece)) for piece in reversed(pieces)]
        normalized: list[tuple[Point2D, ...]] = []
        for piece in pieces:
            if normalized:
                if math.dist(normalized[-1][-1], piece[0]) > 1e-6:
                    raise ValueError("椭圆偏置分段不连续。")
                piece = (normalized[-1][-1], *piece[1:])
            normalized.append(piece)
        if source.closed and math.dist(normalized[-1][-1], normalized[0][0]) > 1e-6:
            raise ValueError("椭圆偏置闭合失败。")
        return tuple(
            SplineEntity(uuid4().hex, piece, source.construction, source.layer_name)
            for piece in normalized
        )
    except RuntimeError as exc:
        raise ValueError("椭圆偏置几何计算失败。") from exc
