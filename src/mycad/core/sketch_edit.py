# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic editing operations for neutral sketch geometry."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from typing import cast
from uuid import uuid4

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
    polyline_self_intersection,
)
from mycad.core.sketch_constraints import SketchGeometryReference

_EPSILON = 1e-10


def _cross(first: Point2D, second: Point2D) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _finite_point(point: Point2D, name: str) -> Point2D:
    candidate = cast("object", point)
    if (
        not isinstance(candidate, (tuple, list))
        or len(cast("Sequence[object]", candidate)) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for value in cast("Sequence[object]", candidate)
        )
        or any(
            not math.isfinite(cast("float", value)) for value in cast("Sequence[object]", candidate)
        )
    ):
        raise ValueError(f"{name} must contain two finite coordinates")
    values = cast("Sequence[float]", candidate)
    return (float(values[0]), float(values[1]))


def _finite_angle(angle_deg: float, name: str) -> float:
    candidate = cast("object", angle_deg)
    if isinstance(candidate, bool) or not isinstance(candidate, int | float):
        raise ValueError(f"{name} must be finite")
    angle = float(candidate)
    if not math.isfinite(angle):
        raise ValueError(f"{name} must be finite")
    return angle


def _selected_entities(
    entities: tuple[SketchEntity, ...], selected_ids: tuple[str, ...]
) -> tuple[tuple[int, SketchEntity], ...]:
    if not selected_ids:
        raise ValueError("请选择至少一个草图元素。")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("选择中包含重复的草图元素。")
    by_id: dict[str, tuple[int, SketchEntity]] = {}
    for index, entity in enumerate(entities):
        if entity.entity_id in by_id:
            raise ValueError("草图中存在重复的元素身份，无法安全编辑。")
        by_id[entity.entity_id] = (index, entity)
    missing = tuple(identity for identity in selected_ids if identity not in by_id)
    if missing:
        raise ValueError(f"选择的草图元素不存在：{missing[0]}")
    selected = set(selected_ids)
    return tuple(item for item in by_id.values() if item[1].entity_id in selected)


def _preserve_entity_metadata[EntityT: SketchEntity](
    source: SketchEntity, target: EntityT
) -> EntityT:
    """Carry construction and layer semantics across a geometric operation."""
    return replace(target, construction=source.construction, layer_name=source.layer_name)


def _copy_identity(entity: SketchEntity) -> SketchEntity:
    identity = uuid4().hex
    if isinstance(entity, SplineEntity):
        return replace(entity, entity_id=identity)
    if isinstance(entity, LineEntity):
        result: SketchEntity = LineEntity(
            identity, entity.start_mm, entity.end_mm, entity.construction
        )
    elif isinstance(entity, PolylineEntity):
        result = PolylineEntity(identity, entity.points_mm, entity.closed, entity.construction)
    elif isinstance(entity, CircleEntity):
        result = CircleEntity(identity, entity.center_mm, entity.radius_mm, entity.construction)
    elif isinstance(entity, ArcEntity):
        result = ArcEntity(
            identity,
            entity.center_mm,
            entity.radius_mm,
            entity.start_angle_deg,
            entity.sweep_angle_deg,
            entity.construction,
        )
    else:
        result = RectangleEntity(
            identity, entity.first_corner_mm, entity.opposite_corner_mm, entity.construction
        )
    return _preserve_entity_metadata(entity, result)


def _transformed_entity(
    entity: SketchEntity,
    transform_point: Callable[[Point2D], Point2D],
    *,
    angle_delta_deg: float = 0.0,
    reflected_axis_angle_deg: float | None = None,
) -> SketchEntity:
    if isinstance(entity, SplineEntity):
        return replace(
            entity,
            control_points_mm=tuple(transform_point(point) for point in entity.control_points_mm),
        )
    if isinstance(entity, LineEntity):
        result: SketchEntity = LineEntity(
            entity.entity_id,
            transform_point(entity.start_mm),
            transform_point(entity.end_mm),
            entity.construction,
        )
    elif isinstance(entity, PolylineEntity):
        result = PolylineEntity(
            entity.entity_id,
            tuple(transform_point(point) for point in entity.points_mm),
            entity.closed,
            entity.construction,
        )
    elif isinstance(entity, CircleEntity):
        result = CircleEntity(
            entity.entity_id,
            transform_point(entity.center_mm),
            entity.radius_mm,
            entity.construction,
        )
    elif isinstance(entity, ArcEntity):
        start_angle = (
            2.0 * reflected_axis_angle_deg - entity.start_angle_deg
            if reflected_axis_angle_deg is not None
            else entity.start_angle_deg + angle_delta_deg
        )
        sweep_angle = (
            -entity.sweep_angle_deg
            if reflected_axis_angle_deg is not None
            else entity.sweep_angle_deg
        )
        result = ArcEntity(
            entity.entity_id,
            transform_point(entity.center_mm),
            entity.radius_mm,
            start_angle,
            sweep_angle,
            entity.construction,
        )

    else:
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm

        def normalize(point: Point2D) -> Point2D:
            transformed = transform_point(point)
            return (
                0.0 if abs(transformed[0]) <= _EPSILON else transformed[0],
                0.0 if abs(transformed[1]) <= _EPSILON else transformed[1],
            )

        corners: tuple[Point2D, ...] = tuple(
            normalize(point) for point in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        )
        xs = tuple(point[0] for point in corners)
        ys = tuple(point[1] for point in corners)
        minimum_x, maximum_x = min(xs), max(xs)
        minimum_y, maximum_y = min(ys), max(ys)
        if (
            maximum_x - minimum_x > _EPSILON
            and maximum_y - minimum_y > _EPSILON
            and all(
                abs(value - minimum_x) <= _EPSILON or abs(value - maximum_x) <= _EPSILON
                for value in xs
            )
            and all(
                abs(value - minimum_y) <= _EPSILON or abs(value - maximum_y) <= _EPSILON
                for value in ys
            )
            and all(
                any(
                    abs(point[0] - expected_x) <= _EPSILON
                    and abs(point[1] - expected_y) <= _EPSILON
                    for point in corners
                )
                for expected_x in (minimum_x, maximum_x)
                for expected_y in (minimum_y, maximum_y)
            )
        ):
            result = RectangleEntity(
                entity.entity_id,
                (min(xs), min(ys)),
                (max(xs), max(ys)),
                entity.construction,
            )
        else:
            result = PolylineEntity(
                entity.entity_id, corners, closed=True, construction=entity.construction
            )
    return _preserve_entity_metadata(entity, result)


def _replace_selected(
    entities: tuple[SketchEntity, ...],
    selected: tuple[tuple[int, SketchEntity], ...],
    transform: Callable[[SketchEntity], SketchEntity],
) -> tuple[SketchEntity, ...]:
    replacements = {
        index: _preserve_entity_metadata(entity, transform(entity)) for index, entity in selected
    }
    return tuple(replacements.get(index, entity) for index, entity in enumerate(entities))


def move_entities(
    entities: tuple[SketchEntity, ...], selected_ids: tuple[str, ...], delta_mm: Point2D
) -> tuple[SketchEntity, ...]:
    """Translate selected draft entities while preserving their identities."""
    dx, dy = _finite_point(delta_mm, "move delta")
    selected = _selected_entities(entities, selected_ids)
    return _replace_selected(entities, selected, lambda entity: _translated_entity(entity, dx, dy))


def move_sketch_handle(
    entities: Sequence[SketchEntity],
    reference: SketchGeometryReference,
    point_mm: Point2D,
) -> tuple[SketchEntity, ...]:
    """Move one editable sketch point while preserving entity identity and metadata."""
    point = _finite_point(point_mm, "sketch handle point")
    result = tuple(entities)
    entity_index = next(
        (index for index, entity in enumerate(result) if entity.entity_id == reference.entity_id),
        None,
    )
    if entity_index is None:
        raise ValueError(f"sketch handle references missing entity {reference.entity_id!r}")
    entity = result[entity_index]
    if isinstance(entity, SplineEntity):
        if (
            reference.kind != "vertex"
            or reference.index is None
            or not 0 <= reference.index < len(entity.control_points_mm)
        ):
            raise ValueError("样条控制点索引无效。")
        controls = list(entity.control_points_mm)
        controls[reference.index] = point
        return (
            *result[:entity_index],
            replace(entity, control_points_mm=tuple(controls)),
            *result[entity_index + 1 :],
        )
    if isinstance(entity, LineEntity):
        if reference.kind == "start":
            changed: SketchEntity = replace(entity, start_mm=point)
        elif reference.kind == "end":
            changed = replace(entity, end_mm=point)
        else:
            raise ValueError("line handle must reference its start or end point")
    elif isinstance(entity, PolylineEntity):
        if reference.kind != "vertex" or reference.index is None:
            raise ValueError("polyline handle must reference a vertex")
        if reference.index >= len(entity.points_mm):
            raise ValueError("polyline handle vertex is outside the path")
        points = list(entity.points_mm)
        points[reference.index] = point
        changed = replace(entity, points_mm=tuple(points))
    elif isinstance(entity, RectangleEntity):
        if reference.kind != "vertex" or reference.index not in (0, 1, 2, 3):
            raise ValueError("rectangle handle must reference one of its four corners")
        first_u, first_v = entity.first_corner_mm
        opposite_u, opposite_v = entity.opposite_corner_mm
        if reference.index == 0:
            first_u, first_v = point
        elif reference.index == 1:
            first_v, opposite_u = point[1], point[0]
        elif reference.index == 2:
            opposite_u, opposite_v = point
        else:
            first_u, opposite_v = point[0], point[1]
        changed = replace(
            entity,
            first_corner_mm=(first_u, first_v),
            opposite_corner_mm=(opposite_u, opposite_v),
        )
    elif isinstance(entity, CircleEntity):
        if reference.kind != "center":
            raise ValueError("circle handle must reference its center")
        changed = replace(entity, center_mm=point)
    else:
        if reference.kind == "center":
            delta = (point[0] - entity.center_mm[0], point[1] - entity.center_mm[1])
            changed = replace(entity, center_mm=point)
            if math.hypot(*delta) <= _EPSILON:
                changed = entity
        elif reference.kind in ("start", "end"):
            dx = point[0] - entity.center_mm[0]
            dy = point[1] - entity.center_mm[1]
            radius = math.hypot(dx, dy)
            if radius <= _EPSILON:
                raise ValueError("arc endpoint cannot coincide with its center")
            angle = math.degrees(math.atan2(dy, dx))
            positive_sweep = entity.sweep_angle_deg > 0.0
            if reference.kind == "start":
                old_end_angle = entity.start_angle_deg + entity.sweep_angle_deg
                sweep = (
                    (old_end_angle - angle) % 360.0
                    if positive_sweep
                    else -((angle - old_end_angle) % 360.0)
                )
                changed = replace(
                    entity, radius_mm=radius, start_angle_deg=angle, sweep_angle_deg=sweep
                )
            else:
                sweep = (
                    (angle - entity.start_angle_deg) % 360.0
                    if positive_sweep
                    else -((entity.start_angle_deg - angle) % 360.0)
                )
                changed = replace(entity, radius_mm=radius, sweep_angle_deg=sweep)
        else:
            raise ValueError("arc handle must reference its center, start, or end point")
    return (*result[:entity_index], changed, *result[entity_index + 1 :])


