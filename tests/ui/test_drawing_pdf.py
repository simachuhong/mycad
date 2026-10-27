# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Vector PDF uses physical millimetres and embedded Chinese glyphs."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument
from pytestqt.qtbot import QtBot

from mycad.ui.drawing_pdf import export_drawing_pdf
from tests.helpers.drawing_scene import drawing_scene


def test_pdf_media_box_and_vector_content(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "drawing.pdf"
    export_drawing_pdf(drawing_scene(), path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    qtbot.waitUntil(lambda: document.pageCount() == 1)
    size = document.pagePointSize(0)
    assert (size.width(), size.height()) == pytest.approx(
        (297 * 72 / 25.4, 210 * 72 / 25.4), abs=0.15
    )
    assert b"/Subtype /Image" not in path.read_bytes()
    assert "80.00 mm" in document.getAllText(0).text()
    image = document.render(0, QSize(1485, 1050))
    assert not image.isNull()
    assert image.save(str(tmp_path / "drawing.png"))


def test_chinese_title_and_curve_output(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "chinese.pdf"
    export_drawing_pdf(drawing_scene(), path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    qtbot.waitUntil(lambda: document.pageCount() == 1)
    text = document.getAllText(0).text()
    assert "法兰工程图" in text and "MC-001" in text
    assert b"/FontFile" in path.read_bytes()


def test_invalid_pdf_preserves_existing_file(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "existing.pdf"
    path.write_bytes(b"original")
    with pytest.raises(ValueError, match="失关联"):
        export_drawing_pdf(replace(drawing_scene(), issues=("标注失关联",)), path)
    assert path.read_bytes() == b"original"


def test_export_action_uses_current_clean_scene_and_blocks_stale(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from PySide6.QtWidgets import QFileDialog

    from mycad.app import build_app, new_document
    from mycad.core.drawing import DrawingSheet, DrawingView
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 80, "size_y": 30, "size_z": 10})
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(100, 100), scale=0.5)
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(sheet))
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    bench.updates.sync(
        bench.session_id, services.kernel.drawing_source_fingerprint, {view.view_id: view.basis}
    )
    batch = bench.updates.begin()
    assert batch is not None
    bench.updates.finish(batch, (services.kernel.project_drawing(batch.requests[0]),))
    window.workspace_tabs.activate("drawing")
    target = tmp_path / "action.pdf"

    def filename(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(target), "PDF"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", filename)
    before = len(loaded.document.commands)
    bench.pdf_action.trigger()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: target.exists() and not unit.is_busy)
    assert len(loaded.document.commands) == before
    original = target.read_bytes()
    loaded.bus.execute("feature.box", {"size_x": 90, "size_y": 30, "size_z": 10})
    bench.export_to("pdf", target)
    assert not unit.is_busy
    assert target.read_bytes() == original
    assert "更新" in bench.hint.text()


@pytest.mark.parametrize("kind", ["pdf", "dxf"])
def test_writer_failure_keeps_original_and_cleans_temporary(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from mycad.formats import drawing_export

    target = tmp_path / f"drawing.{kind}"
    target.write_bytes(b"original")

    def fail(_source: object, _target: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(drawing_export.os, "replace", fail)
    exporter = export_drawing_pdf if kind == "pdf" else drawing_export.export_drawing_dxf
    with pytest.raises(OSError, match="replace failed"):
        exporter(drawing_scene(), target)
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_pdf_line_position_and_length_in_physical_millimetres(qtbot: QtBot, tmp_path: Path) -> None:
    from typing import cast

    from pypdf import PdfReader

    path = tmp_path / "position.pdf"
    export_drawing_pdf(drawing_scene(), path)
    content = PdfReader(path).pages[0].get_contents()
    assert content is not None
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list[tuple[float, ...]] = []
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    start = (0.0, 0.0)
    for operands, operator in content.operations:
        if operator == b"q":
            stack.append(matrix)
        elif operator == b"Q":
            matrix = stack.pop()
        elif operator == b"cm":
            a, b, c, d, e, f = [float(v) for v in cast("list[float]", operands)]
            aa, bb, cc, dd, ee, ff = matrix
            matrix = (
                aa * a + cc * b,
                bb * a + dd * b,
                aa * c + cc * d,
                bb * c + dd * d,
                aa * e + cc * f + ee,
                bb * e + dd * f + ff,
            )
        elif operator in (b"m", b"l"):
            x, y = [float(v) for v in cast("list[float]", operands)]
            a, b, c, d, e, f = matrix
            point = ((a * x + c * y + e) * 25.4 / 72, (b * x + d * y + f) * 25.4 / 72)
            if operator == b"m":
                start = point
            else:
                segments.append((start, point))
                start = point
    assert any(
        a == pytest.approx((60, 130), abs=0.05) and b == pytest.approx((100, 130), abs=0.05)
        for a, b in segments
    )


def test_missing_visible_glyphs_reject_pdf_and_preserve_existing_file(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF

    from mycad.ui import drawing_render

    font: QFont | None = None
    for family in QFontDatabase.families():
        candidate = QFont(family)
        candidate.setPixelSize(100)
        candidate.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        metrics = QFontMetricsF(candidate)
        if metrics.inFontUcs4(ord("A")) and not metrics.inFontUcs4(ord("法")):
            font = candidate
            break
    assert font is not None, "Regression requires a Latin font without CJK glyphs"

    def latin_only() -> QFont:
        assert font is not None
        return font

    monkeypatch.setattr(drawing_render, "paper_font", latin_only)
    path = tmp_path / "existing.pdf"
    path.write_bytes(b"valid-original")
    with pytest.raises(ValueError, match="字形|字体|缺字"):
        export_drawing_pdf(drawing_scene(), path)
    assert path.read_bytes() == b"valid-original"
    assert list(tmp_path.iterdir()) == [path]


def test_pdf_glyph_preflight_accepts_real_font_fallback(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QFont, QRawFont

    from mycad.ui import drawing_render

    font = QFont("Arial")
    font.setPixelSize(100)
    assert not QRawFont.fromFont(font).supportsCharacter("法")

    def with_fallback() -> QFont:
        return font

    monkeypatch.setattr(drawing_render, "paper_font", with_fallback)
    path = tmp_path / "fallback.pdf"
    export_drawing_pdf(drawing_scene(), path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    assert "法兰工程图" in document.getAllText(0).text()
