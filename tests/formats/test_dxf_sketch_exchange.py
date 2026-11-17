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
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import ConstraintKind, SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats import DXF_PROVIDER, DxfExchangeReport, FormatProviderRegistry
from mycad.formats.providers.dxf_provider import (
    read_sketch_dxf,
    write_sketch_dxf,
    write_sketches_dxf,
)
from mycad.geom.kernel import BuildKernel

SKETCH_ID = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"


def test_dimension_text_override_exports_native_and_roundtrips(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        text_override="宽 <> mm",
    )
    target = tmp_path / "text-override.dxf"
    write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    assert native.dxf.text == "宽 <> mm"
    assert read_sketch_dxf(target).sketch.constraints == (dimension,)


def test_negative_ordinate_text_override_keeps_negative_measurement(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (10, 0), (0, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        -10,
        "mm",
        driving=False,
        axis="ordinate_x",
        text_override="X <> mm",
    )
    target = tmp_path / "negative-text.dxf"
    write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    assert native.dxf.text == "X -<> mm"
    assert read_sketch_dxf(target).sketch.constraints == (dimension,)


def test_dimension_text_override_dxf_renders_multiple_values_and_literal_controls(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from ezdxf.tools.text import plain_mtext

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    text = r"C:\Part {A} <> / <>"
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        text_override=text,
    )
    target = tmp_path / "literal-multiple-text.dxf"
    report = write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    labels = [item.dxf.text for item in native.virtual_entities() if item.dxftype() == "MTEXT"]
    assert len(labels) == 1
    assert plain_mtext(labels[0]) == r"C:\Part {A} 25.00 / 25.00"
    assert any("仅首个" in warning for warning in report.warnings)
    assert read_sketch_dxf(target).sketch.constraints == (dimension,)


def test_dimension_text_override_dxf_preserves_literal_percent_sequences(tmp_path: Path) -> None:
    from uuid import uuid4

    from ezdxf.tools.text import plain_mtext

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        text_override="literal %%d and 50%% <>",
    )
    target = tmp_path / "literal-percent.dxf"
    write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    labels = [item.dxf.text for item in native.virtual_entities() if item.dxftype() == "MTEXT"]
    assert len(labels) == 1
    assert plain_mtext(labels[0]) == "literal %%d and 50%% 25.00"
    assert read_sketch_dxf(target).sketch.constraints == (dimension,)


def test_dxf_style_reference_is_detached_with_exchange_warning(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        precision=3,
        scale=2,
        style_name="加工图",
    )
    target = tmp_path / "styled.dxf"
    report = write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    assert native.override().get("dimtxt") == 5
    assert native.override().get("dimasz") == 5
    assert native.override().get("dimdec") == 3
    imported = read_sketch_dxf(target).sketch.constraints[0]
    assert imported.style_name is None
    assert (imported.precision, imported.scale) == (3, 2)
    assert any("样式关联" in warning for warning in report.warnings)


@pytest.mark.parametrize("bulges", [(0.2, 0), (0, 0.2), (0.2, 0.2), (-0.2, -0.2)])
def test_zero_radius_closed_two_curve_path_roundtrips_dxf(
    tmp_path: Path, bulges: tuple[float, float]
) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity("a1" * 16, ((0, 0), (10, 0), (10, 10)), bulges=bulges)
    closed, extra = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=source.points_mm[0], second_pick=source.points_mm[-1]
    )
    assert extra is None and closed.closed
    path = tmp_path / "closed.dxf"
    assert write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (closed,)), path).complete
    imported = read_sketch_dxf(path)
    assert imported.report.complete
    actual = imported.sketch.entities[0]
    assert isinstance(actual, PolylineEntity) and actual.closed
    assert len(actual.points_mm) == len(closed.points_mm)
    for result_point, expected_point in zip(actual.points_mm, closed.points_mm, strict=True):
        assert result_point == pytest.approx(expected_point)
    assert actual.bulges == pytest.approx(closed.bulges)


def test_zero_radius_closure_with_preserved_original_arcs_roundtrips_dxf(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import unique_unchanged_polyline_segment
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity("a1" * 16, ((0, 0), (10, 0), (3.7376, 9.017)), bulges=(0.6, 0.9))
    closed, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=source.points_mm[0], second_pick=source.points_mm[-1]
    )
    assert len(closed.points_mm) == 4
    path = tmp_path / "preserved-arcs.dxf"
    write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (closed,)), path)
    imported = read_sketch_dxf(path).sketch.entities[0]
    assert isinstance(imported, PolylineEntity) and imported.closed
    assert unique_unchanged_polyline_segment(source, imported, 0) == 1
    assert unique_unchanged_polyline_segment(source, imported, 1) == 2


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


@pytest.mark.parametrize("axis", ["horizontal", "vertical", "ordinate_x", "ordinate_y"])
def test_dxf_exports_explicit_projection_axis(tmp_path: Path, axis: str) -> None:
    from uuid import uuid4

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (20, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30 * q,
        "mm",
        driving=False,
        axis=axis,
        projection_axis=(q, q),
        position_mm=(10, 20),
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "axis.dxf"
    report = write_sketch_dxf(sketch, target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    if axis.startswith("ordinate_"):
        labels = [
            item.dxf.get("text")
            for item in native.virtual_entities()
            if item.dxftype() in ("TEXT", "MTEXT")
        ]
        assert labels == ["21.21 mm"]
        assert any("符号" in warning for warning in report.warnings)
    else:
        assert native.get_measurement() == pytest.approx(30 * q)
    assert not any(
        dimension.constraint_id[:8] in warning and "不恢复关联" in warning
        for warning in report.warnings
    )


@pytest.mark.parametrize("axis", ["horizontal", "vertical", "ordinate_x", "ordinate_y"])
@pytest.mark.parametrize("frame_kind", ["same", "rotated", "opposite"])
def test_dxf_explicit_projection_dimension_roundtrips(
    tmp_path: Path, axis: str, frame_kind: str
) -> None:
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import project_coplanar_entity, project_coplanar_vector

    q = math.sqrt(0.5)
    frame = (
        WorkPlaneFrame.xy()
        if frame_kind == "same"
        else WorkPlaneFrame(
            (5, 7, 0),
            (q, q, 0),
            (q, -q, 0) if frame_kind == "opposite" else (-q, q, 0),
            (0, 0, -1) if frame_kind == "opposite" else (0, 0, 1),
        )
    )
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (0, 0), (20, 10)), WorkPlaneFrame.xy(), frame
    )
    direction = (-q, q)
    view_direction = project_coplanar_vector(direction, frame, WorkPlaneFrame.xy())
    first = frame.world_to_local((0, 0, 0))
    second = frame.world_to_local((20, 10, 0))
    value = (second[0] - first[0]) * direction[0] + (second[1] - first[1]) * direction[1]
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        value if axis.startswith("ordinate_") else abs(value),
        "mm",
        driving=False,
        axis=axis,
        projection_axis=direction,
        position_mm=frame.world_to_local((10, 20, 0)),
        text_position_mm=frame.world_to_local((15, 25, 0)),
    )
    source = Sketch(uuid4().hex, frame, (line,), (dimension,))
    marker = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (50, 50)),))
    target = tmp_path / "projection-roundtrip.dxf"
    report = write_sketches_dxf((marker, source), target)
    imported = read_sketch_dxf(target)
    result = next(
        c for c in imported.sketch.constraints if c.constraint_id == dimension.constraint_id
    )
    assert result.axis == axis
    assert result.value == pytest.approx(dimension.value)
    assert result.projection_axis == pytest.approx(view_direction)
    assert result.position_mm == pytest.approx((10, 20))
    assert result.text_position_mm == pytest.approx((15, 25))
    assert result.references == dimension.references
    assert not any(
        dimension.constraint_id[:8] in warning and "不恢复关联" in warning
        for warning in report.warnings
    )


