# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Transient in-canvas drawing gestures; persistent writes belong to the Bus."""

from uuid import UUID, uuid4

from mycad.core.drawing import DrawingSheet, DrawingView
from mycad.core.drawing_projection import Point2, ViewBasis, ViewDirection


class ViewPlacement:
    def __init__(
        self, sheet: DrawingSheet, *, scale: float = 1, basis: ViewBasis | None = None
    ) -> None:
        self.sheet = sheet
        self.scale = scale
        self.basis = basis or ViewBasis()
        self.base_id = uuid4()
        self.pending: list[DrawingView] = []
        self._ids = {direction: uuid4() for direction in ("top", "bottom", "left", "right")}

    def projected_id(self, direction: str) -> UUID:
        return self._ids[direction]

    def preview(self, point: Point2) -> DrawingView | None:
        if not self.pending:
            return DrawingView(
                self.base_id,
                self.sheet.sheet_id,
                basis=self.basis,
                anchor_mm=point,
                scale=self.scale,
            )
        base = self.pending[0]
        dx, dy = point[0] - base.anchor_mm[0], point[1] - base.anchor_mm[1]
        if max(abs(dx), abs(dy)) < 5:
            return None
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
