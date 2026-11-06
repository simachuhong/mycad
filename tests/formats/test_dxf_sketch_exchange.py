# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF sketch-subset exchange reports units and unsupported entities explicitly."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import ezdxf.filemanagement as _filemanagement
import pytest
from ezdxf.filemanagement import new as _new_dxf

from mycad.core.exceptions import ValidationError
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats import DXF_PROVIDER, DxfExchangeReport, FormatProviderRegistry
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf
from mycad.geom.kernel import BuildKernel

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"


def test_point_dxf_round_trip_preserves_position_and_identity(tmp_path: Path) -> None:
    point = PointEntity("a1" * 16, (2.5, -3.75), construction=True)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (point,))
    path = tmp_path / "point.dxf"
    write_sketch_dxf(sketch, path)
    imported = read_sketch_dxf(path)
    assert imported.sketch.entities == (point,)


@pytest.mark.parametrize("axis", ["aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y"])
def test_placed_projection_dimension_roundtrip(tmp_path: Path, axis: str) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    value = 50 if axis == "aligned" else 30 if axis in ("horizontal", "ordinate_x") else 40
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        value,
        "mm",
        driving=False,
        axis=axis,
        position_mm=(20, -15),
        text_position_mm=(15, -20),
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "placed.dxf"
    write_sketch_dxf(sketch, target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    measurement: object = native.get_measurement()
    if axis.startswith("ordinate_"):
        measurement = cast("Sequence[float]", measurement)[0 if axis == "ordinate_x" else 1]
    assert measurement == pytest.approx(value)


def test_arc_length_dimension_roundtrip(tmp_path: Path) -> None:
    from uuid import uuid4

    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    dimension = SketchConstraint(
        uuid4().hex,
        "arc_length",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        5 * math.pi,
        "mm",
        driving=False,
        position_mm=(15, 15),
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (arc,), (dimension,))
    target = tmp_path / "arc-length.dxf"
    write_sketch_dxf(sketch, target)
    assert read_sketch_dxf(target).sketch.constraints == (dimension,)


class _TestSpace(Protocol):
    def add_lwpolyline(
        self,
        points: Sequence[Sequence[float]],
        *,
        format: str,
        close: bool,
        dxfattribs: Mapping[str, object],
    ) -> object: ...

    def add_circle(self, center: Sequence[float], radius: float) -> object: ...

    def add_line(
        self, start: Sequence[float], end: Sequence[float], *, dxfattribs: Mapping[str, object]
    ) -> object: ...

    def add_text(self, text: str, *, dxfattribs: Mapping[str, object]) -> object: ...


class _TestLayer(Protocol):
    def off(self) -> None: ...


class _TestLayers(Protocol):
    def new(self, name: str, *, dxfattribs: Mapping[str, object]) -> _TestLayer: ...


class _TestDocument(Protocol):
    header: MutableMapping[str, object]
    layers: _TestLayers

    def modelspace(self) -> _TestSpace: ...

    def saveas(self, path: Path) -> None: ...


class _DxfDimensionAttributes(Protocol):
    def get(self, name: str, default: object = None) -> object: ...


class _DxfEntity(Protocol):
    dxf: _DxfDimensionAttributes

    def dxftype(self) -> str: ...

    def get_measurement(self) -> float: ...

    def virtual_entities(self) -> Iterable[_DxfEntity]: ...


class _DxfDocument(Protocol):
    def modelspace(self) -> Iterable[_DxfEntity]: ...


class _ReadDxf(Protocol):
    def __call__(self, path: Path) -> _DxfDocument: ...


class _NewDxf(Protocol):
    def __call__(self, dxfversion: str, *, units: int) -> _TestDocument: ...


_new_test_dxf = cast("_NewDxf", _new_dxf)
_read_test_dxf = cast("_ReadDxf", vars(_filemanagement)["readfile"])


def _sketch() -> Sketch:
    return Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), (10.0, 0.0)),
            PolylineEntity(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)),
            ),
            CircleEntity("3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d", (2.0, 3.0), 4.0),
            ArcEntity("4e4e4e4e-4e4e-4e4e-8e4e-4e4e4e4e4e4e", (0.0, 0.0), 5.0, 20.0, -90.0),
            RectangleEntity("5f5f5f5f-5f5f-4f5f-8f5f-5f5f5f5f5f5f", (-2.0, -3.0), (8.0, 6.0)),
            LineEntity(
                "6a6a6a6a-6a6a-4a6a-8a6a-6a6a6a6a6a6a",
                (1.0, 1.0),
                (1.0, 5.0),
                construction=True,
            ),
        ),
    )


