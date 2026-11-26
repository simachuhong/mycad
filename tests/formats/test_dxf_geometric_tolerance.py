# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric tolerance frames use editable native DXF entities."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import ezdxf.filemanagement as filemanagement
import pytest

from mycad.core.geometric_tolerance import DatumReference, FeatureControlFrame, ToleranceRow
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize("value", [0.001, 1e-10])
def test_frame_with_hidden_nonzero_tolerance_does_not_overwrite_export(
    tmp_path: Path, value: float
) -> None:
    from dataclasses import replace

    from mycad.core.exceptions import ValidationError

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", value, 2),), (10, 20))
    path = tmp_path / "frame-precision.dxf"
    path.write_bytes(b"existing drawing")
    with pytest.raises(ValidationError, match="精度"):
        write_sketches_dxf((), path, tolerance_frames=(frame,))
    assert path.read_bytes() == b"existing drawing"
    if value == 0.001:
        corrected = replace(frame, rows=(replace(frame.rows[0], precision=3),))
        write_sketches_dxf((), path, tolerance_frames=(corrected,))
        assert read_sketch_dxf(path).tolerance_frames == (corrected,)


@pytest.mark.parametrize("last_length", [68, 69])
def test_frame_dxf_content_respects_single_group_length(tmp_path: Path, last_length: int) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.formats.geometric_tolerance_codec import encode_rows

    row = ToleranceRow(
        "position",
        0.1,
        1,
        datums=(
            DatumReference("a" * 80),
            DatumReference("b" * 80),
            DatumReference("c" * last_length),
        ),
    )
    assert len(encode_rows((row,)).encode("utf-8")) == 187 + last_length
    frame = FeatureControlFrame(uuid4().hex, (row,), (0, 0))
    path = tmp_path / "frame-length.dxf"
    path.write_bytes(b"existing drawing")
    if last_length == 68:
        write_sketches_dxf((), path, tolerance_frames=(frame,))
        assert read_sketch_dxf(path).tolerance_frames == (frame,)
    else:
        with pytest.raises(ValidationError, match="255"):
            write_sketches_dxf((), path, tolerance_frames=(frame,))
        assert path.read_bytes() == b"existing drawing"


def test_frame_unicode_length_uses_utf8_bytes(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.formats.geometric_tolerance_codec import encode_rows

    row = ToleranceRow(
        "position",
        0.1,
        1,
        datums=(DatumReference("甲" * 40), DatumReference("乙" * 40), DatumReference("丙" * 40)),
    )
    encoded = encode_rows((row,))
    assert len(encoded) < 255 < len(encoded.encode("utf-8"))
    frame = FeatureControlFrame(uuid4().hex, (row,), (0, 0))
    with pytest.raises(ValidationError, match="255"):
        write_sketches_dxf((), tmp_path / "unicode-long.dxf", tolerance_frames=(frame,))


@pytest.mark.parametrize("value", ["-0.00", ".05"])
def test_unimportable_frame_does_not_claim_value_was_imported(tmp_path: Path, value: str) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE",
        {"content": r"{\Fgdt;c}%%v" + value, "insert": (0, 0, 1)},
    )
    path = tmp_path / "off-plane.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.tolerance_frames
    assert any("无法导入" in warning for warning in imported.report.warnings)
    assert not any("已按" in warning and "导入" in warning for warning in imported.report.warnings)


def test_legacy_negative_zero_frame_restores_id_and_datum_link(tmp_path: Path) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.0, 2, True, "M", (DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (0, 0))
    path = tmp_path / "legacy-negative-zero.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads("".join(t.value for t in entity.get_xdata("MYCAD_FCF") if t.code == 1000))
    entity.dxf.content = entity.dxf.content.replace("0.00", "-0.00")
    payload["content"] = entity.dxf.content
    payload["frame"]["rows"][0]["value"] = -0.0
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata("MYCAD_FCF", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames == (frame,)
    assert imported.datum_identifiers == (datum,)
    assert not any("需重建" in warning for warning in imported.report.warnings)
    assert any("负零" in warning and "导入" in warning for warning in imported.report.warnings)


def test_negative_zero_frame_dxf_roundtrip(tmp_path: Path) -> None:
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", -0.0, 2),), (0, 0))
    path = tmp_path / "negative-zero.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames == (frame,)
    assert not any("无法导入" in warning for warning in imported.report.warnings)


def test_import_long_frame_reports_exchange_risk_and_preserves_rows(tmp_path: Path) -> None:
    from mycad.formats.geometric_tolerance_codec import encode_rows

    rows = tuple(ToleranceRow("flatness", 0.1, 1) for _ in range(16))
    content = encode_rows(rows)
    assert len(content.encode("utf-8")) > 255
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity("TOLERANCE", {"insert": (0, 0, 0), "content": content})
    path = tmp_path / "long-external.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames[0].rows == rows
    assert any("255" in message and "长度" in message for message in imported.report.warnings)


def test_unparseable_long_frame_does_not_claim_content_preserved(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (0, 0, 0), "content": "unsupported" * 30}
    )
    path = tmp_path / "unparseable-long.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.tolerance_frames
    assert any("无法导入" in message for message in imported.report.warnings)
    assert any("255" in message for message in imported.report.warnings)
    assert not any("已保留内容" in message for message in imported.report.warnings)


@pytest.mark.parametrize(
    ("unit", "text", "expected", "precision", "warning"),
    [
        (13, "0.001", 1e-6, 6, False),
        (13, "0.00000001", 1e-11, 8, True),
        (1, "0.01", 0.254, 3, False),
        (2, "0.01", 3.048, 3, False),
        (9, "0.01", 0.000254, 6, False),
        (5, "0.01", 0.1, 2, False),
        (6, "0.01", 10.0, 2, False),
        (4, "0.01", 0.01, 2, False),
    ],
)
def test_scaled_external_frame_preserves_available_precision(
    tmp_path: Path, unit: int, text: str, expected: float, precision: int, warning: bool
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = unit
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (0, 0, 0), "content": r"{\Fgdt;c}%%v" + text + "%%v%%v%%v%%v"}
    )
    path = tmp_path / "micron-frame.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    row = result.tolerance_frames[0].rows[0]
    assert row.value == pytest.approx(expected, abs=1e-20)
    assert row.precision == precision and row.precision_insufficient is warning
    assert any("精度不足" in message for message in result.report.warnings) is warning
    if not warning:
        target = tmp_path / "converted.dxf"
        write_sketches_dxf(
            (), target, tolerance_frames=result.tolerance_frames, text_styles=result.text_styles
        )
        assert read_sketch_dxf(target).tolerance_frames[0].rows == (row,)


def test_explicit_unit_override_preserves_frame_precision(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (0, 0, 0), "content": r"{\Fgdt;c}%%v0.001%%v%%v%%v%%v"}
    )
    path = tmp_path / "frame-override.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path, unit_override="micron")
    row = result.tolerance_frames[0].rows[0]
    assert row.value == pytest.approx(1e-6) and row.precision == 6
    assert not row.precision_insufficient


def test_legacy_frame_preserves_hidden_exact_tolerance_and_reports_it(tmp_path: Path) -> None:
    import json

    zero = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0, 2),), (10, 20))
    path = tmp_path / "legacy-hidden-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(zero,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads(
        "".join(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    )
    payload["frame"]["rows"][0]["value"] = 1e-10
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata("MYCAD_FCF", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].frame_id == zero.frame_id
    assert result.tolerance_frames[0].rows[0].value == pytest.approx(1e-10, abs=1e-20)
    assert any("精度不足" in warning for warning in result.report.warnings)


def test_native_frame_multiline_roundtrip_and_external_edit(tmp_path: Path) -> None:
    rows = (
        ToleranceRow("position", 0.05, 2, True, "M", (DatumReference("A"),)),
        ToleranceRow("flatness", 0.1, 1),
    )
    frame = FeatureControlFrame(uuid4().hex, rows, (10, 20), 30)
    path = tmp_path / "frame.dxf"
    report = write_sketches_dxf((), path, tolerance_frames=(frame,))
    assert any("LibreCAD" in warning and "不显示" in warning for warning in report.warnings)
    reader = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = reader(path)
    entity = next(item for item in document.modelspace() if item.dxftype() == "TOLERANCE")
    assert "^J" in entity.dxf.content
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames == (frame,)
    entity.dxf.content = entity.dxf.content.replace("0.05", "0.10")
    document.saveas(path)
    changed = read_sketch_dxf(path).tolerance_frames[0]
    assert changed.rows[0].value == 0.1
    assert changed.rows[1] == rows[1]


def test_external_frame_without_mycad_metadata_is_editable(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (7, 8, 0), "content": r"{\Fgdt;j}%%v{\Fgdt;n}0.05%%v%%vA%%v%%v"}
    )
    target = tmp_path / "external.dxf"
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert len(imported.tolerance_frames) == 1
    frame = imported.tolerance_frames[0]
    assert frame.position_mm == (7, 8)
    assert frame.rows == (ToleranceRow("position", 0.05, 2, True, datums=(DatumReference("A"),)),)


@pytest.mark.parametrize("diameter", [False, True])
def test_external_frame_with_suppressed_leading_zero_imports(
    tmp_path: Path, diameter: bool
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE",
        {
            "insert": (7, 8, 0),
            "content": r"{\Fgdt;j}%%v" + (r"{\fGDT;n}" if diameter else "") + ".0500%%v%%vA",
        },
    )
    target = tmp_path / "external-no-leading-zero.dxf"
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.tolerance_frames[0].rows == (
        ToleranceRow("position", 0.05, 4, diameter, datums=(DatumReference("A"),)),
    )
    assert any("前导零" in warning for warning in imported.report.warnings)


def test_external_standard_dimstyle_preserves_frame_font_and_height(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    font = document.styles.new(
        "ExternalWide", dxfattribs={"font": "DejaVuSerif.ttf", "width": 1.25}
    )
    font.set_extended_font_data("DejaVu Serif")
    dimstyle = document.dimstyles.get("Standard")
    dimstyle.dxf.dimtxt = 6
    dimstyle.dxf.dimscale = 2
    dimstyle.dxf.dimtxsty = "ExternalWide"
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (7, 8, 0), "content": r"{\Fgdt;j}%%v0.05%%v%%vA%%v%%v"}
    )
    target = tmp_path / "external-standard.dxf"
    document.saveas(target)
    imported = read_sketch_dxf(target)
    frame = imported.tolerance_frames[0]
    assert imported.text_styles is not None and frame.text_style_id is not None
    restored = imported.text_styles.get(frame.text_style_id)
    assert restored.height_mm == 12
    assert restored.width_factor == pytest.approx(1.25)
    assert restored.font_family == "DejaVu Serif"


def test_frame_style_name_collision_uses_native_font_without_overwriting_text(
    tmp_path: Path,
) -> None:
    import json

    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable

    frame_style = TextStyle("frame-font", "Inspect", font_file="arial.ttf")
    text_style = TextStyle("text-font", "Collision", font_file="times.ttf")
    text = DrawingText(uuid4().hex, "A", (0, 0), style_id=text_style.style_id)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), text_style_id=frame_style.style_id
    )
    path = tmp_path / "style-collision.dxf"
    write_sketches_dxf(
        (),
        path,
        texts=(text,),
        tolerance_frames=(frame,),
        text_styles=TextStyleTable((frame_style, text_style), frame_style.style_id),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads(
        "".join(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    )
    payload["explicit_font"]["source"]["name"] = text_style.name
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata("MYCAD_FCF", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.text_styles is not None and result.tolerance_frames[0].text_style_id is not None
    assert result.text_styles.get(result.texts[0].style_id).font_file == "times.ttf"
    assert result.text_styles.get(result.tolerance_frames[0].text_style_id).font_file == "arial.ttf"
    assert any("样式" in warning and "冲突" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("oversized", [False, True])
def test_invalid_compressed_frame_metadata_falls_back_to_native(
    tmp_path: Path, oversized: bool
) -> None:
    import base64
    import zlib

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0))
    path = tmp_path / "invalid-compressed.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    content = (
        base64.b64encode(zlib.compress(b"x" * (1024 * 1024 + 1))).decode() if oversized else "!"
    )
    entity.set_xdata(
        "MYCAD_FCF",
        [(1000, "Z1"), *[(1000, content[i : i + 240]) for i in range(0, len(content), 240)]],
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.tolerance_frames) == 1
    assert result.tolerance_frames[0].rows == frame.rows
    assert result.tolerance_frames[0].frame_id != frame.frame_id
    assert any("元数据无效" in warning for warning in result.report.warnings)


def test_large_frame_metadata_fits_xdata_budget_and_roundtrips(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    char = "𠀀"
    style = TextStyle(char * 80, char * 500, char * 63, "Bold", char * 63)
    row = ToleranceRow(
        "position", 0.1, 1, datums=(DatumReference("A"), DatumReference("B"), DatumReference("C"))
    )
    frame = FeatureControlFrame(uuid4().hex, (row,) * 8, (0, 0), text_style_id=style.style_id)
    path = tmp_path / "large-metadata.dxf"
    report = write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("TOLERANCE")[0]
    assert len(native.dxf.content.encode("utf-8")) <= 255
    tags = native.get_xdata("MYCAD_FCF")
    assert tags[0].value == "Z1"
    assert sum(len(str(tag.value).encode("utf-8")) + 4 for tag in tags) <= 14 * 1024
    assert any("压缩" in warning and "旧版" in warning for warning in report.warnings)
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames == (frame,)
    assert imported.text_styles is not None and imported.text_styles.get(style.style_id) == style


def test_long_unicode_frame_style_name_uses_valid_dxf_name_and_roundtrips(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    style = TextStyle("long-style", "基" * 100, font_file="arial.ttf")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), text_style_id=style.style_id
    )
    path = tmp_path / "long-style-name.dxf"
    report = write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("TOLERANCE")[0]
    native_name = document.dimstyles.get(native.dxf.dimstyle).dxf.dimtxsty
    assert len(native_name.encode("utf-8")) <= 255
    assert any("名称" in warning for warning in report.warnings)
    result = read_sketch_dxf(path)
    assert (
        result.text_styles is not None
        and result.tolerance_frames[0].text_style_id == style.style_id
    )
    assert result.text_styles.get(style.style_id) == style


def test_long_sanitized_style_name_collisions_remain_distinct(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    first = TextStyle("first", "A" * 249 + "?", font_file="arial.ttf")
    second = TextStyle("second", "A" * 249 + "*", font_file="arial.ttf")
    rows = (ToleranceRow("flatness", 0.1, 1),)
    frames = (
        FeatureControlFrame(uuid4().hex, rows, (0, 0), text_style_id=first.style_id),
        FeatureControlFrame(uuid4().hex, rows, (0, 10), text_style_id=second.style_id),
    )
    path = tmp_path / "long-style-collisions.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=frames,
        text_styles=TextStyleTable((first, second), first.style_id),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native_names = [
        document.dimstyles.get(entity.dxf.dimstyle).dxf.dimtxsty
        for entity in document.modelspace().query("TOLERANCE")
    ]
    assert len(set(native_names)) == 2
    assert all(len(name.encode("utf-8")) <= 255 for name in native_names)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == frames
    assert result.text_styles is not None
    assert result.text_styles.get(first.style_id) == first
    assert result.text_styles.get(second.style_id) == second


@pytest.mark.parametrize("field", ["font_file", "font_family"])
def test_overlong_frame_font_field_does_not_overwrite_dxf(tmp_path: Path, field: str) -> None:
    from dataclasses import replace

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.exceptions import ValidationError

    style = replace(TextStyle("long-font", "Long font"), **{field: "字" * 86})
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), text_style_id=style.style_id
    )
    path = tmp_path / "long-font.dxf"
    path.write_bytes(b"existing drawing")
    with pytest.raises(ValidationError, match="255"):
        write_sketches_dxf(
            (),
            path,
            tolerance_frames=(frame,),
            text_styles=TextStyleTable((style,), style.style_id),
        )
    assert path.read_bytes() == b"existing drawing"