@pytest.mark.parametrize("opposite", [False, True])
def test_dxf_rotated_rectangle_dimension_endpoints_roundtrip(
    tmp_path: Path, opposite: bool
) -> None:
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import project_coplanar_vector

    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    direction = (q, q)
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(rectangle.entity_id, "start"),
            SketchGeometryReference(rectangle.entity_id, "end"),
        ),
        30 * q,
        "mm",
        driving=False,
        axis="horizontal",
        projection_axis=direction,
    )
    source = Sketch(uuid4().hex, frame, (rectangle,), (dimension,))
    marker = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (50, 50)),))
    target = tmp_path / "rectangle-dimension.dxf"
    report = write_sketches_dxf((marker, source), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    assert native.get_measurement() == pytest.approx(dimension.value)
    imported = read_sketch_dxf(target)
    result = next(
        c for c in imported.sketch.constraints if c.constraint_id == dimension.constraint_id
    )
    assert result.references == (
        SketchGeometryReference(rectangle.entity_id, "vertex", 0),
        SketchGeometryReference(rectangle.entity_id, "vertex", 2),
    )
    assert result.projection_axis == pytest.approx(
        project_coplanar_vector(direction, frame, WorkPlaneFrame.xy())
    )
    assert not any("不恢复关联" in warning for warning in report.warnings)


@pytest.mark.parametrize("driving", [False, True])
def test_dxf_projection_dimension_handles_externally_modified_geometry(
    tmp_path: Path, driving: bool
) -> None:
    from uuid import uuid4

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (20, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        30 * q,
        "mm",
        driving=driving,
        axis="horizontal",
        projection_axis=(q, q),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    target = tmp_path / "modified-projection.dxf"
    write_sketch_dxf(sketch, target)
    document = _read_test_dxf(target)
    native_line = next(entity for entity in document.modelspace() if entity.dxftype() == "LINE")
    native_line.dxf.end = (40, 10, 0)
    native_dimension = next(
        entity for entity in document.modelspace() if entity.dxftype() == "DIMENSION"
    )
    native_dimension.dxf.text_midpoint = (30, 22, 0)
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert any(
        "尺寸" in warning and ("不一致" in warning or "更新" in warning)
        for warning in imported.report.warnings
    )
    if driving:
        assert not imported.sketch.constraints
        assert not any("文字位置已恢复" in warning for warning in imported.report.warnings)
    else:
        assert imported.sketch.constraints[0].value == pytest.approx(50 * q)
        assert imported.sketch.constraints[0].text_position_mm == pytest.approx((30, 22))


@pytest.mark.parametrize("axis", ["ordinate_x", "ordinate_y"])
@pytest.mark.parametrize("explicit", [False, True])
def test_dxf_negative_ordinate_retains_native_dynamic_measurement(
    tmp_path: Path, axis: str, explicit: bool
) -> None:
    from uuid import uuid4

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (-20, -10))
    value = -30 * q if explicit else -20 if axis == "ordinate_x" else -10
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value,
        "mm",
        driving=False,
        axis=axis,
        projection_axis=(q, q) if explicit else None,
    )
    target = tmp_path / "dynamic-ordinate.dxf"
    report = write_sketch_dxf(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target
    )
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    labels = [
        item.dxf.get("text")
        for item in native.virtual_entities()
        if item.dxftype() in ("TEXT", "MTEXT")
    ]
    assert labels == [f"{value:.2f} mm"]
    assert native.dxf.get("text") == "-<> mm"
    native.dxf.defpoint2 = (-40, -30, 0)
    native.render()
    updated = [
        item.dxf.get("text")
        for item in native.virtual_entities()
        if item.dxftype() in ("TEXT", "MTEXT")
    ]
    expected = -70 * q if explicit else -40 if axis == "ordinate_x" else -30
    assert updated == [f"{expected:.2f} mm"]
    assert any("符号" in warning for warning in report.warnings)


@pytest.mark.parametrize("axis", ["ordinate_x", "ordinate_y"])
@pytest.mark.parametrize("precision", [0, 1, 3])
def test_dxf_positive_projected_ordinate_rerenders_at_selected_precision(
    tmp_path: Path, axis: str, precision: int
) -> None:
    from uuid import uuid4

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (20, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30 * q,
        "mm",
        driving=False,
        axis=axis,
        projection_axis=(q, q),
        precision=precision,
    )
    target = tmp_path / "positive-dynamic-ordinate.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    native = next(
        item for item in _read_test_dxf(target).modelspace() if item.dxftype() == "DIMENSION"
    )
    assert native.dxf.get("text") == "<> mm"
    native.dxf.defpoint2 = (40, 30, 0)
    native.render()
    labels = [
        item.dxf.get("text")
        for item in native.virtual_entities()
        if item.dxftype() in ("TEXT", "MTEXT")
    ]
    assert labels == [f"{70 * q:.{precision}f} mm"]