def _translated_entity(entity: SketchEntity, dx: float, dy: float) -> SketchEntity:
    return _transformed_entity(entity, lambda point: (point[0] + dx, point[1] + dy))


def copy_entities(
    entities: tuple[SketchEntity, ...], selected_ids: tuple[str, ...], delta_mm: Point2D
) -> tuple[SketchEntity, ...]:
    """Append translated copies of selected entities with new identities."""
    dx, dy = _finite_point(delta_mm, "copy delta")
    selected = _selected_entities(entities, selected_ids)
    clones = tuple(
        _translated_entity(_copy_identity(entity), dx, dy) for _index, entity in selected
    )
    return (*entities, *clones)


def rotate_entities(
    entities: tuple[SketchEntity, ...],
    selected_ids: tuple[str, ...],
    center_mm: Point2D,
    angle_deg: float,
) -> tuple[SketchEntity, ...]:
    """Rotate selected draft entities counterclockwise around a local point."""
    center = _finite_point(center_mm, "rotation center")
    angle = _finite_angle(angle_deg, "rotation angle")
    selected = _selected_entities(entities, selected_ids)
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)

    def transform(point: Point2D) -> Point2D:
        dx, dy = point[0] - center[0], point[1] - center[1]
        return (center[0] + cosine * dx - sine * dy, center[1] + sine * dx + cosine * dy)

    return _replace_selected(
        entities,
        selected,
        lambda entity: _transformed_entity(entity, transform, angle_delta_deg=angle),
    )


def mirror_entities(
    entities: tuple[SketchEntity, ...],
    selected_ids: tuple[str, ...],
    axis_start_mm: Point2D,
    axis_end_mm: Point2D,
) -> tuple[SketchEntity, ...]:
    """Reflect selected draft entities across an infinite local sketch line."""
    start = _finite_point(axis_start_mm, "mirror axis start")
    end = _finite_point(axis_end_mm, "mirror axis end")
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= _EPSILON:
        raise ValueError("镜像轴必须有非零长度。")
    axis_angle = math.degrees(math.atan2(dy, dx))
    ux, uy = dx / length, dy / length
    selected = _selected_entities(entities, selected_ids)

    def transform(point: Point2D) -> Point2D:
        px, py = point[0] - start[0], point[1] - start[1]
        projection = px * ux + py * uy
        return (start[0] + 2.0 * projection * ux - px, start[1] + 2.0 * projection * uy - py)

    return _replace_selected(
        entities,
        selected,
        lambda entity: _transformed_entity(entity, transform, reflected_axis_angle_deg=axis_angle),
    )


def _array_count(count: int) -> int:
    if isinstance(count, bool) or count < 2:
        raise ValueError("阵列总数必须至少为 2。")
    return count


def linear_array_entities(
    entities: tuple[SketchEntity, ...],
    selected_ids: tuple[str, ...],
    *,
    count: int,
    step_mm: Point2D,
) -> tuple[SketchEntity, ...]:
    """Append a linear pattern; count includes the original selection."""
    total = _array_count(count)
    dx, dy = _finite_point(step_mm, "linear array step")
    if math.hypot(dx, dy) <= _EPSILON:
        raise ValueError("线性阵列步距不能为零。")
    selected = _selected_entities(entities, selected_ids)
    additions: list[SketchEntity] = []
    for index in range(1, total):
        additions.extend(
            _translated_entity(_copy_identity(entity), index * dx, index * dy)
            for _source_index, entity in selected
        )
    return (*entities, *additions)


def circular_array_entities(
    entities: tuple[SketchEntity, ...],
    selected_ids: tuple[str, ...],
    *,
    count: int,
    center_mm: Point2D,
    total_angle_deg: float = 360.0,
) -> tuple[SketchEntity, ...]:
    """Append a circular pattern; full turns omit a duplicate endpoint."""
    total = _array_count(count)
    center = _finite_point(center_mm, "circular array center")
    angle = _finite_angle(total_angle_deg, "circular array angle")
    if abs(angle) <= _EPSILON or abs(angle) > 360.0:
        raise ValueError("环形阵列角度必须大于 0 且不超过 360 度。")
    selected = _selected_entities(entities, selected_ids)
    full_turn = abs(abs(angle) - 360.0) <= _EPSILON
    angular_step = angle / total if full_turn else angle / (total - 1)
    additions: list[SketchEntity] = []
    for index in range(1, total):
        step_angle = angular_step * index
        radians = math.radians(step_angle)
        cosine, sine = math.cos(radians), math.sin(radians)

        def transform(
            point: Point2D, cosine_value: float = cosine, sine_value: float = sine
        ) -> Point2D:
            dx, dy = point[0] - center[0], point[1] - center[1]
            return (
                center[0] + cosine_value * dx - sine_value * dy,
                center[1] + sine_value * dx + cosine_value * dy,
            )

        additions.extend(
            _transformed_entity(_copy_identity(entity), transform, angle_delta_deg=step_angle)
            for _source_index, entity in selected
        )
    return (*entities, *additions)


def _signed_polygon_area(points: tuple[Point2D, ...]) -> float:
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, (*points[1:], points[0]), strict=True)
    )


def _offset_edge_point(start: Point2D, end: Point2D, distance_mm: float) -> Point2D:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= _EPSILON:
        raise ValueError("偏移路径包含零长度或过短线段。")
    normal = (-dy / length, dx / length)
    return (start[0] + normal[0] * distance_mm, start[1] + normal[1] * distance_mm)


def _offset_corner(
    point: Point2D,
    previous: Point2D,
    following: Point2D,
    distance_mm: float,
) -> Point2D:
    previous_length = math.hypot(point[0] - previous[0], point[1] - previous[1])
    following_length = math.hypot(following[0] - point[0], following[1] - point[1])
    if min(previous_length, following_length) <= _EPSILON:
        raise ValueError("偏移路径包含零长度或过短线段。")
    previous_direction = (
        (point[0] - previous[0]) / previous_length,
        (point[1] - previous[1]) / previous_length,
    )
    following_direction = (
        (following[0] - point[0]) / following_length,
        (following[1] - point[1]) / following_length,
    )
    previous_offset = _offset_edge_point(point, previous, -distance_mm)
    following_offset = _offset_edge_point(point, following, distance_mm)
    denominator = _cross(previous_direction, following_direction)
    if abs(denominator) <= _EPSILON:
        dot = (
            previous_direction[0] * following_direction[0]
            + previous_direction[1] * following_direction[1]
        )
        if dot > 0.0:
            return previous_offset
        raise ValueError("偏移在反向折返处没有唯一交点。")
    delta = (
        following_offset[0] - previous_offset[0],
        following_offset[1] - previous_offset[1],
    )
    ratio = _cross(delta, following_direction) / denominator
    intersection = (
        previous_offset[0] + ratio * previous_direction[0],
        previous_offset[1] + ratio * previous_direction[1],
    )
    miter_length = math.hypot(intersection[0] - point[0], intersection[1] - point[1])
    if miter_length > max(abs(distance_mm) * 20.0, abs(distance_mm) + _EPSILON):
        raise ValueError("偏移角过尖，交点距离过大；请缩小偏移量或分段处理。")
    return intersection