@pytest.mark.parametrize("field", ["font_file", "font_family"])
def test_frame_font_field_accepts_255_utf8_bytes(tmp_path: Path, field: str) -> None:
    from dataclasses import replace

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    style = replace(TextStyle("long-font", "Long font"), **{field: "字" * 85})
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), text_style_id=style.style_id
    )
    path = tmp_path / "font-boundary.dxf"
    write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    result = read_sketch_dxf(path)
    assert result.text_styles is not None
    assert result.text_styles.get(style.style_id) == style


def test_frame_and_text_keep_shared_style_after_dxf_import(tmp_path: Path) -> None:
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable

    style = TextStyle("shared-font", "检验字体", font_file="arial.ttf", height_mm=7)
    text = DrawingText(uuid4().hex, "A", (0, 0), style_id=style.style_id)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), text_style_id=style.style_id
    )
    path = tmp_path / "shared-style.dxf"
    write_sketches_dxf(
        (),
        path,
        texts=(text,),
        tolerance_frames=(frame,),
        text_styles=TextStyleTable((style,), style.style_id),
    )
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].text_style_id == result.texts[0].style_id


def test_frame_text_style_identity_survives_repeated_dxf_roundtrips(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    style = TextStyle(
        "inspect-font", "检验字体", font_file="arial.ttf", height_mm=7, width_factor=1.25
    )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), text_style_id=style.style_id
    )
    table = TextStyleTable((style,), style.style_id)
    for index in range(2):
        path = tmp_path / f"styled-{index}.dxf"
        write_sketches_dxf((), path, tolerance_frames=(frame,), text_styles=table)
        result = read_sketch_dxf(path)
        frame = result.tolerance_frames[0]
        assert result.text_styles is not None
        table = result.text_styles
        assert frame.text_style_id == style.style_id
        assert table.get(style.style_id) == style


@pytest.mark.parametrize("invalid_snapshot", [False, True])
def test_tampered_frame_style_snapshot_cannot_override_native_font(
    tmp_path: Path, invalid_snapshot: bool
) -> None:
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable

    style = TextStyle("safe-font", "Inspect", font_file="arial.ttf")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), text_style_id=style.style_id
    )
    path = tmp_path / "tampered-font.dxf"
    write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads(
        "".join(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    )
    if invalid_snapshot:
        payload["explicit_font"] = "invalid"
    else:
        payload["explicit_font"]["source"]["font_file"] = "wrong.ttf"
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata("MYCAD_FCF", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.text_styles is not None and result.tolerance_frames[0].text_style_id is not None
    restored = result.text_styles.get(result.tolerance_frames[0].text_style_id)
    assert restored.font_file == "arial.ttf"
    assert restored.style_id != style.style_id
    assert any("快照无效" in warning for warning in result.report.warnings) == invalid_snapshot
    if not invalid_snapshot:
        assert any("快照与原生样式不一致" in warning for warning in result.report.warnings)


def test_frame_text_style_exports_native_dimstyle_and_reads_external_edits(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    style = TextStyle(style_id="frame-font", name="检验字体", height_mm=7, width_factor=1.25)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), text_style_id=style.style_id
    )
    path = tmp_path / "frame-style.dxf"
    write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = next(item for item in document.modelspace() if item.dxftype() == "TOLERANCE")
    native_style = document.dimstyles.get(native.dxf.dimstyle)
    assert native_style.dxf.dimtxt == 7
    assert document.styles.get(native_style.dxf.dimtxsty).dxf.width == pytest.approx(1.25)
    imported = read_sketch_dxf(path)
    imported_frame = imported.tolerance_frames[0]
    assert imported_frame.text_style_id is not None and imported.text_styles is not None
    restored = imported.text_styles.get(imported_frame.text_style_id)
    assert restored.height_mm == 7 and restored.width_factor == pytest.approx(1.25)
    native_style.dxf.dimtxt = 5
    document.styles.get(native_style.dxf.dimtxsty).dxf.width = 0.8
    document.saveas(path)
    changed = read_sketch_dxf(path)
    assert changed.text_styles is not None and changed.tolerance_frames[0].text_style_id is not None
    updated = changed.text_styles.get(changed.tolerance_frames[0].text_style_id)
    assert updated.height_mm == 5 and updated.width_factor == pytest.approx(0.8)
    assert updated.style_id != style.style_id
    assert any("快照与原生样式不一致" in warning for warning in changed.report.warnings)


def test_default_frame_native_height_and_external_style_edits(tmp_path: Path) -> None:
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2))
    path = tmp_path / "default-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = next(item for item in document.modelspace() if item.dxftype() == "TOLERANCE")
    dimstyle = document.dimstyles.get(native.dxf.dimstyle)
    assert dimstyle.dxf.dimtxt * dimstyle.dxf.dimscale == pytest.approx(3.5)
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames == (frame,)
    dimstyle.dxf.dimtxt = 5
    document.styles.get(dimstyle.dxf.dimtxsty).dxf.width = 0.8
    document.saveas(path)
    changed = read_sketch_dxf(path)
    frame_style_id = changed.tolerance_frames[0].text_style_id
    assert changed.text_styles is not None and frame_style_id is not None
    assert changed.text_styles.get(frame_style_id).height_mm == pytest.approx(5)
    assert changed.text_styles.get(frame_style_id).width_factor == pytest.approx(0.8)
    assert expand_tolerances_for_preview(document) == (1, 0)
    graphic_text = next(item for item in document.modelspace() if item.dxftype() == "TEXT")
    assert graphic_text.dxf.height == pytest.approx(5)
    assert graphic_text.dxf.width == pytest.approx(0.8)


def test_frame_graphic_expansion_respects_native_text_style(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    style = TextStyle(style_id="frame-font", name="检验字体", height_mm=7, width_factor=1.25)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), text_style_id=style.style_id
    )
    path = tmp_path / "graphics.dxf"
    write_sketches_dxf(
        (), path, tolerance_frames=(frame,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = next(item for item in document.modelspace() if item.dxftype() == "TOLERANCE")
    font_name = document.dimstyles.get(native.dxf.dimstyle).dxf.dimtxsty
    assert expand_tolerances_for_preview(document) == (1, 0)
    text = next(item for item in document.modelspace() if item.dxftype() == "TEXT")
    assert text.dxf.height == 7
    assert text.dxf.width == pytest.approx(1.25)
    assert text.dxf.style == font_name


def test_unicode_datum_reference_roundtrips_through_dxf(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "基准甲", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("基准甲", datum.datum_id),)),),
        (10, 10),
    )
    target = tmp_path / "unicode-datum.dxf"
    write_sketches_dxf((), target, tolerance_frames=(frame,), datum_identifiers=(datum,))
    imported = read_sketch_dxf(target)
    assert imported.datum_identifiers == (datum,)
    assert imported.tolerance_frames == (frame,)


def test_frame_only_export_keeps_custom_layer_name(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2), layer_name="公差层"
    )
    path = tmp_path / "custom-layer.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames[0].layer_name == "公差层"


@pytest.mark.parametrize("attributes", [{"insert": (7, 8, 4)}, {"extrusion": (0, 1, 0)}])
def test_nonplanar_external_frame_is_reported_not_flattened(
    tmp_path: Path, attributes: dict[str, object]
) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE", {"content": r"{\Fgdt;c}%%v0.1%%v%%v%%v%%v", **attributes}
    )
    target = tmp_path / "nonplanar.dxf"
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert not imported.tolerance_frames
    assert any("TOLERANCE" in warning for warning in imported.report.warnings)


def test_datum_block_roundtrip_respects_external_translation(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "datum.dxf"
    report = write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert any("图形块" in warning for warning in report.warnings)
    reader = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = reader(path)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    insert.dxf.insert = (12, 23, 0)
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.datum_identifiers) == 1
    assert imported.datum_identifiers[0].position_mm == (12, 23)
    assert imported.datum_identifiers[0].target_mm == (12, 18)


def test_styled_datum_dxf_roundtrip_and_external_font_edit(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A%^", (10, 20), (10, 15), text_style_id="datum-font")
    target = tmp_path / "datum.dxf"
    write_sketches_dxf(
        (), target, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), "datum-font")
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    texts = [item for item in document.blocks.get(insert.dxf.name) if item.dxftype() == "TEXT"]
    assert texts and all(item.dxf.height == 7 and item.dxf.width == 1.5 for item in texts)
    assert all(item.dxf.style != "Standard" for item in texts)
    imported = read_sketch_dxf(target)
    assert imported.text_styles is not None
    restored = imported.datum_identifiers[0]
    assert restored.label == datum.label and restored.text_style_id is not None
    restored_style = imported.text_styles.get(restored.text_style_id)
    assert restored_style.height_mm == 7 and restored_style.width_factor == 1.5
    assert restored_style.font_family == "DejaVu Sans"
    document.styles.get(texts[0].dxf.style).set_extended_font_data("DejaVu Serif")
    document.saveas(target)
    changed = read_sketch_dxf(target)
    assert (
        changed.text_styles is not None and changed.datum_identifiers[0].text_style_id is not None
    )
    assert (
        changed.text_styles.get(changed.datum_identifiers[0].text_style_id).font_family
        == "DejaVu Serif"
    )
    assert any("样式快照" in warning and "不一致" in warning for warning in changed.report.warnings)


def test_standalone_datum_restores_original_text_style_identity(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id=style.style_id)
    path = tmp_path / "datum-style.dxf"
    write_sketches_dxf(
        (), path, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), style.style_id)
    )
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].text_style_id == style.style_id
    assert imported.text_styles is not None and imported.text_styles.get(style.style_id) == style


@pytest.mark.parametrize("kind", ["frame", "datum"])
@pytest.mark.parametrize("edited", [False, True])
def test_legacy_unicode_font_snapshot_preserves_identity_only_when_native_matches(
    tmp_path: Path, kind: str, edited: bool
) -> None:
    import hashlib
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    style = TextStyle("unicode-font", "Straße", "DejaVu Sans", height_mm=7)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (10, 10), text_style_id=style.style_id
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (16, 0), text_style_id=style.style_id)
    path = tmp_path / f"legacy-{kind}-style.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,) if kind == "frame" else (),
        datum_identifiers=(datum,) if kind == "datum" else (),
        text_styles=TextStyleTable((style,), style.style_id),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = next(
        item
        for item in document.modelspace()
        if item.dxftype() == ("TOLERANCE" if kind == "frame" else "INSERT")
    )
    appid = "MYCAD_FCF" if kind == "frame" else "MYCAD_DATUM"
    values = tuple(tag.value for tag in entity.get_xdata(appid) if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    snapshot = payload["explicit_font" if kind == "frame" else "text_style_snapshot"]["native"]
    snapshot["style_id"] = "dxf_" + hashlib.sha256(style.name.casefold().encode()).hexdigest()[:24]
    entity.set_xdata(
        appid, [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    if edited:
        document.styles.get(style.name).set_extended_font_data("DejaVu Serif")
    document.saveas(path)

    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0] if kind == "frame" else result.datum_identifiers[0]
    assert restored.text_style_id is not None and result.text_styles is not None
    if edited:
        assert restored.text_style_id != style.style_id
        assert result.text_styles.get(restored.text_style_id).font_family == "DejaVu Serif"
        assert any(
            "样式快照" in warning and "不一致" in warning for warning in result.report.warnings
        )
    else:
        assert restored.text_style_id == style.style_id
        assert result.text_styles.get(style.style_id) == style


def test_cadcraft_resaved_datum_style_keeps_native_font_with_warning() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-datum-style-snapshot.dxf"
    imported = read_sketch_dxf(path)
    datum = imported.datum_identifiers[0]
    assert datum.datum_id == "dddddddddddddddddddddddddddddddd"
    assert datum.text_style_id is not None and datum.text_style_id != "wide"
    assert imported.text_styles is not None
    style = imported.text_styles.get(datum.text_style_id)
    assert style.font_family == "DejaVu Sans"
    assert style.height_mm == 5.5 and style.width_factor == 1.8
    assert any(
        "样式快照" in warning and "不一致" in warning for warning in imported.report.warnings
    )


@pytest.mark.parametrize("collision", ["id", "name"])
def test_datum_import_does_not_reuse_colliding_generated_style_id(
    tmp_path: Path, collision: str
) -> None:
    import hashlib
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_datum import read_datum_text_style
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    style = TextStyle("datum-font", "基准字体", "DejaVu Serif", height_mm=7)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id=style.style_id)
    path = tmp_path / "collision.dxf"
    write_sketches_dxf(
        (), path, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    native = read_datum_text_style(document, insert, 1.0)
    fingerprint = hashlib.sha256(repr(native).encode()).hexdigest()[:20]
    existing = TextStyle(
        "dxf_datum_" + fingerprint if collision == "id" else "existing-font",
        "已有样式" if collision == "id" else f"基准 {native.name[:48]} {fingerprint[:8]}",
        "DejaVu Sans",
    )
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0), text_style_id=existing.style_id
    )
    write_sketches_dxf(
        (),
        path,
        datum_identifiers=(datum,),
        tolerance_frames=(frame,),
        text_styles=TextStyleTable((style, existing), existing.style_id),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    del payload["text_style_snapshot"]
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.text_styles is not None
    assert result.tolerance_frames[0].text_style_id == existing.style_id
    assert result.text_styles.get(existing.style_id) == existing
    datum_style_id = result.datum_identifiers[0].text_style_id
    assert datum_style_id is not None and datum_style_id != existing.style_id
    assert result.text_styles.get(datum_style_id).font_family == "DejaVu Serif"


@pytest.mark.parametrize("change", ["missing", "null", "source", "native"])
def test_standalone_datum_rejects_unverifiable_style_snapshot(tmp_path: Path, change: str) -> None:
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id=style.style_id)
    path = tmp_path / "datum-style.dxf"
    write_sketches_dxf(
        (), path, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    if change == "missing":
        del payload["text_style_snapshot"]
    elif change == "null":
        payload["text_style_snapshot"] = None
    elif change == "source":
        payload["text_style_snapshot"]["source"]["height_mm"] = 9
    else:
        payload["text_style_snapshot"]["native"]["font_family"] = "DejaVu Serif"
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    document.saveas(path)
    imported = read_sketch_dxf(path)
    restored = imported.datum_identifiers[0]
    assert restored.text_style_id is not None and restored.text_style_id != style.style_id
    assert imported.text_styles is not None
    assert imported.text_styles.get(restored.text_style_id).font_family == "DejaVu Sans"
    if change == "missing":
        assert not any("样式快照" in warning for warning in imported.report.warnings)
    else:
        assert any("样式快照" in warning for warning in imported.report.warnings)


def test_datum_with_removed_style_identity_keeps_edited_native_font(tmp_path: Path) -> None:
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id=style.style_id)
    path = tmp_path / "datum-no-style-id.dxf"
    write_sketches_dxf(
        (), path, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    payload["datum"]["text_style_id"] = None
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0]
    assert restored.text_style_id is not None and restored.text_style_id != style.style_id
    assert result.text_styles is not None
    assert result.text_styles.get(restored.text_style_id).font_family == "DejaVu Sans"
    assert any("样式快照" in warning for warning in result.report.warnings)


def test_datum_style_snapshot_name_conflict_preserves_existing_frame_style(tmp_path: Path) -> None:
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    style = TextStyle("datum-font", "基准字体", "DejaVu Sans", height_mm=7, width_factor=1.5)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0), text_style_id=style.style_id
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id=style.style_id)
    path = tmp_path / "style-name-conflict.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((style,), style.style_id),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    payload["text_style_snapshot"]["source"]["name"] = "另一名称"
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.text_styles is not None
    assert imported.tolerance_frames[0].text_style_id == style.style_id
    assert imported.text_styles.get(style.style_id) == style
    restored = imported.datum_identifiers[0]
    assert restored.text_style_id is not None and restored.text_style_id != style.style_id
    assert imported.text_styles.get(restored.text_style_id).font_family == style.font_family
    assert any("文字样式" in warning and "冲突" in warning for warning in imported.report.warnings)
    assert not any(
        "原生字体与同身份文字样式不同" in warning for warning in imported.report.warnings
    )


