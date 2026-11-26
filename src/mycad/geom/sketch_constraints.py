# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""PlaneGCS adapter for neutral sketch constraints and disposable previews."""

from __future__ import annotations

import importlib.metadata
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast

from mycad.core.cross_sketch_tangency import tangent_endpoints_satisfied, tangent_entity_curve
from mycad.core.polyline_curves import bulge_arc, polyline_arc_segment
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_constraints import (
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.geom.sketch_branches import detect_branch_changes

if TYPE_CHECKING:
    from planegcs.sketch import ArcId, CircleId, LineId, PointId
    from planegcs.sketch import Sketch as PlaneGcsSketch

_SOLVER_ID = "planegcs"
_LINEAR_ABSOLUTE_TOLERANCE_MM = 1e-12
_LINEAR_RELATIVE_TOLERANCE = 1e-9
_RELATION_LINEAR_ABSOLUTE_TOLERANCE_MM = 1e-7
_ANGULAR_TOLERANCE_DEG = 1e-7

type EndpointLink = tuple[
    str,
    SketchGeometryReference,
    Literal["start", "end"],
    SketchGeometryReference,
    Literal["start", "end"] | None,
]


@dataclass(frozen=True, slots=True)
class _EntityBinding:
    entity: SketchEntity
    points: tuple[int, ...]
    lines: tuple[int, ...] = ()
    line_points: tuple[tuple[int, int], ...] = ()
    circle_id: int | None = None
    arc_id: int | None = None
    fixed: bool = False
    segment_arcs: tuple[int | None, ...] = ()
    segment_centers: tuple[int | None, ...] = ()


@dataclass(frozen=True, slots=True)
class _EditAnchor:
    points: tuple[int, ...]
    position: tuple[float, float]


def _installed_solver_version() -> str | None:
    try:
        return importlib.metadata.version(_SOLVER_ID)
    except importlib.metadata.PackageNotFoundError:
        return None


def _unsupported_curved_polyline_constraint(
    sketch: Sketch, additional: tuple[SketchConstraint, ...] = ()
) -> bool:
    curved_entities = {
        entity.entity_id: entity
        for entity in sketch.entities
        if isinstance(entity, PolylineEntity) and entity.bulges
    }
    return any(
        reference.entity_id in curved_entities
        and not (
            (
                constraint.kind in ("fixed", "coincident", "distance")
                and reference.kind in ("start", "end", "vertex")
            )
            or (
                constraint.kind
                in ("radius", "diameter", "arc_length", "tangent", "concentric", "equal")
                and reference.kind == "segment"
            )
            or (
                constraint.kind
                in ("horizontal", "vertical", "parallel", "perpendicular", "length", "angle")
                and _is_line_reference(curved_entities[reference.entity_id], reference)
            )
        )
        for constraint in (*sketch.constraints, *additional)
        for reference in constraint.references
    )


def _curved_polyline_degrees_of_freedom(sketch: Sketch, bindings: dict[str, _EntityBinding]) -> int:
    return sum(
        (0 if bindings[entity.entity_id].points else 2 * len(entity.points_mm))
        + (0 if bindings[entity.entity_id].segment_arcs else sum(b != 0 for b in entity.bulges))
        for entity in sketch.entities
        if isinstance(entity, PolylineEntity)
        and entity.bulges
        and not sketch.layers.get(entity.layer_name).locked
    )


def _local_endpoint_links(
    sketch: Sketch, additional: SketchConstraint | None = None
) -> tuple[EndpointLink, ...]:
    links: list[EndpointLink] = []
    for constraint in (*sketch.constraints, *((additional,) if additional is not None else ())):
        endpoints = (constraint.first_endpoint, constraint.second_endpoint)
        if not constraint.driving or not any(endpoint is not None for endpoint in endpoints):
            continue
        references = constraint.references
        curves = tuple(
            tangent_entity_curve(_reference_entity(sketch, ref), ref.index) for ref in references
        )
        index = next(
            (
                i
                for i, curve in enumerate(curves)
                if endpoints[i] is not None and isinstance(curve, ArcEntity)
            ),
            None,
        )
        if index is None:
            raise ValueError("相切端点连接需要指定圆弧端点。")
        endpoint = endpoints[index]
        if endpoint is None:
            raise ValueError("相切端点连接需要指定圆弧端点。")
        links.append(
            (
                constraint.constraint_id,
                references[index],
                endpoint,
                references[1 - index],
                endpoints[1 - index],
            )
        )
    return tuple(links)


def _apply_endpoint_links(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    active_links: tuple[EndpointLink, ...],
) -> None:
    for _, arc_ref, endpoint, other_ref, other_endpoint in active_links:
        point_id, center_id = _arc_endpoint_and_center(arc_ref, endpoint, bindings)
        point = cast("PointId", point_id)
        other = _binding(other_ref, bindings)
        if other_endpoint is not None:
            if other_ref.kind == "segment" and other_ref.index is not None:
                edge = other.line_points[other_ref.index]
                other_point = edge[0 if other_endpoint == "start" else 1]
            elif isinstance(other.entity, LineEntity):
                other_point = other.points[0 if other_endpoint == "start" else 1]
            elif isinstance(other.entity, ArcEntity):
                other_point = other.points[1 if other_endpoint == "start" else 2]
            else:
                raise ValueError("相切连接的另一端点无效。")
            solver.coincident(point, cast("PointId", other_point))
            if _is_line_reference(other.entity, other_ref):
                radius_line = solver.add_line(cast("PointId", center_id), point)
                solver.perpendicular(radius_line, cast("LineId", _line_for(other_ref, bindings)))
            else:
                _, other_center = _arc_endpoint_and_center(other_ref, other_endpoint, bindings)
                center_line = solver.add_line(
                    cast("PointId", center_id), cast("PointId", other_center)
                )
                solver.point_on_line(point, center_line)
        elif _is_line_reference(other.entity, other_ref):
            radius_line = solver.add_line(cast("PointId", center_id), point)
            solver.perpendicular(radius_line, cast("LineId", _line_for(other_ref, bindings)))
        else:
            if other_ref.kind == "segment" and other_ref.index is not None:
                center = other.segment_centers[other_ref.index]
                if center is None:
                    raise ValueError("相切圆弧段的圆心不存在。")
            else:
                _curve_for(other_ref, bindings)
                center = other.points[0]
            center_line = solver.add_line(cast("PointId", center_id), cast("PointId", center))
            solver.point_on_line(point, center_line)


def solve_sketch_constraint(
    sketch: Sketch,
    new_constraint: SketchConstraint,
    *,
    projection_axes: Mapping[str, tuple[float, float]] | None = None,
    endpoint_links: tuple[EndpointLink, ...] = (),
) -> SketchConstraintSolveResult:
    """Solve a candidate from the current accepted geometry without mutating it."""
    if _unsupported_curved_polyline_constraint(sketch, (new_constraint,)):
        return SketchConstraintSolveResult(
            "invalid", None, None, message="含圆弧的多段线暂不支持约束求解。"
        )
    locked = (
        _locked_reference_message(sketch, new_constraint.references)
        if new_constraint.driving
        else ""
    )
    if locked:
        return SketchConstraintSolveResult("invalid", None, None, message=locked)
    solver_version = _installed_solver_version()
    try:
        from planegcs import Sketch as PlaneSketch
        from planegcs import SolveStatus
    except ModuleNotFoundError:
        return SketchConstraintSolveResult(
            "unavailable",
            None,
            None,
            message="草图约束需要安装 sketch-constraints 可选后端。",
            solver_version=solver_version,
        )
    if solver_version is None:
        return SketchConstraintSolveResult(
            "unavailable",
            None,
            None,
            message="找不到 PlaneGCS 版本信息；本次约束没有提交。",
        )

    if any(item.constraint_id == new_constraint.constraint_id for item in sketch.constraints):
        return SketchConstraintSolveResult(
            "invalid",
            None,
            None,
            message=f"约束身份 {new_constraint.constraint_id!r} 已存在。",
            solver_version=solver_version,
        )

    if not new_constraint.driving:
        if new_constraint.kind not in (
            "length",
            "distance",
            "angle",
            "radius",
            "diameter",
            "arc_length",
        ):
            return SketchConstraintSolveResult(
                "invalid",
                None,
                None,
                message="只有尺寸约束可以作为非驱动参考尺寸。",
                solver_version=solver_version,
            )
        try:
            measured = _measure_dimension(sketch, new_constraint)
            measured_constraint = replace(new_constraint, value=measured)
            degrees_of_freedom = _current_degrees_of_freedom(sketch, PlaneSketch)
            measured_sketch = sketch.with_constraint(measured_constraint, sketch.entities)
        except (KeyError, TypeError, ValueError) as exc:
            return SketchConstraintSolveResult(
                "invalid",
                None,
                None,
                message=str(exc),
                solver_version=solver_version,
            )
        return SketchConstraintSolveResult(
            "success",
            measured_sketch,
            degrees_of_freedom,
            solver_version=solver_version,
        )

    solver = PlaneSketch()
    bindings: dict[str, _EntityBinding] = {}
    tag_to_constraint: dict[int, str] = {}
    try:
        active_ids = {item.constraint_id for item in sketch.constraints} | {
            new_constraint.constraint_id
        }
        active_links = tuple(
            link for link in endpoint_links if link[0] in active_ids
        ) + _local_endpoint_links(sketch, new_constraint)
        bindings = _sketch_bindings(
            solver,
            sketch,
            new_constraint.references,
            free_arc_ids={
                ref.entity_id
                for link in active_links
                for ref in (link[1], *((link[3],) if link[4] is not None else ()))
            },
        )
        for constraint in (item for item in sketch.constraints if item.driving):
            tags = _add_constraint(
                solver,
                bindings,
                constraint,
                projection_axis=None
                if projection_axes is None
                else projection_axes.get(constraint.constraint_id),
            )
            for tag in tags:
                tag_to_constraint[tag] = constraint.constraint_id
        anchor_checks = _apply_edit_anchor(solver, bindings, sketch, new_constraint)
        direction = (
            new_constraint.projection_axis
            if projection_axes is None
            else projection_axes.get(new_constraint.constraint_id, new_constraint.projection_axis)
        )
        if direction is not None and new_constraint.axis.startswith("ordinate_"):
            _seed_signed_projection(solver, bindings, new_constraint, direction)
        for tag in _add_constraint(solver, bindings, new_constraint, projection_axis=direction):
            tag_to_constraint[tag] = new_constraint.constraint_id
        _apply_endpoint_links(solver, bindings, active_links)
        status = solver.solve()
        diagnosis = solver.diagnose()
        dof = int(solver.dof()) + _curved_polyline_degrees_of_freedom(sketch, bindings)
        conflicting = tuple(
            sorted(
                {
                    tag_to_constraint[int(info.tag)]
                    for info in diagnosis.conflicting_info
                    if int(info.tag) in tag_to_constraint
                }
            )
        )
        redundant = tuple(
            sorted(
                {
                    tag_to_constraint[int(info.tag)]
                    for info in (*diagnosis.redundant_info, *diagnosis.partially_redundant_info)
                    if int(info.tag) in tag_to_constraint
                }
            )
        )
        if status not in (SolveStatus.Success, SolveStatus.Converged):
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                conflicting,
                redundant,
                "PlaneGCS 未能找到有效解；当前草图保持不变。",
                solver_version=solver_version,
            )
        try:
            solved_entities = tuple(
                _read_solved_entity(solver, bindings[item.entity_id]) for item in sketch.entities
            )
            solved_sketch = refresh_reference_dimensions(
                sketch.with_constraint(new_constraint, solved_entities)
            )
            _validate_edit_anchor(solver, anchor_checks, sketch)
            _validate_projection_direction(
                sketch,
                solved_sketch,
                new_constraint,
                axis_vector=direction,
            )
        except (TypeError, ValueError) as exc:
            related = _related_constraint_ids(sketch.constraints, new_constraint)
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                tuple(sorted(set(conflicting) | set(related))),
                redundant,
                f"求解结果会产生无效草图几何：{exc}",
                solver_version=solver_version,
            )
        violations = _dimension_violations(solved_sketch, projection_axes=projection_axes)
        if violations:
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                tuple(item[0] for item in violations),
                redundant,
                "求解尺寸残差超过 MyCAD 容差："
                + "；".join(
                    f"{identity[:8]} 残差 {error:.6g}，容差 {tolerance:.6g}"
                    for identity, error, tolerance in violations
                ),
                solver_version=solver_version,
            )
        relation_violations = _relation_violations(sketch, solved_sketch)
        if relation_violations:
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                tuple(item[0] for item in relation_violations),
                redundant,
                "求解几何关系残差超过 MyCAD 容差："
                + "；".join(
                    f"{identity[:8]} 残差 {error:.6g}，容差 {tolerance:.6g}"
                    for identity, error, tolerance in relation_violations
                ),
                solver_version=solver_version,
            )
    except (KeyError, TypeError, ValueError) as exc:
        return SketchConstraintSolveResult(
            "invalid",
            None,
            None,
            message=str(exc),
            solver_version=solver_version,
        )
    if anchor_checks:
        dof = _current_degrees_of_freedom(
            solved_sketch, PlaneSketch, projection_axes=projection_axes
        )
    return SketchConstraintSolveResult(
        "success",
        solved_sketch,
        dof,
        conflicting,
        redundant,
        solver_version=solver_version,
        branch_changes=detect_branch_changes(sketch, solved_sketch),
    )