def _offset_polyline(entity: PolylineEntity, distance_mm: float, identity: str) -> PolylineEntity:
    points = entity.points_mm
    count = len(points)
    offset_points: list[Point2D] = []
    for index, point in enumerate(points):
        if not entity.closed and index == 0:
            offset_points.append(_offset_edge_point(points[0], points[1], distance_mm))
            continue
        if not entity.closed and index == count - 1:
            offset_points.append(_offset_edge_point(points[-1], points[-2], -distance_mm))
            continue
        previous_index = (index - 1) % count
        following_index = (index + 1) % count
        offset_points.append(
            _offset_corner(
                point,
                points[previous_index],
                points[following_index],
                distance_mm,
            )
        )
    result_points = tuple(offset_points)
    segment_count = count if entity.closed else count - 1
    for index in range(segment_count):
        following = (index + 1) % count
        dot = (result_points[following][0] - result_points[index][0]) * (
            points[following][0] - points[index][0]
        ) + (result_points[following][1] - result_points[index][1]) * (
            points[following][1] - points[index][1]
        )
        if dot <= _EPSILON:
            raise ValueError(
                f"偏移距离过大，图元 {entity.entity_id} 第 {index + 1} 段已收缩为零或发生反转。"
            )
    if entity.closed:
        original_area = _signed_polygon_area(points)
        result_area = _signed_polygon_area(result_points)
        if abs(result_area) <= _EPSILON or original_area * result_area <= 0.0:
            raise ValueError("偏移距离过大，轮廓已收缩为零或发生反转。")
    crossing = polyline_self_intersection(result_points, closed=entity.closed)
    if crossing is not None:
        first, second = crossing
        raise ValueError(
            f"偏移结果自交或交叠：图元 {entity.entity_id} 第 {first + 1}/{second + 1} 段；"
            "请缩小偏移量或分段处理。"
        )
    try:
        return _preserve_entity_metadata(
            entity, PolylineEntity(identity, result_points, entity.closed, entity.construction)
        )
    except ValueError as exc:
        raise ValueError("偏移结果形成自交或退化轮廓；请缩小偏移量或分段处理。") from exc


def _offset_entity(entity: SketchEntity, distance_mm: float) -> SketchEntity:
    if isinstance(entity, SplineEntity):
        raise ValueError("样条曲线暂不支持偏移；草稿未修改。")
    identity = uuid4().hex
    if isinstance(entity, LineEntity):
        start = _offset_edge_point(entity.start_mm, entity.end_mm, distance_mm)
        end = _offset_edge_point(entity.end_mm, entity.start_mm, -distance_mm)
        return _preserve_entity_metadata(
            entity, LineEntity(identity, start, end, entity.construction)
        )
    if isinstance(entity, PolylineEntity):
        return _offset_polyline(entity, distance_mm, identity)
    if isinstance(entity, RectangleEntity):
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        outline = _preserve_entity_metadata(
            entity,
            PolylineEntity(
                entity.entity_id,
                ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                closed=True,
                construction=entity.construction,
            ),
        )
        return _offset_polyline(outline, distance_mm, identity)
    if isinstance(entity, CircleEntity):
        radius = entity.radius_mm + distance_mm
        if radius <= _EPSILON:
            raise ValueError("偏移量使圆半径归零或反转。")
        return _preserve_entity_metadata(
            entity, CircleEntity(identity, entity.center_mm, radius, entity.construction)
        )
    radius = entity.radius_mm - math.copysign(distance_mm, entity.sweep_angle_deg)
    if radius <= _EPSILON:
        raise ValueError("偏移量使圆弧半径归零或反转。")
    return _preserve_entity_metadata(
        entity,
        ArcEntity(
            identity,
            entity.center_mm,
            radius,
            entity.start_angle_deg,
            entity.sweep_angle_deg,
            entity.construction,
        ),
    )


def offset_entities(
    entities: tuple[SketchEntity, ...], selected_ids: tuple[str, ...], distance_mm: float
) -> tuple[SketchEntity, ...]:
    """Append parallel copies; polygon/polyline offsets use mitered signed normals."""
    distance = _finite_angle(distance_mm, "offset distance")
    if abs(distance) <= _EPSILON:
        raise ValueError("偏移距离必须为非零值。")
    selected = _selected_entities(entities, selected_ids)
    offsets = tuple(_offset_entity(entity, distance) for _index, entity in selected)
    return (*entities, *offsets)


def _straight_segments(
    entities: Iterable[SketchEntity],
) -> tuple[tuple[str, Point2D, Point2D], ...]:
    segments: list[tuple[str, Point2D, Point2D]] = []
    for entity in entities:
        if entity.construction:
            continue
        if isinstance(entity, LineEntity):
            segments.append((entity.entity_id, entity.start_mm, entity.end_mm))
        elif isinstance(entity, PolylineEntity):
            segments.extend(
                (entity.entity_id, start, end)
                for start, end in zip(entity.points_mm, entity.points_mm[1:], strict=False)
            )
            if entity.closed:
                segments.append((entity.entity_id, entity.points_mm[-1], entity.points_mm[0]))
        elif isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            segments.extend(
                (entity.entity_id, start, end)
                for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
            )
    return tuple(segments)


def _projection(point: Point2D, start: Point2D, end: Point2D) -> tuple[float, float]:
    delta = (end[0] - start[0], end[1] - start[1])
    length_squared = delta[0] ** 2 + delta[1] ** 2
    ratio = min(
        1.0,
        max(
            0.0,
            ((point[0] - start[0]) * delta[0] + (point[1] - start[1]) * delta[1]) / length_squared,
        ),
    )
    projected = (start[0] + ratio * delta[0], start[1] + ratio * delta[1])
    return ratio, math.hypot(point[0] - projected[0], point[1] - projected[1])


def _intersection_parameters(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
) -> tuple[float, float] | None:
    first_delta = (first_end[0] - first_start[0], first_end[1] - first_start[1])
    second_delta = (second_end[0] - second_start[0], second_end[1] - second_start[1])
    denominator = _cross(first_delta, second_delta)
    if abs(denominator) <= _EPSILON:
        return None
    offset = (second_start[0] - first_start[0], second_start[1] - first_start[1])
    first_ratio = _cross(offset, second_delta) / denominator
    second_ratio = _cross(offset, first_delta) / denominator
    if not (-_EPSILON <= first_ratio <= 1.0 + _EPSILON):
        return None
    if not (-_EPSILON <= second_ratio <= 1.0 + _EPSILON):
        return None
    return (min(1.0, max(0.0, first_ratio)), min(1.0, max(0.0, second_ratio)))


def _line_segment_parameters(
    line_start: Point2D,
    line_end: Point2D,
    segment_start: Point2D,
    segment_end: Point2D,
) -> tuple[float, float] | None:
    line_delta = (line_end[0] - line_start[0], line_end[1] - line_start[1])
    segment_delta = (segment_end[0] - segment_start[0], segment_end[1] - segment_start[1])
    denominator = _cross(line_delta, segment_delta)
    if abs(denominator) <= _EPSILON:
        return None
    offset = (segment_start[0] - line_start[0], segment_start[1] - line_start[1])
    line_ratio = _cross(offset, segment_delta) / denominator
    segment_ratio = _cross(offset, line_delta) / denominator
    if not -_EPSILON <= segment_ratio <= 1.0 + _EPSILON:
        return None
    return (line_ratio, min(1.0, max(0.0, segment_ratio)))


def extend_line_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
) -> tuple[SketchEntity, ...]:
    """Extend a standalone line endpoint to the nearest straight-segment hit."""
    if any(isinstance(value, bool) or not math.isfinite(value) for value in click_mm):
        raise ValueError("extend click must contain finite coordinates")
    point = (float(click_mm[0]), float(click_mm[1]))
    if isinstance(hit_tolerance_mm, bool) or not math.isfinite(hit_tolerance_mm):
        raise ValueError("extend hit tolerance must be finite")
    tolerance = float(hit_tolerance_mm)
    if tolerance <= 0.0:
        raise ValueError("extend hit tolerance must be positive")

    endpoint_candidates: list[tuple[int, LineEntity, bool, float]] = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, LineEntity) or (
            target_entity_id is not None and entity.entity_id != target_entity_id
        ):
            continue
        endpoint_candidates.extend(
            (index, entity, at_start, math.hypot(point[0] - endpoint[0], point[1] - endpoint[1]))
            for at_start, endpoint in (
                (True, entity.start_mm),
                (False, entity.end_mm),
            )
            if math.hypot(point[0] - endpoint[0], point[1] - endpoint[1]) <= tolerance
        )
    if not endpoint_candidates:
        raise ValueError("请点选待延伸直线的一个端点。")
    endpoint_candidates.sort(key=lambda item: item[3])
    if (
        len(endpoint_candidates) > 1
        and abs(endpoint_candidates[0][3] - endpoint_candidates[1][3]) <= _EPSILON
    ):
        raise ValueError("延伸目标端点不明确；请缩放视图或分开重叠端点。")
    target_index, target, at_start, _distance = endpoint_candidates[0]

    possible_hits = [
        (ratio, hit)
        for ratio, hit in _line_cutter_intersections(
            target.start_mm, target.end_mm, entities, exclude_entity_id=target.entity_id
        )
        if (at_start and ratio < -_EPSILON) or (not at_start and ratio > 1.0 + _EPSILON)
    ]
    if not possible_hits:
        raise ValueError("所选端点的延伸方向上没有有效交点。")

    _line_ratio, hit = max(possible_hits) if at_start else min(possible_hits)
    extended = _preserve_entity_metadata(
        target,
        LineEntity(
            target.entity_id,
            hit if at_start else target.start_mm,
            target.end_mm if at_start else hit,
            construction=target.construction,
        ),
    )
    return (*entities[:target_index], extended, *entities[target_index + 1 :])


