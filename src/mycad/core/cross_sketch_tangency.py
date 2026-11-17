# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document-level tangency identities and sketch dependency components."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast
from uuid import UUID, uuid4

from mycad.core.fillet_curves import contact_on_curve, tangent_on_curves
from mycad.core.polyline_curves import polyline_arc_segment
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
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
from mycad.core.sketch_constraints import (
    SketchConstraint,
    SketchGeometryReference,
    is_reference_value_refresh,
)
from mycad.core.sketch_edit import move_entities


@dataclass(frozen=True, slots=True)
class DraftConnectedEndpoint:
    """A draft curve's explicitly connected endpoint."""

    reference: SketchGeometryReference
    endpoint: Literal["start", "end"]

    def __post_init__(self) -> None:
        if self.reference.kind not in ("geometry", "segment") or self.endpoint not in (
            "start",
            "end",
        ):
            raise ValueError("端点连接必须引用曲线或线段及有效端点。")


type DraftTangentEndpoint = str | SketchGeometryReference | DraftConnectedEndpoint
type DraftTangentPair = tuple[DraftTangentEndpoint, DraftTangentEndpoint]


def draft_tangent_reference(endpoint: DraftTangentEndpoint) -> SketchGeometryReference:
    """Normalize legacy entity IDs and indexed segment references."""
    reference = (
        SketchGeometryReference(endpoint, "geometry")
        if isinstance(endpoint, str)
        else endpoint.reference
        if isinstance(endpoint, DraftConnectedEndpoint)
        else endpoint
    )
    if reference.kind not in ("geometry", "segment"):
        raise ValueError("待提交相切关系必须引用完整曲线或多段线段。")
    return reference


type TangencyBranch = Literal[
    "external", "first_contains_second", "second_contains_first", "line_left", "line_right"
]

_BRANCHES = frozenset(
    ("external", "first_contains_second", "second_contains_first", "line_left", "line_right")
)


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a canonical UUID") from exc
    if value not in (parsed.hex, str(parsed)):
        raise ValueError(f"{field} must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class CrossSketchRef:
    """Stable entity identity within a particular sketch."""

    sketch_id: str
    entity_id: str
    segment_index: int | None = None

    def __post_init__(self) -> None:
        _identity(self.sketch_id, "sketch_id")
        _identity(self.entity_id, "entity_id")
        if self.segment_index is not None and (
            isinstance(self.segment_index, bool)
            or not isinstance(cast("object", self.segment_index), int)
            or self.segment_index < 0
        ):
            raise ValueError("segment_index must be a nonnegative integer")

    def to_mapping(self) -> dict[str, object]:
        data: dict[str, object] = {"sketch_id": self.sketch_id, "entity_id": self.entity_id}
        if self.segment_index is not None:
            data["segment_index"] = self.segment_index
        return data

    @classmethod
    def from_mapping(cls, value: object) -> CrossSketchRef:
        if not isinstance(value, Mapping):
            raise ValueError("cross-sketch reference has invalid fields")
        data = cast("Mapping[str, object]", value)
        fields = frozenset(data)
        if fields not in (
            frozenset(("sketch_id", "entity_id")),
            frozenset(("sketch_id", "entity_id", "segment_index")),
        ):
            raise ValueError("cross-sketch reference has invalid fields")
        segment = data.get("segment_index")
        if "segment_index" in data and (
            isinstance(segment, bool) or not isinstance(segment, int) or segment < 0
        ):
            raise ValueError("segment_index must be a nonnegative integer")
        return cls(
            _identity(data["sketch_id"], "sketch_id"),
            _identity(data["entity_id"], "entity_id"),
            cast("int | None", segment),
        )


@dataclass(frozen=True, slots=True)
class RectangleTransformEvidence:
    """Replayable local-plane rigid transform of an identified rectangle."""

    reference: CrossSketchRef
    matrix: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        if (
            not isinstance(cast("object", self.reference), CrossSketchRef)
            or self.reference.segment_index is not None
            or len(self.matrix) != 6
            or any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                for value in cast("tuple[object, ...]", self.matrix)
            )
        ):
            raise ValueError("矩形变换依据无效。")
        a, b, c, d, _, _ = self.matrix
        if not (
            math.isclose(a * a + c * c, 1.0, abs_tol=1e-9, rel_tol=0)
            and math.isclose(b * b + d * d, 1.0, abs_tol=1e-9, rel_tol=0)
            and math.isclose(a * b + c * d, 0.0, abs_tol=1e-9, rel_tol=0)
        ):
            raise ValueError("矩形变换必须是旋转或镜像刚体变换。")

    @property
    def reflected(self) -> bool:
        a, b, c, d, _, _ = self.matrix
        return a * d - b * c < 0

    def apply(self, point: Point2D) -> Point2D:
        a, b, c, d, x, y = self.matrix
        return (a * point[0] + b * point[1] + x, c * point[0] + d * point[1] + y)

    def to_mapping(self) -> dict[str, object]:
        return {"reference": self.reference.to_mapping(), "matrix": list(self.matrix)}

    @classmethod
    def from_mapping(cls, value: object) -> RectangleTransformEvidence:
        if not isinstance(value, Mapping):
            raise ValueError("矩形变换依据字段无效。")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"reference", "matrix"}:
            raise ValueError("矩形变换依据字段无效。")
        raw = data["matrix"]
        if not isinstance(raw, list):
            raise ValueError("矩形变换矩阵无效。")
        values = cast("list[object]", raw)
        if len(values) != 6:
            raise ValueError("矩形变换矩阵无效。")
        return cls(
            CrossSketchRef.from_mapping(data["reference"]),
            cast("tuple[float, float, float, float, float, float]", tuple(values)),
        )


@dataclass(frozen=True, slots=True)
class CrossSketchTangency:
    """Ordered references plus the geometric branch to preserve during solving."""

    relation_id: str
    first: CrossSketchRef
    second: CrossSketchRef
    branch: TangencyBranch
    first_endpoint: Literal["start", "end"] | None = None
    second_endpoint: Literal["start", "end"] | None = None

    def __post_init__(self) -> None:
        _identity(self.relation_id, "relation_id")
        if not isinstance(cast("object", self.first), CrossSketchRef) or not isinstance(
            cast("object", self.second), CrossSketchRef
        ):
            raise ValueError("cross-sketch relation requires two references")
        if self.first.sketch_id == self.second.sketch_id:
            raise ValueError("cross-sketch relation requires different sketches")
        if self.branch not in _BRANCHES:
            raise ValueError("unsupported tangency branch")
        if any(
            item not in (None, "start", "end")
            for item in (self.first_endpoint, self.second_endpoint)
        ):
            raise ValueError("unsupported tangency endpoint")

    def to_mapping(self) -> dict[str, object]:
        data: dict[str, object] = {
            "relation_id": self.relation_id,
            "first": self.first.to_mapping(),
            "second": self.second.to_mapping(),
            "branch": self.branch,
        }
        if self.first_endpoint is not None:
            data["first_endpoint"] = self.first_endpoint
        if self.second_endpoint is not None:
            data["second_endpoint"] = self.second_endpoint
        return data

    @classmethod
    def from_mapping(cls, value: object) -> CrossSketchTangency:
        if not isinstance(value, Mapping):
            raise ValueError("cross-sketch tangency record has missing or unknown fields")
        data = cast("Mapping[str, object]", value)
        required = frozenset(("relation_id", "first", "second", "branch"))
        if not required.issubset(data) or not frozenset(data).issubset(
            required | {"first_endpoint", "second_endpoint"}
        ):
            raise ValueError("cross-sketch tangency record has missing or unknown fields")
        for key in ("first_endpoint", "second_endpoint"):
            if key in data and data[key] not in ("start", "end"):
                raise ValueError("unsupported tangency endpoint")
        branch = data["branch"]
        if not isinstance(branch, str) or branch not in _BRANCHES:
            raise ValueError("unsupported tangency branch")
        return cls(
            _identity(data["relation_id"], "relation_id"),
            CrossSketchRef.from_mapping(data["first"]),
            CrossSketchRef.from_mapping(data["second"]),
            branch,
            cast('Literal["start", "end"] | None', data.get("first_endpoint")),
            cast('Literal["start", "end"] | None', data.get("second_endpoint")),
        )


