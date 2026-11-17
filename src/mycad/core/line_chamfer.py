# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Two-line chamfer geometry in the independent sketch plane."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.sketch import LineEntity, Point2D, PolylineEntity, RectangleEntity

_EPS = 1e-9


def _cross(a: Point2D, b: Point2D) -> float:
    return a[0] * b[1] - a[1] * b[0]


def line_chamfer(
    first: LineEntity,
    second: LineEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    first_distance: float,
    second_distance: float,
    identity: str,
    *,
    angle_deg: float | None = None,
    trim: bool = True,
    layer_name: str = "0",
) -> tuple[LineEntity, LineEntity, LineEntity | None]:
    """Chamfer the picked rays, preserving source identities and selection order."""
    if first.entity_id == second.entity_id or first.construction != second.construction:
        raise ValueError("请选择两条不同且类型一致的直线。")
    if any(
        isinstance(value, bool) or not math.isfinite(value) or value < 0
        for value in (first_distance, second_distance)
    ) or any(not math.isfinite(value) for point in (first_pick, second_pick) for value in point):
        raise ValueError("倒角距离和拾取坐标必须是有限的非负数值。")
    directions: list[Point2D] = []
    for line in (first, second):
        delta = (line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1])
        length = math.hypot(*delta)
        if not math.isfinite(length) or length <= _EPS:
            raise ValueError("直线长度无效。")
        directions.append((delta[0] / length, delta[1] / length))
    denominator = _cross(directions[0], directions[1])
    if abs(denominator) <= _EPS:
        raise ValueError("平行或重合直线不能倒角。")
    delta = (second.start_mm[0] - first.start_mm[0], second.start_mm[1] - first.start_mm[1])
    along = _cross(delta, directions[1]) / denominator
    vertex = (
        first.start_mm[0] + along * directions[0][0],
        first.start_mm[1] + along * directions[0][1],
    )
    if not all(math.isfinite(value) for value in vertex):
        raise ValueError("直线交点超出范围。")
    rays: list[Point2D] = []
    signs: list[int] = []
    for direction, pick in zip(directions, (first_pick, second_pick), strict=True):
        projection = (pick[0] - vertex[0]) * direction[0] + (pick[1] - vertex[1]) * direction[1]
        if not math.isfinite(projection) or abs(projection) <= _EPS:
            raise ValueError("请在交点一侧选取直线。")
        sign = 1 if projection > 0 else -1
        signs.append(sign)
        rays.append((direction[0] * sign, direction[1] * sign))
    if angle_deg == 0 and not isinstance(angle_deg, bool) and first_distance == 0:
        angle_deg = None
        second_distance = 0.0
    if angle_deg is not None:
        if isinstance(angle_deg, bool) or not math.isfinite(angle_deg) or not 0 < angle_deg < 180:
            raise ValueError("倒角角度必须在 0 至 180 度之间。")
        corner = math.acos(max(-1.0, min(1.0, rays[0][0] * rays[1][0] + rays[0][1] * rays[1][1])))
        angle = math.radians(angle_deg)
        if first_distance <= _EPS or angle + corner >= math.pi - _EPS:
            raise ValueError("倒角角度或距离不能生成所选侧的倒角。")
        second_distance = first_distance * math.sin(angle) / math.sin(corner + angle)
        if not math.isfinite(second_distance):
            raise ValueError("倒角结果超出范围。")
    distances = (first_distance, second_distance)
    contacts = tuple(
        (vertex[0] + ray[0] * distance, vertex[1] + ray[1] * distance)
        for ray, distance in zip(rays, distances, strict=True)
    )
    results: list[LineEntity] = []
    for line, ray, sign, distance, contact in zip(
        (first, second), rays, signs, distances, contacts, strict=True
    ):
        if not trim:
            results.append(line)
            continue
        retained = line.end_mm if sign > 0 else line.start_mm
        available = (retained[0] - vertex[0]) * ray[0] + (retained[1] - vertex[1]) * ray[1]
        if not math.isfinite(available) or available <= distance + _EPS:
            raise ValueError("倒角距离过大，所选侧无法保留有效直线。")
        results.append(
            replace(line, start_mm=contact) if sign > 0 else replace(line, end_mm=contact)
        )
    if first_distance <= _EPS and second_distance <= _EPS:
        if not trim:
            raise ValueError("零距离倒角需要修剪模式。")
        return results[0], results[1], None
    if math.dist(contacts[0], contacts[1]) <= _EPS:
        raise ValueError("倒角线退化为零长度。")
    edge = LineEntity(
        identity, contacts[0], contacts[1], construction=first.construction, layer_name=layer_name
    )
    return results[0], results[1], edge