def split_line_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
) -> tuple[SketchEntity, ...]:
    """Split a standalone line at the intersection nearest the click."""
    if any(isinstance(value, bool) or not math.isfinite(value) for value in click_mm):
        raise ValueError("split click must contain finite coordinates")
    point = (float(click_mm[0]), float(click_mm[1]))
    if isinstance(hit_tolerance_mm, bool) or not math.isfinite(hit_tolerance_mm):
        raise ValueError("split hit tolerance must be finite")
    tolerance = float(hit_tolerance_mm)
    if tolerance <= 0.0:
        raise ValueError("split hit tolerance must be positive")

    line_candidates: list[tuple[int, LineEntity, float, float]] = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, LineEntity) or (
            target_entity_id is not None and entity.entity_id != target_entity_id
        ):
            continue
        ratio, distance = _projection(point, entity.start_mm, entity.end_mm)
        if distance <= tolerance:
            line_candidates.append((index, entity, ratio, distance))
    if not line_candidates:
        raise ValueError("请点选一条可分割的直线。")
    line_candidates.sort(key=lambda item: item[3])
    if len(line_candidates) > 1 and abs(line_candidates[0][3] - line_candidates[1][3]) <= _EPSILON:
        raise ValueError("分割目标直线不明确；请分开重叠线段后再操作。")

    target_index, target, click_ratio, _distance = line_candidates[0]
    intersections: list[float] = []
    for entity_id, start, end in _straight_segments(entities):
        if entity_id == target.entity_id:
            continue
        parameters = _intersection_parameters(target.start_mm, target.end_mm, start, end)
        if parameters is None:
            continue
        first_ratio, second_ratio = parameters
        if _EPSILON < first_ratio < 1.0 - _EPSILON and -_EPSILON <= second_ratio <= 1.0 + _EPSILON:
            intersections.append(first_ratio)
    if not intersections:
        raise ValueError("没有与其他直线段的内部交点，无法分割。")

    intersections.sort()
    unique_intersections: list[float] = []
    for ratio in intersections:
        if not unique_intersections or ratio - unique_intersections[-1] > _EPSILON:
            unique_intersections.append(ratio)
    unique_intersections.sort(key=lambda ratio: abs(ratio - click_ratio))
    if (
        len(unique_intersections) > 1
        and abs(
            abs(unique_intersections[0] - click_ratio) - abs(unique_intersections[1] - click_ratio)
        )
        <= _EPSILON
    ):
        raise ValueError("分割交点选择不明确；请靠近其中一个交点后再操作。")
    ratio = unique_intersections[0]
    split_point = (
        target.start_mm[0] + ratio * (target.end_mm[0] - target.start_mm[0]),
        target.start_mm[1] + ratio * (target.end_mm[1] - target.start_mm[1]),
    )
    fragments = (
        _preserve_entity_metadata(
            target,
            LineEntity(
                target.entity_id,
                target.start_mm,
                split_point,
                construction=target.construction,
            ),
        ),
        _preserve_entity_metadata(
            target,
            LineEntity(
                uuid4().hex,
                split_point,
                target.end_mm,
                construction=target.construction,
            ),
        ),
    )
    return (*entities[:target_index], *fragments, *entities[target_index + 1 :])


def split_entity_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
) -> tuple[SketchEntity, ...]:
    """Split a line segment or bounded path segment at nearby intersections."""
    point = _finite_point(click_mm, "split click")
    tolerance = _finite_angle(hit_tolerance_mm, "split hit tolerance")
    if tolerance <= 0.0:
        raise ValueError("split hit tolerance must be positive")

    candidates: list[tuple[int, SketchEntity, int | None, Point2D, Point2D, float, float]] = []
    for entity_index, entity in enumerate(entities):
        if target_entity_id is not None and entity.entity_id != target_entity_id:
            continue
        if isinstance(entity, LineEntity):
            segments = ((None, entity.start_mm, entity.end_mm),)
        elif isinstance(entity, PolylineEntity):
            points = entity.points_mm
            pairs = tuple(zip(points, points[1:], strict=False))
            if entity.closed:
                pairs = (*pairs, (points[-1], points[0]))
            segments = tuple(
                (segment_index, start, end) for segment_index, (start, end) in enumerate(pairs)
            )
        elif isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            segments = tuple(
                (segment_index, start, end)
                for segment_index, (start, end) in enumerate(
                    zip(corners, (*corners[1:], corners[0]), strict=True)
                )
            )
        else:
            continue
        for segment_index, start, end in segments:
            ratio, distance = _projection(point, start, end)
            if distance <= tolerance:
                candidates.append(
                    (entity_index, entity, segment_index, start, end, ratio, distance)
                )

    if not candidates:
        raise ValueError("请点选一条可分割直线、矩形边或多段线段。")
    candidates.sort(key=lambda item: item[6])
    if len(candidates) > 1 and abs(candidates[0][6] - candidates[1][6]) <= _EPSILON:
        raise ValueError("分割目标不明确；请分开重叠线段后再操作。")

    target_index, target, segment_index, start, end, click_ratio, _distance = candidates[0]
    if isinstance(target, LineEntity):
        return split_line_at(
            entities,
            point,
            hit_tolerance_mm=tolerance,
            target_entity_id=target.entity_id,
        )
    if segment_index is None:
        raise ValueError("分割目标类型不受支持。")
    if isinstance(target, RectangleEntity):
        x1, y1 = target.first_corner_mm
        x2, y2 = target.opposite_corner_mm
        target = _preserve_entity_metadata(
            target,
            PolylineEntity(
                target.entity_id,
                ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                closed=True,
                construction=target.construction,
            ),
        )
        return _split_closed_polyline_segment(
            entities, target_index, target, segment_index, click_ratio
        )
    if not isinstance(target, PolylineEntity):
        raise ValueError("分割目标类型不受支持。")
    if target.closed:
        return _split_closed_polyline_segment(
            entities, target_index, target, segment_index, click_ratio
        )

    intersections: list[float] = []
    for entity_id, cutter_start, cutter_end in _straight_segments(entities):
        if entity_id == target.entity_id:
            continue
        parameters = _intersection_parameters(start, end, cutter_start, cutter_end)
        if parameters is None:
            continue
        target_ratio, cutter_ratio = parameters
        if _EPSILON < target_ratio < 1.0 - _EPSILON and -_EPSILON <= cutter_ratio <= 1.0 + _EPSILON:
            intersections.append(target_ratio)
    unique_intersections: list[float] = []
    for ratio in sorted(intersections):
        if not unique_intersections or ratio - unique_intersections[-1] > _EPSILON:
            unique_intersections.append(ratio)
    if not unique_intersections:
        raise ValueError("没有与其他有限直线段的内部交点，无法分割多段线段。")
    unique_intersections.sort(key=lambda ratio: abs(ratio - click_ratio))
    if (
        len(unique_intersections) > 1
        and abs(
            abs(unique_intersections[0] - click_ratio) - abs(unique_intersections[1] - click_ratio)
        )
        <= _EPSILON
    ):
        raise ValueError("分割交点选择不明确；请靠近其中一个交点后再操作。")

    ratio = unique_intersections[0]
    split_point = (
        start[0] + ratio * (end[0] - start[0]),
        start[1] + ratio * (end[1] - start[1]),
    )
    points = target.points_mm
    prefix = _preserve_entity_metadata(
        target,
        PolylineEntity(
            target.entity_id,
            (*points[: segment_index + 1], split_point),
            construction=target.construction,
        ),
    )
    suffix = _preserve_entity_metadata(
        target,
        PolylineEntity(
            uuid4().hex,
            (split_point, *points[segment_index + 1 :]),
            construction=target.construction,
        ),
    )
    return (*entities[:target_index], prefix, suffix, *entities[target_index + 1 :])


def _line_circle_intersections(
    start: Point2D, end: Point2D, center: Point2D, radius: float
) -> tuple[Point2D, ...]:
    return tuple(
        point
        for ratio, point in _line_circle_parameters(start, end, center, radius)
        if -_EPSILON <= ratio <= 1.0 + _EPSILON
    )


def _line_circle_parameters(
    start: Point2D, end: Point2D, center: Point2D, radius: float
) -> tuple[tuple[float, Point2D], ...]:
    """Return infinite-line/circle intersections with parameters on start→end."""
    delta = (end[0] - start[0], end[1] - start[1])
    relative = (start[0] - center[0], start[1] - center[1])
    quadratic_a = delta[0] ** 2 + delta[1] ** 2
    if quadratic_a <= _EPSILON**2:
        return ()
    quadratic_b = 2.0 * (relative[0] * delta[0] + relative[1] * delta[1])
    quadratic_c = relative[0] ** 2 + relative[1] ** 2 - radius**2
    discriminant = quadratic_b**2 - 4.0 * quadratic_a * quadratic_c
    if discriminant < -_EPSILON:
        return ()
    root = math.sqrt(max(0.0, discriminant))
    ratios = (
        (-quadratic_b / (2.0 * quadratic_a),)
        if root <= _EPSILON
        else (
            (-quadratic_b - root) / (2.0 * quadratic_a),
            (-quadratic_b + root) / (2.0 * quadratic_a),
        )
    )
    return tuple(
        (
            ratio,
            (
                start[0] + ratio * delta[0],
                start[1] + ratio * delta[1],
            ),
        )
        for ratio in ratios
    )


