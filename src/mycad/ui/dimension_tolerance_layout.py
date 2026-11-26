# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension label layout shared by painting and selection bounds."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter

from mycad.core.dimension_tolerance import (
    DimensionTolerance,
    tolerance_parts,
    tolerance_values_hidden_by_precision,
)
from mycad.core.sketch_constraints import SketchConstraint
from mycad.ui.dimension_text import dimension_text, dimension_text_with_number


@dataclass(frozen=True)
class DimensionToleranceLayout:
    main: str
    lines: tuple[str, ...]
    tolerance: DimensionTolerance
    font: QFont
    tolerance_font: QFont
    width: float
    height: float
    main_width: float
    line_height: float

    def draw(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        if self.tolerance.mode == "limits":
            painter.setFont(self.tolerance_font)
            top = rect.center().y() - len(self.lines) * self.line_height / 2
            for index, text in enumerate(self.lines):
                painter.drawText(
                    QRectF(
                        rect.left(), top + index * self.line_height, rect.width(), self.line_height
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
        elif self.lines:
            painter.setFont(self.font)
            left = rect.center().x() - self.width / 2
            painter.drawText(
                QRectF(left, rect.top(), self.main_width, rect.height()),
                Qt.AlignmentFlag.AlignCenter,
                self.main,
            )
            painter.setFont(self.tolerance_font)
            height = len(self.lines) * self.line_height
            top = {
                "top": rect.top(),
                "middle": rect.center().y() - height / 2,
                "bottom": rect.bottom() - height,
            }[self.tolerance.alignment]
            for index, text in enumerate(self.lines):
                painter.drawText(
                    QRectF(
                        left + self.main_width,
                        top + index * self.line_height,
                        self.width - self.main_width,
                        self.line_height,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
        else:
            painter.setFont(self.font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.main)
        painter.restore()


def layout_dimension_tolerance(
    constraint: SketchConstraint, tolerance: DimensionTolerance, font: QFont, scale: float
) -> DimensionToleranceLayout:
    """Shape the already resolved display value and inherited tolerance."""
    main = dimension_text(constraint)
    if not constraint.driving:
        main = f"({main})"
    value = constraint.value
    overflow = False
    try:
        lines = tolerance_parts(value, tolerance) if value is not None else ()
    except ValueError:
        if tolerance.mode != "limits":
            raise
        lines = ("公差极限超出范围",)
        overflow = True
    if value is not None and tolerance_values_hidden_by_precision(value, tolerance):
        lines = ("公差精度不足",)
        overflow = True
    if tolerance.mode == "limits" and value is not None and not overflow:
        lines = tuple(dimension_text_with_number(constraint, number) for number in lines)
        if not constraint.driving:
            lines = tuple(f"({line})" for line in lines)
    smaller = QFont(font)
    smaller.setPointSizeF(max(0.02, font.pointSizeF() * tolerance.text_factor))
    main_metrics, small_metrics = QFontMetricsF(font), QFontMetricsF(smaller)
    main_width = main_metrics.horizontalAdvance(main) + 6 * scale
    line_width = (
        max((small_metrics.horizontalAdvance(line) for line in lines), default=0) + 4 * scale
    )
    line_height = max(small_metrics.height(), 1.0)
    if tolerance.mode == "limits" and lines:
        width = line_width
    else:
        width = main_width + (line_width if lines else 0)
    width = max(24 * scale, width + 4 * scale)
    height = max(18 * scale, main_metrics.height(), len(lines) * line_height)
    return DimensionToleranceLayout(
        main, lines, tolerance, font, smaller, width, height, main_width, line_height
    )
