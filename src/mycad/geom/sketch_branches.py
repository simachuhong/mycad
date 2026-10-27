# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Compare accepted and solved geometry independently of the optional solver."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_constraints import (
    BranchChangeKind,
    SketchBranchChange,
    SketchGeometryReference,
)

type _PointKey = tuple[str, str, int]
type _Segment = tuple[_PointKey, _PointKey]


def _geometry(sketch: Sketch) -> tuple[dict[_PointKey, Point2D], list[_Segment]]:
    points: dict[_PointKey, Point2D] = {}
    segments: list[_Segment] = []
    for entity in sketch.entities:
        identity = entity.entity_id
        if isinstance(entity, LineEntity):
            start, end = (identity, "start", 0), (identity, "end", 0)
            points[start], points[end] = entity.start_mm, entity.end_mm
            segments.append((start, end))
        elif isinstance(entity, SplineEntity):
            points.update(
                ((identity, "vertex", index), point)
                for index, point in enumerate(entity.control_points_mm)
            )
        elif isinstance(entity, CircleEntity | ArcEntity):
            points[(identity, "center", 0)] = entity.center_mm
            if isinstance(entity, ArcEntity):
                for name, angle in (
                    ("start", entity.start_angle_deg),
                    ("end", entity.start_angle_deg + entity.sweep_angle_deg),
                ):
                    radians = math.radians(angle)
                    points[(identity, name, 0)] = (
                        entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                        entity.center_mm[1] + entity.radius_mm * math.sin(radians),
                    )
        else:
            if isinstance(entity, PolylineEntity):
                vertices, closed = entity.points_mm, entity.closed
            else:
                first, opposite = entity.first_corner_mm, entity.opposite_corner_mm
                vertices = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]))
                closed = True
            keys = [(identity, "vertex", index) for index in range(len(vertices))]
            points.update(zip(keys, vertices, strict=True))
            segments.extend(zip(keys, keys[1:], strict=False))
            if closed:
                segments.append((keys[-1], keys[0]))
    return points, segments


def _point_key(
    reference: SketchGeometryReference, entities: Mapping[str, SketchEntity]
) -> _PointKey | None:
    entity = entities[reference.entity_id]
    kind, index = reference.kind, reference.index or 0
    if kind in ("start", "end") and isinstance(entity, SplineEntity):
        return (
            reference.entity_id,
            "vertex",
            0 if kind == "start" else len(entity.control_points_mm) - 1,
        )
    if kind in ("start", "end") and isinstance(entity, PolylineEntity | RectangleEntity):
        count = len(entity.points_mm) if isinstance(entity, PolylineEntity) else 3
        return entity.entity_id, "vertex", 0 if kind == "start" else count - 1
    if kind == "geometry" and isinstance(entity, CircleEntity | ArcEntity):
        return entity.entity_id, "center", 0
    if kind in ("start", "end", "center", "vertex"):
        return entity.entity_id, kind, index
    return None


def _sign(value: float, tolerance: float) -> int:
    return 1 if value > tolerance else -1 if value < -tolerance else 0


