# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Transient in-canvas drawing gestures; persistent writes belong to the Bus."""

import math
from uuid import UUID, uuid4

from mycad.core.drawing import DrawingSheet, DrawingState, DrawingView, SourceBinding
from mycad.core.drawing_detail import DetailRegion
from mycad.core.drawing_projection import Point2, ViewBasis, ViewDirection
from mycad.core.drawing_section import SectionLine


def isometric_basis() -> ViewBasis:
    """View the part from +X, -Y, +Z with the global Z axis pointing up."""
    return ViewBasis.from_normal_up((1, -1, 1), (0, 0, 1))


class DetailPlacement:
    """Uncommitted circular detail: center, radius point, then view location."""

    def __init__(
        self, state: DrawingState, parent_id: UUID, fingerprint: str, *, scale_factor: float = 2
    ) -> None:
        if not math.isfinite(scale_factor) or scale_factor < 1:
            raise ValueError("详图放大倍数须为不小于 1 的有限数值")
        parent = state.view(parent_id)
        if (
            parent.source.kind != "current_part"
            or parent.section is not None
            or parent.detail is not None
        ):
            raise ValueError("请选择实体模型的普通投影视图作为详图来源")
        self.parent = parent
        self.parent_anchor = state.effective_anchor(parent_id)
        self.parent_scale = state.effective_scale(parent_id)
        self.parent_basis = state.effective_basis(parent_id)
        self.fingerprint = fingerprint
        self.scale_factor = scale_factor
        self.view_id = uuid4()
        self.center: Point2 | None = None
        self.radius_paper: float | None = None
        self.position: Point2 | None = None

    def click(self, point: Point2) -> None:
        if self.center is None:
            self.center = point
        elif self.radius_paper is None:
            radius = math.dist(self.center, point)
            if radius < 1:
                raise ValueError("详图圈半径须至少为 1 mm（图纸坐标）")
            self.radius_paper = radius
        else:
            self.position = point

    def make_view(self) -> DrawingView:
        if self.center is None or self.radius_paper is None or self.position is None:
            raise ValueError("请先选择详图圆心、半径和放置位置")
        center = (
            (self.center[0] - self.parent_anchor[0]) / self.parent_scale,
            (self.center[1] - self.parent_anchor[1]) / self.parent_scale,
        )
        return DrawingView(
            self.view_id,
            self.parent.sheet_id,
            source=self.parent.source,
            parent_id=self.parent.view_id,
            anchor_mm=self.position,
            scale=self.scale_factor * self.parent_scale,
            inherit_scale=False,
            aligned=False,
            detail=DetailRegion(center, self.radius_paper / self.parent_scale),
        )

    def matches(self, state: DrawingState, fingerprint: str) -> bool:
        try:
            identity = self.parent.view_id
            return (
                fingerprint == self.fingerprint
                and state.view(identity) == self.parent
                and state.effective_anchor(identity) == self.parent_anchor
                and state.effective_scale(identity) == self.parent_scale
                and state.effective_basis(identity) == self.parent_basis
            )
        except ValueError:
            return False


class SectionPlacement:
    """Uncommitted straight section: two paper-space points, then view location."""

    def __init__(self, state: DrawingState, parent_id: UUID, fingerprint: str) -> None:
        parent = state.view(parent_id)
        if (
            parent.source.kind != "current_part"
            or parent.section is not None
            or parent.detail is not None
        ):
            raise ValueError("请选择实体的正投影视图作为剖视来源")
        basis = state.effective_basis(parent_id)
        if not any(math.isclose(abs(value), 1, abs_tol=1e-9) for value in basis.normal):
            raise ValueError("请选择实体的正投影视图作为剖视来源")
        self.parent = parent
        self.parent_anchor = state.effective_anchor(parent_id)
        self.parent_scale = state.effective_scale(parent_id)
        self.parent_basis = basis
        self.fingerprint = fingerprint
        self.view_id = uuid4()
        self.start: Point2 | None = None
        self.end: Point2 | None = None
        self.position: Point2 | None = None

    def _local(self, point: Point2) -> Point2:
        return (
            (point[0] - self.parent_anchor[0]) / self.parent_scale,
            (point[1] - self.parent_anchor[1]) / self.parent_scale,
        )

    def click(self, point: Point2) -> None:
        if self.start is None:
            self.start = point
        elif self.end is None:
            if math.dist(self.start, point) < 1:
                raise ValueError("剖切线两点须至少相距 1 mm（图纸坐标）")
            self.end = point
        else:
            self.position = point

    def make_view(self) -> DrawingView:
        if self.start is None or self.end is None or self.position is None:
            raise ValueError("请先选择剖切线两点和剖视放置位置")
        start, end, position = (
            self._local(self.start),
            self._local(self.end),
            self._local(self.position),
        )
        cross = (end[0] - start[0]) * (position[1] - start[1]) - (end[1] - start[1]) * (
            position[0] - start[0]
        )
        if abs(cross) < 1e-9:
            raise ValueError("请将剖视放在剖切线的一侧，以确定观察方向")
        return DrawingView(
            self.view_id,
            self.parent.sheet_id,
            source=self.parent.source,
            parent_id=self.parent.view_id,
            anchor_mm=self.position,
            scale=self.parent_scale,
            aligned=False,
            section=SectionLine(start, end, "left" if cross > 0 else "right"),
        )

    def matches(self, state: DrawingState, fingerprint: str) -> bool:
        try:
            identity = self.parent.view_id
            return (
                fingerprint == self.fingerprint
                and state.view(identity) == self.parent
                and state.effective_anchor(identity) == self.parent_anchor
                and state.effective_scale(identity) == self.parent_scale
                and state.effective_basis(identity) == self.parent_basis
            )
        except ValueError:
            return False


