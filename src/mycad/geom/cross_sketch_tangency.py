# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated cross-sketch constraint previews in a shared work plane."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Literal
from uuid import uuid4

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    RectangleTransformEvidence,
    project_coplanar_vector,
    project_polyline_entity,
    project_tangent_entity,
    resolve_tangency_component,
    resolve_tangent_curve,
    tangent_entity_curve,
    validate_tangency_component,
)
from mycad.core.polyline_curves import polyline_arc_segment
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint, SketchGeometryReference
from mycad.geom.sketch_constraints import (
    EndpointLink,
    solve_sketch_constraint,
    validate_sketch_revision_geometry,
)


def _map_axis_constraint(
    kind: Literal["horizontal", "vertical"], source: WorkPlaneFrame, target: WorkPlaneFrame
) -> Literal["horizontal", "vertical"]:
    axis = source.u_axis if kind == "horizontal" else source.v_axis
    along_u = sum(a * b for a, b in zip(axis, target.u_axis, strict=True))
    along_v = sum(a * b for a, b in zip(axis, target.v_axis, strict=True))
    if abs(abs(along_u) - 1) <= 1e-9 and abs(along_v) <= 1e-9:
        return "horizontal"
    if abs(abs(along_v) - 1) <= 1e-9 and abs(along_u) <= 1e-9:
        return "vertical"
    raise ValueError("倾斜坐标轴上的水平或垂直约束暂无法映射。")


