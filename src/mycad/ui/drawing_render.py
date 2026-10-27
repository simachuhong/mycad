# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared paper-space vector primitives and physical typography."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsTextItem

from mycad.core.drawing_curves import cubic_segments
from mycad.core.drawing_paper import PaperText, paper_texts, sheet_frame
from mycad.core.drawing_projection import CurveGeometry, DrawingScene, LineCurve


def curve_path(curve: CurveGeometry, *, tolerance: float = 0.01) -> QPainterPath:
    path = QPainterPath()
    if isinstance(curve, LineCurve):
        path.moveTo(curve.start[0], -curve.start[1])
        path.lineTo(curve.end[0], -curve.end[1])
        return path
    previous: tuple[float, float] | None = None
    for cubic in cubic_segments(curve, tolerance=tolerance):
        if previous != cubic.start:
            path.moveTo(cubic.start[0], -cubic.start[1])
        path.cubicTo(
            cubic.control1[0],
            -cubic.control1[1],
            cubic.control2[0],
            -cubic.control2[1],
            cubic.end[0],
            -cubic.end[1],
        )
        previous = cubic.end
    return path


def paper_font() -> QFont:
    families = set(QFontDatabase.families())
    preferred = [
        name
        for name in (
            "Noto Sans CJK SC",
            "Microsoft YaHei",
            "WenQuanYi Micro Hei",
            "SimHei",
            "DejaVu Sans",
        )
        if name in families
    ]
    font = QFont()
    if preferred:
        font.setFamilies(preferred)
    font.setPixelSize(100)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def paper_pen(layer: str, scale: float = 1) -> QPen:
    width = 0.3 if layer == "FRAME" else 0.25 if layer == "VISIBLE" else 0.18
    color = "#087589" if layer == "DIM" else "#687789" if layer == "HIDDEN" else "#26313c"
    pen = QPen(QColor(color), width / scale)
    patterns = {"HIDDEN": (2.5, 1.5), "TANGENT": (0.1, 1.9), "CENTER": (5, 1, 1, 1)}
    if layer in patterns:
        pen.setDashPattern([length / width for length in patterns[layer]])
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    return pen


def add_paper_text(graphics: QGraphicsScene, text: PaperText) -> QGraphicsTextItem:
    font = paper_font()
    item = graphics.addText(text.text, font)
    item.document().setDocumentMargin(0)
    metrics = QFontMetricsF(font)
    factor = text.height_mm / metrics.capHeight()
    item.setScale(factor)
    item.setDefaultTextColor(paper_pen(text.layer).color())
    item.setPos(
        text.position_mm[0],
        -text.position_mm[1] - (metrics.ascent() - metrics.capHeight()) * factor,
    )
    return item


def _paint_text(painter: QPainter, text: PaperText) -> None:
    font = paper_font()
    metrics = QFontMetricsF(font)
    factor = text.height_mm / metrics.capHeight()
    painter.save()
    painter.translate(text.position_mm[0], -text.position_mm[1])
    painter.scale(factor, factor)
    painter.setFont(font)
    painter.setPen(paper_pen(text.layer).color())
    for index, line in enumerate(text.text.splitlines()):
        painter.drawText(QPointF(0, metrics.capHeight() + index * metrics.height()), line)
    painter.restore()


def paint_drawing(painter: QPainter, scene: DrawingScene) -> None:
    painter.setPen(paper_pen("FRAME"))
    for line in sheet_frame(scene):
        painter.drawPath(curve_path(line))
    for view in scene.views:
        painter.save()
        painter.translate(view.anchor_mm[0], -view.anchor_mm[1])
        painter.scale(view.scale, view.scale)
        for curve in view.curves:
            painter.setPen(paper_pen(curve.visibility.upper(), view.scale))
            painter.drawPath(curve_path(curve.geometry, tolerance=0.01 / view.scale))
        painter.restore()
    for annotation in scene.resolved_annotations:
        painter.setPen(paper_pen("CENTER" if annotation.kind == "center" else "DIM"))
        for curve in annotation.curves:
            painter.drawPath(curve_path(curve))
    for text in paper_texts(scene):
        _paint_text(painter, text)