class ViewPlacement:
    def __init__(
        self,
        sheet: DrawingSheet,
        *,
        scale: float = 1,
        basis: ViewBasis | None = None,
        source: SourceBinding | None = None,
        allow_projected: bool = True,
        include_isometric: bool = False,
    ) -> None:
        self.source = source or SourceBinding()
        self.sheet = sheet
        self.scale = scale
        self.basis = basis or ViewBasis()
        self.allow_projected = allow_projected
        self.include_isometric = include_isometric and allow_projected
        self.base_id = uuid4()
        self.pending: list[DrawingView] = []
        self._ids = {
            direction: uuid4() for direction in ("top", "bottom", "left", "right", "isometric")
        }

    def projected_id(self, direction: str) -> UUID:
        return self._ids[direction]

    def preview(self, point: Point2) -> DrawingView | None:
        if not self.pending:
            return DrawingView(
                self.base_id,
                self.sheet.sheet_id,
                source=self.source,
                basis=self.basis,
                anchor_mm=point,
                scale=self.scale,
            )
        if self.source.kind == "sketch" or not self.allow_projected:
            return None
        base = self.pending[0]
        dx, dy = point[0] - base.anchor_mm[0], point[1] - base.anchor_mm[1]
        if max(abs(dx), abs(dy)) < 5:
            return None
        if self.include_isometric and min(abs(dx), abs(dy)) >= 0.5 * max(abs(dx), abs(dy)):
            return DrawingView(
                self._ids["isometric"],
                self.sheet.sheet_id,
                source=self.source,
                basis=isometric_basis(),
                anchor_mm=point,
                scale=self.scale,
            )
        first = self.sheet.projection_angle == "first"
        direction: ViewDirection
        if abs(dx) > abs(dy):
            direction = "left" if (dx > 0) == first else "right"
            offset = (dx, 0.0)
        else:
            direction = "top" if (dy < 0) == first else "bottom"
            offset = (0.0, dy)
        return DrawingView(
            self._ids[direction],
            self.sheet.sheet_id,
            parent_id=base.view_id,
            direction=direction,
            offset_mm=offset,
            scale=self.scale,
        )

    def click(self, point: Point2) -> None:
        view = self.preview(point)
        if view is None:
            return
        self.pending = [v for v in self.pending if v.view_id != view.view_id]
        self.pending.append(view)

    def finish(self) -> tuple[DrawingView, ...]:
        return tuple(self.pending)

    def cancel(self) -> None:
        self.pending.clear()


def move_view(state: DrawingState, identity: UUID, position: Point2) -> dict[str, object]:
    view = state.view(identity)
    if view.parent_id is None or not view.aligned:
        return {"view_id": str(identity), "anchor_mm": list(position)}
    parent = state.effective_anchor(view.parent_id)
    dx, dy = position[0] - parent[0], position[1] - parent[1]
    if view.direction in ("top", "bottom"):
        dx = 0
    elif view.direction in ("left", "right"):
        dy = 0
    return {"view_id": str(identity), "offset_mm": [dx, dy]}


def scale_view(state: DrawingState, identity: UUID, scale: float | None) -> dict[str, object]:
    view = state.view(identity)
    if scale is None:
        if view.parent_id is None:
            return {"view_id": str(identity), "scale": state.sheet(view.sheet_id).default_scale}
        return {"view_id": str(identity), "inherit_scale": True}
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("View scale must be finite and positive")
    return {"view_id": str(identity), "scale": scale, "inherit_scale": False}


def set_view_alignment(state: DrawingState, identity: UUID, aligned: bool) -> dict[str, object]:
    view = state.view(identity)
    position = state.effective_anchor(identity)
    if not aligned or view.parent_id is None:
        return {"view_id": str(identity), "aligned": aligned, "anchor_mm": list(position)}
    parent = state.effective_anchor(view.parent_id)
    return {
        "view_id": str(identity),
        "aligned": True,
        "offset_mm": [position[0] - parent[0], position[1] - parent[1]],
    }