def test_dxf_r2010_roundtrip_supported_geometry_units_and_identity(tmp_path: Path) -> None:
    sketch = _sketch()
    path = tmp_path / "drawing.dxf"

    exported = write_sketch_dxf(sketch, path)
    imported = read_sketch_dxf(path)

    assert path.exists()
    assert exported.dxf_version == "AC1024"
    assert exported.unit == "mm"
    assert exported.entity_count == len(sketch.entities)
    assert exported.complete
    assert imported.report.dxf_version == "AC1024"
    assert imported.report.unit == "mm"
    assert imported.report.complete
    assert imported.sketch.sketch_id == sketch.sketch_id
    assert tuple(entity.entity_id for entity in imported.sketch.entities) == tuple(
        entity.entity_id for entity in sketch.entities
    )
    assert isinstance(imported.sketch.entities[0], LineEntity)
    assert isinstance(imported.sketch.entities[1], PolylineEntity)
    assert isinstance(imported.sketch.entities[2], CircleEntity)
    assert isinstance(imported.sketch.entities[3], ArcEntity)
    arc = imported.sketch.entities[3]
    assert isinstance(arc, ArcEntity)
    assert arc.start_angle_deg == pytest.approx(20.0)
    assert arc.sweep_angle_deg == pytest.approx(-90.0)
    assert isinstance(imported.sketch.entities[4], RectangleEntity)
    assert isinstance(imported.sketch.entities[5], LineEntity)
    construction = imported.sketch.entities[5]
    assert isinstance(construction, LineEntity) and construction.construction


def test_dxf_round_trip_preserves_named_layer_style_visibility_lock_and_construction(
    tmp_path: Path,
) -> None:
    outline = SketchLayer(
        "OUTLINE",
        color_rgb=(190, 40, 60),
        linetype="DASHDOT",
        lineweight_mm=0.5,
        visible=False,
        locked=True,
    )
    center = SketchLayer("CENTER", color_rgb=(20, 90, 180), linetype="DASHED")
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b",
                (0.0, 0.0),
                (10.0, 0.0),
                layer_name="OUTLINE",
            ),
            LineEntity(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                (5.0, -2.0),
                (5.0, 2.0),
                construction=True,
                layer_name="CENTER",
            ),
        ),
        layers=SketchLayerTable().add(outline).add(center),
    )
    path = tmp_path / "layered.dxf"

    report = write_sketch_dxf(sketch, path)
    imported = read_sketch_dxf(path)

    assert report.complete
    assert imported.report.complete
    assert imported.sketch == sketch