def _side(start: Point2D, end: Point2D, point: Point2D, tolerance: float) -> int:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= tolerance:
        return 0
    return _sign((dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / length, tolerance)


def _extent(points: Iterable[Point2D]) -> float:
    values = tuple(points)
    if not values:
        return 0.0
    return max(max(p[axis] for p in values) - min(p[axis] for p in values) for axis in (0, 1))


def detect_branch_changes(before: Sketch, after: Sketch) -> tuple[SketchBranchChange, ...]:
    """Report discrete side/orientation changes, not a proof of solution uniqueness.

    Side checks stay within constraint-connected components and include virtual
    point-distance segments. Their signs are invariant under translation and
    proper rotation. Direction checks additionally flag rotations over 90°.
    Near-zero sides use the same scale-aware tolerance as relation validation.
    """
    old_points, segments = _geometry(before)
    new_points, _ = _geometry(after)
    old_entities = {entity.entity_id: entity for entity in before.entities}
    new_entities = {entity.entity_id: entity for entity in after.entities}
    tolerance = max(1e-7, max(_extent(old_points.values()), _extent(new_points.values())) * 1e-9)
    changes: dict[tuple[BranchChangeKind, tuple[str, ...]], SketchBranchChange] = {}

    def record(kind: BranchChangeKind, identities: Iterable[str], message: str) -> None:
        ids = tuple(sorted(set(identities)))
        changes[(kind, ids)] = SketchBranchChange(kind, ids, message)

    parents = {identity: identity for identity in old_entities}

    def root(identity: str) -> str:
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    for constraint in after.constraints:
        ids = [ref.entity_id for ref in constraint.references if ref.entity_id in parents]
        for identity in ids[1:]:
            parents[root(identity)] = root(ids[0])
        if constraint.kind == "distance" and len(constraint.references) == 2:
            first, second = (_point_key(ref, old_entities) for ref in constraint.references)
            if (
                first is not None
                and second is not None
                and first in old_points
                and second in old_points
            ):
                segments.append((first, second))
    groups: dict[str, list[_PointKey]] = {}
    for key in old_points:
        if key in new_points:
            groups.setdefault(root(key[0]), []).append(key)
    for start, end in dict.fromkeys(segments):
        if start not in new_points or end not in new_points:
            continue
        a, b, c, d = old_points[start], old_points[end], new_points[start], new_points[end]
        old_length, new_length = math.dist(a, b), math.dist(c, d)
        ids = (start[0], end[0])
        if (old_length <= tolerance) != (new_length <= tolerance):
            record("degeneracy", ids, "线段或点距进入/离开近退化位置")
        if old_length > tolerance and new_length > tolerance:
            dot = (b[0] - a[0]) * (d[0] - c[0]) + (b[1] - a[1]) * (d[1] - c[1])
            if dot < -old_length * new_length * 1e-9:
                record("direction", ids, "线段或点距方向变化超过 90°")
        for point in groups[root(start[0])]:
            if point in (start, end):
                continue
            old_side, new_side = (
                _side(a, b, old_points[point], tolerance),
                _side(c, d, new_points[point], tolerance),
            )
            if old_side != new_side:
                if old_side and new_side:
                    record("side", (*ids, point[0]), "相关几何跨越基准线，所在侧改变")
                else:
                    record("degeneracy", (*ids, point[0]), "相关几何进入/离开临界共线位置")
    for identity, old in old_entities.items():
        new = new_entities.get(identity)
        if isinstance(old, ArcEntity) and isinstance(new, ArcEntity):
            if old.sweep_angle_deg * new.sweep_angle_deg < 0:
                record("arc_sweep", (identity,), "圆弧顺逆时针方向改变")
            if _sign(abs(old.sweep_angle_deg) - 180, 1e-7) != _sign(
                abs(new.sweep_angle_deg) - 180, 1e-7
            ):
                record("arc_span", (identity,), "圆弧跨越半圆位置，优弧/劣弧分支改变")
    for constraint in before.constraints:
        if constraint.kind not in ("tangent", "concentric") or len(constraint.references) != 2:
            continue
        first_id, second_id = (ref.entity_id for ref in constraint.references)
        old_first, old_second = old_entities[first_id], old_entities[second_id]
        new_first, new_second = new_entities.get(first_id), new_entities.get(second_id)
        if not (
            isinstance(old_first, CircleEntity | ArcEntity)
            and isinstance(old_second, CircleEntity | ArcEntity)
            and isinstance(new_first, CircleEntity | ArcEntity)
            and isinstance(new_second, CircleEntity | ArcEntity)
        ):
            continue
        if constraint.kind == "tangent":
            old_external = (
                abs(
                    math.dist(old_first.center_mm, old_second.center_mm)
                    - old_first.radius_mm
                    - old_second.radius_mm
                )
                <= tolerance
            )
            new_external = (
                abs(
                    math.dist(new_first.center_mm, new_second.center_mm)
                    - new_first.radius_mm
                    - new_second.radius_mm
                )
                <= tolerance
            )
            if old_external != new_external:
                record("tangency", (first_id, second_id), "内相切/外相切分支改变")
        elif _sign(old_first.radius_mm - old_second.radius_mm, tolerance) != _sign(
            new_first.radius_mm - new_second.radius_mm, tolerance
        ):
            record("nesting", (first_id, second_id), "同心圆弧的内外大小关系改变")
    return tuple(changes.values())