def _line_cutter_intersections(
    start: Point2D,
    end: Point2D,
    entities: tuple[SketchEntity, ...],
    *,
    exclude_entity_id: str,
) -> tuple[tuple[float, Point2D], ...]:
    """Find line parameters at valid finite straight and circular cutter hits."""
    hits: list[tuple[float, Point2D]] = []
    for entity_id, segment_start, segment_end in _straight_segments(entities):
        if entity_id == exclude_entity_id:
            continue
        parameters = _line_segment_parameters(start, end, segment_start, segment_end)
        if parameters is None:
            continue
        line_ratio, _segment_ratio = parameters
        hits.append(
            (
                line_ratio,
                (
                    start[0] + line_ratio * (end[0] - start[0]),
                    start[1] + line_ratio * (end[1] - start[1]),
                ),
            )
        )

    for cutter in entities:
        if (
            cutter.entity_id == exclude_entity_id
            or cutter.construction
            or not isinstance(cutter, CircleEntity | ArcEntity)
        ):
            continue
        for ratio, hit in _line_circle_parameters(start, end, cutter.center_mm, cutter.radius_mm):
            if isinstance(cutter, ArcEntity):
                angle = math.degrees(
                    math.atan2(hit[1] - cutter.center_mm[1], hit[0] - cutter.center_mm[0])
                )
                if not _angle_in_curve(angle, cutter.start_angle_deg, cutter.sweep_angle_deg):
                    continue
            hits.append((ratio, hit))

    return tuple(hits)


def _circle_circle_intersections(
    first_center: Point2D,
    first_radius: float,
    second_center: Point2D,
    second_radius: float,
) -> tuple[Point2D, ...]:
    dx = second_center[0] - first_center[0]
    dy = second_center[1] - first_center[1]
    center_distance = math.hypot(dx, dy)
    if center_distance <= _EPSILON:
        return ()
    if (
        center_distance > first_radius + second_radius + _EPSILON
        or center_distance < abs(first_radius - second_radius) - _EPSILON
    ):
        return ()
    along = (first_radius**2 - second_radius**2 + center_distance**2) / (2.0 * center_distance)
    height_squared = first_radius**2 - along**2
    if height_squared < -_EPSILON:
        return ()
    height = math.sqrt(max(0.0, height_squared))
    base = (
        first_center[0] + along * dx / center_distance,
        first_center[1] + along * dy / center_distance,
    )
    if height <= _EPSILON:
        return (base,)
    perpendicular = (-dy / center_distance * height, dx / center_distance * height)
    return (
        (base[0] + perpendicular[0], base[1] + perpendicular[1]),
        (base[0] - perpendicular[0], base[1] - perpendicular[1]),
    )


def _angle_in_curve(angle_deg: float, start_deg: float, sweep_deg: float) -> bool:
    if abs(sweep_deg) >= 360.0 - _EPSILON:
        return True
    distance = (
        (angle_deg - start_deg) % 360.0 if sweep_deg > 0.0 else (start_deg - angle_deg) % 360.0
    )
    return distance <= abs(sweep_deg) + _EPSILON


def _curve_parameter(angle_deg: float, start_deg: float, sweep_deg: float) -> float:
    distance = (
        (angle_deg - start_deg) % 360.0 if sweep_deg > 0.0 else (start_deg - angle_deg) % 360.0
    )
    return distance / abs(sweep_deg)


def _circular_intersection_points(
    target: CircleEntity | ArcEntity, entities: tuple[SketchEntity, ...]
) -> tuple[Point2D, ...]:
    points = [
        point
        for entity_id, start, end in _straight_segments(entities)
        if entity_id != target.entity_id
        for point in _line_circle_intersections(start, end, target.center_mm, target.radius_mm)
    ]
    for entity in entities:
        if entity.entity_id == target.entity_id or entity.construction:
            continue
        if isinstance(entity, CircleEntity):
            center, radius, start_angle, sweep_angle = (
                entity.center_mm,
                entity.radius_mm,
                0.0,
                360.0,
            )
        elif isinstance(entity, ArcEntity):
            center, radius, start_angle, sweep_angle = (
                entity.center_mm,
                entity.radius_mm,
                entity.start_angle_deg,
                entity.sweep_angle_deg,
            )
        else:
            continue
        for point in _circle_circle_intersections(
            target.center_mm, target.radius_mm, center, radius
        ):
            angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
            if _angle_in_curve(angle, start_angle, sweep_angle):
                points.append(point)
    return tuple(points)


def extend_curve_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
) -> tuple[SketchEntity, ...]:
    """Extend a unique line, arc, or open-polyline endpoint to an intersection."""
    if any(isinstance(value, bool) or not math.isfinite(value) for value in click_mm):
        raise ValueError("extend click must contain finite coordinates")
    point = (float(click_mm[0]), float(click_mm[1]))
    if isinstance(hit_tolerance_mm, bool) or not math.isfinite(hit_tolerance_mm):
        raise ValueError("extend hit tolerance must be finite")
    tolerance = float(hit_tolerance_mm)
    if tolerance <= 0.0:
        raise ValueError("extend hit tolerance must be positive")

    endpoint_candidates: list[tuple[int, LineEntity | ArcEntity | PolylineEntity, bool, float]] = []
    for index, entity in enumerate(entities):
        if target_entity_id is not None and entity.entity_id != target_entity_id:
            continue
        if isinstance(entity, LineEntity):
            endpoints = (entity.start_mm, entity.end_mm)
        elif isinstance(entity, ArcEntity):
            endpoints = tuple(
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(math.radians(angle)),
                    entity.center_mm[1] + entity.radius_mm * math.sin(math.radians(angle)),
                )
                for angle in (
                    entity.start_angle_deg,
                    entity.start_angle_deg + entity.sweep_angle_deg,
                )
            )
        elif isinstance(entity, PolylineEntity) and not entity.closed:
            endpoints = (entity.points_mm[0], entity.points_mm[-1])
        else:
            continue
        endpoint_candidates.extend(
            (
                index,
                entity,
                at_start,
                math.hypot(point[0] - endpoint[0], point[1] - endpoint[1]),
            )
            for at_start, endpoint in ((True, endpoints[0]), (False, endpoints[1]))
            if math.hypot(point[0] - endpoint[0], point[1] - endpoint[1]) <= tolerance
        )
    if not endpoint_candidates:
        raise ValueError("请点选待延伸直线、圆弧或开放多段线端点。")
    endpoint_candidates.sort(key=lambda item: item[3])
    if (
        len(endpoint_candidates) > 1
        and abs(endpoint_candidates[0][3] - endpoint_candidates[1][3]) <= _EPSILON
    ):
        raise ValueError("延伸目标端点不明确；请缩放视图或分开重叠端点。")
    target_index, target, at_start, _distance = endpoint_candidates[0]
    if isinstance(target, LineEntity):
        return extend_line_at(
            entities,
            point,
            hit_tolerance_mm=tolerance,
            target_entity_id=target.entity_id,
        )
    if isinstance(target, PolylineEntity):
        return _extend_open_polyline_endpoint(entities, target_index, target, at_start=at_start)

    endpoint_angle = (
        target.start_angle_deg if at_start else target.start_angle_deg + target.sweep_angle_deg
    )
    direction = math.copysign(1.0, target.sweep_angle_deg)
    possible_hits: list[tuple[float, float]] = []
    would_complete_circle = False
    start_angle = target.start_angle_deg
    end_angle = start_angle + target.sweep_angle_deg
    for intersection in _circular_intersection_points(target, entities):
        angle = math.degrees(
            math.atan2(
                intersection[1] - target.center_mm[1],
                intersection[0] - target.center_mm[0],
            )
        )
        is_opposite_endpoint = (
            abs((angle - end_angle + 180.0) % 360.0 - 180.0) <= _EPSILON
            if at_start
            else abs((angle - start_angle + 180.0) % 360.0 - 180.0) <= _EPSILON
        )
        if (
            _angle_in_curve(angle, target.start_angle_deg, target.sweep_angle_deg)
            and not is_opposite_endpoint
        ):
            continue
        if at_start:
            distance = (
                (endpoint_angle - angle) % 360.0
                if direction > 0.0
                else (angle - endpoint_angle) % 360.0
            )
        else:
            distance = (
                (angle - endpoint_angle) % 360.0
                if direction > 0.0
                else (endpoint_angle - angle) % 360.0
            )
        if distance <= _EPSILON:
            continue
        if abs(target.sweep_angle_deg) + distance >= 360.0 - _EPSILON:
            would_complete_circle = True
            continue
        possible_hits.append((distance, angle))
    possible_hits.sort()
    unique_hits: list[tuple[float, float]] = []
    for distance, angle in possible_hits:
        if not unique_hits or abs((angle - unique_hits[-1][1] + 180.0) % 360.0 - 180.0) > _EPSILON:
            unique_hits.append((distance, angle))
    if not unique_hits:
        if would_complete_circle:
            raise ValueError("延伸会使圆弧达到整圆；请调整交点或保留原圆弧。")
        raise ValueError("所选圆弧端点的延伸方向上没有交点。")
    if len(unique_hits) > 1 and abs(unique_hits[0][0] - unique_hits[1][0]) <= _EPSILON:
        raise ValueError("圆弧延伸交点不明确；请调整切割对象或端点选择。")

    extension_degrees = unique_hits[0][0]
    extended = _preserve_entity_metadata(
        target,
        ArcEntity(
            target.entity_id,
            target.center_mm,
            target.radius_mm,
            (target.start_angle_deg - direction * extension_degrees) % 360.0
            if at_start
            else target.start_angle_deg,
            target.sweep_angle_deg + direction * extension_degrees,
            target.construction,
        ),
    )
    return (*entities[:target_index], extended, *entities[target_index + 1 :])


