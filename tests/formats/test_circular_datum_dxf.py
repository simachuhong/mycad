# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A round datum keeps its geometry and identity in DXF."""

from pathlib import Path
from typing import Any, cast

import ezdxf.filemanagement
import pytest

from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.geometric_tolerance_geometry import circular_datum_geometry
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.formats.dxf_datum import (
    DATUM_APPID,
    DatumGraphicSnapshot,
    freeze_datum_blocks,
    read_datum,
    write_datum,
)
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf


def test_circular_datum_dxf_roundtrip() -> None:
    doc: Any = cast("Any", ezdxf.filemanagement).new("R2013")
    doc.appids.new(DATUM_APPID)
    datum = DatumIdentifier(
        "a" * 32, "A", (10, 20), (10, 0), layout_mode="shared", symbol_style="circle"
    )
    write_datum(doc, datum, 1)
    insert = next(iter(doc.modelspace().query("INSERT")))
    block = doc.blocks.get(insert.dxf.name)
    assert len(list(block.query("CIRCLE"))) == 1
    assert len(list(block.query("LINE"))) == 2
    values = tuple(
        cast("str", tag.value) for tag in insert.get_xdata(DATUM_APPID) if tag.code == 1000
    )
    assert read_datum(doc, insert, values, 1.0) == datum
    bar = list(block.query("LINE"))[1]
    bar.dxf.lineweight = 25
    with pytest.raises(ValueError, match="短线样式"):
        read_datum(doc, insert, values, 1.0)
    bar.dxf.lineweight = 50
    circle = next(iter(block.query("CIRCLE")))
    circle.dxf.radius *= 2
    with pytest.raises(ValueError, match="已修改"):
        read_datum(doc, insert, values, 1.0)


def test_circular_datum_graphic_freeze_keeps_circle_and_bar() -> None:
    doc: Any = cast("Any", ezdxf.filemanagement).new("R2013")
    doc.appids.new(DATUM_APPID)
    datum = DatumIdentifier(
        "b" * 32, "A", (10, 20), (10, 0), layout_mode="shared", symbol_style="circle"
    )
    write_datum(doc, datum, 1)
    insert = next(iter(doc.modelspace().query("INSERT")))
    block = doc.blocks.get(insert.dxf.name)
    radius = float(next(iter(block.query("CIRCLE"))).dxf.radius)
    _, leader, _ = circular_datum_geometry((radius, -radius), (0, -20), radius, radius * 1.6)
    contours = ((((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),),)
    snapshot = DatumGraphicSnapshot(datum, 2 * radius, 2 * radius, leader, (), contours)
    assert freeze_datum_blocks(doc, {datum.datum_id: snapshot}) == 1
    assert len(list(block.query("CIRCLE"))) == 1
    assert len(list(block.query("LINE"))) == 2
    assert len(list(block.query("HATCH"))) == 1
    assert not insert.has_xdata(DATUM_APPID)


def test_circular_datum_provider_roundtrip(tmp_path: Path) -> None:
    datum = DatumIdentifier(
        "c" * 32, "A", (10, 20), (10, 0), layout_mode="shared", symbol_style="circle"
    )
    path = tmp_path / "circular.dxf"
    write_sketches_dxf((), path, datum_identifiers=(datum,))
    assert read_sketch_dxf(path).datum_identifiers == (datum,)


def test_slanted_connector_export_keeps_bar_parallel_to_baseline(tmp_path: Path) -> None:
    line = LineEntity("d" * 32, (0, 0), (80, 0))
    sketch = Sketch("e" * 32, WorkPlaneFrame.xy(), (line,))
    datum = DatumIdentifier(
        "f" * 32,
        "A",
        (55, 25),
        (40, 0),
        layout_mode="shared",
        symbol_style="circle",
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
    )
    path = tmp_path / "baseline-circle.dxf"
    write_sketches_dxf((sketch,), path, datum_identifiers=(datum,))
    document: Any = cast("Any", ezdxf.filemanagement).readfile(path)
    insert = next(iter(document.modelspace().query("INSERT")))
    block = document.blocks.get(insert.dxf.name)
    bar = list(block.query("LINE"))[1]
    assert bar.dxf.start.y == pytest.approx(bar.dxf.end.y)
    imported = read_sketch_dxf(path)
    assert imported.datum_identifiers[0].bar_direction == pytest.approx((1, 0))


def test_directed_bar_is_kept_in_graphic_export() -> None:
    doc: Any = cast("Any", ezdxf.filemanagement).new("R2013")
    doc.appids.new(DATUM_APPID)
    datum = DatumIdentifier(
        "1" * 32,
        "A",
        (50, 25),
        (40, 0),
        layout_mode="shared",
        symbol_style="circle",
        bar_direction=(1, 0),
    )
    write_datum(doc, datum, 1)
    insert = next(iter(doc.modelspace().query("INSERT")))
    block = doc.blocks.get(insert.dxf.name)
    radius = float(next(iter(block.query("CIRCLE"))).dxf.radius)
    _, leader, _ = circular_datum_geometry(
        (radius, -radius), (-10, -25), radius, radius * 1.6, bar_direction=(1, 0)
    )
    contours = ((((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),),)
    snapshot = DatumGraphicSnapshot(datum, 2 * radius, 2 * radius, leader, (), contours)
    freeze_datum_blocks(doc, {datum.datum_id: snapshot})
    bar = list(block.query("LINE"))[1]
    assert bar.dxf.start.y == pytest.approx(bar.dxf.end.y)