@pytest.mark.parametrize("driving", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        "aligned",
        "horizontal",
        "vertical",
        "ordinate_x",
        "ordinate_y",
        "angle",
        "radius",
        "diameter",
        "arc_length",
    ],
)
def test_dxf_dimensions_handle_externally_modified_geometry(
    tmp_path: Path, kind: str, driving: bool
) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    circle = CircleEntity(uuid4().hex, (50, 50), 10)
    arc = ArcEntity(uuid4().hex, (80, 50), 10, 0, 90)
    if kind == "angle":
        entities = (LineEntity(line.entity_id, (0, 0), (10, 0)), second)
        refs = (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        value, expected, axis, unit = 90.0, 45.0, "aligned", "deg"
    elif kind in ("radius", "diameter"):
        entities = (circle,)
        refs = (SketchGeometryReference(circle.entity_id, "geometry"),)
        value, expected, axis, unit = (
            (10.0, 15.0, "aligned", "mm") if kind == "radius" else (20.0, 30.0, "aligned", "mm")
        )
    elif kind == "arc_length":
        entities = (arc,)
        refs = (SketchGeometryReference(arc.entity_id, "geometry"),)
        value, expected, axis, unit = 5 * math.pi, 10 * math.pi, "aligned", "mm"
    else:
        entities = (line,)
        refs = (SketchGeometryReference(line.entity_id, "geometry"),)
        value = (
            50.0 if kind == "aligned" else 30.0 if kind in ("horizontal", "ordinate_x") else 40.0
        )
        expected = (
            math.hypot(60, 40)
            if kind == "aligned"
            else 60.0
            if kind in ("horizontal", "ordinate_x")
            else 40.0
        )
        axis, unit = kind, "mm"
    constraint_kind = (
        "length"
        if kind in ("aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y")
        else kind
    )
    dimension = SketchConstraint(
        uuid4().hex,
        cast("ConstraintKind", constraint_kind),
        refs,
        value,
        unit,
        driving=driving,
        axis=axis,
    )
    target = tmp_path / "modified-dimension.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, (dimension,)), target)
    document = _read_test_dxf(target)
    native = list(document.modelspace())
    if kind == "angle":
        [item for item in native if item.dxftype() == "LINE"][1].dxf.end = (10, 10, 0)
    elif kind in ("radius", "diameter"):
        next(item for item in native if item.dxftype() == "CIRCLE").dxf.radius = 15.0
    elif kind == "arc_length":
        next(item for item in native if item.dxftype() == "ARC").dxf.end_angle = 180.0
    else:
        next(item for item in native if item.dxftype() == "LINE").dxf.end = (
            60,
            40 if expected != value else 80,
            0,
        )
        if expected == value:
            expected = 80.0
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert any(
        "尺寸" in warning and ("不一致" in warning or "更新" in warning)
        for warning in imported.report.warnings
    )
    if driving:
        assert not imported.sketch.constraints
    else:
        assert imported.sketch.constraints[0].value == pytest.approx(expected)


@pytest.mark.parametrize("axis", ["ordinate_x", "ordinate_y"])
def test_dxf_modified_ordinate_refresh_preserves_negative_sign(tmp_path: Path, axis: str) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30 if axis == "ordinate_x" else 40,
        "mm",
        driving=False,
        axis=axis,
    )
    target = tmp_path / "negative-ordinate.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    next(item for item in document.modelspace() if item.dxftype() == "LINE").dxf.end = (-60, -80, 0)
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].value == pytest.approx(
        -60 if axis == "ordinate_x" else -80
    )


def test_dxf_equivalent_wrapped_angle_is_preserved(tmp_path: Path) -> None:
    from uuid import uuid4

    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, -10))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        270,
        "deg",
        driving=True,
    )
    target = tmp_path / "wrapped-angle.dxf"
    write_sketch_dxf(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,)), target
    )
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert not any("尺寸" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("change", ["location", "definition", "text"])
def test_dxf_import_detects_external_dimension_edits(tmp_path: Path, change: str) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
        axis="aligned",
    )
    target = tmp_path / "edited-dimension.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    if change == "location":
        native.dxf.text_midpoint = (35, 22, 0)
    elif change == "definition":
        native.dxf.defpoint2 = (5, 0, 0)
    else:
        native.dxf.text = "CUSTOM"
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert len(imported.sketch.constraints) == 1
    if change == "location":
        assert imported.sketch.constraints[0].text_position_mm == pytest.approx((35, 22))
        assert any("文字位置" in warning for warning in imported.report.warnings)
    else:
        assert imported.sketch.constraints[0] == dimension
        assert any(
            "原生标注" in warning and "未" in warning for warning in imported.report.warnings
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_dxf_dimension_snapshot_is_optional_and_corruption_is_reported(
    tmp_path: Path, corrupt: bool
) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "legacy-dimension.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    if corrupt:
        native.set_xdata("MYCAD_DIMENSION_SNAPSHOT", [(1000, "1"), (1000, "invalid-json")])
    mutable = cast("_TestDocument", document)
    if not corrupt:
        mutable.appids.remove("MYCAD_DIMENSION_SNAPSHOT")
    mutable.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any("快照无效" in warning for warning in imported.report.warnings) == corrupt
    assert not any("快照缺失" in warning for warning in imported.report.warnings)


def test_dxf_external_dimension_text_location_uses_declared_units(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    target = tmp_path / "inch-dimension.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    native.dxf.text_midpoint = (3, 2, 0)
    mutable_document = cast("_TestDocument", document)
    mutable_document.header["$INSUNITS"] = 1
    mutable_document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].text_position_mm == pytest.approx((76.2, 50.8))
    assert imported.sketch.constraints[0].value == pytest.approx(127)


def test_dxf_import_reports_removed_dimension_snapshot(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "stripped-snapshot.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any(
        "快照缺失" in warning and "无法检查" in warning for warning in imported.report.warnings
    )


@pytest.mark.parametrize("angle", [False, True])
def test_dxf_import_restores_externally_modified_dimension_precision(
    tmp_path: Path, angle: bool
) -> None:
    from uuid import uuid4

    first = LineEntity(uuid4().hex, (0, 0), (30, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 40))
    references = (
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        if angle
        else (SketchGeometryReference(first.entity_id, "geometry"),)
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "angle" if angle else "length",
        references,
        90 if angle else 30,
        "deg" if angle else "mm",
        driving=False,
        precision=2,
    )
    target = tmp_path / "dimension-precision.dxf"
    write_sketch_dxf(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,)), target
    )
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    override = native.override()
    override["dimadec" if angle else "dimdec"] = 3
    override.commit()
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints[0].precision == 3
    assert any("精度" in warning and "恢复" in warning for warning in imported.report.warnings)


def test_dxf_import_reports_external_unmapped_dimension_style(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "dimension-color.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    override = native.override()
    override["dimclrt"] = 1
    override.commit()
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any("原生标注" in warning and "未" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dimcen", 4.0),
        ("dimexe", 3.0),
        ("dimexo", 2.0),
        ("dimdle", 1.0),
        ("dimsah", 1),
        ("dimblk1", "OBLIQUE"),
        ("dimblk2", "CLOSED"),
        ("dimlwd", 35),
        ("dimlwe", 70),
        ("dimltype", "MYCAD_DASHED"),
        ("dimltex1", "MYCAD_DOTTED"),
        ("dimltex2", "MYCAD_DASHDOT"),
        ("dimse1", 1),
        ("dimse2", 1),
        ("dimsd1", 1),
        ("dimsd2", 1),
    ),
)
def test_dxf_import_reports_external_line_and_center_style_changes(
    tmp_path: Path, field: str, value: float | str
) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "dimension-style-change.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    override = native.override()
    override[field] = value
    override.commit()
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any("原生标注" in warning and "未" in warning for warning in imported.report.warnings)