def test_dxf_exports_native_dimensions_and_restores_mycad_dimension_semantics(
    tmp_path: Path,
) -> None:
    line_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    circle_id = "3d3d3d3d-3d3d-4d3d-8d3d-3d3d3d3d3d3d"
    length = SketchConstraint(
        "7a7a7a7a-7a7a-4a7a-8a7a-7a7a7a7a7a7a",
        "length",
        (SketchGeometryReference(line_id, "geometry"),),
        value=10.0,
        unit="mm",
        driving=False,
        precision=1,
        scale=2.5,
    )
    distance = SketchConstraint(
        "9c9c9c9c-9c9c-4c9c-8c9c-9c9c9c9c9c9c",
        "distance",
        (
            SketchGeometryReference(line_id, "start"),
            SketchGeometryReference("2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c", "vertex", 2),
        ),
        value=50.0**0.5,
        unit="mm",
        driving=False,
    )
    angle = SketchConstraint(
        "a1a1a1a1-a1a1-41a1-81a1-a1a1a1a1a1a1",
        "angle",
        (
            SketchGeometryReference(line_id, "geometry"),
            SketchGeometryReference("2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c", "segment", 1),
        ),
        value=90.0,
        unit="deg",
        driving=False,
    )
    radius = SketchConstraint(
        "8b8b8b8b-8b8b-4b8b-8b8b-8b8b8b8b8b8b",
        "radius",
        (SketchGeometryReference(circle_id, "geometry"),),
        value=4.0,
        unit="mm",
        driving=False,
        precision=3,
    )
    diameter = SketchConstraint(
        "b2b2b2b2-b2b2-42b2-82b2-b2b2b2b2b2b2",
        "diameter",
        (SketchGeometryReference(circle_id, "geometry"),),
        value=8.0,
        unit="mm",
        driving=False,
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        _sketch().entities[:3],
        constraints=(length, distance, angle, radius, diameter),
    )
    path = tmp_path / "dimensions.dxf"

    report = write_sketch_dxf(sketch, path)
    dxf = _read_test_dxf(path)
    dimensions = [entity for entity in dxf.modelspace() if entity.dxftype() == "DIMENSION"]
    imported = read_sketch_dxf(path)

    assert report.complete
    assert report.entity_count == len(sketch.entities) + len(sketch.constraints)
    assert len(dimensions) == len(sketch.constraints)
    assert all(entity.dxf.get("text", "<>") != " " for entity in dimensions)
    assert imported.sketch.constraints == sketch.constraints
    assert imported.report.complete


@pytest.mark.parametrize("angle", [30.0, 90.0, 135.0, 270.0, -30.0, -90.0, -270.0])
def test_native_angle_dimension_measurement_and_rendered_text_match(
    tmp_path: Path, angle: float
) -> None:
    first_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    second_id = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
    radians = math.radians(angle)
    dimension = SketchConstraint(
        "7a7a7a7a-7a7a-4a7a-8a7a-7a7a7a7a7a7a",
        "angle",
        (
            SketchGeometryReference(first_id, "geometry"),
            SketchGeometryReference(second_id, "geometry"),
        ),
        angle,
        "deg",
        driving=False,
        precision=2,
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (
            LineEntity(first_id, (0.0, 0.0), (20.0, 0.0)),
            LineEntity(second_id, (0.0, 0.0), (20 * math.cos(radians), 20 * math.sin(radians))),
        ),
        (dimension,),
    )
    path = tmp_path / "angle.dxf"
    report = write_sketch_dxf(sketch, path)
    assert report.complete
    native = next(e for e in _read_test_dxf(path).modelspace() if e.dxftype() == "DIMENSION")
    assert native.get_measurement() == pytest.approx(abs(angle))
    text = [
        e.dxf.get("text") for e in native.virtual_entities() if e.dxftype() in ("TEXT", "MTEXT")
    ]
    assert text == [f"{angle:.2f}°"]
    assert read_sketch_dxf(path).sketch.constraints == (dimension,)


def test_closed_polyline_closing_segment_dimension_is_exported(tmp_path: Path) -> None:
    identity = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    dimension = SketchConstraint(
        "7a7a7a7a-7a7a-4a7a-8a7a-7a7a7a7a7a7a",
        "length",
        (SketchGeometryReference(identity, "segment", 2),),
        math.sqrt(800),
        "mm",
        driving=False,
    )
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (PolylineEntity(identity, ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0)), closed=True),),
        (dimension,),
    )
    path = tmp_path / "closing-edge.dxf"
    report = write_sketch_dxf(sketch, path)
    assert report.complete, report
    native = next(e for e in _read_test_dxf(path).modelspace() if e.dxftype() == "DIMENSION")
    assert native.get_measurement() == pytest.approx(math.sqrt(800))


def test_dxf_import_requires_unit_override_for_unknown_units(tmp_path: Path) -> None:
    document = _new_test_dxf("R2010", units=0)
    document.modelspace().add_circle((0, 0), 1)
    path = tmp_path / "unitless.dxf"
    document.saveas(path)

    with pytest.raises(ValueError, match="unit_override"):
        read_sketch_dxf(path)

    imported = read_sketch_dxf(path, unit_override="inch")
    entity = imported.sketch.entities[0]
    assert isinstance(entity, CircleEntity)
    assert entity.radius_mm == pytest.approx(25.4)
    assert imported.report.unit == "inch (override)"