def test_styled_datum_dxf_unit_conversion_scales_text_and_positions(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    style = TextStyle("datum-font", "基准字体", height_mm=2, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id="datum-font")
    target = tmp_path / "datum-inch.dxf"
    write_sketches_dxf(
        (), target, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), "datum-font")
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    document.header["$INSUNITS"] = 1
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.text_styles is not None
    result = imported.datum_identifiers[0]
    assert result.position_mm == pytest.approx((254, 508))
    assert result.target_mm == pytest.approx((254, 381))
    assert result.text_style_id is not None and result.text_style_id == style.style_id
    restored = imported.text_styles.get(result.text_style_id)
    assert restored.height_mm == pytest.approx(50.8)
    assert restored.width_factor == pytest.approx(1.5)


@pytest.mark.parametrize("attribute", ["height", "width"])
def test_styled_datum_inconsistent_external_style_is_reported(
    tmp_path: Path,
    attribute: str,
) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    style = TextStyle("datum-font", "基准字体", height_mm=7, width_factor=1.5)
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15), text_style_id="datum-font")
    target = tmp_path / "datum.dxf"
    write_sketches_dxf(
        (), target, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), "datum-font")
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(target)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    text = next(item for item in document.blocks.get(insert.dxf.name) if item.dxftype() == "TEXT")
    setattr(document.styles.get(text.dxf.style).dxf, attribute, 2.0)
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert not imported.datum_identifiers
    assert any("基准" in warning and "不一致" in warning for warning in imported.report.warnings)


def test_modified_datum_block_is_reported_without_restoring_stale_data(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "modified.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    reader = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = reader(path)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    text = next(item for item in document.blocks.get(insert.dxf.name) if item.dxftype() == "TEXT")
    text.dxf.text = "B"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any(
        "基准图形块" in warning and "已修改" in warning for warning in imported.report.warnings
    )
    assert any(text.text == "B" for text in imported.texts)
    assert len(imported.sketch.entities) >= 4
    assert any("普通图元" in warning and "文字" in warning for warning in imported.report.warnings)


def test_modified_datum_block_preserves_transformed_text_and_lines(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import LineEntity

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "rotated-scaled-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    space.add_text("independent", dxfattribs={"insert": (1, 2), "height": 3})
    insert = next(item for item in space if item.dxftype() == "INSERT")
    insert.dxf.rotation = 90
    insert.dxf.xscale = insert.dxf.yscale = insert.dxf.zscale = 2
    virtual = list(insert.virtual_entities())
    line = next(item for item in virtual if item.dxftype() == "LINE")
    text = next(item for item in virtual if item.dxftype() == "TEXT")
    document.saveas(path)

    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any(
        isinstance(item, LineEntity)
        and item.start_mm == pytest.approx(tuple(line.dxf.start)[:2])
        and item.end_mm == pytest.approx(tuple(line.dxf.end)[:2])
        for item in imported.sketch.entities
    )
    restored = next(item for item in imported.texts if item.text == "A")
    assert restored.position_mm == pytest.approx(tuple(text.dxf.insert)[:2])
    assert restored.height_mm == pytest.approx(2 * 3.5)
    assert restored.rotation_deg == pytest.approx(90)
    assert any(item.text == "independent" for item in imported.texts)
    assert imported.text_styles is not None
    assert imported.text_styles.get(restored.style_id).name == "Standard"


def test_modified_datum_text_style_id_collision_is_remapped(tmp_path: Path) -> None:
    import hashlib

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    collision = "dxf_" + hashlib.sha256(b"standard").hexdigest()[:24]
    style = TextStyle(collision, "FrameFont", height_mm=7)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (30, 30), text_style_id=collision
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "colliding-datum-font.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((style,), collision),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    document.blocks[insert.dxf.name].query("TEXT")[0].dxf.text = "B"
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.text_styles is not None
    imported_frame = result.tolerance_frames[0]
    fallback = next(item for item in result.texts if item.text == "B")
    assert fallback.style_id != imported_frame.text_style_id
    assert result.text_styles.get(fallback.style_id).name == "Standard"
    assert result.text_styles.get(cast("str", imported_frame.text_style_id)).name == "FrameFont"


def test_modified_datum_solid_preserves_all_four_outline_edges(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import LineEntity

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 5))
    path = tmp_path / "quadrilateral.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    solid = document.blocks[insert.dxf.name].query("SOLID")[0]
    for index, point in enumerate(((0, 0), (4, 0), (0, 3), (4, 3))):
        setattr(solid.dxf, f"vtx{index}", point)
    document.saveas(path)

    result = read_sketch_dxf(path)
    edges = {
        frozenset((entity.start_mm, entity.end_mm))
        for entity in result.sketch.entities
        if isinstance(entity, LineEntity)
    }
    corners = ((10, 20), (14, 20), (14, 23), (10, 23))
    assert all(
        frozenset((start, end)) in edges
        for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
    )
    assert any("实心填充" in warning and "轮廓" in warning for warning in result.report.warnings)


def test_datum_block_nonplanar_extrusion_is_not_flattened(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "nonplanar-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    reader = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = reader(path)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    insert.dxf.extrusion = (0, 1, 0)
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any("XY 平面" in warning for warning in imported.report.warnings)


def test_datum_block_text_rotation_change_is_reported(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "rotated-text.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    reader = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])
    document = reader(path)
    insert = next(item for item in document.modelspace() if item.dxftype() == "INSERT")
    text = next(item for item in document.blocks.get(insert.dxf.name) if item.dxftype() == "TEXT")
    text.dxf.rotation = 45
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any("已修改" in warning for warning in imported.report.warnings)


def test_datum_attachment_is_remapped_when_dxf_sketches_are_merged(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (1, 2), (5, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (7, 0), (8, 0)),))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    path = tmp_path / "merged.dxf"
    write_sketches_dxf((first, second), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    attachment = imported.datum_identifiers[0].attachment
    assert attachment is not None
    assert attachment.sketch_id == imported.sketch.sketch_id
    assert attachment.reference.entity_id == line.entity_id


def test_missing_datum_attachment_is_reported_on_export_and_import(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference

    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (1, 2),
        attachment=DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start")),
    )
    path = tmp_path / "missing-attachment.dxf"
    report = write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert any("附着" in warning for warning in report.warnings)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].attachment is None
    assert imported.datum_identifiers[0].target_mm == (1, 2)
    assert any("附着" in warning for warning in imported.report.warnings)


def test_line_interior_attachment_roundtrips_in_dxf(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (2.5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.25
        ),
    )
    path = tmp_path / "line-attachment.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_polyline_segment_attachment_roundtrips_in_dxf(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    poly = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (poly,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (3, 4),
        (5, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(poly.entity_id, "segment", 0), 0.5, 2
        ),
    )
    path = tmp_path / "poly-attachment.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_export_rejects_annotations_with_non_xy_reference_plane(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xz(), (LineEntity(uuid4().hex, (0, 0), (10, 0)),))
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (1, 2))
    with pytest.raises(ValidationError, match="XY"):
        write_sketches_dxf((sketch,), tmp_path / "mixed-plane.dxf", tolerance_frames=(frame,))


@pytest.mark.parametrize("label", ("𠀀" * 80, "甲" * 39 + "𠀀" * 40 + "%", "𠀀" * 63 + "  " + "𠀀"))
def test_datum_unicode_text_chunks_fit_dxf_limit_and_roundtrip(tmp_path: Path, label: str) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, label, (0, 0), (0, -10))
    path = tmp_path / "datum-long-unicode.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    texts = document.blocks[insert.dxf.name].query("TEXT")
    assert all(len(text.dxf.text.encode("utf-8")) <= 255 for text in texts)
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_frame_leader_dxf_roundtrip(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "frame-with-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    assert len(document.modelspace().query("LEADER")) == 1
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    assert not any("箭头" in warning for warning in result.report.warnings)
    assert not any("引线" in warning and "外观" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_normal_dxf_roundtrip(tmp_path: Path, owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True)
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (10, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    path = tmp_path / "surface-normal.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0] if owner == "datum" else result.tolerance_frames[0]
    assert restored.surface_indication == surface


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_normal_dxf_releases_constraint_when_target_missing(
    tmp_path: Path, owner: str
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    surface = SurfaceIndication(
        (5, 8),
        (10, 8),
        0.5,
        ((0, 3),),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=True,
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (30, 30), (10, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    path = tmp_path / "missing-normal-target.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    geometry = next(item for item in space.query("LINE") if item.has_xdata("MYCAD"))
    space.delete_entity(geometry)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0] if owner == "datum" else result.tolerance_frames[0]
    assert restored.surface_indication is not None
    assert (
        not restored.surface_indication.auto_normal and not restored.surface_indication.auto_route
    )
    assert not restored.surface_indication.route_avoid_crossing
    assert any("解除关联" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("auto_route", [False, True])
def test_frame_primary_normal_dxf_roundtrip_and_missing_target(
    tmp_path: Path, auto_route: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((-20, -17),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=auto_route,
        route_avoid_crossing=auto_route,
        route_track_target=auto_route,
        route_algorithm_version=2 if auto_route else 1,
    )
    path = tmp_path / "frame-normal.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    geometry = next(item for item in document.modelspace().query("LINE") if item.has_xdata("MYCAD"))
    document.modelspace().delete_entity(geometry)
    document.saveas(path)
    detached = read_sketch_dxf(path)
    assert detached.tolerance_frames[0].leader_attachment is None
    assert not detached.tolerance_frames[0].leader_auto_normal
    assert not detached.tolerance_frames[0].leader_auto_route
    assert not detached.tolerance_frames[0].route_avoid_crossing
    assert not detached.tolerance_frames[0].route_track_target
    assert detached.tolerance_frames[0].route_algorithm_version == 1
    assert any("解除关联" in warning for warning in detached.report.warnings)


def test_spline_normal_datum_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    spline = SplineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0.5,
        curve_kind="spline",
        control_count=4,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 30),
        spline.point_at(0.5),
        attachment=attachment,
        leader_offsets=((-22, -23),),
        leader_auto_normal=True,
        spline_normal_enabled=True,
    )
    path = tmp_path / "spline-normal.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers == (datum,)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_extension_line_dxf_roundtrip(tmp_path: Path, owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 10),
        leader_target_mm=(15, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
    )
    path = tmp_path / "extension.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    extensions = [
        e for e in document.modelspace().query("LINE") if e.has_xdata("MYCAD_SURFACE_EXT")
    ]
    assert len(extensions) == 1
    assert tuple(extensions[0].dxf.start) == pytest.approx((11, 0, 0))
    assert tuple(extensions[0].dxf.end) == pytest.approx((17, 0, 0))
    imported = read_sketch_dxf(path)
    restored = (
        imported.datum_identifiers[0].attachment
        if owner == "datum"
        else imported.tolerance_frames[0].leader_attachment
    )
    assert restored == attachment
    assert len(imported.sketch.entities) == 1


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("bent", [False, True])
def test_surface_indication_dxf_roundtrip(tmp_path: Path, owner: str, bent: bool) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    indication = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    offsets = ((-4, -3),) if bent else ()
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (0, 0), leader_offsets=offsets, surface_indication=indication
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=offsets,
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    path = tmp_path / "surface-indication.dxf"
    write_sketches_dxf(
        (),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    parts = [item for item in document.modelspace() if item.has_xdata("MYCAD_SURFACE_IND")]
    assert len(parts) == 4
    assert [item.dxftype() for item in parts].count("SOLID") == 1
    imported = read_sketch_dxf(path)
    restored = (
        imported.datum_identifiers[0].surface_indication
        if owner == "datum"
        else imported.tolerance_frames[0].surface_indication
    )
    assert restored == indication
    assert not imported.sketch.entities


@pytest.mark.parametrize("change", ["move", "delete", "duplicate", "bad_marker"])
def test_surface_extension_dxf_external_edit_detaches(tmp_path: Path, change: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    path = tmp_path / "edited-extension.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    extension = next(item for item in space.query("LINE") if item.has_xdata("MYCAD_SURFACE_EXT"))
    if change == "move":
        extension.dxf.end = (18, 0, 0)
    elif change == "delete":
        space.delete_entity(extension)
    elif change == "duplicate":
        copy = space.add_line(extension.dxf.start, extension.dxf.end)
        copy.set_xdata("MYCAD_SURFACE_EXT", [(1000, "datum"), (1000, datum.datum_id)])
    else:
        extension.set_xdata("MYCAD_SURFACE_EXT", [(1000, "invalid")])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].attachment is None
    assert any("附着" in warning and "解除" in warning for warning in imported.report.warnings)
    assert len(imported.sketch.entities) == (
        1 if change == "delete" else 3 if change == "duplicate" else 2
    )


def test_surface_indication_sized_arrow_dxf_roundtrip_and_scaling(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import datum_triangle

    indication = SurfaceIndication((0, 20), (10, 20), 0.5, arrow_size_mm=5)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 30), (0, 0), surface_indication=indication)
    path = tmp_path / "sized-arrow.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    solid = next(
        item for item in document.modelspace().query("SOLID") if item.has_xdata("MYCAD_SURFACE_IND")
    )
    expected = datum_triangle((0, 20), (0, 0), 5)
    assert tuple(solid.dxf.vtx1) == pytest.approx((*expected[1], 0))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].surface_indication == indication
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    scaled = read_sketch_dxf(path).datum_identifiers[0].surface_indication
    assert scaled is not None and scaled.arrow_size_mm == pytest.approx(127)


def test_surface_indication_frame_primary_arrow_dxf_size(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=SurfaceIndication((0, 20), (10, 20), 0.5, arrow_size_mm=5),
    )
    path = tmp_path / "frame-arrow.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = next(iter(document.modelspace().query("LEADER")))
    assert document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz == pytest.approx(5)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].surface_indication == frame.surface_indication
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


def test_surface_frame_explicit_arrow_units_remain_consistent(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=SurfaceIndication((0, 20), (10, 20), 0.5, arrow_size_mm=5),
    )
    path = tmp_path / "surface-arrow-inches.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    result = read_sketch_dxf(path)
    indication = result.tolerance_frames[0].surface_indication
    assert indication is not None and indication.arrow_size_mm == pytest.approx(127)
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


def test_short_frame_leader_dxf_arrow_matches_canvas_limit(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (1, 0),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, 0),
    )
    path = tmp_path / "short-frame-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    assert document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz == pytest.approx(1)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("offsets", [((-10, 0),), ((-5, 0), (-5, 0))])
def test_degenerate_frame_leader_does_not_overwrite_dxf(
    tmp_path: Path, offsets: tuple[tuple[float, float], ...]
) -> None:
    from mycad.core.exceptions import ValidationError

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 0),
        leader_target_mm=(0, 0),
        leader_offsets=offsets,
        leader_anchor_offset=(0, 0),
    )
    path = tmp_path / "degenerate-frame.dxf"
    path.write_bytes(b"existing drawing")
    with pytest.raises(ValidationError, match="引线.*重合"):
        write_sketches_dxf((), path, tolerance_frames=(frame,))
    assert path.read_bytes() == b"existing drawing"


def test_normal_vertex_at_frame_anchor_exports_without_degenerate_segment(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((0, 0),),
        leader_anchor_offset=(0, 0),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_auto_normal=True,
    )
    path = tmp_path / "normal-at-anchor.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    assert len(leader.vertices) == 2
    assert read_sketch_dxf(path).tolerance_frames == (frame,)
    leader.vertices.append(leader.vertices[-1])
    document.saveas(path)
    assert read_sketch_dxf(path).tolerance_frames == (frame,)


def test_cadcraft_resaved_short_leader_preserves_arrow_and_geometry() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-short-leader-resaved.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    assert document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz == pytest.approx(1)
    result = read_sketch_dxf(path)
    frame = result.tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((0, 0))
    assert frame.leader_anchor_offset == pytest.approx((0, 0))
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)
    assert any("原生关联" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("arrow_size", [None, 5.0])
def test_short_surface_frame_leader_dxf_arrow_matches_canvas_limit(
    tmp_path: Path, arrow_size: float | None
) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0.5, 2),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, 0),
        surface_indication=SurfaceIndication((0, 1), (1, 1), 0.5, arrow_size_mm=arrow_size),
    )
    path = tmp_path / "short-surface-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    assert document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz == pytest.approx(1)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("change", ["style", "override", "scale"])