def test_dxf_unchanged_extended_dimension_style_is_not_reported_as_modified(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    style = DimensionStyle(
        "样式",
        arrow_first="closed",
        arrow_second="tick",
        center_mark="line",
        dimline_extension=2,
        extline_extension=3,
        extline_offset=1,
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
        style_name=style.name,
    )
    target = tmp_path / "extended-style.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),),
        target,
        dimension_styles=DimensionStyleTable((style,), style.name),
    )
    imported = read_sketch_dxf(target)
    assert len(imported.sketch.constraints) == 1
    assert imported.dimension_styles == ((dimension.constraint_id, style),)
    assert not any(
        "原生标注" in warning and "修改" in warning for warning in imported.report.warnings
    )


@pytest.mark.parametrize("edit", ("style", "snapshot", "unit", "metadata"))
def test_dxf_edited_native_style_does_not_reuse_stale_metadata(tmp_path: Path, edit: str) -> None:
    from uuid import uuid4

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    style = DimensionStyle("样式", center_mark="line")
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
        style_name=style.name,
    )
    target = tmp_path / "changed-style.dxf"
    write_sketches_dxf(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),),
        target,
        dimension_styles=DimensionStyleTable((style,), style.name),
    )
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    if edit == "style":
        override = native.override()
        override["dimcen"] = 9.0
        override.commit()
    elif edit == "snapshot":
        native.discard_xdata("MYCAD_DIMENSION_SNAPSHOT")
    elif edit == "unit":
        cast("_TestDocument", document).header["$INSUNITS"] = 1
    else:
        import json

        altered = style.to_mapping() | {"center_mark": "none", "arrow_first": "filled"}
        payload = json.dumps(altered, separators=(",", ":"))
        digest = str(native.get_xdata("MYCAD_DIMENSION_STYLE")[1].value)
        native.set_xdata(
            "MYCAD_DIMENSION_STYLE",
            [(1000, "2"), (1000, digest)]
            + [(1000, payload[i : i + 240]) for i in range(0, len(payload), 240)],
        )
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.dimension_styles == ()
    assert any("样式信息无法安全恢复" in warning for warning in imported.report.warnings)


def test_dxf_import_reports_modified_base_dimension_style(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "dimension-base-style.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = cast("_TestDocument", _read_test_dxf(target))
    document.dimstyles.get("Standard").dxf.dimclrt = 1
    document.saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any("原生标注" in warning and "未" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("version", ("1", "2", "3", "4", "5", "6"))
def test_dxf_import_preserves_legacy_dimension_snapshot(tmp_path: Path, version: str) -> None:
    import json
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        50,
        "mm",
        driving=False,
    )
    target = tmp_path / "legacy-snapshot.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    tags = native.get_xdata("MYCAD_DIMENSION_SNAPSHOT")
    snapshot = cast("dict[str, object]", json.loads("".join(str(tag.value) for tag in tags[1:])))
    new_fields = {
        "style:dimcen",
        "style:dimexe",
        "style:dimexo",
        "style:dimdle",
        "style:dimsah",
        "style:dimblk1",
        "style:dimblk2",
        "style:dimlwd",
        "style:dimlwe",
        "style:dimltype",
        "style:dimltex1",
        "style:dimltex2",
        "style:dimse1",
        "style:dimse2",
        "style:dimsd1",
        "style:dimsd2",
    }
    v7_fields = {"style:dimsd1", "style:dimsd2"}
    v6_fields = v7_fields | {"style:dimse1", "style:dimse2"}
    v5_fields = v6_fields | {"style:dimltype", "style:dimltex1", "style:dimltex2"}
    v4_fields = v5_fields | {"style:dimlwd", "style:dimlwe"}
    removed = {"2": new_fields, "3": v4_fields, "4": v5_fields, "5": v6_fields, "6": v7_fields}
    legacy = {
        key: value
        for key, value in snapshot.items()
        if (not key.startswith("style:") if version == "1" else key not in removed[version])
    }
    payload = json.dumps(legacy, separators=(",", ":"))
    native.set_xdata(
        "MYCAD_DIMENSION_SNAPSHOT",
        [(1000, version)]
        + [(1000, payload[index : index + 240]) for index in range(0, len(payload), 240)],
    )
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert not any(
        "快照" in warning or "原生标注" in warning for warning in imported.report.warnings
    )


@pytest.mark.parametrize("kind", ["linear", "ordinate", "angle", "radius", "arc_length"])
def test_dxf_unchanged_dimension_snapshot_does_not_report_external_edits(
    tmp_path: Path, kind: str
) -> None:
    from uuid import uuid4

    first = LineEntity(uuid4().hex, (0, 0), (30, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 40))
    circle = CircleEntity(uuid4().hex, (60, 50), 10)
    arc = ArcEntity(uuid4().hex, (80, 50), 10, 0, 90)
    if kind == "angle":
        refs = (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        )
        dimension = SketchConstraint(uuid4().hex, "angle", refs, 90, "deg", driving=False)
        entities = (first, second)
    elif kind == "radius":
        dimension = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(circle.entity_id, "geometry"),),
            10,
            "mm",
            driving=False,
        )
        entities = (circle,)
    elif kind == "arc_length":
        dimension = SketchConstraint(
            uuid4().hex,
            "arc_length",
            (SketchGeometryReference(arc.entity_id, "geometry"),),
            5 * math.pi,
            "mm",
            driving=False,
        )
        entities = (arc,)
    else:
        dimension = SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(first.entity_id, "geometry"),),
            30,
            "mm",
            driving=False,
            axis="ordinate_x" if kind == "ordinate" else "aligned",
        )
        entities = (first,)
    target = tmp_path / "unchanged-dimension.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, (dimension,)), target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert not any(
        "原生标注" in warning or "外部" in warning for warning in imported.report.warnings
    )


