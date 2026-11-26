# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native editable text exchange keeps placement, styles and literal content."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest
from ezdxf.entities.mtext import MTextColumns

from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


class _Attributes(Protocol):
    def get(self, name: str, default: object = None) -> object: ...
    def __setattr__(self, name: str, value: object) -> None: ...
    def discard(self, name: str) -> None: ...


class _Entity(Protocol):
    dxf: _Attributes
    text: str

    def dxftype(self) -> str: ...
    def plain_text(self) -> str: ...
    def setup_columns(self, columns: MTextColumns, linked: bool = False) -> None: ...


class _Space(Protocol):
    def __iter__(self) -> Iterator[_Entity]: ...
    def add_mtext(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...
    def add_text(self, text: str, *, dxfattribs: Mapping[str, object]) -> _Entity: ...


class _Document(Protocol):
    def modelspace(self) -> _Space: ...
    def saveas(self, path: Path) -> None: ...


class _Reader(Protocol):
    def __call__(self, path: Path) -> _Document: ...


_read = cast("_Reader", vars(filemanagement)["readfile"])


def test_text_only_native_content_style_and_external_edit(tmp_path: Path) -> None:
    style = TextStyle("technical", "Technical", "DejaVu Sans", "Regular", "DejaVuSans.ttf", 4, 0.8)
    text = DrawingText(
        str(uuid4()), "孔径 25", (10, 20), style_id="technical", rotation_deg=30, align="right"
    )
    path = tmp_path / "only-text.dxf"
    report = write_sketches_dxf(
        (), path, texts=(text,), text_styles=TextStyleTable((style,), "technical")
    )
    assert report.entity_count == 1
    assert report.complete
    document = _read(path)
    native = next(iter(document.modelspace()))
    assert native.dxftype() == "TEXT"
    assert native.dxf.get("text") == "孔径 25"
    assert native.dxf.get("height") == 4
    assert native.dxf.get("width") == 0.8
    native.dxf.text = "外部修改"
    native.dxf.align_point = (40, 50, 0)
    native.dxf.height = 6
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.report.entity_count == 1
    assert imported.report.complete
    result = imported.texts[0]
    assert result.text == "外部修改"
    assert result.position_mm == (40, 50)
    assert result.height_mm == 6
    assert result.align == "right"
    assert result.rotation_deg == 30
    assert imported.text_styles is not None
    recovered_style = imported.text_styles.get(result.style_id)
    assert recovered_style.font_file == "DejaVuSans.ttf"
    assert recovered_style.font_family == "DejaVu Sans"


def test_mtext_escapes_literals_and_preserves_layout(tmp_path: Path) -> None:
    content = "中文 {A} C:\\Part %%d 50%%\n第二行 \\P"
    text = DrawingText(
        str(uuid4()),
        content,
        (-3, 8),
        kind="mtext",
        height_mm=5,
        width_factor=1.25,
        box_width_mm=40,
        line_spacing=1.3,
        rotation_deg=12,
        align="middle_center",
    )
    path = tmp_path / "multiline.dxf"
    write_sketches_dxf((), path, texts=(text,))
    native = next(iter(_read(path).modelspace()))
    assert native.dxftype() == "MTEXT"
    assert native.plain_text() == content
    imported = read_sketch_dxf(path)
    assert imported.report.complete
    result = imported.texts[0]
    assert result.text == content
    assert result.kind == "mtext"
    assert result.width_factor == 1.25
    assert result.box_width_mm == 40
    assert result.line_spacing == 1.3
    assert result.align == "middle_center"


def test_import_native_units_and_unsupported_format_warning(tmp_path: Path) -> None:
    text = DrawingText(str(uuid4()), "seed", (0, 0))
    path = tmp_path / "external.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    document.modelspace().add_mtext(
        r"{\C1;red}\Pplain",
        dxfattribs={
            "insert": (1, 2, 0),
            "char_height": 0.5,
            "width": 3,
            "rotation": 45,
            "attachment_point": 9,
        },
    )
    document.saveas(path)
    result = read_sketch_dxf(path, unit_override="inch")
    imported = result.texts[1]
    assert imported.text == "red\nplain"
    assert imported.position_mm == pytest.approx((25.4, 50.8))
    assert imported.height_mm == pytest.approx(12.7)
    assert imported.box_width_mm == pytest.approx(76.2)
    assert imported.align == "bottom_right"
    assert any("格式" in warning for warning in result.report.warnings)