def _auto_anchor_is_grounded(sketch: Sketch, candidate: SketchConstraint) -> bool:
    """Respect fixed geometry anywhere in the active constraint component."""
    connected = {ref.entity_id for ref in candidate.references}
    changed = True
    while changed:
        previous = len(connected)
        for relation in sketch.constraints:
            ids = {ref.entity_id for ref in relation.references}
            if relation.driving and ids.intersection(connected):
                connected.update(ids)
        changed = len(connected) != previous
    return any(
        entity.entity_id in connected and sketch.layers.get(entity.layer_name).locked
        for entity in sketch.entities
    ) or any(
        c.driving and c.kind == "fixed" and c.references[0].entity_id in connected
        for c in sketch.constraints
    )


def _seed_signed_projection(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    constraint: SketchConstraint,
    direction: tuple[float, float],
) -> None:
    """Choose the signed branch before solving an absolute point-line distance."""
    first = constraint.references[0]
    start, end = (
        _line_points(first, bindings)
        if constraint.kind == "length"
        else (_point_for(first, bindings), _point_for(constraint.references[1], bindings))
    )
    a, b = solver.get_point(cast("PointId", start)), solver.get_point(cast("PointId", end))
    current = (b[0] - a[0]) * direction[0] + (b[1] - a[1]) * direction[1]
    target = _constraint_value(constraint)
    if target == 0 or current * target > 0:
        return
    change = target - current
    if constraint.anchor_mode == "symmetric":
        adjustments = ((start, -change / 2), (end, change / 2))
    elif constraint.anchor_mode == "end":
        adjustments = ((start, -change),)
    else:
        adjustments = ((end, change),)
    for point_id, amount in adjustments:
        parameters = solver.get_point_param_ids(cast("PointId", point_id))
        for parameter, component in zip(parameters, direction, strict=True):
            solver.set_param(parameter, solver.get_param(parameter) + amount * component)


def _apply_edit_anchor(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    sketch: Sketch,
    candidate: SketchConstraint,
) -> tuple[_EditAnchor, ...]:
    """Temporary edit gauges; never add persistent relations to the sketch."""
    if candidate.anchor_mode == "auto" and _auto_anchor_is_grounded(sketch, candidate):
        return ()
    reference = candidate.references[0]
    checks: list[_EditAnchor] = []
    if candidate.kind in ("length", "distance"):
        start, end = (
            _line_points(reference, bindings)
            if candidate.kind == "length"
            else (_point_for(reference, bindings), _point_for(candidate.references[1], bindings))
        )
        if candidate.anchor_mode == "symmetric":
            a, b = solver.get_point(cast("PointId", start)), solver.get_point(cast("PointId", end))
            center = solver.add_point_from_params(
                solver.add_fixed_param((a[0] + b[0]) / 2),
                solver.add_fixed_param((a[1] + b[1]) / 2),
            )
            solver.symmetric_point(cast("PointId", start), cast("PointId", end), center)
            # Verify the actual midpoint independently after solving.
            return (_EditAnchor((start, end), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)),)
        points = (end,) if candidate.anchor_mode == "end" else (start,)
    elif candidate.kind in ("radius", "diameter", "arc_length"):
        points = (_center_for(reference, bindings),)
    elif candidate.kind == "angle":
        points = _line_points(reference, bindings)
    else:
        return ()
    for point in points:
        current = solver.get_point(cast("PointId", point))
        position = (float(current[0]), float(current[1]))
        solver.fix_point(cast("PointId", point), *position)
        checks.append(_EditAnchor((point,), position))
    return tuple(checks)


def _validate_edit_anchor(
    solver: PlaneGcsSketch, checks: tuple[_EditAnchor, ...], sketch: Sketch
) -> None:
    tolerance = max(
        _RELATION_LINEAR_ABSOLUTE_TOLERANCE_MM,
        _sketch_linear_scale(sketch) * _LINEAR_RELATIVE_TOLERANCE,
    )
    for anchor in checks:
        points = tuple(solver.get_point(cast("PointId", point)) for point in anchor.points)
        actual = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
        if math.dist(actual, anchor.position) > tolerance:
            raise ValueError("固定端或中心对称与已有约束冲突，草图保持原状")


def _validate_projection_direction(
    before: Sketch,
    after: Sketch,
    candidate: SketchConstraint,
    *,
    axis_vector: tuple[float, float] | None = None,
) -> None:
    if candidate.kind not in ("length", "distance") or candidate.axis == "aligned":
        return
    first = candidate.references[0]
    axis = 0 if candidate.axis in ("horizontal", "ordinate_x") else 1

    def delta(sketch: Sketch) -> float:
        a, b = (
            _reference_line(sketch, first)
            if candidate.kind == "length"
            else (
                _reference_point(sketch, first),
                _reference_point(sketch, candidate.references[1]),
            )
        )
        return (
            b[axis] - a[axis]
            if axis_vector is None
            else (b[0] - a[0]) * axis_vector[0] + (b[1] - a[1]) * axis_vector[1]
        )

    expected = _constraint_value(candidate)
    if not candidate.axis.startswith("ordinate_") and delta(before) < 0:
        expected = -expected
    tolerance = max(
        _LINEAR_ABSOLUTE_TOLERANCE_MM, _sketch_linear_scale(after) * _LINEAR_RELATIVE_TOLERANCE
    )
    if abs(delta(after) - expected) > tolerance:
        raise ValueError("尺寸投影方向不符合当前图形，草图保持原状")


def refresh_reference_dimensions(sketch: Sketch) -> Sketch:
    """Measure reference annotations from accepted geometry, without solving."""
    return replace(
        sketch,
        constraints=tuple(
            replace(item, value=measure_sketch_dimension(sketch, item))
            if not item.driving
            else item
            for item in sketch.constraints
        ),
    )


def solve_sketch_constraint_update(
    sketch: Sketch, constraint: SketchConstraint
) -> SketchConstraintSolveResult:
    """Solve a dimension revision from current geometry and preserve relation identities."""
    try:
        sketch.with_updated_constraint(constraint, sketch.entities)
    except ValueError as exc:
        return SketchConstraintSolveResult("invalid", None, None, message=str(exc))
    seed = replace(
        sketch,
        constraints=tuple(
            item for item in sketch.constraints if item.constraint_id != constraint.constraint_id
        ),
    )
    result = solve_sketch_constraint(seed, constraint)
    if result.status != "success" or result.sketch is None:
        return result
    solved_constraint = next(
        item for item in result.sketch.constraints if item.constraint_id == constraint.constraint_id
    )
    updated = sketch.with_updated_constraint(solved_constraint, result.sketch.entities)
    return replace(result, sketch=refresh_reference_dimensions(updated))