def test_dxf_import_does_not_claim_incompatible_ordinate_precision(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (30, 40))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        axis="ordinate_x",
        precision=2,
    )
    target = tmp_path / "ordinate-rounding.dxf"
    write_sketch_dxf(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)), target)
    document = _read_test_dxf(target)
    native = next(item for item in document.modelspace() if item.dxftype() == "DIMENSION")
    override = native.override()
    override["dimdec"] = 3
    override.commit()
    cast("_TestDocument", document).saveas(target)
    imported = read_sketch_dxf(target)
    assert imported.sketch.constraints == (dimension,)
    assert any("原生标注" in warning and "未" in warning for warning in imported.report.warnings)


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("axis", ["horizontal", "vertical", "ordinate_x", "ordinate_y"])
def test_dxf_exports_explicit_axis_from_rotated_sketch(
    tmp_path: Path, axis: str, opposite: bool
) -> None:
    from uuid import uuid4

    from mycad.core.cross_sketch_tangency import project_coplanar_entity, project_coplanar_vector

    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    view_line = LineEntity(uuid4().hex, (0, 0), (20, 10))
    line = project_coplanar_entity(view_line, WorkPlaneFrame.xy(), frame)
    x_axis = axis in ("horizontal", "ordinate_x")
    sign = -1 if axis.startswith("ordinate_") else 1
    direction = project_coplanar_vector(
        (sign, 0) if x_axis else (0, sign), WorkPlaneFrame.xy(), frame
    )
    value = sign * (20 if x_axis else 10)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value,
        "mm",
        driving=False,
        axis=axis,
        projection_axis=direction,
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (50, 50)),))
    second = Sketch(uuid4().hex, frame, (line,), (dimension,))
    target = tmp_path / "rotated-axis.dxf"
    report = write_sketches_dxf((first, second), target)
    native = next(e for e in _read_test_dxf(target).modelspace() if e.dxftype() == "DIMENSION")
    if axis.startswith("ordinate_"):
        labels = [
            item.dxf.get("text")
            for item in native.virtual_entities()
            if item.dxftype() in ("TEXT", "MTEXT")
        ]
        assert labels == [f"{value:.2f} mm"]
        assert any("符号" in warning for warning in report.warnings)
    else:
        assert native.get_measurement() == pytest.approx(value)
    assert not any(
        dimension.constraint_id[:8] in warning and "不恢复关联" in warning
        for warning in report.warnings
    )


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


class _TestDimStyleAttributes(Protocol):
    dimclrt: int


class _TestDimStyle(Protocol):
    dxf: _TestDimStyleAttributes


class _TestDimStyles(Protocol):
    def get(self, name: str) -> _TestDimStyle: ...


class _TestAppIds(Protocol):
    def remove(self, name: str) -> None: ...


class _TestDocument(Protocol):
    header: MutableMapping[str, object]
    layers: _TestLayers
    dimstyles: _TestDimStyles
    appids: _TestAppIds

    def modelspace(self) -> _TestSpace: ...

    def saveas(self, path: Path) -> None: ...


class _DxfDimensionAttributes(Protocol):
    end: tuple[float, float, float]
    defpoint2: tuple[float, float, float]
    text_midpoint: tuple[float, float, float]
    text: str
    radius: float
    end_angle: float

    def get(self, name: str, default: object = None) -> object: ...


class _DxfStyleOverride(Protocol):
    def get(self, name: str, default: object = None) -> object: ...

    def __setitem__(self, name: str, value: object) -> None: ...

    def commit(self) -> None: ...


class _DxfTag(Protocol):
    value: object


class _DxfEntity(Protocol):
    dxf: _DxfDimensionAttributes

    def dxftype(self) -> str: ...

    def get_measurement(self) -> float: ...

    def render(self) -> None: ...

    def set_xdata(self, appid: str, tags: Iterable[tuple[int, str]]) -> None: ...

    def get_xdata(self, appid: str) -> Sequence[_DxfTag]: ...

    def discard_xdata(self, appid: str) -> None: ...

    def override(self) -> _DxfStyleOverride: ...

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


def test_dxf_provider_exports_multiple_coplanar_sketches(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (LineEntity("11" * 16, (0, 0), (2, 0)),))
    second = Sketch("22" * 16, WorkPlaneFrame.xy(), (CircleEntity("33" * 16, (4, 0), 2),))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_mapping())
    path = tmp_path / "multiple.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 2
    imported = read_sketch_dxf(path)
    assert imported.sketch.entities == (*first.entities, *second.entities)
    assert any("多个 MyCAD 草图身份" in warning for warning in imported.report.warnings)


def test_dxf_rejects_duplicate_source_sketch_ids_without_touching_destination(
    tmp_path: Path,
) -> None:
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    second = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("22" * 16, (2, 0)),))
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"previous")
    with pytest.raises(ValidationError, match="草图身份.*重复"):
        write_sketches_dxf((first, second), path)
    assert path.read_bytes() == b"previous"


def test_multi_sketch_dxf_restores_dimensions_from_each_sketch(tmp_path: Path) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    sketches: list[Sketch] = []
    for y in (0, 10):
        line = LineEntity(uuid4().hex, (0, y), (5, y))
        dimension = SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            5,
            "mm",
            driving=False,
        )
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
        sketches.append(sketch)
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "multi-dimensions.dxf"
    DXF_PROVIDER.write(kernel, path)
    imported = read_sketch_dxf(path)
    assert imported.sketch.entities == tuple(sketch.entities[0] for sketch in sketches)
    assert imported.sketch.constraints == tuple(sketch.constraints[0] for sketch in sketches)
    assert not any("标注与导入草图身份不一致" in warning for warning in imported.report.warnings)


def test_multi_sketch_dxf_remaps_duplicate_entity_ids_in_dimensions(tmp_path: Path) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    shared_id = uuid4().hex
    for y in (0, 10):
        line = LineEntity(shared_id, (0, y), (5, y))
        dimension = SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(shared_id, "geometry"),),
            5,
            "mm",
            driving=False,
        )
        kernel.apply(
            "sketch.create",
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)).to_state_mapping(),
        )
    path = tmp_path / "duplicate-identity.dxf"
    DXF_PROVIDER.write(kernel, path)
    imported = read_sketch_dxf(path)
    assert len(imported.sketch.entities) == len(imported.sketch.constraints) == 2
    ids = tuple(entity.entity_id for entity in imported.sketch.entities)
    assert ids[0] != ids[1]
    assert (
        tuple(constraint.references[0].entity_id for constraint in imported.sketch.constraints)
        == ids
    )
    assert any("重复" in warning for warning in imported.report.warnings)


def test_multi_sketch_dxf_preserves_dimensions_with_duplicate_constraint_ids(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    shared_constraint = uuid4().hex
    for y in (0, 10):
        line = LineEntity(uuid4().hex, (0, y), (5, y))
        dimension = SketchConstraint(
            shared_constraint,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            5,
            "mm",
            driving=False,
        )
        kernel.apply(
            "sketch.create",
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)).to_state_mapping(),
        )
    path = tmp_path / "duplicate-dimension.dxf"
    DXF_PROVIDER.write(kernel, path)
    imported = read_sketch_dxf(path)
    assert len(imported.sketch.constraints) == 2
    assert len({constraint.constraint_id for constraint in imported.sketch.constraints}) == 2
    assert tuple(
        constraint.references[0].entity_id for constraint in imported.sketch.constraints
    ) == tuple(entity.entity_id for entity in imported.sketch.entities)
    assert any(
        "标注 ID" in warning and "重新分配" in warning for warning in imported.report.warnings
    )


