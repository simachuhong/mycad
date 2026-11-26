# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Physical typography uses one layout for wrapping, selection and painting."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from mycad.core.drawing_text import DrawingText, TextStyle
from mycad.ui.font_manager import FontManager
from mycad.ui.text_layout import layout_text


def test_physical_height_width_factor_and_alignment(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle(height_mm=4)
    text = DrawingText(str(uuid4()), "HHHH", (0, 0))
    normal = layout_text(text, style, manager)
    wide = layout_text(replace(text, width_factor=2), style, manager)
    assert wide.bounds.width() == pytest.approx(normal.bounds.width() * 2)
    assert wide.bounds.height() == pytest.approx(normal.bounds.height())
    assert normal.bounds.top() < -3.9
    assert normal.bounds.bottom() > 0
    center = layout_text(replace(text, align="middle_center"), style, manager)
    assert center.bounds.center().x() == pytest.approx(0)
    assert center.bounds.center().y() == pytest.approx(0)
    top = layout_text(replace(text, align="top_right"), style, manager)
    assert top.bounds.top() == pytest.approx(0)
    assert top.bounds.right() == pytest.approx(0)


def test_wrap_width_matches_scaled_drawing_and_explicit_newlines(
    qapp: QApplication, tmp_path: Path
) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle()
    text = DrawingText(str(uuid4()), "one two three four five", (0, 0), kind="mtext")
    unwrapped = layout_text(text, style, manager)
    wrapped = layout_text(replace(text, box_width_mm=12), style, manager)
    wide = layout_text(replace(text, box_width_mm=12, width_factor=2), style, manager)
    assert wrapped.bounds.width() == pytest.approx(12)
    assert wrapped.bounds.height() > unwrapped.bounds.height()
    assert wide.bounds.height() > wrapped.bounds.height()
    newlines = layout_text(replace(text, text="one\n\nthree"), style, manager)
    assert newlines.bounds.height() > unwrapped.bounds.height() * 2


def test_draw_occupies_reported_bounds_and_detects_missing_glyphs(
    qapp: QApplication, tmp_path: Path
) -> None:
    manager = FontManager(tmp_path)
    text = DrawingText(str(uuid4()), "Hello\U0010ffff", (0, 0), align="top_left")
    layout = layout_text(text, TextStyle(height_mm=4), manager)
    assert layout.missing_glyphs == "\U0010ffff"
    with pytest.raises(ValueError, match="缺少字形"):
        layout.glyph_paths()
    image = QImage(800, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    painter.translate(20, 20)
    painter.scale(20, 20)
    layout.draw(painter)
    painter.end()
    occupied = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y) != QColor(Qt.GlobalColor.white)
    ]
    assert occupied
    assert min(x for x, _ in occupied) >= 19
    assert min(y for _, y in occupied) >= 19
    assert max(x for x, _ in occupied) <= 21 + layout.bounds.right() * 20
    assert max(y for _, y in occupied) <= 21 + layout.bounds.bottom() * 20


def test_italic_overhang_is_in_hit_bounds(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle(font_family="DejaVu Serif", font_style="Italic", height_mm=4)
    if "DejaVu Serif" not in manager.families():
        pytest.skip("Italic font fixture unavailable")
    text = DrawingText(str(uuid4()), "jf", (0, 0), align="top_left")
    layout = layout_text(text, style, manager)
    image = QImage(800, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    painter.translate(100, 20)
    painter.scale(20, 20)
    layout.draw(painter)
    painter.end()
    occupied = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y) != QColor(Qt.GlobalColor.white)
    ]
    assert occupied
    assert min(x for x, _ in occupied) >= 99 + layout.bounds.left() * 20
    assert max(x for x, _ in occupied) <= 101 + layout.bounds.right() * 20


def test_mtext_line_spacing_uses_dxf_cap_height_leading(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path)
    style = TextStyle(height_mm=4)
    text = DrawingText(str(uuid4()), "ABC", (0, 0), kind="mtext", align="top_left")
    first = layout_text(text, style, manager)
    second = layout_text(replace(text, text="ABC\nABC"), style, manager)
    assert second.bounds.height() - first.bounds.height() == pytest.approx(4 * 5 / 3)
    spaced = layout_text(replace(text, text="ABC\nABC", line_spacing=1.5), style, manager)
    assert spaced.bounds.height() - first.bounds.height() == pytest.approx(4 * 5 / 3 * 1.5)


@pytest.mark.parametrize("ratio", [1, 2])
def test_extreme_text_respects_painter_window_and_viewport(
    qapp: QApplication, tmp_path: Path, ratio: int
) -> None:
    manager = FontManager(tmp_path)
    text = DrawingText(str(uuid4()), "I", (0, 0), height_mm=1e200, align="center")
    layout = layout_text(text, TextStyle(), manager)
    image = QImage(400 * ratio, 200 * ratio, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    painter.setViewport(80, 20, 200, 100)
    painter.setWindow(0, 0, 100, 100)
    painter.translate(50, 50)
    layout.draw(painter)
    painter.end()
    assert image.pixelColor(180 * ratio, 55 * ratio) == QColor(Qt.GlobalColor.black)
    assert image.pixelColor(180 * ratio, 80 * ratio) == QColor(Qt.GlobalColor.white)


def test_extreme_text_preserves_existing_painter_clip(qapp: QApplication, tmp_path: Path) -> None:
    manager = FontManager(tmp_path)
    text = DrawingText(str(uuid4()), "I", (0, 0), height_mm=1e200, align="center")
    layout = layout_text(text, TextStyle(), manager)
    image = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    painter.setViewport(80, 20, 200, 100)
    painter.setWindow(0, 0, 100, 100)
    painter.translate(50, 50)
    painter.setClipRect(-10, -40, 20, 20)
    layout.draw(painter)
    painter.end()
    assert image.pixelColor(180, 40) == QColor(Qt.GlobalColor.black)
    assert image.pixelColor(220, 40) == QColor(Qt.GlobalColor.white)


@pytest.mark.parametrize("value", ["O0.1", "A\u0301fi", "سلام", "A基准"])
def test_shaped_glyph_paths_follow_painted_text_and_keep_holes(
    qapp: QApplication, tmp_path: Path, value: str
) -> None:
    manager = FontManager(tmp_path)
    if "DejaVu Sans" not in manager.families():
        pytest.skip("DejaVu Sans unavailable")
    text = DrawingText(str(uuid4()), value, (0, 0), align="top_left", width_factor=1.4)
    layout = layout_text(text, TextStyle(font_family="DejaVu Sans", height_mm=4), manager)
    if layout.missing_glyphs:
        pytest.skip("fixture glyphs unavailable on this system")
    paths = layout.glyph_paths()
    assert paths
    if value == "O0.1":
        assert len(paths) == 4
        first = paths[0]
        assert not first.contains(first.boundingRect().center())

    images: list[QImage] = []
    for draw_paths in (False, True):
        image = QImage(500, 200, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        painter.setPen(Qt.GlobalColor.black)
        painter.translate(20, 20)
        painter.scale(20, 20)
        if draw_paths:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.black)
            for path in paths:
                painter.drawPath(path)
        else:
            layout.draw(painter)
        painter.end()
        images.append(image)
    occupied = [
        {
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y) != QColor(Qt.GlobalColor.white)
        }
        for image in images
    ]
    assert len(occupied[0] & occupied[1]) / len(occupied[0] | occupied[1]) > 0.85