def _extend_open_polyline_endpoint(
    entities: tuple[SketchEntity, ...],
    target_index: int,
    target: PolylineEntity,
    *,
    at_start: bool,
) -> tuple[SketchEntity, ...]:
    """Extend one open path terminal segment while preserving its connected path."""
    if at_start:
        line_start, line_end = target.points_mm[0], target.points_mm[1]
    else:
        line_start, line_end = target.points_mm[-2], target.points_mm[-1]

    possible_hits = [
        (ratio, hit)
        for ratio, hit in _line_cutter_intersections(
            line_start, line_end, entities, exclude_entity_id=target.entity_id
        )
        if (at_start and ratio < -_EPSILON) or (not at_start and ratio > 1.0 + _EPSILON)
    ]
    if not possible_hits:
        raise ValueError("所选开放多段线端点的延伸方向上没有有效交点。")

    _ratio, hit = max(possible_hits) if at_start else min(possible_hits)
    points = (hit, *target.points_mm[1:]) if at_start else (*target.points_mm[:-1], hit)
    extended = _preserve_entity_metadata(
        target,
        PolylineEntity(
            target.entity_id,
            points,
            closed=False,
            construction=target.construction,
        ),
    )
    return (*entities[:target_index], extended, *entities[target_index + 1 :])


def _unique_curve_parameters(
    target: CircleEntity | ArcEntity, intersections: tuple[Point2D, ...]
) -> tuple[float, ...]:
    angles = tuple(
        math.degrees(math.atan2(point[1] - target.center_mm[1], point[0] - target.center_mm[0]))
        for point in intersections
    )
    if isinstance(target, ArcEntity):
        values = sorted(
            _curve_parameter(angle, target.start_angle_deg, target.sweep_angle_deg)
            for angle in angles
            if _angle_in_curve(angle, target.start_angle_deg, target.sweep_angle_deg)
            and _EPSILON
            < _curve_parameter(angle, target.start_angle_deg, target.sweep_angle_deg)
            < 1.0 - _EPSILON
        )
    else:
        values = sorted((angle % 360.0) / 360.0 for angle in angles)
    unique: list[float] = []
    for value in values:
        if not unique or value - unique[-1] > _EPSILON:
            unique.append(value)
    if (
        isinstance(target, CircleEntity)
        and len(unique) > 1
        and unique[0] + 1.0 - unique[-1] <= _EPSILON
    ):
        unique.pop()
    return tuple(unique)


def _circle_trim_interval(
    parameters: tuple[float, ...], click_parameter: float
) -> tuple[float, float]:
    for start, end in zip(parameters, parameters[1:], strict=False):
        if start + _EPSILON < click_parameter < end - _EPSILON:
            return (start, end)
    start, end = parameters[-1], parameters[0] + 1.0
    adjusted_click = click_parameter if click_parameter > start else click_parameter + 1.0
    if start + _EPSILON < adjusted_click < end - _EPSILON:
        return (start, end)
    raise ValueError("请点选两个交点之间的圆弧区段，不要点击交点。")


def _trim_circular_entity(
    entities: tuple[SketchEntity, ...],
    target_index: int,
    target: CircleEntity | ArcEntity,
    click_mm: Point2D,
) -> tuple[SketchEntity, ...]:
    intersections = _circular_intersection_points(target, entities)
    parameters = _unique_curve_parameters(target, intersections)
    if isinstance(target, CircleEntity) and len(parameters) < 2:
        raise ValueError("完整圆至少需要两个唯一曲线交点，无法修剪。")
    if isinstance(target, ArcEntity) and not parameters:
        raise ValueError("圆弧至少需要一个内部曲线交点，无法修剪。")
    click_angle = math.degrees(
        math.atan2(click_mm[1] - target.center_mm[1], click_mm[0] - target.center_mm[0])
    )
    click_parameter = (
        (click_angle % 360.0) / 360.0
        if isinstance(target, CircleEntity)
        else _curve_parameter(click_angle, target.start_angle_deg, target.sweep_angle_deg)
    )
    if isinstance(target, CircleEntity):
        cut_start, cut_end = _circle_trim_interval(parameters, click_parameter)
        remaining_sweep = 360.0 - (cut_end - cut_start) * 360.0
        if remaining_sweep <= _EPSILON:
            raise ValueError("修剪会删除整个圆；请靠近要保留的弧段操作。")
        replacement: SketchEntity = _preserve_entity_metadata(
            target,
            ArcEntity(
                target.entity_id,
                target.center_mm,
                target.radius_mm,
                (cut_end * 360.0) % 360.0,
                remaining_sweep,
                target.construction,
            ),
        )
        return (*entities[:target_index], replacement, *entities[target_index + 1 :])

    breakpoints = sorted({0.0, 1.0, *parameters})
    if click_parameter <= _EPSILON or click_parameter >= 1.0 - _EPSILON:
        raise ValueError("请点选圆弧内部区段，不要点击端点。")
    interval = next(
        (
            (start, end)
            for start, end in zip(breakpoints, breakpoints[1:], strict=False)
            if start + _EPSILON < click_parameter < end - _EPSILON
        ),
        None,
    )
    if interval is None:
        raise ValueError("请点选两个交点之间的圆弧区段，不要点击交点。")
    cut_start, cut_end = interval
    replacements: list[ArcEntity] = []
    if cut_start > _EPSILON:
        replacements.append(
            _preserve_entity_metadata(
                target,
                ArcEntity(
                    target.entity_id,
                    target.center_mm,
                    target.radius_mm,
                    target.start_angle_deg,
                    target.sweep_angle_deg * cut_start,
                    target.construction,
                ),
            )
        )
    if cut_end < 1.0 - _EPSILON:
        replacements.append(
            _preserve_entity_metadata(
                target,
                ArcEntity(
                    target.entity_id if not replacements else uuid4().hex,
                    target.center_mm,
                    target.radius_mm,
                    target.start_angle_deg + target.sweep_angle_deg * cut_end,
                    target.sweep_angle_deg * (1.0 - cut_end),
                    target.construction,
                ),
            )
        )
    if not replacements:
        raise ValueError("修剪会删除整个圆弧。")
    return (*entities[:target_index], *replacements, *entities[target_index + 1 :])


def _closed_path_intersections(
    entities: tuple[SketchEntity, ...],
    target: PolylineEntity,
    segments: tuple[tuple[Point2D, Point2D], ...],
    lengths: tuple[float, ...],
    cumulative: Sequence[float],
    tolerance: float,
) -> tuple[float, ...]:
    intersection_distances: list[float] = []
    straight_cutters = tuple(
        segment for segment in _straight_segments(entities) if segment[0] != target.entity_id
    )
    curve_cutters = tuple(
        entity
        for entity in entities
        if entity.entity_id != target.entity_id
        and not entity.construction
        and isinstance(entity, CircleEntity | ArcEntity)
    )
    for current_index, (segment_start, segment_end) in enumerate(segments):
        segment_length = lengths[current_index]
        for _entity_id, cutter_start, cutter_end in straight_cutters:
            parameters = _intersection_parameters(
                segment_start, segment_end, cutter_start, cutter_end
            )
            if parameters is None:
                continue
            target_ratio, cutter_ratio = parameters
            if -_EPSILON <= target_ratio <= 1.0 + _EPSILON and (
                -_EPSILON <= cutter_ratio <= 1.0 + _EPSILON
            ):
                distance = (
                    cumulative[current_index] + min(1.0, max(0.0, target_ratio)) * segment_length
                )
                intersection_distances.append(
                    0.0 if cumulative[-1] - distance <= tolerance else distance
                )

        for cutter in curve_cutters:
            for point in _line_circle_intersections(
                segment_start, segment_end, cutter.center_mm, cutter.radius_mm
            ):
                angle = math.degrees(
                    math.atan2(point[1] - cutter.center_mm[1], point[0] - cutter.center_mm[0])
                )
                if isinstance(cutter, ArcEntity) and not _angle_in_curve(
                    angle, cutter.start_angle_deg, cutter.sweep_angle_deg
                ):
                    continue
                ratio, distance_to_segment = _projection(point, segment_start, segment_end)
                if -_EPSILON <= ratio <= 1.0 + _EPSILON and distance_to_segment <= tolerance:
                    distance = (
                        cumulative[current_index] + min(1.0, max(0.0, ratio)) * segment_length
                    )
                    intersection_distances.append(
                        0.0 if cumulative[-1] - distance <= tolerance else distance
                    )

    unique_intersections: list[float] = []
    for distance in sorted(intersection_distances):
        if not unique_intersections or distance - unique_intersections[-1] > tolerance:
            unique_intersections.append(distance)
    return tuple(unique_intersections)


def _closed_path_click_interval(
    intersections: Sequence[float],
    click_distance: float,
    total_length: float,
    tolerance: float,
) -> tuple[float, float]:
    normalized_click = click_distance % total_length
    for index, first in enumerate(intersections):
        is_wrap_interval = index == len(intersections) - 1
        second = intersections[0] + total_length if is_wrap_interval else intersections[index + 1]
        candidate_click = normalized_click
        if is_wrap_interval and candidate_click < first:
            candidate_click += total_length
        if first + tolerance < candidate_click < second - tolerance:
            return (first, second)
    raise ValueError("请点选闭合路径两个唯一交点之间的区段，不要点交点。")