def solve_sketch_drag(
    sketch: Sketch,
    reference: SketchGeometryReference,
    target_mm: tuple[float, float],
    *,
    _lock_target: bool = True,
) -> SketchConstraintSolveResult:
    """Solve a transient point drag while preserving accepted driving constraints."""
    locked = _locked_reference_message(sketch, (reference,))
    if locked:
        return SketchConstraintSolveResult("invalid", None, None, message=locked)
    if _unsupported_curved_polyline_constraint(sketch):
        return SketchConstraintSolveResult(
            "invalid", None, None, message="含圆弧的多段线暂不支持约束拖动。"
        )
    solver_version = _installed_solver_version()
    try:
        from planegcs import Sketch as PlaneSketch
        from planegcs import SolveStatus
    except ModuleNotFoundError:
        return SketchConstraintSolveResult(
            "unavailable",
            None,
            None,
            message="草图拖动需要安装 sketch-constraints 可选后端。",
            solver_version=solver_version,
        )
    if solver_version is None:
        return SketchConstraintSolveResult(
            "unavailable",
            None,
            None,
            message="找不到 PlaneGCS 版本信息；本次拖动没有应用。",
        )
    if (
        len(target_mm) != 2
        or any(isinstance(value, bool) for value in target_mm)
        or not all(math.isfinite(value) for value in target_mm)
    ):
        return SketchConstraintSolveResult(
            "invalid",
            None,
            None,
            message="拖动目标必须是两个有限坐标。",
            solver_version=solver_version,
        )

    target_entity = next(
        (entity for entity in sketch.entities if entity.entity_id == reference.entity_id), None
    )
    if (
        isinstance(target_entity, PolylineEntity)
        and target_entity.bulges
        and not any(
            ref.entity_id == target_entity.entity_id
            for constraint in sketch.constraints
            for ref in constraint.references
        )
    ):
        from mycad.core.sketch_edit import move_sketch_handle

        try:
            entities = move_sketch_handle(sketch.entities, reference, target_mm)
            revised = validate_sketch_revision_geometry(sketch, replace(sketch, entities=entities))
            dof = _current_degrees_of_freedom(revised, PlaneSketch)
        except (KeyError, TypeError, ValueError) as exc:
            return SketchConstraintSolveResult(
                "invalid", None, None, message=str(exc), solver_version=solver_version
            )
        return SketchConstraintSolveResult("success", revised, dof, solver_version=solver_version)

    projected_target = [float(target_mm[0]), float(target_mm[1])]
    for constraint in sketch.constraints:
        if not constraint.driving:
            continue
        if constraint.kind == "fixed" and constraint.references[0] == reference:
            return SketchConstraintSolveResult(
                "failed",
                None,
                None,
                (constraint.constraint_id,),
                message="该控制点已有固定约束；请先编辑或删除约束。",
                solver_version=solver_version,
            )
        if constraint.kind not in ("horizontal", "vertical"):
            continue
        constrained_line = constraint.references[0]
        if constrained_line.entity_id != reference.entity_id:
            continue
        entity = next(
            (item for item in sketch.entities if item.entity_id == constrained_line.entity_id),
            None,
        )
        anchor: tuple[float, float] | None = None
        if isinstance(entity, LineEntity) and constrained_line.kind == "geometry":
            if reference.kind == "start":
                anchor = entity.end_mm
            elif reference.kind == "end":
                anchor = entity.start_mm
        elif isinstance(entity, PolylineEntity) and constrained_line.kind == "segment":
            segment_index = constrained_line.index
            if segment_index is not None:
                segment_count = (
                    len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                )
                if segment_index < segment_count and reference.kind == "vertex":
                    next_index = (segment_index + 1) % len(entity.points_mm)
                    if reference.index == segment_index:
                        anchor = entity.points_mm[next_index]
                    elif reference.index == next_index:
                        anchor = entity.points_mm[segment_index]
        if anchor is not None:
            axis = 1 if constraint.kind == "horizontal" else 0
            projected_target[axis] = anchor[axis]

    solver = PlaneSketch()
    bindings: dict[str, _EntityBinding] = {}
    tag_to_constraint: dict[int, str] = {}
    try:
        active_links = _local_endpoint_links(sketch)
        bindings = _sketch_bindings(
            solver,
            sketch,
            (reference,),
            free_arc_ids={
                ref.entity_id
                for link in active_links
                for ref in (link[1], *((link[3],) if link[4] is not None else ()))
            },
        )
        for constraint in sketch.constraints:
            if not constraint.driving:
                continue
            tags = _add_constraint(solver, bindings, constraint)
            for tag in tags:
                tag_to_constraint[tag] = constraint.constraint_id
        _apply_endpoint_links(solver, bindings, active_links)
        point_id = _point_for(reference, bindings)
        x_param, y_param = solver.get_point_param_ids(cast("PointId", point_id))
        solver.set_param(x_param, projected_target[0])
        solver.set_param(y_param, projected_target[1])
        if _lock_target:
            solver.fix_point(
                cast("PointId", point_id), projected_target[0], projected_target[1], driving=True
            )
        status = solver.solve()
        diagnosis = solver.diagnose()
        dof = int(solver.dof()) + _curved_polyline_degrees_of_freedom(sketch, bindings)
        conflicting = tuple(
            sorted(
                {
                    tag_to_constraint[int(info.tag)]
                    for info in diagnosis.conflicting_info
                    if int(info.tag) in tag_to_constraint
                }
            )
        )
        redundant = tuple(
            sorted(
                {
                    tag_to_constraint[int(info.tag)]
                    for info in (*diagnosis.redundant_info, *diagnosis.partially_redundant_info)
                    if int(info.tag) in tag_to_constraint
                }
            )
        )
        if status not in (SolveStatus.Success, SolveStatus.Converged):
            if _lock_target:
                return solve_sketch_drag(sketch, reference, target_mm, _lock_target=False)
            related_ids = tuple(
                sorted(
                    {
                        constraint.constraint_id
                        for constraint in sketch.constraints
                        if any(
                            item.entity_id == reference.entity_id for item in constraint.references
                        )
                    }
                )
            )
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                tuple(sorted(set(conflicting) | set(related_ids))),
                redundant,
                "拖动位置与现有草图约束冲突；几何保持原状。",
                solver_version=solver_version,
            )
        solved_entities = tuple(
            _read_solved_entity(solver, bindings[item.entity_id]) for item in sketch.entities
        )
        provisional = Sketch(
            sketch.sketch_id,
            sketch.frame,
            solved_entities,
            sketch.constraints,
            sketch.layers,
            sketch.support_face,
        )
        solved_constraints = tuple(
            replace(constraint, value=_measure_dimension(provisional, constraint))
            if not constraint.driving
            and constraint.kind
            in ("length", "distance", "angle", "radius", "diameter", "arc_length")
            else constraint
            for constraint in sketch.constraints
        )
        solved_sketch = Sketch(
            sketch.sketch_id,
            sketch.frame,
            solved_entities,
            solved_constraints,
            sketch.layers,
            sketch.support_face,
        )
        if _lock_target and math.dist(
            _reference_point(solved_sketch, reference), projected_target
        ) > max(
            _RELATION_LINEAR_ABSOLUTE_TOLERANCE_MM,
            _sketch_linear_scale(solved_sketch) * _LINEAR_RELATIVE_TOLERANCE,
        ):
            return solve_sketch_drag(sketch, reference, target_mm, _lock_target=False)
        dimension_violations = _dimension_violations(solved_sketch)
        relation_violations = _relation_violations(sketch, solved_sketch)
        if dimension_violations or relation_violations:
            if _lock_target:
                return solve_sketch_drag(sketch, reference, target_mm, _lock_target=False)
            violation_ids = tuple(
                sorted(
                    {
                        identity
                        for identity, _error, _tolerance in (
                            *dimension_violations,
                            *relation_violations,
                        )
                    }
                )
            )
            return SketchConstraintSolveResult(
                "failed",
                None,
                dof,
                violation_ids,
                redundant,
                "求解结果未满足现有尺寸或关系容差；几何保持原状。",
                solver_version=solver_version,
            )
    except (KeyError, TypeError, ValueError) as exc:
        return SketchConstraintSolveResult(
            "invalid", None, None, message=str(exc), solver_version=solver_version
        )
    return SketchConstraintSolveResult(
        "success",
        solved_sketch,
        dof,
        conflicting,
        redundant,
        solver_version=solver_version,
        branch_changes=detect_branch_changes(sketch, solved_sketch),
    )


def _related_constraint_ids(
    constraints: tuple[SketchConstraint, ...], candidate: SketchConstraint
) -> tuple[str, ...]:
    """Name accepted constraints sharing candidate geometry when output is invalid."""
    entity_ids = {reference.entity_id for reference in candidate.references}
    related = [candidate.constraint_id]
    related.extend(
        item.constraint_id
        for item in constraints
        if entity_ids.intersection(reference.entity_id for reference in item.references)
    )
    return tuple(related)


def _current_degrees_of_freedom(
    sketch: Sketch,
    solver_type: type[PlaneGcsSketch],
    *,
    projection_axes: Mapping[str, tuple[float, float]] | None = None,
) -> int:
    """Diagnose accepted driving relations without changing their coordinates."""
    solver = solver_type()
    links = _local_endpoint_links(sketch)
    bindings = _sketch_bindings(
        solver,
        sketch,
        free_arc_ids={
            ref.entity_id
            for link in links
            for ref in (link[1], *((link[3],) if link[4] is not None else ()))
        },
    )
    for constraint in sketch.constraints:
        if constraint.driving:
            _add_constraint(
                solver,
                bindings,
                constraint,
                projection_axis=None
                if projection_axes is None
                else projection_axes.get(constraint.constraint_id),
            )
    _apply_endpoint_links(solver, bindings, links)
    return int(solver.dof()) + _curved_polyline_degrees_of_freedom(sketch, bindings)


def _reference_entity(sketch: Sketch, reference: SketchGeometryReference) -> SketchEntity:
    try:
        return next(entity for entity in sketch.entities if entity.entity_id == reference.entity_id)
    except StopIteration as exc:
        raise ValueError(f"constraint references missing entity {reference.entity_id!r}") from exc