@pytest.mark.parametrize(
    "align", ("left", "center", "right", "top_left", "middle_center", "bottom_right")
)
def test_single_line_alignments_roundtrip(tmp_path: Path, align: str) -> None:
    text = DrawingText.from_mapping(
        {"text_id": str(uuid4()), "text": "label", "position_mm": [7, 9], "align": align}
    )
    path = tmp_path / "alignment.dxf"
    write_sketches_dxf((), path, texts=(text,))
    result = read_sketch_dxf(path).texts[0]
    assert result.align == align
    assert result.position_mm == (7, 9)


def test_single_line_literal_percent_and_caret_roundtrip(tmp_path: Path) -> None:
    content = "literal %%d %%u 50% and ^A and ^ "
    text = DrawingText(str(uuid4()), content, (0, 0))
    path = tmp_path / "literal-text.dxf"
    write_sketches_dxf((), path, texts=(text,))
    assert read_sketch_dxf(path).texts[0].text == content


def test_native_mtext_edits_override_exported_values(tmp_path: Path) -> None:
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "edit-mtext.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.text = r"\W0.75;edited\Psecond"
    native.dxf.insert = (9, 10, 0)
    native.dxf.rotation = 90
    native.dxf.char_height = 8
    native.dxf.width = 20
    document.saveas(path)
    result = read_sketch_dxf(path).texts[0]
    assert result.text == "edited\nsecond"
    assert result.position_mm == (9, 10)
    assert result.width_factor == 0.75
    assert result.rotation_deg == 90
    assert result.box_width_mm == 20
    assert result.height_mm == 8


def test_external_mtext_mixed_width_formatting_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "mixed-width.dxf"
    write_sketches_dxf((), path, texts=(DrawingText(str(uuid4()), "seed", (0, 0)),))
    document = _read(path)
    document.modelspace().add_mtext(r"\W2;wide\W1;narrow", dxfattribs={"char_height": 3})
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts[-1].text == "widenarrow"
    assert any("格式" in warning for warning in imported.report.warnings)


def test_native_text_unicode_escapes_and_literal_backslashes(tmp_path: Path) -> None:
    content = r"literal \U+0041 and C:\Part"
    text = DrawingText(str(uuid4()), content, (0, 0))
    path = tmp_path / "unicode-text.dxf"
    write_sketches_dxf((), path, texts=(text,))
    assert read_sketch_dxf(path).texts[0].text == content
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.dxf.text = r"\U+4E2D\U+6587"
    document.saveas(path)
    assert read_sketch_dxf(path).texts[0].text == "中文"


def test_native_mtext_without_inline_width_ignores_style_width(tmp_path: Path) -> None:
    style = TextStyle(width_factor=1.7)
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "native-default-width.dxf"
    write_sketches_dxf((), path, texts=(text,), text_styles=TextStyleTable((style,)))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.text = "external replacement"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts[0].width_factor == 1.0
    assert imported.report.complete


def test_native_mtext_uniform_width_in_outer_group(tmp_path: Path) -> None:
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "grouped-width.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.text = r"{\W0.65;native\Pwrapped}"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts[0].width_factor == 0.65
    assert imported.texts[0].text == "native\nwrapped"
    assert imported.report.complete


def test_native_mtext_partial_width_group_stays_an_approximation(tmp_path: Path) -> None:
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "partial-width.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.text = r"{\W0.65;narrow}normal{end}"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts[0].width_factor == 1
    assert imported.texts[0].text == "narrownormalend"
    assert any("格式" in warning for warning in imported.report.warnings)


