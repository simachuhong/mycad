# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Kernel-backed planar region measurements, including exact B-splines."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import cast
from uuid import uuid4

from build123d import Edge, Face, Plane, Wire
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape

from mycad.core.drawing_curved_arrangement import arc_point
from mycad.core.drawing_quick_regions import SampledMeasuredRegion
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.geom.sketch_profiles import spline_edge


def _member(value: object, name: str) -> object:
    return getattr(value, name)


@dataclass(frozen=True)
class PlanarMeasurementRegion:
    """A bounded kernel face with exact numerical area and perimeter."""

    face: Face
    area_mm2: float
    perimeter_mm: float

    def contains(self, point: Point2D) -> bool:
        """Accept strict interior points, excluding the face boundary."""
        make_classifier = cast(
            "Callable[[TopoDS_Face, gp_Pnt, float], object]",
            import_module("OCP.BRepClass").BRepClass_FaceClassifier,
        )
        classifier = make_classifier(self.face.wrapped, gp_Pnt(*point, 0), 1e-7)
        state = cast("Callable[[], object]", _member(classifier, "State"))()
        return state == cast("object", import_module("OCP.TopAbs").TopAbs_IN)


def _edge(entity: LineEntity | ArcEntity | CircleEntity | SplineEntity | EllipseEntity) -> Edge:
    if isinstance(entity, EllipseEntity):
        from mycad.geom.offset_ellipse import ellipse_edge

        return ellipse_edge(entity)
    if isinstance(entity, LineEntity):
        return Edge.make_line((*entity.start_mm, 0), (*entity.end_mm, 0))
    if isinstance(entity, CircleEntity):
        return Edge.make_circle(entity.radius_mm, Plane(origin=(*entity.center_mm, 0)))
    if isinstance(entity, ArcEntity):
        return Edge.make_three_point_arc(
            (*arc_point(entity, 0), 0), (*arc_point(entity, 0.5), 0), (*arc_point(entity, 1), 0)
        )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    return spline_edge(sketch, entity)


def _edges(entities: Sequence[SketchEntity]) -> tuple[Edge, ...]:
    result: list[Edge] = []
    for entity in entities:
        if isinstance(entity, PointEntity):
            continue
        if isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            result.extend(
                Edge.make_line((*a, 0), (*b, 0))
                for a, b in zip(points, (*points[1:], points[0]), strict=True)
            )
        elif isinstance(entity, PolylineEntity):
            count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
            result.extend(
                _edge(segment)
                for segment in polyline_curve_segments(
                    entity.points_mm,
                    entity.bulges or (0.0,) * count,
                    entity.closed,
                    entity.entity_id,
                )
            )
        else:
            result.append(_edge(entity))
    return tuple(result)


def build_planar_measurement_regions(
    entities: Sequence[SketchEntity],
) -> tuple[PlanarMeasurementRegion, ...]:
    """Split bounded faces using exact kernel curves; the outside face is omitted."""
    edges = _edges(entities)
    if not edges:
        return ()
    boxes = tuple(edge.bounding_box() for edge in edges)
    xmin, xmax = min(box.min.X for box in boxes), max(box.max.X for box in boxes)
    ymin, ymax = min(box.min.Y for box in boxes), max(box.max.Y for box in boxes)
    size = max(xmax - xmin, ymax - ymin, 1.0)
    margin = 2 * size
    center_x, center_y = xmin + (xmax - xmin) / 2, ymin + (ymax - ymin) / 2
    width, height = xmax - xmin + 2 * margin, ymax - ymin + 2 * margin
    if not all(math.isfinite(value) for value in (center_x, center_y, width, height)):
        raise ValueError("区域坐标超出可测量范围。")
    outer = Face.make_rect(width, height, Plane(origin=(center_x, center_y, 0)))
    make_splitter = cast("Callable[[], object]", import_module("OCP.BOPAlgo").BOPAlgo_Splitter)
    solver = make_splitter()
    cast("Callable[[TopoDS_Shape], None]", _member(solver, "AddArgument"))(outer.wrapped)
    add_tool = cast("Callable[[TopoDS_Shape], None]", _member(solver, "AddTool"))
    for edge in edges:
        add_tool(edge.wrapped)
    cast("Callable[[], None]", _member(solver, "Perform"))()
    if cast("Callable[[], bool]", _member(solver, "HasErrors"))():
        raise ValueError("几何内核无法分割区域。")
    shape = cast("Callable[[], TopoDS_Shape]", _member(solver, "Shape"))()
    make_explorer = cast(
        "Callable[[TopoDS_Shape, object], object]",
        import_module("OCP.TopExp").TopExp_Explorer,
    )
    explorer = make_explorer(shape, cast("object", import_module("OCP.TopAbs").TopAbs_FACE))
    more = cast("Callable[[], bool]", _member(explorer, "More"))
    current = cast("Callable[[], TopoDS_Shape]", _member(explorer, "Current"))
    advance = cast("Callable[[], None]", _member(explorer, "Next"))
    result: list[PlanarMeasurementRegion] = []
    while more():
        face = Face(TopoDS.Face_s(current()))
        box = face.bounding_box()
        if (
            xmin - margin / 2 < box.min.X
            and xmax + margin / 2 > box.max.X
            and ymin - margin / 2 < box.min.Y
            and ymax + margin / 2 > box.max.Y
        ):
            area = face.area
            perimeter = math.fsum(wire.length for wire in face.wires())
            if not math.isfinite(area) or not math.isfinite(perimeter):
                raise ValueError("区域面积或周长超出可测量范围。")
            if area > 0:
                result.append(PlanarMeasurementRegion(face, area, perimeter))
        advance()
    return tuple(result)


def measure_planar_region_at(
    entities: Sequence[SketchEntity], point: Point2D
) -> SampledMeasuredRegion | None:
    """Measure the unique strict interior face and return neutral display data."""
    matches = tuple(
        region for region in build_planar_measurement_regions(entities) if region.contains(point)
    )
    if len(matches) != 1:
        return None
    region = matches[0]

    def sample(wire: Wire) -> tuple[Point2D, ...]:
        return tuple((vector.X, vector.Y) for vector in wire.positions(i / 512 for i in range(512)))

    return SampledMeasuredRegion(
        sample(region.face.outer_wire()),
        tuple(sample(wire) for wire in region.face.inner_wires()),
        region.area_mm2,
        region.perimeter_mm,
    )
