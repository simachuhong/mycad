# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Radial DXF suppression must preserve the unaffected annotation parts."""

from pathlib import Path
from uuid import uuid4

import ezdxf
import pytest

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize("kind", ("radius", "diameter"))
def test_first_side_suppression_keeps_mark_and_opposite_arrow(tmp_path: Path, kind: str) -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    style = DimensionStyle("隐藏", suppress_dimension_first=True, center_mark="mark")
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10 if kind == "radius" else 20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    target = tmp_path / "radial.dxf"
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    doc = ezdxf.readfile(target)
    native = next(e for e in doc.modelspace() if e.dxftype() == "DIMENSION")
    block = doc.blocks.get(native.dxf.geometry)
    assert any(e.dxftype() == "LINE" and abs(e.dxf.end.y - e.dxf.start.y) > 0.1 for e in block)
    assert len(list(block.query("INSERT"))) == (1 if kind == "diameter" else 0)
    assert native.override().get("dimsd1") == 1
    assert read_sketch_dxf(target).dimension_styles == ((dimension.constraint_id, style),)


@pytest.mark.parametrize("hidden_first", (False, True))
def test_diameter_second_side_is_removed_and_style_roundtrips(
    tmp_path: Path, hidden_first: bool
) -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    style = DimensionStyle(
        "隐藏第二侧", suppress_dimension_first=hidden_first, suppress_dimension_second=True
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    target = tmp_path / "diameter.dxf"
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    doc = ezdxf.readfile(target)
    native = next(e for e in doc.modelspace() if e.dxftype() == "DIMENSION")
    block = doc.blocks.get(native.dxf.geometry)
    assert not list(block.query("LINE"))
    assert len(list(block.query("INSERT"))) == (0 if hidden_first else 1)
    assert (native.override().get("dimsd1"), native.override().get("dimsd2")) == (
        int(hidden_first),
        1,
    )
    assert read_sketch_dxf(target).dimension_styles == ((dimension.constraint_id, style),)


@pytest.mark.parametrize("hide_first", (False, True))
@pytest.mark.parametrize(
    ("second_style", "block_name"),
    (("closed", "_CLOSED"), ("filled", "_CLOSEDFILLED"), ("tick", "_OBLIQUE"), ("none", "_NONE")),
)
def test_diameter_arrow_styles_match_each_endpoint(
    tmp_path: Path, hide_first: bool, second_style: str, block_name: str
) -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    style = DimensionStyle(
        "两种箭头",
        arrow_first="open",
        arrow_second=second_style,
        suppress_dimension_first=hide_first,
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    target = tmp_path / "arrows.dxf"
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    doc = ezdxf.readfile(target)
    native = next(e for e in doc.modelspace() if e.dxftype() == "DIMENSION")
    arrows = list(doc.blocks.get(native.dxf.geometry).query("INSERT"))
    assert {e.dxf.name for e in arrows if e.dxf.insert.x < 0} == {block_name}
    assert {e.dxf.name for e in arrows if e.dxf.insert.x > 0} == (
        set() if hide_first else {"_OPEN"}
    )
    assert block_name in doc.blocks


@pytest.mark.parametrize("kind", ("radius", "diameter"))
@pytest.mark.parametrize(("mark", "count"), (("mark", 2), ("line", 6)))
def test_radial_center_marks_export_without_suppression(
    tmp_path: Path, kind: str, mark: str, count: int
) -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    style = DimensionStyle("圆心", center_mark=mark, center_size=2)
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10 if kind == "radius" else 20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        style_name=style.name,
    )
    target = tmp_path / "center.dxf"
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    doc = ezdxf.readfile(target)
    native = next(e for e in doc.modelspace() if e.dxftype() == "DIMENSION")
    lines = list(doc.blocks.get(native.dxf.geometry).query("LINE"))
    # Nonnegative and negative center strokes plus the one dimension line.
    assert len(lines) == count + 1


@pytest.mark.parametrize("kind", ("radius", "diameter"))
def test_moved_radial_text_does_not_duplicate_center_mark(tmp_path: Path, kind: str) -> None:
    circle = CircleEntity(uuid4().hex, (0, 0), 10)
    style = DimensionStyle(
        "圆心",
        center_mark="mark",
        center_size=2,
        dimension_color=1,
        extension_color=3,
        extension_lineweight=35,
    )
    dimension = SketchConstraint(
        uuid4().hex,
        kind,
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        10 if kind == "radius" else 20,
        "mm",
        driving=False,
        position_mm=(20, 0),
        text_position_mm=(20, 8),
        style_name=style.name,
    )
    target = tmp_path / "center-moved.dxf"
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (dimension,))
    write_sketches_dxf(
        (sketch,), target, dimension_styles=DimensionStyleTable((style,), style.name)
    )
    doc = ezdxf.readfile(target)
    native = next(e for e in doc.modelspace() if e.dxftype() == "DIMENSION")
    lines = list(doc.blocks.get(native.dxf.geometry).query("LINE"))
    for a, b in (((-2, 0), (2, 0)), ((0, -2), (0, 2))):
        matches = [
            line
            for line in lines
            if (tuple(line.dxf.start)[:2], tuple(line.dxf.end)[:2]) in ((a, b), (b, a))
        ]
        assert len(matches) == 1
        assert matches[0].dxf.color == 3
        assert matches[0].dxf.lineweight == 35
