# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Angular DXF styles follow the original selected reference lines."""

import math
from pathlib import Path
from uuid import uuid4

import ezdxf
import pytest

from mycad.core.angular_dimension import angular_sector
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize("sector", (45, 135, 225, 315))
@pytest.mark.parametrize("hidden_first", (True, False))
@pytest.mark.parametrize(
    "reversed_lines", ((False, False), (True, False), (False, True), (True, True))
)
def test_angular_hidden_arrow_tracks_reference(
    tmp_path: Path, sector: int, hidden_first: bool, reversed_lines: tuple[bool, bool]
) -> None:
    first_points = ((0.0, 0.0), (10.0, 0.0))
    second_points = ((0.0, 0.0), (0.0, 10.0))
    if reversed_lines[0]:
        first_points = first_points[::-1]
    if reversed_lines[1]:
        second_points = second_points[::-1]
    first = LineEntity(uuid4().hex, *first_points)
    second = LineEntity(uuid4().hex, *second_points)
    style = DimensionStyle(
        "角度",
        arrow_first="open",
        arrow_second="closed",
        suppress_extension_first=True,
        suppress_dimension_first=hidden_first,
        suppress_dimension_second=not hidden_first,
    )
    table = DimensionStyleTable((style,), style.name)
    angle = math.radians(sector)
    dim = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        position_mm=(20 * math.cos(angle), 20 * math.sin(angle)),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dim,))
    target = tmp_path / "angular.dxf"
    write_sketches_dxf((sketch,), target, dimension_styles=table)
    document = ezdxf.readfile(target)
    native = next(e for e in document.modelspace() if e.dxftype() == "DIMENSION")
    assert dim.position_mm is not None
    starts_first = angular_sector(first_points, second_points, dim.position_mm).starts_with_first
    override = native.override()
    assert (override.get("dimse1"), override.get("dimse2")) == ((1, 0) if starts_first else (0, 1))
    assert (override.get("dimblk1"), override.get("dimblk2")) == (
        ("OPEN", "CLOSED") if starts_first else ("CLOSED", "OPEN")
    )
    arrows = [e for e in document.blocks.get(native.dxf.geometry) if e.dxftype() == "INSERT"]
    assert len(arrows) == 1
    x, y, _ = arrows[0].dxf.insert
    assert (x if hidden_first else y) == pytest.approx(0, abs=1e-6)
    assert abs(y if hidden_first else x) > 1
    for arc in document.blocks.get(native.dxf.geometry).query("ARC"):
        start = math.radians(arc.dxf.start_angle)
        sweep = math.radians((arc.dxf.end_angle - arc.dxf.start_angle) % 360)
        for fraction in (0.01, 0.5, 0.99):
            angle = start + sweep * fraction
            x_component, y_component = abs(math.cos(angle)), abs(math.sin(angle))
            assert (y_component if hidden_first else x_component) >= (
                x_component if hidden_first else y_component
            ) - 1e-6
    assert read_sketch_dxf(target).dimension_styles == ((dim.constraint_id, style),)


@pytest.mark.parametrize("both_hidden", (False, True))
def test_angular_arc_splits_at_moved_text(tmp_path: Path, both_hidden: bool) -> None:
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    style = DimensionStyle(
        "移动文字", suppress_dimension_first=True, suppress_dimension_second=both_hidden
    )
    table = DimensionStyleTable((style,), style.name)
    dim = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        position_mm=(10, 10),
        text_position_mm=(15 * math.cos(math.pi / 6), 15 * math.sin(math.pi / 6)),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dim,))
    target = tmp_path / "moved-text.dxf"
    write_sketches_dxf((sketch,), target, dimension_styles=table)
    document = ezdxf.readfile(target)
    native = next(e for e in document.modelspace() if e.dxftype() == "DIMENSION")
    arcs = list(document.blocks.get(native.dxf.geometry).query("ARC"))
    if both_hidden:
        assert not arcs
    else:
        assert arcs
        assert all(arc.dxf.start_angle >= 30 - 1e-6 for arc in arcs)