def _map_dimension_axis(
    axis: str, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> tuple[str, float]:
    if axis == "aligned":
        return axis, 1.0
    horizontal = axis in ("horizontal", "ordinate_x")
    mapped = _map_axis_constraint("horizontal" if horizontal else "vertical", source, target)
    if not axis.startswith("ordinate_"):
        return mapped, 1.0
    source_axis = source.u_axis if horizontal else source.v_axis
    target_axis = target.u_axis if mapped == "horizontal" else target.v_axis
    sign = sum(a * b for a, b in zip(source_axis, target_axis, strict=True))
    return ("ordinate_x" if mapped == "horizontal" else "ordinate_y"), sign


def solve_unconstrained_tangency(
    sketches: tuple[Sketch, ...], relation: CrossSketchTangency
) -> tuple[Sketch, ...]:
    """Preview one relation between two sketches with no existing constraints."""
    return solve_unconstrained_component(sketches, (relation,), relation.first.sketch_id)


def solve_unconstrained_component(
    sketches: tuple[Sketch, ...], relations: tuple[CrossSketchTangency, ...], sketch_id: str
) -> tuple[Sketch, ...]:
    """Preview all linked tangencies without mutating the source sketches."""
    return _solve_component(sketches, relations, sketch_id, allow_constraints=False)


def solve_tangency_component(
    sketches: tuple[Sketch, ...], relations: tuple[CrossSketchTangency, ...], sketch_id: str
) -> tuple[Sketch, ...]:
    """Preview a component, retaining supported existing local constraints."""
    return _solve_component(sketches, relations, sketch_id, allow_constraints=True)


def solve_tangency_component_constraint(
    sketches: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    sketch_id: str,
    constraint: SketchConstraint,
    *,
    allow_tangency: bool = False,
) -> tuple[Sketch, ...]:
    """Preview one dimension change together with its linked tangent geometry."""
    component, selected = resolve_tangency_component(sketches, relations, sketch_id)
    if not selected:
        raise ValueError("尺寸没有关联的跨草图相切分量。")
    supported = (
        "length",
        "distance",
        "radius",
        "diameter",
        "arc_length",
        "angle",
    )
    if allow_tangency:
        supported = (*supported, "tangent")
    if not constraint.driving or constraint.kind not in supported:
        raise ValueError("跨草图联动暂不支持此尺寸类型。")
    source = next(sketch for sketch in component if sketch.sketch_id == sketch_id)
    updated = (
        source.with_updated_constraint(constraint, source.entities)
        if any(item.constraint_id == constraint.constraint_id for item in source.constraints)
        else source.with_constraint(constraint, source.entities)
    )
    candidate = tuple(updated if sketch.sketch_id == sketch_id else sketch for sketch in component)
    return _solve_component(
        candidate,
        relations,
        sketch_id,
        allow_constraints=True,
        edited_dimension=(sketch_id, constraint.constraint_id),
    )


def solve_tangency_component_anchored(
    sketches: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    sketch_id: str,
    anchors: tuple[CrossSketchRef, ...],
    seed_transform: RectangleTransformEvidence | None = None,
) -> tuple[Sketch, ...]:
    """Keep explicitly edited curves fixed while solving the connected component."""
    if not anchors:
        raise ValueError("联动求解必须指定至少一个编辑目标。")
    return _solve_component(
        sketches,
        relations,
        sketch_id,
        allow_constraints=True,
        anchors=anchors,
        seed_transform=seed_transform,
    )


def _solve_component(
    sketches: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    sketch_id: str,
    *,
    allow_constraints: bool,
    anchors: tuple[CrossSketchRef, ...] = (),
    edited_dimension: tuple[str, str] | None = None,
    seed_transform: RectangleTransformEvidence | None = None,
) -> tuple[Sketch, ...]:
    component, selected = resolve_tangency_component(sketches, relations, sketch_id)
    has_constraints = any(sketch.constraints for sketch in component)
    if has_constraints and not allow_constraints:
        raise ValueError("跨草图预览暂不支持已有约束。")
    if not selected:
        return component
    by_id = {sketch.sketch_id: sketch for sketch in component}
    frame = by_id[sketch_id].frame
    projected_dimensions = tuple(
        (sketch.frame, constraint.axis)
        for sketch in component
        for constraint in sketch.constraints
        if constraint.driving
        and constraint.kind in ("length", "distance")
        and constraint.axis != "aligned"
    )
    try:
        for source_frame, dimension_axis in projected_dimensions:
            _map_dimension_axis(dimension_axis, source_frame, frame)
    except ValueError:
        # Choosing a dimension's own frame retains its projection direction.
        # Incompatible dimensions from other frames still fail explicitly.
        frame = projected_dimensions[0][0]
    if has_constraints and any(
        (not constraint.driving and constraint.kind not in DIMENSION_KINDS)
        or (
            constraint.driving
            and constraint.kind
            not in (
                "fixed",
                "horizontal",
                "vertical",
                "length",
                "distance",
                "radius",
                "diameter",
                "arc_length",
                "angle",
                "coincident",
                "parallel",
                "perpendicular",
                "tangent",
                "concentric",
                "equal",
            )
        )
        or (
            constraint.driving
            and constraint.axis
            not in ("aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y")
        )
        or (
            constraint.driving
            and constraint.axis != "aligned"
            and constraint.kind not in ("length", "distance")
        )
        for sketch in component
        for constraint in sketch.constraints
    ):
        raise ValueError("跨草图预览暂不支持此已有约束。")
    references = {
        (reference.sketch_id, reference.entity_id)
        for relation in selected
        for reference in (relation.first, relation.second)
    }
    if has_constraints:
        references.update(
            (sketch.sketch_id, reference.entity_id)
            for sketch in component
            for constraint in sketch.constraints
            if constraint.driving
            for reference in constraint.references
        )
    anchor_keys = {(item.sketch_id, item.entity_id) for item in anchors}
    available = {
        (sketch.sketch_id, entity.entity_id) for sketch in component for entity in sketch.entities
    }
    if len(anchor_keys) != len(anchors) or not anchor_keys.issubset(available):
        raise ValueError("联动求解目标不存在、重复或不属于相切分量。")
    references.update(anchor_keys)
    owners: dict[str, tuple[str, str]] = {}
    originals: dict[
        tuple[str, str], LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
    ] = {}
    projected: list[LineEntity | CircleEntity | ArcEntity | PolylineEntity] = []
    rectangle_axes: list[tuple[str, tuple[float, float], tuple[float, float]]] = []

    def seed(point: tuple[float, float]) -> tuple[float, float]:
        if seed_transform is None:
            return point
        source = by_id[seed_transform.reference.sketch_id].frame
        local = source.world_to_local(frame.local_to_world(point))
        return frame.world_to_local(source.local_to_world(seed_transform.apply(local)))

    for owner_id, entity_id in sorted(references):
        sketch = by_id[owner_id]
        entity = next(item for item in sketch.entities if item.entity_id == entity_id)
        if not isinstance(
            entity, LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
        ):
            raise ValueError("不支持此图元的跨草图相切。")
        if sketch.layers.get(entity.layer_name).locked and (owner_id, entity_id) not in anchor_keys:
            raise ValueError("锁定图层上的图元不能参与求解。")
        if isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            path = PolylineEntity(
                entity.entity_id,
                ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                closed=True,
                construction=entity.construction,
                layer_name=entity.layer_name,
            )
            transformed = project_polyline_entity(path, sketch.frame, frame)
        else:
            transformed = (
                project_polyline_entity(entity, sketch.frame, frame)
                if isinstance(entity, PolylineEntity)
                else project_tangent_entity(entity, sketch.frame, frame)
            )
        if seed_transform is not None and (owner_id, entity_id) not in anchor_keys:
            if isinstance(transformed, LineEntity):
                transformed = replace(
                    transformed,
                    start_mm=seed(transformed.start_mm),
                    end_mm=seed(transformed.end_mm),
                )
            elif isinstance(transformed, PolylineEntity):
                transformed = replace(
                    transformed,
                    points_mm=tuple(seed(point) for point in transformed.points_mm),
                    bulges=tuple(-bulge for bulge in transformed.bulges)
                    if seed_transform.reflected
                    else transformed.bulges,
                )
            elif isinstance(transformed, CircleEntity):
                transformed = replace(transformed, center_mm=seed(transformed.center_mm))
            else:
                angle = math.radians(transformed.start_angle_deg)
                direction = seed(
                    (
                        transformed.center_mm[0] + math.cos(angle),
                        transformed.center_mm[1] + math.sin(angle),
                    )
                )
                center = seed(transformed.center_mm)
                transformed = replace(
                    transformed,
                    center_mm=center,
                    start_angle_deg=math.degrees(
                        math.atan2(direction[1] - center[1], direction[0] - center[0])
                    ),
                    sweep_angle_deg=-transformed.sweep_angle_deg
                    if seed_transform.reflected
                    else transformed.sweep_angle_deg,
                )
        identity = uuid4().hex
        owners[identity] = (owner_id, entity_id)
        originals[(owner_id, entity_id)] = entity
        projected.append(replace(transformed, entity_id=identity, layer_name="0"))
        if isinstance(entity, RectangleEntity):
            rectangle_axes.append(
                (
                    identity,
                    (
                        sum(a * b for a, b in zip(sketch.frame.u_axis, frame.u_axis, strict=True)),
                        sum(a * b for a, b in zip(sketch.frame.u_axis, frame.v_axis, strict=True)),
                    ),
                    (
                        sum(a * b for a, b in zip(sketch.frame.v_axis, frame.u_axis, strict=True)),
                        sum(a * b for a, b in zip(sketch.frame.v_axis, frame.v_axis, strict=True)),
                    ),
                )
            )
    temporary = {owner: identity for identity, owner in owners.items()}
    local_constraints: list[SketchConstraint] = []
    auxiliary_ids: set[str] = set()
    projection_axes: dict[str, tuple[float, float]] = {}
    edit_constraint: SketchConstraint | None = None
    for identity, u_axis, v_axis in rectangle_axes:
        for axis_index, direction in enumerate((u_axis, v_axis)):
            auxiliary_id = uuid4().hex
            auxiliary_ids.add(auxiliary_id)
            projected.append(LineEntity(auxiliary_id, (0, 0), direction, construction=True))
            local_constraints.extend(
                SketchConstraint(
                    uuid4().hex, "fixed", (SketchGeometryReference(auxiliary_id, point),)
                )
                for point in ("start", "end")
            )
            local_constraints.extend(
                SketchConstraint(
                    uuid4().hex,
                    "parallel",
                    (
                        SketchGeometryReference(identity, "segment", edge),
                        SketchGeometryReference(auxiliary_id, "geometry"),
                    ),
                )
                for edge in (axis_index, axis_index + 2)
            )
    for sketch in component:
        for constraint in sketch.constraints:
            if not constraint.driving:
                continue
            try:
                refs = tuple(
                    replace(
                        ref,
                        entity_id=temporary[(sketch.sketch_id, ref.entity_id)],
                        kind="vertex"
                        if isinstance(originals[(sketch.sketch_id, ref.entity_id)], RectangleEntity)
                        and ref.kind == "end"
                        else ref.kind,
                        index=2
                        if isinstance(originals[(sketch.sketch_id, ref.entity_id)], RectangleEntity)
                        and ref.kind == "end"
                        else ref.index,
                    )
                    for ref in constraint.references
                )
            except KeyError as exc:
                raise ValueError("已有约束引用的图元不存在。") from exc
            identity = uuid4().hex
            mapped_projection = None
            if constraint.projection_axis is not None:
                mapped_projection = project_coplanar_vector(
                    constraint.projection_axis, sketch.frame, frame
                )
                projection_axes[identity] = mapped_projection
                axis, axis_sign = constraint.axis, 1.0
            else:
                try:
                    axis, axis_sign = _map_dimension_axis(constraint.axis, sketch.frame, frame)
                except ValueError:
                    direction = (
                        sketch.frame.u_axis
                        if constraint.axis in ("horizontal", "ordinate_x")
                        else sketch.frame.v_axis
                    )
                    projection_axes[identity] = (
                        sum(a * b for a, b in zip(direction, frame.u_axis, strict=True)),
                        sum(a * b for a, b in zip(direction, frame.v_axis, strict=True)),
                    )
                    axis, axis_sign = constraint.axis, 1.0
            mapped_kind = constraint.kind
            if constraint.kind in ("horizontal", "vertical"):
                try:
                    mapped_kind = _map_axis_constraint(constraint.kind, sketch.frame, frame)
                except ValueError:
                    direction = (
                        sketch.frame.u_axis
                        if constraint.kind == "horizontal"
                        else sketch.frame.v_axis
                    )
                    endpoint = (
                        sum(a * b for a, b in zip(direction, frame.u_axis, strict=True)),
                        sum(a * b for a, b in zip(direction, frame.v_axis, strict=True)),
                    )
                    auxiliary_id = uuid4().hex
                    auxiliary_ids.add(auxiliary_id)
                    projected.append(LineEntity(auxiliary_id, (0, 0), endpoint, construction=True))
                    local_constraints.extend(
                        SketchConstraint(
                            uuid4().hex,
                            "fixed",
                            (SketchGeometryReference(auxiliary_id, point),),
                        )
                        for point in ("start", "end")
                    )
                    refs += (SketchGeometryReference(auxiliary_id, "geometry"),)
                    mapped_kind = "parallel"
            mapped = replace(
                constraint,
                constraint_id=identity,
                kind=mapped_kind,
                axis=axis,
                value=(
                    -constraint.value
                    if constraint.kind == "angle"
                    and constraint.value is not None
                    and sum(a * b for a, b in zip(sketch.frame.normal, frame.normal, strict=True))
                    < 0
                    else constraint.value * axis_sign
                    if constraint.value is not None
                    else None
                ),
                references=refs,
                position_mm=None,
                text_position_mm=None,
                layer_name=None,
                projection_axis=mapped_projection,
            )
            if edited_dimension == (sketch.sketch_id, constraint.constraint_id):
                edit_constraint = mapped
            else:
                local_constraints.append(mapped)
    for owner in sorted(anchor_keys):
        original = originals[owner]
        identity = temporary[owner]
        point_kinds: tuple[Literal["start", "end", "center"], ...]
        if isinstance(original, PolylineEntity | RectangleEntity):
            local_constraints.extend(
                SketchConstraint(
                    uuid4().hex, "fixed", (SketchGeometryReference(identity, "vertex", index),)
                )
                for index in range(
                    len(original.points_mm) if isinstance(original, PolylineEntity) else 4
                )
            )
            if isinstance(original, PolylineEntity):
                local_constraints.extend(
                    SketchConstraint(
                        uuid4().hex,
                        "arc_length",
                        (SketchGeometryReference(identity, "segment", index),),
                        polyline_arc_segment(original, index).radius_mm
                        * abs(math.radians(polyline_arc_segment(original, index).sweep_angle_deg)),
                        "mm",
                    )
                    for index, bulge in enumerate(original.bulges)
                    if bulge != 0
                )
            continue
        if isinstance(original, LineEntity):
            point_kinds = ("start", "end")
        elif isinstance(original, CircleEntity):
            point_kinds = ("center",)
            local_constraints.append(
                SketchConstraint(
                    uuid4().hex,
                    "radius",
                    (SketchGeometryReference(identity, "geometry"),),
                    original.radius_mm,
                    "mm",
                )
            )
        else:
            point_kinds = ("center", "start", "end")
        local_constraints.extend(
            SketchConstraint(uuid4().hex, "fixed", (SketchGeometryReference(identity, kind),))
            for kind in point_kinds
        )
    # PlaneGCS preserves its initial side of a line. Seed the opposite side when
    # a mirrored anchored line reverses direction and the free circle is the only
    # other participant; the final branch and finite contact are still validated.
    if anchors and not has_constraints and len(selected) == 1:
        relation = selected[0]
        indices = {entity.entity_id: index for index, entity in enumerate(projected)}
        first_key = (relation.first.sketch_id, relation.first.entity_id)
        second_key = (relation.second.sketch_id, relation.second.entity_id)
        first = tangent_entity_curve(
            projected[indices[temporary[first_key]]], relation.first.segment_index
        )
        second = tangent_entity_curve(
            projected[indices[temporary[second_key]]], relation.second.segment_index
        )
        line_key, line, circle_key, circle = (
            (first_key, first, second_key, second)
            if isinstance(first, LineEntity)
            else (second_key, second, first_key, first)
        )
        free_line = projected[indices[temporary[line_key]]]
        if (
            isinstance(line, LineEntity)
            and isinstance(circle, CircleEntity)
            and isinstance(free_line, PolylineEntity)
            and line_key not in anchor_keys
            and circle_key in anchor_keys
            and relation.branch in ("line_left", "line_right")
            and relation.first_endpoint is None
            and relation.second_endpoint is None
        ):
            dx, dy = line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]
            length = math.hypot(dx, dy)
            if length > 1e-12:
                alignment = sum(
                    a * b
                    for a, b in zip(frame.normal, by_id[line_key[0]].frame.normal, strict=True)
                )
                side = 1.0 if (relation.branch == "line_left") == (alignment > 0) else -1.0
                contact = (
                    circle.center_mm[0] + side * circle.radius_mm * dy / length,
                    circle.center_mm[1] - side * circle.radius_mm * dx / length,
                )
                t = max(
                    0.0,
                    min(
                        1.0,
                        (
                            (contact[0] - line.start_mm[0]) * dx
                            + (contact[1] - line.start_mm[1]) * dy
                        )
                        / (length * length),
                    ),
                )
                offset = (
                    contact[0] - line.start_mm[0] - t * dx,
                    contact[1] - line.start_mm[1] - t * dy,
                )
                projected[indices[temporary[line_key]]] = replace(
                    free_line,
                    points_mm=tuple((x + offset[0], y + offset[1]) for x, y in free_line.points_mm),
                )
        if (
            isinstance(line, LineEntity)
            and isinstance(circle, CircleEntity)
            and line_key in anchor_keys
            and circle_key not in anchor_keys
            and relation.branch in ("line_left", "line_right")
        ):
            dx, dy = line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]
            side = dx * (circle.center_mm[1] - line.start_mm[1]) - dy * (
                circle.center_mm[0] - line.start_mm[0]
            )
            normal_alignment = sum(
                a * b for a, b in zip(frame.normal, by_id[line_key[0]].frame.normal, strict=True)
            )
            if abs(side) <= 1e-12:
                direction = (
                    1.0 if (relation.branch == "line_left") == (normal_alignment > 0) else -1.0
                )
                distance = direction * circle.radius_mm / math.hypot(dx, dy)
                projected[indices[temporary[circle_key]]] = replace(
                    circle,
                    center_mm=(
                        circle.center_mm[0] - distance * dy,
                        circle.center_mm[1] + distance * dx,
                    ),
                )
            elif (side * normal_alignment > 0) != (relation.branch == "line_left"):
                factor = 2 * side / (dx * dx + dy * dy)
                reflected = (circle.center_mm[0] + factor * dy, circle.center_mm[1] - factor * dx)
                projected[indices[temporary[circle_key]]] = replace(circle, center_mm=reflected)
    # Start a new line dimension on the same side of its tangent partner.  A
    # large unconstrained endpoint move can otherwise cross the curved partner before
    # PlaneGCS settles, changing the recorded tangency branch.
    if edit_constraint is not None and not anchors:
        refs = edit_constraint.references
        if (
            len(refs) == 2
            and refs[0].entity_id == refs[1].entity_id
            and {refs[0].kind, refs[1].kind} == {"start", "end"}
            and edit_constraint.value is not None
            and edit_constraint.kind in ("length", "distance")
            and edit_constraint.axis in ("horizontal", "vertical")
        ):
            line_constraints = tuple(
                constraint
                for constraint in local_constraints
                if any(
                    reference.entity_id == refs[0].entity_id for reference in constraint.references
                )
            )
            fixed_ends = {
                constraint.references[0].kind
                for constraint in line_constraints
                if constraint.kind == "fixed" and len(constraint.references) == 1
            }
            safe_line_constraints = len(fixed_ends) <= 1 and all(
                constraint.kind == "fixed"
                and len(constraint.references) == 1
                and constraint.references[0].kind in ("start", "end")
                for constraint in line_constraints
            )
            curve_ids = {
                entity.entity_id
                for entity in projected
                if isinstance(entity, CircleEntity | ArcEntity)
            }
            direct_relations = tuple(
                relation
                for relation in selected
                if any(
                    temporary[(reference.sketch_id, reference.entity_id)] == refs[0].entity_id
                    for reference in (relation.first, relation.second)
                )
            )
            direction = projection_axes.get(edit_constraint.constraint_id)
            if (
                direction is not None
                and safe_line_constraints
                and direct_relations
                and all(
                    relation.first.segment_index is None
                    and relation.second.segment_index is None
                    and any(
                        temporary[(reference.sketch_id, reference.entity_id)] in curve_ids
                        for reference in (relation.first, relation.second)
                    )
                    for relation in direct_relations
                )
            ):
                for index, entity in enumerate(projected):
                    if not isinstance(entity, LineEntity) or entity.entity_id != refs[0].entity_id:
                        continue
                    delta = (
                        entity.end_mm[0] - entity.start_mm[0],
                        entity.end_mm[1] - entity.start_mm[1],
                    )
                    measured = delta[0] * direction[0] + delta[1] * direction[1]
                    if abs(measured) > 1e-9:
                        factor = abs(edit_constraint.value / measured)
                        if factor > 1e-9:
                            if "end" in fixed_ends:
                                projected[index] = replace(
                                    entity,
                                    start_mm=(
                                        entity.end_mm[0] - factor * delta[0],
                                        entity.end_mm[1] - factor * delta[1],
                                    ),
                                )
                            else:
                                projected[index] = replace(
                                    entity,
                                    end_mm=(
                                        entity.start_mm[0] + factor * delta[0],
                                        entity.start_mm[1] + factor * delta[1],
                                    ),
                                )
                    break
    compound = Sketch(uuid4().hex, frame, tuple(projected), tuple(local_constraints))
    endpoint_links: list[EndpointLink] = []
    for relation in selected:
        refs = tuple(
            SketchGeometryReference(
                temporary[(ref.sketch_id, ref.entity_id)],
                "segment" if ref.segment_index is not None else "geometry",
                ref.segment_index,
            )
            for ref in (relation.first, relation.second)
        )
        endpoints = (relation.first_endpoint, relation.second_endpoint)
        if any(endpoint is not None for endpoint in endpoints):
            relation_refs = (relation.first, relation.second)
            index = next(
                (
                    i
                    for i, ref in enumerate(relation_refs)
                    if endpoints[i] is not None
                    and isinstance(resolve_tangent_curve(by_id[ref.sketch_id], ref), ArcEntity)
                ),
                None,
            )
            if index is None:
                raise ValueError("相切端点求解需要指定圆弧端点。")
            endpoint = endpoints[index]
            if endpoint is None:
                raise ValueError("相切端点求解需要指定圆弧端点。")
            endpoint_links.append(
                (
                    relation.relation_id,
                    refs[index],
                    endpoint,
                    refs[1 - index],
                    endpoints[1 - index],
                )
            )
    links = tuple(endpoint_links)
    for relation in selected:
        constraint = SketchConstraint(
            relation.relation_id,
            "tangent",
            tuple(
                SketchGeometryReference(
                    temporary[(ref.sketch_id, ref.entity_id)],
                    "segment" if ref.segment_index is not None else "geometry",
                    ref.segment_index,
                )
                for ref in (relation.first, relation.second)
            ),
        )
        result = solve_sketch_constraint(
            compound, constraint, projection_axes=projection_axes, endpoint_links=links
        )
        if result.status != "success" or result.sketch is None:
            raise ValueError(result.message or "跨草图相切求解失败。")
        compound = result.sketch
    if edited_dimension is not None:
        if edit_constraint is None:
            raise ValueError("联动尺寸不存在。")
        result = solve_sketch_constraint(
            compound, edit_constraint, projection_axes=projection_axes, endpoint_links=links
        )
        if result.status != "success" or result.sketch is None:
            raise ValueError(result.message or "跨草图尺寸求解失败。")
        compound = result.sketch
    replacements: dict[
        tuple[str, str], LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
    ] = {}
    for solved in compound.entities:
        if solved.entity_id in auxiliary_ids:
            continue
        if not isinstance(solved, LineEntity | CircleEntity | ArcEntity | PolylineEntity):
            raise ValueError("跨草图求解产生了不支持的图元。")
        owner = owners[solved.entity_id]
        sketch = by_id[owner[0]]
        original = originals[owner]
        local = (
            project_polyline_entity(solved, frame, sketch.frame)
            if isinstance(solved, PolylineEntity)
            else project_tangent_entity(solved, frame, sketch.frame)
        )
        if isinstance(original, RectangleEntity):
            if not isinstance(local, PolylineEntity) or len(local.points_mm) != 4:
                raise ValueError("跨草图求解未保留矩形路径。")
            a, b, c, d = local.points_mm
            if max(abs(a[1] - b[1]), abs(b[0] - c[0]), abs(c[1] - d[1]), abs(d[0] - a[0])) > 1e-7:
                raise ValueError("跨草图求解未保留矩形直角。")
            restored = replace(original, first_corner_mm=a, opposite_corner_mm=c)
        else:
            restored = replace(
                local,
                entity_id=original.entity_id,
                construction=original.construction,
                layer_name=original.layer_name,
            )
        if owner in anchor_keys:
            if isinstance(original, PolylineEntity) and isinstance(restored, PolylineEntity):
                unchanged = (
                    len(original.bulges) == len(restored.bulges)
                    and all(
                        math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-10)
                        for a, b in zip(original.bulges, restored.bulges, strict=True)
                    )
                    and all(
                        math.dist(a, b) <= 1e-7
                        for a, b in zip(original.points_mm, restored.points_mm, strict=True)
                    )
                )
            elif isinstance(original, RectangleEntity) and isinstance(restored, RectangleEntity):
                unchanged = (
                    max(
                        math.dist(original.first_corner_mm, restored.first_corner_mm),
                        math.dist(original.opposite_corner_mm, restored.opposite_corner_mm),
                    )
                    <= 1e-7
                )
            elif isinstance(original, LineEntity) and isinstance(restored, LineEntity):
                unchanged = (
                    max(
                        math.dist(original.start_mm, restored.start_mm),
                        math.dist(original.end_mm, restored.end_mm),
                    )
                    <= 1e-7
                )
            elif isinstance(original, CircleEntity | ArcEntity) and isinstance(
                restored, CircleEntity | ArcEntity
            ):
                unchanged = (
                    math.dist(original.center_mm, restored.center_mm) <= 1e-7
                    and abs(original.radius_mm - restored.radius_mm) <= 1e-7
                )
                if isinstance(original, ArcEntity) and isinstance(restored, ArcEntity):
                    unchanged = (
                        unchanged
                        and abs(
                            (original.start_angle_deg - restored.start_angle_deg + 180) % 360 - 180
                        )
                        <= 1e-7
                        and abs(original.sweep_angle_deg - restored.sweep_angle_deg) <= 1e-7
                    )
            else:
                unchanged = False
            if not unchanged:
                raise ValueError("联动求解改变了用户指定的编辑目标。")
            restored = original
        replacements[owner] = restored
    result_sketches = tuple(
        validate_sketch_revision_geometry(
            sketch,
            replace(
                sketch,
                entities=tuple(
                    replacements.get((sketch.sketch_id, entity.entity_id), entity)
                    for entity in sketch.entities
                ),
            ),
        )
        for sketch in component
    )
    validate_tangency_component(result_sketches, selected, sketch_id)
    return result_sketches
