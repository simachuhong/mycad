# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Clip enormously scaled shaped glyph outlines before passing them to Qt."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPolygonF, QTextLayout

if TYPE_CHECKING:
    from collections.abc import Sequence

Point = tuple[Decimal, Decimal]


def _number(value: float) -> Decimal:
    return Decimal.from_float(value)


def _midpoint(first: Point, second: Point) -> Point:
    return ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)


def flatten_glyph_cubic(
    start: Point, first: Point, second: Point, end: Point, rect: tuple[Decimal, ...]
) -> list[Point]:
    """Flatten only the portion near the viewport; distant curves stay outside it."""
    result: list[Point] = []
    pending = [(start, first, second, end, 0)]
    left, top, right, bottom = rect
    tolerance = Decimal("0.1")
    while pending:
        a, b, c, d, depth = pending.pop()
        xs, ys = (a[0], b[0], c[0], d[0]), (a[1], b[1], c[1], d[1])
        if max(xs) < left or min(xs) > right or max(ys) < top or min(ys) > bottom:
            result.append(d)
            continue
        dx, dy = d[0] - a[0], d[1] - a[1]
        extent = abs(dx) + abs(dy)
        length_squared = dx * dx + dy * dy
        first_projection = (b[0] - a[0]) * dx + (b[1] - a[1]) * dy
        second_projection = (c[0] - a[0]) * dx + (c[1] - a[1]) * dy
        flat = (
            extent > 0
            and abs((b[0] - a[0]) * dy - (b[1] - a[1]) * dx) <= tolerance * extent
            and abs((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) <= tolerance * extent
            and 0 <= first_projection <= length_squared
            and 0 <= second_projection <= length_squared
        ) or (max(xs) - min(xs) <= tolerance and max(ys) - min(ys) <= tolerance)
        if flat:
            result.append(d)
            continue
        if depth >= 2048:
            raise ValueError("glyph clipping exceeded subdivision limit")
        ab, bc, cd = _midpoint(a, b), _midpoint(b, c), _midpoint(c, d)
        abc, bcd = _midpoint(ab, bc), _midpoint(bc, cd)
        middle = _midpoint(abc, bcd)
        pending.append((middle, bcd, cd, d, depth + 1))
        pending.append((a, ab, abc, middle, depth + 1))
    return result


def _clip_polygon(points: Sequence[Point], rect: tuple[Decimal, ...]) -> list[Point]:
    result = list(points)
    for axis, bound, keep_greater in (
        (0, rect[0], True),
        (0, rect[2], False),
        (1, rect[1], True),
        (1, rect[3], False),
    ):
        if not result:
            break
        original = result
        clipped: list[Point] = []
        previous = original[-1]
        previous_inside = previous[axis] >= bound if keep_greater else previous[axis] <= bound
        for current in original:
            current_inside = current[axis] >= bound if keep_greater else current[axis] <= bound
            if current_inside != previous_inside:
                fraction = (bound - previous[axis]) / (current[axis] - previous[axis])
                clipped.append(
                    (
                        previous[0] + fraction * (current[0] - previous[0]),
                        previous[1] + fraction * (current[1] - previous[1]),
                    )
                )
            if current_inside:
                clipped.append(current)
            previous, previous_inside = current, current_inside
        result = clipped
    return result


def _append_contour(
    path: QPainterPath, contour: Sequence[Point], rect: tuple[Decimal, ...]
) -> None:
    polygon = _clip_polygon(contour, rect)
    if len(polygon) >= 3:
        path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in polygon]))
        path.closeSubpath()


def draw_extreme_text(
    painter: QPainter,
    paragraphs: tuple[QTextLayout, ...],
    font_offset: QPointF,
    scale_x: float,
    scale_y: float,
) -> None:
    """Fill clipped glyph contours in device coordinates with high precision."""
    viewport = QRectF(painter.viewport())
    if viewport.isEmpty():
        return
    combined = painter.combinedTransform()
    painter.save()
    painter.resetTransform()
    reset_inverse, invertible = painter.combinedTransform().inverted()
    painter.restore()
    if not invertible:
        return
    transform = combined * reset_inverse
    with localcontext() as context:
        # Binary64 coordinates need up to 309 decimal places plus screen precision.
        context.prec = 380
        rect = tuple(
            _number(value)
            for value in (viewport.left(), viewport.top(), viewport.right(), viewport.bottom())
        )
        m11, m12, m21, m22, tx, ty = map(
            _number,
            (
                transform.m11(),
                transform.m12(),
                transform.m21(),
                transform.m22(),
                transform.dx(),
                transform.dy(),
            ),
        )
        sx, sy = _number(scale_x), _number(scale_y)
        ox, oy = _number(font_offset.x()), _number(font_offset.y())

        def project(x: float, y: float, position: QPointF) -> Point:
            model_x = (_number(x) + _number(position.x()) + ox) * sx
            model_y = (_number(y) + _number(position.y()) + oy) * sy
            return (m11 * model_x + m21 * model_y + tx, m12 * model_x + m22 * model_y + ty)

        clipped_paths: list[QPainterPath] = []
        for paragraph in paragraphs:
            for run in paragraph.glyphRuns():
                font = run.rawFont()
                for glyph, position in zip(run.glyphIndexes(), run.positions(), strict=True):
                    glyph_path = font.pathForGlyph(glyph)
                    result = QPainterPath()
                    result.setFillRule(glyph_path.fillRule())
                    contour: list[Point] = []

                    index = 0
                    while index < glyph_path.elementCount():
                        element = glyph_path.elementAt(index)
                        if element.type == QPainterPath.ElementType.MoveToElement:
                            _append_contour(result, contour, rect)
                            contour = [project(element.x, element.y, position)]
                        elif element.type == QPainterPath.ElementType.LineToElement:
                            contour.append(project(element.x, element.y, position))
                        elif element.type == QPainterPath.ElementType.CurveToElement:
                            if not contour or index + 2 >= glyph_path.elementCount():
                                raise ValueError("invalid glyph curve")
                            second, end = (
                                glyph_path.elementAt(index + 1),
                                glyph_path.elementAt(index + 2),
                            )
                            contour.extend(
                                flatten_glyph_cubic(
                                    contour[-1],
                                    project(element.x, element.y, position),
                                    project(second.x, second.y, position),
                                    project(end.x, end.y, position),
                                    rect,
                                )
                            )
                            index += 2
                        else:
                            raise ValueError("invalid glyph outline")
                        index += 1
                    _append_contour(result, contour, rect)
                    if not result.isEmpty():
                        clipped_paths.append(result)
    painter.save()
    painter.resetTransform()
    painter.setClipRect(viewport, Qt.ClipOperation.IntersectClip)
    for path in clipped_paths:
        painter.fillPath(path, painter.pen().brush())
    painter.restore()
