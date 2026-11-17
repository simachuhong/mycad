# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact local-U/V paper curves from immutable authored sketch geometry."""

from collections import Counter

from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    DrawingProjectionRequest,
    LineCurve,
    ProjectedCurve,
    ProjectionResult,
    SplineCurve,
)
from mycad.core.drawing_references import DrawingGeometryReference
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
)


def _curves(entity: SketchEntity) -> tuple[CurveGeometry, ...]:
    if isinstance(entity, PointEntity):
        return ()
    if isinstance(entity, LineEntity):
        return (LineCurve(entity.start_mm, entity.end_mm),)
    if isinstance(entity, CircleEntity):
        return (ArcCurve(entity.center_mm, entity.radius_mm),)
    if isinstance(entity, ArcEntity):
        return (
            ArcCurve(
                entity.center_mm, entity.radius_mm, entity.start_angle_deg, entity.sweep_angle_deg
            ),
        )
    if isinstance(entity, PolylineEntity) and entity.bulges:
        return tuple(
            ArcCurve(
                segment.center_mm,
                segment.radius_mm,
                segment.start_angle_deg,
                segment.sweep_angle_deg,
            )
            if isinstance(segment, ArcEntity)
            else LineCurve(segment.start_mm, segment.end_mm)
            for segment in polyline_curve_segments(
                entity.points_mm, entity.bulges, entity.closed, entity.entity_id
            )
        )
    if isinstance(entity, RectangleEntity | PolylineEntity):
        if isinstance(entity, RectangleEntity):
            a, b = entity.first_corner_mm, entity.opposite_corner_mm
            points = (a, (b[0], a[1]), b, (a[0], b[1]), a)
        else:
            points = entity.points_mm + ((entity.points_mm[0],) if entity.closed else ())
        return tuple(LineCurve(a, b) for a, b in zip(points, points[1:], strict=False))
    knots = Counter(entity.knots)
    return (
        SplineCurve(
            entity.control_points_mm,
            3,
            tuple(knots),
            tuple(knots.values()),
            (1.0,) * len(entity.control_points_mm),
        ),
    )


def project_sketch(sketch: Sketch, request: DrawingProjectionRequest) -> ProjectionResult:
    """Keep authored segment order as topology; never flatten via sampled polylines."""
    if request.source != "sketch" or request.sketch_id != sketch.sketch_id:
        return ProjectionResult(
            request.view_id,
            request.source_fingerprint,
            request.generation,
            (),
            ("草图来源已改变或不存在，请重新选择来源",),
        )
    curves: list[ProjectedCurve] = []
    for entity in sketch.entities:
        if entity.construction or not sketch.layers.get(entity.layer_name).displayed:
            continue
        for index, geometry in enumerate(_curves(entity)):
            source = DrawingGeometryReference(
                "sketch_entity",
                (("segment", float(index)),),
                sketch_id=sketch.sketch_id,
                entity_id=entity.entity_id,
            )
            curves.append(ProjectedCurve(f"{entity.entity_id}:{index}", geometry, source=source))
    return ProjectionResult(
        request.view_id,
        request.source_fingerprint,
        request.generation,
        tuple(curves),
        () if curves else ("草图没有可显示的非构造曲线，请检查图元与图层可见性",),
    )