def test_dxf_skips_dimension_when_source_identity_is_ambiguous(tmp_path: Path) -> None:
    from uuid import uuid4

    class XDataWriter(Protocol):
        def set_xdata(self, appid: str, tags: list[tuple[int, str]]) -> None: ...

    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    path = tmp_path / "ambiguous.dxf"
    write_sketch_dxf(sketch, path)
    document = cast("_TestDocument", cast("_ReadDxf", vars(_filemanagement)["readfile"])(path))
    duplicate = cast("XDataWriter", document.modelspace().add_line((0, 10), (5, 10), dxfattribs={}))
    duplicate.set_xdata(
        "MYCAD",
        [(1000, sketch.sketch_id), (1000, line.entity_id), (1000, ""), (1000, "ccw"), (1000, "0")],
    )
    document.saveas(path)
    imported = read_sketch_dxf(path)
    assert len(imported.sketch.entities) == 2 and not imported.sketch.constraints
    assert any("身份不唯一" in warning for warning in imported.report.warnings)


def test_dxf_dimension_metadata_is_scaled_with_declared_units(tmp_path: Path) -> None:
    from uuid import uuid4

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        position_mm=(1, 3),
        text_position_mm=(1, 4),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    path = tmp_path / "inch-dimension.dxf"
    write_sketch_dxf(sketch, path)
    document = cast("_TestDocument", cast("_ReadDxf", vars(_filemanagement)["readfile"])(path))
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    imported = read_sketch_dxf(path).sketch
    assert isinstance(imported.entities[0], LineEntity)
    assert imported.entities[0].end_mm == pytest.approx((50.8, 0))
    result = imported.constraints[0]
    assert result.value == pytest.approx(50.8)
    assert result.position_mm == pytest.approx((25.4, 76.2))
    assert result.text_position_mm == pytest.approx((25.4, 101.6))


def test_dxf_unit_scaling_keeps_angle_values_in_degrees(tmp_path: Path) -> None:
    from uuid import uuid4

    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 2))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
        position_mm=(1, 1),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    path = tmp_path / "inch-angle.dxf"
    write_sketch_dxf(sketch, path)
    document = cast("_TestDocument", cast("_ReadDxf", vars(_filemanagement)["readfile"])(path))
    document.header["$INSUNITS"] = 1
    document.saveas(path)
    result = read_sketch_dxf(path).sketch.constraints[0]
    assert result.value == pytest.approx(90)
    assert result.position_mm == pytest.approx((25.4, 25.4))


def test_dxf_provider_transforms_rotated_coplanar_geometry(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (LineEntity("11" * 16, (0, 0), (2, 0)),))
    frame = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    second = Sketch(
        "22" * 16,
        frame,
        (
            PointEntity("31" * 16, (1, 2)),
            LineEntity("32" * 16, (0, 0), (2, 0)),
            CircleEntity("33" * 16, (2, 1), 1),
            ArcEntity("34" * 16, (0, 0), 2, 0, 90),
            PolylineEntity("35" * 16, ((0, 0), (2, 0)), bulges=(0.5,)),
            RectangleEntity("36" * 16, (0, 0), (2, 3)),
            SplineEntity("37" * 16, ((0, 0), (1, 0), (2, 0), (3, 1))),
        ),
    )
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "rotated.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 8
    imported = read_sketch_dxf(path).sketch.entities
    assert isinstance(imported[1], PointEntity) and imported[1].position_mm == pytest.approx((8, 6))
    assert isinstance(imported[2], LineEntity) and imported[2].end_mm == pytest.approx((10, 7))
    assert isinstance(imported[3], CircleEntity) and imported[3].center_mm == pytest.approx((9, 7))
    assert isinstance(imported[4], ArcEntity) and imported[4].start_angle_deg == pytest.approx(90)
    assert isinstance(imported[5], PolylineEntity) and imported[5].bulges == (0.5,)
    assert isinstance(imported[6], PolylineEntity) and imported[6].points_mm == (
        (10, 5),
        (10, 7),
        (7, 7),
        (7, 5),
    )
    assert isinstance(imported[7], SplineEntity) and imported[7].control_points_mm[
        -1
    ] == pytest.approx((9, 8))


def test_dxf_provider_reflects_bulge_and_arc_orientation(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), ())
    reflected = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    second = Sketch(
        "22" * 16,
        reflected,
        (
            ArcEntity("34" * 16, (0, 0), 2, 0, 90),
            PolylineEntity("35" * 16, ((0, 0), (2, 0)), bulges=(0.5,)),
        ),
    )
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "reflected.dxf"
    DXF_PROVIDER.write(kernel, path)
    imported = read_sketch_dxf(path).sketch.entities
    assert isinstance(imported[0], ArcEntity) and imported[0].sweep_angle_deg == pytest.approx(-90)
    assert isinstance(imported[1], PolylineEntity) and imported[1].bulges == (-0.5,)


def test_dxf_provider_projects_aligned_and_axis_dependent_dimensions(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (0, 0)),))
    frame = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    refs = (
        SketchGeometryReference(line.entity_id, "start"),
        SketchGeometryReference(line.entity_id, "end"),
    )
    aligned = SketchConstraint(
        uuid4().hex, "distance", refs, 5, "mm", driving=False, position_mm=(2, -2)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "distance", refs, 3, "mm", driving=False, axis="horizontal"
    )
    second = Sketch(uuid4().hex, frame, (line,), (aligned, horizontal))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "dimensions.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 4
    assert any(
        horizontal.constraint_id[:8] in warning and "关联" in warning for warning in report.warnings
    )
    native = [
        entity for entity in _read_test_dxf(path).modelspace() if entity.dxftype() == "DIMENSION"
    ]
    assert len(native) == 2
    assert sorted(entity.get_measurement() for entity in native) == pytest.approx([3, 5])


