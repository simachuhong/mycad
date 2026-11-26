# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Display-only geometry for independent reference dimensions."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPolygonF, QTransform

from mycad.core.cross_sketch_tangency import project_coplanar_rotation, project_coplanar_vector
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.geometric_tolerance_geometry import datum_triangle
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.sketch_constraints import ConstraintKind, SketchConstraint, SketchGeometryReference
from mycad.ui.dimension_tolerance_layout import DimensionToleranceLayout, layout_dimension_tolerance

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import SketchCanvas


def project_reference_dimension(
    dimension: DetachedDimension,
    source: WorkPlaneFrame,
    target: WorkPlaneFrame,
    delta: tuple[float, float] = (0, 0),
) -> DetachedDimension:
    """Project a reference dimension without changing its measured value."""
    direction = project_coplanar_vector(
        (math.cos(math.radians(dimension.angle_deg)), math.sin(math.radians(dimension.angle_deg))),
        source,
        target,
    )
    reflected = project_coplanar_rotation(1, source, target) < 0

    def point(value: tuple[float, float]) -> tuple[float, float]:
        x, y = target.world_to_local(source.local_to_world(value))
        return (x + delta[0], y + delta[1])

    angular = dimension.kind in ("angular_3p", "angular_2l")
    first, second = dimension.first_mm, dimension.second_mm
    if angular and reflected:
        first, second = second, first
    angle = 0.0 if angular else math.degrees(math.atan2(direction[1], direction[0]))
    if dimension.kind == "ordinate_y" and reflected:
        angle += 180
    return replace(
        dimension,
        first_mm=point(first),
        second_mm=point(second),
        location_mm=point(dimension.location_mm),
        vertex_mm=point(dimension.vertex_mm) if dimension.vertex_mm is not None else None,
        angle_deg=angle,
    )


@dataclass(frozen=True)
class ReferenceDimensionLayout:
    lines: tuple[tuple[QPointF, QPointF], ...]
    arrows: tuple[tuple[QPointF, ...], ...]
    label: QRectF
    text: DimensionToleranceLayout
    label_polygon: QPolygonF | None = None
    label_rotation: float = 0.0

    def hit(self, point: QPointF, radius: float = 6.0) -> bool:
        if (
            self.label_polygon.containsPoint(point, Qt.FillRule.WindingFill)
            if self.label_polygon is not None
            else self.label.contains(point)
        ):
            return True
        if any(
            len(triangle) >= 3 and QPolygonF(triangle).containsPoint(point, Qt.FillRule.WindingFill)
            for triangle in self.arrows
        ):
            return True
        for start, end in self.lines:
            dx, dy = end.x() - start.x(), end.y() - start.y()
            squared = dx * dx + dy * dy
            fraction = (
                0.0
                if squared < 1e-12
                else max(
                    0.0,
                    min(
                        1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / squared
                    ),
                )
            )
            if (
                math.hypot(
                    point.x() - start.x() - fraction * dx, point.y() - start.y() - fraction * dy
                )
                <= radius
            ):
                return True
        return False

    def draw(self, painter: QPainter) -> None:
        for start, end in self.lines:
            painter.drawLine(start, end)
        painter.save()
        painter.setBrush(painter.pen().color())
        for triangle in self.arrows:
            painter.drawPolygon(QPolygonF(triangle))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.label_polygon is None:
            self.text.draw(painter, self.label)
        else:
            painter.translate(self.label.center())
            painter.rotate(self.label_rotation)
            self.text.draw(
                painter,
                QRectF(
                    -self.text.width / 2, -self.text.height / 2, self.text.width, self.text.height
                ),
            )
        painter.restore()


