# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Project persistent dimension positions into screen-space annotation geometry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF

from mycad.core.sketch import ArcEntity, CircleEntity, SketchEntity
from mycad.core.sketch_constraints import SketchConstraint

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import DimensionLayout, SketchCanvas


def placed_dimension_layout(
    canvas: SketchCanvas, c: SketchConstraint, entities: dict[str, SketchEntity]
) -> DimensionLayout | None:
    from mycad.ui.sketch_editor import DimensionLayout

    position = c.position_mm
    if position is None:
        anchor = canvas.constraint_anchor(c, entities)
        if anchor is None:
            return None
        position = (anchor[0] + 5, anchor[1] + 5)
    p = QPointF(canvas.local_to_screen(position))
    label = QPointF(canvas.local_to_screen(c.text_position_mm)) if c.text_position_mm else p
    lines: list[tuple[QPointF, QPointF]] = []
    arrows: tuple[tuple[QPointF, QPointF], ...] = ()
    if c.kind in ("length", "distance"):
        if c.kind == "length":
            segment = canvas.line_for_reference(c.references[0], entities)
        else:
            first = canvas.point_for_reference(c.references[0], entities)
            second = canvas.point_for_reference(c.references[1], entities)
            segment = (first, second) if first is not None and second is not None else None
        if segment is None:
            return None
        a, b = (QPointF(canvas.local_to_screen(x)) for x in segment)
        if c.axis.startswith("ordinate_"):
            corner = QPointF(b.x(), p.y()) if c.axis == "ordinate_x" else QPointF(p.x(), b.y())
            lines.extend(((b, corner), (corner, p)))
            arrows = ((b, corner),)
        else:
            if c.axis == "horizontal":
                u, v = QPointF(a.x(), p.y()), QPointF(b.x(), p.y())
            elif c.axis == "vertical":
                u, v = QPointF(p.x(), a.y()), QPointF(p.x(), b.y())
            else:
                delta = b - a
                length = math.hypot(delta.x(), delta.y())
                if length <= 1e-10:
                    return None
                normal = QPointF(-delta.y(), delta.x()) / length
                offset = (p.x() - a.x()) * normal.x() + (p.y() - a.y()) * normal.y()
                u, v = a + normal * offset, b + normal * offset
            lines.extend(((a, u), (b, v), (u, v)))
            arrows = ((u, v), (v, u))
            if c.text_position_mm is None:
                label = (u + v) / 2
    elif c.kind in ("radius", "diameter", "arc_length"):
        entity = entities.get(c.references[0].entity_id)
        if not isinstance(entity, CircleEntity | ArcEntity):
            return None
        center = QPointF(canvas.local_to_screen(entity.center_mm))
        delta = p - center
        length = math.hypot(delta.x(), delta.y())
        direction = delta / length if length > 1e-10 else QPointF(1, 0)
        rim = center + direction * (entity.radius_mm * canvas.view_scale)
        if c.kind == "arc_length" and isinstance(entity, ArcEntity):
            radius = max(8.0, length)
            points = tuple(
                center
                + QPointF(
                    math.cos(
                        math.radians(entity.start_angle_deg + entity.sweep_angle_deg * i / 48)
                    ),
                    -math.sin(
                        math.radians(entity.start_angle_deg + entity.sweep_angle_deg * i / 48)
                    ),
                )
                * radius
                for i in range(49)
            )
            lines.extend(zip(points, points[1:], strict=False))
            arrows = ((points[0], points[1]), (points[-1], points[-2]))
            for angle, endpoint in (
                (entity.start_angle_deg, points[0]),
                (entity.start_angle_deg + entity.sweep_angle_deg, points[-1]),
            ):
                actual = (
                    center
                    + QPointF(math.cos(math.radians(angle)), -math.sin(math.radians(angle)))
                    * entity.radius_mm
                    * canvas.view_scale
                )
                lines.append((actual, endpoint))
        else:
            start = (
                center - direction * entity.radius_mm * canvas.view_scale
                if c.kind == "diameter"
                else center
            )
            lines.append((start, p))
            arrows = ((rim, start), (start, rim)) if c.kind == "diameter" else ((rim, center),)
    elif c.kind == "angle":
        first = canvas.line_for_reference(c.references[0], entities)
        second = canvas.line_for_reference(c.references[1], entities)
        if first is None or second is None:
            return None
        a, b = (QPointF(canvas.local_to_screen(x)) for x in first)
        x, y = (QPointF(canvas.local_to_screen(x)) for x in second)
        u, v = b - a, y - x
        cross = u.x() * v.y() - u.y() * v.x()
        if abs(cross) <= 1e-10:
            return None
        d = x - a
        center = a + u * ((d.x() * v.y() - d.y() * v.x()) / cross)
        start = math.atan2(u.y(), u.x())
        sweep = -math.radians(c.value or 0)
        radius = max(12.0, math.hypot(p.x() - center.x(), p.y() - center.y()))
        points = tuple(
            center
            + QPointF(math.cos(start + sweep * i / 32), math.sin(start + sweep * i / 32)) * radius
            for i in range(33)
        )
        lines.extend(zip(points, points[1:], strict=False))
        lines.extend(((center, points[0]), (center, points[-1])))
        arrows = ((points[0], points[1]), (points[-1], points[-2]))
    else:
        return None
    if c.text_position_mm is not None and (label - p).manhattanLength() > 8:
        lines.append((p, label))
    return DimensionLayout(tuple(lines), arrows, label)