def test_dxf_provider_exports_rotated_ordinate_dimensions_with_source_axes(tmp_path: Path) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (0, 0)),))
    frame = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    refs = (
        SketchGeometryReference(line.entity_id, "start"),
        SketchGeometryReference(line.entity_id, "end"),
    )
    dimensions = tuple(
        SketchConstraint(uuid4().hex, "distance", refs, value, "mm", driving=False, axis=axis)
        for axis, value in (("ordinate_x", 3), ("ordinate_y", 4))
    )
    second = Sketch(uuid4().hex, frame, (line,), dimensions)
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "ordinate.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 4
    native = [
        entity for entity in _read_test_dxf(path).modelspace() if entity.dxftype() == "DIMENSION"
    ]
    assert len(native) == 2
    for entity in native:
        assert entity.dxf.get("horizontal_direction") == pytest.approx(-90)
        vector = cast("Sequence[float]", entity.get_measurement())
        assert (vector[0], vector[1]) == pytest.approx((-4, 3))
    labels = [
        item.dxf.get("text")
        for entity in native
        for item in entity.virtual_entities()
        if item.dxftype() in ("TEXT", "MTEXT")
    ]
    assert labels == ["3.00 mm", "4.00 mm"]
    assert all(
        any(
            dimension.constraint_id[:8] in warning and "关联" in warning
            for warning in report.warnings
        )
        for dimension in dimensions
    )


def test_dxf_provider_exports_reflected_ordinate_and_angle_dimensions(tmp_path: Path) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (0, 0)),))
    frame = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    line1 = LineEntity(uuid4().hex, (0, 0), (3, 0))
    line2 = LineEntity(uuid4().hex, (0, 0), (0, 4))
    refs = (
        SketchGeometryReference(line1.entity_id, "start"),
        SketchGeometryReference(line2.entity_id, "end"),
    )
    ordinate = SketchConstraint(
        uuid4().hex, "distance", refs, 4, "mm", driving=False, axis="ordinate_y"
    )
    angle = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(line1.entity_id, "geometry"),
            SketchGeometryReference(line2.entity_id, "geometry"),
        ),
        90,
        "deg",
        driving=False,
    )
    second = Sketch(uuid4().hex, frame, (line1, line2), (ordinate, angle))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "reflected-dimensions.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 5
    native = [
        entity for entity in _read_test_dxf(path).modelspace() if entity.dxftype() == "DIMENSION"
    ]
    assert len(native) == 2
    assert native[0].dxf.get("horizontal_direction") == pytest.approx(-180)
    assert native[1].get_measurement() == pytest.approx(90)
    labels = [
        item.dxf.get("text")
        for entity in native
        for item in entity.virtual_entities()
        if item.dxftype() in ("TEXT", "MTEXT")
    ]
    assert "4.00 mm" in labels


@pytest.mark.parametrize(("angle", "expected"), [(270, 270), (-90, 90)])
def test_dxf_reflection_preserves_major_and_signed_angle_dimensions(
    tmp_path: Path, angle: float, expected: float
) -> None:
    from uuid import uuid4

    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (0, 0)),))
    reflected = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    line1 = LineEntity(uuid4().hex, (0, 0), (3, 0))
    line2 = LineEntity(uuid4().hex, (0, 0), (0, -4))
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(line1.entity_id, "geometry"),
            SketchGeometryReference(line2.entity_id, "geometry"),
        ),
        angle,
        "deg",
        driving=False,
    )
    second = Sketch(uuid4().hex, reflected, (line1, line2), (dimension,))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "angle.dxf"
    DXF_PROVIDER.write(kernel, path)
    native = next(
        entity for entity in _read_test_dxf(path).modelspace() if entity.dxftype() == "DIMENSION"
    )
    assert native.get_measurement() == pytest.approx(expected)
    assert native.dxf.get("text") == ("-<>" if angle < 0 else "<>")


def test_dxf_provider_rejects_non_coplanar_sketches_and_keeps_kernel_unchanged(
    tmp_path: Path,
) -> None:
    kernel = BuildKernel()
    kernel.apply("sketch.create", _sketch().to_mapping())
    second = Sketch(
        "7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b",
        WorkPlaneFrame((0, 0, 5), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        (),
    )
    kernel.apply("sketch.create", second.to_mapping())
    before = kernel.sketches

    with pytest.raises(ValidationError, match="共面"):
        DXF_PROVIDER.write(kernel, tmp_path / "multiple.dxf")

    assert kernel.sketches == before
    assert not (tmp_path / "multiple.dxf").exists()


def test_dxf_rejects_slightly_tilted_planes_without_touching_destination(tmp_path: Path) -> None:
    tilt = 1e-5
    tilted = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(tilt), math.sin(tilt)),
        (0, -math.sin(tilt), math.cos(tilt)),
    )
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    second = Sketch("22" * 16, tilted, (PointEntity("33" * 16, (0, 10)),))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"previous")
    with pytest.raises(ValidationError, match="共面"):
        DXF_PROVIDER.write(kernel, path)
    assert path.read_bytes() == b"previous"


def test_dxf_rejects_sub_tolerance_tilt_with_material_plane_separation(tmp_path: Path) -> None:
    tilt = 1e-10
    tilted = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(tilt), math.sin(tilt)),
        (0, -math.sin(tilt), math.cos(tilt)),
    )
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    second = Sketch("22" * 16, tilted, (PointEntity("33" * 16, (0, 1e9)),))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"previous")
    with pytest.raises(ValidationError, match="共面"):
        DXF_PROVIDER.write(kernel, path)
    assert path.read_bytes() == b"previous"


def test_dxf_rejects_tilted_bulge_even_when_endpoints_lie_on_plane(tmp_path: Path) -> None:
    tilt = 1e-10
    tilted = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(tilt), math.sin(tilt)),
        (0, -math.sin(tilt), math.cos(tilt)),
    )
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    arc = PolylineEntity("33" * 16, ((-1e9, 0), (1e9, 0)), bulges=(1,))
    second = Sketch("22" * 16, tilted, (arc,))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    with pytest.raises(ValidationError, match="共面"):
        DXF_PROVIDER.write(kernel, tmp_path / "tilted-arc.dxf")


def test_dxf_accepts_tiny_arc_within_plane_tolerance_despite_distant_center(tmp_path: Path) -> None:
    tilt = 1e-10
    tilted = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(tilt), math.sin(tilt)),
        (0, -math.sin(tilt), math.cos(tilt)),
    )
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    arc = ArcEntity("33" * 16, (0, 1e9), 1e9, 270, 0.01)
    second = Sketch("22" * 16, tilted, (arc,))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "near-plane-arc.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport) and report.entity_count == 2
    imported = read_sketch_dxf(path).sketch.entities[1]
    assert isinstance(imported, ArcEntity) and imported.sweep_angle_deg == pytest.approx(0.01)