def _reference_point(sketch: Sketch, reference: SketchGeometryReference) -> tuple[float, float]:
    entity = _reference_entity(sketch, reference)
    if isinstance(entity, PointEntity) and reference.kind == "vertex" and reference.index == 0:
        return entity.position_mm
    if isinstance(entity, SplineEntity):
        if reference.kind == "start":
            return entity.control_points_mm[0]
        if reference.kind == "end":
            return entity.control_points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return _point_at(entity.control_points_mm, reference.index)
    if isinstance(entity, LineEntity):
        if reference.kind == "start":
            return entity.start_mm
        if reference.kind == "end":
            return entity.end_mm
    elif isinstance(entity, PolylineEntity):
        if reference.kind == "start":
            return entity.points_mm[0]
        if reference.kind == "end":
            return entity.points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return _point_at(entity.points_mm, reference.index)
    elif isinstance(entity, RectangleEntity):
        first_u, first_v = entity.first_corner_mm
        opposite_u, opposite_v = entity.opposite_corner_mm
        corners = (
            (first_u, first_v),
            (opposite_u, first_v),
            (opposite_u, opposite_v),
            (first_u, opposite_v),
        )
        if reference.kind == "start":
            return corners[0]
        if reference.kind == "end":
            return corners[2]
        if reference.kind == "vertex" and reference.index is not None:
            return _point_at(corners, reference.index)
    elif isinstance(entity, CircleEntity) and reference.kind in ("center", "geometry"):
        return entity.center_mm
    elif isinstance(entity, ArcEntity):
        if reference.kind in ("center", "geometry"):
            return entity.center_mm
        if reference.kind in ("start", "end"):
            angle = entity.start_angle_deg
            if reference.kind == "end":
                angle += entity.sweep_angle_deg
            radians = math.radians(angle)
            return (
                entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                entity.center_mm[1] + entity.radius_mm * math.sin(radians),
            )
    raise ValueError(f"reference {reference.kind!r} is not a measurable point")


def _point_at(points: tuple[tuple[float, float], ...], index: int) -> tuple[float, float]:
    if index >= len(points):
        raise ValueError(f"point index {index} is outside the referenced geometry")
    return points[index]


def _reference_line(
    sketch: Sketch, reference: SketchGeometryReference
) -> tuple[tuple[float, float], tuple[float, float]]:
    entity = _reference_entity(sketch, reference)
    if isinstance(entity, LineEntity) and reference.kind == "geometry":
        return (entity.start_mm, entity.end_mm)
    if isinstance(entity, PolylineEntity) and reference.kind == "segment":
        if reference.index is None:
            raise ValueError("line segment reference requires an index")
        segment_count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        if reference.index >= segment_count:
            raise ValueError("line segment reference is outside the polyline")
        if entity.bulges and entity.bulges[reference.index] != 0:
            raise ValueError("圆弧段不能作为直线约束或标注。")
        return (
            _point_at(entity.points_mm, reference.index),
            _point_at(entity.points_mm, (reference.index + 1) % len(entity.points_mm)),
        )
    if isinstance(entity, RectangleEntity) and reference.kind == "segment":
        if reference.index is None or reference.index >= 4:
            raise ValueError("rectangle segment index must be between 0 and 3")
        first_u, first_v = entity.first_corner_mm
        opposite_u, opposite_v = entity.opposite_corner_mm
        corners = (
            (first_u, first_v),
            (opposite_u, first_v),
            (opposite_u, opposite_v),
            (first_u, opposite_v),
        )
        return (corners[reference.index], corners[(reference.index + 1) % 4])
    raise ValueError("angle reference must select a line or indexed segment")


def _projected_distance(
    a: tuple[float, float],
    b: tuple[float, float],
    axis: str,
    direction: tuple[float, float] | None = None,
) -> float:
    if axis == "aligned":
        return math.dist(a, b)
    delta = (
        (b[0] - a[0]) * direction[0] + (b[1] - a[1]) * direction[1]
        if direction is not None
        else b[0] - a[0]
        if axis in ("horizontal", "ordinate_x")
        else b[1] - a[1]
    )
    return delta if axis.startswith("ordinate_") else abs(delta)


def _measure_dimension(sketch: Sketch, constraint: SketchConstraint) -> float:
    first = constraint.references[0]
    if constraint.kind == "length":
        start, end = _reference_line(sketch, first)
        return _projected_distance(start, end, constraint.axis, constraint.projection_axis)
    if constraint.kind == "distance":
        return _projected_distance(
            _reference_point(sketch, first),
            _reference_point(sketch, constraint.references[1]),
            constraint.axis,
            constraint.projection_axis,
        )
    if constraint.kind == "angle":
        first_start, first_end = _reference_line(sketch, first)
        second_start, second_end = _reference_line(sketch, constraint.references[1])
        first_vector = (first_end[0] - first_start[0], first_end[1] - first_start[1])
        second_vector = (second_end[0] - second_start[0], second_end[1] - second_start[1])
        cross = first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0]
        dot = first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1]
        return math.degrees(math.atan2(cross, dot))
    entity = _reference_entity(sketch, first)
    if isinstance(entity, PolylineEntity) and constraint.kind in (
        "radius",
        "diameter",
        "arc_length",
    ):
        _center, radius, arc = _curve_data(sketch, first)
        if arc is None:
            raise ValueError("多段线段不是圆弧。")
        if constraint.kind == "arc_length":
            return radius * abs(math.radians(arc.sweep_angle_deg))
        return radius * (2 if constraint.kind == "diameter" else 1)
    if constraint.kind == "arc_length" and isinstance(entity, ArcEntity):
        return entity.radius_mm * abs(math.radians(entity.sweep_angle_deg))
    if isinstance(entity, CircleEntity | ArcEntity) and constraint.kind in (
        "radius",
        "diameter",
    ):
        if constraint.kind == "diameter":
            return 2.0 * entity.radius_mm
        return entity.radius_mm
    raise ValueError(f"{constraint.kind} does not define a reference dimension")


def measure_sketch_dimension(sketch: Sketch, constraint: SketchConstraint) -> float:
    """Measure a supported dimension from neutral sketch geometry."""
    if constraint.kind not in ("length", "distance", "angle", "radius", "diameter", "arc_length"):
        raise ValueError(f"{constraint.kind} is not a supported dimension")
    return _measure_dimension(sketch, constraint)


def sketch_dimension_anchor(
    sketch: Sketch, constraint: SketchConstraint, offset_mm: float = 5.0
) -> tuple[float, float]:
    """Place a readable label near its measured geometry in sketch-local units."""
    if not math.isfinite(offset_mm) or offset_mm <= 0.0:
        raise ValueError("dimension label offset must be positive and finite")
    if constraint.text_position_mm is not None:
        return constraint.text_position_mm
    if constraint.position_mm is not None:
        return constraint.position_mm
    first = constraint.references[0]
    if constraint.kind == "length":
        start, end = _reference_line(sketch, first)
        direction = (end[0] - start[0], end[1] - start[1])
        length = math.hypot(*direction)
        normal = (-direction[1] / length, direction[0] / length)
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        return (midpoint[0] + normal[0] * offset_mm, midpoint[1] + normal[1] * offset_mm)
    if constraint.kind == "distance":
        start = _reference_point(sketch, first)
        end = _reference_point(sketch, constraint.references[1])
        direction = (end[0] - start[0], end[1] - start[1])
        length = math.hypot(*direction)
        if length <= 1e-12:
            raise ValueError("zero-length point distance has no label direction")
        normal = (-direction[1] / length, direction[0] / length)
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        return (midpoint[0] + normal[0] * offset_mm, midpoint[1] + normal[1] * offset_mm)
    if constraint.kind == "angle":
        first_line = _reference_line(sketch, first)
        second_line = _reference_line(sketch, constraint.references[1])
        base = _line_intersection(first_line, second_line)
        first_direction = _unit_vector(first_line)
        second_direction = _unit_vector(second_line)
        bisector = (
            first_direction[0] + second_direction[0],
            first_direction[1] + second_direction[1],
        )
        bisector_length = math.hypot(*bisector)
        if bisector_length <= 1e-12:
            raise ValueError("opposite overlapping lines do not define an angle label side")
        return (
            base[0] + offset_mm * bisector[0] / bisector_length,
            base[1] + offset_mm * bisector[1] / bisector_length,
        )
    entity = _reference_entity(sketch, first)
    if isinstance(entity, PolylineEntity) and first.kind == "segment" and first.index is not None:
        entity = polyline_arc_segment(entity, first.index)
    if isinstance(entity, CircleEntity | ArcEntity):
        center = entity.center_mm
        radius = entity.radius_mm
        reach = radius + offset_mm
        angle = math.radians(45.0)
        return (center[0] + reach * math.cos(angle), center[1] + reach * math.sin(angle))
    raise ValueError(f"{constraint.kind} has no supported viewport anchor")


