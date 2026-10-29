# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real external DXF templates, including blocks, units and portable library files."""

from pathlib import Path

import pytest

from mycad.core.drawing_projection import LineCurve
from mycad.core.drawing_templates import builtin_template
from mycad.formats.drawing_templates import TemplateLibrary, import_dxf_template
from tests.helpers.template_dxf import new_dxf


def test_import_inches_block_attributes_and_rotation(tmp_path: Path) -> None:
    document = new_dxf("R2010", units=1)
    block = document.blocks.new("TITLE")
    block.add_line((0, 0), (4, 0))
    block.add_attdef("DRAWING_NO", (1, 1), height=0.1)
    insert = document.modelspace().add_blockref("TITLE", (1, 1))
    insert.add_auto_attribs({"DRAWING_NO": "X-10"})
    document.modelspace().add_text(
        "ROTATED", dxfattribs={"insert": (2, 2), "height": 0.1, "rotation": 90}
    )
    path = tmp_path / "ansi.dxf"
    document.saveas(path)
    template = import_dxf_template(path, name="ASME 企业模板", size_mm=(279.4, 215.9))
    assert template.curves[0] == LineCurve((25.4, 25.4), (127, 25.4))
    assert any(t.field == "DRAWING_NO" and t.text == "X-10" for t in template.texts)
    assert any(t.rotation_deg == 90 and t.height_mm == pytest.approx(2.54) for t in template.texts)
    library = TemplateLibrary(tmp_path / "library")
    library.save(template)
    path.unlink()
    templates, issues = library.load()
    assert templates == (template,)
    assert not issues


def test_unknown_unit_and_unsupported_entity_fail_explicitly(tmp_path: Path) -> None:
    document = new_dxf("R2010", units=0)
    document.modelspace().add_line((0, 0), (10, 10))
    path = tmp_path / "unknown.dxf"
    document.saveas(path)
    with pytest.raises(ValueError, match="单位"):
        import_dxf_template(path, name="Test", size_mm=(297, 210))
    assert import_dxf_template(path, name="Test", size_mm=(297, 210), unit="mm")
    document.modelspace().add_point((10, 10))
    document.saveas(path)
    with pytest.raises(ValueError, match="POINT"):
        import_dxf_template(path, name="Test", size_mm=(297, 210), unit="mm")


def test_layout_selection_and_offset(tmp_path: Path) -> None:
    document = new_dxf("R2010", units=4)
    document.modelspace().add_line((0, 0), (10, 0))
    document.layouts.get("Layout1").add_line((50, 50), (150, 50))
    path = tmp_path / "layout.dxf"
    document.saveas(path)
    template = import_dxf_template(
        path, name="Paper", size_mm=(297, 210), layout="Layout1", offset_mm=(-50, -50)
    )
    assert template.curves == (LineCurve((0, 0), (100, 0)),)
    with pytest.raises(ValueError, match="幅面"):
        import_dxf_template(path, name="Paper", size_mm=(100, 100), layout="Layout1")


def test_corrupt_library_does_not_hide_valid_templates(tmp_path: Path) -> None:
    library = TemplateLibrary(tmp_path)
    template = builtin_template("GB", "A4")
    library.save(template)
    (tmp_path / "broken.json").write_text('{"version":999}', encoding="utf-8")
    templates, issues = library.load()
    assert templates == (template,)
    assert len(issues) == 1 and "broken.json" in issues[0]


def test_malformed_file_and_text_outside_sheet_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.dxf"
    path.write_text("not a drawing", encoding="utf-8")
    with pytest.raises(ValueError, match="DXF"):
        import_dxf_template(path, name="Broken", size_mm=(297, 210))
    document = new_dxf()
    document.modelspace().add_line((0, 0), (10, 0))
    document.modelspace().add_text("outside", dxfattribs={"insert": (500, 500), "height": 3})
    document.saveas(path)
    with pytest.raises(ValueError, match="幅面"):
        import_dxf_template(path, name="Outside", size_mm=(297, 210))


def test_nested_rotated_scaled_block_keeps_geometry(tmp_path: Path) -> None:
    document = new_dxf()
    block = document.blocks.new("FRAME")
    block.add_line((0, 0), (10, 0))
    outer = document.blocks.new("OUTER")
    outer.add_blockref("FRAME", (5, 0))
    document.modelspace().add_blockref(
        "OUTER", (50, 50), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2, "zscale": 2}
    )
    path = tmp_path / "nested.dxf"
    document.saveas(path)
    template = import_dxf_template(path, name="Rotated", size_mm=(297, 210))
    curve = template.curves[0]
    assert isinstance(curve, LineCurve)
    assert curve.start == pytest.approx((50, 60))
    assert curve.end == pytest.approx((50, 80))


def test_constant_block_text_is_preserved(tmp_path: Path) -> None:
    document = new_dxf()
    block = document.blocks.new("TITLE")
    block.add_line((0, 0), (20, 0))
    block.add_attdef("COMPANY", (2, 3), height=2, text="CONST", dxfattribs={"flags": 2})
    document.modelspace().add_blockref("TITLE", (10, 10))
    path = tmp_path / "constant.dxf"
    document.saveas(path)
    template = import_dxf_template(path, name="Constant", size_mm=(297, 210))
    assert len(template.texts) == 1
    assert template.texts[0].text == "CONST"
    assert template.texts[0].position_mm == (12, 15)


def test_classic_polyline_width_is_rejected(tmp_path: Path) -> None:
    document = new_dxf()
    document.modelspace().add_polyline2d(
        [(10, 10), (50, 10)], dxfattribs={"default_start_width": 5, "default_end_width": 5}
    )
    path = tmp_path / "wide.dxf"
    document.saveas(path)
    with pytest.raises(ValueError, match="宽度"):
        import_dxf_template(path, name="Wide", size_mm=(297, 210))
