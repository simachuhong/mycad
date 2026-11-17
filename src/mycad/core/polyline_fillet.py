# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Round straight and circular polyline segments with exact bulges."""

from __future__ import annotations

import math
from dataclasses import replace
from uuid import uuid4

from mycad.core.circle_fillet import circle_fillet_notrim
from mycad.core.curve_corner import curve_corner_with_contact
from mycad.core.fillet_curves import contact_on_curve, tangent_on_curves, trim_arc_at_contact
from mycad.core.line_circle_fillet import line_circle_fillet_notrim, line_circle_fillet_trim
from mycad.core.line_fillet import line_corner, line_fillet, lines_parallel
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D, PolylineEntity
from mycad.core.sketch_edit import (
    supporting_circle_intersections,
    supporting_line_circle_intersections,
)


def polyline_line_fillet(
    source: PolylineEntity,
    segment_index: int,
    line: LineEntity,
    segment_pick: Point2D,
    line_pick: Point2D,
    radius: float,
) -> PolylineEntity:
    """Trim the picked polyline branch and join it to a line with a fillet."""
    count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
    if isinstance(segment_index, bool) or not 0 <= segment_index < count:
        raise ValueError("多段线段不存在。")
    if source.entity_id == line.entity_id:
        raise ValueError("请选择两个不同的对象。")
    bulges = source.bulges or (0.0,) * count
    selected = polyline_curve_segments(
        source.points_mm,
        bulges,
        source.closed,
        source.entity_id,
        construction=source.construction,
        layer_name=source.layer_name,
    )[segment_index]
    if isinstance(selected, ArcEntity) and radius == 0:
        first_result, second_result, contact = curve_corner_with_contact(
            selected, line, segment_pick, line_pick
        )
        assert isinstance(first_result, ArcEntity) and isinstance(second_result, LineEntity)
        selected_result, line_result = first_result, second_result
        selected_contact = line_contact = contact
        arc = None
    elif isinstance(selected, ArcEntity):
        line_result, reverse_arc = line_circle_fillet_trim(
            line,
            selected,
            line_pick,
            segment_pick,
            radius,
            uuid4().hex,
            layer_name=source.layer_name,
        )
        arc = replace(
            reverse_arc,
            start_angle_deg=reverse_arc.start_angle_deg + reverse_arc.sweep_angle_deg,
            sweep_angle_deg=-reverse_arc.sweep_angle_deg,
        )
        selected_contact = _segment_point(arc, 0)
        line_contact = _segment_point(arc, 1)
        selected_result = trim_arc_at_contact(selected, selected_contact, segment_pick)
    elif radius == 0 and not lines_parallel(selected, line):
        selected_result, line_result = line_corner(selected, line, segment_pick, line_pick)
        intersections = _support_intersections(selected, line)
        if len(intersections) != 1:
            raise ValueError("无法确定圆角交点。")
        selected_contact = line_contact = intersections[0]
        arc = None
    else:
        selected_result, line_result, arc = line_fillet(
            selected,
            line,
            segment_pick,
            line_pick,
            radius,
            uuid4().hex,
            layer_name=source.layer_name,
        )
        selected_contact = _segment_point(arc, 0)
        line_contact = _segment_point(arc, 1)
    branch_points, branch_bulges, keep_start = _retained_polyline_branch(
        source, segment_index, selected, selected_result, selected_contact
    )
    if math.dist(line_result.start_mm, line_contact) <= 1e-8:
        far = line_result.end_mm
    elif math.dist(line_result.end_mm, line_contact) <= 1e-8:
        far = line_result.start_mm
    else:
        raise ValueError("无法确定直线保留侧。")
    if arc is None:
        points = (*branch_points, far) if keep_start else (far, *branch_points)
        result_bulges = (*branch_bulges, 0.0) if keep_start else (0.0, *branch_bulges)
    else:
        arc_bulge = math.tan(math.radians(arc.sweep_angle_deg) / 4)
        if keep_start:
            points = (*branch_points, line_contact, far)
            result_bulges = (*branch_bulges, arc_bulge, 0.0)
        else:
            points = (far, line_contact, *branch_points)
            result_bulges = (0.0, -arc_bulge, *branch_bulges)
    return replace(source, points_mm=points, bulges=result_bulges, closed=False)


def _retained_polyline_branch(
    source: PolylineEntity,
    segment_index: int,
    selected: LineEntity | ArcEntity,
    selected_result: LineEntity | ArcEntity,
    selected_contact: Point2D,
) -> tuple[tuple[Point2D, ...], tuple[float, ...], bool]:
    count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
    bulges = source.bulges or (0.0,) * count
    keep_start = (
        math.dist(_segment_point(selected_result, 0), _segment_point(selected, 0)) <= 1e-8
        and math.dist(_segment_point(selected_result, 1), selected_contact) <= 1e-8
    )
    keep_end = (
        math.dist(_segment_point(selected_result, 1), _segment_point(selected, 1)) <= 1e-8
        and math.dist(_segment_point(selected_result, 0), selected_contact) <= 1e-8
    )
    if keep_start == keep_end:
        raise ValueError("无法确定多段线保留侧。")
    retained_bulge = (
        math.tan(math.radians(selected_result.sweep_angle_deg) / 4)
        if isinstance(selected_result, ArcEntity)
        else 0.0
    )
    if source.closed:
        remaining_points = (
            *source.points_mm[segment_index + 1 :],
            *source.points_mm[: segment_index + 1],
        )
        remaining_bulges = (*bulges[segment_index + 1 :], *bulges[:segment_index])
        if keep_start:
            branch_points = (*remaining_points, selected_contact)
            branch_bulges = (*remaining_bulges, retained_bulge)
        else:
            branch_points = (selected_contact, *remaining_points)
            branch_bulges = (retained_bulge, *remaining_bulges)
    elif keep_start:
        branch_points = (*source.points_mm[: segment_index + 1], selected_contact)
        branch_bulges = (*bulges[:segment_index], retained_bulge)
    else:
        branch_points = (selected_contact, *source.points_mm[segment_index + 1 :])
        branch_bulges = (retained_bulge, *bulges[segment_index + 1 :])
    return branch_points, branch_bulges, keep_start


def polyline_circular_fillet(
    source: PolylineEntity,
    segment_index: int,
    circular: CircleEntity | ArcEntity,
    segment_pick: Point2D,
    circular_pick: Point2D,
    radius: float,
    *,
    layer_name: str = "0",
) -> tuple[PolylineEntity, CircleEntity | ArcEntity, ArcEntity | None, int]:
    """Trim a polyline segment and circular source, returning a separate fillet."""
    count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
    if isinstance(segment_index, bool) or not 0 <= segment_index < count:
        raise ValueError("多段线段不存在。")
    segments = polyline_curve_segments(
        source.points_mm,
        source.bulges or (0.0,) * count,
        source.closed,
        source.entity_id,
        construction=source.construction,
        layer_name=source.layer_name,
    )
    selected = segments[segment_index]
    if radius == 0:
        first_result, target, contact = curve_corner_with_contact(
            selected, circular, segment_pick, circular_pick
        )
        assert isinstance(first_result, LineEntity | ArcEntity) and isinstance(
            target, CircleEntity | ArcEntity
        )
        selected_result = first_result
        arc = None
    elif isinstance(selected, LineEntity):
        selected_result, arc = line_circle_fillet_trim(
            selected,
            circular,
            segment_pick,
            circular_pick,
            radius,
            uuid4().hex,
            layer_name=layer_name,
        )
        contact = _segment_point(arc, 0)
        target = (
            trim_arc_at_contact(circular, _segment_point(arc, 1), circular_pick)
            if isinstance(circular, ArcEntity)
            else circular
        )
    else:
        arc = circle_fillet_notrim(
            selected,
            circular,
            segment_pick,
            circular_pick,
            radius,
            uuid4().hex,
            layer_name=layer_name,
            extend_arcs=True,
        )
        contact = _segment_point(arc, 0)
        selected_result = trim_arc_at_contact(selected, contact, segment_pick)
        target = (
            trim_arc_at_contact(circular, _segment_point(arc, 1), circular_pick)
            if isinstance(circular, ArcEntity)
            else circular
        )
    points, bulges, keep_start = _retained_polyline_branch(
        source, segment_index, selected, selected_result, contact
    )
    result = replace(source, points_mm=points, bulges=bulges, closed=False)
    result_segment = len(result.points_mm) - 2 if keep_start else 0
    return result, target, arc, result_segment