def _unit_vector(
    line: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    direction = (line[1][0] - line[0][0], line[1][1] - line[0][1])
    length = math.hypot(*direction)
    if length <= 1e-12:
        raise ValueError("dimension references a degenerate line")
    return (direction[0] / length, direction[1] / length)


def _line_intersection(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    p, p_end = first
    q, q_end = second
    r = (p_end[0] - p[0], p_end[1] - p[1])
    s = (q_end[0] - q[0], q_end[1] - q[1])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) <= 1e-12:
        raise ValueError("parallel lines do not define an angle label anchor")
    difference = (q[0] - p[0], q[1] - p[1])
    parameter = (difference[0] * s[1] - difference[1] * s[0]) / denominator
    return (p[0] + parameter * r[0], p[1] + parameter * r[1])


def _dimension_violations(
    sketch: Sketch,
    *,
    projection_axes: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[tuple[str, float, float], ...]:
    scale = _sketch_linear_scale(sketch)
    linear_tolerance = max(_LINEAR_ABSOLUTE_TOLERANCE_MM, scale * _LINEAR_RELATIVE_TOLERANCE)
    violations: list[tuple[str, float, float]] = []
    for constraint in sketch.constraints:
        if constraint.kind not in (
            "length",
            "distance",
            "angle",
            "radius",
            "diameter",
            "arc_length",
        ):
            continue
        if constraint.value is None:
            continue
        direction = (
            None if projection_axes is None else projection_axes.get(constraint.constraint_id)
        )
        if direction is None:
            measured = _measure_dimension(sketch, constraint)
        else:
            first = constraint.references[0]
            start, end = (
                _reference_line(sketch, first)
                if constraint.kind == "length"
                else (
                    _reference_point(sketch, first),
                    _reference_point(sketch, constraint.references[1]),
                )
            )
            projected = (end[0] - start[0]) * direction[0] + (end[1] - start[1]) * direction[1]
            measured = projected if constraint.axis.startswith("ordinate_") else abs(projected)
        if constraint.kind == "angle":
            error = abs((measured - constraint.value + 180.0) % 360.0 - 180.0)
            tolerance = _ANGULAR_TOLERANCE_DEG
        else:
            error = abs(measured - constraint.value)
            tolerance = linear_tolerance
        if error > tolerance:
            violations.append((constraint.constraint_id, error, tolerance))
    return tuple(violations)


def _relation_violations(
    base_sketch: Sketch, solved_sketch: Sketch
) -> tuple[tuple[str, float, float], ...]:
    """Independently measure every accepted driving geometric relation."""
    scale = _sketch_linear_scale(solved_sketch)
    linear_tolerance = max(
        _RELATION_LINEAR_ABSOLUTE_TOLERANCE_MM, scale * _LINEAR_RELATIVE_TOLERANCE
    )
    violations: list[tuple[str, float, float]] = []
    base_constraints = {
        constraint.constraint_id: constraint for constraint in base_sketch.constraints
    }
    for constraint in solved_sketch.constraints:
        if not constraint.driving or constraint.kind in (
            "length",
            "distance",
            "angle",
            "radius",
            "diameter",
            "arc_length",
        ):
            continue
        try:
            if (
                constraint.kind == "fixed"
                and (original := base_constraints.get(constraint.constraint_id)) is not None
                and original.kind == "fixed"
            ):
                error = math.dist(
                    _reference_point(base_sketch, original.references[0]),
                    _reference_point(solved_sketch, constraint.references[0]),
                )
                tolerance = linear_tolerance
            else:
                error, tolerance = _relation_residual(
                    base_sketch, solved_sketch, constraint, linear_tolerance
                )
        except (KeyError, TypeError, ValueError):
            error, tolerance = math.inf, linear_tolerance
        if error > tolerance:
            violations.append((constraint.constraint_id, error, tolerance))
    return tuple(violations)


def validate_sketch_revision_geometry(base: Sketch, revised: Sketch) -> Sketch:
    """Refresh reference dimensions and verify all remaining driving relations."""
    if _unsupported_curved_polyline_constraint(revised):
        raise ValueError("含圆弧的多段线暂不支持关联约束。")
    refreshed = refresh_reference_dimensions(revised)
    if _dimension_violations(refreshed) or _relation_violations(base, refreshed):
        raise ValueError("revised geometry violates existing constraints")
    return refreshed


def inferred_coincident_satisfied(sketch: Sketch, constraint: SketchConstraint) -> bool:
    """Check a persisted inferred coincidence without invoking PlaneGCS."""
    if constraint.kind != "coincident" or constraint.source != "inferred" or not constraint.driving:
        return False
    linear_tolerance = max(
        1e-9,
        _sketch_linear_scale(sketch) * 1e-10,
    )
    try:
        error, tolerance = _relation_residual(sketch, sketch, constraint, linear_tolerance)
    except (KeyError, TypeError, ValueError):
        return False
    return error <= tolerance


def _relation_residual(
    base_sketch: Sketch,
    solved_sketch: Sketch,
    constraint: SketchConstraint,
    linear_tolerance: float,
) -> tuple[float, float]:
    references = constraint.references
    first = references[0]
    second = references[1] if len(references) > 1 else None
    if constraint.kind == "fixed":
        return (
            math.dist(
                _reference_point(base_sketch, first),
                _reference_point(solved_sketch, first),
            ),
            linear_tolerance,
        )
    if constraint.kind == "coincident":
        if second is None:
            raise ValueError("coincident relation is missing its second point")
        return (
            math.dist(
                _reference_point(solved_sketch, first),
                _reference_point(solved_sketch, second),
            ),
            linear_tolerance,
        )
    if constraint.kind in ("horizontal", "vertical"):
        start, end = _reference_line(solved_sketch, first)
        angle = _line_angle_deg(start, end)
        if constraint.kind == "horizontal":
            error = min(angle % 180.0, 180.0 - (angle % 180.0))
        else:
            error = abs(90.0 - (angle % 180.0))
        return (error, _ANGULAR_TOLERANCE_DEG)
    if constraint.kind in ("parallel", "perpendicular"):
        if second is None:
            raise ValueError(f"{constraint.kind} relation is missing its second line")
        first_start, first_end = _reference_line(solved_sketch, first)
        second_start, second_end = _reference_line(solved_sketch, second)
        first_vector = _vector(first_start, first_end)
        second_vector = _vector(second_start, second_end)
        cross = first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0]
        dot = first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1]
        angle = abs(math.degrees(math.atan2(cross, dot)))
        if constraint.kind == "parallel":
            error = min(angle, abs(180.0 - angle))
        else:
            error = abs(90.0 - angle)
        return (error, _ANGULAR_TOLERANCE_DEG)
    if constraint.kind == "concentric":
        if second is None:
            raise ValueError("concentric relation is missing its second curve")
        first_center, _first_radius, _first_arc = _curve_data(solved_sketch, first)
        second_center, _second_radius, _second_arc = _curve_data(solved_sketch, second)
        return (math.dist(first_center, second_center), linear_tolerance)
    if constraint.kind == "equal":
        if second is None:
            raise ValueError("equal relation is missing its second curve")
        first_entity = _reference_entity(solved_sketch, first)
        second_entity = _reference_entity(solved_sketch, second)
        if _is_line_reference(first_entity, first):
            first_line = _reference_line(solved_sketch, first)
            second_line = _reference_line(solved_sketch, second)
            return (
                abs(math.dist(*first_line) - math.dist(*second_line)),
                linear_tolerance,
            )
        _first_center, first_radius, _first_arc = _curve_data(solved_sketch, first)
        _second_center, second_radius, _second_arc = _curve_data(solved_sketch, second)
        return (abs(first_radius - second_radius), linear_tolerance)
    if constraint.kind == "tangent":
        if second is None:
            raise ValueError("tangent relation is missing its second curve")
        first_entity = _reference_entity(solved_sketch, first)
        second_entity = _reference_entity(solved_sketch, second)
        if (
            constraint.first_endpoint is not None or constraint.second_endpoint is not None
        ) and not tangent_endpoints_satisfied(
            tangent_entity_curve(first_entity, first.index),
            tangent_entity_curve(second_entity, second.index),
            constraint.first_endpoint,
            constraint.second_endpoint,
        ):
            return math.inf, linear_tolerance
        if _is_line_reference(first_entity, first):
            line = _reference_line(solved_sketch, first)
            curve = _curve_data(solved_sketch, second)
            return _line_curve_tangent_residual(line, curve, linear_tolerance), linear_tolerance
        if _is_line_reference(second_entity, second):
            line = _reference_line(solved_sketch, second)
            curve = _curve_data(solved_sketch, first)
            return _line_curve_tangent_residual(line, curve, linear_tolerance), linear_tolerance
        first_curve = _curve_data(solved_sketch, first)
        second_curve = _curve_data(solved_sketch, second)
        return (
            _curve_curve_tangent_residual(first_curve, second_curve, linear_tolerance),
            linear_tolerance,
        )
    raise ValueError(f"unsupported geometric relation {constraint.kind!r}")


def _line_angle_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    dx, dy = _vector(start, end)
    return abs(math.degrees(math.atan2(dy, dx)))


def _is_line_reference(entity: SketchEntity, reference: SketchGeometryReference) -> bool:
    if isinstance(entity, LineEntity | RectangleEntity):
        return True
    if (
        isinstance(entity, PolylineEntity)
        and reference.kind == "segment"
        and reference.index is not None
    ):
        return not entity.bulges or (
            reference.index < len(entity.bulges) and entity.bulges[reference.index] == 0
        )
    return False