def polyline_chamfer(
    source: PolylineEntity,
    first_distance: float,
    second_distance: float,
    identities: tuple[str, ...],
    *,
    angle_deg: float | None = None,
    trim: bool = True,
    corner_indices: tuple[int, ...] | None = None,
    reverse: bool = False,
) -> tuple[PolylineEntity, tuple[LineEntity, ...]]:
    """Chamfer eligible straight corners; preserve arcs and skip short segments."""
    points = source.points_mm
    count = len(points)
    segment_count = count if source.closed else count - 1
    if len(identities) != count or len(set(identities)) != count:
        raise ValueError("倒角输出身份无效。")
    if any(
        isinstance(value, bool) or not math.isfinite(value) or value < 0
        for value in (first_distance, second_distance)
    ):
        raise ValueError("倒角距离必须是非负有限数值。")
    if angle_deg == 0 and not isinstance(angle_deg, bool) and first_distance == 0:
        angle_deg = None
        second_distance = 0.0
    if angle_deg is not None and (
        isinstance(angle_deg, bool) or not math.isfinite(angle_deg) or not 0 < angle_deg < 180
    ):
        raise ValueError("倒角角度必须在 0 至 180 度之间。")
    if first_distance <= _EPS and second_distance <= _EPS and angle_deg is None:
        return source, ()
    if corner_indices is not None and (
        len(set(corner_indices)) != len(corner_indices)
        or any(isinstance(index, bool) or not 0 <= index < count for index in corner_indices)
    ):
        raise ValueError("多段线角点无效。")
    bulges = source.bulges or (0.0,) * segment_count
    corners: dict[int, tuple[Point2D, Point2D, LineEntity]] = {}
    for index in range(count):
        if corner_indices is not None and index not in corner_indices:
            continue
        if not source.closed and index in (0, count - 1):
            continue
        previous = (index - 1) % count
        following = (index + 1) % count
        if bulges[previous] != 0 or bulges[index] != 0:
            continue
        left = LineEntity("00000000000000000000000000000001", points[previous], points[index])
        right = LineEntity("00000000000000000000000000000002", points[index], points[following])
        try:
            a, b, edge = line_chamfer(
                right if reverse else left,
                left if reverse else right,
                points[following] if reverse else points[previous],
                points[previous] if reverse else points[following],
                first_distance,
                second_distance,
                identities[index],
                angle_deg=angle_deg,
                layer_name=source.layer_name,
            )
        except ValueError:
            continue
        if edge is not None:
            incoming = b.end_mm if reverse else a.end_mm
            outgoing = a.start_mm if reverse else b.start_mm
            corners[index] = (incoming, outgoing, replace(edge, construction=source.construction))
    if trim:
        for index in range(segment_count):
            following = (index + 1) % count
            if index not in corners or following not in corners:
                continue
            length = math.dist(points[index], points[following])
            consumed = math.dist(points[index], corners[index][1]) + math.dist(
                points[following], corners[following][0]
            )
            if consumed >= length - _EPS:
                corners.pop(index, None)
                corners.pop(following, None)
    if not trim:
        return source, tuple(corners[index][2] for index in sorted(corners))
    output_points: list[Point2D] = []
    output_bulges: list[float] = []
    for index, point in enumerate(points):
        corner = corners.get(index)
        if corner is not None:
            output_points.extend(corner[:2])
            output_bulges.append(0.0)
        else:
            output_points.append(point)
        if index < segment_count:
            output_bulges.append(bulges[index])
    return replace(source, points_mm=tuple(output_points), bulges=tuple(output_bulges)), ()


