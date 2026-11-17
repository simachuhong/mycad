# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Project persistent dimension positions into screen-space annotation geometry."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF

from mycad.core.angular_dimension import angular_sector
from mycad.core.polyline_curves import polyline_arc_segment
from mycad.core.sketch import ArcEntity, CircleEntity, PolylineEntity, SketchEntity
from mycad.core.sketch_constraints import SketchConstraint

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import DimensionLayout, SketchCanvas


def apply_dimension_visibility(
    canvas: SketchCanvas, constraint: SketchConstraint, layout: DimensionLayout | None
) -> DimensionLayout | None:
    """Remove the requested dimension-line halves and their matching arrows."""
    style = canvas.dimension_style_for_constraint(constraint)
    if (
        layout is None
        or style is None
        or constraint.axis.startswith("ordinate_")
        or not (style.suppress_dimension_first or style.suppress_dimension_second)
        or not layout.arrows
    ):
        return layout
    roles = layout.arrow_roles or tuple(range(len(layout.arrows)))
    suppressed = (style.suppress_dimension_first, style.suppress_dimension_second)
    arrows = tuple(
        arrow for arrow, role in zip(layout.arrows, roles, strict=True) if not suppressed[role]
    )
    arrow_roles = tuple(role for role in roles if not suppressed[role])
    path_indices = [
        i
        for i in range(len(layout.lines))
        if i not in layout.extension_indices and i not in layout.leader_indices
    ]
    if not path_indices:
        return replace(layout, arrows=arrows, arrow_roles=arrow_roles)
    if constraint.kind == "radius":
        hidden: set[int] = set(path_indices) if style.suppress_dimension_first else set()
        remaining_lines = tuple(line for i, line in enumerate(layout.lines) if i not in hidden)
        indices = tuple(i - sum(x < i for x in hidden) for i in layout.extension_indices)
        remaining_leaders = tuple(i - sum(x < i for x in hidden) for i in layout.leader_indices)
        return replace(
            layout,
            lines=remaining_lines,
            extension_indices=indices,
            leader_indices=remaining_leaders,
            arrows=arrows,
            arrow_roles=arrow_roles,
        )
    if len(layout.arrows) != 2:
        return layout
    first_tip = next(tip for (tip, _), role in zip(layout.arrows, roles, strict=True) if role == 0)
    start = layout.lines[path_indices[0]][0]
    end = layout.lines[path_indices[-1]][1]
    starts_first = math.hypot((start - first_tip).x(), (start - first_tip).y()) <= math.hypot(
        (end - first_tip).x(), (end - first_tip).y()
    )
    best_index, best_fraction, best_distance = path_indices[0], 0.0, math.inf
    for index in path_indices:
        a, b = layout.lines[index]
        delta = b - a
        squared = delta.x() ** 2 + delta.y() ** 2
        fraction = (
            0.0
            if squared <= 1e-20
            else max(
                0.0,
                min(
                    1.0,
                    (
                        (layout.label.x() - a.x()) * delta.x()
                        + (layout.label.y() - a.y()) * delta.y()
                    )
                    / squared,
                ),
            )
        )
        point = a + delta * fraction
        distance = math.hypot((layout.label - point).x(), (layout.label - point).y())
        if distance < best_distance:
            best_index, best_fraction, best_distance = index, fraction, distance
    before_suppressed = suppressed[0 if starts_first else 1]
    after_suppressed = suppressed[1 if starts_first else 0]
    lines: list[tuple[QPointF, QPointF]] = []
    ext_indices: list[int] = []
    leaders: list[int] = []
    for index, (a, b) in enumerate(layout.lines):
        if index not in path_indices:
            if index in layout.extension_indices:
                ext_indices.append(len(lines))
            if index in layout.leader_indices:
                leaders.append(len(lines))
            lines.append((a, b))
        elif (
            index < best_index
            and not before_suppressed
            or index > best_index
            and not after_suppressed
        ):
            lines.append((a, b))
        elif index == best_index:
            point = a + (b - a) * best_fraction
            if not before_suppressed and best_fraction > 1e-10:
                lines.append((a, point))
            if not after_suppressed and best_fraction < 1 - 1e-10:
                lines.append((point, b))
    return replace(
        layout,
        lines=tuple(lines),
        extension_indices=tuple(ext_indices),
        leader_indices=tuple(leaders),
        arrows=arrows,
        arrow_roles=arrow_roles,
    )


