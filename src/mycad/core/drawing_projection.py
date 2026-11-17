# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact drawing geometry and frozen paper scenes, without Qt or CAD imports."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from mycad.core.drawing_references import DrawingGeometryReference

if TYPE_CHECKING:
    from mycad.core.drawing import DrawingAnnotation, DrawingNote, DrawingState
    from mycad.core.drawing_annotations import SceneAnnotation
    from mycad.core.drawing_detail import DetailRegion
    from mycad.core.drawing_section import SectionPlane
    from mycad.core.drawing_templates import DrawingTemplate

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
ViewDirection = Literal["front", "back", "top", "bottom", "left", "right"]


def finite(values: Sequence[float], name: str) -> None:
    if any(isinstance(value, bool) or not math.isfinite(value) for value in values):
        raise ValueError(f"{name} must contain finite numbers")


def _dot(a: Point3, b: Point3) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a: Point3, b: Point3) -> Point3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _neg(a: Point3) -> Point3:
    return (-a[0], -a[1], -a[2])


def _unit(a: Point3) -> Point3:
    finite(a, "direction")
    length = math.sqrt(_dot(a, a))
    if length < 1e-12:
        raise ValueError("direction cannot be zero")
    return (a[0] / length, a[1] / length, a[2] / length)


@dataclass(frozen=True, slots=True)
class ViewBasis:
    """Observer-facing normal; right cross up equals normal. Default is front."""

    right: Point3 = (1, 0, 0)
    up: Point3 = (0, 0, 1)
    normal: Point3 = (0, -1, 0)

    def __post_init__(self) -> None:
        for axis in (self.right, self.up, self.normal):
            finite(axis, "basis")
            if not math.isclose(_dot(axis, axis), 1, abs_tol=1e-9):
                raise ValueError("basis vectors must be unit length")
        if any(
            abs(x - y) > 1e-9 for x, y in zip(_cross(self.right, self.up), self.normal, strict=True)
        ):
            raise ValueError("basis must be orthonormal and right handed")

    @classmethod
    def from_normal_up(cls, normal: Point3, up: Point3) -> ViewBasis:
        n = _unit(normal)
        right = _unit(_cross(up, n))
        return cls(right, _cross(n, right), n)

    def project(self, point: Point3) -> Point2:
        finite(point, "model point")
        return (_dot(point, self.right), _dot(point, self.up))


def projected_basis(parent: ViewBasis, direction: ViewDirection) -> ViewBasis:
    r, u, n = parent.right, parent.up, parent.normal
    bases = {
        "front": parent,
        "back": ViewBasis(_neg(r), u, _neg(n)),
        "top": ViewBasis(r, _neg(n), u),
        "bottom": ViewBasis(r, n, _neg(u)),
        "left": ViewBasis(n, u, _neg(r)),
        "right": ViewBasis(_neg(n), u, r),
    }
    if direction not in bases:
        raise ValueError("unsupported view direction")
    return bases[direction]


@dataclass(frozen=True, slots=True)
class LineCurve:
    start: Point2
    end: Point2

    def __post_init__(self) -> None:
        finite((*self.start, *self.end), "line")
        if self.length < 1e-12:
            raise ValueError("projected line cannot have zero length")

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True, slots=True)
class ArcCurve:
    center: Point2
    radius: float
    start_deg: float = 0
    sweep_deg: float = 360

    def __post_init__(self) -> None:
        finite((*self.center, self.radius, self.start_deg, self.sweep_deg), "arc")
        if self.radius <= 0 or not 0 < abs(self.sweep_deg) <= 360:
            raise ValueError("arc radius/sweep invalid")


@dataclass(frozen=True, slots=True)
class EllipseCurve:
    center: Point2
    major_radius: float
    minor_radius: float
    rotation_deg: float = 0
    start_deg: float = 0
    sweep_deg: float = 360

    def __post_init__(self) -> None:
        finite(
            (
                *self.center,
                self.major_radius,
                self.minor_radius,
                self.rotation_deg,
                self.start_deg,
                self.sweep_deg,
            ),
            "ellipse",
        )
        if not 0 < self.minor_radius <= self.major_radius or not 0 < abs(self.sweep_deg) <= 360:
            raise ValueError("ellipse radii/sweep invalid")


