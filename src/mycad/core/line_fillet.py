# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Trimmed or extended two-line fillets in the sketch plane."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.sketch import ArcEntity, LineEntity, Point2D

_EPSILON = 1e-9
_PARALLEL_ANGLE_EPSILON = 1e-12


def _cross(first: Point2D, second: Point2D) -> float:
    return first[0] * second[1] - first[1] * second[0]


def lines_parallel(first: LineEntity, second: LineEntity) -> bool:
    """Return whether the supporting line directions are parallel."""
    a = (first.end_mm[0] - first.start_mm[0], first.end_mm[1] - first.start_mm[1])
    b = (second.end_mm[0] - second.start_mm[0], second.end_mm[1] - second.start_mm[1])
    length_a, length_b = math.hypot(*a), math.hypot(*b)
    if (
        not math.isfinite(length_a)
        or not math.isfinite(length_b)
        or min(length_a, length_b) <= _EPSILON
    ):
        raise ValueError("直线长度无效，无法创建圆角。")
    return (
        abs(_cross((a[0] / length_a, a[1] / length_a), (b[0] / length_b, b[1] / length_b)))
        <= _EPSILON
    )


def _parallel_fillet(
    first: LineEntity,
    second: LineEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    first_dir: Point2D,
    second_dir: Point2D,
    identity: str,
    layer_name: str,
) -> tuple[LineEntity, LineEntity, ArcEntity]:
    projection = (first_pick[0] - first.start_mm[0]) * first_dir[0] + (
        first_pick[1] - first.start_mm[1]
    ) * first_dir[1]
    half = math.dist(first.start_mm, first.end_mm) / 2
    if abs(projection - half) <= _EPSILON:
        raise ValueError("请靠近第一条直线的一端选取，以确定圆角方向。")
    at_end = projection > half
    contact_a = first.end_mm if at_end else first.start_mm
    outward = first_dir if at_end else (-first_dir[0], -first_dir[1])
    normal_unit = (-first_dir[1], first_dir[0])
    delta = (second.start_mm[0] - contact_a[0], second.start_mm[1] - contact_a[1])
    signed_gap = _cross(delta, second_dir) / _cross(normal_unit, second_dir)
    if not math.isfinite(signed_gap) or abs(signed_gap) <= _EPSILON:
        raise ValueError("重合直线无法创建圆角。")
    normal = (normal_unit[0] * signed_gap, normal_unit[1] * signed_gap)
    contact_b = (contact_a[0] + normal[0], contact_a[1] + normal[1])
    center = ((contact_a[0] + contact_b[0]) / 2, (contact_a[1] + contact_b[1]) / 2)
    pick_side = (second_pick[0] - contact_b[0]) * second_dir[0] + (
        second_pick[1] - contact_b[1]
    ) * second_dir[1]
    if abs(pick_side) <= _EPSILON:
        pick_side = -(outward[0] * second_dir[0] + outward[1] * second_dir[1])
    trimmed = (
        replace(second, start_mm=contact_b) if pick_side > 0 else replace(second, end_mm=contact_b)
    )
    radial = (contact_a[0] - center[0], contact_a[1] - center[1])
    sweep = 180.0 if _cross(radial, outward) > 0 else -180.0
    return (
        first,
        trimmed,
        ArcEntity(
            identity,
            center,
            abs(signed_gap) / 2,
            math.degrees(math.atan2(radial[1], radial[0])),
            sweep,
            construction=first.construction,
            layer_name=layer_name,
        ),
    )


