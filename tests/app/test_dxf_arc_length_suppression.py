# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF arc-length formatting follows the source arc's start and end."""

import math
from pathlib import Path
from uuid import uuid4

import ezdxf
import pytest

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


@pytest.mark.parametrize("clockwise", (False, True))
@pytest.mark.parametrize("hidden_first", (False, True))
def test_arc_length_suppression_matches_source_end(
    tmp_path: Path, clockwise: bool, hidden_first: bool
) -> None:
    source = ArcEntity(uuid4().hex, (0, 0), 10, 90 if clockwise else 0, -90 if clockwise else 90)
    style = DimensionStyle(
        "弧长",
        arrow_first="open",
        arrow_second="closed",
        suppress_extension_first=True,
        suppress_dimension_first=hidden_first,
        suppress_dimension_second=not hidden_first,
    )
    table = DimensionStyleTable((style,), style.name)
    dimension = SketchConstraint(
        uuid4().hex,
        "arc_length",
        (SketchGeometryReference(source.entity_id, "geometry"),),
        5 * math.pi,
        "mm",
        driving=False,
        position_mm=(12, 12),
        style_name=style.name,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (dimension,))
    target = tmp_path / "arc-length.dxf"
    write_sketches_dxf((sketch,), target, dimension_styles=table)
    document = ezdxf.readfile(target)
    native = next(e for e in document.modelspace() if e.dxftype() in ("DIMENSION", "ARC_DIMENSION"))
    override = native.override()
    assert (override.get("dimblk1"), override.get("dimblk2")) == (
        ("CLOSED", "OPEN") if clockwise else ("OPEN", "CLOSED")
    )
    assert (override.get("dimse1"), override.get("dimse2")) == ((0, 1) if clockwise else (1, 0))
    block = document.blocks.get(native.dxf.geometry)
    arrows = list(block.query("INSERT"))
    assert len(arrows) == 1
    remaining_vertical = hidden_first != clockwise
    x, y, _ = arrows[0].dxf.insert
    assert (x if remaining_vertical else y) == pytest.approx(0, abs=1e-6)
    arcs = list(block.query("ARC"))
    assert arcs
    for arc in arcs:
        start = math.radians(arc.dxf.start_angle)
        sweep = math.radians((arc.dxf.end_angle - arc.dxf.start_angle) % 360)
        for fraction in (0.01, 0.5, 0.99):
            angle = start + fraction * sweep
            assert (math.sin(angle) if remaining_vertical else math.cos(angle)) >= (
                math.cos(angle) if remaining_vertical else math.sin(angle)
            ) - 1e-6
    assert read_sketch_dxf(target).dimension_styles == ((dimension.constraint_id, style),)