def test_dxf_import_reports_unsupported_entities_without_dropping_notice(tmp_path: Path) -> None:
    document = _new_test_dxf("R2010", units=4)
    modelspace = document.modelspace()
    modelspace.add_circle((0, 0), 5)
    notes = document.layers.new("NOTES", dxfattribs={"color": 3})
    notes.off()
    modelspace.add_line((0, 0), (3, 0), dxfattribs={"layer": "NOTES"})
    modelspace.add_text("drawing label", dxfattribs={"height": 2})
    path = tmp_path / "with-text.dxf"
    document.saveas(path)

    imported = read_sketch_dxf(path)

    assert len(imported.sketch.entities) == 2
    assert not imported.report.complete
    assert any("TEXT" in warning and "已跳过" in warning for warning in imported.report.warnings)
    assert imported.sketch.entities[1].layer_name == "NOTES"
    assert imported.sketch.layers.get("NOTES").visible is False


def test_dxf_provider_exports_one_replayed_sketch_and_returns_report(tmp_path: Path) -> None:
    kernel = BuildKernel()
    kernel.apply("sketch.create", _sketch().to_mapping())
    registry = FormatProviderRegistry([DXF_PROVIDER])
    path = tmp_path / "provider.dxf"

    report = registry.resolve(path).write(kernel, path)

    assert isinstance(report, DxfExchangeReport)
    assert report.entity_count == 6
    assert path.stat().st_size > 0
    assert read_sketch_dxf(path).sketch.sketch_id == SKETCH_ID


def test_dxf_provider_rejects_multiple_sketches_and_keeps_kernel_unchanged(tmp_path: Path) -> None:
    kernel = BuildKernel()
    kernel.apply("sketch.create", _sketch().to_mapping())
    second = Sketch(
        "7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b",
        WorkPlaneFrame.xy(),
        (),
    )
    kernel.apply("sketch.create", second.to_mapping())
    before = kernel.sketches

    with pytest.raises(ValidationError, match="一张草图"):
        DXF_PROVIDER.write(kernel, tmp_path / "multiple.dxf")

    assert kernel.sketches == before
    assert not (tmp_path / "multiple.dxf").exists()


@pytest.mark.parametrize("bulge", [1.0, -0.5])
@pytest.mark.parametrize("closed", [False, True])
def test_bulged_polyline_is_reported_without_silent_straightening(
    tmp_path: Path, bulge: float, closed: bool
) -> None:
    document = _new_test_dxf("R2010", units=4)
    modelspace = document.modelspace()
    modelspace.add_circle((50, 0), 5)
    modelspace.add_lwpolyline(
        [(0, 0, bulge), (20, 0, 0), (20, 20, 0)],
        format="xyb",
        close=closed,
        dxfattribs={},
    )
    path = tmp_path / "bulged.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.report.complete
    assert len(imported.sketch.entities) == 1
    assert isinstance(imported.sketch.entities[0], CircleEntity)
    assert any(
        "LWPOLYLINE" in item and "bulge" in item and "已跳过" in item
        for item in imported.report.warnings
    )


@pytest.mark.parametrize("constant", [False, True])
def test_polyline_width_is_reported_without_silent_centerline_conversion(
    tmp_path: Path, constant: bool
) -> None:
    document = _new_test_dxf("R2010", units=4)
    document.modelspace().add_lwpolyline(
        [(0, 0, 0 if constant else 2, 0 if constant else 3), (20, 0, 0, 0)],
        format="xyse",
        close=False,
        dxfattribs={"const_width": 2} if constant else {},
    )
    path = tmp_path / "wide.dxf"
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert not imported.report.complete
    assert imported.sketch.entities == ()
    assert any(
        "LWPOLYLINE" in item and "宽度" in item and "已跳过" in item
        for item in imported.report.warnings
    )
