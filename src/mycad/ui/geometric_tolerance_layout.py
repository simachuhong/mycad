# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Physical layout of editable geometric tolerance frame cells."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen

from mycad.core.drawing_text import DrawingText, TextStyle
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.core.geometric_tolerance_geometry import datum_leader_path, surface_indication_geometry
from mycad.formats.dxf_datum import datum_box_dimensions
from mycad.ui.font_manager import FontManager
from mycad.ui.geometric_tolerance_symbols import geometric_symbol
from mycad.ui.text_layout import TextLayout, layout_text

_TEXT_ID = "00000000000000000000000000000000"
_HEIGHT = 3.5
_ROW_HEIGHT = 6.0
_GAP = 0.8
_SYMBOL_WIDTH = 5.4


def datum_box_size(
    datum: DatumIdentifier, label: TextLayout, style: TextStyle
) -> tuple[float, float]:
    """Calculate the same physical datum box for paint and export."""
    scale = style.height_mm / 3.5
    if datum.layout_mode == "shared":
        size = datum.box_size_mm or datum_box_dimensions(datum.label, style)
    else:
        size = (
            max(5 * scale, label.bounds.width() + 1.6 * scale),
            max(5 * scale, label.bounds.height() + 0.8 * scale),
        )
    return (max(size), max(size)) if datum.symbol_style == "circle" else size


@dataclass(frozen=True)
class FrameCell:
    bounds: QRectF
    symbol: str = ""
    text: TextLayout | None = None
    diameter: bool = False
    modifier: str = ""
    modifier_text: TextLayout | None = None
    modifier_scale: float = 1.0


@dataclass(frozen=True)
class FrameRow:
    cells: tuple[FrameCell, ...]


@dataclass(frozen=True)
class FrameLayout:
    bounds: QRectF
    rows: tuple[FrameRow, ...]
    scale: float = 1.0

    def draw(self, painter: QPainter) -> None:
        painter.save()
        pen = QPen(painter.pen())
        scale = self.scale
        pen.setWidthF(0.18 * scale)
        painter.setPen(pen)
        for row in self.rows:
            for cell in row.cells:
                painter.drawRect(cell.bounds)
                if cell.symbol:
                    path = geometric_symbol(cell.symbol)
                    painter.save()
                    painter.translate(
                        cell.bounds.left() + 0.8 * scale, cell.bounds.top() + 1.1 * scale
                    )
                    painter.scale(3.8 * scale, 3.8 * scale)
                    scaled = QPen(painter.pen())
                    scaled.setWidthF(0.18 / 3.8)
                    painter.setPen(scaled)
                    painter.drawPath(path)
                    painter.restore()
                    continue
                x = cell.bounds.left() + _GAP * scale
                if cell.diameter:
                    diameter = QPainterPath()
                    diameter.addEllipse(
                        QRectF(
                            x + 0.2 * scale,
                            cell.bounds.top() + 1.6 * scale,
                            2.5 * scale,
                            2.5 * scale,
                        )
                    )
                    diameter.moveTo(x, cell.bounds.top() + 4.3 * scale)
                    diameter.lineTo(x + 2.9 * scale, cell.bounds.top() + 1.4 * scale)
                    painter.drawPath(diameter)
                    x += 3.3 * scale
                if cell.text is not None:
                    painter.save()
                    painter.translate(
                        x - cell.text.bounds.left(),
                        cell.bounds.center().y() - cell.text.bounds.center().y(),
                    )
                    cell.text.draw(painter)
                    painter.restore()
                    x += cell.text.bounds.width()
                if cell.modifier_text is not None:
                    x += 0.6 * scale
                    circle = QRectF(
                        x, cell.bounds.center().y() - 1.45 * scale, 2.9 * scale, 2.9 * scale
                    )
                    painter.drawEllipse(circle)
                    painter.save()
                    painter.translate(circle.center())
                    painter.scale(cell.modifier_scale, cell.modifier_scale)
                    painter.translate(-cell.modifier_text.bounds.center())
                    cell.modifier_text.draw(painter)
                    painter.restore()
        painter.restore()


def _text(value: str, manager: FontManager, style: TextStyle) -> TextLayout:
    return layout_text(DrawingText(_TEXT_ID, value, (0, 0)), style, manager)


