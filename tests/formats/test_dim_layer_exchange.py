# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native DXF freeze and dimension layer membership are independent."""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import ezdxf.filemanagement as _filemanagement

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import DEFAULT_DIM_LAYER, SketchLayerTable
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf


class _Attributes(Protocol):
    layer: str


class _Entity(Protocol):
    dxf: _Attributes

    def dxftype(self) -> str: ...


class _Layer(Protocol):
    def is_off(self) -> bool: ...

    def is_frozen(self) -> bool: ...

    def is_locked(self) -> bool: ...


class _Layers(Protocol):
    def get(self, name: str) -> _Layer: ...


class _Document(Protocol):
    layers: _Layers

    def modelspace(self) -> Iterable[_Entity]: ...


class _Reader(Protocol):
    def __call__(self, path: Path) -> _Document: ...


def test_dxf_dim_layer_and_frozen_off_flags_roundtrip(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        layer_name="DIM",
        position_mm=(15, -10),
    )
    table = SketchLayerTable().add(
        replace(DEFAULT_DIM_LAYER, visible=False, frozen=True, locked=True)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), table)
    path = tmp_path / "dim-layers.dxf"
    write_sketch_dxf(sketch, path)
    imported = read_sketch_dxf(path).sketch
    assert imported.layers.get("DIM").frozen
    assert not imported.layers.get("DIM").visible
    assert imported.constraints[0].layer_name == "DIM"
    assert imported.entities[0].layer_name == "0"
    native = cast("_Reader", vars(_filemanagement)["readfile"])(path)
    native_layer = native.layers.get("DIM")
    assert native_layer.is_off()
    assert native_layer.is_frozen()
    assert native_layer.is_locked()
    dimension_entity = next(e for e in native.modelspace() if e.dxftype() == "DIMENSION")
    assert dimension_entity.dxf.layer == "DIM"
    geometry = next(e for e in native.modelspace() if e.dxftype() == "LINE")
    assert geometry.dxf.layer == "0"