def _vector(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    return (end[0] - start[0], end[1] - start[1])


def _curve_data(
    sketch: Sketch, reference: SketchGeometryReference
) -> tuple[tuple[float, float], float, ArcEntity | None]:
    entity = _reference_entity(sketch, reference)
    if (
        isinstance(entity, PolylineEntity)
        and reference.kind == "segment"
        and reference.index is not None
    ):
        arc = polyline_arc_segment(entity, reference.index)
        return (arc.center_mm, arc.radius_mm, arc)
    if isinstance(entity, CircleEntity):
        return (entity.center_mm, entity.radius_mm, None)
    if isinstance(entity, ArcEntity):
        return (entity.center_mm, entity.radius_mm, entity)
    raise ValueError("curve relation requires a circle or arc reference")


def _line_curve_tangent_residual(
    line: tuple[tuple[float, float], tuple[float, float]],
    curve: tuple[tuple[float, float], float, ArcEntity | None],
    tolerance: float,
) -> float:
    start, end = line
    center, radius, arc = curve
    dx, dy = _vector(start, end)
    length = math.hypot(dx, dy)
    if length <= tolerance:
        return math.inf
    normal = (-dy / length, dx / length)
    signed_distance = (center[0] - start[0]) * normal[0] + (center[1] - start[1]) * normal[1]
    error = abs(abs(signed_distance) - radius)
    if arc is not None:
        contact = (
            center[0] - normal[0] * signed_distance,
            center[1] - normal[1] * signed_distance,
        )
        if not _arc_contains(arc, contact, tolerance):
            endpoints = (
                (
                    center[0] + radius * math.cos(math.radians(angle)),
                    center[1] + radius * math.sin(math.radians(angle)),
                )
                for angle in (arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg)
            )
            endpoint_error = min(
                abs((point[0] - start[0]) * normal[0] + (point[1] - start[1]) * normal[1])
                for point in endpoints
            )
            if endpoint_error > tolerance:
                return max(error, tolerance * 2.0)
    return error


def _curve_curve_tangent_residual(
    first: tuple[tuple[float, float], float, ArcEntity | None],
    second: tuple[tuple[float, float], float, ArcEntity | None],
    tolerance: float,
) -> float:
    first_center, first_radius, first_arc = first
    second_center, second_radius, second_arc = second
    delta = _vector(first_center, second_center)
    distance = math.hypot(*delta)
    external_error = abs(distance - first_radius - second_radius)
    internal_error = abs(distance - abs(first_radius - second_radius))
    error = min(external_error, internal_error)
    if distance <= tolerance:
        return error
    direction = (delta[0] / distance, delta[1] / distance)
    contacts = (
        (
            (
                first_center[0] + direction[0] * first_radius,
                first_center[1] + direction[1] * first_radius,
            ),
            (
                second_center[0] - direction[0] * second_radius,
                second_center[1] - direction[1] * second_radius,
            ),
            external_error,
        ),
        (
            (
                first_center[0] + direction[0] * first_radius,
                first_center[1] + direction[1] * first_radius,
            ),
            (
                second_center[0] + direction[0] * second_radius,
                second_center[1] + direction[1] * second_radius,
            ),
            internal_error,
        )
        if first_radius >= second_radius
        else (
            (
                first_center[0] - direction[0] * first_radius,
                first_center[1] - direction[1] * first_radius,
            ),
            (
                second_center[0] - direction[0] * second_radius,
                second_center[1] - direction[1] * second_radius,
            ),
            internal_error,
        ),
    )
    valid_errors = [
        branch_error
        for first_contact, second_contact, branch_error in contacts
        if (first_arc is None or _arc_contains(first_arc, first_contact, tolerance))
        and (second_arc is None or _arc_contains(second_arc, second_contact, tolerance))
    ]
    if not valid_errors:
        return max(error, tolerance * 2.0)
    return min(valid_errors)


def _arc_contains(arc: ArcEntity, point: tuple[float, float], tolerance: float) -> bool:
    angle = math.degrees(math.atan2(point[1] - arc.center_mm[1], point[0] - arc.center_mm[0]))
    start = arc.start_angle_deg
    sweep = arc.sweep_angle_deg
    angle_tolerance = math.degrees(tolerance / max(arc.radius_mm, tolerance))
    if sweep >= 0.0:
        delta = (angle - start) % 360.0
        return delta <= sweep + angle_tolerance or delta >= 360.0 - angle_tolerance
    delta = (start - angle) % 360.0
    return delta <= -sweep + angle_tolerance or delta >= 360.0 - angle_tolerance


def _sketch_linear_scale(sketch: Sketch) -> float:
    points: list[tuple[float, float]] = []
    radii: list[float] = []
    for entity in sketch.entities:
        if isinstance(entity, PointEntity):
            points.append(entity.position_mm)
        elif isinstance(entity, LineEntity):
            points.extend((entity.start_mm, entity.end_mm))
        elif isinstance(entity, SplineEntity):
            points.extend(entity.control_points_mm)
        elif isinstance(entity, PolylineEntity):
            points.extend(entity.points_mm)
        elif isinstance(entity, RectangleEntity):
            points.extend((entity.first_corner_mm, entity.opposite_corner_mm))
        elif isinstance(entity, EllipseEntity):
            points.append(entity.center_mm)
            radii.append(entity.major_radius_mm)
        else:
            points.append(entity.center_mm)
            radii.append(entity.radius_mm)
    if not points:
        return 1.0
    width = max(point[0] for point in points) - min(point[0] for point in points)
    height = max(point[1] for point in points) - min(point[1] for point in points)
    return max(width, height, max(radii, default=0.0), _LINEAR_ABSOLUTE_TOLERANCE_MM)


def _locked_reference_message(
    sketch: Sketch, references: tuple[SketchGeometryReference, ...]
) -> str:
    identities = {reference.entity_id for reference in references}
    locked = [
        entity
        for entity in sketch.entities
        if entity.entity_id in identities and sketch.layers.get(entity.layer_name).locked
    ]
    if not locked:
        return ""
    details = "、".join(f"{entity.layer_name} / {entity.entity_id[:8]}" for entity in locked)
    return f"图层已锁定，不能驱动修改或拖动这些图元：{details}；请先解锁，或使用参考尺寸。"


def _sketch_bindings(
    solver: PlaneGcsSketch,
    sketch: Sketch,
    additional: tuple[SketchGeometryReference, ...] = (),
    *,
    free_arc_ids: set[str] | None = None,
) -> dict[str, _EntityBinding]:
    referenced = {ref.entity_id for ref in additional}
    referenced.update(ref.entity_id for c in sketch.constraints for ref in c.references)
    if any(
        isinstance(entity, EllipseEntity) and entity.entity_id in referenced
        for entity in sketch.entities
    ):
        raise ValueError("椭圆暂不支持草图约束引用。")
    entities = {entity.entity_id: entity for entity in sketch.entities}
    arc_referenced = {
        ref.entity_id
        for ref in (*additional, *(ref for c in sketch.constraints for ref in c.references))
        if ref.kind == "segment"
        and ref.entity_id in entities
        and not _is_line_reference(entities[ref.entity_id], ref)
    }
    return {
        entity.entity_id: (
            _EntityBinding(entity, (), fixed=True)
            if entity.entity_id not in referenced
            and (
                isinstance(entity, EllipseEntity)
                or (isinstance(entity, PolylineEntity) and entity.bulges)
            )
            else _add_entity(
                solver,
                entity,
                fixed=sketch.layers.get(entity.layer_name).locked,
                polyline_arcs=entity.entity_id in arc_referenced,
                free_arc_angle=free_arc_ids is not None and entity.entity_id in free_arc_ids,
            )
        )
        for entity in sketch.entities
    }


def _add_point(solver: PlaneGcsSketch, point: tuple[float, float], *, fixed: bool = False) -> int:
    if fixed:
        return int(
            solver.add_point_from_params(
                solver.add_fixed_param(point[0]), solver.add_fixed_param(point[1])
            )
        )
    return int(solver.add_point(*point))


def _add_line(solver: PlaneGcsSketch, start: int, end: int) -> int:
    return int(solver.add_line(cast("PointId", start), cast("PointId", end)))


def _add_entity(
    solver: PlaneGcsSketch,
    entity: SketchEntity,
    *,
    fixed: bool = False,
    polyline_arcs: bool = False,
    free_arc_angle: bool = False,
) -> _EntityBinding:
    if isinstance(entity, EllipseEntity):
        return _EntityBinding(entity, (), fixed=True)
    if isinstance(entity, PointEntity):
        return _EntityBinding(
            entity, (_add_point(solver, entity.position_mm, fixed=fixed),), fixed=fixed
        )
    if isinstance(entity, SplineEntity):
        points = tuple(_add_point(solver, point, fixed=fixed) for point in entity.control_points_mm)
        return _EntityBinding(entity, points, fixed=fixed)
    if isinstance(entity, LineEntity):
        points = (
            _add_point(solver, entity.start_mm, fixed=fixed),
            _add_point(solver, entity.end_mm, fixed=fixed),
        )
        line = _add_line(solver, *points)
        return _EntityBinding(entity, points, (line,), (points,), fixed=fixed)
    if isinstance(entity, PolylineEntity):
        points = tuple(_add_point(solver, point, fixed=fixed) for point in entity.points_mm)
        edges = tuple(zip(points, points[1:], strict=False))
        if entity.closed:
            edges = (*edges, (points[-1], points[0]))
        lines = tuple(_add_line(solver, start, end) for start, end in edges)
        if not polyline_arcs or not entity.bulges:
            return _EntityBinding(entity, points, lines, edges, fixed=fixed)
        arcs: list[int | None] = []
        centers: list[int | None] = []
        for index, bulge in enumerate(entity.bulges):
            if bulge == 0:
                arcs.append(None)
                centers.append(None)
                continue
            arc = bulge_arc(
                entity.points_mm[index],
                entity.points_mm[(index + 1) % len(points)],
                bulge,
                entity.entity_id,
            )
            center = _add_point(solver, arc.center_mm, fixed=fixed)
            start_angle = math.radians(arc.start_angle_deg)
            end_angle = start_angle + math.radians(arc.sweep_angle_deg)
            start_id, end_id = edges[index]
            if bulge < 0:
                start_id, end_id = end_id, start_id
                start_angle, end_angle = end_angle, start_angle
            if fixed:
                arc_id = int(
                    solver.add_arc(
                        cast("PointId", center),
                        cast("PointId", start_id),
                        cast("PointId", end_id),
                        solver.add_fixed_param(arc.radius_mm),
                        solver.add_fixed_param(start_angle),
                        solver.add_fixed_param(end_angle),
                    )
                )
            else:
                arc_id = int(
                    solver.add_arc_cse(
                        cast("PointId", center),
                        cast("PointId", start_id),
                        cast("PointId", end_id),
                        arc.radius_mm,
                        start_angle,
                        end_angle,
                    )
                )
            arcs.append(arc_id)
            centers.append(center)
        return _EntityBinding(
            entity,
            points,
            lines,
            edges,
            fixed=fixed,
            segment_arcs=tuple(arcs),
            segment_centers=tuple(centers),
        )
    if isinstance(entity, RectangleEntity):
        first_u, first_v = entity.first_corner_mm
        opposite_u, opposite_v = entity.opposite_corner_mm
        coordinates = (
            (first_u, first_v),
            (opposite_u, first_v),
            (opposite_u, opposite_v),
            (first_u, opposite_v),
        )
        points = tuple(_add_point(solver, point, fixed=fixed) for point in coordinates)
        edges = tuple(zip(points, (*points[1:], points[0]), strict=True))
        lines = tuple(_add_line(solver, start, end) for start, end in edges)
        for index, line in enumerate(lines if not fixed else ()):
            if index in (0, 2):
                solver.horizontal(cast("LineId", line))
            else:
                solver.vertical(cast("LineId", line))
        for index, edge in enumerate(edges if not fixed else ()):
            next_edge = edges[(index + 1) % len(edges)]
            solver.coincident(cast("PointId", edge[1]), cast("PointId", next_edge[0]))
        return _EntityBinding(entity, points, lines, edges, fixed=fixed)
    if isinstance(entity, CircleEntity):
        center = _add_point(solver, entity.center_mm, fixed=fixed)
        radius = solver.add_param(entity.radius_mm, fixed=fixed)
        circle = int(solver.add_circle(cast("PointId", center), radius))
        return _EntityBinding(entity, (center,), circle_id=circle, fixed=fixed)
    if isinstance(entity, EllipseEntity):
        raise ValueError("椭圆约束求解尚不支持。")
    start_radians = math.radians(entity.start_angle_deg)
    end_radians = math.radians(entity.start_angle_deg + entity.sweep_angle_deg)
    start = (
        entity.center_mm[0] + entity.radius_mm * math.cos(start_radians),
        entity.center_mm[1] + entity.radius_mm * math.sin(start_radians),
    )
    end = (
        entity.center_mm[0] + entity.radius_mm * math.cos(end_radians),
        entity.center_mm[1] + entity.radius_mm * math.sin(end_radians),
    )
    points = (
        _add_point(solver, entity.center_mm, fixed=fixed),
        _add_point(solver, start, fixed=fixed),
        _add_point(solver, end, fixed=fixed),
    )
    start_id, end_id = points[1], points[2]
    if entity.sweep_angle_deg < 0:
        start_id, end_id = end_id, start_id
        start_radians, end_radians = end_radians, start_radians
    if fixed:
        arc = int(
            solver.add_arc(
                cast("PointId", points[0]),
                cast("PointId", start_id),
                cast("PointId", end_id),
                solver.add_fixed_param(entity.radius_mm),
                solver.add_fixed_param(start_radians),
                solver.add_fixed_param(end_radians),
            )
        )
        return _EntityBinding(entity, points, arc_id=arc, fixed=True)
    arc = int(
        solver.add_arc_cse(
            cast("PointId", points[0]),
            cast("PointId", start_id),
            cast("PointId", end_id),
            entity.radius_mm,
            start_radians,
            end_radians,
        )
    )
    if not free_arc_angle:
        solver.set_arc_angle(cast("ArcId", arc), math.radians(abs(entity.sweep_angle_deg)))
    return _EntityBinding(entity, points, arc_id=arc)


def _binding(
    reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]
) -> _EntityBinding:
    try:
        return bindings[reference.entity_id]
    except KeyError as exc:
        raise ValueError(f"constraint references missing entity {reference.entity_id!r}") from exc


