# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only measurements for closed planar drawing geometry."""

from __future__ import annotations

import math
from decimal import Decimal, localcontext

from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import ArcEntity, LineEntity, Point2D, PolylineEntity


def _on_arc(arc: ArcEntity, point: Point2D) -> bool:
    angle = math.degrees(math.atan2(point[1] - arc.center_mm[1], point[0] - arc.center_mm[0]))
    distance = (
        (angle - arc.start_angle_deg) % 360
        if arc.sweep_angle_deg > 0
        else (arc.start_angle_deg - angle) % 360
    )
    tolerance = 32 * math.ulp(max(360.0, abs(arc.start_angle_deg), abs(arc.sweep_angle_deg)))
    return distance <= abs(arc.sweep_angle_deg) + tolerance or 360 - distance <= tolerance


def _arc_intervals(arc: ArcEntity) -> tuple[tuple[float, float], ...]:
    start = (
        math.radians(
            arc.start_angle_deg
            if arc.sweep_angle_deg > 0
            else arc.start_angle_deg + arc.sweep_angle_deg
        )
        % math.tau
    )
    end = start + math.radians(abs(arc.sweep_angle_deg))
    if end <= math.tau:
        return ((start, end),)
    return ((start, math.tau), (0.0, end - math.tau))


def _arc_endpoint(arc: ArcEntity, *, end: bool) -> Point2D:
    angle = math.radians(arc.start_angle_deg + (arc.sweep_angle_deg if end else 0.0))
    return (
        arc.center_mm[0] + arc.radius_mm * math.cos(angle),
        arc.center_mm[1] + arc.radius_mm * math.sin(angle),
    )


def _line_intersections(first: LineEntity, second: LineEntity) -> tuple[Point2D, ...]:
    if any(
        max(a[axis], b[axis]) < min(c[axis], d[axis])
        or max(c[axis], d[axis]) < min(a[axis], b[axis])
        for axis in (0, 1)
        for a, b, c, d in ((first.start_mm, first.end_mm, second.start_mm, second.end_mm),)
    ):
        return ()
    with localcontext() as context:
        context.prec = 80
        a = tuple(Decimal.from_float(value) for value in first.start_mm)
        b = tuple(Decimal.from_float(value) for value in first.end_mm)
        c = tuple(Decimal.from_float(value) for value in second.start_mm)
        d = tuple(Decimal.from_float(value) for value in second.end_mm)
        ux, uy = b[0] - a[0], b[1] - a[1]
        vx, vy = d[0] - c[0], d[1] - c[1]
        wx, wy = c[0] - a[0], c[1] - a[1]
        denominator = ux * vy - uy * vx
        if denominator == 0:
            if wx * uy - wy * ux != 0:
                return ()
            axis = 0 if abs(ux) >= abs(uy) else 1
            direction = b[axis] - a[axis]
            left = max(
                Decimal(0), min((c[axis] - a[axis]) / direction, (d[axis] - a[axis]) / direction)
            )
            right = min(
                Decimal(1), max((c[axis] - a[axis]) / direction, (d[axis] - a[axis]) / direction)
            )
            if left < right:
                raise ValueError("面积边界自交或重叠。")
            ratios = (left,) if left == right else ()
        else:
            ratio = (wx * vy - wy * vx) / denominator
            other = (wx * uy - wy * ux) / denominator
            ratios = (ratio,) if 0 <= ratio <= 1 and 0 <= other <= 1 else ()
        return tuple((float(a[0] + ratio * ux), float(a[1] + ratio * uy)) for ratio in ratios)


def line_boundary_intersections(first: LineEntity, second: LineEntity) -> tuple[Point2D, ...]:
    """Return cut points for two finite lines, including overlapping endpoints."""
    try:
        return _line_intersections(first, second)
    except ValueError:

        def in_bounds(point: Point2D, line: LineEntity) -> bool:
            return all(
                min(line.start_mm[axis], line.end_mm[axis])
                <= point[axis]
                <= max(line.start_mm[axis], line.end_mm[axis])
                for axis in (0, 1)
            )

        return tuple(
            dict.fromkeys(
                point
                for point in (first.start_mm, first.end_mm, second.start_mm, second.end_mm)
                if in_bounds(point, first) and in_bounds(point, second)
            )
        )