def test_surface_indication_frame_reports_external_arrow_size_change(
    tmp_path: Path, change: str
) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    indication = SurfaceIndication((0, 20), (10, 20), 0.5, arrow_size_mm=5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    path = tmp_path / "edited-arrow.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = next(iter(document.modelspace().query("LEADER")))
    if change == "style":
        document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz = 9
    elif change == "override":
        override = leader.override()
        override["dimasz"] = 9
        override.commit()
    else:
        document.dimstyles.get(leader.dxf.dimstyle).dxf.dimscale = 2
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].surface_indication == indication
    assert any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("surface", [False, True])
@pytest.mark.parametrize("change", ["size", "shape"])
def test_frame_reports_external_arrow_appearance_change(
    tmp_path: Path, surface: bool, change: str
) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    indication = SurfaceIndication((0, 20), (10, 20), 0.5, arrow_size_mm=5) if surface else None
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    path = tmp_path / "edited-arrow-appearance.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    override = leader.override()
    if change == "size":
        override["dimasz"] = 9
    else:
        document.blocks.new("MY_ARROW").add_line((0, 0), (1, 1))
        override["dimldrblk"] = "MY_ARROW"
    override.commit()
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm == frame.leader_target_mm
    assert any(
        "箭头" in warning and ("尺寸" if change == "size" else "样式") in warning
        for warning in result.report.warnings
    )


@pytest.mark.parametrize("source", ["dimstyle", "override"])
def test_frame_reports_external_leader_arrow_block(tmp_path: Path, source: str) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_arrow_style="closed_filled",
    )
    path = tmp_path / "leader-arrow-block.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    document.blocks.new("CUSTOM_LEADER_ARROW").add_line((0, 0), (1, 1))
    if source == "dimstyle":
        document.dimstyles.get(leader.dxf.dimstyle).dxf.dimldrblk = "CUSTOM_LEADER_ARROW"
    else:
        override = leader.override()
        override["dimldrblk"] = "CUSTOM_LEADER_ARROW"
        override.commit()
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm == frame.leader_target_mm
    assert any("箭头" in warning and "样式" in warning for warning in result.report.warnings)


def test_frame_ignores_unrelated_dimension_arrow_block(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 30),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_arrow_style="closed_filled",
    )
    path = tmp_path / "dimension-arrow-block.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    document.blocks.new("CUSTOM_DIMENSION_ARROW").add_line((0, 0), (1, 1))
    override = leader.override()
    override["dimblk"] = "CUSTOM_DIMENSION_ARROW"
    override.commit()
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm == frame.leader_target_mm
    assert not any("箭头" in warning and "样式" in warning for warning in result.report.warnings)


def test_orphaned_custom_leader_arrow_is_not_replaced_by_default(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "orphan-custom-arrow.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    leader = space.query("LEADER")[0]
    document.blocks.new("CUSTOM_LEADER_ARROW").add_line((0, 0), (1, 1))
    override = leader.override()
    override["dimldrblk"] = "CUSTOM_LEADER_ARROW"
    override.commit()
    space.delete_entity(space.query("TOLERANCE")[0])
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert len([entity for entity in result.sketch.entities if isinstance(entity, LineEntity)]) == 1
    assert any("箭头" in warning and "不支持" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_indication_dxf_unit_conversion(tmp_path: Path, owner: str) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    indication = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),), arrow_size_mm=4)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=indication)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    path = tmp_path / "indication-inches.dxf"
    write_sketches_dxf(
        (),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0] if owner == "datum" else result.tolerance_frames[0]
    assert restored.surface_indication is not None
    assert restored.surface_indication.reference_start_offset_mm == pytest.approx((127, 127))
    assert restored.surface_indication.leader_offsets_mm[0] == pytest.approx((76.2, 76.2))
    assert restored.surface_indication.arrow_size_mm == pytest.approx(101.6)
    assert not any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)


def test_surface_indication_dxf_preserves_geometry_attachment(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    indication = SurfaceIndication((3, 8), (8, 8), 0.5)
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment, surface_indication=indication
    )
    path = tmp_path / "attached-indication.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].attachment == attachment
    assert result.datum_identifiers[0].surface_indication == indication
    assert len(result.sketch.entities) == 1


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_indication_dxf_edited_component_preserves_graphics(
    tmp_path: Path, owner: str
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    indication = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=indication)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=indication,
    )
    path = tmp_path / "edited-indication.dxf"
    write_sketches_dxf(
        (),
        path,
        datum_identifiers=(datum,) if owner == "datum" else (),
        tolerance_frames=(frame,) if owner == "frame" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    part = next(
        item for item in document.modelspace().query("LINE") if item.has_xdata("MYCAD_SURFACE_IND")
    )
    part.dxf.end = (11, 5, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.datum_identifiers[0] if owner == "datum" else result.tolerance_frames[0]
    assert restored.surface_indication is None
    target = (
        restored.target_mm if isinstance(restored, DatumIdentifier) else restored.leader_target_mm
    )
    assert target == pytest.approx((7.5, 5))
    assert len(result.sketch.entities) >= 3
    assert any("表面指示" in warning and "解除" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("side", ["start", "end"])
def test_surface_extension_arc_dxf_roundtrip(tmp_path: Path, side: str) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import (
        SurfaceExtensionSpec,
        surface_extension_geometry,
    )
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    arc = ArcEntity(uuid4().hex, (0, 0), 10, 90, -90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    extension = SurfaceExtensionSpec(cast("Any", side), 2, 0.5, 1)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(arc.entity_id, "geometry"),
        0 if side == "start" else 1,
        surface_extension=extension,
    )
    target = surface_extension_geometry(arc, extension.side, 2, 0.5, 1).target_mm
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), target, attachment=attachment)
    path = tmp_path / "arc-extension.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    assert (
        len(
            [
                item
                for item in document.modelspace().query("ARC")
                if item.has_xdata("MYCAD_SURFACE_EXT")
            ]
        )
        == 1
    )
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].attachment == attachment
    assert len(imported.sketch.entities) == 1


def test_surface_extension_dxf_rotated_source_sketch(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    base = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    frame = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, frame, (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 15), attachment=attachment)
    path = tmp_path / "rotated-extension.dxf"
    write_sketches_dxf((base, sketch), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    restored = imported.datum_identifiers[0]
    assert (
        restored.attachment is not None
        and restored.attachment.surface_extension == attachment.surface_extension
    )
    assert restored.attachment.sketch_id == imported.sketch.sketch_id
    assert restored.target_mm == pytest.approx((0, 15))


def test_surface_extension_dxf_duplicate_owner_never_guesses(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    identity = uuid4().hex
    datums = (
        DatumIdentifier(identity, "A", (20, 10), (15, 0), attachment=attachment),
        DatumIdentifier(identity, "B", (20, 20), (15, 0), attachment=attachment),
    )
    path = tmp_path / "duplicate-owner.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=datums)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    extensions = [item for item in space.query("LINE") if item.has_xdata("MYCAD_SURFACE_EXT")]
    space.delete_entity(extensions[0])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.datum_identifiers) == 2
    assert all(item.attachment is None for item in imported.datum_identifiers)
    assert any("解除" in warning for warning in imported.report.warnings)


def test_surface_extension_dxf_unit_conversion(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    path = tmp_path / "inches.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    imported = read_sketch_dxf(path)
    restored = imported.datum_identifiers[0]
    assert restored.attachment is not None and restored.attachment.surface_extension is not None
    assert restored.target_mm == pytest.approx((381, 0))
    assert restored.attachment.surface_extension.distance_mm == pytest.approx(127)
    assert restored.attachment.surface_extension.offset_mm == pytest.approx(25.4)
    assert restored.attachment.surface_extension.overshoot_mm == pytest.approx(50.8)


def test_surface_extension_dxf_rejects_missing_target_without_overwriting(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(
        uuid4().hex,
        SketchGeometryReference(uuid4().hex, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 10), (15, 0), attachment=attachment)
    path = tmp_path / "unchanged.dxf"
    path.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="表面延伸"):
        write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert path.read_bytes() == b"existing"


def test_annotation_attachment_export_does_not_silently_drop_link(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    ref = AnnotationAttachment("frame", uuid4().hex, (0, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), annotation_attachment=ref)
    with pytest.raises(ValidationError, match="附着"):
        write_sketches_dxf((), tmp_path / "datum-annotation.dxf", datum_identifiers=(datum,))


def test_datum_frame_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    path = tmp_path / "attached-datum.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].annotation_attachment == datum.annotation_attachment
    assert result.datum_identifiers[0].target_mm == datum.target_mm


def test_datum_reference_dimension_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "reference_dimension", dimension.dimension_id, (0, 0)
        ),
    )
    path = tmp_path / "dimension-attachment.dxf"
    write_sketches_dxf((), path, reference_dimensions=(dimension,), datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].annotation_attachment == datum.annotation_attachment


def test_frame_reference_dimension_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import AnnotationAttachment

    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 0), (10, 0), (0, 5), 0, 10)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 5),
        leader_anchor_offset=(0, -2),
        leader_annotation_attachment=AnnotationAttachment(
            "reference_dimension", dimension.dimension_id, (0, 0)
        ),
    )
    path = tmp_path / "frame-reference-dimension.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), reference_dimensions=(dimension,))
    result = read_sketch_dxf(path)
    assert (
        result.tolerance_frames[0].leader_annotation_attachment
        == frame.leader_annotation_attachment
    )


def test_datum_sketch_dimension_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 5),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), sketch.sketch_id
        ),
    )
    path = tmp_path / "sketch-dimension-attachment.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    attachment = result.datum_identifiers[0].annotation_attachment
    assert attachment is not None
    assert attachment.sketch_id == result.sketch.sketch_id
    assert attachment.object_id == result.sketch.constraints[0].constraint_id


def test_sketch_dimension_attachment_dxf_duplicate_dimension_ids(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = [LineEntity(uuid4().hex, (0, y), (20, y)) for y in (0, 20)]
    sketches = tuple(
        Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (line,),
            (
                SketchConstraint(
                    identity,
                    "length",
                    (SketchGeometryReference(line.entity_id, "geometry"),),
                    value=20,
                    unit="mm",
                    position_mm=(0, y + 5),
                ),
            ),
        )
        for line, y in zip(lines, (0, 20), strict=True)
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 30),
        (0, 25),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", identity, (0, 0), sketches[1].sketch_id
        ),
    )
    path = tmp_path / "duplicate-dimensions.dxf"
    write_sketches_dxf(sketches, path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    attachment = result.datum_identifiers[0].annotation_attachment
    assert attachment is not None
    assert attachment.object_id != identity
    assert attachment.object_id == result.sketch.constraints[1].constraint_id


def test_sketch_dimension_text_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
        text_position_mm=(8, 7),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (8, 7),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), sketch.sketch_id, "text"
        ),
    )
    path = tmp_path / "text-attachment.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    attachment = result.datum_identifiers[0].annotation_attachment
    assert attachment is not None and attachment.anchor == "text"
    assert attachment.object_id == result.sketch.constraints[0].constraint_id


def test_sketch_dimension_text_attachment_dxf_detaches_after_external_move(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
        text_position_mm=(8, 7),
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (8, 7),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (0, 0), sketch.sketch_id, "text"
        ),
    )
    path = tmp_path / "text-attachment-moved.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("DIMENSION")[0]
    native.dxf.text_midpoint = (30, 22, 0)
    native.dxf.dimtype |= 128
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].annotation_attachment is None
    assert any("标注附着" in warning for warning in result.report.warnings)


def test_sketch_dimension_attachment_dxf_rotated_sketch_offset(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    primary = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=20,
        unit="mm",
        position_mm=(0, 5),
    )
    sketch = Sketch(uuid4().hex, rotated, (line,), (dimension,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (-5, 2),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", dimension.constraint_id, (2, 0), sketch.sketch_id
        ),
    )
    path = tmp_path / "rotated-attachment.dxf"
    write_sketches_dxf((primary, sketch), path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    attachment = result.datum_identifiers[0].annotation_attachment
    assert attachment is not None
    assert attachment.offset_mm == pytest.approx((0, 2))
    assert result.datum_identifiers[0].target_mm == pytest.approx((-5, 2))


def test_frame_to_frame_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    rows = (ToleranceRow("position", 0.1, 2),)
    source = FeatureControlFrame(uuid4().hex, rows, (0, 0))
    dependent = FeatureControlFrame(
        uuid4().hex,
        rows,
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    path = tmp_path / "frame-attachment.dxf"
    write_sketches_dxf((), path, tolerance_frames=(source, dependent))
    result = read_sketch_dxf(path)
    assert (
        result.tolerance_frames[1].leader_annotation_attachment
        == dependent.leader_annotation_attachment
    )


def test_frame_attachment_dxf_import_detaches_cycle(tmp_path: Path) -> None:
    import json
    from dataclasses import replace

    from mycad.core.geometric_tolerance import AnnotationAttachment
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    rows = (ToleranceRow("position", 0.1, 2),)
    source = FeatureControlFrame(
        uuid4().hex, rows, (0, 0), leader_target_mm=(10, 10), leader_anchor_offset=(0, -2)
    )
    dependent = FeatureControlFrame(
        uuid4().hex,
        rows,
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    path = tmp_path / "cyclic-frames.dxf"
    write_sketches_dxf((), path, tolerance_frames=(source, dependent))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    values = tuple(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    metadata = json.loads(unpack_annotation_metadata(values))
    metadata["frame"] = replace(
        source,
        leader_annotation_attachment=AnnotationAttachment("frame", dependent.frame_id, (0, 0)),
    ).to_mapping()
    entity.set_xdata(
        "MYCAD_FCF", [(1000, value) for value in pack_annotation_metadata(json.dumps(metadata))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert all(frame.leader_annotation_attachment is None for frame in result.tolerance_frames)
    assert any("循环" in warning for warning in result.report.warnings)


def test_datum_frame_attachment_dxf_detaches_when_target_was_moved(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", frame.frame_id, (0, 0)),
    )
    path = tmp_path / "modified-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.modelspace().query("TOLERANCE")[0].dxf.insert = (5, 0, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].annotation_attachment is None
    assert any("标注附着" in warning for warning in result.report.warnings)


def test_datum_frame_attachment_dxf_rebinds_identity_collision(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumIdentifier

    identity = uuid4().hex
    frame = FeatureControlFrame(identity, (ToleranceRow("position", 0.1, 2),), (0, 0))
    datum = DatumIdentifier(
        identity,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", identity, (0, 0)),
    )
    path = tmp_path / "colliding-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    attachment = result.datum_identifiers[0].annotation_attachment
    assert attachment is not None
    assert attachment.object_id == result.tolerance_frames[0].frame_id
    assert attachment.object_id != identity


def test_datum_without_leader_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), leader_visible=False)
    path = tmp_path / "datum-no-leader.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    assert len(document.blocks[insert.dxf.name].query("LINE")) == 4
    assert not document.blocks[insert.dxf.name].query("SOLID")
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_shared_datum_without_leader_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(
        uuid4().hex, "A", (10, 10), (10, 10), leader_visible=False, layout_mode="shared"
    )
    path = tmp_path / "shared-datum-no-leader.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_graphics_expansion_unlinks_frame_leader(tmp_path: Path) -> None:
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "frame-graphics.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    assert expand_tolerances_for_preview(document) == (1, 0)
    leader = document.modelspace().query("LEADER")[0]
    assert not leader.dxf.hasattr("annotation_handle")
    assert not leader.has_xdata("MYCAD_FCF_LEADER")


def test_graphics_expansion_short_leader_keeps_arrow_as_ordinary_geometry(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.formats.geometric_tolerance_preview import expand_tolerances_for_preview

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (1, 0),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, 0),
    )
    path = tmp_path / "short-graphics.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    assert expand_tolerances_for_preview(document) == (1, 0)
    leader = document.modelspace().query("LEADER")[0]
    assert document.dimstyles.get(leader.dxf.dimstyle).dxf.dimasz == pytest.approx(1)
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.tolerance_frames
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((0, 0))
        and entity.end_mm == pytest.approx((1, 0))
        for entity in imported.sketch.entities
    )
    assert any("箭头" in warning and "轮廓" in warning for warning in imported.report.warnings)


def test_frame_leader_dxf_preserves_geometry_attachment(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    path = tmp_path / "frame-attached.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    assert read_sketch_dxf(path).tolerance_frames == (frame,)


def test_ellipse_datum_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    ellipse = EllipseEntity(uuid4().hex, (0, 0), 10, 5, rotation_deg=20)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    target = ellipse.point_at(0.125)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(ellipse.entity_id, "geometry"),
        0.125,
        curve_kind="ellipse",
    )
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), target, attachment=attachment)
    path = tmp_path / "ellipse-datum.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers[0].attachment == attachment
    assert result.datum_identifiers[0].target_mm == pytest.approx(target)


def test_ellipse_frame_attachment_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    ellipse = EllipseEntity(uuid4().hex, (0, 0), 10, 5, rotation_deg=20)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    target = ellipse.point_at(0.125)
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(ellipse.entity_id, "geometry"),
        0.125,
        curve_kind="ellipse",
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=target,
        leader_anchor_offset=(0, -3),
        leader_attachment=attachment,
    )
    path = tmp_path / "ellipse-frame.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_attachment == attachment
    assert result.tolerance_frames[0].leader_target_mm == pytest.approx(target)