def _point_for(reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]) -> int:
    bound = _binding(reference, bindings)
    entity = bound.entity
    if isinstance(entity, PointEntity) and reference.kind == "vertex" and reference.index == 0:
        return bound.points[0]
    if reference.kind == "center" and isinstance(entity, CircleEntity | ArcEntity):
        return bound.points[0]
    if isinstance(entity, LineEntity):
        if reference.kind == "start":
            return bound.points[0]
        if reference.kind == "end":
            return bound.points[1]
    if isinstance(entity, PolylineEntity | SplineEntity):
        if reference.kind == "start":
            return bound.points[0]
        if reference.kind == "end":
            return bound.points[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return _indexed(bound.points, reference.index, "polyline vertex")
    if isinstance(entity, RectangleEntity):
        if reference.kind == "start":
            return bound.points[0]
        if reference.kind == "end":
            return bound.points[2]
        if reference.kind == "vertex" and reference.index is not None:
            return _indexed(bound.points, reference.index, "rectangle vertex")
    if isinstance(entity, ArcEntity):
        if reference.kind == "start":
            return bound.points[1]
        if reference.kind == "end":
            return bound.points[2]
    raise ValueError(
        f"reference {reference.kind!r} does not name a point on {type(entity).__name__}"
    )


def _line_for(reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]) -> int:
    bound = _binding(reference, bindings)
    if isinstance(bound.entity, LineEntity) and reference.kind == "geometry":
        return bound.lines[0]
    if (
        isinstance(bound.entity, (PolylineEntity, RectangleEntity))
        and reference.kind == "segment"
        and reference.index is not None
    ):
        if not _is_line_reference(bound.entity, reference):
            raise ValueError("圆弧段不能作为直线约束。")
        return _indexed(bound.lines, reference.index, "line segment")
    raise ValueError(
        f"reference {reference.kind!r} does not name a line on {type(bound.entity).__name__}"
    )


def _curve_for(
    reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]
) -> tuple[str, int]:
    bound = _binding(reference, bindings)
    if (
        isinstance(bound.entity, PolylineEntity)
        and reference.kind == "segment"
        and reference.index is not None
    ):
        if (
            reference.index >= len(bound.segment_arcs)
            or bound.segment_arcs[reference.index] is None
        ):
            raise ValueError("所选多段线段不是圆弧。")
        return ("arc", cast("int", bound.segment_arcs[reference.index]))
    if reference.kind != "geometry":
        raise ValueError("tangent, equal, radius, and diameter require a whole curve reference")
    if bound.circle_id is not None:
        return ("circle", bound.circle_id)
    if bound.arc_id is not None:
        return ("arc", bound.arc_id)
    raise ValueError(f"{type(bound.entity).__name__} is not a circular curve")


def _center_for(reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]) -> int:
    bound = _binding(reference, bindings)
    if (
        isinstance(bound.entity, PolylineEntity)
        and reference.kind == "segment"
        and reference.index is not None
    ):
        if (
            reference.index >= len(bound.segment_centers)
            or bound.segment_centers[reference.index] is None
        ):
            raise ValueError("所选多段线段不是圆弧。")
        return cast("int", bound.segment_centers[reference.index])
    if reference.kind == "center" and isinstance(bound.entity, CircleEntity | ArcEntity):
        return bound.points[0]
    curve = _curve_for(reference, bindings)
    if curve[0] in ("circle", "arc"):
        return bound.points[0]
    raise ValueError("concentric requires circle or arc references")


def _arc_endpoint_and_center(
    reference: SketchGeometryReference,
    endpoint: Literal["start", "end"],
    bindings: dict[str, _EntityBinding],
) -> tuple[int, int]:
    if _curve_for(reference, bindings)[0] != "arc":
        raise ValueError("端点连接需要圆弧。")
    binding = _binding(reference, bindings)
    if reference.kind == "segment" and reference.index is not None:
        if reference.index >= len(binding.line_points):
            raise ValueError("圆弧段索引超出范围。")
        edge = binding.line_points[reference.index]
        point = edge[0 if endpoint == "start" else 1]
    else:
        point = binding.points[1 if endpoint == "start" else 2]
    return point, _center_for(reference, bindings)


def _indexed(values: tuple[int, ...], index: int, name: str) -> int:
    if index >= len(values):
        raise ValueError(f"{name} index {index} is outside the referenced geometry")
    return values[index]


def _add_constraint(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    constraint: SketchConstraint,
    *,
    projection_axis: tuple[float, float] | None = None,
) -> tuple[int, ...]:
    references = constraint.references
    first = references[0]
    tag: int | tuple[int, ...]
    if constraint.kind == "coincident":
        tag = solver.coincident(
            cast("PointId", _point_for(first, bindings)),
            cast("PointId", _point_for(references[1], bindings)),
            driving=constraint.driving,
        )
    elif constraint.kind == "horizontal":
        tag = solver.horizontal(
            cast("LineId", _line_for(first, bindings)), driving=constraint.driving
        )
    elif constraint.kind == "vertical":
        tag = solver.vertical(
            cast("LineId", _line_for(first, bindings)), driving=constraint.driving
        )
    elif constraint.kind == "parallel":
        tag = solver.parallel(
            cast("LineId", _line_for(first, bindings)),
            cast("LineId", _line_for(references[1], bindings)),
            driving=constraint.driving,
        )
    elif constraint.kind == "perpendicular":
        tag = solver.perpendicular(
            cast("LineId", _line_for(first, bindings)),
            cast("LineId", _line_for(references[1], bindings)),
            driving=constraint.driving,
        )
    elif constraint.kind == "tangent":
        tag = _apply_tangent(solver, bindings, references, constraint.driving)
    elif constraint.kind == "concentric":
        tag = solver.coincident(
            cast("PointId", _center_for(first, bindings)),
            cast("PointId", _center_for(references[1], bindings)),
            driving=constraint.driving,
        )
    elif constraint.kind == "equal":
        tag = _apply_equal(solver, bindings, references, constraint.driving)
    elif constraint.kind == "fixed":
        point_id = _point_for(first, bindings)
        point = solver.get_point(cast("PointId", point_id))
        tag = solver.fix_point(
            cast("PointId", point_id),
            float(point[0]),
            float(point[1]),
            driving=constraint.driving,
        )
    elif constraint.kind in ("length", "distance") and constraint.axis != "aligned":
        start, end = (
            _line_points(first, bindings)
            if constraint.kind == "length"
            else (_point_for(first, bindings), _point_for(references[1], bindings))
        )
        projection_axis = projection_axis or constraint.projection_axis
        if projection_axis is not None:
            direction = projection_axis
            point = solver.get_point(cast("PointId", start))
            helper = solver.add_point(
                float(point[0]) - direction[1], float(point[1]) + direction[0]
            )
            line = solver.add_line(cast("PointId", start), helper)
            angle = math.atan2(direction[0], -direction[1])
            angle_tag = solver.set_p2p_angle(cast("PointId", start), helper, angle)
            length_tag = solver.set_p2p_distance(cast("PointId", start), helper, 1.0)
            value = _constraint_value(constraint)
            distance_tag = (
                solver.point_on_line(cast("PointId", end), line)
                if value == 0
                else solver.set_p2l_distance(cast("PointId", end), line, abs(value))
            )
            return (int(angle_tag), int(length_tag), int(distance_tag))
        axis = 0 if constraint.axis in ("horizontal", "ordinate_x") else 1
        a = solver.get_point_param_ids(cast("PointId", start))[axis]
        b = solver.get_point_param_ids(cast("PointId", end))[axis]
        value = _constraint_value(constraint)
        if not constraint.axis.startswith("ordinate_") and solver.get_param(b) < solver.get_param(
            a
        ):
            value = -value
        tag = solver.difference(
            a, b, solver.add_param(value, fixed=True), driving=constraint.driving
        )
    elif constraint.kind == "arc_length":
        curve_type, curve_id = _curve_for(first, bindings)
        if curve_type != "arc":
            raise ValueError("arc length requires an arc")
        tag = solver.set_arc_length(
            cast("ArcId", curve_id), _constraint_value(constraint), driving=constraint.driving
        )
    elif constraint.kind == "length":
        start, end = _line_points(first, bindings)
        tag = solver.set_p2p_distance(
            cast("PointId", start),
            cast("PointId", end),
            _constraint_value(constraint),
            driving=constraint.driving,
        )
    elif constraint.kind == "distance":
        tag = solver.set_p2p_distance(
            cast("PointId", _point_for(first, bindings)),
            cast("PointId", _point_for(references[1], bindings)),
            _constraint_value(constraint),
            driving=constraint.driving,
        )
    elif constraint.kind == "angle":
        tag = solver.set_l2l_angle(
            cast("LineId", _line_for(first, bindings)),
            cast("LineId", _line_for(references[1], bindings)),
            math.radians(_constraint_value(constraint)),
            driving=constraint.driving,
        )
    elif constraint.kind == "radius":
        curve_type, curve_id = _curve_for(first, bindings)
        if curve_type == "circle":
            tag = solver.set_circle_radius(
                cast("CircleId", curve_id),
                _constraint_value(constraint),
                driving=constraint.driving,
            )
        else:
            tag = solver.set_arc_radius(
                cast("ArcId", curve_id),
                _constraint_value(constraint),
                driving=constraint.driving,
            )
    elif constraint.kind == "diameter":
        curve_type, curve_id = _curve_for(first, bindings)
        if curve_type == "circle":
            tag = solver.set_circle_diameter(
                cast("CircleId", curve_id),
                _constraint_value(constraint),
                driving=constraint.driving,
            )
        else:
            tag = solver.set_arc_diameter(
                cast("ArcId", curve_id),
                _constraint_value(constraint),
                driving=constraint.driving,
            )
    else:
        raise ValueError(f"unsupported constraint kind {constraint.kind!r}")
    if isinstance(tag, tuple):
        return tuple(int(item) for item in tag)
    return (int(tag),)


