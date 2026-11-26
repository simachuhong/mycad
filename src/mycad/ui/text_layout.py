# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native shaped text with shared physical bounds and painting transforms."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QTextLayout,
    QTextOption,
    QTransform,
)

from mycad.core.drawing_text import DrawingText, TextStyle
from mycad.ui.font_manager import FontManager


@dataclass(frozen=True)
class TextLayout:
    """A ready-to-paint local layout; callers apply model/view transforms."""

    bounds: QRectF
    missing_glyphs: str
    _paragraphs: tuple[QTextLayout, ...]
    _offset: QPointF
    _font_offset: QPointF
    _scale_x: float
    _scale_y: float

    def draw(self, painter: QPainter) -> None:
        transform = painter.combinedTransform()
        factor = max(
            abs(transform.m11()), abs(transform.m12()), abs(transform.m21()), abs(transform.m22())
        )
        if factor and max(abs(self._scale_x), abs(self._scale_y)) > 1e12 / factor:
            from mycad.ui.extreme_text_clipping import draw_extreme_text

            draw_extreme_text(
                painter, self._paragraphs, self._font_offset, self._scale_x, self._scale_y
            )
            return
        painter.save()
        painter.translate(self._offset)
        painter.scale(self._scale_x, self._scale_y)
        for paragraph in self._paragraphs:
            paragraph.draw(painter, QPointF())
        painter.restore()

    def glyph_paths(self) -> tuple[QPainterPath, ...]:
        """Capture the shaped glyphs in the same local coordinates as draw()."""
        if self.missing_glyphs:
            raise ValueError(f"文字缺少字形：{self.missing_glyphs}")
        transform = QTransform(
            self._scale_x, 0, 0, self._scale_y, self._offset.x(), self._offset.y()
        )
        paths: list[QPainterPath] = []
        for paragraph in self._paragraphs:
            for run in paragraph.glyphRuns():
                font = run.rawFont()
                if not font.isValid():
                    raise ValueError("文字字形轮廓不可用")
                for glyph, position in zip(run.glyphIndexes(), run.positions(), strict=True):
                    path = font.pathForGlyph(glyph)
                    if path.isEmpty() and not font.boundingRect(glyph).isEmpty():
                        raise ValueError("文字字形轮廓不可用")
                    if not path.isEmpty():
                        paths.append(transform.map(path.translated(position)))
        return tuple(paths)


def layout_text(text: DrawingText, style: TextStyle, manager: FontManager) -> TextLayout:
    """Measure in mm using cap height and shape only once for drawing and hit testing."""
    font = manager.resolve(style)
    metrics = QFontMetricsF(font)
    height = style.height_mm if text.height_mm is None else text.height_mm
    width_factor = style.width_factor if text.width_factor is None else text.width_factor
    scale_y = height / max(metrics.capHeight(), 1e-9)
    scale_x = scale_y * width_factor
    wrapped = text.kind == "mtext" and text.box_width_mm > 0
    width = text.box_width_mm / scale_x if wrapped else 1e9
    horizontal = text.align.rsplit("_", 1)[-1]
    horizontal_factor = {"left": 0.0, "center": 0.5, "right": 1.0}[horizontal]
    paragraphs: list[QTextLayout] = []
    y = 0.0
    maximum_width = 0.0
    natural_height = metrics.height()
    leading = (
        metrics.capHeight() * 5 / 3 if text.kind == "mtext" else metrics.height()
    ) * text.line_spacing
    # U+2028 has newline semantics in QTextLayout and must use the same line-spacing path.
    for value in (
        text.text.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").split("\n")
    ):
        paragraph = QTextLayout(value, font)
        option = QTextOption()
        option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
            if wrapped
            else QTextOption.WrapMode.NoWrap
        )
        paragraph.setTextOption(option)
        paragraph.beginLayout()
        made_line = False
        while True:
            line = paragraph.createLine()
            if not line.isValid():
                break
            made_line = True
            line.setLineWidth(width)
            natural_width = line.naturalTextWidth()
            x = (width - natural_width) * horizontal_factor if wrapped else 0.0
            line.setPosition(QPointF(x, y))
            maximum_width = max(maximum_width, natural_width)
            natural_height = max(natural_height, line.height())
            y += leading
        paragraph.endLayout()
        if not made_line:
            y += leading
        paragraphs.append(paragraph)
    total_height = max(natural_height, y - leading + natural_height)
    total_width = width if wrapped else maximum_width
    if not wrapped and horizontal_factor:
        for paragraph in paragraphs:
            for index in range(paragraph.lineCount()):
                line = paragraph.lineAt(index)
                pos = line.position()
                line.setPosition(
                    QPointF((total_width - line.naturalTextWidth()) * horizontal_factor, pos.y())
                )
    font_x_offset = -total_width * horizontal_factor
    vertical = text.align.split("_", 1)[0] if "_" in text.align else "baseline"
    font_y_offset = {
        "baseline": -metrics.ascent(),
        "top": 0.0,
        "middle": -total_height / 2,
        "bottom": -total_height,
    }[vertical]
    x_offset, y_offset = font_x_offset * scale_x, font_y_offset * scale_y
    # QTextLine's natural width omits negative bearings (for example italic j).
    # Include actual shaped fallback glyph ink so selection also covers overhangs.
    logical_bounds = QRectF(0, 0, total_width, total_height)
    for paragraph in paragraphs:
        for run in paragraph.glyphRuns():
            raw_font = run.rawFont()
            for glyph, position in zip(run.glyphIndexes(), run.positions(), strict=True):
                ink = raw_font.boundingRect(glyph).translated(position)
                logical_bounds = logical_bounds.united(ink)
    return TextLayout(
        QRectF(
            x_offset + logical_bounds.left() * scale_x,
            y_offset + logical_bounds.top() * scale_y,
            logical_bounds.width() * scale_x,
            logical_bounds.height() * scale_y,
        ),
        manager.missing_glyphs(text.text, style),
        tuple(paragraphs),
        QPointF(x_offset, y_offset),
        QPointF(font_x_offset, font_y_offset),
        scale_x,
        scale_y,
    )