@pytest.mark.parametrize("amplitude,accepted", [(2000.0, True), (4000.0, False)])
def test_dxf_checks_spline_curve_not_control_polygon(
    tmp_path: Path, amplitude: float, accepted: bool
) -> None:
    tilt = 1e-10
    frame = WorkPlaneFrame(
        (0, 0, 0),
        (1, 0, 0),
        (0, math.cos(tilt), math.sin(tilt)),
        (0, -math.sin(tilt), math.cos(tilt)),
    )
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    curve = SplineEntity("33" * 16, ((0, 0), (1, amplitude), (2, -amplitude), (3, 0)))
    second = Sketch("22" * 16, frame, (curve,))
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "spline.dxf"
    if accepted:
        report = DXF_PROVIDER.write(kernel, path)
        assert isinstance(report, DxfExchangeReport) and report.entity_count == 2
    else:
        with pytest.raises(ValidationError, match="共面"):
            DXF_PROVIDER.write(kernel, path)


def test_dxf_rejects_conflicting_shared_layer_without_touching_destination(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first_layers = SketchLayerTable().add(SketchLayer("CUT", color_rgb=(255, 0, 0)))
    second_layers = SketchLayerTable().add(SketchLayer("CUT", color_rgb=(0, 0, 255)))
    first = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (PointEntity("11" * 16, (0, 0), layer_name="CUT"),),
        layers=first_layers,
    )
    second = Sketch(
        "22" * 16,
        WorkPlaneFrame.xy(),
        (PointEntity("33" * 16, (2, 0), layer_name="CUT"),),
        layers=second_layers,
    )
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "existing.dxf"
    path.write_bytes(b"previous")
    with pytest.raises(ValidationError, match="图层.*冲突"):
        DXF_PROVIDER.write(kernel, path)
    assert path.read_bytes() == b"previous"


def test_dxf_merges_identical_layer_definitions_with_different_case(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first_layers = SketchLayerTable().add(SketchLayer("CUT", color_rgb=(255, 0, 0)))
    second_layers = SketchLayerTable().add(SketchLayer("cut", color_rgb=(255, 0, 0)))
    first = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (PointEntity("11" * 16, (0, 0), layer_name="CUT"),),
        layers=first_layers,
    )
    second = Sketch(
        "22" * 16,
        WorkPlaneFrame.xy(),
        (PointEntity("33" * 16, (2, 0), layer_name="cut"),),
        layers=second_layers,
    )
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "case.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport)
    assert any("大小写" in warning for warning in report.warnings)
    imported = read_sketch_dxf(path)
    assert [entity.layer_name for entity in imported.sketch.entities] == ["CUT", "CUT"]


@pytest.mark.parametrize("bulge", [1.0, -0.5])
@pytest.mark.parametrize("closed", [False, True])
def test_bulged_polyline_import_preserves_exact_segments(
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
    assert imported.report.complete
    assert len(imported.sketch.entities) == 2
    polyline = imported.sketch.entities[1]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.closed is closed
    assert polyline.bulges == ((bulge, 0.0, 0.0) if closed else (bulge, 0.0))
    output = tmp_path / "roundtrip.dxf"
    write_sketch_dxf(imported.sketch, output)
    reopened = read_sketch_dxf(output)
    assert reopened.sketch.entities == imported.sketch.entities


def test_offset_curved_polyline_roundtrips_dxf_without_flattening(tmp_path: Path) -> None:
    from mycad.core.sketch_edit import offset_entities

    source = PolylineEntity(
        "a1" * 16, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1)
    )
    offset = offset_entities((source,), (source.entity_id,), 1)[1]
    assert isinstance(offset, PolylineEntity)
    path = tmp_path / "offset-curve.dxf"
    write_sketch_dxf(Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (offset,)), path)
    reopened = read_sketch_dxf(path)
    assert reopened.report.complete
    assert reopened.sketch.entities == (offset,)


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


def test_dxf_retains_small_rotation_on_large_rectangle(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity("11" * 16, (0, 0)),))
    angle = 1e-10
    frame = WorkPlaneFrame(
        (0, 0, 0),
        (math.cos(angle), math.sin(angle), 0),
        (-math.sin(angle), math.cos(angle), 0),
        (0, 0, 1),
    )
    rectangle = RectangleEntity("33" * 16, (0, 0), (1e9, 1e9))
    second = Sketch("22" * 16, frame, (rectangle,))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "small-rotation.dxf"
    DXF_PROVIDER.write(kernel, path)
    imported = read_sketch_dxf(path).sketch.entities[1]
    assert isinstance(imported, PolylineEntity)
    assert imported.points_mm[1] == pytest.approx((1e9, 0.1), abs=1e-7)


def test_dxf_multi_sketch_uses_first_non_xy_frame_consistently(tmp_path: Path) -> None:
    kernel = BuildKernel()
    first = Sketch(SKETCH_ID, WorkPlaneFrame.xz(), (PointEntity("11" * 16, (0, 0)),))
    frame = WorkPlaneFrame((2, 0, -3), (0, 0, -1), (-1, 0, 0), (0, 1, 0))
    second = Sketch("22" * 16, frame, (LineEntity("33" * 16, (0, 0), (2, 0)),))
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    path = tmp_path / "non-xy.dxf"
    report = DXF_PROVIDER.write(kernel, path)
    assert isinstance(report, DxfExchangeReport)
    assert any("工作平面位姿" in warning for warning in report.warnings)
    line = read_sketch_dxf(path).sketch.entities[1]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((2, 3))
    assert line.end_mm == pytest.approx((2, 5))


def test_dxf_does_not_report_projected_dimension_as_exported_when_writing_fails(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    first = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (PointEntity(uuid4().hex, (0, 0)),))
    frame = WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    references = (
        SketchGeometryReference(line.entity_id, "start"),
        SketchGeometryReference(line.entity_id, "end"),
    )
    dimension = SketchConstraint(
        uuid4().hex, "distance", references, None, "mm", driving=False, axis="horizontal"
    )
    second = Sketch(uuid4().hex, frame, (line,), (dimension,))
    report = write_sketches_dxf((first, second), tmp_path / "missing-value.dxf")
    notices = [warning for warning in report.warnings if dimension.constraint_id[:8] in warning]
    assert len(notices) == 1 and "未导出" in notices[0]
    assert "已按原坐标轴导出" not in notices[0]


def test_dxf_discards_dimension_if_rendering_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = LineEntity("33" * 16, (0, 0), (3, 4))
    dimension = SketchConstraint(
        "44" * 16,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        5.0,
        "mm",
        driving=False,
    )
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (line,), (dimension,))

    def fail_render(*args: object, **kwargs: object) -> None:
        raise ValueError("render failed")

    monkeypatch.setattr("ezdxf.entities.dimstyleoverride.DimStyleOverride.render", fail_render)
    path = tmp_path / "failed-dimension.dxf"
    report = write_sketch_dxf(sketch, path)
    assert any("未导出" in warning for warning in report.warnings)
    document = _read_test_dxf(path)
    assert all(entity.dxftype() != "DIMENSION" for entity in document.modelspace())