def test_native_mtext_missing_height_uses_entity_default(tmp_path: Path) -> None:
    from mycad.formats.text_exchange import read_texts_dxf

    style = TextStyle(height_mm=4)
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "default-height.dxf"
    write_sketches_dxf((), path, texts=(text,), text_styles=TextStyleTable((style,)))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.dxf.discard("char_height")
    texts, _styles, warnings = read_texts_dxf(document, 25.4)
    assert texts[0].height_mm == pytest.approx(2.5 * 25.4)
    assert not warnings


def test_native_mtext_at_least_spacing_reports_approximation(tmp_path: Path) -> None:
    text = DrawingText(str(uuid4()), "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "at-least-spacing.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.dxf.line_spacing_style = 1
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert any("行距" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize(
    "align",
    [
        "top_left",
        "top_center",
        "top_right",
        "middle_left",
        "middle_center",
        "middle_right",
        "bottom_left",
        "bottom_center",
        "bottom_right",
    ],
)
@pytest.mark.parametrize("kind", ["text", "mtext"])
def test_all_native_box_anchors_and_layer_roundtrip(tmp_path: Path, align: str, kind: str) -> None:
    text = DrawingText(
        uuid4().hex,
        "中文 ABC",
        (10, 20),
        kind=kind,
        align=align,
        layer_name="TEXT_LAYER",
        height_mm=4,
        rotation_deg=30,
    )
    path = tmp_path / "anchors.dxf"
    report = write_sketches_dxf((), path, texts=(text,))
    assert report.complete
    native = next(iter(_read(path).modelspace()))
    assert native.dxftype() == kind.upper()
    assert native.dxf.get("layer") == "TEXT_LAYER"
    assert native.dxf.get("rotation") == pytest.approx(30, abs=1e-8)
    result = read_sketch_dxf(path)
    assert result.report.complete
    assert result.texts[0].align == align
    assert result.texts[0].position_mm == pytest.approx((10, 20), abs=1e-8, rel=1e-9)
    assert result.texts[0].height_mm == pytest.approx(4, abs=1e-8, rel=1e-9)
    assert result.texts[0].layer_name == "TEXT_LAYER"


def test_mtext_baseline_export_discloses_bottom_alignment(tmp_path: Path) -> None:
    text = DrawingText(uuid4().hex, "Text", (3, 4), kind="mtext", align="center")
    path = tmp_path / "baseline.dxf"
    report = write_sketches_dxf((), path, texts=(text,))
    assert not report.complete
    assert any("基线" in warning and "底部" in warning for warning in report.warnings)
    assert read_sketch_dxf(path).texts[0].align == "bottom_center"


def test_native_shx_style_import_reports_unavailable_glyphs(tmp_path: Path) -> None:
    style = TextStyle("shx", "SHX", font_file="simplex.shx")
    text = DrawingText(uuid4().hex, "ABC", (0, 0), style_id="shx")
    path = tmp_path / "shx.dxf"
    exported = write_sketches_dxf(
        (), path, texts=(text,), text_styles=TextStyleTable((style,), "shx")
    )
    assert any("SHX" in warning for warning in exported.warnings)
    imported = read_sketch_dxf(path)
    assert imported.texts[0].text == "ABC"
    assert any("SHX" in warning for warning in imported.report.warnings)
    assert not imported.report.complete


def test_native_stacked_mtext_reports_approximation(tmp_path: Path) -> None:
    text = DrawingText(uuid4().hex, "before", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "stacked.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    next(iter(document.modelspace())).text = r"Diameter \S1/2;"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts
    assert any("格式" in warning for warning in imported.report.warnings)
    assert not imported.report.complete


def test_native_mtext_columns_are_reported(tmp_path: Path) -> None:
    text = DrawingText(uuid4().hex, "Two columns", (0, 0), kind="mtext", align="top_left")
    path = tmp_path / "columns.dxf"
    write_sketches_dxf((), path, texts=(text,))
    document = _read(path)
    native = next(iter(document.modelspace()))
    native.setup_columns(MTextColumns.new_static_columns(2, 20, 5, 40))
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.texts
    assert any("多栏" in warning for warning in imported.report.warnings)
    assert not imported.report.complete