def apply_extension_visibility(
    canvas: SketchCanvas, constraint: SketchConstraint, layout: DimensionLayout | None
) -> DimensionLayout | None:
    """Remove hidden extension lines from both drawing and picking geometry."""
    style = canvas.dimension_style_for_constraint(constraint)
    if (
        layout is None
        or style is None
        or len(layout.extension_indices) != 2
        or constraint.kind in ("radius", "diameter")
        or constraint.axis.startswith("ordinate_")
        or not (style.suppress_extension_first or style.suppress_extension_second)
    ):
        return layout
    hidden = {
        index
        for index, suppress in zip(
            layout.extension_indices,
            (style.suppress_extension_first, style.suppress_extension_second),
            strict=True,
        )
        if suppress
    }
    lines = tuple(line for index, line in enumerate(layout.lines) if index not in hidden)
    roles = tuple(
        role for role, index in enumerate(layout.extension_indices) if index not in hidden
    )
    indices = tuple(
        index - sum(removed < index for removed in hidden)
        for index in layout.extension_indices
        if index not in hidden
    )
    leaders = tuple(i - sum(removed < i for removed in hidden) for i in layout.leader_indices)
    return replace(
        layout,
        lines=lines,
        extension_indices=indices,
        extension_roles=roles,
        leader_indices=leaders,
    )