def tangency_component(
    relations: tuple[CrossSketchTangency, ...], sketch_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return sorted sketch and relation identities in the seed's connected component."""
    _identity(sketch_id, "sketch_id")
    identities = [relation.relation_id for relation in relations]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate cross-sketch relation identity")
    sketches = {sketch_id}
    found: set[str] = set()
    pending = list(relations)
    while pending:
        remaining: list[CrossSketchTangency] = []
        changed = False
        for relation in pending:
            owners = {relation.first.sketch_id, relation.second.sketch_id}
            if sketches.isdisjoint(owners):
                remaining.append(relation)
                continue
            sketches.update(owners)
            found.add(relation.relation_id)
            changed = True
        if not changed:
            break
        pending = remaining
    return tuple(sorted(sketches)), tuple(sorted(found))


def _plane_normal_dot(source: WorkPlaneFrame, target: WorkPlaneFrame) -> float:
    normal_dot = sum(a * b for a, b in zip(source.normal, target.normal, strict=True))
    cross_normal = (
        source.normal[1] * target.normal[2] - source.normal[2] * target.normal[1],
        source.normal[2] * target.normal[0] - source.normal[0] * target.normal[2],
        source.normal[0] * target.normal[1] - source.normal[1] * target.normal[0],
    )
    displacement = tuple(a - b for a, b in zip(source.origin_mm, target.origin_mm, strict=True))
    plane_distance = sum(a * b for a, b in zip(displacement, target.normal, strict=True))
    if math.hypot(*cross_normal) > 1e-9 or abs(plane_distance) > 1e-7:
        raise ValueError("跨草图相切要求工作平面共面。")
    return normal_dot


def project_coplanar_vector(
    vector: Point2D, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> Point2D:
    """Express a displacement in another frame on the same plane."""
    _plane_normal_dot(source, target)

    def component(axis: tuple[float, float, float]) -> float:
        return vector[0] * sum(a * b for a, b in zip(source.u_axis, axis, strict=True)) + vector[
            1
        ] * sum(a * b for a, b in zip(source.v_axis, axis, strict=True))

    return component(target.u_axis), component(target.v_axis)


def project_coplanar_rotation(
    angle: float, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> float:
    """Express the same world-space rotation in another coplanar frame."""
    return angle if _plane_normal_dot(source, target) > 0 else -angle


def project_polyline_entity(
    entity: PolylineEntity, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> PolylineEntity:
    """Project vertices and preserve circular segments across reflected planes."""
    normal_dot = _plane_normal_dot(source, target)
    return replace(
        entity,
        points_mm=tuple(target.world_to_local(source.local_to_world(p)) for p in entity.points_mm),
        bulges=tuple(b if normal_dot > 0 else -b for b in entity.bulges),
    )


def project_tangent_entity(
    entity: LineEntity | CircleEntity | ArcEntity,
    source: WorkPlaneFrame,
    target: WorkPlaneFrame,
) -> LineEntity | CircleEntity | ArcEntity:
    """Transform one finite curve between coincident orthonormal sketch planes."""
    normal_dot = _plane_normal_dot(source, target)

    def project(point: Point2D) -> Point2D:
        return target.world_to_local(source.local_to_world(point))

    if isinstance(entity, LineEntity):
        return replace(entity, start_mm=project(entity.start_mm), end_mm=project(entity.end_mm))
    center = project(entity.center_mm)
    if isinstance(entity, CircleEntity):
        return replace(entity, center_mm=center)
    angle = math.radians(entity.start_angle_deg)
    source_u = math.cos(angle)
    source_v = math.sin(angle)
    direction = tuple(
        source_u * sum(a * b for a, b in zip(source.u_axis, axis, strict=True))
        + source_v * sum(a * b for a, b in zip(source.v_axis, axis, strict=True))
        for axis in (target.u_axis, target.v_axis)
    )
    return replace(
        entity,
        center_mm=center,
        start_angle_deg=math.degrees(math.atan2(direction[1], direction[0])),
        sweep_angle_deg=entity.sweep_angle_deg if normal_dot > 0 else -entity.sweep_angle_deg,
    )


def project_coplanar_entity(
    entity: SketchEntity, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> SketchEntity:
    """Produce view geometry with directed segment identities in source order.

    With differing axes a rectangle becomes a closed polyline so its four
    source edges retain their order under rotation or reflection.
    This is display geometry; the source sketch remains authoritative.
    """
    _plane_normal_dot(source, target)
    if source.u_axis == target.u_axis and source.v_axis == target.v_axis:
        shift = target.world_to_local(source.local_to_world((0.0, 0.0)))
        return move_entities((entity,), (entity.entity_id,), shift, preserve_rectangle_order=True)[
            0
        ]

    def project(point: Point2D) -> Point2D:
        return target.world_to_local(source.local_to_world(point))

    if isinstance(entity, LineEntity | CircleEntity | ArcEntity):
        return project_tangent_entity(entity, source, target)
    if isinstance(entity, PolylineEntity):
        return project_polyline_entity(entity, source, target)
    if isinstance(entity, PointEntity):
        return replace(entity, position_mm=project(entity.position_mm))
    if isinstance(entity, SplineEntity):
        return replace(entity, control_points_mm=tuple(map(project, entity.control_points_mm)))
    first, opposite = entity.first_corner_mm, entity.opposite_corner_mm
    corners = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]))
    return PolylineEntity(
        entity.entity_id,
        tuple(map(project, corners)),
        closed=True,
        construction=entity.construction,
        layer_name=entity.layer_name,
    )


def infer_tangency_branch(
    first: LineEntity | CircleEntity | ArcEntity,
    second: LineEntity | CircleEntity | ArcEntity,
) -> TangencyBranch:
    """Identify the branch of two already tangent curves in one common frame."""
    if not tangent_on_curves(first, second):
        raise ValueError("所选有限曲线不相切。")
    if isinstance(second, LineEntity):
        first, second = second, first
    if isinstance(first, LineEntity) and isinstance(second, CircleEntity | ArcEntity):
        dx = first.end_mm[0] - first.start_mm[0]
        dy = first.end_mm[1] - first.start_mm[1]
        side = dx * (second.center_mm[1] - first.start_mm[1]) - dy * (
            second.center_mm[0] - first.start_mm[0]
        )
        return "line_left" if side > 0 else "line_right"
    if isinstance(first, CircleEntity | ArcEntity) and isinstance(second, CircleEntity | ArcEntity):
        distance = math.dist(first.center_mm, second.center_mm)
        tolerance = max(1e-8, first.radius_mm * 1e-9, second.radius_mm * 1e-9)
        if abs(distance - first.radius_mm - second.radius_mm) <= tolerance:
            return "external"
        return (
            "first_contains_second"
            if first.radius_mm > second.radius_mm
            else "second_contains_first"
        )
    raise ValueError("不支持所选图元的相切关系。")


def resolve_tangent_curve(
    sketch: Sketch, reference: CrossSketchRef
) -> LineEntity | CircleEntity | ArcEntity:
    """Resolve a relation endpoint to its actual finite curve in its owner's plane."""
    if reference.sketch_id != sketch.sketch_id:
        raise ValueError("相切关系引用的草图不匹配。")
    entity = next((item for item in sketch.entities if item.entity_id == reference.entity_id), None)
    if entity is None:
        raise ValueError("相切关系引用的图元不存在。")
    return tangent_entity_curve(entity, reference.segment_index)


def unique_unchanged_polyline_segment(
    previous: PolylineEntity, updated: PolylineEntity, index: int
) -> int | None:
    """Find the sole unchanged directed segment in both polyline states."""

    def signatures(polyline: PolylineEntity) -> tuple[tuple[Point2D, Point2D, float], ...]:
        count = len(polyline.points_mm) if polyline.closed else len(polyline.points_mm) - 1
        return tuple(
            (
                polyline.points_mm[i],
                polyline.points_mm[(i + 1) % len(polyline.points_mm)],
                polyline.bulges[i] if polyline.bulges else 0.0,
            )
            for i in range(count)
        )

    old, new = signatures(previous), signatures(updated)
    if index < 0 or index >= len(old):
        return None
    signature = old[index]
    matches = [i for i, candidate in enumerate(new) if candidate == signature]
    return matches[0] if old.count(signature) == len(matches) == 1 else None


def unique_extended_polyline_segment(
    previous: PolylineEntity, updated: PolylineEntity, index: int
) -> int | None:
    """Prove that one directed straight segment wholly contains the old segment."""
    if (
        previous.entity_id != updated.entity_id
        or previous.layer_name != updated.layer_name
        or previous.construction != updated.construction
    ):
        return None
    old_count = len(previous.points_mm) if previous.closed else len(previous.points_mm) - 1
    if not 0 <= index < old_count or (previous.bulges and previous.bulges[index] != 0):
        return None
    start = previous.points_mm[index]
    end = previous.points_mm[(index + 1) % len(previous.points_mm)]
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 1e-9:
        return None
    count = len(updated.points_mm) if updated.closed else len(updated.points_mm) - 1
    matches: list[int] = []
    for candidate in range(count):
        if updated.bulges and updated.bulges[candidate] != 0:
            continue
        a = updated.points_mm[candidate]
        b = updated.points_mm[(candidate + 1) % len(updated.points_mm)]
        u, v = b[0] - a[0], b[1] - a[1]
        candidate_length = math.hypot(u, v)
        if not math.isfinite(candidate_length) or candidate_length <= 1e-9:
            continue
        tolerance = max(1e-8, length * 1e-10, candidate_length * 1e-10)
        unit_u, unit_v = u / candidate_length, v / candidate_length
        if (dx / length * unit_u + dy / length * unit_v) <= 0:
            continue
        offsets = tuple((point[0] - a[0], point[1] - a[1]) for point in (start, end))
        if any(not math.isfinite(value) for offset in offsets for value in offset):
            continue
        if any(abs(x * unit_v - y * unit_u) > tolerance for x, y in offsets):
            continue
        positions = tuple(x * unit_u + y * unit_v for x, y in offsets)
        if any(not math.isfinite(position) for position in positions):
            continue
        if positions[0] >= -tolerance and positions[1] <= candidate_length + tolerance:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def unique_containing_polyline_arc(
    previous: PolylineEntity, updated: PolylineEntity, index: int
) -> int | None:
    """Prove that exactly one directed circular segment contains the whole old arc."""
    if (
        previous.entity_id != updated.entity_id
        or previous.layer_name != updated.layer_name
        or previous.construction != updated.construction
        or index < 0
        or index >= len(previous.bulges)
        or previous.bulges[index] == 0
    ):
        return None
    original = polyline_arc_segment(previous, index)
    sign = math.copysign(1.0, original.sweep_angle_deg)
    matches: list[int] = []
    for candidate, bulge in enumerate(updated.bulges):
        if bulge == 0 or math.copysign(1.0, bulge) != sign:
            continue
        arc = polyline_arc_segment(updated, candidate)
        tolerance = max(1e-8, original.radius_mm * 1e-10, arc.radius_mm * 1e-10)
        if (
            math.dist(original.center_mm, arc.center_mm) > tolerance
            or abs(original.radius_mm - arc.radius_mm) > tolerance
        ):
            continue
        offset = (sign * (original.start_angle_deg - arc.start_angle_deg)) % 360
        if offset > 360 - 1e-7:
            offset = 0.0
        if offset + abs(original.sweep_angle_deg) <= abs(arc.sweep_angle_deg) + 1e-7:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def unique_retained_tangent_polyline_arc(
    previous: PolylineEntity,
    updated: PolylineEntity,
    index: int,
    other: LineEntity | CircleEntity | ArcEntity,
) -> int | None:
    """Identify a same-circle directed result retaining an existing tangent contact."""
    if (
        previous.entity_id != updated.entity_id
        or previous.layer_name != updated.layer_name
        or previous.construction != updated.construction
        or index < 0
        or index >= len(previous.bulges)
        or previous.bulges[index] == 0
    ):
        return None
    original = polyline_arc_segment(previous, index)
    if not tangent_on_curves(original, other):
        return None
    sign = math.copysign(1.0, original.sweep_angle_deg)
    matches: list[int] = []
    for candidate, bulge in enumerate(updated.bulges):
        if bulge == 0 or math.copysign(1.0, bulge) != sign:
            continue
        arc = polyline_arc_segment(updated, candidate)
        tolerance = max(1e-8, original.radius_mm * 1e-10, arc.radius_mm * 1e-10)
        if (
            math.dist(original.center_mm, arc.center_mm) <= tolerance
            and abs(original.radius_mm - arc.radius_mm) <= tolerance
            and tangent_on_curves(arc, other)
        ):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def unique_retained_relation_arc(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relation: CrossSketchTangency,
    reference: CrossSketchRef,
) -> int | None:
    """Prove a unique retained arc contact with the relation's unchanged other curve."""
    if reference not in (relation.first, relation.second) or reference.segment_index is None:
        return None
    other_ref = relation.second if reference == relation.first else relation.first
    old = {sketch.sketch_id: sketch for sketch in previous}
    new = {sketch.sketch_id: sketch for sketch in updated}
    try:
        old_owner, new_owner = old[reference.sketch_id], new[reference.sketch_id]
        old_other, new_other = old[other_ref.sketch_id], new[other_ref.sketch_id]
        if old_owner.frame != new_owner.frame or old_other.frame != new_other.frame:
            return None
        original = next(
            entity for entity in old_owner.entities if entity.entity_id == reference.entity_id
        )
        revised = next(
            entity for entity in new_owner.entities if entity.entity_id == reference.entity_id
        )
        other = resolve_tangent_curve(old_other, other_ref)
        if other != resolve_tangent_curve(new_other, other_ref):
            return None
        if not isinstance(original, PolylineEntity) or not isinstance(revised, PolylineEntity):
            return None
        projected = project_tangent_entity(other, old_other.frame, old_owner.frame)
        return unique_retained_tangent_polyline_arc(
            original, revised, reference.segment_index, projected
        )
    except (KeyError, StopIteration, ValueError):
        return None


def unique_retained_relation_line(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relation: CrossSketchTangency,
    reference: CrossSketchRef,
) -> int | None:
    """Prove one directed trimmed segment retains the unchanged tangent contact."""
    if reference not in (relation.first, relation.second) or reference.segment_index is None:
        return None
    other_ref = relation.second if reference == relation.first else relation.first
    old = {sketch.sketch_id: sketch for sketch in previous}
    new = {sketch.sketch_id: sketch for sketch in updated}
    try:
        old_owner, new_owner = old[reference.sketch_id], new[reference.sketch_id]
        old_other, new_other = old[other_ref.sketch_id], new[other_ref.sketch_id]
        if old_owner.frame != new_owner.frame or old_other.frame != new_other.frame:
            return None
        original = next(e for e in old_owner.entities if e.entity_id == reference.entity_id)
        revised = next(e for e in new_owner.entities if e.entity_id == reference.entity_id)
        if not isinstance(original, PolylineEntity) or not isinstance(revised, PolylineEntity):
            return None
        other = resolve_tangent_curve(old_other, other_ref)
        if other != resolve_tangent_curve(new_other, other_ref):
            return None
        projected = project_tangent_entity(other, old_other.frame, old_owner.frame)
        old_curve = tangent_entity_curve(original, reference.segment_index)
        if not isinstance(old_curve, LineEntity) or not tangent_on_curves(old_curve, projected):
            return None
        count = len(revised.points_mm) if revised.closed else len(revised.points_mm) - 1
        matches: list[int] = []
        for index in range(count):
            if (
                unique_extended_polyline_segment(revised, original, index)
                != reference.segment_index
            ):
                continue
            if unique_extended_polyline_segment(revised, revised, index) != index:
                continue
            curve = tangent_entity_curve(revised, index)
            if isinstance(curve, LineEntity) and tangent_on_curves(curve, projected):
                matches.append(index)
        return matches[0] if len(matches) == 1 else None
    except (KeyError, StopIteration, ValueError):
        return None


def unique_retained_relation_fragment(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relation: CrossSketchTangency,
    reference: CrossSketchRef,
) -> CrossSketchRef | None:
    """Prove one new polyline fragment uniquely retains the old tangent contact."""
    if reference not in (relation.first, relation.second) or reference.segment_index is None:
        return None
    other_ref = relation.second if reference == relation.first else relation.first
    old = {sketch.sketch_id: sketch for sketch in previous}
    new = {sketch.sketch_id: sketch for sketch in updated}
    try:
        old_owner, new_owner = old[reference.sketch_id], new[reference.sketch_id]
        old_other, new_other = old[other_ref.sketch_id], new[other_ref.sketch_id]
        if old_owner.frame != new_owner.frame or old_other.frame != new_other.frame:
            return None
        original = next(e for e in old_owner.entities if e.entity_id == reference.entity_id)
        if not isinstance(original, PolylineEntity):
            return None
        other = resolve_tangent_curve(old_other, other_ref)
        if other != resolve_tangent_curve(new_other, other_ref):
            return None
        projected = project_tangent_entity(other, old_other.frame, old_owner.frame)
        old_curve = tangent_entity_curve(original, reference.segment_index)
        if not tangent_on_curves(old_curve, projected):
            return None
        old_ids = {entity.entity_id for entity in old_owner.entities}
        matches: list[CrossSketchRef] = []
        for entity in new_owner.entities:
            if not isinstance(entity, PolylineEntity) or (
                entity.entity_id != original.entity_id and entity.entity_id in old_ids
            ):
                continue
            normalized = replace(entity, entity_id=original.entity_id)
            count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
            for index in range(count):
                line_match = (
                    unique_extended_polyline_segment(normalized, original, index)
                    == reference.segment_index
                    and unique_extended_polyline_segment(normalized, normalized, index) == index
                )
                arc_match = (
                    unique_containing_polyline_arc(normalized, original, index)
                    == reference.segment_index
                    and unique_containing_polyline_arc(normalized, normalized, index) == index
                )
                if (line_match or arc_match) and tangent_on_curves(
                    tangent_entity_curve(entity, index), projected
                ):
                    matches.append(
                        replace(reference, entity_id=entity.entity_id, segment_index=index)
                    )
        return matches[0] if len(matches) == 1 else None
    except (KeyError, StopIteration, ValueError):
        return None


def unique_split_line_relation_fragment(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relation: CrossSketchTangency,
    reference: CrossSketchRef,
) -> CrossSketchRef | None:
    """Prove a directed two-piece line split uniquely retains the old contact."""
    if reference not in (relation.first, relation.second) or reference.segment_index is not None:
        return None
    other_ref = relation.second if reference == relation.first else relation.first
    old = {sketch.sketch_id: sketch for sketch in previous}
    new = {sketch.sketch_id: sketch for sketch in updated}
    try:
        owner, revised = old[reference.sketch_id], new[reference.sketch_id]
        old_other, new_other = old[other_ref.sketch_id], new[other_ref.sketch_id]
        if owner.frame != revised.frame or old_other.frame != new_other.frame:
            return None
        original = next(e for e in owner.entities if e.entity_id == reference.entity_id)
        prefix = next(e for e in revised.entities if e.entity_id == reference.entity_id)
        if not isinstance(original, LineEntity) or not isinstance(prefix, LineEntity):
            return None
        if replace(prefix, start_mm=original.start_mm, end_mm=original.end_mm) != original:
            return None
        other = resolve_tangent_curve(old_other, other_ref)
        if other != resolve_tangent_curve(new_other, other_ref):
            return None
        projected = project_tangent_entity(other, old_other.frame, owner.frame)
        if not tangent_on_curves(original, projected):
            return None
        length = math.dist(original.start_mm, original.end_mm)
        first_length = math.dist(original.start_mm, prefix.end_mm)
        last_length = math.dist(prefix.end_mm, original.end_mm)
        dx = original.end_mm[0] - original.start_mm[0]
        dy = original.end_mm[1] - original.start_mm[1]
        offset_x = prefix.end_mm[0] - original.start_mm[0]
        offset_y = prefix.end_mm[1] - original.start_mm[1]
        perpendicular_distance = abs(dx * offset_y - dy * offset_x) / length
        if (
            math.dist(prefix.start_mm, original.start_mm) > 1e-7
            or min(first_length, last_length) <= 1e-7
            or abs(first_length + last_length - length) > 1e-7
            or perpendicular_distance > 1e-7
        ):
            return None
        old_ids = {entity.entity_id for entity in owner.entities}
        suffixes = [
            entity
            for entity in revised.entities
            if isinstance(entity, LineEntity)
            and entity.entity_id not in old_ids
            and replace(
                entity,
                entity_id=original.entity_id,
                start_mm=original.start_mm,
                end_mm=original.end_mm,
            )
            == original
            and math.dist(entity.start_mm, prefix.end_mm) <= 1e-7
            and math.dist(entity.end_mm, original.end_mm) <= 1e-7
        ]
        if len(suffixes) != 1:
            return None
        first_endpoint, second_endpoint = (
            (relation.first_endpoint, relation.second_endpoint)
            if reference == relation.first
            else (relation.second_endpoint, relation.first_endpoint)
        )
        matches = [
            candidate
            for candidate in (prefix, suffixes[0])
            if tangent_on_curves(candidate, projected)
            and tangent_endpoints_satisfied(candidate, projected, first_endpoint, second_endpoint)
        ]
        return replace(reference, entity_id=matches[0].entity_id) if len(matches) == 1 else None
    except (KeyError, StopIteration, ValueError):
        return None


def unique_split_arc_relation_fragment(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relation: CrossSketchTangency,
    reference: CrossSketchRef,
) -> CrossSketchRef | None:
    """Prove a directed arc split uniquely retains the old tangent contact."""
    if reference not in (relation.first, relation.second) or reference.segment_index is not None:
        return None
    other_ref = relation.second if reference == relation.first else relation.first
    old = {sketch.sketch_id: sketch for sketch in previous}
    new = {sketch.sketch_id: sketch for sketch in updated}
    try:
        owner, revised = old[reference.sketch_id], new[reference.sketch_id]
        old_other, new_other = old[other_ref.sketch_id], new[other_ref.sketch_id]
        if owner.frame != revised.frame or old_other.frame != new_other.frame:
            return None
        original = next(e for e in owner.entities if e.entity_id == reference.entity_id)
        prefix = next(e for e in revised.entities if e.entity_id == reference.entity_id)
        if not isinstance(original, ArcEntity) or not isinstance(prefix, ArcEntity):
            return None
        if (
            replace(
                prefix,
                start_angle_deg=original.start_angle_deg,
                sweep_angle_deg=original.sweep_angle_deg,
            )
            != original
        ):
            return None
        if abs(math.remainder(prefix.start_angle_deg - original.start_angle_deg, 360)) > 1e-7:
            return None
        ratio = prefix.sweep_angle_deg / original.sweep_angle_deg
        if not 1e-9 < ratio < 1 - 1e-9:
            return None
        other = resolve_tangent_curve(old_other, other_ref)
        if other != resolve_tangent_curve(new_other, other_ref):
            return None
        projected = project_tangent_entity(other, old_other.frame, owner.frame)
        if not tangent_on_curves(original, projected):
            return None
        old_ids = {entity.entity_id for entity in owner.entities}
        suffixes = [
            entity
            for entity in revised.entities
            if isinstance(entity, ArcEntity)
            and entity.entity_id not in old_ids
            and replace(
                entity,
                entity_id=original.entity_id,
                start_angle_deg=original.start_angle_deg,
                sweep_angle_deg=original.sweep_angle_deg,
            )
            == original
            and abs(
                math.remainder(
                    entity.start_angle_deg - prefix.start_angle_deg - prefix.sweep_angle_deg, 360
                )
            )
            <= 1e-7
            and abs(entity.sweep_angle_deg + prefix.sweep_angle_deg - original.sweep_angle_deg)
            <= 1e-7
        ]
        if len(suffixes) != 1:
            return None
        first_endpoint, second_endpoint = (
            (relation.first_endpoint, relation.second_endpoint)
            if reference == relation.first
            else (relation.second_endpoint, relation.first_endpoint)
        )
        matches = [
            candidate
            for candidate in (prefix, suffixes[0])
            if tangent_on_curves(candidate, projected)
            and tangent_endpoints_satisfied(candidate, projected, first_endpoint, second_endpoint)
        ]
        return replace(reference, entity_id=matches[0].entity_id) if len(matches) == 1 else None
    except (KeyError, StopIteration, ValueError):
        return None


def unique_retained_tangent_fragment(
    original: PolylineEntity,
    candidates: tuple[PolylineEntity, ...],
    index: int,
    other: LineEntity | CircleEntity | ArcEntity,
) -> tuple[str, int] | None:
    """Find one directed fragment that retains an existing finite tangent contact."""
    try:
        if not tangent_on_curves(tangent_entity_curve(original, index), other):
            return None
        matches: list[tuple[str, int]] = []
        for candidate in candidates:
            normalized = replace(candidate, entity_id=original.entity_id)
            count = len(candidate.points_mm) if candidate.closed else len(candidate.points_mm) - 1
            for candidate_index in range(count):
                line_match = (
                    unique_extended_polyline_segment(normalized, original, candidate_index) == index
                    and unique_extended_polyline_segment(normalized, normalized, candidate_index)
                    == candidate_index
                )
                arc_match = (
                    unique_containing_polyline_arc(normalized, original, candidate_index) == index
                    and unique_containing_polyline_arc(normalized, normalized, candidate_index)
                    == candidate_index
                )
                if (line_match or arc_match) and tangent_on_curves(
                    tangent_entity_curve(candidate, candidate_index), other
                ):
                    matches.append((candidate.entity_id, candidate_index))
        return matches[0] if len(matches) == 1 else None
    except ValueError:
        return None


def rebind_retained_local_tangencies(
    previous: Sketch,
    updated: Sketch,
    *,
    allow_fragment_rebind: bool = False,
    allow_split_lines: bool = False,
    allow_split_arcs: bool = False,
    allow_joint_similarity: bool = False,
) -> tuple[SketchConstraint, ...]:
    """Rebind local tangencies to uniquely retained trimmed polyline segments."""
    before = {entity.entity_id: entity for entity in previous.entities}
    after = {entity.entity_id: entity for entity in updated.entities}
    result: list[SketchConstraint] = []
    for constraint in previous.constraints:
        if constraint.kind != "tangent" or constraint.source != "user":
            result.append(constraint)
            continue
        refs = list(constraint.references)
        if previous.frame == updated.frame and all(
            (old := before.get(ref.entity_id)) is not None
            and (new := after.get(ref.entity_id)) is not None
            and type(old) is type(new)
            and replace(new, layer_name=old.layer_name) == old
            for ref in refs
        ):
            result.append(constraint)
            continue
        if allow_split_lines or allow_split_arcs:
            # A v47 mixed picture transform also enables split handling. Prove
            # that the original line and circle share one similarity transform.
            original = tuple(before.get(ref.entity_id) for ref in refs)
            changed = tuple(after.get(ref.entity_id) for ref in refs)
            if (
                allow_joint_similarity
                and len(refs) == 2
                and all(ref.kind == "geometry" and ref.index is None for ref in refs)
                and len([item for item in original if isinstance(item, LineEntity)]) == 1
                and len([item for item in original if isinstance(item, CircleEntity)]) == 1
            ):
                line_pos = 0 if isinstance(original[0], LineEntity) else 1
                circle_pos = 1 - line_pos
                old_line, new_line = original[line_pos], changed[line_pos]
                old_circle, new_circle = original[circle_pos], changed[circle_pos]
                if (
                    isinstance(old_line, LineEntity)
                    and isinstance(new_line, LineEntity)
                    and isinstance(old_circle, CircleEntity)
                    and isinstance(new_circle, CircleEntity)
                ):
                    ux = old_line.end_mm[0] - old_line.start_mm[0]
                    uy = old_line.end_mm[1] - old_line.start_mm[1]
                    vx = new_line.end_mm[0] - new_line.start_mm[0]
                    vy = new_line.end_mm[1] - new_line.start_mm[1]
                    norm = ux * ux + uy * uy
                    similarity = False
                    if norm > 1e-24:
                        cx = old_circle.center_mm[0] - old_line.start_mm[0]
                        cy = old_circle.center_mm[1] - old_line.start_mm[1]
                        for reflected in (False, True):
                            a = (ux * vx - uy * vy if reflected else ux * vx + uy * vy) / norm
                            b = (uy * vx + ux * vy if reflected else ux * vy - uy * vx) / norm
                            x = a * cx + b * cy if reflected else a * cx - b * cy
                            y = b * cx - a * cy if reflected else b * cx + a * cy
                            target = (new_line.start_mm[0] + x, new_line.start_mm[1] + y)
                            if (
                                math.isclose(
                                    target[0], new_circle.center_mm[0], rel_tol=1e-9, abs_tol=1e-8
                                )
                                and math.isclose(
                                    target[1], new_circle.center_mm[1], rel_tol=1e-9, abs_tol=1e-8
                                )
                                and math.isclose(
                                    old_circle.radius_mm * math.hypot(a, b),
                                    new_circle.radius_mm,
                                    rel_tol=1e-9,
                                    abs_tol=1e-8,
                                )
                            ):
                                similarity = True
                                break
                    if (
                        similarity
                        and replace(new_line, start_mm=old_line.start_mm, end_mm=old_line.end_mm)
                        == old_line
                        and replace(
                            new_circle,
                            center_mm=old_circle.center_mm,
                            radius_mm=old_circle.radius_mm,
                        )
                        == old_circle
                        and tangent_on_curves(old_line, old_circle)
                        and tangent_on_curves(new_line, new_circle)
                        and tangent_endpoints_satisfied(
                            new_line if line_pos == 0 else new_circle,
                            new_circle if line_pos == 0 else new_line,
                            constraint.first_endpoint,
                            constraint.second_endpoint,
                        )
                    ):
                        result.append(constraint)
                        continue
            split_positions = [
                i
                for i, ref in enumerate(refs)
                if ref.kind == "geometry"
                and ref.index is None
                and (
                    allow_split_lines
                    and isinstance(before.get(ref.entity_id), LineEntity)
                    or allow_split_arcs
                    and isinstance(before.get(ref.entity_id), ArcEntity)
                )
                and before.get(ref.entity_id) != after.get(ref.entity_id)
            ]
            if split_positions:
                if len(split_positions) != 1:
                    raise ValueError("无法唯一确定相切直线片段。")
                position = split_positions[0]
                ref, other_ref = refs[position], refs[1 - position]
                other = before.get(other_ref.entity_id)
                if other is None or other != after.get(other_ref.entity_id):
                    raise ValueError("相切对象已改变，无法确认打断片段。")
                virtual = Sketch(uuid4().hex, previous.frame, (other,), layers=previous.layers)
                source_ref = CrossSketchRef(previous.sketch_id, ref.entity_id)
                partner_ref = CrossSketchRef(
                    virtual.sketch_id, other_ref.entity_id, other_ref.index
                )
                source_endpoint, partner_endpoint = (
                    (constraint.first_endpoint, constraint.second_endpoint)
                    if position == 0
                    else (constraint.second_endpoint, constraint.first_endpoint)
                )
                relation = CrossSketchTangency(
                    constraint.constraint_id,
                    source_ref,
                    partner_ref,
                    "external",
                    source_endpoint,
                    partner_endpoint,
                )
                proof = (
                    unique_split_line_relation_fragment
                    if isinstance(before.get(ref.entity_id), LineEntity)
                    else unique_split_arc_relation_fragment
                )
                fragment = proof((previous, virtual), (updated, virtual), relation, source_ref)
                if fragment is not None:
                    refs[position] = replace(ref, entity_id=fragment.entity_id)
                    result.append(replace(constraint, references=tuple(refs)))
                    continue
                raise ValueError("无法唯一确定打断后的相切曲线片段。")
        changed = [
            i
            for i, ref in enumerate(refs)
            if isinstance(before.get(ref.entity_id), PolylineEntity)
            and before.get(ref.entity_id) != after.get(ref.entity_id)
        ]
        if not changed:
            result.append(constraint)
            continue
        if len(changed) != 1:
            raise ValueError("无法唯一确定相切段及其切点。")
        position = changed[0]
        ref, other_ref = refs[position], refs[1 - position]
        old, new = before.get(ref.entity_id), after.get(ref.entity_id)
        other = before.get(other_ref.entity_id)
        if (
            ref.kind != "segment"
            or ref.index is None
            or not isinstance(old, PolylineEntity)
            or not isinstance(new, PolylineEntity)
            or other is None
            or other != after.get(other_ref.entity_id)
        ):
            raise ValueError("无法唯一确定相切段及其切点。")
        other_curve = tangent_entity_curve(other, other_ref.index)
        old_curve = tangent_entity_curve(old, ref.index)
        if not tangent_on_curves(old_curve, other_curve):
            raise ValueError("原相切段不包含切点。")
        candidates = (
            tuple(
                entity
                for entity in updated.entities
                if isinstance(entity, PolylineEntity)
                and (entity.entity_id == old.entity_id or entity.entity_id not in before)
            )
            if allow_fragment_rebind
            else (new,)
        )
        matches: list[tuple[str, int]] = []
        for candidate in candidates:
            normalized = replace(candidate, entity_id=old.entity_id)
            count = len(candidate.points_mm) if candidate.closed else len(candidate.points_mm) - 1
            for index in range(count):
                line_match = (
                    unique_extended_polyline_segment(normalized, old, index) == ref.index
                    and unique_extended_polyline_segment(normalized, normalized, index) == index
                )
                arc_match = (
                    unique_containing_polyline_arc(normalized, old, index) == ref.index
                    and unique_containing_polyline_arc(normalized, normalized, index) == index
                )
                if (line_match or arc_match) and tangent_on_curves(
                    tangent_entity_curve(candidate, index), other_curve
                ):
                    matches.append((candidate.entity_id, index))
        if len(matches) != 1:
            raise ValueError("无法唯一确定相切段及其切点。")
        refs[position] = replace(ref, entity_id=matches[0][0], index=matches[0][1])
        rebound = replace(constraint, references=tuple(refs))
        first, second = (tangent_entity_curve(after[item.entity_id], item.index) for item in refs)
        if not tangent_endpoints_satisfied(
            first, second, rebound.first_endpoint, rebound.second_endpoint
        ):
            raise ValueError("修剪不能保留相切端点。")
        result.append(rebound)
    return tuple(result)


def is_retained_local_tangent_rebind(
    old: SketchConstraint,
    new: SketchConstraint,
    previous: Sketch,
    updated: Sketch,
    *,
    allow_split_lines: bool = False,
    allow_split_arcs: bool = False,
) -> bool:
    if old.kind != "tangent" or old.source != "user" or old.references == new.references:
        return False
    try:
        return any(
            item == new and item.constraint_id == old.constraint_id
            for item in rebind_retained_local_tangencies(
                previous,
                updated,
                allow_fragment_rebind=True,
                allow_split_lines=allow_split_lines,
                allow_split_arcs=allow_split_arcs,
            )
        )
    except (KeyError, ValueError):
        return False


def map_transformed_rectangle_segments(
    previous: RectangleEntity,
    updated: SketchEntity,
    transform: Callable[[Point2D], Point2D],
) -> tuple[tuple[int, bool], ...]:
    """Prove each transformed rectangle edge's unique index and direction.

    A non-axis-aligned rotation may convert the rectangle into a closed,
    four-segment polyline.  Each returned pair is the new segment index and
    whether its direction is opposite to the explicitly transformed old edge.
    """
    if previous.entity_id != updated.entity_id or not (
        isinstance(updated, RectangleEntity)
        or (
            isinstance(updated, PolylineEntity)
            and updated.closed
            and len(updated.points_mm) == 4
            and not any(updated.bulges)
        )
    ):
        raise ValueError("变换后的矩形轮廓无效。")
    old_edges = tuple(tangent_entity_curve(previous, index) for index in range(4))
    new_edges = tuple(tangent_entity_curve(updated, index) for index in range(4))
    if not all(isinstance(edge, LineEntity) for edge in (*old_edges, *new_edges)):
        raise ValueError("变换后的矩形边不是直线。")
    old_lines = cast("tuple[LineEntity, ...]", old_edges)
    new_lines = cast("tuple[LineEntity, ...]", new_edges)
    scale = max(math.dist(edge.start_mm, edge.end_mm) for edge in new_lines)
    tolerance = max(1e-7, scale * 1e-10)
    mappings: list[tuple[int, bool]] = []
    for edge in old_lines:
        start, end = transform(edge.start_mm), transform(edge.end_mm)
        if not all(math.isfinite(value) for point in (start, end) for value in point):
            raise ValueError("矩形边变换结果必须有限。")
        matches = [
            (index, reversed_direction)
            for index, candidate in enumerate(new_lines)
            for reversed_direction, (first, second) in (
                (False, (candidate.start_mm, candidate.end_mm)),
                (True, (candidate.end_mm, candidate.start_mm)),
            )
            if math.dist(start, first) <= tolerance and math.dist(end, second) <= tolerance
        ]
        if len(matches) != 1:
            raise ValueError("无法唯一匹配变换后的矩形边。")
        mappings.append(matches[0])
    if len({index for index, _ in mappings}) != 4:
        raise ValueError("变换后的矩形边不唯一。")
    return tuple(mappings)


def rebind_transformed_rectangle_tangency(
    relation: CrossSketchTangency,
    rectangle_reference: CrossSketchRef,
    mapping: tuple[tuple[int, bool], ...],
    reflected: bool,
) -> CrossSketchTangency:
    """Apply a proven edge mapping to one rectangle/curve tangency."""
    index = rectangle_reference.segment_index
    if (
        rectangle_reference not in (relation.first, relation.second)
        or index is None
        or index >= 4
        or len(mapping) != 4
        or {item[0] for item in mapping} != set(range(4))
        or any(not isinstance(cast("object", item[1]), bool) for item in mapping)
        or relation.branch not in ("line_left", "line_right")
    ):
        raise ValueError("矩形相切关系或边映射无效。")
    new_index, reversed_direction = mapping[index]
    reference = replace(rectangle_reference, segment_index=new_index)
    endpoint = (
        relation.first_endpoint
        if relation.first == rectangle_reference
        else relation.second_endpoint
    )
    if reversed_direction and endpoint is not None:
        endpoint = "end" if endpoint == "start" else "start"
    branch = relation.branch
    if reflected != reversed_direction:
        branch = "line_right" if branch == "line_left" else "line_left"
    if relation.first == rectangle_reference:
        return replace(relation, first=reference, first_endpoint=endpoint, branch=branch)
    return replace(relation, second=reference, second_endpoint=endpoint, branch=branch)


def closed_polyline_vertex_rotation_index(
    previous: PolylineEntity, updated: PolylineEntity, index: int
) -> int | None:
    """Resolve an exact cyclic reordering of closed path vertices."""
    count = len(previous.points_mm)
    if (
        not previous.closed
        or not updated.closed
        or len(updated.points_mm) != count
        or not 0 <= index < count
    ):
        return None
    positions = [i for i, point in enumerate(updated.points_mm) if point == previous.points_mm[0]]
    if len(positions) != 1:
        return None
    offset = positions[0]
    if all(previous.points_mm[i] == updated.points_mm[(offset + i) % count] for i in range(count)):
        return (offset + index) % count
    return None


def closed_polyline_rotation_index(
    previous: PolylineEntity, updated: PolylineEntity, index: int
) -> int | None:
    """Resolve a whole closed path's exact cyclic start-vertex rotation."""
    mapped = closed_polyline_vertex_rotation_index(previous, updated, index)
    if mapped is None:
        return None
    count = len(previous.points_mm)
    offset = (mapped - index) % count
    old_bulges = previous.bulges or (0.0,) * count
    new_bulges = updated.bulges or (0.0,) * count
    return (
        mapped
        if all(old_bulges[i] == new_bulges[(offset + i) % count] for i in range(count))
        else None
    )


def split_transform_evidence(
    sketches: tuple[Sketch, ...], evidence: tuple[RectangleTransformEvidence, ...]
) -> tuple[
    tuple[RectangleTransformEvidence, ...],
    tuple[RectangleTransformEvidence, ...],
    tuple[RectangleTransformEvidence, ...],
]:
    """Classify retained transform proofs by their original entity type."""
    entities = {
        (sketch.sketch_id, entity.entity_id): entity
        for sketch in sketches
        for entity in sketch.entities
    }
    groups: tuple[
        list[RectangleTransformEvidence],
        list[RectangleTransformEvidence],
        list[RectangleTransformEvidence],
    ] = ([], [], [])
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.reference.sketch_id, item.reference.entity_id)
        entity = entities.get(key)
        if key in seen:
            raise ValueError("变换依据重复。")
        seen.add(key)
        if isinstance(entity, RectangleEntity):
            groups[0].append(item)
        elif isinstance(entity, PolylineEntity):
            groups[1].append(item)
        elif isinstance(entity, LineEntity):
            groups[2].append(item)
        else:
            raise ValueError("变换依据引用了不支持的图元。")
    return tuple(groups[0]), tuple(groups[1]), tuple(groups[2])


def rebind_committed_tangencies(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
    polyline_transforms: tuple[RectangleTransformEvidence, ...] = (),
    line_transforms: tuple[RectangleTransformEvidence, ...] = (),
    *,
    allow_extended_segments: bool = False,
    allow_extended_arcs: bool = False,
    allow_retained_tangent_arcs: bool = False,
    allow_retained_tangent_lines: bool = False,
    allow_retained_tangent_fragments: bool = False,
    allow_split_line_fragments: bool = False,
    allow_split_arc_fragments: bool = False,
) -> tuple[CrossSketchTangency, ...]:
    """Rebind proven segments, optionally allowing uniquely containing line extensions."""
    before = {
        (sketch.sketch_id, entity.entity_id): entity
        for sketch in previous
        for entity in sketch.entities
    }
    after = {
        (sketch.sketch_id, entity.entity_id): entity
        for sketch in updated
        for entity in sketch.entities
    }
    transforms: dict[
        tuple[str, str], tuple[RectangleTransformEvidence, tuple[tuple[int, bool], ...]]
    ] = {}
    for evidence in rectangle_transforms:
        key = (evidence.reference.sketch_id, evidence.reference.entity_id)
        old, new = before.get(key), after.get(key)
        if key in transforms or not isinstance(old, RectangleEntity) or new is None:
            raise ValueError("矩形变换依据重复或引用无效。")
        transforms[key] = (evidence, map_transformed_rectangle_segments(old, new, evidence.apply))
    curve_proofs: dict[tuple[str, str], RectangleTransformEvidence] = {}
    for evidence in polyline_transforms:
        key = (evidence.reference.sketch_id, evidence.reference.entity_id)
        old, new = before.get(key), after.get(key)
        if (
            key in curve_proofs
            or key in transforms
            or not isinstance(old, PolylineEntity)
            or not isinstance(new, PolylineEntity)
            or len(old.points_mm) != len(new.points_mm)
            or len(old.bulges) != len(new.bulges)
            or replace(old, points_mm=new.points_mm, bulges=new.bulges) != new
            or any(
                math.dist(evidence.apply(point), target) > 1e-7
                for point, target in zip(old.points_mm, new.points_mm, strict=True)
            )
            or any(
                not math.isclose(-a if evidence.reflected else a, b, abs_tol=1e-10, rel_tol=0)
                for a, b in zip(old.bulges, new.bulges, strict=True)
            )
        ):
            raise ValueError("多段线变换依据与修订几何不一致。")
        curve_proofs[key] = evidence
    for evidence in line_transforms:
        key = (evidence.reference.sketch_id, evidence.reference.entity_id)
        old, new = before.get(key), after.get(key)
        if (
            key in curve_proofs
            or key in transforms
            or not isinstance(old, LineEntity)
            or not isinstance(new, LineEntity)
            or replace(old, start_mm=new.start_mm, end_mm=new.end_mm) != new
            or math.dist(evidence.apply(old.start_mm), new.start_mm) > 1e-7
            or math.dist(evidence.apply(old.end_mm), new.end_mm) > 1e-7
        ):
            raise ValueError("直线变换依据与修订几何不一致。")
        curve_proofs[key] = evidence
    result: list[CrossSketchTangency] = []
    frames = {sketch.sketch_id: sketch.frame for sketch in previous}
    for relation in relations:
        rebound = relation
        proofs = {
            curve_proofs[(ref.sketch_id, ref.entity_id)]
            for ref in (relation.first, relation.second)
            if (ref.sketch_id, ref.entity_id) in curve_proofs
        }
        rectangle_proofs = {
            transforms[(ref.sketch_id, ref.entity_id)][0]
            for ref in (relation.first, relation.second)
            if (ref.sketch_id, ref.entity_id) in transforms
        }
        all_proofs = tuple(proofs | rectangle_proofs)
        if len(all_proofs) > 1:
            common = frames[relation.first.sketch_id]

            def world_point(
                proof: RectangleTransformEvidence,
                point: tuple[float, float],
                common_frame: WorkPlaneFrame = common,
            ) -> tuple[float, float, float]:
                frame = frames[proof.reference.sketch_id]
                local = frame.world_to_local(common_frame.local_to_world(point))
                return frame.local_to_world(proof.apply(local))

            first_proof = all_proofs[0]
            if any(
                proof.reflected != first_proof.reflected
                or any(
                    math.dist(world_point(proof, point), world_point(first_proof, point)) > 1e-7
                    for point in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
                )
                for proof in all_proofs[1:]
            ):
                raise ValueError("同一相切关系的变换依据不一致。")
        if (
            proofs
            and not rectangle_proofs
            and next(iter(proofs)).reflected
            and relation.branch in ("line_left", "line_right")
        ):
            rebound = replace(
                rebound, branch="line_right" if relation.branch == "line_left" else "line_left"
            )
        refs: list[CrossSketchRef] = []
        for ref in (relation.first, relation.second):
            old, new = (
                before.get((ref.sketch_id, ref.entity_id)),
                after.get((ref.sketch_id, ref.entity_id)),
            )
            if old is None or new is None:
                raise ValueError("跨草图相切引用的图元不存在。")
            if allow_split_line_fragments and isinstance(old, LineEntity) and old != new:
                split = unique_split_line_relation_fragment(previous, updated, relation, ref)
                if split is not None:
                    refs.append(split)
                    continue
            if allow_split_arc_fragments and isinstance(old, ArcEntity) and old != new:
                split = unique_split_arc_relation_fragment(previous, updated, relation, ref)
                if split is not None:
                    refs.append(split)
                    continue
            if ref.segment_index is not None:
                if allow_retained_tangent_fragments and old != new:
                    fragment = unique_retained_relation_fragment(previous, updated, relation, ref)
                    if fragment is not None and fragment.entity_id != ref.entity_id:
                        refs.append(fragment)
                        continue
                transform = transforms.get((ref.sketch_id, ref.entity_id))
                if transform is not None:
                    evidence, mapping = transform
                    rebound = rebind_transformed_rectangle_tangency(
                        rebound, ref, mapping, evidence.reflected
                    )
                    refs.append(rebound.first if relation.first == ref else rebound.second)
                    continue
                if isinstance(old, RectangleEntity) and isinstance(new, RectangleEntity):
                    if ref.segment_index >= 4:
                        raise ValueError("跨草图相切引用的矩形边无效。")
                    if any(
                        (old.opposite_corner_mm[axis] - old.first_corner_mm[axis])
                        * (new.opposite_corner_mm[axis] - new.first_corner_mm[axis])
                        <= 0
                        for axis in (0, 1)
                    ):
                        raise ValueError("矩形边方向发生变化，无法安全重绑定相切关系。")
                    refs.append(ref)
                    continue
                if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
                    raise ValueError("跨草图相切引用的多段线已变化。")
                index = ref.segment_index
                old_count = len(old.points_mm) if old.closed else len(old.points_mm) - 1
                new_count = len(new.points_mm) if new.closed else len(new.points_mm) - 1
                if index >= old_count:
                    raise ValueError("跨草图相切引用的段无效。")
                rotated = closed_polyline_rotation_index(old, new, index)
                if rotated is not None:
                    ref = replace(ref, segment_index=rotated)
                elif (
                    (vertex_index := closed_polyline_vertex_rotation_index(old, new, index))
                    is not None
                    and vertex_index != index
                ) or (
                    old.closed != new.closed
                    or old_count != new_count
                    or bool(old.bulges and old.bulges[index])
                    != bool(new.bulges and index < len(new.bulges) and new.bulges[index])
                ):
                    matched = unique_unchanged_polyline_segment(old, new, index)
                    if matched is None and allow_extended_segments:
                        matched = unique_extended_polyline_segment(old, new, index)
                    if matched is None and allow_extended_arcs:
                        matched = unique_containing_polyline_arc(old, new, index)
                    if matched is None and allow_retained_tangent_arcs:
                        matched = unique_retained_relation_arc(previous, updated, relation, ref)
                    if matched is None and allow_retained_tangent_lines:
                        matched = unique_retained_relation_line(previous, updated, relation, ref)
                    if matched is None and allow_retained_tangent_fragments:
                        fragment = unique_retained_relation_fragment(
                            previous, updated, relation, ref
                        )
                        if fragment is not None:
                            ref = fragment
                            matched = fragment.segment_index
                    if matched is None:
                        raise ValueError("无法唯一重绑定已提交的相切段。")
                    ref = replace(ref, segment_index=matched)
            refs.append(ref)
        result.append(replace(rebound, first=refs[0], second=refs[1]))
    return tuple(result)


def rebind_committed_tangencies_for_edit(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
    polyline_transforms: tuple[RectangleTransformEvidence, ...] = (),
    line_transforms: tuple[RectangleTransformEvidence, ...] = (),
) -> tuple[tuple[CrossSketchTangency, ...], int]:
    """Use the oldest applicable rebind rule and return its minimum command version."""
    before_ids = {
        (sketch.sketch_id, entity.entity_id) for sketch in previous for entity in sketch.entities
    }
    new_owner_ids = {
        sketch.sketch_id
        for sketch in updated
        for entity in sketch.entities
        if isinstance(entity, PolylineEntity)
        and (sketch.sketch_id, entity.entity_id) not in before_ids
    }
    requires_fragment = any(
        fragment is not None and fragment.entity_id != ref.entity_id
        for relation in relations
        for ref in (relation.first, relation.second)
        if ref.sketch_id in new_owner_ids
        for fragment in (unique_retained_relation_fragment(previous, updated, relation, ref),)
    )
    requires_split_line = any(
        fragment is not None and fragment.entity_id != ref.entity_id
        for relation in relations
        for ref in (relation.first, relation.second)
        for fragment in (unique_split_line_relation_fragment(previous, updated, relation, ref),)
    )
    requires_split_arc = any(
        fragment is not None and fragment.entity_id != ref.entity_id
        for relation in relations
        for ref in (relation.first, relation.second)
        for fragment in (unique_split_arc_relation_fragment(previous, updated, relation, ref),)
    )
    for version, lines, arcs, retained, trimmed_lines, fragments, split_lines, split_arcs in (
        (0, False, False, False, False, False, False, False),
        (35, True, False, False, False, False, False, False),
        (36, True, True, False, False, False, False, False),
        (37, True, True, True, False, False, False, False),
        (40, True, True, True, True, False, False, False),
        (43, True, True, True, True, True, False, False),
        (44, True, True, True, True, True, True, False),
        (46, True, True, True, True, True, True, True),
    ):
        if requires_split_arc and version != 46:
            continue
        if requires_split_line and version not in (44, 46):
            continue
        if requires_fragment and version not in (43, 44, 46):
            continue
        try:
            result = rebind_committed_tangencies(
                previous,
                updated,
                relations,
                rectangle_transforms,
                polyline_transforms,
                line_transforms,
                allow_extended_segments=lines,
                allow_extended_arcs=arcs,
                allow_retained_tangent_arcs=retained,
                allow_retained_tangent_lines=trimmed_lines,
                allow_retained_tangent_fragments=fragments,
                allow_split_line_fragments=split_lines,
                allow_split_arc_fragments=split_arcs,
            )
            return result, version
        except ValueError:
            if version == 46:
                raise
    raise ValueError("无法重绑定相切关系。")


def is_inferred_reference_rebind(
    old: SketchConstraint, new: SketchConstraint, previous: Sketch, updated: Sketch
) -> bool:
    """Recognize a uniquely proven index-only rebind of an inferred relation."""
    if (
        old.source != "inferred"
        or old.kind not in ("coincident", "tangent")
        or old.references == new.references
        or replace(new, references=old.references) != old
    ):
        return False
    old_entities = {entity.entity_id: entity for entity in previous.entities}
    new_entities = {entity.entity_id: entity for entity in updated.entities}
    for before, after in zip(old.references, new.references, strict=True):
        if before == after:
            continue
        if (
            before.entity_id != after.entity_id
            or before.kind != after.kind
            or before.kind not in ("vertex", "segment")
            or before.index is None
            or after.index is None
        ):
            return False
        original, revised = old_entities.get(before.entity_id), new_entities.get(after.entity_id)
        if not isinstance(original, PolylineEntity) or not isinstance(revised, PolylineEntity):
            return False
        if before.kind == "segment":
            if unique_unchanged_polyline_segment(original, revised, before.index) != after.index:
                return False
        else:
            if before.index >= len(original.points_mm) or after.index >= len(revised.points_mm):
                return False
            point = original.points_mm[before.index]
            if (
                original.points_mm.count(point) != 1
                or revised.points_mm.count(point) != 1
                or revised.points_mm[after.index] != point
            ):
                return False
    return True


def rebind_unchanged_user_polyline_constraints(
    previous: Sketch, updated: Sketch, *, include_inferred: bool = False
) -> tuple[SketchConstraint, ...]:
    """Rebind selected references only to uniquely identical polyline parts."""
    old_entities = {entity.entity_id: entity for entity in previous.entities}
    new_entities = {entity.entity_id: entity for entity in updated.entities}
    result: list[SketchConstraint] = []
    for constraint in previous.constraints:
        if constraint.source != "user" and not (
            include_inferred and constraint.kind in ("coincident", "tangent")
        ):
            if include_inferred and any(
                old_entities.get(ref.entity_id) != new_entities.get(ref.entity_id)
                for ref in constraint.references
            ):
                raise ValueError("不支持重绑定该自动约束。")
            result.append(constraint)
            continue
        refs: list[SketchGeometryReference] = []
        for ref in constraint.references:
            old, new = old_entities.get(ref.entity_id), new_entities.get(ref.entity_id)
            if old == new:
                refs.append(ref)
                continue
            if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
                raise ValueError("用户约束引用的图元已改变。")
            if (
                old.closed != new.closed
                or old.layer_name != new.layer_name
                or old.construction != new.construction
            ):
                raise ValueError("用户约束引用的多段线属性已改变。")
            if ref.kind == "vertex" and ref.index is not None and ref.index < len(old.points_mm):
                point = old.points_mm[ref.index]
                matches = [index for index, item in enumerate(new.points_mm) if item == point]
                if old.points_mm.count(point) != 1 or len(matches) != 1:
                    raise ValueError("用户约束顶点已改变或不唯一。")
                refs.append(replace(ref, index=matches[0]))
            elif ref.kind == "segment" and ref.index is not None:
                index = unique_unchanged_polyline_segment(old, new, ref.index)
                if index is None:
                    raise ValueError("用户约束线段已改变或不唯一。")
                refs.append(replace(ref, index=index))
            elif ref.kind in ("start", "end") and not old.closed:
                index = 0 if ref.kind == "start" else -1
                if old.points_mm[index] != new.points_mm[index]:
                    raise ValueError("用户约束端点已改变。")
                refs.append(ref)
            else:
                raise ValueError("用户约束引用的多段线已改变。")
        result.append(replace(constraint, references=tuple(refs)))
    return tuple(result)


def is_unchanged_user_polyline_reference_rebind(
    old: SketchConstraint, new: SketchConstraint, previous: Sketch, updated: Sketch
) -> bool:
    """Prove an index-only user-reference change against both sketch states."""
    if old.source != "user" or old.references == new.references:
        return False
    try:
        proof = rebind_unchanged_user_polyline_constraints(
            replace(previous, constraints=(old,)), updated
        )
    except ValueError:
        return False
    return proof == (new,)


def is_unchanged_inferred_polyline_reference_rebind(
    old: SketchConstraint, new: SketchConstraint, previous: Sketch, updated: Sketch
) -> bool:
    """Prove all referenced geometry remains unchanged for an inferred rebind."""
    if old.source != "inferred" or old.kind not in ("coincident", "tangent"):
        return False
    if old.references == new.references:
        return False
    try:
        proof = rebind_unchanged_user_polyline_constraints(
            replace(previous, constraints=(old,)), updated, include_inferred=True
        )
    except ValueError:
        return False
    return proof == (new,)


def tangent_entity_curve(
    entity: SketchEntity, segment_index: int | None
) -> LineEntity | CircleEntity | ArcEntity:
    """Resolve a whole entity or one indexed path segment to a finite curve."""
    if isinstance(entity, RectangleEntity):
        if segment_index is None or isinstance(segment_index, bool) or not 0 <= segment_index < 4:
            raise ValueError("相切关系必须引用有效的矩形边。")
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        return LineEntity(
            entity.entity_id,
            corners[segment_index],
            corners[(segment_index + 1) % 4],
            entity.construction,
            entity.layer_name,
        )
    if isinstance(entity, PolylineEntity):
        index = segment_index
        count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        if index is None or index >= count:
            raise ValueError("相切关系必须引用有效的多段线段。")
        if entity.bulges and entity.bulges[index] != 0:
            return polyline_arc_segment(entity, index)
        return LineEntity(
            entity.entity_id,
            entity.points_mm[index],
            entity.points_mm[(index + 1) % len(entity.points_mm)],
            entity.construction,
            entity.layer_name,
        )
    if segment_index is not None or not isinstance(entity, LineEntity | CircleEntity | ArcEntity):
        raise ValueError("跨草图相切引用的图元或段不受支持。")
    return entity


def has_rectangle_segment_tangency(sketch: Sketch) -> bool:
    """Return whether a local tangent relation references an indexed rectangle edge."""
    rectangle_ids = {
        entity.entity_id for entity in sketch.entities if isinstance(entity, RectangleEntity)
    }
    return any(
        constraint.kind == "tangent"
        and any(
            ref.kind == "segment" and ref.entity_id in rectangle_ids
            for ref in constraint.references
        )
        for constraint in sketch.constraints
    )


def relations_use_rectangle_segments(
    sketches: tuple[Sketch, ...], relations: tuple[CrossSketchTangency, ...]
) -> bool:
    """Identify cross-sketch relations that use a rectangle's indexed edge."""
    rectangle_ids = {
        (sketch.sketch_id, entity.entity_id)
        for sketch in sketches
        for entity in sketch.entities
        if isinstance(entity, RectangleEntity)
    }
    return any(
        ref.segment_index is not None and (ref.sketch_id, ref.entity_id) in rectangle_ids
        for relation in relations
        for ref in (relation.first, relation.second)
    )


def resolve_tangency_component(
    sketches: tuple[Sketch, ...], relations: tuple[CrossSketchTangency, ...], sketch_id: str
) -> tuple[tuple[Sketch, ...], tuple[CrossSketchTangency, ...]]:
    """Resolve ownership, supported branches and coplanarity before solving."""
    by_id = {sketch.sketch_id: sketch for sketch in sketches}
    if len(by_id) != len(sketches):
        raise ValueError("草图身份不唯一。")
    sketch_ids, relation_ids = tangency_component(relations, sketch_id)
    if any(identity not in by_id for identity in sketch_ids):
        raise ValueError("相切关系引用的草图不存在。")
    component_sketches = tuple(by_id[identity] for identity in sketch_ids)
    selected_ids = set(relation_ids)
    component_relations = tuple(
        sorted(
            (relation for relation in relations if relation.relation_id in selected_ids),
            key=lambda relation: relation.relation_id,
        )
    )
    frame = by_id[sketch_id].frame
    for relation in component_relations:
        entities: list[LineEntity | CircleEntity | ArcEntity] = []
        for reference, endpoint in zip(
            (relation.first, relation.second),
            (relation.first_endpoint, relation.second_endpoint),
            strict=True,
        ):
            sketch = by_id[reference.sketch_id]
            entity = resolve_tangent_curve(sketch, reference)
            if endpoint is not None and not isinstance(entity, LineEntity | ArcEntity):
                raise ValueError("相切端点连接需要直线段或圆弧。")
            project_tangent_entity(entity, sketch.frame, frame)
            entities.append(entity)
        line_count = sum(isinstance(entity, LineEntity) for entity in entities)
        endpoints = (relation.first_endpoint, relation.second_endpoint)
        if any(endpoint is not None for endpoint in endpoints) and not any(
            endpoint is not None and isinstance(entity, ArcEntity)
            for endpoint, entity in zip(endpoints, entities, strict=True)
        ):
            raise ValueError("相切端点连接需要指定圆弧端点。")
        if line_count == 1 and relation.branch not in ("line_left", "line_right"):
            raise ValueError("直线相切分支无效。")
        if line_count == 0 and relation.branch in ("line_left", "line_right"):
            raise ValueError("圆形图元相切分支无效。")
        if line_count == 2:
            raise ValueError("暂不支持两条直线的跨草图相切。")
    return component_sketches, component_relations


def validate_tangency_component(
    sketches: tuple[Sketch, ...], relations: tuple[CrossSketchTangency, ...], sketch_id: str
) -> None:
    """Verify finite-curve contact and the persisted branch in each component relation."""
    component, selected = resolve_tangency_component(sketches, relations, sketch_id)
    by_id = {sketch.sketch_id: sketch for sketch in component}
    for relation in selected:
        first_sketch = by_id[relation.first.sketch_id]
        second_sketch = by_id[relation.second.sketch_id]
        first = resolve_tangent_curve(first_sketch, relation.first)
        second = resolve_tangent_curve(second_sketch, relation.second)
        projected_second = project_tangent_entity(second, second_sketch.frame, first_sketch.frame)
        endpoint_checks: tuple[
            tuple[
                LineEntity | CircleEntity | ArcEntity,
                LineEntity | CircleEntity | ArcEntity,
                Literal["start", "end"] | None,
            ],
            ...,
        ] = (
            (first, projected_second, relation.first_endpoint),
            (projected_second, first, relation.second_endpoint),
        )
        for curve, other, endpoint in endpoint_checks:
            if endpoint is not None and not _endpoint_on_curve(curve, endpoint, other):
                raise ValueError("跨草图相切端点未连接到另一有限曲线。")
        if isinstance(second, LineEntity):
            first, second = second, first
            first_sketch, second_sketch = second_sketch, first_sketch
        projected = project_tangent_entity(second, second_sketch.frame, first_sketch.frame)
        if not tangent_on_curves(first, projected):
            raise ValueError("跨草图图元不满足有限曲线相切。")
        if isinstance(first, LineEntity) and isinstance(projected, CircleEntity | ArcEntity):
            dx = first.end_mm[0] - first.start_mm[0]
            dy = first.end_mm[1] - first.start_mm[1]
            side = dx * (projected.center_mm[1] - first.start_mm[1]) - dy * (
                projected.center_mm[0] - first.start_mm[0]
            )
            if (side > 0) != (relation.branch == "line_left"):
                raise ValueError("跨草图相切分支发生变化。")

        elif isinstance(first, CircleEntity | ArcEntity) and isinstance(
            projected, CircleEntity | ArcEntity
        ):
            distance = math.dist(first.center_mm, projected.center_mm)
            if relation.branch == "external":
                expected = first.radius_mm + projected.radius_mm
            elif relation.branch == "first_contains_second":
                expected = first.radius_mm - projected.radius_mm
            else:
                expected = projected.radius_mm - first.radius_mm
            if expected <= 0 or abs(distance - expected) > max(1e-8, expected * 1e-9):
                raise ValueError("跨草图相切分支发生变化。")


def _endpoint_on_curve(
    curve: LineEntity | CircleEntity | ArcEntity,
    endpoint: Literal["start", "end"],
    other: LineEntity | CircleEntity | ArcEntity,
) -> bool:
    if isinstance(curve, CircleEntity):
        return False
    if isinstance(curve, LineEntity):
        point = curve.start_mm if endpoint == "start" else curve.end_mm
        tolerance = max(1e-8, math.dist(curve.start_mm, curve.end_mm) * 1e-9)
    else:
        angle = math.radians(
            curve.start_angle_deg + (curve.sweep_angle_deg if endpoint == "end" else 0)
        )
        point = (
            curve.center_mm[0] + curve.radius_mm * math.cos(angle),
            curve.center_mm[1] + curve.radius_mm * math.sin(angle),
        )
        tolerance = max(1e-8, curve.radius_mm * 1e-9)
    if isinstance(other, LineEntity):
        dx = other.end_mm[0] - other.start_mm[0]
        dy = other.end_mm[1] - other.start_mm[1]
        length_squared = dx * dx + dy * dy
        position = (
            (point[0] - other.start_mm[0]) * dx + (point[1] - other.start_mm[1]) * dy
        ) / length_squared
        nearest = (other.start_mm[0] + position * dx, other.start_mm[1] + position * dy)
        return -1e-9 <= position <= 1 + 1e-9 and math.dist(point, nearest) <= tolerance
    tolerance = max(tolerance, other.radius_mm * 1e-9)
    return abs(
        math.dist(point, other.center_mm) - other.radius_mm
    ) <= tolerance and contact_on_curve(other, point)


def arc_tangent_endpoint(
    arc: ArcEntity, other: LineEntity | CircleEntity | ArcEntity
) -> Literal["start", "end"]:
    """Resolve the unique endpoint where an already tangent fillet meets a curve."""
    if not tangent_on_curves(arc, other):
        raise ValueError("圆角与来源不是有限曲线相切。")
    endpoints: tuple[Literal["start", "end"], ...] = ("start", "end")
    matches: tuple[Literal["start", "end"], ...] = tuple(
        endpoint for endpoint in endpoints if _endpoint_on_curve(arc, endpoint, other)
    )
    if len(matches) != 1:
        raise ValueError("圆角连接端点不唯一。")
    return matches[0]


def curve_endpoint_at_fillet(
    curve: LineEntity | CircleEntity | ArcEntity, arc: ArcEntity
) -> Literal["start", "end"] | None:
    """Identify a source endpoint already coincident with its fillet contact."""
    if isinstance(curve, CircleEntity):
        return None
    endpoints: tuple[Literal["start", "end"], ...] = ("start", "end")
    matches: tuple[Literal["start", "end"], ...] = tuple(
        endpoint for endpoint in endpoints if _endpoint_on_curve(curve, endpoint, arc)
    )
    return matches[0] if len(matches) == 1 else None


def tangent_endpoints_satisfied(
    first: LineEntity | CircleEntity | ArcEntity,
    second: LineEntity | CircleEntity | ArcEntity,
    first_endpoint: Literal["start", "end"] | None,
    second_endpoint: Literal["start", "end"] | None,
) -> bool:
    """Check explicit finite-curve endpoint contacts for a tangent relation."""
    endpoints = (first_endpoint, second_endpoint)
    curves = (first, second)
    if not any(endpoint is not None for endpoint in endpoints):
        return True
    if not any(
        endpoint is not None and isinstance(curve, ArcEntity)
        for endpoint, curve in zip(endpoints, curves, strict=True)
    ):
        return False
    return (first_endpoint is None or _endpoint_on_curve(first, first_endpoint, second)) and (
        second_endpoint is None or _endpoint_on_curve(second, second_endpoint, first)
    )


def rectangle_transform_kind_change_allowed(
    sketch: Sketch,
    previous: SketchEntity,
    updated: SketchEntity,
    evidence: RectangleTransformEvidence | None,
) -> bool:
    """Prove the transformed path preserves all existing local references."""
    if (
        evidence is None
        or evidence.reference.sketch_id != sketch.sketch_id
        or evidence.reference.entity_id != previous.entity_id
        or not isinstance(previous, RectangleEntity)
        or not isinstance(updated, PolylineEntity)
        or previous.construction != updated.construction
        or previous.layer_name != updated.layer_name
    ):
        return False
    return rectangle_transform_local_references_preserved(sketch, previous, updated, evidence)


def rectangle_transform_local_references_preserved(
    sketch: Sketch,
    previous: RectangleEntity,
    updated: SketchEntity,
    evidence: RectangleTransformEvidence,
) -> bool:
    """Check existing local references follow the same transformed edges and vertices."""
    if (
        evidence.reference.sketch_id != sketch.sketch_id
        or evidence.reference.entity_id != previous.entity_id
    ):
        return False
    mapping = map_transformed_rectangle_segments(previous, updated, evidence.apply)
    for constraint in sketch.constraints:
        for reference in constraint.references:
            if reference.entity_id != previous.entity_id:
                continue
            if reference.kind == "start":
                index = 0
                expected_vertex = 0
            elif reference.kind == "end":
                index = 2
                expected_vertex = 2 if isinstance(updated, RectangleEntity) else 3
            elif reference.kind == "vertex" and reference.index is not None:
                index = reference.index
                expected_vertex = index
            elif reference.kind == "segment" and reference.index is not None:
                index = reference.index
                if not 0 <= index < 4 or mapping[index] != (index, False):
                    return False
                continue
            else:
                return False
            if not 0 <= index < 4:
                return False
            new_index, reversed_direction = mapping[index]
            if (new_index + int(reversed_direction)) % 4 != expected_vertex:
                return False
    return True


def rebind_rectangle_local_constraints(
    sketch: Sketch,
    updated: SketchEntity,
    evidence: RectangleTransformEvidence,
) -> tuple[SketchConstraint, ...]:
    """Map local rectangle references to the corresponding transformed edges and vertices."""
    previous = next(
        (item for item in sketch.entities if item.entity_id == evidence.reference.entity_id), None
    )
    if evidence.reference.sketch_id != sketch.sketch_id or not isinstance(
        previous, RectangleEntity
    ):
        raise ValueError("矩形变换依据引用无效。")
    mapping = map_transformed_rectangle_segments(previous, updated, evidence.apply)
    result: list[SketchConstraint] = []
    for constraint in sketch.constraints:
        references: list[SketchGeometryReference] = []
        endpoints = [constraint.first_endpoint, constraint.second_endpoint]
        anchor_mode = constraint.anchor_mode
        for position, reference in enumerate(constraint.references):
            if reference.entity_id != previous.entity_id:
                references.append(reference)
                continue
            if reference.kind == "segment" and reference.index is not None:
                if reference.index >= 4:
                    raise ValueError("矩形边引用无效。")
                index, reversed_direction = mapping[reference.index]
                references.append(replace(reference, index=index))
                if reversed_direction:
                    if position < len(endpoints) and endpoints[position] is not None:
                        endpoints[position] = "end" if endpoints[position] == "start" else "start"
                    if len(constraint.references) == 1 and anchor_mode in ("start", "end"):
                        anchor_mode = "end" if anchor_mode == "start" else "start"
                continue
            if reference.kind == "start":
                vertex = 0
            elif reference.kind == "end":
                vertex = 2
            elif reference.kind == "vertex" and reference.index is not None:
                vertex = reference.index
            else:
                raise ValueError("矩形本地约束引用无法重绑定。")
            if not 0 <= vertex < 4:
                raise ValueError("矩形顶点引用无效。")
            index, reversed_direction = mapping[vertex]
            mapped_vertex = (index + int(reversed_direction)) % 4
            if (
                reference.kind == "start"
                and mapped_vertex == 0
                or (
                    reference.kind == "end"
                    and mapped_vertex == (2 if isinstance(updated, RectangleEntity) else 3)
                )
            ):
                references.append(reference)
            else:
                references.append(
                    SketchGeometryReference(previous.entity_id, "vertex", mapped_vertex)
                )
        rebound = replace(
            constraint,
            references=tuple(references),
            first_endpoint=endpoints[0],
            second_endpoint=endpoints[1],
            anchor_mode=anchor_mode,
        )
        result.append(rebound)
    return tuple(result)


def rebind_rectangle_constraints_for_sketch(
    previous: Sketch,
    updated: Sketch,
    transforms: tuple[RectangleTransformEvidence, ...],
) -> tuple[SketchConstraint, ...]:
    """Compute the only permitted local-constraint changes for rectangle transforms."""
    constraints = previous.constraints
    updated_entities = {entity.entity_id: entity for entity in updated.entities}
    for evidence in transforms:
        if evidence.reference.sketch_id != previous.sketch_id:
            continue
        entity = updated_entities.get(evidence.reference.entity_id)
        if entity is None:
            raise ValueError("矩形变换目标不存在。")
        constraints = rebind_rectangle_local_constraints(
            replace(previous, constraints=constraints), entity, evidence
        )
    return constraints


def build_tangency_revisions(
    original: tuple[Sketch, ...],
    proposed: tuple[Sketch, ...],
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
    *,
    allow_local_rebind: bool = False,
    allow_user_polyline_rebind: bool = False,
    allow_inferred_polyline_rebind: bool = False,
) -> tuple[dict[str, object], ...]:
    """Freeze identity-preserving sketch changes with stale-preview digests."""
    before = {sketch.sketch_id: sketch for sketch in original}
    after = {sketch.sketch_id: sketch for sketch in proposed}
    if len(before) != len(original) or len(after) != len(proposed) or set(before) != set(after):
        raise ValueError("跨草图候选的草图身份不一致。")
    evidence_by_key = {
        (item.reference.sketch_id, item.reference.entity_id): item for item in rectangle_transforms
    }
    if len(evidence_by_key) != len(rectangle_transforms):
        raise ValueError("矩形变换依据重复。")
    revisions: list[dict[str, object]] = []
    for identity in sorted(before):
        base, candidate = before[identity], after[identity]
        expected_constraints = (
            rebind_rectangle_constraints_for_sketch(base, candidate, rectangle_transforms)
            if allow_local_rebind
            else base.constraints
        )
        if (
            base.frame != candidate.frame
            or base.layers != candidate.layers
            or base.support_face != candidate.support_face
            or len(base.constraints) != len(candidate.constraints)
            or any(
                expected != actual
                and not is_reference_value_refresh(expected, actual)
                and not (
                    allow_user_polyline_rebind
                    and is_unchanged_user_polyline_reference_rebind(
                        expected, actual, base, candidate
                    )
                )
                and not (
                    allow_inferred_polyline_rebind
                    and is_unchanged_inferred_polyline_reference_rebind(
                        expected, actual, base, candidate
                    )
                )
                for expected, actual in zip(
                    expected_constraints, candidate.constraints, strict=True
                )
            )
        ):
            raise ValueError("跨草图候选不得修改工作平面、图层或已有约束。")
        if len(base.entities) != len(candidate.entities) or any(
            old.entity_id != new.entity_id
            or old.construction != new.construction
            or old.layer_name != new.layer_name
            or (
                type(old) is not type(new)
                and not (
                    allow_local_rebind
                    and isinstance(old, RectangleEntity)
                    and isinstance(new, PolylineEntity)
                    and evidence_by_key.get((identity, old.entity_id)) is not None
                )
                and not rectangle_transform_kind_change_allowed(
                    base, old, new, evidence_by_key.get((identity, old.entity_id))
                )
            )
            for old, new in zip(base.entities, candidate.entities, strict=True)
        ):
            raise ValueError("跨草图候选必须保留图元身份、类型和图层。")
        for old, new in zip(base.entities, candidate.entities, strict=True):
            evidence = evidence_by_key.get((identity, old.entity_id))
            if (
                not allow_local_rebind
                and evidence is not None
                and isinstance(old, RectangleEntity)
                and not rectangle_transform_local_references_preserved(base, old, new, evidence)
            ):
                raise ValueError("矩形变换会改变本地约束引用的边或顶点。")
        if base == candidate:
            continue
        state = candidate.to_state_mapping()
        revisions.append(
            {
                "sketch_id": identity,
                "base_state_sha256": base.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    return tuple(revisions)