def _closed_path_points(
    points: tuple[Point2D, ...],
    segments: tuple[tuple[Point2D, Point2D], ...],
    lengths: tuple[float, ...],
    cumulative: Sequence[float],
    total_length: float,
    start_distance: float,
    end_distance: float,
    tolerance: float,
) -> tuple[Point2D, ...]:
    def point_at(distance: float) -> Point2D:
        position = distance % total_length
        for index, (first, second) in enumerate(segments):
            if position <= cumulative[index + 1] + tolerance:
                ratio = min(
                    1.0,
                    max(0.0, (position - cumulative[index]) / lengths[index]),
                )
                return (
                    first[0] + ratio * (second[0] - first[0]),
                    first[1] + ratio * (second[1] - first[1]),
                )
        return points[0]

    result = [point_at(start_distance)]
    interior_vertices: list[tuple[float, Point2D]] = []
    for index, vertex in enumerate(points):
        vertex_distance = cumulative[index]
        while vertex_distance <= start_distance + tolerance:
            vertex_distance += total_length
        if vertex_distance < end_distance - tolerance:
            interior_vertices.append((vertex_distance, vertex))
    result.extend(vertex for _, vertex in sorted(interior_vertices))
    result.append(point_at(end_distance))
    if (
        len(result) < 2
        or math.hypot(result[-1][0] - result[0][0], result[-1][1] - result[0][1]) <= tolerance
    ):
        raise ValueError("闭合路径结果退化；草图未修改。")
    return tuple(result)


def _trim_closed_polyline_segment(
    entities: tuple[SketchEntity, ...],
    target_index: int,
    target: PolylineEntity,
    segment_index: int,
    click_ratio: float,
) -> tuple[SketchEntity, ...]:
    """Remove the closed-path interval under the click and retain one open path."""
    points = target.points_mm
    segments = tuple(zip(points, (*points[1:], points[0]), strict=True))
    lengths = tuple(
        math.hypot(second[0] - first[0], second[1] - first[1]) for first, second in segments
    )
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    total_length = cumulative[-1]
    tolerance = _EPSILON * max(1.0, total_length)
    if total_length <= tolerance or any(length <= tolerance for length in lengths):
        raise ValueError("闭合多段线含无效或过短边；草图未修改。")

    unique_intersections = _closed_path_intersections(
        entities, target, segments, lengths, cumulative, tolerance
    )
    if len(unique_intersections) < 2:
        raise ValueError("闭合多段线至少需要两个唯一交点才能修剪；草图未修改。")

    click_distance = cumulative[segment_index] + click_ratio * lengths[segment_index]
    cut_start, cut_end = _closed_path_click_interval(
        unique_intersections, click_distance, total_length, tolerance
    )
    retained_length = total_length - (cut_end - cut_start)
    if retained_length <= tolerance:
        raise ValueError("修剪会使闭合多段线退化；草图未修改。")

    retained_start, retained_end = cut_end, cut_start + total_length
    retained_points = _closed_path_points(
        points,
        segments,
        lengths,
        cumulative,
        total_length,
        retained_start,
        retained_end,
        tolerance,
    )

    replacement = _preserve_entity_metadata(
        target,
        PolylineEntity(
            target.entity_id,
            retained_points,
            closed=False,
            construction=target.construction,
        ),
    )
    return (*entities[:target_index], replacement, *entities[target_index + 1 :])


def _split_closed_polyline_segment(
    entities: tuple[SketchEntity, ...],
    target_index: int,
    target: PolylineEntity,
    segment_index: int,
    click_ratio: float,
) -> tuple[SketchEntity, ...]:
    """Split a closed path at the adjacent intersections surrounding a click."""
    points = target.points_mm
    segments = tuple(zip(points, (*points[1:], points[0]), strict=True))
    lengths = tuple(
        math.hypot(second[0] - first[0], second[1] - first[1]) for first, second in segments
    )
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    total_length = cumulative[-1]
    tolerance = _EPSILON * max(1.0, total_length)
    if total_length <= tolerance or any(length <= tolerance for length in lengths):
        raise ValueError("闭合多段线含无效或过短边；草图未修改。")
    intersections = _closed_path_intersections(
        entities, target, segments, lengths, cumulative, tolerance
    )
    if len(intersections) < 2:
        raise ValueError("闭合多段线至少需要两个唯一交点才能分割；草图未修改。")

    click_distance = cumulative[segment_index] + click_ratio * lengths[segment_index]
    split_start, split_end = _closed_path_click_interval(
        intersections, click_distance, total_length, tolerance
    )
    first_points = _closed_path_points(
        points,
        segments,
        lengths,
        cumulative,
        total_length,
        split_start,
        split_end,
        tolerance,
    )
    second_points = _closed_path_points(
        points,
        segments,
        lengths,
        cumulative,
        total_length,
        split_end,
        split_start + total_length,
        tolerance,
    )
    fragments = (
        _preserve_entity_metadata(
            target,
            PolylineEntity(
                target.entity_id,
                first_points,
                construction=target.construction,
            ),
        ),
        _preserve_entity_metadata(
            target,
            PolylineEntity(
                uuid4().hex,
                second_points,
                construction=target.construction,
            ),
        ),
    )
    return (*entities[:target_index], *fragments, *entities[target_index + 1 :])


def _trim_open_polyline_segment(
    entities: tuple[SketchEntity, ...],
    target_index: int,
    target: PolylineEntity,
    segment_index: int,
    start: Point2D,
    end: Point2D,
    click_ratio: float,
) -> tuple[SketchEntity, ...]:
    intersections: list[float] = []
    for entity_id, cutter_start, cutter_end in _straight_segments(entities):
        if entity_id == target.entity_id:
            continue
        parameters = _intersection_parameters(start, end, cutter_start, cutter_end)
        if parameters is None:
            continue
        target_ratio, cutter_ratio = parameters
        if _EPSILON < target_ratio < 1.0 - _EPSILON and -_EPSILON <= cutter_ratio <= 1.0 + _EPSILON:
            intersections.append(target_ratio)

    segment_length = math.hypot(end[0] - start[0], end[1] - start[1])
    intersection_tolerance = _EPSILON * max(1.0, segment_length)
    for entity in entities:
        if entity.entity_id == target.entity_id or entity.construction:
            continue
        if isinstance(entity, CircleEntity | ArcEntity):
            for point in _line_circle_intersections(start, end, entity.center_mm, entity.radius_mm):
                angle = math.degrees(
                    math.atan2(point[1] - entity.center_mm[1], point[0] - entity.center_mm[0])
                )
                if isinstance(entity, ArcEntity) and not _angle_in_curve(
                    angle, entity.start_angle_deg, entity.sweep_angle_deg
                ):
                    continue
                ratio, distance = _projection(point, start, end)
                if _EPSILON < ratio < 1.0 - _EPSILON and distance <= intersection_tolerance:
                    intersections.append(ratio)

    unique_intersections: list[float] = []
    for ratio in sorted(intersections):
        if not unique_intersections or ratio - unique_intersections[-1] > _EPSILON:
            unique_intersections.append(ratio)
    if not unique_intersections:
        raise ValueError("开放多段线段没有唯一内部交点，无法修剪。")

    breakpoints = (0.0, *unique_intersections, 1.0)
    interval = next(
        (
            (first, second)
            for first, second in zip(breakpoints, breakpoints[1:], strict=False)
            if first + _EPSILON < click_ratio < second - _EPSILON
        ),
        None,
    )
    if interval is None:
        raise ValueError("请点选交点与路径顶点之间，或两个交点之间的多段线段区段。")

    def point_at(ratio: float) -> Point2D:
        return (
            start[0] + ratio * (end[0] - start[0]),
            start[1] + ratio * (end[1] - start[1]),
        )

    def same_point(first: Point2D, second: Point2D) -> bool:
        tolerance = _EPSILON * max(1.0, segment_length)
        return math.hypot(first[0] - second[0], first[1] - second[1]) <= tolerance

    cut_start, cut_end = point_at(interval[0]), point_at(interval[1])
    prefix_points = (
        *target.points_mm[: segment_index + 1],
        *((cut_start,) if not same_point(cut_start, start) else ()),
    )
    suffix_points = (
        *((cut_end,) if not same_point(cut_end, end) else ()),
        *target.points_mm[segment_index + 1 :],
    )

    fragments: list[PolylineEntity] = []
    has_prefix = len(prefix_points) >= 2
    has_suffix = len(suffix_points) >= 2
    if not has_prefix and not has_suffix:
        raise ValueError("修剪会使开放多段线退化；草图未修改。")
    if has_prefix:
        fragments.append(
            _preserve_entity_metadata(
                target,
                PolylineEntity(
                    target.entity_id,
                    prefix_points,
                    construction=target.construction,
                ),
            )
        )
    if has_suffix:
        fragments.append(
            _preserve_entity_metadata(
                target,
                PolylineEntity(
                    target.entity_id if not has_prefix else uuid4().hex,
                    suffix_points,
                    construction=target.construction,
                ),
            )
        )
    return (
        *entities[:target_index],
        *fragments,
        *entities[target_index + 1 :],
    )