def _line_arc_intersections(
    line: LineEntity, arc: ArcEntity, shared: Point2D | None
) -> tuple[Point2D, ...]:
    dx = line.end_mm[0] - line.start_mm[0]
    dy = line.end_mm[1] - line.start_mm[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length == 0:
        raise ValueError("面积结果超出可用范围。")
    ux, uy = dx / length, dy / length
    cx, cy = arc.center_mm[0] - line.start_mm[0], arc.center_mm[1] - line.start_mm[1]
    projection = cx * ux + cy * uy
    if shared is not None:
        shared_parameter = (shared[0] - line.start_mm[0]) * ux + (shared[1] - line.start_mm[1]) * uy
        parameters = (shared_parameter, 2 * projection - shared_parameter)
    else:
        perpendicular = abs(cx * uy - cy * ux)
        if perpendicular > arc.radius_mm:
            return ()
        offset = math.sqrt((arc.radius_mm - perpendicular) * (arc.radius_mm + perpendicular))
        parameters = (projection - offset, projection + offset)
    tolerance = 32 * math.ulp(length)
    points = (
        (line.start_mm[0] + value * ux, line.start_mm[1] + value * uy)
        for value in parameters
        if -tolerance <= value <= length + tolerance
    )
    return tuple(point for point in points if _on_arc(arc, point))


def curve_intersections(
    first: LineEntity | ArcEntity,
    second: LineEntity | ArcEntity,
    shared: Point2D | None,
) -> tuple[Point2D, ...]:
    """Find finite intersections; adjacent arcs may supply their known common point."""
    if isinstance(first, LineEntity):
        if isinstance(second, LineEntity):
            return _line_intersections(first, second)
        return _line_arc_intersections(first, second, shared)
    if isinstance(second, LineEntity):
        return _line_arc_intersections(second, first, shared)
    tolerance = 16 * max(
        math.ulp(value)
        for value in (*first.center_mm, *second.center_mm, first.radius_mm, second.radius_mm)
    )
    if (
        math.dist(first.center_mm, second.center_mm) <= tolerance
        and abs(first.radius_mm - second.radius_mm) <= tolerance
    ):
        for first_range in _arc_intervals(first):
            for second_range in _arc_intervals(second):
                if min(first_range[1], second_range[1]) - max(
                    first_range[0], second_range[0]
                ) > 64 * math.ulp(math.tau):
                    raise ValueError("面积边界自交或重叠。")
        candidates = (
            _arc_endpoint(first, end=False),
            _arc_endpoint(first, end=True),
            _arc_endpoint(second, end=False),
            _arc_endpoint(second, end=True),
        )
        return tuple(
            point for point in candidates if _on_arc(first, point) and _on_arc(second, point)
        )
    if shared is not None:
        dx = second.center_mm[0] - first.center_mm[0]
        dy = second.center_mm[1] - first.center_mm[1]
        distance = math.hypot(dx, dy)
        if not math.isfinite(distance):
            raise ValueError("面积结果超出可用范围。")
        ux, uy = dx / distance, dy / distance
        projection = (shared[0] - first.center_mm[0]) * ux + (shared[1] - first.center_mm[1]) * uy
        other = (
            2 * (first.center_mm[0] + projection * ux) - shared[0],
            2 * (first.center_mm[1] + projection * uy) - shared[1],
        )
        return (shared, other) if _on_arc(first, other) and _on_arc(second, other) else (shared,)
    dx = second.center_mm[0] - first.center_mm[0]
    dy = second.center_mm[1] - first.center_mm[1]
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance):
        raise ValueError("面积结果超出可用范围。")
    if distance > first.radius_mm + second.radius_mm or distance < abs(
        first.radius_mm - second.radius_mm
    ):
        return ()
    ux, uy = dx / distance, dy / distance
    along = (
        distance
        + (first.radius_mm - second.radius_mm) / distance * (first.radius_mm + second.radius_mm)
    ) / 2
    height_squared = (first.radius_mm - along) * (first.radius_mm + along)
    if height_squared < 0:
        return ()
    height = math.sqrt(height_squared)
    base = (first.center_mm[0] + along * ux, first.center_mm[1] + along * uy)
    points = (
        (base[0] - height * uy, base[1] + height * ux),
        (base[0] + height * uy, base[1] - height * ux),
    )
    return tuple(point for point in points if _on_arc(first, point) and _on_arc(second, point))


def polyline_area_perimeter(entity: PolylineEntity) -> tuple[float, float]:
    """Measure a simple closed polyline with exact circular bulge segments."""
    if not entity.closed:
        raise ValueError("请选择闭合多段线。")
    count = len(entity.points_mm)
    bulges = entity.bulges or (0.0,) * count
    try:
        origin = entity.points_mm[0]
        points = tuple((x - origin[0], y - origin[1]) for x, y in entity.points_mm)
        segments = polyline_curve_segments(points, bulges, True, entity.entity_id)
        for first_index, first in enumerate(segments):
            for second_index in range(first_index + 1, count):
                second = segments[second_index]
                adjacent = second_index == first_index + 1 or (
                    first_index == 0 and second_index == count - 1
                )
                shared = points[second_index] if second_index == first_index + 1 else points[0]
                hits = curve_intersections(first, second, shared if adjacent else None)
                tolerance = max(1e-12, 32 * max(math.ulp(value) for value in shared))
                if any(not adjacent or math.dist(hit, shared) > tolerance for hit in hits):
                    raise ValueError("面积边界自交或重叠。")
        terms: list[float] = []
        lengths: list[float] = []
        for index, (start, bulge) in enumerate(zip(points, bulges, strict=True)):
            end = points[(index + 1) % count]
            terms.append((start[0] * end[1] - end[0] * start[1]) / 2)
            chord = math.dist(start, end)
            if bulge == 0:
                lengths.append(chord)
                continue
            theta = 4 * math.atan(bulge)
            radius = chord * (abs(bulge) + 1 / abs(bulge)) / 4
            difference = (
                theta**3 / 6 - theta**5 / 120 + theta**7 / 5040
                if abs(theta) < 1e-3
                else theta - math.sin(theta)
            )
            terms.append(radius * radius * difference / 2)
            lengths.append(radius * abs(theta))
        area, perimeter = abs(math.fsum(terms)), math.fsum(lengths)
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("面积结果超出可用范围。") from exc
    if not math.isfinite(area) or not math.isfinite(perimeter) or area <= 1e-12:
        raise ValueError("面积结果无效或边界退化。")
    return area, perimeter