def rectangle_chamfer(
    source: RectangleEntity,
    first_distance: float,
    second_distance: float,
    replacement_identity: str,
    identities: tuple[str, ...],
    *,
    angle_deg: float | None = None,
    trim: bool = True,
    corner_indices: tuple[int, ...] | None = None,
    reverse: bool = False,
) -> tuple[PolylineEntity, tuple[LineEntity, ...]]:
    """Represent a chamfered rectangle as an identity-safe closed polyline."""
    x1, y1 = source.first_corner_mm
    x2, y2 = source.opposite_corner_mm
    polyline = PolylineEntity(
        replacement_identity,
        ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
        closed=True,
        construction=source.construction,
        layer_name=source.layer_name,
    )
    return polyline_chamfer(
        polyline,
        first_distance,
        second_distance,
        identities,
        angle_deg=angle_deg,
        trim=trim,
        corner_indices=corner_indices,
        reverse=reverse,
    )


def polyline_chamfer_between(
    source: PolylineEntity,
    first_index: int,
    second_index: int,
    first_pick: Point2D,
    second_pick: Point2D,
    first_distance: float,
    second_distance: float,
    identity: str,
    *,
    angle_deg: float | None = None,
    trim: bool = True,
) -> tuple[PolylineEntity, LineEntity | None]:
    """Replace one intermediate segment between two selected straight segments."""
    from mycad.core.polyline_curves import polyline_curve_segments

    count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
    if (
        isinstance(first_index, bool)
        or isinstance(second_index, bool)
        or not 0 <= first_index < count
        or not 0 <= second_index < count
    ):
        raise ValueError("请选择间隔一段的直线段。")
    bulges = source.bulges or (0.0,) * count
    if source.closed:
        starts = [
            index
            for index, other in ((first_index, second_index), (second_index, first_index))
            if (index + 2) % count == other
        ]
        if len(starts) != 1:
            raise ValueError("闭合多段线的间隔路径不明确。")
        start = starts[0]
        rotated_points = (*source.points_mm[start:], *source.points_mm[:start])
        rotated_bulges = (*bulges[start:], *bulges[:start])
        opened = replace(
            source,
            points_mm=(*rotated_points, rotated_points[0]),
            bulges=rotated_bulges,
            closed=False,
        )
        revised, edge = polyline_chamfer_between(
            opened,
            (first_index - start) % count,
            (second_index - start) % count,
            first_pick,
            second_pick,
            first_distance,
            second_distance,
            identity,
            angle_deg=angle_deg,
            trim=trim,
        )
        if not trim:
            return source, edge
        points = revised.points_mm[:-1]
        result_bulges = revised.bulges or (0.0,) * len(points)
        if source.points_mm[0] in points:
            origin = points.index(source.points_mm[0])
            points = (*points[origin:], *points[:origin])
            result_bulges = (*result_bulges[origin:], *result_bulges[:origin])
        return replace(source, points_mm=points, bulges=result_bulges, closed=True), None
    if abs(first_index - second_index) != 2:
        raise ValueError("请选择间隔一段的直线段。")
    segments = polyline_curve_segments(
        source.points_mm,
        bulges,
        source.closed,
        source.entity_id,
        construction=source.construction,
        layer_name=source.layer_name,
    )
    first, second = segments[first_index], segments[second_index]
    if not isinstance(first, LineEntity) or not isinstance(second, LineEntity):
        raise ValueError("倒角仅支持选取直线段。")
    first = replace(first, entity_id="00000000000000000000000000000001")
    second = replace(second, entity_id="00000000000000000000000000000002")
    a, b, edge = line_chamfer(
        first,
        second,
        first_pick,
        second_pick,
        first_distance,
        second_distance,
        identity,
        angle_deg=angle_deg,
        trim=trim,
        layer_name=source.layer_name,
    )
    if not trim:
        return source, edge
    left = min(first_index, second_index)
    left_result, right_result = (a, b) if first_index == left else (b, a)
    if (
        math.dist(left_result.start_mm, source.points_mm[left]) > _EPS
        or math.dist(right_result.end_mm, source.points_mm[left + 3]) > _EPS
    ):
        raise ValueError("请选择保留多段线外侧路径的保留侧。")
    if edge is None:
        contacts = [
            (x, y)
            for x in (a.start_mm, a.end_mm)
            for y in (b.start_mm, b.end_mm)
            if math.dist(x, y) <= _EPS
        ]
        if len(contacts) != 1:
            raise ValueError("无法确定多段线交点。")
        first_contact = second_contact = contacts[0][0]
    else:
        first_contact, second_contact = edge.start_mm, edge.end_mm
    incoming, outgoing = (
        (first_contact, second_contact) if first_index == left else (second_contact, first_contact)
    )
    if edge is None:
        points = (*source.points_mm[: left + 1], incoming, *source.points_mm[left + 3 :])
        result_bulges = (*bulges[:left], 0.0, 0.0, *bulges[left + 3 :])
    else:
        points = (*source.points_mm[: left + 1], incoming, outgoing, *source.points_mm[left + 3 :])
        result_bulges = (*bulges[:left], 0.0, 0.0, 0.0, *bulges[left + 3 :])
    return replace(source, points_mm=points, bulges=result_bulges), None