def layout_frame(
    frame: FeatureControlFrame, manager: FontManager, style: TextStyle | None = None
) -> FrameLayout:
    """Create all cell geometry in local millimetres for paint and hit testing."""
    style = style or TextStyle()
    scale = style.height_mm / _HEIGHT
    rows: list[FrameRow] = []
    max_width = 0.0
    for index, row in enumerate(frame.rows):
        y = index * _ROW_HEIGHT * scale
        cells = [
            FrameCell(
                QRectF(0, y, _SYMBOL_WIDTH * scale, _ROW_HEIGHT * scale), symbol=row.characteristic
            )
        ]
        x = _SYMBOL_WIDTH * scale
        contents = [
            (
                "精度不足" if row.precision_insufficient else f"{row.value:.{row.precision}f}",
                row.diameter,
                row.modifier,
            )
        ]
        contents.extend((datum.label, False, datum.modifier) for datum in row.datums)
        for value, diameter, modifier in contents:
            text = _text(value, manager, style)
            mod_text = (
                _text(modifier, manager, replace(style, height_mm=2.0 * scale))
                if modifier
                else None
            )
            modifier_scale = (
                min(
                    1.0,
                    2.3 * scale / max(mod_text.bounds.width(), 1e-12),
                    2.3 * scale / max(mod_text.bounds.height(), 1e-12),
                )
                if mod_text is not None
                else 1.0
            )
            width = (
                2 * _GAP + (3.3 if diameter else 0) + (3.5 if modifier else 0)
            ) * scale + text.bounds.width()
            cells.append(
                FrameCell(
                    QRectF(x, y, width, _ROW_HEIGHT * scale),
                    text=text,
                    diameter=diameter,
                    modifier=modifier,
                    modifier_text=mod_text,
                    modifier_scale=modifier_scale,
                )
            )
            x += width
        rows.append(FrameRow(tuple(cells)))
        max_width = max(max_width, x)
    return FrameLayout(QRectF(0, 0, max_width, len(rows) * _ROW_HEIGHT * scale), tuple(rows), scale)


def legacy_frame_leader_layout(
    frame: FeatureControlFrame,
    manager: FontManager,
    style: TextStyle | None = None,
    *,
    bounds: QRectF | None = None,
) -> tuple[tuple[float, float], int] | None:
    """Calculate the visible leader anchor and clipped prefix in drawing coordinates."""
    if frame.leader_target_mm is None:
        return None
    angle = math.radians(frame.rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)

    def local(point: tuple[float, float]) -> tuple[float, float]:
        dx, dy = point[0] - frame.position_mm[0], point[1] - frame.position_mm[1]
        return cosine * dx + sine * dy, sine * dx - cosine * dy

    rect = bounds if bounds is not None else layout_frame(frame, manager, style).bounds
    vertices = tuple(
        local((frame.position_mm[0] + x, frame.position_mm[1] + y)) for x, y in frame.leader_offsets
    )
    target = frame.leader_target_mm
    if frame.surface_indication is not None:
        _, _, target = surface_indication_geometry(target, frame.surface_indication)
    path = datum_leader_path(
        (rect.left(), rect.top(), rect.right(), rect.bottom()), local(target), vertices
    )
    if not path:
        return None
    x, y = path[0]
    return (
        (
            frame.position_mm[0] + cosine * x + sine * y,
            frame.position_mm[1] + sine * x - cosine * y,
        ),
        len(vertices) + 2 - len(path),
    )


def frame_font_warning(
    frame: FeatureControlFrame,
    manager: FontManager,
    style: TextStyle | None,
    *,
    layout: FrameLayout | None = None,
) -> str:
    """Describe font substitution and missing glyphs in a frame layout."""
    if style is None:
        return f"文字样式 {frame.text_style_id} 不可用，使用默认样式显示。"
    replacement = manager.substitution(style)
    actual = layout if layout is not None else layout_frame(frame, manager, style)
    missing = "".join(
        dict.fromkeys(
            character
            for row in actual.rows
            for cell in row.cells
            for text in (cell.text, cell.modifier_text)
            if text is not None
            for character in text.missing_glyphs
        )
    )
    message = (
        f"字体 {style.font_family or style.font_file} 不可用，使用 {replacement} 显示。"
        if replacement
        else ""
    )
    return message + (f"缺少字符：{missing}。" if missing else "")
