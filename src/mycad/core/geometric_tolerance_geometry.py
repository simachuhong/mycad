# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral geometry for datum annotation indicators."""

from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING

from mycad.core.sketch import Point2D

if TYPE_CHECKING:
    from mycad.core.geometric_tolerance import SurfaceIndication


def circular_datum_geometry(
    center: Point2D,
    target: Point2D,
    radius: float,
    bar_length: float,
    *,
    bar_direction: Point2D | None = None,
) -> tuple[tuple[Point2D, float], tuple[Point2D, Point2D], tuple[Point2D, Point2D]]:
    """Return a circle, radial connector, and centered perpendicular target bar."""
    if not all(math.isfinite(value) for value in (*center, *target, radius, bar_length)):
        raise ValueError("圆圈基准尺寸及位置必须为有限值。")
    if radius <= 0 or bar_length <= 0:
        raise ValueError("圆圈半径及基准短线长度必须大于零。")
    dx, dy = target[0] - center[0], target[1] - center[1]
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance) or distance <= radius:
        raise ValueError("基准短线必须位于圆圈之外。")
    ux, uy = dx / distance, dy / distance
    start = (center[0] + ux * radius, center[1] + uy * radius)
    half = bar_length / 2
    tx, ty = (uy, -ux)
    if bar_direction is not None:
        length = math.hypot(*bar_direction)
        if (
            not all(math.isfinite(v) for v in bar_direction)
            or not math.isfinite(length)
            or length <= 1e-12
        ):
            raise ValueError("基准短线方向必须为非零有限向量。")
        tx, ty = bar_direction[0] / length, bar_direction[1] / length
    bar = (
        (target[0] - tx * half, target[1] - ty * half),
        (target[0] + tx * half, target[1] + ty * half),
    )
    if not all(math.isfinite(value) for point in (start, *bar) for value in point):
        raise ValueError("圆圈基准几何超出数值范围。")
    return (center, radius), (start, target), bar


def surface_indication_geometry(
    target: Point2D, indication: SurfaceIndication
) -> tuple[tuple[Point2D, Point2D], tuple[Point2D, ...], Point2D]:
    """Resolve the reference line, surface leader, and main leader landing."""

    def translate(offset: Point2D) -> Point2D:
        return (target[0] + offset[0], target[1] + offset[1])

    start = translate(indication.reference_start_offset_mm)
    end = translate(indication.reference_end_offset_mm)
    ratio = indication.landing_ratio
    landing = (start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1]))
    leader = (
        start,
        *(translate(point) for point in reversed(indication.leader_offsets_mm)),
        target,
    )
    return (start, end), leader, landing


def datum_leader(
    box: tuple[float, float, float, float], target: Point2D
) -> tuple[Point2D, Point2D] | None:
    """Connect the target to the first box edge along the ray from its center."""
    x1, y1, x2, y2 = box
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    x, y = target
    if left <= x <= right and bottom <= y <= top:
        return None
    cx, cy = (left + right) / 2, (bottom + top) / 2
    dx, dy = x - cx, y - cy
    x_fraction = (right - left) / (2 * abs(dx)) if dx else math.inf
    y_fraction = (top - bottom) / (2 * abs(dy)) if dy else math.inf
    fraction = min(x_fraction, y_fraction)
    return (cx + fraction * dx, cy + fraction * dy), target


def datum_leader_path(
    box: tuple[float, float, float, float], target: Point2D, vertices: tuple[Point2D, ...] = ()
) -> tuple[Point2D, ...]:
    """Connect a box to the target through ordered intermediate vertices."""
    points = (*vertices, target)
    for index, point in enumerate(points):
        segment = datum_leader(box, point)
        if segment is not None:
            return (segment[0], *points[index:])
    return ()