@dataclass(frozen=True, slots=True)
class SplineCurve:
    poles: tuple[Point2, ...]
    degree: int
    knots: tuple[float, ...]
    multiplicities: tuple[int, ...]
    weights: tuple[float, ...]
    periodic: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.degree, bool) or self.degree < 1 or len(self.poles) <= self.degree:
            raise ValueError("spline degree/poles invalid")
        for point in self.poles:
            finite(point, "spline pole")
        finite((*self.knots, *self.weights), "spline parameters")
        if len(self.weights) != len(self.poles) or any(weight <= 0 for weight in self.weights):
            raise ValueError("spline weights invalid")
        if len(self.knots) < 2 or len(self.knots) != len(self.multiplicities):
            raise ValueError("spline knots/multiplicities invalid")
        if any(b <= a for a, b in zip(self.knots, self.knots[1:], strict=False)):
            raise ValueError("spline knots must increase")
        if any(isinstance(m, bool) or not 1 <= m <= self.degree + 1 for m in self.multiplicities):
            raise ValueError("spline multiplicities invalid")
        if not self.periodic and sum(self.multiplicities) != len(self.poles) + self.degree + 1:
            raise ValueError("spline knot count invalid")


CurveGeometry = LineCurve | ArcCurve | EllipseCurve | SplineCurve


@dataclass(frozen=True, slots=True)
class ProjectedCurve:
    curve_id: str
    geometry: CurveGeometry
    visibility: Literal["visible", "hidden", "tangent"] = "visible"
    source: DrawingGeometryReference | None = None
    silhouette: bool = False
    source_count: int = 1

    def __post_init__(self) -> None:
        if not self.curve_id or self.visibility not in ("visible", "hidden", "tangent"):
            raise ValueError("invalid projected curve identity or visibility")


@dataclass(frozen=True, slots=True)
class DrawingProjectionRequest:
    view_id: UUID
    source_fingerprint: str
    generation: int
    basis: ViewBasis = ViewBasis()
    source: Literal["current_part", "sketch"] = "current_part"
    sketch_id: str | None = None
    section: SectionPlane | None = None
    hatch_spacing_mm: float = 2.5
    detail: DetailRegion | None = None

    def __post_init__(self) -> None:
        from mycad.core.drawing import SourceBinding

        SourceBinding(self.source, self.sketch_id)
        if not self.source_fingerprint or self.generation < 0:
            raise ValueError("invalid drawing projection request")
        finite((self.hatch_spacing_mm,), "hatch spacing")
        if self.hatch_spacing_mm <= 0:
            raise ValueError("hatch spacing must be positive")
        if self.section is not None and (
            self.source != "current_part" or self.basis != self.section.basis
        ):
            raise ValueError("section request requires the part and section basis")
        if self.detail is not None and (self.source != "current_part" or self.section is not None):
            raise ValueError("detail request requires an ordinary part projection")


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    view_id: UUID
    source_fingerprint: str
    generation: int
    curves: tuple[ProjectedCurve, ...]
    diagnostics: tuple[str, ...] = ()
    hatch: tuple[LineCurve, ...] = ()

    def __post_init__(self) -> None:
        ids = [curve.curve_id for curve in self.curves]
        if len(ids) != len(set(ids)):
            raise ValueError("projected curve ids must be unique per result")


class DrawingProjectionPort(Protocol):
    def project_drawing(self, request: DrawingProjectionRequest) -> ProjectionResult: ...


@dataclass(frozen=True, slots=True)
class SceneView:
    view_id: UUID
    anchor_mm: Point2
    scale: float
    curves: tuple[ProjectedCurve, ...]
    hatch: tuple[LineCurve, ...] = ()

    def to_paper(self, point: Point2) -> Point2:
        return (
            self.anchor_mm[0] + self.scale * point[0],
            self.anchor_mm[1] + self.scale * point[1],
        )


@dataclass(frozen=True, slots=True)
class SectionMarker:
    label: str
    start_mm: Point2
    end_mm: Point2
    observer_side: Literal["left", "right"]
    view_label_mm: Point2


@dataclass(frozen=True, slots=True)
class DetailMarker:
    label: str
    source_center_mm: Point2
    source_radius_mm: float
    view_center_mm: Point2
    view_radius_mm: float
    view_scale: float


@dataclass(frozen=True, slots=True)
class DrawingScene:
    sheet_id: UUID
    size_mm: Point2
    margin_mm: float
    title: tuple[tuple[str, str], ...]
    views: tuple[SceneView, ...]
    annotations: tuple[DrawingAnnotation, ...] = ()
    issues: tuple[str, ...] = ()
    source_fingerprint: str = ""
    resolved_annotations: tuple[SceneAnnotation, ...] = ()
    notes: tuple[DrawingNote, ...] = ()
    template: DrawingTemplate | None = None
    default_scale: float = 1
    sheet_number: int = 1
    sheet_count: int = 1
    section_markers: tuple[SectionMarker, ...] = ()
    detail_markers: tuple[DetailMarker, ...] = ()


def _section_label(index: int) -> str:
    label = ""
    while index:
        index, digit = divmod(index - 1, 26)
        label = chr(65 + digit) + label
    return label


def _curve_lower_bound(curve: CurveGeometry) -> float:
    if isinstance(curve, LineCurve):
        return min(curve.start[1], curve.end[1])
    if isinstance(curve, ArcCurve):
        return curve.center[1] - curve.radius
    if isinstance(curve, EllipseCurve):
        return curve.center[1] - curve.major_radius
    return min(point[1] for point in curve.poles)