def _line_points(
    reference: SketchGeometryReference, bindings: dict[str, _EntityBinding]
) -> tuple[int, int]:
    bound = _binding(reference, bindings)
    if isinstance(bound.entity, LineEntity) and reference.kind == "geometry":
        return bound.line_points[0]
    if (
        isinstance(bound.entity, (PolylineEntity, RectangleEntity))
        and reference.kind == "segment"
        and reference.index is not None
    ):
        return _indexed_pair(bound.line_points, reference.index)
    raise ValueError("length requires a line or indexed line segment reference")


def _indexed_pair(values: tuple[tuple[int, int], ...], index: int) -> tuple[int, int]:
    if index >= len(values):
        raise ValueError(f"line segment index {index} is outside the referenced geometry")
    return values[index]


def _constraint_value(constraint: SketchConstraint) -> float:
    if constraint.value is None:
        raise ValueError(f"{constraint.kind} requires a dimension value")
    return float(constraint.value)


def _apply_tangent(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    references: tuple[SketchGeometryReference, ...],
    driving: bool,
) -> int:
    first, second = references
    first_binding = _binding(first, bindings)
    second_binding = _binding(second, bindings)
    if _is_line_reference(first_binding.entity, first):
        line_id = _line_for(first, bindings)
        curve_kind, curve_id = _curve_for(second, bindings)
    elif _is_line_reference(second_binding.entity, second):
        line_id = _line_for(second, bindings)
        curve_kind, curve_id = _curve_for(first, bindings)
    else:
        first_kind, first_curve_id = _curve_for(first, bindings)
        second_kind, second_curve_id = _curve_for(second, bindings)
        if first_kind == "circle" and second_kind == "circle":
            return solver.tangent_circle_circle(
                cast("CircleId", first_curve_id),
                cast("CircleId", second_curve_id),
                driving=driving,
            )
        if first_kind == "circle" and second_kind == "arc":
            return solver.tangent_circle_arc(
                cast("CircleId", first_curve_id),
                cast("ArcId", second_curve_id),
                driving=driving,
            )
        if first_kind == "arc" and second_kind == "circle":
            return solver.tangent_circle_arc(
                cast("CircleId", second_curve_id),
                cast("ArcId", first_curve_id),
                driving=driving,
            )
        if first_kind == "arc" and second_kind == "arc":
            return solver.tangent_arc_arc(
                cast("ArcId", first_curve_id),
                cast("ArcId", second_curve_id),
                driving=driving,
            )
        raise ValueError("the selected curve pair does not support tangency")
    if curve_kind == "circle":
        return solver.tangent_line_circle(
            cast("LineId", line_id), cast("CircleId", curve_id), driving=driving
        )
    return solver.tangent_line_arc(
        cast("LineId", line_id), cast("ArcId", curve_id), driving=driving
    )


def _apply_equal(
    solver: PlaneGcsSketch,
    bindings: dict[str, _EntityBinding],
    references: tuple[SketchGeometryReference, ...],
    driving: bool,
) -> int:
    first, second = references
    first_binding = _binding(first, bindings)
    if _is_line_reference(first_binding.entity, first):
        return solver.equal_length(
            cast("LineId", _line_for(first, bindings)),
            cast("LineId", _line_for(second, bindings)),
            driving=driving,
        )
    first_kind, first_curve_id = _curve_for(first, bindings)
    second_kind, second_curve_id = _curve_for(second, bindings)
    if first_kind == "circle" and second_kind == "circle":
        return solver.equal_radius_cc(
            cast("CircleId", first_curve_id), cast("CircleId", second_curve_id), driving=driving
        )
    if first_kind == "arc" and second_kind == "arc":
        return solver.equal_radius_aa(
            cast("ArcId", first_curve_id), cast("ArcId", second_curve_id), driving=driving
        )
    if first_kind == "circle" and second_kind == "arc":
        return solver.equal_radius_ca(
            cast("CircleId", first_curve_id), cast("ArcId", second_curve_id), driving=driving
        )
    if first_kind == "arc" and second_kind == "circle":
        return solver.equal_radius_ca(
            cast("CircleId", second_curve_id), cast("ArcId", first_curve_id), driving=driving
        )
    raise ValueError("equal requires two line segments or circular curves")


def _read_solved_entity(solver: PlaneGcsSketch, binding: _EntityBinding) -> SketchEntity:
    if binding.fixed:
        # All parameters were allocated as constants. Preserve authored values
        # exactly, including arc angle normalization and metadata.
        return binding.entity
    entity = binding.entity
    if isinstance(entity, PointEntity):
        return replace(entity, position_mm=_point_value(solver, binding.points[0]))
    if isinstance(entity, SplineEntity):
        return SplineEntity(
            entity.entity_id,
            tuple(_point_value(solver, point) for point in binding.points),
            entity.construction,
            entity.layer_name,
            entity.point_ids,
        )
    if isinstance(entity, LineEntity):
        return LineEntity(
            entity.entity_id,
            _point_value(solver, binding.points[0]),
            _point_value(solver, binding.points[1]),
            entity.construction,
            entity.layer_name,
        )
    if isinstance(entity, PolylineEntity):
        bulges = entity.bulges
        if binding.segment_arcs:
            values: list[float] = []
            for original, arc_id in zip(entity.bulges, binding.segment_arcs, strict=True):
                if arc_id is None:
                    values.append(0.0)
                    continue
                info = solver.get_arc(cast("ArcId", arc_id))
                sweep = (float(info.end_angle) - float(info.start_angle)) * (
                    1 if original > 0 else -1
                )
                if (
                    not math.isfinite(sweep)
                    or sweep * original <= 0
                    or abs(sweep) >= 2 * math.pi - 1e-9
                ):
                    raise ValueError("求解后的圆弧方向或扫角无效。")
                value = math.tan(sweep / 4)
                if (abs(value) > 1) != (abs(original) > 1) and abs(abs(original) - 1) > 1e-9:
                    raise ValueError("求解改变了圆弧的优弧或劣弧分支。")
                values.append(value)
            bulges = tuple(values)
        return PolylineEntity(
            entity.entity_id,
            tuple(_point_value(solver, point_id) for point_id in binding.points),
            entity.closed,
            entity.construction,
            entity.layer_name,
            bulges,
            entity.point_ids,
        )
    if isinstance(entity, RectangleEntity):
        first = _point_value(solver, binding.points[0])
        opposite = _point_value(solver, binding.points[2])
        return RectangleEntity(
            entity.entity_id, first, opposite, entity.construction, entity.layer_name
        )
    if isinstance(entity, CircleEntity):
        if binding.circle_id is None:
            raise ValueError("circle solver identity is missing")
        info = solver.get_circle(cast("CircleId", binding.circle_id))
        return CircleEntity(
            entity.entity_id,
            _point_value(solver, binding.points[0]),
            float(info.radius),
            entity.construction,
            entity.layer_name,
        )
    if binding.arc_id is None:
        raise ValueError("arc solver identity is missing")
    info = solver.get_arc(cast("ArcId", binding.arc_id))
    reverse = entity.sweep_angle_deg < 0
    start_angle = math.degrees(float(info.end_angle if reverse else info.start_angle))
    sweep_angle = math.degrees(float(info.end_angle) - float(info.start_angle)) * (
        -1 if reverse else 1
    )
    if sweep_angle * entity.sweep_angle_deg <= 0:
        raise ValueError("求解改变了圆弧的方向。")
    return ArcEntity(
        entity.entity_id,
        _point_value(solver, binding.points[0]),
        float(info.radius),
        start_angle,
        sweep_angle,
        entity.construction,
        entity.layer_name,
    )


def _point_value(solver: PlaneGcsSketch, point_id: int) -> tuple[float, float]:
    value = solver.get_point(cast("PointId", point_id))
    return (float(value[0]), float(value[1]))
