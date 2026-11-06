# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Window/crossing predicates for the geometry displayed by the sketch canvas."""

import math

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
)


def entity_in_selection_box(
    entity: SketchEntity, first: Point2D, second: Point2D, *, crossing: bool
) -> bool:
    """Include an outline wholly inside the box, or touching it in crossing mode.

    Circular curves use analytic bounds/intersections. Splines use the same
    sampled polyline as the canvas, so selection follows their displayed shape.
    The interior of a closed outline is not itself selectable geometry.
    """
    low = (min(first[0], second[0]), min(first[1], second[1]))
    high = (max(first[0], second[0]), max(first[1], second[1]))

    def contains(point: Point2D) -> bool:
        return all(low[axis] - 1e-9 <= point[axis] <= high[axis] + 1e-9 for axis in (0, 1))

    if isinstance(entity, PointEntity):
        return contains(entity.position_mm)

    if isinstance(entity, CircleEntity | ArcEntity):

        def on_arc(angle: float) -> bool:
            if isinstance(entity, CircleEntity):
                return True
            sweep = entity.sweep_angle_deg
            offset = (
                (angle - entity.start_angle_deg) % 360.0
                if sweep > 0.0
                else (entity.start_angle_deg - angle) % 360.0
            )
            return offset <= abs(sweep) + 1e-9

        angles = [angle for angle in (0.0, 90.0, 180.0, 270.0) if on_arc(angle)]
        if isinstance(entity, ArcEntity):
            angles.extend((entity.start_angle_deg, entity.start_angle_deg + entity.sweep_angle_deg))
        center, radius = entity.center_mm, entity.radius_mm
        points = tuple(
            (
                center[0] + radius * math.cos(math.radians(angle)),
                center[1] + radius * math.sin(math.radians(angle)),
            )
            for angle in angles
        )
        if not crossing:
            return all(contains(point) for point in points)
        if any(contains(point) for point in points):
            return True
        # Intersect each infinite box-edge line with the circle, then restrict
        # solutions to that finite edge and (for an arc) its signed sweep.
        for axis in (0, 1):
            other = 1 - axis
            for edge in (low[axis], high[axis]):
                delta = edge - center[axis]
                if abs(delta) > radius + 1e-9:
                    continue
                offset = math.sqrt(max(0.0, radius * radius - delta * delta))
                for value in (center[other] - offset, center[other] + offset):
                    point = (edge, value) if axis == 0 else (value, edge)
                    angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
                    if contains(point) and on_arc(angle):
                        return True
        return False

    if isinstance(entity, LineEntity):
        points = (entity.start_mm, entity.end_mm)
    elif isinstance(entity, PolylineEntity):
        points = entity.points_mm
        if entity.closed:
            points = (*points, points[0])
    elif isinstance(entity, RectangleEntity):
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1))
    else:
        points = entity.sampled_points()
    if not crossing:
        return all(contains(point) for point in points)
    return any(
        _segment_touches_box(start, end, low, high)
        for start, end in zip(points, points[1:], strict=False)
    )


def _segment_touches_box(start: Point2D, end: Point2D, low: Point2D, high: Point2D) -> bool:
    """Clip the finite segment against both box slabs, including tangencies."""
    enter, leave = 0.0, 1.0
    for axis in (0, 1):
        delta = end[axis] - start[axis]
        if abs(delta) <= 1e-15:
            if not low[axis] - 1e-9 <= start[axis] <= high[axis] + 1e-9:
                return False
            continue
        first = (low[axis] - start[axis]) / delta
        second = (high[axis] - start[axis]) / delta
        enter = max(enter, min(first, second))
        leave = min(leave, max(first, second))
        if enter > leave + 1e-12:
            return False
    return True