def polyline_polyline_fillet(
    first: PolylineEntity,
    first_index: int,
    second: PolylineEntity,
    second_index: int,
    first_pick: Point2D,
    second_pick: Point2D,
    radius: float,
) -> PolylineEntity:
    """Join the picked branches of two distinct polylines with a fillet."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两条不同的多段线。")

    def selected_curve(source: PolylineEntity, index: int) -> LineEntity | ArcEntity:
        count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
        if isinstance(index, bool) or not 0 <= index < count:
            raise ValueError("多段线段不存在。")
        return polyline_curve_segments(
            source.points_mm,
            source.bulges or (0.0,) * count,
            source.closed,
            source.entity_id,
            construction=source.construction,
            layer_name=source.layer_name,
        )[index]

    first_curve = selected_curve(first, first_index)
    second_curve = selected_curve(second, second_index)
    both_lines = isinstance(first_curve, LineEntity) and isinstance(second_curve, LineEntity)
    if (
        radius == 0
        and isinstance(first_curve, LineEntity)
        and isinstance(second_curve, LineEntity)
        and not lines_parallel(first_curve, second_curve)
    ):
        a, b = line_corner(first_curve, second_curve, first_pick, second_pick)
        intersections = _support_intersections(first_curve, second_curve)
        if len(intersections) != 1:
            raise ValueError("无法确定圆角交点。")
        first_contact = second_contact = intersections[0]
        arc = None
    elif radius == 0 and not both_lines:
        a, b, contact = curve_corner_with_contact(
            first_curve, second_curve, first_pick, second_pick
        )
        assert isinstance(a, LineEntity | ArcEntity) and isinstance(b, LineEntity | ArcEntity)
        first_contact = second_contact = contact
        arc = None
    elif isinstance(first_curve, LineEntity) and isinstance(second_curve, LineEntity):
        a, b, arc = line_fillet(
            first_curve,
            second_curve,
            first_pick,
            second_pick,
            radius,
            uuid4().hex,
            layer_name=first.layer_name,
        )
        first_contact, second_contact = _segment_point(arc, 0), _segment_point(arc, 1)
    elif isinstance(first_curve, LineEntity) and isinstance(second_curve, ArcEntity):
        a, arc = line_circle_fillet_trim(
            first_curve,
            second_curve,
            first_pick,
            second_pick,
            radius,
            uuid4().hex,
            layer_name=first.layer_name,
        )
        first_contact, second_contact = _segment_point(arc, 0), _segment_point(arc, 1)
        b = trim_arc_at_contact(second_curve, second_contact, second_pick)
    elif isinstance(first_curve, ArcEntity) and isinstance(second_curve, LineEntity):
        b, reversed_arc = line_circle_fillet_trim(
            second_curve,
            first_curve,
            second_pick,
            first_pick,
            radius,
            uuid4().hex,
            layer_name=first.layer_name,
        )
        arc = replace(
            reversed_arc,
            start_angle_deg=reversed_arc.start_angle_deg + reversed_arc.sweep_angle_deg,
            sweep_angle_deg=-reversed_arc.sweep_angle_deg,
        )
        first_contact, second_contact = _segment_point(arc, 0), _segment_point(arc, 1)
        a = trim_arc_at_contact(first_curve, first_contact, first_pick)
    else:
        assert isinstance(first_curve, ArcEntity) and isinstance(second_curve, ArcEntity)
        arc = circle_fillet_notrim(
            first_curve,
            second_curve,
            first_pick,
            second_pick,
            radius,
            uuid4().hex,
            layer_name=first.layer_name,
            extend_arcs=True,
        )
        first_contact, second_contact = _segment_point(arc, 0), _segment_point(arc, 1)
        a = trim_arc_at_contact(first_curve, first_contact, first_pick)
        b = trim_arc_at_contact(second_curve, second_contact, second_pick)
    first_points, first_bulges, first_ends = _retained_polyline_branch(
        first, first_index, first_curve, a, first_contact
    )
    second_points, second_bulges, second_ends = _retained_polyline_branch(
        second, second_index, second_curve, b, second_contact
    )
    if not first_ends:
        first_points = tuple(reversed(first_points))
        first_bulges = tuple(-value for value in reversed(first_bulges))
    if second_ends:
        second_points = tuple(reversed(second_points))
        second_bulges = tuple(-value for value in reversed(second_bulges))
    if arc is None:
        points = (*first_points, *second_points[1:])
        bulges = (*first_bulges, *second_bulges)
    else:
        points = (*first_points, *second_points)
        bulges = (*first_bulges, math.tan(math.radians(arc.sweep_angle_deg) / 4), *second_bulges)
    return replace(first, points_mm=points, bulges=bulges, closed=False)


def polyline_segment_fillet(
    source: PolylineEntity,
    first_index: int,
    second_index: int,
    radius: float,
    *,
    trim: bool = True,
    first_pick: Point2D | None = None,
    second_pick: Point2D | None = None,
) -> tuple[PolylineEntity, ArcEntity | None]:
    """Round two selected straight segments while preserving the remaining path."""
    if isinstance(radius, bool) or not math.isfinite(radius) or radius < 0:
        raise ValueError("多段线圆角半径必须是非负有限数值。")
    count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
    bulges = source.bulges or (0.0,) * count
    segments = polyline_curve_segments(
        source.points_mm,
        bulges,
        source.closed,
        source.entity_id,
        construction=source.construction,
        layer_name=source.layer_name,
    )
    count = len(segments)
    if (
        isinstance(first_index, bool)
        or isinstance(second_index, bool)
        or not 0 <= first_index < count
        or not 0 <= second_index < count
        or first_index == second_index
    ):
        raise ValueError("请选择两条不同的多段线段。")
    if (first_pick is None) != (second_pick is None):
        raise ValueError("两次拾取位置必须同时提供。")
    if any(
        not math.isfinite(value)
        for point in (first_pick, second_pick)
        if point is not None
        for value in point
    ):
        raise ValueError("拾取坐标必须是有限数值。")
    if isinstance(segments[first_index], ArcEntity) or isinstance(
        segments[second_index], ArcEntity
    ):
        is_open_ends = not source.closed and {first_index, second_index} == {0, count - 1}
        closes_open_path = (
            is_open_ends and count >= 3 and (count > 3 or isinstance(segments[1], LineEntity))
        )
        if is_open_ends and count in (2, 3) and first_pick is not None and second_pick is not None:
            start_pick, end_pick = (
                (first_pick, second_pick) if first_index == 0 else (second_pick, first_pick)
            )
            start_ratio = min(1.0, max(0.0, _segment_ratio(segments[0], start_pick)))
            end_ratio = min(1.0, max(0.0, _segment_ratio(segments[-1], end_pick)))
            if count == 2 or isinstance(segments[1], ArcEntity):
                closes_open_path = start_ratio + (1 - end_ratio) < 0.95
        if closes_open_path:
            start_pick, end_pick = (
                (first_pick, second_pick) if first_index == 0 else (second_pick, first_pick)
            )
            return _close_open_mixed_polyline(
                source,
                segments[0],
                segments[-1],
                radius,
                trim=trim,
                first_pick=start_pick,
                last_pick=end_pick,
            )
        forward = (first_index + 1) % count == second_index and (
            source.closed or second_index > first_index
        )
        backward = (second_index + 1) % count == first_index and (
            source.closed or first_index > second_index
        )
        if forward == backward:
            if not forward:
                starts: list[int] = []
                for start, end in ((first_index, second_index), (second_index, first_index)):
                    distance = (end - start) % count if source.closed else end - start
                    if distance == 2 and isinstance(segments[(start + 1) % count], ArcEntity):
                        starts.append(start)
                if len(starts) == 1 and (not source.closed or count > 3):
                    return _replace_selected_mixed_fillet(source, starts[0], radius, trim=trim)
                if len(starts) > 1:
                    raise ValueError("多段线两段之间的路径不明确。")
            raise ValueError("请选择路径明确的相邻多段线段。")
        junction = second_index if forward else first_index
        if radius == 0:
            if not trim:
                raise ValueError("零半径多段线圆角需要修剪模式。")
            return source, None
        rounded, generated = _round_mixed_junctions(
            source, radius, [False] * count, corner_indices=(junction,)
        )
        if not any(generated):
            raise ValueError("无法在所选有限多段线段上创建圆角。")
        if trim:
            return rounded, None
        curves = polyline_curve_segments(
            rounded.points_mm,
            rounded.bulges,
            rounded.closed,
            rounded.entity_id,
            construction=source.construction,
            layer_name=source.layer_name,
        )
        generated_arcs = tuple(
            curve
            for curve, created in zip(curves, generated, strict=True)
            if created and isinstance(curve, ArcEntity)
        )
        if len(generated_arcs) != 1:
            raise ValueError("无法确定新建圆角。")
        return source, replace(generated_arcs[0], entity_id=uuid4().hex)
    closes_open_path = (
        not source.closed
        and count >= 3
        and {first_index, second_index} == {0, count - 1}
        and (count > 3 or isinstance(segments[1], LineEntity))
    )
    if (
        not source.closed
        and count in (2, 3)
        and {first_index, second_index} == {0, count - 1}
        and first_pick is not None
        and second_pick is not None
    ):
        if any(not math.isfinite(value) for point in (first_pick, second_pick) for value in point):
            raise ValueError("拾取坐标必须是有限数值。")
        start_pick, end_pick = (
            (first_pick, second_pick) if first_index == 0 else (second_pick, first_pick)
        )
        start_segment, end_segment = segments[0], segments[-1]
        assert isinstance(start_segment, LineEntity) and isinstance(end_segment, LineEntity)
        start_ratio = min(1.0, max(0.0, _segment_ratio(start_segment, start_pick)))
        end_ratio = min(1.0, max(0.0, _segment_ratio(end_segment, end_pick)))
        # Near the middle of both segments, prefer replacing the inner
        # junction; a small margin keeps screen rounding from flipping it.
        closes_open_path = (
            lines_parallel(start_segment, end_segment) or start_ratio + (1 - end_ratio) < 0.95
        )
    if closes_open_path:
        first, last = segments[0], segments[-1]
        assert isinstance(first, LineEntity) and isinstance(last, LineEntity)
        first = replace(first, entity_id=uuid4().hex)
        last = replace(last, entity_id=uuid4().hex)
        parallel = lines_parallel(last, first)
        if radius == 0 and not trim and not parallel:
            raise ValueError("零半径多段线圆角需要修剪模式。")
        if radius == 0 and not parallel:
            if count == 2:
                raise ValueError("两段直线无法以零半径闭合非退化路径。")
            intersections = _support_intersections(last, first)
            if len(intersections) != 1:
                raise ValueError("无法确定多段线闭合交点。")
            last_contact = first_contact = intersections[0]
            closing_arc = None
        else:
            _, _, closing_arc = line_fillet(
                last,
                first,
                last.end_mm if parallel or count == 2 else last.start_mm,
                first.start_mm if count == 2 else first.end_mm,
                radius,
                uuid4().hex,
                layer_name=source.layer_name,
            )
            last_contact = _segment_point(closing_arc, 0)
            first_contact = _segment_point(closing_arc, 1)
        if (
            _segment_ratio(last, last_contact) <= 1e-9
            or _segment_ratio(first, first_contact) >= 1 - 1e-9
        ):
            raise ValueError("圆角无法保留所选多段线路径。")
        if not trim:
            if (
                closing_arc is None
                or not tangent_on_curves(last, closing_arc)
                or not tangent_on_curves(first, closing_arc)
            ):
                raise ValueError("不修剪模式要求切点位于原多段线段上。")
            return source, closing_arc
        if closing_arc is None:
            new_points = (last_contact, *source.points_mm[1:-1])
            new_bulges = (0.0, *bulges[1:-1], 0.0)
        else:
            new_points = (first_contact, *source.points_mm[1:-1], last_contact)
            new_bulges = (
                0.0,
                *bulges[1:-1],
                0.0,
                math.tan(math.radians(closing_arc.sweep_angle_deg) / 4),
            )
        return replace(source, points_mm=new_points, bulges=new_bulges, closed=True), None

    def gap(start: int, end: int) -> int | None:
        distance = (end - start) % count if source.closed else end - start
        if distance == 1:
            return distance
        if distance == 2:
            return distance
        return None

    forward, backward = gap(first_index, second_index), gap(second_index, first_index)
    if forward is not None and backward is not None and forward == backward:
        raise ValueError("多段线两段之间的路径不明确。")
    if forward is not None and (backward is None or forward <= backward):
        start_index, span = first_index, forward
    elif backward is not None:
        start_index, span = second_index, backward
    else:
        raise ValueError("请选择相邻直线段或中间仅有一段的直线段。")
    if source.closed and span + 1 >= count:
        raise ValueError("所选路径不足以保留闭合多段线。")
    ordered_first = start_index
    ordered_second = second_index if ordered_first == first_index else first_index
    points = source.points_mm
    if source.closed:
        points = (*points[start_index:], *points[:start_index])
        bulges = (*bulges[start_index:], *bulges[:start_index])
        start_index = 0
    first = segments[ordered_first]
    second = segments[ordered_second]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    first = replace(first, entity_id=uuid4().hex)
    second = replace(second, entity_id=uuid4().hex)
    if lines_parallel(first, second):
        raise ValueError("平行多段线段无法形成角点。")
    if span == 2 and isinstance(segments[(ordered_first + 1) % count], ArcEntity):
        corner_first, corner_second = line_corner(first, second, first.start_mm, second.end_mm)
        if (
            math.dist(corner_first.start_mm, first.start_mm) > 1e-8
            or math.dist(corner_second.end_mm, second.end_mm) > 1e-8
            or _segment_ratio(first, corner_first.end_mm) < 1 - 1e-9
            or _segment_ratio(second, corner_second.start_mm) > 1e-9
        ):
            raise ValueError("两条直线段未朝中间圆弧收敛。")
    if radius == 0:
        if not trim:
            raise ValueError("零半径多段线圆角需要修剪模式。")
        if span == 1:
            return source, None
        a, b = line_corner(first, second, first.start_mm, second.end_mm)
        arc = None
    else:
        a, b, arc = line_fillet(
            first,
            second,
            first.start_mm,
            second.end_mm,
            radius,
            uuid4().hex,
            layer_name=source.layer_name,
        )
    if math.dist(a.start_mm, first.start_mm) > 1e-8 or math.dist(b.end_mm, second.end_mm) > 1e-8:
        raise ValueError("圆角无法保留所选多段线路径。")
    if trim and arc is not None and span == 2:
        existing = segments[(ordered_first + 1) % count]
        if (
            isinstance(existing, ArcEntity)
            and math.isclose(existing.radius_mm, arc.radius_mm, rel_tol=1e-12, abs_tol=1e-10)
            and math.dist(existing.center_mm, arc.center_mm) <= 1e-9
            and abs(existing.sweep_angle_deg - arc.sweep_angle_deg) <= 1e-9
            and math.dist(_segment_point(existing, 0), a.end_mm) <= 1e-9
            and math.dist(_segment_point(existing, 1), b.start_mm) <= 1e-9
        ):
            return source, None
    if not trim:
        if arc is None or not tangent_on_curves(first, arc) or not tangent_on_curves(second, arc):
            raise ValueError("不修剪模式要求切点位于原多段线段上。")
        return source, arc
    prefix_points = points[: start_index + 1]
    suffix_points = points[start_index + span + 1 :]
    prefix_bulges = bulges[:start_index]
    suffix_bulges = bulges[start_index + span + 1 :]
    if arc is None:
        new_points = (*prefix_points, a.end_mm, *suffix_points)
        new_bulges = (*prefix_bulges, 0.0, 0.0, *suffix_bulges)
    else:
        new_points = (*prefix_points, a.end_mm, b.start_mm, *suffix_points)
        new_bulges = (
            *prefix_bulges,
            0.0,
            math.tan(math.radians(arc.sweep_angle_deg) / 4),
            0.0,
            *suffix_bulges,
        )
    return replace(source, points_mm=new_points, bulges=new_bulges), None


def _replace_selected_mixed_fillet(
    source: PolylineEntity, start_index: int, radius: float, *, trim: bool
) -> tuple[PolylineEntity, ArcEntity | None]:
    """Replace a single existing tangent arc between selected mixed segments."""
    if radius == 0 and not trim:
        raise ValueError("零半径多段线圆角需要修剪模式。")
    points = source.points_mm
    bulges = source.bulges
    if source.closed:
        points = (*points[start_index:], *points[:start_index])
        bulges = (*bulges[start_index:], *bulges[:start_index])
        start_index = 0
    local = PolylineEntity(
        source.entity_id,
        points[start_index : start_index + 4],
        construction=source.construction,
        layer_name=source.layer_name,
        bulges=bulges[start_index : start_index + 3],
    )
    segments = polyline_curve_segments(local.points_mm, local.bulges, False, local.entity_id)
    first, old_arc, second = segments
    if (
        not isinstance(old_arc, ArcEntity)
        or not tangent_on_curves(first, old_arc)
        or not tangent_on_curves(old_arc, second)
    ):
        raise ValueError("所选段之间没有可替换的相切圆角。")
    for incoming, outgoing in ((first, old_arc), (old_arc, second)):
        before, after = _segment_tangent(incoming, 1), _segment_tangent(outgoing, 0)
        if sum(a * b for a, b in zip(before, after, strict=True)) < 1 - 1e-8:
            raise ValueError("所选旧圆角不保持路径方向。")
    corners: list[tuple[float, Point2D]] = []
    for point in _support_intersections(first, second):
        incoming = _extended_bulge(first, point, incoming=True)
        outgoing = _extended_bulge(second, point, incoming=False)
        if incoming is not None and outgoing is not None:
            corners.append((incoming[0] + outgoing[0], point))
    corners.sort(key=lambda item: item[0])
    if not corners or (
        len(corners) > 1
        and abs(corners[0][0] - corners[1][0]) <= 1e-8
        and math.dist(corners[0][1], corners[1][1]) > 1e-8
    ):
        raise ValueError("无法唯一恢复所选旧圆角的角点。")
    changed, _ = _remove_existing_fillet_arcs(
        local, include_curved_neighbours=True, replacement_radius=radius if radius else None
    )
    if radius > 0 and math.isclose(old_arc.radius_mm, radius, rel_tol=1e-12, abs_tol=1e-10):
        if trim:
            return source, None
        return source, replace(old_arc, entity_id=uuid4().hex)
    expected = 3 if radius == 0 else 4
    if changed == local or len(changed.points_mm) != expected:
        raise ValueError("无法重设所选旧圆角。")
    changed_bulges = changed.bulges or (0.0,) * (len(changed.points_mm) - 1)
    if not trim:
        generated = polyline_curve_segments(
            changed.points_mm,
            changed_bulges,
            False,
            changed.entity_id,
            construction=source.construction,
            layer_name=source.layer_name,
        )[1]
        if (
            not isinstance(generated, ArcEntity)
            or not tangent_on_curves(first, generated)
            or not tangent_on_curves(second, generated)
        ):
            raise ValueError("不修剪模式要求切点位于原多段线段上。")
        return source, replace(generated, entity_id=uuid4().hex)
    return replace(
        source,
        points_mm=(
            *points[: start_index + 1],
            *changed.points_mm[1:-1],
            *points[start_index + 3 :],
        ),
        bulges=(*bulges[:start_index], *changed_bulges, *bulges[start_index + 3 :]),
    ), None


def _close_open_mixed_polyline(
    source: PolylineEntity,
    first: LineEntity | ArcEntity,
    last: LineEntity | ArcEntity,
    radius: float,
    *,
    trim: bool,
    first_pick: Point2D | None,
    last_pick: Point2D | None,
) -> tuple[PolylineEntity, ArcEntity | None]:
    """Close a path by joining the last and first finite curves in path order."""
    if radius == 0 and not trim:
        raise ValueError("零半径多段线圆角需要修剪模式。")
    bulges = source.bulges or (0.0,) * (len(source.points_mm) - 1)
    first_part = PolylineEntity(
        uuid4().hex,
        source.points_mm[:2],
        construction=source.construction,
        layer_name=source.layer_name,
        bulges=(bulges[0],),
    )
    last_part = PolylineEntity(
        uuid4().hex,
        source.points_mm[-2:],
        construction=source.construction,
        layer_name=source.layer_name,
        bulges=(bulges[-1],),
    )

    def retained(
        curve: LineEntity | ArcEntity, contact: Point2D, *, keep_start: bool
    ) -> tuple[LineEntity | ArcEntity, float]:
        if isinstance(curve, LineEntity):
            other = curve.start_mm if keep_start else curve.end_mm
            dx, dy = curve.end_mm[0] - curve.start_mm[0], curve.end_mm[1] - curve.start_mm[1]
            direction = ((contact[0] - other[0]) * dx + (contact[1] - other[1]) * dy) * (
                1 if keep_start else -1
            )
            if math.dist(other, contact) <= 1e-9 or direction <= 1e-9:
                raise ValueError("圆角无法保留所选多段线路径。")
            result = (
                replace(curve, end_mm=contact) if keep_start else replace(curve, start_mm=contact)
            )
            return result, 0.0
        pick = _segment_point(curve, 0 if keep_start else 1)
        result = trim_arc_at_contact(curve, contact, pick)
        preserved = _segment_point(result, 0 if keep_start else 1)
        if math.dist(preserved, pick) > 1e-8:
            raise ValueError("圆角无法保留所选多段线路径。")
        return result, math.tan(math.radians(result.sweep_angle_deg) / 4)

    def candidate(
        last_ratio: float, first_ratio: float
    ) -> tuple[PolylineEntity, ArcEntity | None, Point2D, Point2D]:
        if radius == 0 and len(source.points_mm) == 3:
            if isinstance(first, LineEntity) or isinstance(last, LineEntity):
                line = first if isinstance(first, LineEntity) else last
                curve = last if isinstance(first, LineEntity) else first
                assert isinstance(line, LineEntity) and isinstance(curve, ArcEntity)
                intersections = supporting_line_circle_intersections(
                    line.start_mm, line.end_mm, curve.center_mm, curve.radius_mm
                )
            else:
                intersections = supporting_circle_intersections(
                    first.center_mm, first.radius_mm, last.center_mm, last.radius_mm
                )
            contacts = [p for p in intersections if math.dist(p, source.points_mm[1]) > 1e-8]
            if len(contacts) != 1:
                raise ValueError("无法确定非退化的多段线闭合交点。")
            contact = contacts[0]

            def retained_arc(curve: ArcEntity, *, keep_start: bool) -> ArcEntity:
                sign = math.copysign(1.0, curve.sweep_angle_deg)
                angle = math.degrees(
                    math.atan2(contact[1] - curve.center_mm[1], contact[0] - curve.center_mm[0])
                )
                end = curve.start_angle_deg + curve.sweep_angle_deg
                sweep = (
                    (sign * (angle - curve.start_angle_deg)) % 360
                    if keep_start
                    else (sign * (end - angle)) % 360
                )
                if sweep <= 1e-8 or sweep >= 360 - 1e-8:
                    raise ValueError("圆角无法保留所选多段线路径。")
                return replace(
                    curve,
                    start_angle_deg=curve.start_angle_deg if keep_start else angle,
                    sweep_angle_deg=sign * sweep,
                )

            first_result = (
                retained_arc(first, keep_start=False)
                if isinstance(first, ArcEntity)
                else retained(first, contact, keep_start=False)[0]
            )
            last_result = (
                retained_arc(last, keep_start=True)
                if isinstance(last, ArcEntity)
                else retained(last, contact, keep_start=True)[0]
            )
            if first_pick is not None and last_pick is not None:
                for original, result, ratio in (
                    (first, first_result, first_ratio),
                    (last, last_result, last_ratio),
                ):
                    picked = _segment_point(original, ratio)
                    if isinstance(result, ArcEntity):
                        preserved = contact_on_curve(result, picked)
                    else:
                        position = _segment_ratio(result, picked)
                        preserved = -1e-9 <= position <= 1 + 1e-9
                    if not preserved:
                        raise ValueError("无法保留拾取位置所在的多段线路径。")
            first_bulge = (
                math.tan(math.radians(first_result.sweep_angle_deg) / 4)
                if isinstance(first_result, ArcEntity)
                else 0.0
            )
            last_bulge = (
                math.tan(math.radians(last_result.sweep_angle_deg) / 4)
                if isinstance(last_result, ArcEntity)
                else 0.0
            )
            if isinstance(first_result, ArcEntity):
                midpoint = _segment_point(first_result, 0.5)
                half_bulge = math.tan(math.radians(first_result.sweep_angle_deg) / 8)
                points = (contact, midpoint, source.points_mm[1])
                closed_bulges = (half_bulge, half_bulge, last_bulge)
                assert isinstance(first, ArcEntity)
                sign = math.copysign(1.0, first.sweep_angle_deg)
                prefix = (sign * (first.start_angle_deg - first_result.start_angle_deg)) % 360
                original_sweep = abs(first.sweep_angle_deg)
                total = abs(first_result.sweep_angle_deg)
                if (
                    prefix > 1e-7
                    and math.isclose(prefix + original_sweep, total, rel_tol=0, abs_tol=1e-7)
                    and prefix + 1e-7 < total / 2 < prefix + original_sweep - 1e-7
                ):
                    points = (contact, source.points_mm[0], source.points_mm[1])
                    closed_bulges = (
                        math.tan(math.radians(sign * prefix) / 4),
                        bulges[0],
                        last_bulge,
                    )
                    if isinstance(last, ArcEntity) and isinstance(last_result, ArcEntity):
                        extra = abs(last_result.sweep_angle_deg) - abs(last.sweep_angle_deg)
                        if extra > 1e-7:
                            points = (*points, source.points_mm[-1])
                            closed_bulges = (
                                *closed_bulges[:-1],
                                bulges[-1],
                                math.tan(
                                    math.radians(math.copysign(extra, last.sweep_angle_deg)) / 4
                                ),
                            )
            else:
                assert isinstance(last_result, ArcEntity)
                midpoint = _segment_point(last_result, 0.5)
                half_bulge = math.tan(math.radians(last_result.sweep_angle_deg) / 8)
                points = (contact, source.points_mm[1], midpoint)
                closed_bulges = (first_bulge, half_bulge, half_bulge)
                assert isinstance(last, ArcEntity)
                original_sweep = abs(last.sweep_angle_deg)
                total = abs(last_result.sweep_angle_deg)
                extra = total - original_sweep
                if extra > 1e-7 and total / 2 < original_sweep - 1e-7:
                    points = (contact, source.points_mm[1], source.points_mm[-1])
                    closed_bulges = (
                        first_bulge,
                        bulges[-1],
                        math.tan(math.radians(math.copysign(extra, last.sweep_angle_deg)) / 4),
                    )
            return (
                replace(source, points_mm=points, bulges=closed_bulges, closed=True),
                None,
                contact,
                contact,
            )
        joined = polyline_polyline_fillet(
            last_part,
            0,
            first_part,
            0,
            _segment_point(last, last_ratio),
            _segment_point(first, first_ratio),
            radius,
        )
        joined_bulges = joined.bulges or (0.0,) * (len(joined.points_mm) - 1)
        if radius == 0:
            if len(joined.points_mm) != 3:
                raise ValueError("无法确定多段线闭合角点。")
            _, last_bulge = retained(last, joined.points_mm[1], keep_start=True)
            _, first_bulge = retained(first, joined.points_mm[1], keep_start=False)
            return (
                replace(
                    source,
                    points_mm=(joined.points_mm[1], *source.points_mm[1:-1]),
                    bulges=(first_bulge, *bulges[1:-1], last_bulge),
                    closed=True,
                ),
                None,
                joined.points_mm[1],
                joined.points_mm[1],
            )
        if len(joined.points_mm) != 4:
            raise ValueError("无法确定多段线闭合圆角。")
        generated = polyline_curve_segments(
            joined.points_mm,
            joined_bulges,
            False,
            joined.entity_id,
            construction=source.construction,
            layer_name=source.layer_name,
        )[1]
        if not isinstance(generated, ArcEntity):
            raise ValueError("无法确定多段线闭合圆角。")
        if not trim and (
            not tangent_on_curves(first, generated) or not tangent_on_curves(last, generated)
        ):
            raise ValueError("不修剪模式要求切点位于原多段线段上。")
        last_result, last_bulge = retained(last, joined.points_mm[1], keep_start=True)
        first_result, first_bulge = retained(first, joined.points_mm[2], keep_start=False)
        before = _segment_tangent(last_result, 1)
        after = _segment_tangent(generated, 0)
        if sum(a * b for a, b in zip(before, after, strict=True)) < -1 + 1e-8:
            generated = replace(
                generated,
                sweep_angle_deg=generated.sweep_angle_deg
                - math.copysign(360.0, generated.sweep_angle_deg),
            )
        for incoming, outgoing in ((last_result, generated), (generated, first_result)):
            before, after = _segment_tangent(incoming, 1), _segment_tangent(outgoing, 0)
            if sum(a * b for a, b in zip(before, after, strict=True)) < 1 - 1e-8:
                raise ValueError("圆角会使多段线路径方向反折。")
        if not trim:
            return (
                source,
                replace(generated, entity_id=uuid4().hex),
                joined.points_mm[1],
                joined.points_mm[2],
            )
        return (
            replace(
                source,
                points_mm=(joined.points_mm[2], *source.points_mm[1:-1], joined.points_mm[1]),
                bulges=(
                    first_bulge,
                    *bulges[1:-1],
                    last_bulge,
                    math.tan(math.radians(generated.sweep_angle_deg) / 4),
                ),
                closed=True,
            ),
            None,
            joined.points_mm[1],
            joined.points_mm[2],
        )

    if radius == 0:
        result, arc, _, _ = candidate(
            min(1.0, max(0.0, _segment_ratio(last, last_pick))) if last_pick else 0.1,
            min(1.0, max(0.0, _segment_ratio(first, first_pick))) if first_pick else 0.9,
        )
        return result, arc
    attempts = ((0.1, 0.9), *((a, b) for a in (0.1, 0.5, 0.9) for b in (0.1, 0.5, 0.9)))
    choices: list[tuple[float, PolylineEntity, ArcEntity | None, Point2D, Point2D]] = []
    for last_ratio, first_ratio in attempts:
        try:
            result, arc, last_contact, first_contact = candidate(last_ratio, first_ratio)
        except ValueError:
            continue
        if any(
            math.dist(last_contact, old_last) <= 1e-8
            and math.dist(first_contact, old_first) <= 1e-8
            for _, _, _, old_last, old_first in choices
        ):
            continue
        score = math.dist(last_contact, last_pick or _segment_point(last, 1)) + math.dist(
            first_contact, first_pick or _segment_point(first, 0)
        )
        choices.append((score, result, arc, last_contact, first_contact))
    if choices:
        choices.sort(key=lambda choice: choice[0])
        if len(choices) > 1 and math.isclose(choices[0][0], choices[1][0], abs_tol=1e-9):
            raise ValueError("多段线闭合圆角方向不明确，请重新拾取。")
        _, result, arc, _, _ = choices[0]
        return result, arc
    if not trim:
        raise ValueError("不修剪模式要求切点位于原多段线段上并保持路径方向。")
    raise ValueError("无法在保持路径方向的情况下闭合多段线。")


def polyline_fillet_notrim(
    source: PolylineEntity, radius: float, *, layer_name: str = "0"
) -> tuple[ArcEntity, ...]:
    """Create separate arcs for the feasible corners, retaining the source."""
    if radius <= 0:
        raise ValueError("不修剪的多段线圆角需要正半径。")
    vertices, bulges, generated = _polyline_fillet_segments(source, radius)
    arcs = tuple(
        replace(
            segment, entity_id=uuid4().hex, construction=source.construction, layer_name=layer_name
        )
        for segment, is_generated in zip(
            polyline_curve_segments(vertices, bulges, source.closed, source.entity_id),
            generated,
            strict=True,
        )
        if is_generated and isinstance(segment, ArcEntity)
    )
    if not arcs:
        raise ValueError("多段线没有可圆角的顶点。")
    return arcs


def polyline_fillet_trimmed_segments(
    source: PolylineEntity, radius: float
) -> tuple[tuple[Point2D, ...], tuple[float, ...]]:
    """Return ordered vertices and signed bulges for a single rounded polyline."""
    vertices, bulges, _generated = _polyline_fillet_segments(source, radius)
    return vertices, bulges


def _polyline_fillet_segments(
    source: PolylineEntity, radius: float
) -> tuple[tuple[Point2D, ...], tuple[float, ...], tuple[bool, ...]]:
    if isinstance(radius, bool) or not math.isfinite(radius) or radius < 0:
        raise ValueError("多段线圆角半径必须是非负有限数值。")
    generated: list[bool] = [False] * (
        len(source.points_mm) if source.closed else len(source.points_mm) - 1
    )
    if source.bulges:
        source, generated = _remove_existing_fillet_arcs(
            source,
            include_curved_neighbours=True,
            replacement_radius=radius if radius > 0 else None,
        )
    if radius == 0:
        zero_bulges = source.bulges or (0.0,) * (
            len(source.points_mm) if source.closed else len(source.points_mm) - 1
        )
        return source.points_mm, zero_bulges, (False,) * len(zero_bulges)
    if source.bulges:
        source, generated = _round_mixed_junctions(source, radius, generated)
    points = source.points_mm
    count = len(points)
    corner_indices = range(count) if source.closed else range(1, count - 1)
    consumption = [0.0] * (count if source.closed else count - 1)
    original_bulges = source.bulges or (0.0,) * len(consumption)
    arcs: dict[int, ArcEntity] = {}
    for index in corner_indices:
        if original_bulges[(index - 1) % len(original_bulges)] or original_bulges[index]:
            continue
        previous, vertex, following = (
            points[(index - 1) % count],
            points[index],
            points[(index + 1) % count],
        )
        first = LineEntity(uuid4().hex, previous, vertex, source.construction)
        second = LineEntity(uuid4().hex, vertex, following, source.construction)
        first_pick = ((previous[0] + vertex[0]) / 2, (previous[1] + vertex[1]) / 2)
        second_pick = ((following[0] + vertex[0]) / 2, (following[1] + vertex[1]) / 2)
        try:
            trimmed_first, trimmed_second, arc = line_fillet(
                first,
                second,
                first_pick,
                second_pick,
                radius,
                uuid4().hex,
                layer_name=source.layer_name,
            )
        except ValueError:
            continue
        before_index = (index - 1) % count
        before = math.dist(vertex, trimmed_first.end_mm)
        after = math.dist(vertex, trimmed_second.start_mm)
        if (
            consumption[before_index] + before >= math.dist(previous, vertex) - 1e-9
            or consumption[index] + after >= math.dist(vertex, following) - 1e-9
        ):
            continue
        consumption[before_index] += before
        consumption[index] += after
        arcs[index] = arc
    vertices: list[Point2D] = []
    bulges: list[float] = []
    result_generated: list[bool] = []
    if not source.closed:
        vertices.append(source.points_mm[0])
        bulges.append(original_bulges[0])
        result_generated.append(generated[0])
    for index in corner_indices:
        arc = arcs.get(index)
        if arc is None:
            vertices.append(points[index])
            bulges.append(original_bulges[index])
            result_generated.append(generated[index])
            continue
        start = math.radians(arc.start_angle_deg)
        end = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
        vertices.extend(
            (
                (
                    arc.center_mm[0] + radius * math.cos(start),
                    arc.center_mm[1] + radius * math.sin(start),
                ),
                (
                    arc.center_mm[0] + radius * math.cos(end),
                    arc.center_mm[1] + radius * math.sin(end),
                ),
            )
        )
        bulges.extend((math.tan(math.radians(arc.sweep_angle_deg) / 4), 0.0))
        result_generated.extend((True, False))
    if not source.closed:
        vertices.append(source.points_mm[-1])
    return tuple(vertices), tuple(bulges), tuple(result_generated)


def _segment_point(segment: LineEntity | ArcEntity, ratio: float) -> Point2D:
    if isinstance(segment, LineEntity):
        return (
            segment.start_mm[0] + ratio * (segment.end_mm[0] - segment.start_mm[0]),
            segment.start_mm[1] + ratio * (segment.end_mm[1] - segment.start_mm[1]),
        )
    angle = math.radians(segment.start_angle_deg + ratio * segment.sweep_angle_deg)
    return (
        segment.center_mm[0] + segment.radius_mm * math.cos(angle),
        segment.center_mm[1] + segment.radius_mm * math.sin(angle),
    )


def _segment_ratio(segment: LineEntity | ArcEntity, point: Point2D) -> float:
    if isinstance(segment, LineEntity):
        dx = segment.end_mm[0] - segment.start_mm[0]
        dy = segment.end_mm[1] - segment.start_mm[1]
        return ((point[0] - segment.start_mm[0]) * dx + (point[1] - segment.start_mm[1]) * dy) / (
            dx * dx + dy * dy
        )
    angle = math.degrees(
        math.atan2(point[1] - segment.center_mm[1], point[0] - segment.center_mm[0])
    )
    direction = 1.0 if segment.sweep_angle_deg > 0 else -1.0
    offset = (direction * (angle - segment.start_angle_deg)) % 360.0
    if offset > 360.0 - 1e-8:
        offset = 0.0
    return offset / abs(segment.sweep_angle_deg)


def _segment_tangent(segment: LineEntity | ArcEntity, ratio: float) -> Point2D:
    if isinstance(segment, LineEntity):
        dx = segment.end_mm[0] - segment.start_mm[0]
        dy = segment.end_mm[1] - segment.start_mm[1]
        length = math.hypot(dx, dy)
        return dx / length, dy / length
    angle = math.radians(segment.start_angle_deg + ratio * segment.sweep_angle_deg)
    direction = 1.0 if segment.sweep_angle_deg > 0 else -1.0
    return -direction * math.sin(angle), direction * math.cos(angle)


def _round_mixed_junctions(
    source: PolylineEntity,
    radius: float,
    generated: list[bool],
    *,
    corner_indices: tuple[int, ...] | None = None,
) -> tuple[PolylineEntity, list[bool]]:
    """Round finite line/arc and arc/arc corners without extending their segments."""
    points: list[Point2D] = list(source.points_mm)
    bulges: list[float] = list(source.bulges)
    original_count = len(points)
    indices = (
        corner_indices
        if corner_indices is not None
        else (
            range(original_count - 1, -1, -1) if source.closed else range(original_count - 2, 0, -1)
        )
    )
    for index in indices:
        segments = polyline_curve_segments(
            tuple(points), tuple(bulges), source.closed, source.entity_id
        )
        before_index = (index - 1) % len(segments)
        first, second = segments[before_index], segments[index]
        if isinstance(first, LineEntity) and isinstance(second, LineEntity):
            continue
        incoming, outgoing = _segment_tangent(first, 1), _segment_tangent(second, 0)
        if (
            abs(incoming[0] * outgoing[1] - incoming[1] * outgoing[0]) <= 1e-9
            and incoming[0] * outgoing[0] + incoming[1] * outgoing[1] > 0
        ):
            continue
        # The solver requires unique identities even though both segments belong to one polyline.
        first = replace(first, entity_id=uuid4().hex)
        second = replace(second, entity_id=uuid4().hex)
        first_pick = _segment_point(first, 1.0 - 1e-6)
        second_pick = _segment_point(second, 1e-6)
        try:
            if isinstance(first, LineEntity) and isinstance(second, ArcEntity):
                fillet = line_circle_fillet_notrim(
                    first, second, first_pick, second_pick, radius, uuid4().hex
                )
            elif isinstance(first, ArcEntity) and isinstance(second, LineEntity):
                reversed_fillet = line_circle_fillet_notrim(
                    second, first, second_pick, first_pick, radius, uuid4().hex
                )
                fillet = replace(
                    reversed_fillet,
                    start_angle_deg=reversed_fillet.start_angle_deg
                    + reversed_fillet.sweep_angle_deg,
                    sweep_angle_deg=-reversed_fillet.sweep_angle_deg,
                )
            else:
                assert isinstance(first, ArcEntity) and isinstance(second, ArcEntity)
                fillet = circle_fillet_notrim(
                    first, second, first_pick, second_pick, radius, uuid4().hex
                )
            contact_first, contact_second = _segment_point(fillet, 0), _segment_point(fillet, 1)
            first_ratio = _segment_ratio(first, contact_first)
            second_ratio = _segment_ratio(second, contact_second)
            if not (1e-8 < first_ratio < 1 - 1e-8 and 1e-8 < second_ratio < 1 - 1e-8):
                continue
            if not tangent_on_curves(first, fillet) or not tangent_on_curves(second, fillet):
                continue
            first_bulge = (
                math.tan(math.radians(first.sweep_angle_deg * first_ratio) / 4)
                if isinstance(first, ArcEntity)
                else 0.0
            )
            second_bulge = (
                math.tan(math.radians(second.sweep_angle_deg * (1 - second_ratio)) / 4)
                if isinstance(second, ArcEntity)
                else 0.0
            )
            fillet_bulge = math.tan(math.radians(fillet.sweep_angle_deg) / 4)
            updated_points = points.copy()
            updated_bulges = bulges.copy()
            updated_points[index] = contact_first
            updated_points.insert(index + 1, contact_second)
            updated_bulges[before_index] = first_bulge
            updated_bulges[index] = fillet_bulge
            updated_bulges.insert(index + 1, second_bulge)
            candidate = replace(
                source, points_mm=tuple(updated_points), bulges=tuple(updated_bulges)
            )
        except ValueError:
            continue
        points, bulges = list(candidate.points_mm), list(candidate.bulges)
        second_generated = generated[index]
        generated[index] = True
        generated.insert(index + 1, second_generated)
    return replace(source, points_mm=tuple(points), bulges=tuple(bulges)), generated


def _support_intersections(
    first: LineEntity | ArcEntity, second: LineEntity | ArcEntity
) -> tuple[Point2D, ...]:
    if isinstance(first, LineEntity) and isinstance(second, LineEntity):
        ax, ay = first.end_mm[0] - first.start_mm[0], first.end_mm[1] - first.start_mm[1]
        bx, by = second.end_mm[0] - second.start_mm[0], second.end_mm[1] - second.start_mm[1]
        denominator = ax * by - ay * bx
        if abs(denominator) <= 1e-12 * math.hypot(ax, ay) * math.hypot(bx, by):
            return ()
        dx, dy = second.start_mm[0] - first.start_mm[0], second.start_mm[1] - first.start_mm[1]
        ratio = (dx * by - dy * bx) / denominator
        return ((first.start_mm[0] + ratio * ax, first.start_mm[1] + ratio * ay),)
    if isinstance(second, LineEntity):
        first, second = second, first
    if isinstance(first, LineEntity) and isinstance(second, ArcEntity):
        dx, dy = first.end_mm[0] - first.start_mm[0], first.end_mm[1] - first.start_mm[1]
        ox, oy = first.start_mm[0] - second.center_mm[0], first.start_mm[1] - second.center_mm[1]
        a = dx * dx + dy * dy
        b = 2 * (ox * dx + oy * dy)
        c = ox * ox + oy * oy - second.radius_mm**2
        discriminant = b * b - 4 * a * c
        if discriminant < -1e-10 * max(1.0, b * b, abs(4 * a * c)):
            return ()
        root = math.sqrt(max(0.0, discriminant))
        return tuple(
            (first.start_mm[0] + ratio * dx, first.start_mm[1] + ratio * dy)
            for ratio in ((-b - root) / (2 * a), (-b + root) / (2 * a))
        )
    assert isinstance(first, ArcEntity) and isinstance(second, ArcEntity)
    dx, dy = second.center_mm[0] - first.center_mm[0], second.center_mm[1] - first.center_mm[1]
    distance = math.hypot(dx, dy)
    if (
        distance <= 1e-10
        or distance > first.radius_mm + second.radius_mm + 1e-9
        or distance < abs(first.radius_mm - second.radius_mm) - 1e-9
    ):
        return ()
    along = (first.radius_mm**2 - second.radius_mm**2 + distance**2) / (2 * distance)
    height_squared = first.radius_mm**2 - along**2
    if height_squared < -1e-8:
        return ()
    height = math.sqrt(max(0.0, height_squared))
    base = (first.center_mm[0] + along * dx / distance, first.center_mm[1] + along * dy / distance)
    normal = (-dy / distance * height, dx / distance * height)
    return ((base[0] + normal[0], base[1] + normal[1]), (base[0] - normal[0], base[1] - normal[1]))


def _extended_bulge(
    segment: LineEntity | ArcEntity, point: Point2D, *, incoming: bool
) -> tuple[float, float] | None:
    if isinstance(segment, LineEntity):
        ratio = _segment_ratio(segment, point)
        if (incoming and ratio < 1 - 1e-9) or (not incoming and ratio > 1e-9):
            return None
        return abs(ratio - (1.0 if incoming else 0.0)) * math.dist(
            segment.start_mm, segment.end_mm
        ), 0.0
    angle = math.degrees(
        math.atan2(point[1] - segment.center_mm[1], point[0] - segment.center_mm[0])
    )
    direction = 1.0 if segment.sweep_angle_deg > 0 else -1.0
    boundary = (
        segment.start_angle_deg + segment.sweep_angle_deg if incoming else segment.start_angle_deg
    )
    delta = (direction * (angle - boundary) if incoming else direction * (boundary - angle)) % 360.0
    if delta > 360 - 1e-8:
        delta = 0.0
    if delta >= 180 or abs(segment.sweep_angle_deg) + delta >= 360 - 1e-8:
        return None
    sweep = segment.sweep_angle_deg + direction * delta
    return math.radians(delta) * segment.radius_mm, math.tan(math.radians(sweep) / 4)


def _remove_existing_fillet_arcs(
    source: PolylineEntity,
    *,
    include_curved_neighbours: bool = False,
    replacement_radius: float | None = None,
) -> tuple[PolylineEntity, list[bool]]:
    """Restore converging line corners or replace feasible smoothly joined arcs."""
    points = list(source.points_mm)
    bulges = list(source.bulges)
    generated = [False] * len(bulges)
    replaced_indices: set[int] = set()
    while any(bulges):
        segments = polyline_curve_segments(
            tuple(points), tuple(bulges), source.closed, source.entity_id
        )
        removed = False
        for index, arc in enumerate(segments):
            if not isinstance(arc, ArcEntity):
                continue
            if replacement_radius is not None and index in replaced_indices:
                continue
            if source.closed and len(points) <= 3 and replacement_radius is None:
                continue
            if not source.closed and (index == 0 or index == len(segments) - 1):
                continue
            first = segments[(index - 1) % len(segments)]
            second = segments[(index + 1) % len(segments)]
            if not include_curved_neighbours and (
                not isinstance(first, LineEntity) or not isinstance(second, LineEntity)
            ):
                continue
            remove_between_lines = (
                replacement_radius is None
                and isinstance(first, LineEntity)
                and isinstance(second, LineEntity)
            )
            if not remove_between_lines:
                if not tangent_on_curves(first, arc) or not tangent_on_curves(second, arc):
                    continue
                first_tangent = _segment_tangent(first, 1)
                arc_start_tangent = _segment_tangent(arc, 0)
                arc_end_tangent = _segment_tangent(arc, 1)
                second_tangent = _segment_tangent(second, 0)
                if (
                    first_tangent[0] * arc_start_tangent[0]
                    + first_tangent[1] * arc_start_tangent[1]
                    < 1 - 1e-8
                    or arc_end_tangent[0] * second_tangent[0]
                    + arc_end_tangent[1] * second_tangent[1]
                    < 1 - 1e-8
                ):
                    continue
            if replacement_radius is not None and math.isclose(
                arc.radius_mm, replacement_radius, rel_tol=1e-12, abs_tol=1e-10
            ):
                replaced_indices.add(index)
                continue
            candidates: list[tuple[float, Point2D, float, float]] = []
            for corner in _support_intersections(first, second):
                incoming = _extended_bulge(first, corner, incoming=True)
                outgoing = _extended_bulge(second, corner, incoming=False)
                if incoming is not None and outgoing is not None:
                    candidates.append((incoming[0] + outgoing[0], corner, incoming[1], outgoing[1]))
            candidates.sort(key=lambda item: item[0])
            if not candidates:
                continue
            if (
                len(candidates) > 1
                and abs(candidates[0][0] - candidates[1][0]) <= 1e-8
                and math.dist(candidates[0][1], candidates[1][1]) > 1e-8
            ):
                continue
            _, corner, incoming_bulge, outgoing_bulge = candidates[0]
            if replacement_radius is not None:
                try:
                    local = PolylineEntity(
                        source.entity_id,
                        (_segment_point(first, 0), corner, _segment_point(second, 1)),
                        construction=source.construction,
                        layer_name=source.layer_name,
                        bulges=(incoming_bulge, outgoing_bulge),
                    )
                    local_points, local_bulges = polyline_fillet_trimmed_segments(
                        local, replacement_radius
                    )
                except ValueError:
                    continue
                if len(local_points) != 4:
                    continue
                points[index] = local_points[1]
                points[(index + 1) % len(points)] = local_points[2]
                bulges[(index - 1) % len(bulges)] = local_bulges[0]
                bulges[index] = local_bulges[1]
                bulges[(index + 1) % len(bulges)] = local_bulges[2]
                generated[index] = True
                replaced_indices.add(index)
                removed = True
                break
            if source.closed and index == len(points) - 1:
                points = [*points[1:], points[0]]
                bulges = [*bulges[1:], bulges[0]]
                index -= 1
            previous = (index - 1) % len(bulges)
            bulges[previous] = incoming_bulge
            points[index] = corner
            del points[index + 1]
            bulges[index] = outgoing_bulge
            del bulges[index + 1]
            removed = True
            break
        if not removed:
            break
    result = replace(source, points_mm=tuple(points), bulges=tuple(bulges))
    if replacement_radius is None:
        generated = [False] * len(bulges)
    return result, generated


def chamfer_joined_paths(
    first: LineEntity | PolylineEntity,
    first_index: int | None,
    second: LineEntity | PolylineEntity,
    second_index: int | None,
    first_pick: Point2D,
    second_pick: Point2D,
    first_distance: float,
    second_distance: float,
    identity: str,
    *,
    angle_deg: float | None = None,
    trim: bool = True,
    layer_name: str = "0",
) -> tuple[PolylineEntity | None, LineEntity | None]:
    """Chamfer straight segments of two paths and join their retained branches."""
    from mycad.core.line_chamfer import line_chamfer

    if (
        first.entity_id == second.entity_id
        or not isinstance(first, PolylineEntity)
        and not isinstance(second, PolylineEntity)
    ):
        raise ValueError("请选择两个不同对象，且至少一个是多段线。")

    def curve(source: LineEntity | PolylineEntity, index: int | None) -> LineEntity:
        if isinstance(source, LineEntity):
            return source
        count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
        if index is None or isinstance(index, bool) or not 0 <= index < count:
            raise ValueError("请选择有效的多段线段。")
        selected = polyline_curve_segments(
            source.points_mm,
            source.bulges or (0.0,) * count,
            source.closed,
            source.entity_id,
            construction=source.construction,
            layer_name=source.layer_name,
        )[index]
        if not isinstance(selected, LineEntity):
            raise ValueError("倒角仅支持直线段。")
        return selected

    first_curve, second_curve = curve(first, first_index), curve(second, second_index)
    a, b, edge = line_chamfer(
        first_curve,
        second_curve,
        first_pick,
        second_pick,
        first_distance,
        second_distance,
        identity,
        angle_deg=angle_deg,
        trim=trim,
        layer_name=layer_name,
    )
    if not trim:
        return None, edge
    if edge is None:
        intersections = _support_intersections(first_curve, second_curve)
        if len(intersections) != 1:
            raise ValueError("无法确定倒角交点。")
        first_contact = second_contact = intersections[0]
    else:
        first_contact, second_contact = edge.start_mm, edge.end_mm

    def branch(
        source: LineEntity | PolylineEntity,
        index: int | None,
        selected: LineEntity,
        result: LineEntity,
        contact: Point2D,
        *,
        toward: bool,
    ) -> tuple[tuple[Point2D, ...], tuple[float, ...]]:
        if isinstance(source, PolylineEntity):
            assert index is not None
            points, bulges, ends = _retained_polyline_branch(
                source, index, selected, result, contact
            )
            if ends != toward:
                return tuple(reversed(points)), tuple(-value for value in reversed(bulges))
            return points, bulges
        if math.dist(result.start_mm, contact) <= 1e-8:
            far = result.end_mm
        elif math.dist(result.end_mm, contact) <= 1e-8:
            far = result.start_mm
        else:
            raise ValueError("无法确定倒角保留侧。")
        return ((far, contact) if toward else (contact, far)), (0.0,)

    first_points, first_bulges = branch(
        first, first_index, first_curve, a, first_contact, toward=True
    )
    second_points, second_bulges = branch(
        second, second_index, second_curve, b, second_contact, toward=False
    )
    points = (
        (*first_points, *second_points) if edge is not None else (*first_points, *second_points[1:])
    )
    bulges = (
        (*first_bulges, 0.0, *second_bulges)
        if edge is not None
        else (*first_bulges, *second_bulges)
    )
    source = first if isinstance(first, PolylineEntity) else second
    assert isinstance(source, PolylineEntity)
    return replace(source, points_mm=points, bulges=bulges, closed=False), edge
