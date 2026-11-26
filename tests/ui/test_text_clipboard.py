# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mixed text clipboard retains geometry and protects existing styles."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.sketch import LineEntity, Sketch
from mycad.ui.drawing_text_tools import DrawingTextTools
from mycad.ui.sketch_editor import SketchCanvas


@pytest.fixture(autouse=True)
def clear_test_clipboard(qapp: QApplication) -> Iterator[None]:
    yield
    qapp.clipboard().clear()


def test_mixed_copy_retains_geometry_and_one_paste_transaction(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    text = DrawingText(uuid4().hex, "ABC", (10, 20))
    tools.sync((text,), TextStyleTable())
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    canvas.entities = [line]
    canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    assert tools.copy()
    received: list[object] = []

    def receive(
        sketch: Sketch,
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable,
        images: tuple[DrawingRaster, ...],
        dimensions: DimensionStyleTable | None,
    ) -> bool:
        received.extend((sketch, texts, styles, images, dimensions))
        return True

    tools.paste_commit = receive
    assert tools.begin_paste()
    assert tools.place_paste((20, 30))
    assert len(received) == 5
    sketch, texts = received[:2]
    assert isinstance(sketch, Sketch)
    assert isinstance(sketch.entities[0], LineEntity)
    assert sketch.entities[0].start_mm == (10, 10)
    assert isinstance(texts, tuple)
    assert isinstance(texts[0], DrawingText)
    assert texts[0].position_mm == (20, 30)


def test_mixed_copy_failure_preserves_clipboard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mycad.ui.drawing_text_tools as text_tools_module

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    text = DrawingText(uuid4().hex, "ABC", (10, 20))
    tools.sync((text,), TextStyleTable())
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    canvas.entities = [line]
    canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    QApplication.clipboard().setText("original clipboard")
    monkeypatch.setattr(text_tools_module, "_MAX_CLIPBOARD_BYTES", 100)
    assert not tools.copy()
    assert QApplication.clipboard().text() == "original clipboard"


def test_paste_remaps_case_insensitive_style_collision(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    text = DrawingText(uuid4().hex, "ABC", (0, 0))
    source = TextStyleTable((TextStyle(font_family="Font A"),))
    tools.sync((text,), source)
    tools.selected_ids = {text.text_id}
    assert tools.copy()
    target = TextStyleTable((TextStyle("target", "标准", "Font B"),), "target")
    tools.sync((), target)
    calls: list[dict[str, object]] = []
    tools.execute = lambda command, params: calls.append(params) is None
    assert tools.begin_paste()
    assert tools.place_paste((0, 0))
    assert calls
    result = TextStyleTable.from_mapping(calls[0]["styles"])
    assert result.get("target").font_family == "Font B"
    assert len(result.styles) == 2


def test_mixed_dimension_styles_reconcile_against_destination(qtbot: QtBot) -> None:
    from mycad.core.dimension_styles import DimensionStyle
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    text = DrawingText(uuid4().hex, "ABC", (10, 20))
    tools.sync((text,), TextStyleTable())
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    canvas.entities = [line]
    canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            5,
            "mm",
            driving=False,
            scale=2,
            style_name="标准",
        )
    ]
    canvas.drawing_dimension_styles = DimensionStyleTable(
        (DimensionStyle("标准", scale=2),), "标准"
    )
    canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    assert tools.copy()
    target = DimensionStyleTable((DimensionStyle("标准", scale=3),), "标准")
    canvas.drawing_dimension_styles = target
    received: list[DimensionStyleTable] = []

    def receive(
        sketch: Sketch,
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable,
        images: tuple[DrawingRaster, ...],
        dimensions: DimensionStyleTable | None,
    ) -> bool:
        assert dimensions is not None
        received.append(dimensions)
        assert sketch.constraints[0].style_name != "标准"
        return True

    tools.paste_commit = receive
    assert tools.begin_paste()
    assert tools.place_paste((20, 30))
    assert received[0].get("标准").scale == 3
    assert len(received[0].styles) == 2


def test_text_and_dimension_copy_reconciles_both_font_styles(qtbot: QtBot) -> None:
    from mycad.core.dimension_styles import DimensionStyle
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tools = DrawingTextTools(canvas)
    canvas.text_tools = tools
    text = DrawingText(uuid4().hex, "ABC", (10, 20))
    source = TextStyleTable((TextStyle(), TextStyle("font", "检验", "Font A")))
    tools.sync((text,), source)
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    canvas.entities = [line]
    canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            5,
            "mm",
            driving=False,
            style_name="尺寸",
        )
    ]
    canvas.drawing_dimension_styles = DimensionStyleTable(
        (DimensionStyle("尺寸", text_style_id="font"),), "尺寸"
    )
    canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    assert tools.copy()
    target_fonts = TextStyleTable((TextStyle(), TextStyle("font", "检验", "Font B")))
    tools.sync((), target_fonts)
    canvas.drawing_dimension_styles = DimensionStyleTable((DimensionStyle("标准"),), "标准")
    received: list[tuple[TextStyleTable, DimensionStyleTable]] = []

    def receive(
        sketch: Sketch,
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable,
        images: tuple[DrawingRaster, ...],
        dimensions: DimensionStyleTable | None,
    ) -> bool:
        assert dimensions is not None
        received.append((styles, dimensions))
        return True

    tools.paste_commit = receive
    assert tools.begin_paste() and tools.place_paste((20, 30))
    fonts, dimensions = received[0]
    copied_id = dimensions.get("尺寸").text_style_id
    assert copied_id is not None and copied_id != "font"
    assert fonts.get(copied_id).font_family == "Font A"
    assert fonts.get("font").font_family == "Font B"
