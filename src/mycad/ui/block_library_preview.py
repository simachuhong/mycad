# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only preview using the existing block canvas and text renderer."""

from dataclasses import replace
from uuid import uuid4

from PySide6.QtWidgets import QVBoxLayout, QWidget

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockInstance
from mycad.core.drawing_text import TextStyleTable
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    SplineEntity,
)
from mycad.core.sketch_layers import SketchLayerTable
from mycad.ui.drawing_text_tools import DrawingTextTools
from mycad.ui.sketch_editor import SketchCanvas


class BlockLibraryPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = SketchCanvas(self)
        self.canvas.text_tools = DrawingTextTools(self.canvas, self)
        self.canvas.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def set_asset(self, asset: BlockAsset | None) -> None:
        if asset is None:
            self.canvas.set_drawing_blocks((), (), TextStyleTable())
            return
        self.canvas.layer_table = SketchLayerTable(
            tuple(
                replace(layer, visible=True, locked=False, frozen=False)
                for layer in asset.layers.layers
            )
        )
        if self.canvas.text_tools is not None:
            self.canvas.text_tools.styles = asset.text_styles
        instance = BlockInstance(uuid4().hex, asset.definition.definition_id, (0, 0))
        self.canvas.set_drawing_blocks((asset.definition,), (instance,), asset.text_styles)
        self._fit_asset()

    def _fit_asset(self) -> None:
        points: list[tuple[float, float]] = []
        view = self.canvas.drawing_block_view()
        for item in view.geometry:
            entity = item.entity
            if isinstance(entity, LineEntity):
                points.extend((entity.start_mm, entity.end_mm))
            elif isinstance(entity, PointEntity):
                points.append(entity.position_mm)
            elif isinstance(entity, CircleEntity | ArcEntity):
                x, y = entity.center_mm
                radius = entity.radius_mm
                points.extend(((x - radius, y - radius), (x + radius, y + radius)))
            elif isinstance(entity, EllipseEntity | SplineEntity):
                points.extend(entity.sampled_points())
            elif isinstance(entity, PolylineEntity):
                from mycad.core.polyline_curves import polyline_sampled_points

                points.extend(polyline_sampled_points(entity))
            else:
                points.extend((entity.first_corner_mm, entity.opposite_corner_mm))
        if self.canvas.text_tools is not None:
            for item in view.texts:
                points.extend(self.canvas.text_tools.model_corners(item.text))
        if not points:
            return
        left, right = min(point[0] for point in points), max(point[0] for point in points)
        bottom, top = min(point[1] for point in points), max(point[1] for point in points)
        margin = max(1.0, (right - left) * 0.1, (top - bottom) * 0.1)
        self.canvas.zoom_view_window(
            (left - margin, bottom - margin), (right + margin, top + margin)
        )