def build_drawing_scene(
    state: DrawingState, sheet_id: UUID, projections: Mapping[UUID, ProjectionResult]
) -> DrawingScene:
    from mycad.core.drawing_annotations import resolve_annotation

    sheet = state.sheet(sheet_id)
    views: list[SceneView] = []
    issues: list[str] = []
    fingerprints: set[str] = set()
    for view in state.views:
        if view.sheet_id != sheet_id:
            continue
        if view.section is not None:
            issues.append("剖视功能开发中，尚不能出图")
        if view.detail is not None:
            issues.append("局部详图功能开发中，尚不能出图")
        projection = projections.get(view.view_id)
        if projection is None or projection.view_id != view.view_id:
            issues.append(f"视图 {view.view_id} 尚未生成投影")
            continue
        fingerprints.add(projection.source_fingerprint)
        issues.extend(projection.diagnostics)
        hidden, tangent = state.effective_display(view.view_id)
        curves = tuple(
            curve
            for curve in projection.curves
            if (curve.visibility != "hidden" or hidden)
            and (curve.visibility != "tangent" or tangent)
        )
        views.append(
            SceneView(
                view.view_id,
                state.effective_anchor(view.view_id),
                state.effective_scale(view.view_id),
                curves,
                projection.hatch,
            )
        )
    if len(fingerprints) > 1:
        issues.append("视图来源版本不一致，请更新工程图")
    view_ids = {view.view_id for view in state.views if view.sheet_id == sheet_id}
    markers: list[SectionMarker] = []
    for view in state.views:
        if view.sheet_id != sheet_id or view.section is None or view.parent_id is None:
            continue
        anchor = state.effective_anchor(view.parent_id)
        scale = state.effective_scale(view.parent_id)
        start = view.section.start
        end = view.section.end
        view_anchor = state.effective_anchor(view.view_id)
        scene_view = next((item for item in views if item.view_id == view.view_id), None)
        bottom = (
            min((_curve_lower_bound(curve.geometry) for curve in scene_view.curves), default=0)
            if scene_view is not None
            else 0
        )
        label_y = view_anchor[1] + state.effective_scale(view.view_id) * bottom - 5
        markers.append(
            SectionMarker(
                _section_label(len(markers) + 1),
                (anchor[0] + scale * start[0], anchor[1] + scale * start[1]),
                (anchor[0] + scale * end[0], anchor[1] + scale * end[1]),
                view.section.observer_side,
                (view_anchor[0], label_y),
            )
        )
    details: list[DetailMarker] = []
    for view in state.views:
        if view.sheet_id != sheet_id or view.detail is None or view.parent_id is None:
            continue
        anchor = state.effective_anchor(view.parent_id)
        parent_scale = state.effective_scale(view.parent_id)
        scale = state.effective_scale(view.view_id)
        details.append(
            DetailMarker(
                _section_label(len(details) + 1),
                (
                    anchor[0] + parent_scale * view.detail.center[0],
                    anchor[1] + parent_scale * view.detail.center[1],
                ),
                parent_scale * view.detail.radius,
                state.effective_anchor(view.view_id),
                scale * view.detail.radius,
                scale,
            )
        )
    resolved: list[SceneAnnotation] = []
    for annotation in state.annotations:
        if annotation.view_id not in view_ids:
            continue
        scene_view = next((v for v in views if v.view_id == annotation.view_id), None)
        if scene_view is None:
            scene_view = SceneView(
                annotation.view_id,
                state.effective_anchor(annotation.view_id),
                state.effective_scale(annotation.view_id),
                (),
            )
        projection = projections.get(
            annotation.view_id, ProjectionResult(annotation.view_id, "unavailable", 0, ())
        )
        item = resolve_annotation(annotation, projection, scene_view)
        resolved.append(item)
        if item.status != "resolved":
            issues.append(f"标注 {annotation.annotation_id}：{item.message}")
    return DrawingScene(
        sheet_id,
        sheet.size_mm,
        sheet.margin_mm,
        sheet.title,
        tuple(views),
        tuple(a for a in state.annotations if a.view_id in view_ids),
        tuple(issues),
        next(iter(fingerprints), ""),
        tuple(resolved),
        tuple(note for note in state.notes if note.sheet_id == sheet_id),
        sheet.template,
        sheet.default_scale,
        next(i + 1 for i, item in enumerate(state.sheets) if item.sheet_id == sheet_id),
        len(state.sheets),
        tuple(markers),
        tuple(details),
    )


@dataclass(frozen=True, slots=True)
class DrawingSourceSnapshot:
    """Runtime-only immutable BREP payload; never persisted in the document."""

    source_fingerprint: str
    brep: bytes