def radial_center_lines(
    canvas: SketchCanvas,
    c: SketchConstraint,
    entity: CircleEntity | ArcEntity,
    center: QPointF,
    position: QPointF,
) -> tuple[tuple[QPointF, QPointF], ...]:
    """Build center marks for radial dimensions placed outside their circle."""
    style = canvas.dimension_style_for_constraint(c)
    radius = entity.radius_mm * canvas.view_scale
    delta = position - center
    if style is None or style.center_mark == "none" or math.hypot(delta.x(), delta.y()) <= radius:
        return ()
    size = style.center_size * c.scale * canvas.view_scale
    horizontal, vertical = QPointF(size, 0), QPointF(0, size)
    lines = [(center - horizontal, center + horizontal), (center - vertical, center + vertical)]
    if style.center_mark == "line" and radius >= size:
        for axis in (QPointF(1, 0), QPointF(-1, 0), QPointF(0, 1), QPointF(0, -1)):
            lines.append((center + axis * (2 * size), center + axis * (radius + size)))
    return tuple(lines)


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
    extension_indices: list[int] = []
    arrows: tuple[tuple[QPointF, QPointF], ...] = ()
    arrow_roles: tuple[int, ...] = ()
    leader_indices: tuple[int, ...] = ()
    style = canvas.dimension_style_for_constraint(c)
    factor = c.scale * canvas.view_scale

    def extension(start: QPointF, end: QPointF) -> tuple[QPointF, QPointF]:
        if style is None:
            return start, end
        delta = end - start
        length = math.hypot(delta.x(), delta.y())
        if length <= 1e-10:
            return start, end
        direction = delta / length
        return (
            start + direction * min(length, style.extline_offset * factor),
            end + direction * style.extline_extension * factor,
        )

    def add_curved_dimension_line(
        points: tuple[QPointF, ...], center: QPointF, start: float, sweep: float, radius: float
    ) -> None:
        if style is not None and style.dimline_extension > 0 and abs(sweep) > 1e-10:
            extra = min(math.tau, style.dimline_extension * factor / radius)
            steps = max(1, math.ceil(extra / math.radians(7.5)))
            direction = 1 if sweep > 0 else -1

            def circle_point(angle: float) -> QPointF:
                return center + QPointF(math.cos(angle), math.sin(angle)) * radius

            before = tuple(
                circle_point(start - direction * extra * (steps - i) / steps) for i in range(steps)
            ) + (points[0],)
            after = (points[-1],) + tuple(
                circle_point(start + sweep + direction * extra * i / steps)
                for i in range(1, steps + 1)
            )
            lines.extend(zip(before, before[1:], strict=False))
            lines.extend(zip(points, points[1:], strict=False))
            lines.extend(zip(after, after[1:], strict=False))
        else:
            lines.extend(zip(points, points[1:], strict=False))

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
        basis = canvas.dimension_basis(c)
        u_axis = QPointF(basis[0][0], -basis[0][1]) if basis else QPointF(1, 0)
        v_axis = QPointF(basis[1][0], -basis[1][1]) if basis else QPointF(0, -1)
        if c.axis.startswith("ordinate_"):
            normal = v_axis if c.axis == "ordinate_x" else u_axis
            delta = p - b
            corner = b + normal * (delta.x() * normal.x() + delta.y() * normal.y())
            lines.extend(((b, corner), (corner, p)))
            arrows = ((b, corner),)
        else:
            if c.axis == "horizontal":
                normal = v_axis
            elif c.axis == "vertical":
                normal = u_axis
            else:
                delta = b - a
                length = math.hypot(delta.x(), delta.y())
                if length <= 1e-10:
                    return None
                normal = QPointF(-delta.y(), delta.x()) / length
            offset_a = (p.x() - a.x()) * normal.x() + (p.y() - a.y()) * normal.y()
            offset_b = (p.x() - b.x()) * normal.x() + (p.y() - b.y()) * normal.y()
            u, v = a + normal * offset_a, b + normal * offset_b
            extension_indices.extend((len(lines), len(lines) + 1))
            if style is None:
                lines.extend(((a, u), (b, v), (u, v)))
            else:
                delta = v - u
                length = math.hypot(delta.x(), delta.y())
                direction = delta / length if length > 1e-10 else QPointF()
                extra = style.dimline_extension * factor
                lines.extend(
                    (
                        extension(a, u),
                        extension(b, v),
                        (u - direction * extra, v + direction * extra),
                    )
                )
            arrows = ((u, v), (v, u))
            if c.text_position_mm is None:
                label = (u + v) / 2
    elif c.kind in ("radius", "diameter", "arc_length"):
        entity = entities.get(c.references[0].entity_id)
        ref = c.references[0]
        if isinstance(entity, PolylineEntity) and ref.kind == "segment" and ref.index is not None:
            entity = polyline_arc_segment(entity, ref.index)
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
            add_curved_dimension_line(
                points,
                center,
                -math.radians(entity.start_angle_deg),
                -math.radians(entity.sweep_angle_deg),
                radius,
            )
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
                extension_indices.append(len(lines))
                lines.append(extension(actual, endpoint))
        else:
            start = (
                center - direction * entity.radius_mm * canvas.view_scale
                if c.kind == "diameter"
                else center
            )
            lines.append((start, p))
            arrows = ((rim, start), (start, rim)) if c.kind == "diameter" else ((rim, center),)
            center_lines = radial_center_lines(canvas, c, entity, center, p)
            extension_indices.extend(range(len(lines), len(lines) + len(center_lines)))
            lines.extend(center_lines)
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
        if c.position_mm is not None:
            try:
                sector = angular_sector(first, second, c.position_mm)
            except ValueError:
                return None
            start, sweep = -sector.start, -sector.sweep
            first_boundary_start = sector.starts_with_first
        else:
            start = math.atan2(u.y(), u.x())
            basis = canvas.dimension_basis(c)
            sweep = -math.radians(c.value or 0) * (basis[2] if basis else 1.0)
            first_boundary_start = True
        radius = max(12.0, math.hypot(p.x() - center.x(), p.y() - center.y()))
        points = tuple(
            center
            + QPointF(math.cos(start + sweep * i / 32), math.sin(start + sweep * i / 32)) * radius
            for i in range(33)
        )
        add_curved_dimension_line(points, center, start, sweep, radius)
        first_endpoint, second_endpoint = (
            (points[0], points[-1]) if first_boundary_start else (points[-1], points[0])
        )
        extension_indices.extend((len(lines), len(lines) + 1))
        lines.extend((extension(center, first_endpoint), extension(center, second_endpoint)))
        arrows = ((points[0], points[1]), (points[-1], points[-2]))
        arrow_roles = (0, 1) if first_boundary_start else (1, 0)
    else:
        return None
    if c.text_position_mm is not None and (label - p).manhattanLength() > 8:
        leader_indices = (len(lines),)
        lines.append((p, label))
    return DimensionLayout(
        tuple(lines), arrows, label, tuple(extension_indices), (), arrow_roles, leader_indices
    )
