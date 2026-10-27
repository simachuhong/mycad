# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Vector PDF from a frozen engineering scene; no canvas screenshot export."""

from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, RectangleObject, TextStringObject
from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from mycad.core.drawing_paper import paper_texts, validate_drawing_output
from mycad.core.drawing_projection import DrawingScene
from mycad.formats.drawing_export import atomic_drawing_output
from mycad.ui.drawing_render import paint_drawing, validate_paper_glyphs


def _normalize_pdf(path: Path, scene: DrawingScene) -> None:
    """Correct Qt's integer-point MediaBox and reverse-cmap text loss.

    Mark each logical painted label with its original Unicode ActualText.
    This keeps glyph rendering/font embedding intact and works in PDFium and
    Poppler, including fonts whose cmap aliases CJK characters to radicals.
    """
    writer = PdfWriter(clone_from=BytesIO(path.read_bytes()))
    writer.pdf_header = "%PDF-1.7"
    page = writer.pages[0]
    content = page.get_contents()
    if content is None:
        raise ValueError("PDF 缺少矢量内容")
    # QPainter save/translate/restore scopes bound each logical label. Font
    # fallback can split a label into several BT blocks inside that scope.
    stack: list[tuple[int, bool, bool]] = []
    scopes: list[tuple[int, int]] = []
    for index, (_, operator) in enumerate(content.operations):
        if operator == b"q":
            stack.append((index, False, False))
        elif operator == b"cm" and stack:
            start, _, text = stack[-1]
            stack[-1] = (start, True, text)
        elif operator == b"BT":
            stack = [(start, transform, True) for start, transform, _ in stack]
        elif operator == b"Q" and stack:
            start, transform, text = stack.pop()
            if transform and text:
                scopes.append((start, index))
    labels = sorted((a, b) for a, b in scopes if not any(a < c < d < b for c, d in scopes))
    texts = paper_texts(scene)
    if len(labels) != len(texts):
        raise ValueError("PDF 文字结构无法安全校正，原文件未修改")
    for (start, end), text in reversed(tuple(zip(labels, texts, strict=True))):
        content.operations.insert(end + 1, ([], b"EMC"))
        content.operations.insert(
            start,
            (
                [
                    NameObject("/Span"),
                    DictionaryObject(
                        {NameObject("/ActualText"): TextStringObject(text.text + "\n")}
                    ),
                ],
                b"BDC",
            ),
        )
    page.replace_contents(content)
    width, height = (value * 72 / 25.4 for value in scene.size_mm)
    page.add_transformation((1, 0, 0, 1, 0, height - float(page.mediabox.height)))
    page.mediabox = RectangleObject((0, 0, width, height))
    page.cropbox = RectangleObject((0, 0, width, height))
    writer.write(path)
    writer.close()


def export_drawing_pdf(scene: DrawingScene, target: Path) -> None:
    validate_drawing_output(scene)
    validate_paper_glyphs(scene)

    def write(path: Path) -> None:
        writer = QPdfWriter(str(path))
        writer.setCreator("MyCAD")
        writer.setTitle(dict(scene.title).get("名称", "工程图"))
        writer.setResolution(720)
        writer.setPageSize(
            QPageSize(
                QSizeF(*scene.size_mm),
                QPageSize.Unit.Millimeter,
                "MyCAD",
                QPageSize.SizeMatchPolicy.ExactMatch,
            )
        )
        writer.setPageMargins(QMarginsF(), QPageLayout.Unit.Millimeter)
        painter = QPainter()
        if not painter.begin(writer):
            raise OSError("无法创建 PDF 绘图设备")
        try:
            painter.scale(writer.resolution() / 25.4, writer.resolution() / 25.4)
            painter.translate(0, scene.size_mm[1])
            paint_drawing(painter, scene)
        finally:
            if not painter.end():
                raise OSError("PDF 绘图未能完整结束")
        del writer
        _normalize_pdf(path, scene)

    atomic_drawing_output(target, write)