def datum_triangle(origin: Point2D, target: Point2D, size: float = 2.5) -> tuple[Point2D, ...]:
    """Return a triangular pointer with its tip at the leader target."""
    dx, dy = origin[0] - target[0], origin[1] - target[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-12:
        return ()
    ux, uy = dx / distance, dy / distance
    base = (target[0] + ux * size, target[1] + uy * size)
    half = size * 0.4
    return (
        target,
        (base[0] - uy * half, base[1] + ux * half),
        (base[0] + uy * half, base[1] - ux * half),
    )


def frame_leader_arrow(origin: Point2D, target: Point2D, size: float = 2.5) -> tuple[Point2D, ...]:
    """Return the closed-filled leader arrow, separate from a datum triangle."""
    dx, dy = origin[0] - target[0], origin[1] - target[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-12:
        return ()
    ux, uy = dx / distance, dy / distance
    base = (target[0] + ux * size, target[1] + uy * size)
    half = size / 6.0
    return (
        target,
        (base[0] - uy * half, base[1] + ux * half),
        (base[0] + uy * half, base[1] - ux * half),
    )


def _leader_crosses_arrow(start: Point2D, end: Point2D, target: Point2D, normal: Point2D) -> bool:
    arrow = (normal[0] - target[0], normal[1] - target[1])
    length_squared = arrow[0] * arrow[0] + arrow[1] * arrow[1]
    direction = (end[0] - start[0], end[1] - start[1])
    cross = direction[0] * arrow[1] - direction[1] * arrow[0]
    delta = (target[0] - start[0], target[1] - start[1])
    if abs(cross) <= 1e-12:
        if abs(delta[0] * arrow[1] - delta[1] * arrow[0]) > 1e-9:
            return False
        if length_squared <= 1e-18:
            return False
        projection = sorted(
            ((point[0] - target[0]) * arrow[0] + (point[1] - target[1]) * arrow[1]) / length_squared
            for point in (start, end)
        )
        return max(projection[0], 0.0) < min(projection[1], 1.0) - 1e-9
    along = (delta[0] * arrow[1] - delta[1] * arrow[0]) / cross
    arrow_along = (delta[0] * direction[1] - delta[1] * direction[0]) / cross
    if -1e-9 <= along <= 1 + 1e-9 and -1e-9 <= arrow_along <= 1 + 1e-9:
        return not (along >= 1 - 1e-9 and arrow_along >= 1 - 1e-9)
    return False


def reroute_orthogonal_leader(
    position: Point2D,
    offsets: tuple[Point2D, ...],
    normal_vertex: Point2D,
    target: Point2D,
    *,
    avoid_crossing: bool = True,
) -> tuple[Point2D, ...]:
    """Keep the box-side waypoint fixed while routing to a new normal vertex."""
    if not offsets:
        raise ValueError("automatic leader route requires an existing vertex")
    first = (position[0] + offsets[0][0], position[1] + offsets[0][1])
    arrow = (normal_vertex[0] - target[0], normal_vertex[1] - target[1])
    length_squared = arrow[0] * arrow[0] + arrow[1] * arrow[1]

    def on_arrow(point: Point2D) -> bool:
        delta = (point[0] - target[0], point[1] - target[1])
        cross = abs(delta[0] * arrow[1] - delta[1] * arrow[0])
        projection = delta[0] * arrow[0] + delta[1] * arrow[1]
        return (
            cross <= 1e-9 * max(math.sqrt(length_squared), 1.0)
            and -1e-9 <= projection <= length_squared + 1e-9
        )

    if math.dist(first, normal_vertex) > 1e-9 and on_arrow(first):
        raise ValueError("自动引线与附着首段重叠，请先调整引线。")
    points = [first]
    if math.dist(first, normal_vertex) > 1e-9:
        if abs(first[0] - normal_vertex[0]) > 1e-9 and abs(first[1] - normal_vertex[1]) > 1e-9:
            corners = ((first[0], normal_vertex[1]), (normal_vertex[0], first[1]))
            corner = next(
                (
                    candidate
                    for candidate in corners
                    if (
                        not _leader_crosses_arrow(first, candidate, target, normal_vertex)
                        and not _leader_crosses_arrow(
                            candidate, normal_vertex, target, normal_vertex
                        )
                        if avoid_crossing
                        else not on_arrow(candidate) or candidate == corners[1]
                    )
                ),
                None,
            )
            if corner is None:
                raise ValueError("自动引线与附着首段相交，请先调整引线。")
            points.append(corner)
        elif avoid_crossing and _leader_crosses_arrow(first, normal_vertex, target, normal_vertex):
            raise ValueError("自动引线与附着首段重叠，请先调整引线。")
        points.append(normal_vertex)
    return tuple((point[0] - position[0], point[1] - position[1]) for point in points)


def relocate_automatic_leader(
    old_position: Point2D,
    offsets: tuple[Point2D, ...],
    position: Point2D,
    target: Point2D,
    *,
    anchor: Point2D | None = None,
) -> tuple[Point2D, ...]:
    """Move the box while keeping its normal waypoint fixed at the attached target."""
    if not offsets:
        raise ValueError("自动引线缺少顶点。")
    normal = (old_position[0] + offsets[-1][0], old_position[1] + offsets[-1][1])
    origin = position if anchor is None else anchor
    candidates = (
        offsets[0],
        (origin[0] - position[0], normal[1] - position[1]),
        (normal[0] - position[0], origin[1] - position[1]),
    )
    for first in candidates:
        if math.hypot(*first) <= 1e-9:
            continue
        first_point = (position[0] + first[0], position[1] + first[1])
        if _leader_crosses_arrow(origin, first_point, target, normal):
            continue
        try:
            return reroute_orthogonal_leader(position, (first,), normal, target)
        except ValueError:
            continue
    raise ValueError("自动引线无法避开附着首段，请调整标注框位置。")


def _segment_crosses_box(
    start: Point2D, end: Point2D, box: tuple[float, float, float, float]
) -> bool:
    left, right = sorted((box[0], box[2]))
    bottom, top = sorted((box[1], box[3]))
    enter, leave = 0.0, 1.0
    for coordinate, delta, low, high in (
        (start[0], end[0] - start[0], left, right),
        (start[1], end[1] - start[1], bottom, top),
    ):
        if abs(delta) <= 1e-12:
            if not low < coordinate < high:
                return False
            continue
        first = (low - coordinate) / delta
        second = (high - coordinate) / delta
        enter = max(enter, min(first, second))
        leave = min(leave, max(first, second))
    return leave - enter > 1e-9


def box_aware_leader_is_safe(
    position: Point2D,
    offsets: tuple[Point2D, ...],
    target: Point2D,
    box: tuple[float, float, float, float],
    *,
    orthogonal_box_side: bool = False,
) -> bool:
    """Check the visible segments against the recorded annotation box and arrow."""
    if not offsets:
        return False
    vertices = tuple((position[0] + x, position[1] + y) for x, y in offsets)
    normal = vertices[-1]
    if math.dist(normal, target) <= 1e-9:
        return False
    if orthogonal_box_side:
        left, right = sorted((box[0], box[2]))
        bottom, top = sorted((box[1], box[3]))
        if left <= target[0] <= right and bottom <= target[1] <= top:
            return False
    path = datum_leader_path(box, target, vertices)
    if len(path) < 3 or math.dist(path[-2], normal) > 1e-9:
        return False
    if orthogonal_box_side and any(
        abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9
        for a, b in zip(path[:-2], path[1:-1], strict=True)
    ):
        return False
    if any(_segment_crosses_box(a, b, box) for a, b in zip(path[:-1], path[1:], strict=True)):
        return False
    return not any(
        _leader_crosses_arrow(a, b, target, normal)
        for a, b in zip(path[:-2], path[1:-1], strict=True)
    )


def reroute_leader_around_box(
    position: Point2D,
    offsets: tuple[Point2D, ...],
    normal_vertex: Point2D,
    target: Point2D,
    box: tuple[float, float, float, float],
    *,
    orthogonal_box_side: bool = False,
) -> tuple[Point2D, ...]:
    """Route a leader using the actual clipped box edge as its visible start.

    The caller supplies drawing-space box dimensions; no font resources are read.
    The returned vertices remain relative to the annotation position.
    """
    if not offsets or not all(
        math.isfinite(value) for value in (*position, *normal_vertex, *target, *box)
    ):
        raise ValueError("自动引线缺少有效的框或顶点。")
    left, right = sorted((box[0], box[2]))
    bottom, top = sorted((box[1], box[3]))
    limit = math.sqrt(sys.float_info.max) / 8
    if any(abs(value) > limit for value in (*position, *normal_vertex, *target, *box)):
        raise ValueError("自动引线框或法向线段超出数值范围。")
    if right - left <= 1e-9 or top - bottom <= 1e-9 or math.dist(normal_vertex, target) <= 1e-9:
        raise ValueError("自动引线框或法向线段无效。")
    if left <= target[0] <= right and bottom <= target[1] <= top:
        raise ValueError("引线目标位于标注框内，请调整标注位置。")
    if left < normal_vertex[0] < right and bottom < normal_vertex[1] < top:
        raise ValueError("引线法向顶点位于标注框内，请调整标注位置。")
    if not all(
        math.isfinite(value) and abs(value) <= limit for offset in offsets for value in offset
    ):
        raise ValueError("自动引线顶点无效。")
    cx, cy = (left + right) / 2, (bottom + top) / 2
    margin = max(right - left, top - bottom, math.dist(normal_vertex, target), 1.0)

    first = (position[0] + offsets[0][0], position[1] + offsets[0][1])
    candidates = (
        first,
        (normal_vertex[0], cy),
        (cx, normal_vertex[1]),
        (left - margin, cy),
        (right + margin, cy),
        (cx, bottom - margin),
        (cx, top + margin),
    )
    if orthogonal_box_side:
        clearance = max(min(right - left, top - bottom) * 1e-5, 1e-7)
        candidates += (
            (left - clearance, cy),
            (right + clearance, cy),
            (cx, bottom - clearance),
            (cx, top + clearance),
        )
    for candidate in candidates:
        try:
            route = reroute_orthogonal_leader(
                position,
                ((candidate[0] - position[0], candidate[1] - position[1]),),
                normal_vertex,
                target,
            )
        except ValueError:
            continue
        vertices = tuple((position[0] + x, position[1] + y) for x, y in route)
        path = datum_leader_path((left, bottom, right, top), target, vertices)
        if len(path) < 3 or math.dist(path[-2], normal_vertex) > 1e-9:
            continue
        if orthogonal_box_side and any(
            abs(start[0] - end[0]) > 1e-9 and abs(start[1] - end[1]) > 1e-9
            for start, end in zip(path[:-2], path[1:-1], strict=True)
        ):
            continue
        if any(
            _segment_crosses_box(start, end, box)
            for start, end in zip(path[:-1], path[1:], strict=True)
        ):
            continue
        if any(
            _leader_crosses_arrow(start, end, target, normal_vertex)
            for start, end in zip(path[:-2], path[1:-1], strict=True)
        ):
            continue
        return route
    raise ValueError("自动引线无法避开基准框或附着首段，请调整标注位置。")


def relocate_box_aware_leader(
    old_position: Point2D,
    offsets: tuple[Point2D, ...],
    position: Point2D,
    target: Point2D,
    box_size: Point2D,
    *,
    orthogonal_box_side: bool = False,
) -> tuple[Point2D, ...]:
    """Move a sized box, preserving its target and normal vertex in world coordinates."""
    if not offsets:
        raise ValueError("自动引线缺少顶点。")
    normal = (old_position[0] + offsets[-1][0], old_position[1] + offsets[-1][1])
    return reroute_leader_around_box(
        position,
        offsets,
        normal,
        target,
        (position[0], position[1], position[0] + box_size[0], position[1] - box_size[1]),
        orthogonal_box_side=orthogonal_box_side,
    )