def polyline_chamfer_close(
    source: PolylineEntity,
    first_index: int,
    second_index: int,
    first_pick: Point2D,
    second_pick: Point2D,
    first_distance: float,
    second_distance: float,
    identity: str,
    *,
    angle_deg: float | None = None,
    trim: bool = True,
) -> tuple[PolylineEntity, LineEntity | None]:
    """Chamfer the outer ends of an open path and close it in trim mode."""
    from mycad.core.polyline_curves import polyline_curve_segments

    count = len(source.points_mm) - 1
    if source.closed or count < 2 or {first_index, second_index} != {0, count - 1}:
        raise ValueError("请选择开放多段线的首尾直线段。")
    bulges = source.bulges or (0.0,) * count
    segments = polyline_curve_segments(
        source.points_mm,
        bulges,
        False,
        source.entity_id,
        construction=source.construction,
        layer_name=source.layer_name,
    )
    first, second = segments[first_index], segments[second_index]
    if not isinstance(first, LineEntity) or not isinstance(second, LineEntity):
        raise ValueError("倒角仅支持选取直线段。")
    first = replace(first, entity_id="00000000000000000000000000000001")
    second = replace(second, entity_id="00000000000000000000000000000002")
    a, b, edge = line_chamfer(
        first,
        second,
        first_pick,
        second_pick,
        first_distance,
        second_distance,
        identity,
        angle_deg=angle_deg,
        trim=trim,
        layer_name=source.layer_name,
    )
    if not trim:
        return source, edge
    first_result, last_result = (a, b) if first_index == 0 else (b, a)
    if (
        math.dist(first_result.end_mm, source.points_mm[1]) > _EPS
        or math.dist(last_result.start_mm, source.points_mm[-2]) > _EPS
    ):
        raise ValueError("请选择靠近多段线首尾的保留侧。")
    first_contact, last_contact = first_result.start_mm, last_result.end_mm
    if edge is None:
        if math.dist(first_contact, last_contact) > _EPS:
            raise ValueError("无法确定多段线闭合交点。")
        points = (first_contact, *source.points_mm[1:-1])
        result_bulges = (0.0, *bulges[1:-1], 0.0)
    else:
        points = (first_contact, *source.points_mm[1:-1], last_contact)
        result_bulges = (0.0, *bulges[1:-1], 0.0, 0.0)
    return replace(source, points_mm=points, bulges=result_bulges, closed=True), None
