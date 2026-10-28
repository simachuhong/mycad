# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Durable drawing references describe geometry, never runtime topology IDs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

if TYPE_CHECKING:
    from mycad.core.drawing_projection import ProjectedCurve, ProjectionResult

ReferenceStatus = Literal["resolved", "orphaned", "ambiguous"]


@dataclass(frozen=True, slots=True)
class DrawingGeometryReference:
    """Bounded source predicate plus the requested projected point/curve role.

    An optional original command audit key narrows the owner; geometry must
    still resolve uniquely after replay. A curve index is deliberately absent.
    """

    kind: Literal["cylindrical_face", "planar_face", "edge", "sketch_entity"]
    parameters: tuple[tuple[str, float], ...] = ()
    owner_command: str | None = None
    role: Literal["geometry", "start", "end", "center"] = "geometry"

    sketch_id: str | None = None
    entity_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "sketch_entity":
            for identity in (self.sketch_id, self.entity_id):
                if identity is None:
                    raise ValueError("sketch reference requires sketch and entity identities")
                parsed = UUID(identity)
                if identity not in (str(parsed), parsed.hex):
                    raise ValueError("expected canonical sketch reference UUID")
        elif self.sketch_id is not None or self.entity_id is not None:
            raise ValueError("solid reference cannot carry sketch identities")
        if self.kind not in ("cylindrical_face", "planar_face", "edge", "sketch_entity"):
            raise ValueError("unsupported drawing reference kind")
        if self.role not in ("geometry", "start", "end", "center"):
            raise ValueError("unsupported drawing reference role")
        names = [key for key, _ in self.parameters]
        if len(set(names)) != len(names) or any(not name for name in names):
            raise ValueError("reference predicate names must be unique and nonempty")
        if any(isinstance(value, bool) or not math.isfinite(value) for _, value in self.parameters):
            raise ValueError("reference predicates must be finite numbers")


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    status: ReferenceStatus
    curve_ids: tuple[str, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("resolved", "orphaned", "ambiguous"):
            raise ValueError("invalid reference status")
        if (self.status == "resolved") != bool(self.curve_ids):
            raise ValueError("only uniquely resolved references carry projected curves")


def same_source(a: DrawingGeometryReference, b: DrawingGeometryReference) -> bool:
    """Exact predicate family with numerical tolerance, never closest candidate."""
    if (
        a.kind != b.kind
        or a.owner_command != b.owner_command
        or a.sketch_id != b.sketch_id
        or a.entity_id != b.entity_id
    ):
        return False
    left = {k: v for k, v in a.parameters if not k.startswith("projected_")}
    right = {k: v for k, v in b.parameters if not k.startswith("projected_")}
    return left.keys() == right.keys() and all(
        math.isclose(value, right[key], rel_tol=1e-9, abs_tol=1e-6) for key, value in left.items()
    )


def _curve_predicate(curve: ProjectedCurve) -> tuple[tuple[str, float], ...]:
    from mycad.core.drawing_projection import ArcCurve, EllipseCurve, LineCurve

    geometry = curve.geometry
    if isinstance(geometry, LineCurve):
        a, b = sorted((geometry.start, geometry.end))
        length = math.dist(a, b)
        if length <= 1e-9:
            raise ValueError("不能关联零长线")
        return (
            ("projected_type", 1),
            ("projected_dx", (b[0] - a[0]) / length),
            ("projected_dy", (b[1] - a[1]) / length),
        )
    if isinstance(geometry, ArcCurve):
        return (("projected_type", 2),)
    if isinstance(geometry, EllipseCurve):
        return (("projected_type", 3),)
    return (("projected_type", 4),)


def reference_for_curve(
    curve: ProjectedCurve, *, role: Literal["geometry", "start", "end", "center"] = "geometry"
) -> DrawingGeometryReference:
    if curve.source is None:
        raise ValueError("此曲线没有可持久关联的来源证据，请选择其他几何")
    predicate = _curve_predicate(curve)
    if curve.source.kind == "sketch_entity":
        predicate = tuple((key, value) for key, value in predicate if key == "projected_type")
    return DrawingGeometryReference(
        curve.source.kind,
        (*curve.source.parameters, *predicate),
        curve.source.owner_command,
        role,
        curve.source.sketch_id,
        curve.source.entity_id,
    )


def resolve_reference(
    reference: DrawingGeometryReference, result: ProjectionResult
) -> ReferenceResolution:
    candidates: list[ProjectedCurve] = []
    wanted = {k: v for k, v in reference.parameters if k.startswith("projected_")}
    for curve in result.curves:
        if curve.source is None or not same_source(reference, curve.source):
            continue
        actual = dict(_curve_predicate(curve))
        if all(
            k in actual and math.isclose(v, actual[k], abs_tol=1e-6, rel_tol=1e-9)
            for k, v in wanted.items()
        ):
            candidates.append(curve)
    if not candidates:
        return ReferenceResolution(
            "orphaned", message="原几何已删除或超出可关联的几何变化范围，请重附着"
        )
    if len(candidates) != 1 or candidates[0].source_count != 1:
        return ReferenceResolution(
            "ambiguous", message="存在多个相同来源候选，不能自动选择；请重附着到可唯一识别的几何"
        )
    return ReferenceResolution("resolved", (candidates[0].curve_id,))