def line_corner(
    first: LineEntity, second: LineEntity, first_pick: Point2D, second_pick: Point2D
) -> tuple[LineEntity, LineEntity]:
    """Trim or extend two lines to their intersection, retaining picked sides."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两条不同的直线。")
    if first.construction != second.construction:
        raise ValueError("构造线和普通线不能混合创建圆角。")
    directions: list[Point2D] = []
    for line in (first, second):
        dx, dy = line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]
        length = math.hypot(dx, dy)
        if not math.isfinite(length) or length <= _EPSILON:
            raise ValueError("直线长度无效。")
        directions.append((dx / length, dy / length))
    if any(not math.isfinite(v) for point in (first_pick, second_pick) for v in point):
        raise ValueError("拾取坐标必须是有限数值。")
    denominator = _cross(directions[0], directions[1])
    if abs(denominator) <= _EPSILON:
        raise ValueError("平行或重合直线无法创建角点。")
    delta = (second.start_mm[0] - first.start_mm[0], second.start_mm[1] - first.start_mm[1])
    distance = _cross(delta, directions[1]) / denominator
    vertex = (
        first.start_mm[0] + distance * directions[0][0],
        first.start_mm[1] + distance * directions[0][1],
    )
    if not all(math.isfinite(value) for value in vertex):
        raise ValueError("直线交点超出范围。")
    result: list[LineEntity] = []
    for line, direction, pick in zip(
        (first, second), directions, (first_pick, second_pick), strict=True
    ):
        projection = (pick[0] - vertex[0]) * direction[0] + (pick[1] - vertex[1]) * direction[1]
        if not math.isfinite(projection) or abs(projection) <= _EPSILON:
            raise ValueError("请在线交点的一侧选取对象。")
        result.append(
            replace(line, start_mm=vertex) if projection > 0 else replace(line, end_mm=vertex)
        )
    return result[0], result[1]


def line_fillet(
    first: LineEntity,
    second: LineEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    radius: float,
    identity: str,
    *,
    layer_name: str = "0",
) -> tuple[LineEntity, LineEntity, ArcEntity]:
    """Trim or extend lines to a minor tangent arc on their picked sides."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两条不同的直线。")
    if first.construction != second.construction:
        raise ValueError("构造线和普通线不能混合创建圆角。")
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("圆角半径必须是非负有限数值。")
    if any(not math.isfinite(value) for point in (first_pick, second_pick) for value in point):
        raise ValueError("拾取坐标必须是有限数值。")
    directions: list[Point2D] = []
    lengths: list[float] = []
    for line in (first, second):
        dx = line.end_mm[0] - line.start_mm[0]
        dy = line.end_mm[1] - line.start_mm[1]
        length = math.hypot(dx, dy)
        if not math.isfinite(length) or length <= _EPSILON:
            raise ValueError("直线长度无效，无法创建圆角。")
        lengths.append(length)
        directions.append((dx / length, dy / length))
    first_dir, second_dir = directions
    denominator = _cross(first_dir, second_dir)
    if abs(denominator) <= _EPSILON:
        if abs(denominator) > _PARALLEL_ANGLE_EPSILON:
            raise ValueError("直线近乎平行，无法可靠确定圆角；请调整几何。")
        return _parallel_fillet(
            first, second, first_pick, second_pick, first_dir, second_dir, identity, layer_name
        )
    if radius <= _EPSILON:
        raise ValueError("圆角半径必须是大于零的有限数值。")
    delta = (
        second.start_mm[0] - first.start_mm[0],
        second.start_mm[1] - first.start_mm[1],
    )
    distances = (_cross(delta, second_dir) / denominator, _cross(delta, first_dir) / denominator)
    if any(not math.isfinite(value) for value in distances):
        raise ValueError("直线交点超出范围。")
    vertex = (
        first.start_mm[0] + first_dir[0] * distances[0],
        first.start_mm[1] + first_dir[1] * distances[0],
    )
    rays: list[Point2D] = []
    available: list[float] = []
    signs: list[int] = []
    for direction, length, distance, pick in zip(
        directions, lengths, distances, (first_pick, second_pick), strict=True
    ):
        projection = (pick[0] - vertex[0]) * direction[0] + (pick[1] - vertex[1]) * direction[1]
        if not math.isfinite(projection) or abs(projection) <= _EPSILON:
            raise ValueError("请在线交点的一侧选取对象，以确定保留方向。")
        sign = 1 if projection > 0 else -1
        signs.append(sign)
        rays.append((sign * direction[0], sign * direction[1]))
        available.append(length - distance if sign > 0 else distance)
    dot = max(-1.0, min(1.0, rays[0][0] * rays[1][0] + rays[0][1] * rays[1][1]))
    half_angle = math.acos(dot) / 2
    if half_angle <= _EPSILON or abs(math.pi / 2 - half_angle) <= _EPSILON:
        raise ValueError("直线夹角退化，无法创建圆角。")
    tangent_distance = radius / math.tan(half_angle)
    if not math.isfinite(tangent_distance) or any(
        tangent_distance >= length - _EPSILON for length in available
    ):
        raise ValueError("半径过大，切点超出所选直线。")
    contacts = tuple(
        (vertex[0] + tangent_distance * ray[0], vertex[1] + tangent_distance * ray[1])
        for ray in rays
    )
    bisector = (rays[0][0] + rays[1][0], rays[0][1] + rays[1][1])
    bisector_length = math.hypot(*bisector)
    center_distance = radius / math.sin(half_angle)
    center = (
        vertex[0] + center_distance * bisector[0] / bisector_length,
        vertex[1] + center_distance * bisector[1] / bisector_length,
    )
    if not all(math.isfinite(value) for point in (*contacts, center) for value in point):
        raise ValueError("圆角坐标超出范围。")
    angles = tuple(
        math.degrees(math.atan2(point[1] - center[1], point[0] - center[0])) for point in contacts
    )
    sweep = (angles[1] - angles[0] + 180.0) % 360.0 - 180.0
    trimmed = tuple(
        replace(line, start_mm=contact) if sign > 0 else replace(line, end_mm=contact)
        for line, sign, contact in zip((first, second), signs, contacts, strict=True)
    )
    return (
        trimmed[0],
        trimmed[1],
        ArcEntity(
            identity,
            center,
            radius,
            angles[0],
            sweep,
            construction=first.construction,
            layer_name=layer_name,
        ),
    )