def test_frame_export_reports_missing_attachment_target(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
        leader_attachment=DatumAttachment(
            uuid4().hex, SketchGeometryReference(uuid4().hex, "start")
        ),
    )
    report = write_sketches_dxf(
        (), tmp_path / "missing-frame-target.dxf", tolerance_frames=(frame,)
    )
    assert any("公差" in warning and "附着" in warning for warning in report.warnings)


def test_orphaned_frame_leader_is_reported(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "orphan-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.modelspace().delete_entity(document.modelspace().query("TOLERANCE")[0])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert any("引线" in warning and "无法" in warning for warning in result.report.warnings)
    from mycad.core.sketch import LineEntity

    assert any(
        isinstance(item, LineEntity) and item.start_mm == pytest.approx((0, 0))
        for item in result.sketch.entities
    )


@pytest.mark.parametrize("arrow", [True, False])
def test_orphaned_frame_leader_retains_units_and_arrow_outline(tmp_path: Path, arrow: bool) -> None:
    from mycad.core.geometric_tolerance_geometry import frame_leader_arrow
    from mycad.core.sketch import LineEntity

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "orphan-inches.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    leader = space.query("LEADER")[0]
    leader.dxf.has_arrowhead = int(arrow)
    space.delete_entity(space.query("TOLERANCE")[0])
    document.header["$INSUNITS"] = 1
    document.saveas(path)

    result = read_sketch_dxf(path)
    lines = [item for item in result.sketch.entities if isinstance(item, LineEntity)]
    assert any(
        item.start_mm == pytest.approx((0, 0)) and item.end_mm == pytest.approx((254, 177.8))
        for item in lines
    )
    assert len(lines) == (4 if arrow else 1)
    if arrow:
        triangle = frame_leader_arrow((254, 177.8), (0, 0), 2.5 * 25.4)
        assert any(item.end_mm == pytest.approx(triangle[1]) for item in lines)
        assert any("箭头" in warning and "轮廓" in warning for warning in result.report.warnings)


def test_orphaned_spline_leader_is_reported_without_flattening(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "orphan-spline.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    space.query("LEADER")[0].dxf.path_type = 1
    space.delete_entity(space.query("TOLERANCE")[0])
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert not result.sketch.entities
    assert any("引线" in warning and "只支持" in warning for warning in result.report.warnings)


def test_modified_frame_leader_recovers_native_geometry(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "modified-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices[0] = (1, 0, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm == pytest.approx((1, 0))
    assert result.tolerance_frames[0].leader_anchor_offset == pytest.approx((0, -3))
    assert any("引线" in warning and "修改" in warning for warning in result.report.warnings)
    assert not result.sketch.entities


def test_cadcraft_moved_leader_recovers_with_unique_metadata() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-leader-moved.dxf"
    result = read_sketch_dxf(path)
    frame = result.tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((1, 0))
    assert frame.leader_anchor_offset == pytest.approx((1, -2))
    assert not result.sketch.entities
    assert any("引线" in warning and "原生关联" in warning for warning in result.report.warnings)


def test_native_tolerance_and_leader_without_mycad_metadata_import(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/mycad-leader-cadcraft-source.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    space.query("TOLERANCE")[0].discard_xdata("MYCAD_FCF")
    space.query("LEADER")[0].discard_xdata("MYCAD_FCF_LEADER")
    path = tmp_path / "native-frame-leader.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    frame = result.tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((0, 0))
    assert frame.leader_anchor_offset == pytest.approx((0, -2))
    assert not result.sketch.entities


@pytest.mark.parametrize(
    "fixture", ["cadcraft-frame-independent-leader.dxf", "cadcraft-frame-attempted-link.dxf"]
)
def test_cadcraft_independent_leader_is_preserved_without_guessing_link(fixture: str) -> None:
    from mycad.core.sketch import LineEntity

    path = Path(__file__).parents[1] / "fixtures/dxf" / fixture
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((0, 0))
        and entity.end_mm == pytest.approx((20, 18))
        for entity in result.sketch.entities
    )
    assert any("引线" in warning and "普通图元" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("z", [float("nan"), float("inf")])
def test_unlinked_leader_rejects_nonfinite_z(tmp_path: Path, z: float) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-frame-independent-leader.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices[0] = (0, 0, z)
    path = tmp_path / "invalid-leader-z.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.sketch.entities
    assert any("引线" in warning and "无法" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("change", ["duplicate", "spline", "no_arrow", "nonplanar"])
def test_native_frame_leader_rejects_ambiguous_or_unsupported_geometry(
    tmp_path: Path, change: str
) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/mycad-leader-cadcraft-source.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    space.query("TOLERANCE")[0].discard_xdata("MYCAD_FCF")
    leader = space.query("LEADER")[0]
    leader.discard_xdata("MYCAD_FCF_LEADER")
    if change == "duplicate":
        space.add_entity(leader.copy())
    elif change == "spline":
        leader.dxf.path_type = 1
    elif change == "no_arrow":
        leader.dxf.has_arrowhead = 0
    else:
        leader.vertices[0] = (0, 0, 5)
    path = tmp_path / "unsupported-native-frame-leader.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning and "无法" in warning for warning in result.report.warnings)
    if change == "nonplanar":
        assert not result.sketch.entities


@pytest.mark.parametrize("native_arrow,expect_warning", [(2.5, True), (2.5 / 25.4, False)])
def test_native_frame_leader_uses_dxf_unit_conversion(
    tmp_path: Path, native_arrow: float, expect_warning: bool
) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/mycad-leader-cadcraft-source.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    space.query("TOLERANCE")[0].discard_xdata("MYCAD_FCF")
    space.query("LEADER")[0].discard_xdata("MYCAD_FCF_LEADER")
    document.dimstyles.get(space.query("LEADER")[0].dxf.dimstyle).dxf.dimasz = native_arrow
    document.header["$INSUNITS"] = 1
    path = tmp_path / "native-inches.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    frame = result.tolerance_frames[0]
    assert frame.position_mm == pytest.approx((508, 508))
    assert frame.leader_arrow_style == "closed_filled"
    assert frame.leader_target_mm == pytest.approx((0, 0))
    assert frame.leader_anchor_offset == pytest.approx((0, -50.8))
    assert (
        any("箭头" in warning and "尺寸" in warning for warning in result.report.warnings)
        is expect_warning
    )


def test_leader_without_native_handle_rejects_duplicate_frame_metadata(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-leader-moved.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    space.add_entity(space.query("TOLERANCE")[0].copy())
    path = tmp_path / "ambiguous-leader.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.tolerance_frames) == 2
    assert all(frame.leader_target_mm is None for frame in result.tolerance_frames)
    assert any("引线" in warning and "未恢复" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("ambiguity", ["wrong_handle", "duplicate_leader"])
def test_cadcraft_leader_rejects_ambiguous_link(tmp_path: Path, ambiguity: str) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-leader-moved.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    leader = space.query("LEADER")[0]
    if ambiguity == "wrong_handle":
        leader.dxf.annotation_handle = "FFFF"
    else:
        space.add_entity(leader.copy())
    path = tmp_path / "ambiguous-cadcraft-leader.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning and "未恢复" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("units,scale", [(4, 1.0), (1, 25.4)])
def test_modified_frame_leader_preserves_vertices_and_units(
    tmp_path: Path, units: int, scale: float
) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "modified-vertices.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.header["$INSUNITS"] = units
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices = [(1, 2, 0), (4, 5, 0), (8, 9, 0)]
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.leader_target_mm == pytest.approx((scale, 2 * scale))
    assert restored.leader_offsets[0] == pytest.approx((-6 * scale, -5 * scale))
    assert restored.leader_anchor_offset == pytest.approx((-2 * scale, -scale))
    assert not result.sketch.entities


def test_modified_attached_frame_leader_detaches_and_roundtrips(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_offsets=((-20, -20),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    path = tmp_path / "attached-external-edit.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.modelspace().query("LEADER")[0].vertices[0] = (11, 0, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.leader_target_mm == pytest.approx((11, 0))
    assert restored.leader_attachment is None and not restored.leader_auto_normal
    assert any("解除" in warning and "附着" in warning for warning in result.report.warnings)
    output = tmp_path / "reexport.dxf"
    write_sketches_dxf((result.sketch,), output, tolerance_frames=(restored,))
    assert read_sketch_dxf(output).tolerance_frames == (restored,)


@pytest.mark.parametrize("changed_normal_vertex", [False, True])
def test_edited_main_leader_keeps_unchanged_target_attachment(
    tmp_path: Path, changed_normal_vertex: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_offsets=((-20, -20),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    path = tmp_path / "edited-attached-leader.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    if changed_normal_vertex:
        leader.vertices[1] = (12, 10, 0)
    else:
        leader.vertices[-1] = (29, 28, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.leader_target_mm == pytest.approx((10, 0))
    assert restored.leader_attachment is not None
    assert restored.leader_auto_normal is not changed_normal_vertex
    if changed_normal_vertex:
        assert any("法向" in warning and "解除" in warning for warning in result.report.warnings)
    output = tmp_path / "edited-attached-reexport.dxf"
    write_sketches_dxf((result.sketch,), output, tolerance_frames=(restored,))
    reread = read_sketch_dxf(output).tolerance_frames[0]
    assert reread.leader_attachment is not None
    assert reread.leader_auto_normal is not changed_normal_vertex


def test_edited_leader_detaches_if_target_geometry_changed(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
    )
    path = tmp_path / "edited-target-and-leader.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    space.query("LEADER")[0].vertices[-1] = (29, 28, 0)
    source = space.query("LINE")[0]
    source.dxf.start = (0, 1, 0)
    source.dxf.end = (20, 1, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.leader_target_mm == pytest.approx((10, 0))
    assert restored.leader_attachment is None
    assert any("附着" in warning and "解除" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("owner", ["datum", "frame"])
@pytest.mark.parametrize("surface", [False, True])
@pytest.mark.parametrize("auto", [False, True])
def test_rotated_target_at_same_point_releases_imported_normal(
    tmp_path: Path, owner: str, surface: bool, auto: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    indication = SurfaceIndication(
        (5, 8),
        (10, 8),
        0.5,
        ((0, 3),),
        auto_normal=True,
        auto_route=auto,
        route_avoid_crossing=auto,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_offsets=() if surface else ((-20, -20),),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        leader_auto_normal=not surface,
        leader_auto_route=auto and not surface,
        route_avoid_crossing=auto and not surface,
        route_track_target=auto and not surface,
        surface_indication=indication if surface else None,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (30, 30),
        (10, 0),
        leader_offsets=() if surface else ((-20, -20),),
        attachment=attachment,
        leader_auto_normal=not surface,
        leader_auto_route=auto and not surface,
        route_avoid_crossing=auto and not surface,
        route_track_target=auto and not surface,
        surface_indication=indication if surface else None,
    )
    path = tmp_path / "rotated-target.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,) if owner == "frame" else (),
        datum_identifiers=(datum,) if owner == "datum" else (),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    line_dxf = next(
        item
        for item in document.modelspace().query("LINE")
        if not item.has_xdata("MYCAD_SURFACE_IND")
    )
    line_dxf.dxf.start = (10, -10, 0)
    line_dxf.dxf.end = (10, 10, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0] if owner == "frame" else result.datum_identifiers[0]
    if owner == "frame":
        assert result.tolerance_frames[0].leader_attachment is not None
    else:
        assert result.datum_identifiers[0].attachment is not None
    if surface:
        assert restored.surface_indication is not None
        assert not restored.surface_indication.auto_normal
        assert not restored.surface_indication.auto_route
        assert not restored.surface_indication.route_avoid_crossing
    else:
        assert not restored.leader_auto_normal
        assert not restored.leader_auto_route
        assert not restored.route_avoid_crossing and not restored.route_track_target
    assert any("法向" in warning and "解除" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("attached", [False, True])
def test_surface_frame_with_edited_main_leader_preserves_indication(
    tmp_path: Path, attached: bool
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, SurfaceIndication
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = (
        DatumAttachment(sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5)
        if attached
        else None
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=attached)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (30, 30),
        leader_target_mm=(10, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    path = tmp_path / "edited-surface-main-leader.dxf"
    write_sketches_dxf((sketch,), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices[-1] = (29, 28, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.surface_indication == surface
    assert restored.leader_target_mm == pytest.approx((10, 0))
    assert restored.leader_anchor_offset == pytest.approx((-1, -2))
    assert (restored.leader_attachment is not None) == attached
    assert any("引线" in warning and "修改" in warning for warning in result.report.warnings)
    output = tmp_path / "surface-reexport.dxf"
    write_sketches_dxf((result.sketch,), output, tolerance_frames=(restored,))
    reread = read_sketch_dxf(output).tolerance_frames[0]
    assert reread.surface_indication == surface
    assert reread.leader_anchor_offset == pytest.approx((-1, -2))


@pytest.mark.parametrize("change", ["landing", "surface_component"])
def test_edited_surface_frame_does_not_retain_unverified_indication(
    tmp_path: Path, change: str
) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    surface = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        surface_indication=surface,
    )
    path = tmp_path / "edited-surface.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices[-1] = (19, 18, 0)
    if change == "landing":
        leader.vertices[0] = (8, 5, 0)
    else:
        part = next(
            item
            for item in document.modelspace().query("LINE")
            if item.has_xdata("MYCAD_SURFACE_IND")
        )
        part.dxf.end = (11, 5, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].surface_indication is None
    assert result.sketch.entities
    assert any("引线" in warning or "表面指示" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("change", ["zero_length", "too_many_vertices"])
def test_modified_invalid_frame_leader_is_not_restored(tmp_path: Path, change: str) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "invalid-external-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    if change == "zero_length":
        leader.vertices = [(1, 0, 0), (1, 0, 0), (10, 7, 0)]
    else:
        leader.vertices = [(index, 0, 0) for index in range(67)]
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning and "未恢复" in warning for warning in result.report.warnings)


@pytest.mark.parametrize(
    "change",
    ["layer", "color", "true_color", "linetype", "lineweight", "transparency", "scale", "hidden"],
)
@pytest.mark.parametrize("edited", [False, True])
def test_frame_reports_external_leader_graphic_overrides(
    tmp_path: Path, change: str, edited: bool
) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "leader-appearance.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    if change == "layer":
        document.layers.new("OTHER")
        leader.dxf.layer = "OTHER"
    elif change == "color":
        leader.dxf.color = 1
    elif change == "true_color":
        leader.dxf.true_color = 0xFF0000
    elif change == "linetype":
        leader.dxf.linetype = "CONTINUOUS"
    elif change == "lineweight":
        leader.dxf.lineweight = 50
    elif change == "transparency":
        leader.dxf.transparency = 0x02000080
    elif change == "scale":
        leader.dxf.ltscale = 2.0
    else:
        leader.dxf.invisible = 1
    if edited:
        leader.vertices[0] = (1, 0, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm == ((1, 0) if edited else (0, 0))
    assert any("引线" in warning and "外观" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("change", ["spline", "no_arrow"])
def test_frame_leader_changed_kind_is_not_restored(tmp_path: Path, change: str) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "changed-kind.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    if change == "spline":
        leader.dxf.path_type = 1
    else:
        leader.dxf.has_arrowhead = 0
    document.saveas(path)

    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning and "修改" in warning for warning in result.report.warnings)
    assert bool(result.sketch.entities) == (change == "no_arrow")


def test_frame_leader_in_other_plane_is_not_restored(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "nonplanar-leader.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    leader = document.modelspace().query("LEADER")[0]
    leader.vertices[0] = (0, 0, 5)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning for warning in result.report.warnings)


def test_frame_leader_with_rotated_normal_is_not_restored(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    path = tmp_path / "rotated-normal.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.modelspace().query("LEADER")[0].dxf.normal_vector = (0, 1, 0)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].leader_target_mm is None
    assert any("引线" in warning for warning in result.report.warnings)


def test_frame_leader_is_not_silently_lost_on_dxf_export(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError

    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (10, 10), leader_target_mm=(0, 0)
    )
    with pytest.raises(ValidationError, match="引线"):
        write_sketches_dxf((), tmp_path / "frame-leader.dxf", tolerance_frames=(frame,))


def test_dxf_preserves_normal_datum_association(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=((-10, -6),),
        leader_auto_normal=True,
    )
    path = tmp_path / "normal-datum.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    restored = read_sketch_dxf(path).datum_identifiers[0]
    assert restored.attachment is not None
    assert restored.leader_auto_normal and restored.leader_offsets == datum.leader_offsets


def test_bent_datum_leader_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), leader_offsets=((-5, -5),))
    path = tmp_path / "bent-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    lines = list(document.blocks.get(insert.dxf.name).query("LINE"))
    assert len(lines) == 6
    assert read_sketch_dxf(path).datum_identifiers == (datum,)
    insert.dxf.insert = (20, 30, 0)
    document.saveas(path)
    moved = read_sketch_dxf(path).datum_identifiers[0]
    assert moved.position_mm == (20, 30)
    assert moved.target_mm == (10, 20)
    assert moved.leader_offsets == datum.leader_offsets
    scaled = read_sketch_dxf(path, unit_override="cm").datum_identifiers[0]
    assert scaled.position_mm == (200, 300)
    assert scaled.target_mm == (100, 200)
    assert scaled.leader_offsets == ((-50, -50),)


def test_datum_dxf_leader_does_not_cross_label_box(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (20, -20))
    path = tmp_path / "datum-leader.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    leader = document.blocks[insert.dxf.name].query("LINE")[0]
    assert leader.dxf.start.x > 0
    assert leader.dxf.start.y < 0
    assert tuple(leader.dxf.end)[:2] == pytest.approx((20, -20))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_datum_dxf_target_inside_box_roundtrips_without_leader(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (1, -1))
    path = tmp_path / "datum-inside.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks[insert.dxf.name]
    assert len(block.query("LINE")) == 4 and not block.query("SOLID")
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_damaged_compressed_datum_metadata_does_not_restore_stale_link(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (5, 5),
    )
    path = tmp_path / "damaged-compressed-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    document.modelspace().query("INSERT")[0].set_xdata("MYCAD_DATUM", [(1000, "Z1"), (1000, "!")])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.datum_identifiers
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert any("基准" in warning and "无法导入" in warning for warning in result.report.warnings)
    assert any("基准关联" in warning for warning in result.report.warnings)


def test_large_datum_metadata_is_bounded_and_roundtrips(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier

    style = TextStyle("datum-font", "字" * 80, font_file="arial.ttf")
    datum = DatumIdentifier(uuid4().hex, "%^" * 40, (0, 0), (0, -5), text_style_id=style.style_id)
    path = tmp_path / "large-datum.dxf"
    report = write_sketches_dxf(
        (), path, datum_identifiers=(datum,), text_styles=TextStyleTable((style,), style.style_id)
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("INSERT")[0]
    tags = native.get_xdata("MYCAD_DATUM")
    assert tags[0].value == "Z1"
    assert sum(len(str(tag.value).encode("utf-8")) + 4 for tag in tags) <= 14 * 1024
    assert any(
        "基准" in warning and "压缩" in warning and "旧版" in warning for warning in report.warnings
    )
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1
    restored = result.datum_identifiers[0]
    assert (restored.datum_id, restored.label, restored.position_mm, restored.target_mm) == (
        datum.datum_id,
        datum.label,
        datum.position_mm,
        datum.target_mm,
    )
    assert result.text_styles is not None and restored.text_style_id is not None
    assert result.text_styles.get(restored.text_style_id).font_file == style.font_file


def test_datum_dxf_block_expands_to_fit_long_label(tmp_path: Path) -> None:
    from ezdxf import bbox

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    datum = DatumIdentifier("de" * 16, "WIDE", (0, 0), (0, -10))
    path = tmp_path / "datum-width.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    blockref = document.modelspace().query("INSERT")[0]
    block = document.blocks[blockref.dxf.name]
    text = block.query("TEXT")[0]
    right = max(line.dxf.start.x for line in block.query("LINE"))
    assert bbox.extents([text]).extmax.x < right


@pytest.mark.parametrize("label", ("A%%d", "A^I", "X%%uY", "^", "A^", "测%%d量"))
def test_datum_special_characters_remain_literal_in_dxf(tmp_path: Path, label: str) -> None:
    from ezdxf.tools.text import plain_text

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    datum = DatumIdentifier("df" * 16, label, (0, 0), (0, -10))
    path = tmp_path / "datum-special.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks[insert.dxf.name]
    assert (
        "".join(
            plain_text(entity.dxf.text).rstrip(" ")
            if entity.dxf.text == "^  "
            else plain_text(entity.dxf.text)
            for entity in block.query("TEXT")
        )
        == label
    )
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_segmented_datum_block_edit_does_not_restore_stale_label(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    datum = DatumIdentifier("ef" * 16, "A%%d", (0, 0), (0, -10))
    path = tmp_path / "edited-segment.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    texts = list(document.blocks[insert.dxf.name].query("TEXT"))
    assert len(texts) > 1
    texts[1].dxf.text = "X"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.datum_identifiers
    assert any("基准" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("unknown", (False, True))
def test_external_tolerance_glyph_case_is_not_invented(tmp_path: Path, unknown: bool) -> None:
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    content = (
        r"{\Fgdt;J}%%v0.1%%v%%vA%%v%%v"
        if unknown
        else r"{\FGDT;j}%%v{\fGdt;n}0.05{\FGDT;m}%%v%%vA%%v%%v"
    )
    document.modelspace().new_entity("TOLERANCE", {"content": content, "insert": (2, 3)})
    path = tmp_path / "external-glyph-case.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    if unknown:
        assert not result.tolerance_frames
        assert any(
            "TOLERANCE" in warning and "无法导入" in warning for warning in result.report.warnings
        )
    else:
        assert len(result.tolerance_frames) == 1
        row = result.tolerance_frames[0].rows[0]
        assert row.characteristic == "position" and row.diameter and row.modifier == "M"


def test_inconsistent_frame_metadata_does_not_override_native_content(tmp_path: Path) -> None:
    import json

    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A"),)),), (10, 20)
    )
    path = tmp_path / "inconsistent-xdata.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads(
        "".join(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    )
    payload["frame"]["rows"][0]["value"] = 0.99
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata(
        "MYCAD_FCF", [(1000, raw[index : index + 240]) for index in range(0, len(raw), 240)]
    )
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.tolerance_frames) == 1
    assert imported.tolerance_frames[0].rows[0].value == 0.05
    assert any("元数据" in warning for warning in imported.report.warnings)


def test_malformed_frame_metadata_keeps_valid_native_tolerance(tmp_path: Path) -> None:
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.12, 2),), (10, 20))
    path = tmp_path / "malformed-xdata.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    entity.set_xdata("MYCAD_FCF", [(1000, "invalid json")])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.tolerance_frames) == 1
    assert result.tolerance_frames[0].rows == frame.rows
    assert any("元数据" in warning for warning in result.report.warnings)


def test_invalid_frame_font_metadata_does_not_reuse_saved_identity(tmp_path: Path) -> None:
    import json

    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.12, 2),), (10, 20))
    path = tmp_path / "invalid-font-xdata.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    payload = json.loads(
        "".join(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    )
    payload["implicit_font"] = {"invalid": True}
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    entity.set_xdata("MYCAD_FCF", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].frame_id != frame.frame_id
    assert result.tolerance_frames[0].rows == frame.rows
    assert any("元数据" in warning for warning in result.report.warnings)


def test_unchanged_frame_retains_unrounded_value_and_linked_datum(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.054, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    path = tmp_path / "unrounded-linked.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)
    assert result.datum_identifiers == (datum,)
    assert not any("元数据无效" in warning for warning in result.report.warnings)


def test_external_frame_edit_does_not_reuse_stale_datum_link(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    path = tmp_path / "changed-linked.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    native = document.modelspace().query("TOLERANCE")[0]
    native.dxf.content = native.dxf.content.replace("0.05", "0.10")
    document.saveas(path)
    result = read_sketch_dxf(path)
    restored = result.tolerance_frames[0]
    assert restored.frame_id == frame.frame_id and restored.rows[0].value == 0.1
    assert restored.rows[0].datums == (DatumReference("A"),)
    assert any("基准关联需重建" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("field", ("label", "target_mm", "position_mm"))
def test_inconsistent_datum_metadata_is_not_restored(tmp_path: Path, field: str) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 15))
    path = tmp_path / "inconsistent-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    payload = json.loads(
        "".join(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    )
    payload["datum"][field] = "B" if field == "label" else [20, 50]
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    insert.set_xdata("MYCAD_DATUM", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any(
        "基准图形块" in warning and "元数据" in warning for warning in imported.report.warnings
    )


def test_legacy_datum_single_text_with_literal_percent_still_imports(tmp_path: Path) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats import dxf_datum

    datum = DatumIdentifier(uuid4().hex, "A%B", (10, 20), (10, 15))
    path = tmp_path / "legacy-percent.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks[insert.dxf.name]
    for text in list(block.query("TEXT")):
        block.delete_entity(text)
    block.add_text(datum.label, dxfattribs={"insert": (0.8, -4.0), "height": 3.5})
    payload = json.loads(
        "".join(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    )
    signature = cast("Callable[[Any], list[object]]", vars(dxf_datum)["_signature"])
    payload["signature"] = signature(block)
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    insert.set_xdata("MYCAD_DATUM", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_large_datum_displacement_does_not_hide_metadata_mismatch(tmp_path: Path) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (1_000_000_000_000, 0))
    path = tmp_path / "large-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    payload = json.loads(
        "".join(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    )
    payload["datum"]["target_mm"][0] += 0.5
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    insert.set_xdata("MYCAD_DATUM", [(1000, raw[i : i + 240]) for i in range(0, len(raw), 240)])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any("元数据" in warning for warning in imported.report.warnings)


def test_frame_datum_id_with_conflicting_label_is_not_silently_relinked(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "B", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    path = tmp_path / "conflicting-label.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert imported.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert imported.datum_identifiers == (datum,)
    assert any("基准" in warning and "关联" in warning for warning in imported.report.warnings)


def test_duplicate_datum_id_cannot_be_used_to_resolve_frame_reference(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    identity = uuid4().hex
    first = DatumIdentifier(identity, "A", (0, 0), (0, -5))
    second = DatumIdentifier(identity, "B", (10, 0), (10, -5))
    row = ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", identity),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    path = tmp_path / "ambiguous-datum-id.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(first, second))
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert len(result.datum_identifiers) == 2
    assert len({item.datum_id for item in result.datum_identifiers}) == 2
    assert any("基准关联" in warning for warning in result.report.warnings)
    assert any("基准" in warning and "重复" in warning for warning in result.report.warnings)


def test_cross_kind_annotation_id_collision_is_reassigned_on_dxf_import(tmp_path: Path) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier

    identity = uuid4().hex
    datum = DatumIdentifier(identity, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        identity,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", identity),)),),
        (10, 20),
    )
    dimension = DetachedDimension(identity, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    path = tmp_path / "cross-kind-identities.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        reference_dimensions=(dimension,),
    )
    result = read_sketch_dxf(path)
    restored_frame = result.tolerance_frames[0]
    assert (
        len(
            {
                result.datum_identifiers[0].datum_id,
                restored_frame.frame_id,
                result.detached_dimensions[0].dimension_id,
            }
        )
        == 3
    )
    assert restored_frame.rows[0].datums == (DatumReference("A", identity),)
    assert any("身份" in warning and "重复" in warning for warning in result.report.warnings)


def test_duplicate_frame_ids_are_reassigned_without_losing_rows_or_links(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    row = ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    copied = replace(frame, position_mm=(20, 30))
    path = tmp_path / "copied-frame.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame, copied), datum_identifiers=(datum,))
    result = read_sketch_dxf(path)
    assert len(result.tolerance_frames) == 2
    assert len({item.frame_id for item in result.tolerance_frames}) == 2
    assert [item.position_mm for item in result.tolerance_frames] == [(10, 20), (20, 30)]
    assert all(item.rows == (row,) for item in result.tolerance_frames)
    assert any("公差框" in warning and "重复" in warning for warning in result.report.warnings)


def test_duplicate_datum_name_is_reported_and_conflicting_reference_is_unresolved(
    tmp_path: Path,
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    first = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    second = DatumIdentifier(uuid4().hex, "a", (10, 0), (10, -5))
    row = ToleranceRow("position", 0.05, 2, datums=(DatumReference("a", second.datum_id),))
    frame = FeatureControlFrame(uuid4().hex, (row,), (10, 20))
    path = tmp_path / "ambiguous-datum-label.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(first, second))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers == (first,)
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("a"),)
    assert any(
        "基准" in warning and "重复" in warning and "跳过" in warning
        for warning in result.report.warnings
    )


def test_copied_datum_with_same_name_and_id_does_not_restore_ambiguous_reference(
    tmp_path: Path,
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    copied = DatumIdentifier(datum.datum_id, "A", (10, 0), (10, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 20),
    )
    path = tmp_path / "copied-datum.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum, copied))
    result = read_sketch_dxf(path)
    assert result.datum_identifiers == (datum,)
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert any("跳过" in warning for warning in result.report.warnings)
    assert any("基准关联" in warning for warning in result.report.warnings)


def test_damaged_datum_becomes_unresolved_reference(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.05, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 20),
    )
    path = tmp_path / "damaged-datum.dxf"
    write_sketches_dxf((), path, tolerance_frames=(frame,), datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    document.blocks[insert.dxf.name].query("TEXT")[0].dxf.text = "B"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.datum_identifiers
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert any("基准关联" in warning for warning in result.report.warnings)


def test_external_short_native_tolerance_from_documented_draftsight_example(tmp_path: Path) -> None:
    document = cast("Callable[[str], Any]", vars(filemanagement)["new"])("R2010")
    document.header["$INSUNITS"] = 4
    document.modelspace().new_entity(
        "TOLERANCE", {"insert": (1, 2), "content": r"{\Fgdt;j}%%v{\Fgdt;n}0.7{\Fgdt;m}"}
    )
    path = tmp_path / "draftsight-short-tolerance.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.tolerance_frames) == 1
    assert result.tolerance_frames[0].rows == (ToleranceRow("position", 0.7, 1, True, "M"),)
    assert not any("无法导入" in warning for warning in result.report.warnings)


def test_cadcraft_moved_frame_keeps_resolved_datum_references() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-moved-frame.dxf"
    result = read_sketch_dxf(path)
    frame = next(item for item in result.tolerance_frames if len(item.rows) == 2)
    assert all(ref.datum_id is not None for row in frame.rows for ref in row.datums)
    assert not any("未关联" in warning for warning in result.report.warnings)


def test_cadcraft_edited_frame_reports_unresolved_datum_references() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-frame-edited.dxf"
    result = read_sketch_dxf(path)
    frame = next(item for item in result.tolerance_frames if len(item.rows) == 2)
    assert frame.rows[0].value == 0.25
    assert [ref.label for ref in frame.rows[0].datums] == ["A", "B", "C"]
    assert all(ref.datum_id is None for row in frame.rows for ref in row.datums)
    assert any("基准" in warning and "未关联" in warning for warning in result.report.warnings)


def test_cadcraft_created_multiline_native_tolerance_imports() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-0.20.1-multiline.dxf"
    result = read_sketch_dxf(path, unit_override="mm")
    assert len(result.tolerance_frames) == 1
    frame = result.tolerance_frames[0]
    assert frame.position_mm == (10, 20)
    assert frame.rows == (
        ToleranceRow(
            "position",
            0.12,
            2,
            True,
            "M",
            (DatumReference("A"), DatumReference("B", modifier="L"), DatumReference("C")),
        ),
        ToleranceRow("parallelism", 0.08, 2, False, "L", (DatumReference("A"),)),
    )
    assert any("基准" in warning and "未关联" in warning for warning in result.report.warnings)


def test_auto_routed_datum_dxf_missing_geometry_releases_route(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        attachment=attachment,
        leader_offsets=((-20, -17),),
        leader_auto_normal=True,
        leader_auto_route=True,
        layout_mode="shared",
    )
    path = tmp_path / "datum-auto-route.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    geometry = next(item for item in document.modelspace().query("LINE") if item.has_xdata("MYCAD"))
    document.modelspace().delete_entity(geometry)
    document.saveas(path)
    detached = read_sketch_dxf(path)
    assert detached.datum_identifiers[0].attachment is None
    assert not detached.datum_identifiers[0].leader_auto_normal
    assert not detached.datum_identifiers[0].leader_auto_route
    assert any("解除关联" in warning for warning in detached.report.warnings)


@pytest.mark.parametrize(("version", "algorithm"), [(24, 1), (25, 2)])
def test_cadcraft_automatic_leaders_preserve_routing_policy(version: int, algorithm: int) -> None:
    path = Path(__file__).parents[1] / f"fixtures/dxf/cadcraft-v{version}-autoroute-resaved.dxf"
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == len(result.tolerance_frames) == 1
    datum, frame = result.datum_identifiers[0], result.tolerance_frames[0]
    assert datum.position_mm == pytest.approx((30, 20))
    assert frame.position_mm == pytest.approx((80, 20))
    assert datum.target_mm == pytest.approx((10, 0))
    assert frame.leader_target_mm == pytest.approx((60, 0))
    for item in (datum, frame):
        assert item.leader_auto_normal and item.leader_auto_route
        assert item.route_avoid_crossing and item.route_track_target
        assert item.route_algorithm_version == algorithm
    assert any("依据唯一身份恢复" in warning for warning in result.report.warnings)


def test_datum_recorded_box_size_dxf_roundtrip_and_units(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(
        uuid4().hex, "A", (2, 3), (30, 0), layout_mode="shared", box_size_mm=(8, 5)
    )
    path = tmp_path / "datum-box-size.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers == (datum,)
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks.get(insert.dxf.name)
    outline = list(block.query("LINE"))[-4:]
    assert max(float(entity.dxf.start.x) for entity in outline) == pytest.approx(8)
    assert min(float(entity.dxf.start.y) for entity in outline) == pytest.approx(-5)
    scaled = read_sketch_dxf(path, unit_override="cm").datum_identifiers[0]
    assert scaled.box_size_mm == pytest.approx((80, 50))


def test_datum_recorded_box_size_rejects_inconsistent_dxf_metadata(tmp_path: Path) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    datum = DatumIdentifier(
        uuid4().hex, "A", (2, 3), (30, 0), layout_mode="shared", box_size_mm=(8, 5)
    )
    path = tmp_path / "changed-box-metadata.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    metadata = json.loads(unpack_annotation_metadata(values))
    metadata["datum"]["box_size_mm"] = [12, 5]
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, value) for value in pack_annotation_metadata(json.dumps(metadata))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.datum_identifiers
    assert any("基准" in warning and "元数据" in warning for warning in result.report.warnings)


def test_strict_box_aware_datum_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (13, 7), (18, -4))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    box = (0.0, 0.0, 5.212759544541193, -5.0)
    offsets = reroute_leader_around_box(
        (0, 0), ((10, 15), (2, 2)), (2, 2), (13, 7), box, orthogonal_box_side=True
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 0),
        (13, 7),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
        leader_offsets=offsets,
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=4,
        layout_mode="shared",
        box_size_mm=(box[2], -box[3]),
    )
    path = tmp_path / "orthogonal-datum.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_external_datum_single_letter_edit_restores_datum_and_unlinks_old_reference(
    tmp_path: Path,
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (10, 20), (10, 10), layout_mode="shared")
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (25, 20),
    )
    path = tmp_path / "external-datum-rename.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,), tolerance_frames=(frame,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    text = document.blocks[insert.dxf.name].query("TEXT")[0]
    text.dxf.text = "B"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.datum_identifiers) == 1, imported.report.warnings
    restored = imported.datum_identifiers[0]
    assert restored.datum_id == datum.datum_id and restored.label == "B"
    assert restored.target_mm == datum.target_mm and restored.position_mm == datum.position_mm
    assert restored.box_size_mm is not None
    assert imported.tolerance_frames[0].rows[0].datums == (DatumReference("A"),)
    assert any("名称" in warning and "修改" in warning for warning in imported.report.warnings)
    assert any("基准关联" in warning for warning in imported.report.warnings)
    assert not imported.texts


@pytest.mark.parametrize(
    "case", ["geometry", "extra_text", "metadata", "wide", "control", "color", "hidden"]
)
def test_external_datum_rename_rejects_ambiguous_or_modified_block(
    tmp_path: Path, case: str
) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    datum = DatumIdentifier(
        uuid4().hex, "I" if case == "wide" else "A", (10, 20), (10, 10), layout_mode="shared"
    )
    path = tmp_path / f"invalid-datum-rename-{case}.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks[insert.dxf.name]
    text = block.query("TEXT")[0]
    text.dxf.text = "W" if case == "wide" else "B^J" if case == "control" else "B"
    if case == "geometry":
        line = block.query("LINE")[0]
        line.dxf.start = (1, 1, 0)
    elif case == "extra_text":
        block.add_text("X")
    elif case == "color":
        text.dxf.color = 1
    elif case == "hidden":
        text.dxf.invisible = 1
    elif case == "metadata":
        values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
        payload = json.loads(unpack_annotation_metadata(values))
        payload["datum"]["label"] = "Z"
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        insert.set_xdata("MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(data)])
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.datum_identifiers
    assert any("基准" in warning and "无法" in warning for warning in imported.report.warnings)
    assert imported.texts


def test_external_datum_rename_scales_original_box_and_location(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 1), layout_mode="shared")
    path = tmp_path / "inch-datum-rename.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    block = document.blocks[insert.dxf.name]
    width = max(float(item.dxf.start.x) for item in list(block.query("LINE"))[-4:])
    block.query("TEXT")[0].dxf.text = "B"
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    imported = read_sketch_dxf(path)
    restored = imported.datum_identifiers[0]
    assert restored.label == "B"
    assert restored.position_mm == pytest.approx((25.4, 50.8))
    assert restored.target_mm == pytest.approx((25.4, 25.4))
    assert restored.box_size_mm == pytest.approx((width * 25.4, 5 * 25.4))


@pytest.mark.parametrize(
    ("original", "new"), [("A1", "b2"), ("BASE-1", "BASE_2"), ("基准甲", "基准乙")]
)
def test_external_datum_plain_name_edit_recovers_when_text_fits(
    tmp_path: Path, original: str, new: str
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(
        uuid4().hex, original, (10, 20), (10, 10), layout_mode="shared", box_size_mm=(50, 5)
    )
    path = tmp_path / "plain-name-edit.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    document.blocks[insert.dxf.name].query("TEXT")[0].dxf.text = new
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1, result.report.warnings
    assert result.datum_identifiers[0].label == new
    assert result.datum_identifiers[0].box_size_mm == pytest.approx((50, 5))
    assert any("名称" in item and "修改" in item for item in result.report.warnings)


def test_external_segmented_datum_name_edit_preserves_literal_control_characters(
    tmp_path: Path,
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(
        uuid4().hex, "A%%d", (0, 0), (0, -10), layout_mode="shared", box_size_mm=(60, 5)
    )
    path = tmp_path / "segmented-name.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    texts = list(document.blocks[insert.dxf.name].query("TEXT"))
    assert [item.dxf.text for item in texts] == ["A", "%", "%", "d"]
    texts[-1].dxf.text = "e"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1, result.report.warnings
    assert result.datum_identifiers[0].label == "A%%e"
    assert any("名称" in warning and "修改" in warning for warning in result.report.warnings)


def test_external_segmented_datum_name_edit_with_overlapping_parts_degrades(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(
        uuid4().hex, "A%%d", (0, 0), (0, -10), layout_mode="shared", box_size_mm=(60, 5)
    )
    path = tmp_path / "overlapping-datum.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = document.modelspace().query("INSERT")[0]
    document.blocks[insert.dxf.name].query("TEXT")[0].dxf.text = "WWWW"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.datum_identifiers
    assert any("片段重叠" in warning for warning in result.report.warnings)
    assert result.texts


def test_cadcraft_block_edited_datum_retains_value_and_unlinks_old_reference() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-datum-renamed.dxf"
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1
    datum = result.datum_identifiers[0]
    assert datum.datum_id == "a" * 32 and datum.label == "B"
    assert datum.position_mm == pytest.approx((10, 20))
    assert datum.target_mm == pytest.approx((10, 10))
    assert datum.box_size_mm == pytest.approx((8, 5))
    assert len(result.tolerance_frames) == 1
    frame = result.tolerance_frames[0]
    assert frame.frame_id == "b" * 32
    assert frame.rows[0].datums == (DatumReference("A"),)
    assert any("名称" in warning and "修改" in warning for warning in result.report.warnings)
    assert any("基准关联" in warning for warning in result.report.warnings)


def test_cadcraft_resaved_adaptive_annotation_keeps_layer_and_datum_reference() -> None:
    from mycad.core.sketch_layers import SketchLayer

    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-adaptive-annotation.dxf"
    result = read_sketch_dxf(path)
    assert result.sketch.layers.get("0").color_rgb == SketchLayer("0").color_rgb
    assert result.datum_identifiers[0].datum_id == "a" * 32
    assert result.datum_identifiers[0].label == "A"
    assert result.tolerance_frames[0].rows[0].datums == (DatumReference("A", "a" * 32),)


def test_cadcraft_resaved_current_automatic_datum_and_frame_preserve_attachment() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-v27-autoroute-resaved.dxf"
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1 and len(result.tolerance_frames) == 1
    datum, frame = result.datum_identifiers[0], result.tolerance_frames[0]
    assert datum.label == "A" and datum.route_algorithm_version == 4
    assert datum.leader_auto_route and datum.attachment is not None
    assert datum.position_mm == pytest.approx((30, 20))
    assert datum.target_mm == pytest.approx((10, 0))
    assert datum.box_size_mm == pytest.approx((5.212759544541193, 5.0))
    assert frame.route_algorithm_version == 2 and frame.leader_auto_route
    assert frame.leader_attachment is not None
    assert frame.position_mm == pytest.approx((80, 20))
    assert frame.leader_target_mm == pytest.approx((60, 0))
    assert any("原生关联缺失" in warning for warning in result.report.warnings)


def test_frame_arrow_style_dxf_roundtrip_reports_legacy_shape_difference(tmp_path: Path) -> None:
    from dataclasses import replace

    legacy = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
    )
    modern = replace(legacy, leader_arrow_style="closed_filled")
    for frame, expected_warning in ((legacy, True), (modern, False)):
        path = tmp_path / f"{frame.leader_arrow_style}.dxf"
        report = write_sketches_dxf((), path, tolerance_frames=(frame,))
        assert (
            any("旧式" in warning and "箭头" in warning for warning in report.warnings)
            is expected_warning
        )
        assert read_sketch_dxf(path).tolerance_frames == (frame,)


def test_cadcraft_resaved_closed_filled_frame_preserves_style_and_attachment() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures/dxf"
    original = read_sketch_dxf(fixtures / "mycad-v28-autoroute-source.dxf")
    resaved = read_sketch_dxf(fixtures / "cadcraft-v28-autoroute-resaved.dxf")
    assert resaved.datum_identifiers == original.datum_identifiers
    assert resaved.tolerance_frames == original.tolerance_frames
    frame = resaved.tolerance_frames[0]
    assert frame.leader_arrow_style == "closed_filled"
    assert frame.leader_auto_route and frame.leader_attachment is not None
    assert any("原生关联缺失" in warning for warning in resaved.report.warnings)


@pytest.mark.parametrize("kind", ["route", "normal"])
def test_cadcraft_resaved_legacy_hidden_constraints_recover_by_unique_identity(kind: str) -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf" / f"cadcraft-legacy-hidden-{kind}.dxf"
    result = read_sketch_dxf(path)
    frame = result.tolerance_frames[0]
    assert frame.frame_id == "c" * 32
    assert frame.leader_auto_normal and frame.leader_auto_route
    assert frame.leader_attachment is not None
    assert frame.leader_anchor_offset is None
    assert frame.leader_offsets == (((8, -3), (-20, -15)) if kind == "route" else ((2, -3),))
    assert any("原生关联缺失" in warning for warning in result.report.warnings)
    assert not any("无法核验" in warning for warning in result.report.warnings)


def test_native_frame_leader_export_warns_about_external_frame_layout(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -3),
    )
    report = write_sketches_dxf((), tmp_path / "frame.dxf", tolerance_frames=(frame,))
    assert any("目标 CAD" in warning and "间隙" in warning for warning in report.warnings)


@pytest.mark.parametrize("kind", ["route", "normal"])
@pytest.mark.parametrize(
    "change", ["duplicate_leader", "wrong_handle", "duplicate_frame", "arrow", "color"]
)
def test_cadcraft_legacy_hidden_constraints_reject_ambiguous_identity(
    tmp_path: Path, kind: str, change: str
) -> None:
    source = Path(__file__).parents[1] / "fixtures/dxf" / f"cadcraft-legacy-hidden-{kind}.dxf"
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(source)
    space = document.modelspace()
    leader = space.query("LEADER")[0]
    if change == "duplicate_leader":
        space.add_entity(leader.copy())
    elif change == "wrong_handle":
        leader.dxf.annotation_handle = space.query("LINE")[0].dxf.handle
    elif change == "duplicate_frame":
        space.add_entity(space.query("TOLERANCE")[0].copy())
    elif change == "arrow":
        document.blocks.new("CUSTOM_LEADER_ARROW").add_line((0, 0), (1, 1))
        override = leader.override()
        override["dimldrblk"] = "CUSTOM_LEADER_ARROW"
        override.commit()
    else:
        leader.dxf.color = 1
    path = tmp_path / "ambiguous.dxf"
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert all(not frame.leader_auto_route for frame in result.tolerance_frames)
    assert any("引线" in warning or "身份" in warning for warning in result.report.warnings)


def test_legacy_frame_export_uses_supplied_anchor_without_mutating_frame(tmp_path: Path) -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((-10, -5),),
    )
    path = tmp_path / "legacy-frame.dxf"
    report = write_sketches_dxf(
        (), path, tolerance_frames=(frame,), legacy_frame_anchors={frame.frame_id: (1, -2)}
    )
    assert frame.leader_anchor_offset is None
    assert any("字体" in warning and "锚点" in warning for warning in report.warnings)
    restored = read_sketch_dxf(path).tolerance_frames[0]
    assert restored.leader_target_mm == frame.leader_target_mm
    assert restored.leader_offsets == frame.leader_offsets
    assert restored.leader_anchor_offset == (1, -2)


@pytest.mark.parametrize("bad_anchor", ["missing", "unknown", "nonfinite", "already_anchored"])
def test_legacy_frame_export_rejects_invalid_anchors_without_overwriting(
    tmp_path: Path, bad_anchor: str
) -> None:
    from dataclasses import replace

    from mycad.core.exceptions import ValidationError

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
    )
    anchors = {frame.frame_id: (1.0, -2.0)}
    if bad_anchor == "missing":
        anchors = {}
    elif bad_anchor == "unknown":
        anchors = {uuid4().hex: (1.0, -2.0)}
    elif bad_anchor == "nonfinite":
        anchors = {frame.frame_id: (float("nan"), -2.0)}
    else:
        frame = replace(frame, leader_anchor_offset=(1, -2))
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="锚点"):
        write_sketches_dxf((), path, tolerance_frames=(frame,), legacy_frame_anchors=anchors)
    assert path.read_bytes() == b"existing"


def test_legacy_anchor_snapshot_does_not_change_other_frames(tmp_path: Path) -> None:
    legacy = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
    )
    modern = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (40, 20),
        leader_target_mm=(30, 0),
        leader_anchor_offset=(0, -3),
        leader_arrow_style="closed_filled",
    )
    path = tmp_path / "mixed-frames.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(legacy, modern),
        legacy_frame_anchors={legacy.frame_id: (0, -3)},
    )
    restored = read_sketch_dxf(path).tolerance_frames
    assert restored[0].leader_anchor_offset == (0, -3)
    assert restored[1] == modern


@pytest.mark.parametrize("bad_skip", [-1, 2, True])
def test_legacy_export_rejects_invalid_hidden_vertex_count(tmp_path: Path, bad_skip: int) -> None:
    from mycad.core.exceptions import ValidationError

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3),),
    )
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="顶点"):
        write_sketches_dxf(
            (),
            path,
            tolerance_frames=(frame,),
            legacy_frame_anchors={frame.frame_id: (0, -3)},
            legacy_frame_skipped_vertices={frame.frame_id: bad_skip},
        )
    assert path.read_bytes() == b"existing"


@pytest.mark.parametrize("auto_route", [False, True])
def test_legacy_export_rejects_skipping_automatic_normal_vertex(
    tmp_path: Path, auto_route: bool
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-10, -5)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=auto_route,
    )
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="自动约束"):
        write_sketches_dxf(
            (),
            path,
            tolerance_frames=(frame,),
            legacy_frame_anchors={frame.frame_id: (0, -3)},
            legacy_frame_skipped_vertices={frame.frame_id: 2},
        )
    assert path.read_bytes() == b"existing"


def test_legacy_export_preserves_normal_when_only_box_side_vertex_is_hidden(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    path = tmp_path / "normal-with-hidden-vertex.dxf"
    report = write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (0, -3)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
    )
    result = read_sketch_dxf(path)
    imported = result.tolerance_frames[0]
    assert imported.leader_offsets == ((-20, -15),)
    assert imported.leader_attachment == attachment
    assert imported.leader_auto_normal
    assert any("顶点未写入可见路径" in warning for warning in report.warnings)
    assert frame.leader_offsets == ((1, -3), (-20, -15))
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="sketch")
    app.commit_new_sketch(services, loaded, result.sketch, session_identity=0)
    loaded.bus.execute("drawing.tolerance.batch", {"add_frames": [imported.to_mapping()]}, "local")
    revised_line = replace(line, end_mm=(5, 10))
    revised = replace(result.sketch, entities=(revised_line,))
    state = revised.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": result.sketch.sketch_id,
                    "base_state_sha256": result.sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    updated = services.kernel.drawing_tolerance_frames[0]
    assert updated.leader_auto_normal and updated.leader_attachment is not None
    assert updated.leader_target_mm == pytest.approx((0, 5))
    assert updated.leader_offsets[-1] == pytest.approx((-20 - 5 / 2**0.5, -15 + 5 / 2**0.5))


def test_legacy_auto_route_hidden_vertex_survives_dxf_roundtrip(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "legacy-auto-route.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (0, -3)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
    )
    result = read_sketch_dxf(path)
    assert result.tolerance_frames == (frame,)

    def after_rotation(source: FeatureControlFrame) -> FeatureControlFrame:
        from mycad.core.persistence import save_document

        services = app.build_app(discoverers=())
        loaded = app.new_workspace_document(services, kind="sketch")
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [source.to_mapping()]}, "local"
        )
        revised = replace(sketch, entities=(replace(line, end_mm=(5, 10)),))
        state = revised.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
        updated = services.kernel.drawing_tolerance_frames[0]
        loaded.bus.undo_operation()
        assert services.kernel.drawing_tolerance_frames == (source,)
        loaded.bus.redo_operation()
        archive = tmp_path / "legacy-route.my2d"
        save_document(loaded.document, archive)
        reopened = app.build_app(discoverers=())
        app.open_app_document(reopened, archive)
        assert reopened.kernel.drawing_tolerance_frames == (updated,)
        return updated

    assert after_rotation(result.tolerance_frames[0]) == after_rotation(frame)


def test_legacy_auto_route_rejects_hidden_vertex_outside_provable_cell(tmp_path: Path) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((8, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"original")
    with pytest.raises(ValidationError, match="隐藏顶点无法安全核验"):
        write_sketches_dxf(
            (),
            path,
            tolerance_frames=(frame,),
            legacy_frame_anchors={frame.frame_id: (0, -3)},
            legacy_frame_skipped_vertices={frame.frame_id: 1},
        )
    assert path.read_bytes() == b"original"


def test_legacy_auto_route_restores_text_cell_vertex_with_verified_layout(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((8, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "text-cell-route.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (2.5, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    assert read_sketch_dxf(path).tolerance_frames == (frame,)


@pytest.mark.parametrize("route_version", [0, 1, 2])
def test_legacy_hidden_normal_vertex_roundtrips_with_full_layout_evidence(
    tmp_path: Path, route_version: int
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-3, -2), (7, -2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 6),
        leader_target_mm=(2, -2),
        leader_offsets=((2, -3),),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=route_version > 0,
        route_avoid_crossing=route_version == 2,
        route_track_target=route_version == 2,
        route_algorithm_version=max(1, route_version),
    )
    path = tmp_path / "hidden-normal.dxf"
    report = write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (5.2, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    assert any("约束" in warning and "扩展数据" in warning for warning in report.warnings)
    assert read_sketch_dxf(path).tolerance_frames == (frame,)


@pytest.mark.parametrize(
    "change",
    [
        "leader",
        "source",
        "bounds",
        "vertex",
        "duplicate",
        "unit",
        "font",
        "rotation",
        "content",
        "conflict",
        "drop_hidden",
    ],
)
def test_legacy_hidden_normal_requires_unchanged_evidence(tmp_path: Path, change: str) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    line = LineEntity(uuid4().hex, (-3, -2), (7, -2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 6),
        leader_target_mm=(2, -2),
        leader_offsets=((2, -3),),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "modified-hidden-normal.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (5.2, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    entity = space.query("TOLERANCE")[0]
    leader = space.query("LEADER")[0]
    if change == "leader":
        leader.vertices[0] = (3, -2, 0)
    elif change == "source":
        space.query("LINE")[0].dxf.end = (7, 8, 0)
    elif change == "duplicate":
        space.add_entity(entity.copy())
    elif change == "unit":
        document.header["$INSUNITS"] = 1
    elif change == "font":
        document.dimstyles.get(entity.dxf.dimstyle).dxf.dimtxt = 7
    elif change == "rotation":
        entity.dxf.x_axis_vector = (0, 1, 0)
    elif change == "content":
        entity.dxf.content = entity.dxf.content.replace("0.10", "0.20")
    else:
        values = tuple(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
        metadata = json.loads(unpack_annotation_metadata(values))
        if change == "bounds":
            del metadata["legacy_hidden_normal_bounds"]
        elif change == "vertex":
            metadata["legacy_hidden_normal"]["leader_offsets"][0] = [900, 900]
        elif change == "drop_hidden":
            del metadata["legacy_hidden_normal"]
        else:
            metadata["legacy_auto_route"] = metadata["legacy_hidden_normal"]
        entity.set_xdata(
            "MYCAD_FCF", [(1000, part) for part in pack_annotation_metadata(json.dumps(metadata))]
        )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.tolerance_frames[0].leader_auto_normal
    assert not result.tolerance_frames[0].leader_auto_route
    if change != "drop_hidden":
        assert any("约束" in warning or "附着" in warning for warning in result.report.warnings)


@pytest.mark.parametrize("auto_route", [False, True])
def test_restored_hidden_normal_follows_target_like_original(
    tmp_path: Path, auto_route: bool
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-3, -2), (7, -2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (0, 6),
        leader_target_mm=(2, -2),
        leader_offsets=((2, -3),),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=auto_route,
    )
    path = tmp_path / "hidden-normal.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (5.2, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    restored = read_sketch_dxf(path).tolerance_frames[0]

    def revise(source: FeatureControlFrame) -> FeatureControlFrame:
        services = app.build_app(discoverers=())
        loaded = app.new_workspace_document(services, kind="sketch")
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_frames": [source.to_mapping()]}, "local"
        )
        revised = replace(sketch, entities=(replace(line, end_mm=(7, 4)),))
        state = revised.to_state_mapping()
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
        updated = services.kernel.drawing_tolerance_frames[0]
        loaded.bus.undo_operation()
        assert services.kernel.drawing_tolerance_frames == (source,)
        loaded.bus.redo_operation()
        assert services.kernel.drawing_tolerance_frames == (updated,)
        return updated

    assert revise(restored) == revise(frame)


@pytest.mark.parametrize("change", ["anchor", "height", "width", "count", "bounds_identity"])
def test_legacy_auto_route_rejects_inconsistent_layout_snapshot(
    tmp_path: Path, change: str
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((8, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    anchor = (3.0, -6.0) if change == "anchor" else (2.5, -6.0)
    bounds = (0.0, 0.0, 20.0, 8.0 if change == "height" else 6.0)
    if change == "width":
        bounds = (0.0, 0.0, 6.0, 6.0)
    bounds_id = uuid4().hex if change == "bounds_identity" else frame.frame_id
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"original")
    with pytest.raises(ValidationError, match="顶点|锚点"):
        write_sketches_dxf(
            (),
            path,
            tolerance_frames=(frame,),
            legacy_frame_anchors={frame.frame_id: anchor},
            legacy_frame_skipped_vertices={frame.frame_id: 0 if change == "count" else 1},
            legacy_frame_bounds={bounds_id: bounds},
        )
    assert path.read_bytes() == b"original"


@pytest.mark.parametrize("change", ["width", "height", "missing", "nonfinite"])
def test_legacy_auto_route_rejects_modified_layout_metadata(tmp_path: Path, change: str) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((8, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "modified-layout.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (2.5, -6)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
        legacy_frame_bounds={frame.frame_id: (0, 0, 20, 6)},
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    entity = document.modelspace().query("TOLERANCE")[0]
    values = tuple(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
    metadata = json.loads(unpack_annotation_metadata(values))
    if change == "missing":
        del metadata["legacy_auto_route_bounds"]
    elif change == "nonfinite":
        metadata["legacy_auto_route_bounds"][2] = float("inf")
    else:
        metadata["legacy_auto_route_bounds"][2 if change == "width" else 3] += 1
    entity.set_xdata(
        "MYCAD_FCF", [(1000, part) for part in pack_annotation_metadata(json.dumps(metadata))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.tolerance_frames[0].leader_auto_route
    assert any("自动布线无法核验" in warning for warning in result.report.warnings)


def test_legacy_auto_route_retains_versioned_policy_in_metadata(tmp_path: Path) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=2,
    )
    path = tmp_path / "versioned-route.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (0, -3)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
    )
    assert read_sketch_dxf(path).tolerance_frames == (frame,)


@pytest.mark.parametrize(
    "change",
    [
        "leader",
        "unit",
        "source",
        "font",
        "position",
        "rotation",
        "content",
        "legacy_metadata",
        "null_legacy",
        "drop_legacy",
        "duplicate",
    ],
)
def test_legacy_auto_route_is_not_restored_when_evidence_changes(
    tmp_path: Path, change: str
) -> None:
    import json

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    line = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((1, -3), (-20, -15)),
        leader_attachment=attachment,
        leader_auto_normal=True,
        leader_auto_route=True,
    )
    path = tmp_path / "modified-auto-route.dxf"
    write_sketches_dxf(
        (sketch,),
        path,
        tolerance_frames=(frame,),
        legacy_frame_anchors={frame.frame_id: (0, -3)},
        legacy_frame_skipped_vertices={frame.frame_id: 1},
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    leader = space.query("LEADER")[0]
    if change == "leader":
        leader.vertices[1] = (1, 5, 0)
    elif change == "unit":
        document.header["$INSUNITS"] = 1
    elif change == "source":
        space.query("LINE")[0].dxf.end = (5, 10, 0)
    elif change == "font":
        native = space.query("TOLERANCE")[0]
        document.dimstyles.get(native.dxf.dimstyle).dxf.dimtxt = 7
    elif change == "position":
        space.query("TOLERANCE")[0].dxf.insert = (21, 20, 0)
    elif change == "rotation":
        space.query("TOLERANCE")[0].dxf.x_axis_vector = (0, 1, 0)
    elif change == "content":
        native = space.query("TOLERANCE")[0]
        native.dxf.content = native.dxf.content.replace("0.10", "0.20")
    elif change == "duplicate":
        space.add_entity(space.query("TOLERANCE")[0].copy())
    else:
        entity = space.query("TOLERANCE")[0]
        values = tuple(tag.value for tag in entity.get_xdata("MYCAD_FCF") if tag.code == 1000)
        metadata = json.loads(unpack_annotation_metadata(values))
        if change == "drop_legacy":
            del metadata["legacy_auto_route"]
        elif change == "null_legacy":
            metadata["legacy_auto_route"] = None
        else:
            metadata["legacy_auto_route"]["leader_offsets"][0] = [900, 900]
        entity.set_xdata(
            "MYCAD_FCF", [(1000, part) for part in pack_annotation_metadata(json.dumps(metadata))]
        )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert not result.tolerance_frames[0].leader_auto_route
    if change != "drop_legacy":
        assert any(
            "自动布线" in warning or "附着" in warning or "法向" in warning
            for warning in result.report.warnings
        )


def test_cadcraft_resaved_native_legacy_datum_retains_identity_and_geometry() -> None:
    path = Path(__file__).parents[1] / "fixtures/dxf/cadcraft-native-legacy-datum.dxf"
    result = read_sketch_dxf(path)
    assert len(result.datum_identifiers) == 1
    datum = result.datum_identifiers[0]
    assert datum.datum_id == "d" * 32
    assert datum.label == "B8"
    assert datum.layout_mode == "legacy"
    assert datum.position_mm == pytest.approx((10, 10))
    assert datum.target_mm == pytest.approx((55, 0))
    assert not result.report.warnings


def test_datum_dxf_does_not_reuse_conflicting_frame_style_identity(tmp_path: Path) -> None:
    import json

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.formats.dxf_xdata import pack_annotation_metadata, unpack_annotation_metadata

    frame_style = TextStyle("frame", "框字体", font_family="DejaVu Sans")
    datum_style = TextStyle("datum", "基准字体", font_family="DejaVu Serif")
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0), text_style_id="frame"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), text_style_id="datum")
    path = tmp_path / "style-conflict.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((frame_style, datum_style), "frame"),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    insert = list(document.modelspace().query("INSERT"))[0]
    values = tuple(tag.value for tag in insert.get_xdata("MYCAD_DATUM") if tag.code == 1000)
    payload = json.loads(unpack_annotation_metadata(values))
    payload["datum"]["text_style_id"] = "frame"
    insert.set_xdata(
        "MYCAD_DATUM", [(1000, part) for part in pack_annotation_metadata(json.dumps(payload))]
    )
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.text_styles is not None
    restored = result.datum_identifiers[0]
    assert restored.text_style_id != "frame" and restored.text_style_id is not None
    assert result.text_styles.get(restored.text_style_id).font_family == "DejaVu Serif"
    assert result.text_styles.get("frame").font_family == "DejaVu Sans"
    assert any("基准" in warning and "样式" in warning for warning in result.report.warnings)


def test_datum_and_frame_share_style_when_datum_precedes_frame_in_dxf(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow

    style = TextStyle("shared", "共同字体", font_family="DejaVu Sans", height_mm=5)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0), text_style_id="shared"
    )
    datum = DatumIdentifier(uuid4().hex, "A", (10, 10), (0, 0), text_style_id="shared")
    path = tmp_path / "datum-first.dxf"
    write_sketches_dxf(
        (),
        path,
        tolerance_frames=(frame,),
        datum_identifiers=(datum,),
        text_styles=TextStyleTable((style,), "shared"),
    )
    document = cast("Callable[[Path], Any]", vars(filemanagement)["readfile"])(path)
    space = document.modelspace()
    tolerance = list(space.query("TOLERANCE"))[0]
    space.unlink_entity(tolerance)
    space.add_entity(tolerance)
    document.saveas(path)
    result = read_sketch_dxf(path)
    assert result.tolerance_frames[0].text_style_id == "shared"
    assert result.datum_identifiers[0].text_style_id == "shared"