def layout_reference_dimension(
    dimension: DetachedDimension, canvas: SketchCanvas, *, ordinate_bent: bool | None = None
) -> ReferenceDimensionLayout:
    first, second, base = dimension.first_mm, dimension.second_mm, dimension.location_mm
    angle = (
        math.atan2(second[1] - first[1], second[0] - first[0])
        if dimension.kind == "aligned"
        else math.radians(dimension.angle_deg)
    )
    normal = (-math.sin(angle), math.cos(angle))

    def projection(point: tuple[float, float]) -> tuple[float, float]:
        distance = (base[0] - point[0]) * normal[0] + (base[1] - point[1]) * normal[1]
        return point[0] + normal[0] * distance, point[1] + normal[1] * distance

    q1, q2 = projection(first), projection(second)

    def screen(point: tuple[float, float]) -> QPointF:
        return canvas.local_to_screen_precise(point)

    radial = dimension.kind in ("radius", "diameter")
    angular = dimension.kind in ("angular_3p", "angular_2l")
    if angular:
        assert dimension.vertex_mm is not None
        vertex = dimension.vertex_mm
        start = math.atan2(first[1] - vertex[1], first[0] - vertex[0])
        sweep = math.radians(dimension.nominal)
        radius = math.dist(vertex, base)
        arc = tuple(
            (
                vertex[0] + radius * math.cos(start + sweep * index / 32),
                vertex[1] + radius * math.sin(start + sweep * index / 32),
            )
            for index in range(33)
        )
        lines = (
            (screen(first), screen(arc[0])),
            (screen(second), screen(arc[-1])),
            *((screen(a), screen(b)) for a, b in zip(arc, arc[1:], strict=False)),
        )
        arrows = tuple(
            tuple(screen(point) for point in datum_triangle(other, tip, 1.8))
            for tip, other in ((arc[0], arc[1]), (arc[-1], arc[-2]))
        )
    elif dimension.kind in ("ordinate_x", "ordinate_y"):
        if ordinate_bent if ordinate_bent is not None else dimension.angle_deg != 0:
            normal = (
                (-math.sin(angle), math.cos(angle))
                if dimension.kind == "ordinate_x"
                else (math.cos(angle), math.sin(angle))
            )
            offset = (base[0] - second[0]) * normal[0] + (base[1] - second[1]) * normal[1]
            corner = (second[0] + offset * normal[0], second[1] + offset * normal[1])
            lines = ((screen(second), screen(corner)), (screen(corner), screen(base)))
            arrow_origin = base if math.dist(corner, second) <= 1e-12 else corner
            arrows = (tuple(screen(point) for point in datum_triangle(arrow_origin, second, 1.8)),)
        else:
            lines = ((screen(second), screen(base)),)
            arrows = (tuple(screen(point) for point in datum_triangle(base, second, 1.8)),)
    elif radial:
        lines = ((screen(first), screen(second)), (screen(second), screen(base)))
        endpoints = (
            ((second, first),) if dimension.kind == "radius" else ((first, second), (second, first))
        )
        arrows = tuple(
            tuple(screen(point) for point in datum_triangle(other, tip, 1.8))
            for tip, other in endpoints
        )
    else:
        lines = (
            (screen(first), screen(q1)),
            (screen(second), screen(q2)),
            (screen(q1), screen(q2)),
        )
        arrows = tuple(
            tuple(screen(point) for point in datum_triangle(other, tip, 1.8))
            for tip, other in ((q1, q2), (q2, q1))
        )
    constraint = SketchConstraint(
        "0" * 32,
        "angle" if angular else cast("ConstraintKind", dimension.kind) if radial else "length",
        (
            (
                SketchGeometryReference("0" * 32, "geometry"),
                SketchGeometryReference("1" * 32, "geometry"),
            )
            if angular
            else (SketchGeometryReference("0" * 32, "geometry"),)
        ),
        dimension.nominal,
        "deg" if angular else "mm",
        driving=True,
        axis=dimension.kind if dimension.kind in ("ordinate_x", "ordinate_y") else "aligned",
        precision=dimension.precision,
        text_override=(
            None
            if (radial or angular) and dimension.text_override in ("", "<>")
            else dimension.text_override or "<>"
        ),
    )
    text = layout_dimension_tolerance(
        constraint, dimension.tolerance, canvas.dimension_label_font(constraint), 1.0
    )
    center = screen(
        base
        if radial or angular or dimension.kind in ("ordinate_x", "ordinate_y")
        else ((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
    )
    label = QRectF(
        center.x() - text.width / 2, center.y() - text.height / 2, text.width, text.height
    )
    if dimension.kind in ("ordinate_x", "ordinate_y") and dimension.angle_deg != 0:
        rotation = -dimension.angle_deg
        transform = QTransform().translate(center.x(), center.y()).rotate(rotation)
        local = QRectF(-text.width / 2, -text.height / 2, text.width, text.height)
        polygon = transform.map(QPolygonF(local))
        return ReferenceDimensionLayout(
            lines, arrows, polygon.boundingRect(), text, polygon, rotation
        )
    return ReferenceDimensionLayout(lines, arrows, label, text)