def _circular_hit_distance(point: Point2D, entity: CircleEntity | ArcEntity) -> float:
    dx, dy = point[0] - entity.center_mm[0], point[1] - entity.center_mm[1]
    radius_distance = math.hypot(dx, dy)
    if isinstance(entity, CircleEntity):
        return abs(radius_distance - entity.radius_mm)
    angle = math.degrees(math.atan2(dy, dx))
    if _angle_in_curve(angle, entity.start_angle_deg, entity.sweep_angle_deg):
        return abs(radius_distance - entity.radius_mm)
    endpoints = tuple(
        (
            entity.center_mm[0] + entity.radius_mm * math.cos(math.radians(value)),
            entity.center_mm[1] + entity.radius_mm * math.sin(math.radians(value)),
        )
        for value in (
            entity.start_angle_deg,
            entity.start_angle_deg + entity.sweep_angle_deg,
        )
    )
    return min(math.hypot(point[0] - x, point[1] - y) for x, y in endpoints)


def trim_curve_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
    allow_endpoint_intersections: bool = False,
) -> tuple[SketchEntity, ...]:
    """Trim one unique line, curve, rectangle edge, or polyline path segment."""
    if any(isinstance(value, bool) or not math.isfinite(value) for value in click_mm):
        raise ValueError("trim click must contain finite coordinates")
    point = (float(click_mm[0]), float(click_mm[1]))
    if isinstance(hit_tolerance_mm, bool) or not math.isfinite(hit_tolerance_mm):
        raise ValueError("trim hit tolerance must be finite")
    tolerance = float(hit_tolerance_mm)
    if tolerance <= 0.0:
        raise ValueError("trim hit tolerance must be positive")

    candidates: list[
        tuple[int, SketchEntity, int | None, Point2D | None, Point2D | None, float, float]
    ] = []
    for index, entity in enumerate(entities):
        if target_entity_id is not None and entity.entity_id != target_entity_id:
            continue
        if isinstance(entity, LineEntity):
            ratio, distance = _projection(point, entity.start_mm, entity.end_mm)
            if distance <= tolerance:
                candidates.append(
                    (index, entity, None, entity.start_mm, entity.end_mm, ratio, distance)
                )
        elif isinstance(entity, PolylineEntity):
            points = entity.points_mm
            pairs = tuple(zip(points, points[1:], strict=False))
            if entity.closed:
                pairs = (*pairs, (points[-1], points[0]))
            for segment_index, (start, end) in enumerate(pairs):
                ratio, distance = _projection(point, start, end)
                if distance <= tolerance:
                    candidates.append((index, entity, segment_index, start, end, ratio, distance))
        elif isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            for segment_index, (start, end) in enumerate(
                zip(corners, (*corners[1:], corners[0]), strict=True)
            ):
                ratio, distance = _projection(point, start, end)
                if distance <= tolerance:
                    candidates.append((index, entity, segment_index, start, end, ratio, distance))
        elif isinstance(entity, CircleEntity | ArcEntity):
            distance = _circular_hit_distance(point, entity)
            if distance <= tolerance:
                candidates.append((index, entity, None, None, None, 0.0, distance))
    if not candidates:
        raise ValueError(
            "指定修剪目标已不存在。"
            if target_entity_id is not None
            else "请点选一条直线、圆、圆弧、矩形边或多段线段。"
        )
    candidates.sort(key=lambda item: item[6])
    if len(candidates) > 1 and abs(candidates[0][6] - candidates[1][6]) <= _EPSILON:
        raise ValueError("修剪目标不明确；请缩放视图或分开重叠曲线。")
    target_index, target, segment_index, start, end, click_ratio, _distance = candidates[0]
    if isinstance(target, LineEntity):
        return trim_line_at(
            entities,
            point,
            hit_tolerance_mm=tolerance,
            target_entity_id=target.entity_id,
            allow_endpoint_intersections=allow_endpoint_intersections,
        )
    if isinstance(target, PolylineEntity):
        if segment_index is None or start is None or end is None:
            raise ValueError("多段线修剪目标无效；草图未修改。")
        if target.closed:
            return _trim_closed_polyline_segment(
                entities, target_index, target, segment_index, click_ratio
            )
        return _trim_open_polyline_segment(
            entities, target_index, target, segment_index, start, end, click_ratio
        )
    if isinstance(target, RectangleEntity):
        if segment_index is None:
            raise ValueError("矩形修剪目标无效；草图未修改。")
        x1, y1 = target.first_corner_mm
        x2, y2 = target.opposite_corner_mm
        outline = _preserve_entity_metadata(
            target,
            PolylineEntity(
                target.entity_id,
                ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                closed=True,
                construction=target.construction,
            ),
        )
        return _trim_closed_polyline_segment(
            entities, target_index, outline, segment_index, click_ratio
        )
    if isinstance(target, CircleEntity | ArcEntity):
        return _trim_circular_entity(entities, target_index, target, point)
    raise ValueError("样条曲线暂不支持修剪；草稿未修改。")


def trim_line_at(
    entities: tuple[SketchEntity, ...],
    click_mm: Point2D,
    *,
    hit_tolerance_mm: float,
    target_entity_id: str | None = None,
    allow_endpoint_intersections: bool = False,
) -> tuple[SketchEntity, ...]:
    """Remove the finite line interval under a click, bounded by intersections.

    This draft-level operation only trims standalone straight lines against
    non-construction straight segments. The source line identity stays with
    its first surviving fragment in the line's original direction; any other
    surviving fragment receives a new identity.
    """
    if any(isinstance(value, bool) or not math.isfinite(value) for value in click_mm):
        raise ValueError("trim click must contain finite coordinates")
    point = (float(click_mm[0]), float(click_mm[1]))
    if isinstance(hit_tolerance_mm, bool) or not math.isfinite(hit_tolerance_mm):
        raise ValueError("trim hit tolerance must be finite")
    tolerance = float(hit_tolerance_mm)
    if tolerance <= 0.0:
        raise ValueError("trim hit tolerance must be positive")

    line_candidates: list[tuple[int, LineEntity, float, float]] = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, LineEntity) or (
            target_entity_id is not None and entity.entity_id != target_entity_id
        ):
            continue
        ratio, distance = _projection(point, entity.start_mm, entity.end_mm)
        if distance <= tolerance:
            line_candidates.append((index, entity, ratio, distance))
    if not line_candidates:
        raise ValueError("请点选一条可修剪的直线。")
    line_candidates.sort(key=lambda item: item[3])
    if len(line_candidates) > 1 and abs(line_candidates[0][3] - line_candidates[1][3]) <= _EPSILON:
        raise ValueError("目标直线选择不明确；请分开重叠的线段后再修剪。")

    target_index, target, click_ratio, _distance = line_candidates[0]
    segments = _straight_segments(entities)
    intersections: list[float] = []
    for entity_id, start, end in segments:
        if entity_id == target.entity_id:
            continue
        parameters = _intersection_parameters(target.start_mm, target.end_mm, start, end)
        if parameters is None:
            continue
        first_ratio, second_ratio = parameters
        target_is_interior = _EPSILON < first_ratio < 1.0 - _EPSILON
        target_is_endpoint = (
            allow_endpoint_intersections and -_EPSILON <= first_ratio <= 1.0 + _EPSILON
        )
        if (
            target_is_interior or target_is_endpoint
        ) and -_EPSILON <= second_ratio <= 1.0 + _EPSILON:
            intersections.append(first_ratio)
    if not intersections:
        raise ValueError("没有与其他直线段的内部交点，无法修剪。")

    breakpoints = [0.0]
    for ratio in sorted(intersections):
        if ratio - breakpoints[-1] > _EPSILON:
            breakpoints.append(ratio)
    if 1.0 - breakpoints[-1] > _EPSILON:
        breakpoints.append(1.0)
    interval_index = next(
        (
            index
            for index, (start_ratio, end_ratio) in enumerate(
                zip(breakpoints, breakpoints[1:], strict=False)
            )
            if start_ratio + _EPSILON < click_ratio < end_ratio - _EPSILON
        ),
        None,
    )
    if interval_index is None:
        raise ValueError("请点在线段与交点之间的可修剪区域，不要点交点或端点。")

    # Keep each surviving side continuous across untouched intersections.
    removed_start = breakpoints[interval_index]
    removed_end = breakpoints[interval_index + 1]
    surviving_intervals: list[tuple[float, float]] = []
    if removed_start > _EPSILON:
        surviving_intervals.append((0.0, removed_start))
    if removed_end < 1.0 - _EPSILON:
        surviving_intervals.append((removed_end, 1.0))
    if not surviving_intervals and not allow_endpoint_intersections:
        raise ValueError("修剪会删除整条直线，当前操作已拒绝。")

    dx = target.end_mm[0] - target.start_mm[0]
    dy = target.end_mm[1] - target.start_mm[1]
    fragments = tuple(
        _preserve_entity_metadata(
            target,
            LineEntity(
                target.entity_id if index == 0 else uuid4().hex,
                (
                    target.start_mm[0] + dx * start_ratio,
                    target.start_mm[1] + dy * start_ratio,
                ),
                (
                    target.start_mm[0] + dx * end_ratio,
                    target.start_mm[1] + dy * end_ratio,
                ),
                construction=target.construction,
            ),
        )
        for index, (start_ratio, end_ratio) in enumerate(surviving_intervals)
    )
    return (*entities[:target_index], *fragments, *entities[target_index + 1 :])
