# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Canvas placement and selection of geometric tolerance annotations."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog

from mycad.core.cross_sketch_tangency import project_coplanar_vector
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable, move_text
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    SurfaceIndication,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_attachment import (
    resolve_attachment_local,
    resolve_attachment_normal,
    resolve_datum_bar_direction,
)
from mycad.core.geometric_tolerance_copy import copy_geometric_annotations, translate_frame
from mycad.core.geometric_tolerance_geometry import (
    circular_datum_geometry,
    datum_leader_path,
    datum_triangle,
    frame_leader_arrow,
    relocate_automatic_leader,
    relocate_box_aware_leader,
    reroute_leader_around_box,
    surface_indication_geometry,
)
from mycad.core.geometric_tolerance_surface_extension import (
    SurfaceExtensionSpec,
    surface_extension_geometry,
)
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.core.sketch_layers import SketchLayerTable
from mycad.core.text_interchange import reconcile_text_style_ids
from mycad.formats.dxf_datum import DatumGraphicSnapshot, DatumNativeSnapshot, datum_box_dimensions
from mycad.formats.geometric_tolerance_preview import FrameGlyphs, GlyphContours
from mycad.ui.detached_dimension_layout import (
    ReferenceDimensionLayout,
    layout_reference_dimension,
    project_reference_dimension,
)
from mycad.ui.dimension_tolerance_editor import DimensionToleranceDialog
from mycad.ui.drawing2d_command_bar import parse_coordinate
from mycad.ui.drawing_annotation_projection import project_annotation, project_surface
from mycad.ui.drawing_clipboard import (
    MAX_MIXED_CLIPBOARD_BYTES,
    instantiate_drawing_clipboard,
    reconcile_clipboard_styles,
)
from mycad.ui.font_manager import FontManager
from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog, SurfaceExtensionDialog
from mycad.ui.geometric_tolerance_layout import (
    FrameLayout,
    datum_box_size,
    frame_font_warning,
    layout_frame,
    legacy_frame_leader_layout,
)
from mycad.ui.text_layout import TextLayout, layout_text


def _capture_text_glyphs(text: TextLayout, dx: float, dy: float, scale: float = 1.0) -> FrameGlyphs:
    paths = text.glyph_paths()
    if not paths:
        raise ValueError("文字字形轮廓不可用")
    glyphs: list[GlyphContours] = []
    for path in paths:
        contours = tuple(
            tuple(
                (dx + polygon.at(index).x() * scale / 20, dy + polygon.at(index).y() * scale / 20)
                for index in range(polygon.size())
            )
            for polygon in path.toSubpathPolygons(QTransform.fromScale(20, 20))
            if polygon.size() >= 3
        )
        if not contours:
            raise ValueError("文字字形轮廓不可用")
        glyphs.append(contours)
    return tuple(glyphs)


def _relocate_automatic_leader(
    item: FeatureControlFrame | DatumIdentifier, position: tuple[float, float]
) -> tuple[tuple[float, float], ...]:
    target = item.leader_target_mm if isinstance(item, FeatureControlFrame) else item.target_mm
    if target is None:
        raise ValueError("自动引线缺少附着目标。")
    if isinstance(item, DatumIdentifier) and item.route_algorithm_version >= 3:
        assert item.box_size_mm is not None
        return relocate_box_aware_leader(
            item.position_mm,
            item.leader_offsets,
            position,
            target,
            item.box_size_mm,
            orthogonal_box_side=item.route_algorithm_version >= 4,
        )
    anchor = (
        (position[0] + item.leader_anchor_offset[0], position[1] + item.leader_anchor_offset[1])
        if isinstance(item, FeatureControlFrame) and item.leader_anchor_offset is not None
        else None
    )
    return relocate_automatic_leader(
        item.position_mm, item.leader_offsets, position, target, anchor=anchor
    )


def _moved_leader_offsets(
    item: FeatureControlFrame | DatumIdentifier, position: tuple[float, float]
) -> tuple[tuple[float, float], ...]:
    if item.leader_auto_route:
        return _relocate_automatic_leader(item, position)
    attachment = (
        item.leader_attachment if isinstance(item, FeatureControlFrame) else item.attachment
    )
    if item.leader_auto_normal and attachment is not None:
        dx, dy = position[0] - item.position_mm[0], position[1] - item.position_mm[1]
        return tuple((x - dx, y - dy) for x, y in item.leader_offsets)
    return item.leader_offsets


def _translated_datum(datum: DatumIdentifier, dx: float, dy: float) -> DatumIdentifier:
    position = (datum.position_mm[0] + dx, datum.position_mm[1] + dy)
    return replace(
        datum,
        position_mm=position,
        target_mm=datum.target_mm
        if datum.attachment is not None or datum.annotation_attachment is not None
        else (datum.target_mm[0] + dx, datum.target_mm[1] + dy),
        leader_offsets=_moved_leader_offsets(datum, position),
    )


TOLERANCE_CLIPBOARD_MIME = "application/x-mycad-tolerance-frame+json"
_DATUM_NAME_PROMPT = "基准名称（请输入本图中唯一的标识，例如 A；创建后可编辑）："


def _near_segment(point: QPointF, start: QPointF, end: QPointF, radius: float) -> bool:
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length_squared = dx * dx + dy * dy
    fraction = (
        max(
            0.0,
            min(
                1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length_squared
            ),
        )
        if length_squared
        else 0.0
    )
    return (
        math.hypot(point.x() - start.x() - fraction * dx, point.y() - start.y() - fraction * dy)
        <= radius
    )


def _spline_hits(
    spline: SplineEntity, point: tuple[float, float], radius: float
) -> tuple[tuple[float, tuple[float, float]], ...]:
    """Find separate nearby local minima so self-crossings remain ambiguous."""
    samples = spline.sampled_points()
    count = len(samples) - 1
    distances = tuple(math.dist(point, sample) for sample in samples)
    hits: list[tuple[float, tuple[float, float]]] = []
    for index in range(1, count):
        if distances[index] > distances[index - 1] or distances[index] > distances[index + 1]:
            continue
        left, right = (index - 1) / count, (index + 1) / count
        for _ in range(32):
            first = left + (right - left) / 3
            second = right - (right - left) / 3
            if math.dist(point, spline.point_at(first)) < math.dist(point, spline.point_at(second)):
                right = second
            else:
                left = first
        parameter = (left + right) / 2
        target = spline.point_at(parameter)
        if math.dist(point, target) <= radius and all(
            abs(parameter - previous) > 1e-6 for previous, _ in hits
        ):
            hits.append((parameter, target))
    return tuple(hits)


def _ellipse_hits(
    ellipse: EllipseEntity, point: tuple[float, float], radius: float
) -> tuple[tuple[float, tuple[float, float]], ...]:
    count = 192

    def sample(parameter: float) -> tuple[float, float]:
        return ellipse.point_at(
            parameter % 1.0 if ellipse.closed else min(1.0, max(0.0, parameter))
        )

    distances = [math.dist(point, sample(i / count)) for i in range(count + 1)]
    hits: list[tuple[float, tuple[float, float]]] = []
    for index in range(count if ellipse.closed else count + 1):
        previous = (
            distances[(index - 1) % count] if ellipse.closed else distances[max(0, index - 1)]
        )
        following = (
            distances[(index + 1) % count] if ellipse.closed else distances[min(count, index + 1)]
        )
        if distances[index] > previous or distances[index] > following:
            continue
        left, right = (index - 1) / count, (index + 1) / count
        if not ellipse.closed:
            left, right = max(0.0, left), min(1.0, right)
        for _ in range(40):
            first, second = (2 * left + right) / 3, (left + 2 * right) / 3
            if math.dist(point, sample(first)) < math.dist(point, sample(second)):
                right = second
            else:
                left = first
        parameter = (left + right) / 2
        parameter = parameter % 1.0 if ellipse.closed else parameter
        target = ellipse.point_at(parameter)
        if math.dist(point, target) <= radius:
            hits.append((parameter, target))
    return tuple(hits)


if TYPE_CHECKING:
    from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


@dataclass(frozen=True)
class MixedTolerancePaste:
    sketch: Sketch
    owners: dict[str, str]
    frames: tuple[FeatureControlFrame, ...]
    datums: tuple[DatumIdentifier, ...]
    references: tuple[DetachedDimension, ...]
    texts: tuple[DrawingText, ...]
    rasters: tuple[DrawingRaster, ...]
    labels: dict[str, str]
    styles: DimensionStyleTable | None
    text_styles: TextStyleTable | None
    preserve_external: bool
    anchor: tuple[float, float]
    target_revision: int


class GeometricToleranceTools:
    def __init__(self, canvas: SketchCanvas, parent: SketchEditorDialog) -> None:
        self.canvas = canvas
        self.parent = parent
        self.manager = FontManager()
        self.frames: tuple[FeatureControlFrame, ...] = ()
        self.datums: tuple[DatumIdentifier, ...] = ()
        self.reference_dimensions: tuple[DetachedDimension, ...] = ()
        self.selected_id: str | None = None
        self.selected_ids: set[str] = set()
        self.selection_before_press: set[str] = set()
        self.selection_original: set[str] = set()
        self.selected_kind = "frame"
        self.pending_rows: tuple[ToleranceRow, ...] = ()
        self.pending_rotation = 0.0
        self.pending_layer = "0"
        self.pending_text_style_id: str | None = None
        self.mechanical_frame_active = False
        self.mechanical_leader_orthogonal = True
        self.mechanical_last_pointer: QPoint | None = None
        self.surface_pick_active = False
        self.surface_joint_pending = False
        self.surface_joint: tuple[float, float] | None = None
        self.surface_vertex_pending = False
        self.surface_vertices: list[tuple[float, float]] = []
        self.surface_auto_normal = False
        self.surface_edit: DatumIdentifier | FeatureControlFrame | None = None
        self.surface_edit_revision: int | None = None
        self.surface_edit_cursor: tuple[float, float] | None = None
        self.mechanical_frame_target: tuple[float, float] | None = None
        self.mechanical_frame_attachment: DatumAttachment | None = None
        self.mechanical_frame_annotation_attachment: AnnotationAttachment | None = None
        self.mechanical_frame_cursor: tuple[float, float] | None = None
        self.mechanical_frame_vertices: list[tuple[float, float]] = []
        self.mechanical_frame_adding_vertex = False
        self.mechanical_frame_auto_normal = False
        self.pending_datum_label = ""
        self.default_datum_symbol_style: Callable[[], str] = lambda: "rectangle"
        self.creation_datum_symbol_style = "rectangle"
        self.datum_target_preview: tuple[QPointF, QPointF] | None = None
        self.mechanical_datum_active = False
        self.mechanical_datum_no_leader = False
        self.mechanical_datum_target: tuple[float, float] | None = None
        self.mechanical_datum_attachment: DatumAttachment | None = None
        self.mechanical_datum_annotation_attachment: AnnotationAttachment | None = None
        self.mechanical_datum_cursor: tuple[float, float] | None = None
        self.mechanical_datum_vertices: list[tuple[float, float]] = []
        self.mechanical_datum_adding_vertex = False
        self.mechanical_datum_auto_normal = False
        self.datum_grip: tuple[DatumIdentifier, int] | None = None
        self.datum_grip_cursor: tuple[float, float] | None = None
        self.datum_drag: (
            tuple[DatumIdentifier, QPointF, tuple[float, float], WorkPlaneFrame] | None
        ) = None
        self.datum_drag_cursor: tuple[float, float] | None = None
        self.frame_grip: tuple[FeatureControlFrame, int] | None = None
        self.frame_grip_cursor: tuple[float, float] | None = None
        self.grip_view_frame: WorkPlaneFrame | None = None
        self.canvas.pointer_moved.connect(self._datum_pointer_moved)
        self.pending_reattach = False
        self.pending_reattach_target: DatumIdentifier | None = None
        self.pending_reattach_revision: int | None = None
        self.clipboard_frame: FeatureControlFrame | None = None
        self.clipboard_datum: DatumIdentifier | None = None
        self.clipboard_reference: DetachedDimension | None = None
        self.clipboard_mixed: MixedTolerancePaste | None = None
        self.mixed_copy_command = False
        self.mixed_copy_base: tuple[float, float] | None = None
        self.mixed_view_frame: WorkPlaneFrame | None = None
        self.mixed_move_active = False
        self.mixed_move_copy = False
        self.mixed_move_base: tuple[float, float] | None = None
        self.mixed_move_revision = 0
        self.mixed_move_entities: tuple[str, ...] = ()
        self.mixed_move_frames: tuple[str, ...] = ()
        self.mixed_move_datums: tuple[str, ...] = ()
        self.mixed_move_references: tuple[str, ...] = ()
        self.mixed_move_texts: tuple[str, ...] = ()
        self.mixed_move_rasters: tuple[str, ...] = ()
        self._clipboard_source = uuid4().hex
        self._collection_clipboard_source = self._clipboard_source
        self.pending_datum_position: tuple[float, float] | None = None
        self.transform_action = ""
        self.transform_arrow_base = False
        self.transform_base: tuple[float, float] | None = None
        self.transform_cursor: tuple[float, float] | None = None
        self.transform_view_frame: WorkPlaneFrame | None = None
        self.transform_subject: FeatureControlFrame | DatumIdentifier | DetachedDimension | None = (
            None
        )
        self.execute: Callable[[str, dict[str, object]], bool] | None = None
        self.commit_identity_repair: Callable[[], bool] | None = None
        self.commit_curve_identity_upgrade: Callable[[], bool] | None = None
        self.commit_mixed: (
            Callable[
                [
                    Sketch,
                    tuple[FeatureControlFrame, ...],
                    tuple[DatumIdentifier, ...],
                    tuple[DetachedDimension, ...],
                    tuple[DrawingText, ...],
                    tuple[DrawingRaster, ...],
                    DimensionStyleTable | None,
                    TextStyleTable | None,
                    bool,
                ],
                bool,
            ]
            | None
        ) = None
        self.attachment_resolved: Callable[[str], bool] | None = None
        self.source_revision: Callable[[], int] | None = None
        self.source_subject: (
            Callable[[str, str], FeatureControlFrame | DatumIdentifier | DetachedDimension | None]
            | None
        ) = None
        self.source_layer_editable: Callable[[str], bool] | None = None
        self.source_text: Callable[[str], DrawingText | None] | None = None
        self.source_raster: Callable[[str], DrawingRaster | None] | None = None
        self.commit_geometry_delete: Callable[[], bool] | None = None
        self.commit_delete: (
            Callable[
                [
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                ],
                bool,
            ]
            | None
        ) = None
        self.commit_move: (
            Callable[
                [
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[float, float],
                    int,
                ],
                bool,
            ]
            | None
        ) = None
        self.commit_collection_copy: (
            Callable[
                [
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[str, ...],
                    tuple[float, float],
                    int,
                ],
                bool,
            ]
            | None
        ) = None
        self._cache: dict[tuple[FeatureControlFrame, TextStyle], FrameLayout] = {}

    @property
    def clipboard_source(self) -> str:
        """Identify the current live document for collection clipboard associations."""
        return self._collection_clipboard_source

    def set_collection_clipboard_source(self, source: str) -> None:
        """Share a document token across its replacement drawing canvases."""
        self._collection_clipboard_source = source

    @property
    def pending(self) -> bool:
        return bool(
            self.pending_rows
            or self.mechanical_frame_active
            or self.surface_edit is not None
            or self.pending_datum_label
            or self.mechanical_datum_active
            or self.datum_grip is not None
            or self.datum_drag is not None
            or self.frame_grip is not None
            or self.pending_reattach
            or self.clipboard_frame is not None
            or self.clipboard_datum is not None
            or self.clipboard_reference is not None
            or self.clipboard_mixed is not None
            or self.mixed_move_active
            or self.transform_action
        )

    def sync(
        self,
        frames: tuple[FeatureControlFrame, ...],
        datums: tuple[DatumIdentifier, ...],
        references: tuple[DetachedDimension, ...] = (),
    ) -> None:
        old_kinds = {
            **{frame.frame_id: "frame" for frame in self.frames},
            **{datum.datum_id: "datum" for datum in self.datums},
            **{dimension.dimension_id: "reference" for dimension in self.reference_dimensions},
        }
        new_kinds = {
            **{frame.frame_id: "frame" for frame in frames},
            **{datum.datum_id: "datum" for datum in datums},
            **{dimension.dimension_id: "reference" for dimension in references},
        }
        self.frames, self.datums, self.reference_dimensions = frames, datums, references
        counts = Counter(
            [frame.frame_id for frame in frames]
            + [datum.datum_id for datum in datums]
            + [dimension.dimension_id for dimension in references]
        )
        ambiguous = {identity for identity in self.selected_ids if counts[identity] > 1}
        changed_kind = {
            identity
            for identity in self.selected_ids
            if identity in old_kinds
            and identity in new_kinds
            and old_kinds[identity] != new_kinds[identity]
        }
        self.selected_ids.intersection_update(
            identity for identity, count in counts.items() if count == 1
        )
        self.selected_ids.difference_update(changed_kind)
        if self.selected_id not in self.selected_ids:
            self._restore_selected_kind()
        if ambiguous:
            self._message("标注身份重复，已取消相关选择；请先修复重复身份。")
        elif changed_kind:
            self._message("标注类型已改变，已取消相关选择；请重新选择。")
        self._cache.clear()
        self.canvas.update()

    def _can_begin_annotation(self) -> bool:
        if (
            self.pending
            or self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or (self.canvas.text_tools is not None and self.canvas.text_tools.pending)
        ):
            self._message("请先完成或取消当前操作，再开始标注。")
            return False
        return True

    def begin_frame(self) -> None:
        if not self._can_begin_annotation():
            return
        dialog = GeometricToleranceDialog(
            available=self.datums,
            parent=self.parent,
            layer_names=tuple(layer.name for layer in self.canvas.layer_table.layers),
            layer_name=self.canvas.active_layer_name,
            text_styles=self.canvas.text_tools.styles if self.canvas.text_tools else None,
            font_manager=self.manager,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self.pending_rows = dialog.values()
        self.pending_rotation = dialog.rotation.precise_value()
        self.pending_layer = dialog.layer.currentText()
        self.pending_text_style_id = cast("str | None", dialog.text_style.currentData())
        self.canvas.set_tool("选择元素")
        self._message("形位公差：点击画布指定位置，Esc 取消。")

    def begin_datum(self) -> None:
        if not self._can_begin_annotation():
            return
        label, accepted = QInputDialog.getText(self.parent, "基准标识", _DATUM_NAME_PROMPT)
        if not accepted:
            return
        try:
            DatumIdentifier(uuid4().hex, label, (0, 0), (0, 0))
            if any(item.label.casefold() == label.casefold() for item in self.datums):
                raise ValueError("基准名称已存在。")
        except ValueError as exc:
            self._message(str(exc))
            return
        self.pending_datum_label = label
        self.creation_datum_symbol_style = self.default_datum_symbol_style()
        self.pending_datum_position = None
        self.canvas.set_tool("选择元素")
        self._message(
            "基准标识：点击指定标识框位置，再点击指向点；靠近唯一几何点或线、圆弧位置时自动附着。"
        )

    def toggle_mechanical_leader_orthogonal(self) -> None:
        if not (self.mechanical_frame_active or self.mechanical_datum_active):
            return
        self.mechanical_leader_orthogonal = not self.mechanical_leader_orthogonal
        state = "开启" if self.mechanical_leader_orthogonal else "关闭"
        self._message(f"标注引线正交已{state}；Shift+F 切换。")
        if self.mechanical_last_pointer is not None:
            self._datum_pointer_moved(self.mechanical_last_pointer)
        self.canvas.update()

    def begin_mechanical_frame(self) -> None:
        if not self._can_begin_annotation():
            return
        self.mechanical_frame_active = True
        self.mechanical_leader_orthogonal = True
        self.mechanical_last_pointer = None
        self.canvas.set_tool("选择元素")
        self._message("形位公差：选择附着位置或指定指向点；输入 E 指向表面延伸；Esc 取消。")

    def _mechanical_frame_point(
        self,
        point: tuple[float, float],
        *,
        normal_at_box: bool = False,
        surface_normal_at_box: bool = False,
    ) -> None:
        if self.mechanical_frame_target is None:
            if self.surface_pick_active:
                geometry, target = self._pick_surface_extension(point)
                annotation = None
                if geometry is None:
                    return
                self.surface_pick_active = False
            else:
                geometry, annotation, target = self._pick_target(point)
            if target is None:
                return
            (
                self.mechanical_frame_attachment,
                self.mechanical_frame_annotation_attachment,
                self.mechanical_frame_target,
            ) = geometry, annotation, target
            self._message(
                "形位公差：指定公差框位置；V 添加顶点，F 表面指示；Shift+F 切换引线正交；Esc 取消。"
            )
            return
        if self.surface_joint_pending:
            if self.surface_vertex_pending:
                if len(self.surface_vertices) >= 64:
                    self._message("表面引线顶点最多 64 个。")
                    return
                previous = (
                    self.surface_vertices[-1]
                    if self.surface_vertices
                    else self.mechanical_frame_target
                )
                if math.dist(point, previous) <= 1e-9:
                    self._message("表面引线相邻顶点不能重合。")
                    return
                if not self.surface_vertices:
                    self.surface_auto_normal = self._surface_vertex_is_normal(
                        self.mechanical_frame_attachment, self.mechanical_frame_target, point
                    )
                self.surface_vertices.append(point)
                self.surface_vertex_pending = False
                self._message("形位公差：指定参考线位置，或输入 V 添加表面引线顶点。")
                return
            if (
                self.mechanical_leader_orthogonal
                and self.mechanical_frame_attachment is not None
                and not self.surface_vertices
                and not self.mechanical_frame_auto_normal
                and self._direct_normal_vertex(
                    self.mechanical_frame_attachment, self.mechanical_frame_target, point
                )
                is None
            ):
                self._message("无法确定表面引线法向或侧别；请重新指定位置，或按 Shift+F 关闭约束。")
                return
            previous = (
                self.surface_vertices[-1] if self.surface_vertices else self.mechanical_frame_target
            )
            if math.dist(point, previous) <= 1e-9:
                self._message("表面指示参考线位置不能与指向点重合。")
                return
            self.surface_joint = point
            self.surface_joint_pending = False
            self._message("形位公差：指定公差框位置；Esc 取消。")
            return
        if self.mechanical_frame_adding_vertex:
            if len(self.mechanical_frame_vertices) >= 64:
                self._message("引线顶点最多 64 个。")
                return
            previous = (
                self.mechanical_frame_vertices[-1]
                if self.mechanical_frame_vertices
                else self.mechanical_frame_target
                if self.surface_joint is None
                else None
            )
            if previous is not None and math.dist(point, previous) <= 1e-9:
                self._message("引线相邻顶点不能重合，请重新指定顶点。")
                return
            normal_missing = False
            if not self.mechanical_frame_vertices and self.surface_joint is None:
                self.mechanical_frame_auto_normal = self._surface_vertex_is_normal(
                    self.mechanical_frame_attachment, self.mechanical_frame_target, point
                )
                normal_missing = (
                    (self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled)
                    and self.mechanical_frame_attachment is not None
                    and self._attachment_normal(
                        self.mechanical_frame_attachment, self.mechanical_frame_target
                    )
                    is None
                )
            self.mechanical_frame_vertices.append(point)
            self.mechanical_frame_adding_vertex = False
            self._message(
                "附着位置无法确定法向；请指定公差框位置，或输入 V 添加顶点。"
                if normal_missing
                else "形位公差：指定公差框位置，V 添加顶点，Enter 使用最后顶点；Esc 取消。"
            )
            return
        if (
            self.mechanical_leader_orthogonal
            and self.mechanical_frame_attachment is not None
            and not self.mechanical_frame_vertices
            and self.surface_joint is None
            and self._attachment_normal(
                self.mechanical_frame_attachment, self.mechanical_frame_target
            )
            is None
        ):
            self._message("无法确定引线法向或侧别；请移动公差框，或按 Shift+F 关闭约束。")
            return
        dialog = GeometricToleranceDialog(
            available=self.datums,
            parent=self.parent,
            layer_names=tuple(layer.name for layer in self.canvas.layer_table.layers),
            layer_name=self.canvas.active_layer_name,
            text_styles=self.canvas.text_tools.styles if self.canvas.text_tools else None,
            font_manager=self.manager,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            self.cancel()
            return
        frame = FeatureControlFrame(
            uuid4().hex,
            dialog.values(),
            point,
            dialog.rotation.precise_value(),
            dialog.layer.currentText(),
            cast("str | None", dialog.text_style.currentData()),
            self.mechanical_frame_target,
            tuple(
                (v[0] - point[0], v[1] - point[1]) for v in reversed(self.mechanical_frame_vertices)
            ),
            leader_attachment=self.mechanical_frame_attachment,
            leader_annotation_attachment=self.mechanical_frame_annotation_attachment,
            leader_auto_normal=self.mechanical_frame_auto_normal,
            leader_arrow_style="closed_filled",
        )
        if not self.mechanical_frame_vertices and self.surface_joint is None:
            vertices = self._direct_frame_normal_vertices(frame)
            if vertices is not None:
                frame = replace(
                    frame,
                    leader_offsets=tuple(
                        (vertex[0] - point[0], vertex[1] - point[1]) for vertex in vertices
                    ),
                    leader_auto_normal=True,
                    leader_auto_route=True,
                    route_avoid_crossing=True,
                    route_track_target=True,
                    route_algorithm_version=2,
                )
            elif self.mechanical_leader_orthogonal and self.mechanical_frame_attachment is not None:
                self._message("公差框与法向引线重叠；请移动公差框，或按 Shift+F 关闭约束。")
                return
        style = self._annotation_text_style(frame) or TextStyle()
        indication = self._new_surface_indication(
            self.mechanical_frame_target,
            point,
            text_height=style.height_mm,
            auto_normal=self.surface_auto_normal,
        )
        if indication is not None:
            try:
                if surface_normal_at_box and indication.auto_normal:
                    frame = replace(
                        frame,
                        leader_auto_normal=False,
                        leader_auto_route=False,
                        route_avoid_crossing=False,
                        route_track_target=False,
                        route_algorithm_version=1,
                        leader_offsets=(),
                    )
                frame = cast(
                    "FeatureControlFrame", self._preserve_surface_normal(frame, indication)
                )
            except ValueError:
                self._message("参考线位置与法向顶点重合，请选择其他位置。")
                return
        anchor = self._frame_leader_anchor(frame)
        if anchor is None:
            self._message("公差框与引线指向点重叠，请重新指定公差框位置。")
            return
        if normal_at_box:
            frame = replace(frame, leader_offsets=((anchor[0] - point[0], anchor[1] - point[1]),))
        frame = replace(frame, leader_anchor_offset=(anchor[0] - point[0], anchor[1] - point[1]))
        if not self._annotation_layer_editable(frame.layer_name):
            return
        if self._commit({"add_frames": [frame.to_mapping()]}):
            self.cancel()
            self._message("形位公差已放置。")

    def begin_mechanical_datum(self) -> None:
        if not self._can_begin_annotation():
            return
        self.mechanical_datum_active = True
        self.creation_datum_symbol_style = self.default_datum_symbol_style()
        self.datum_target_preview = None
        self.mechanical_leader_orthogonal = True
        self.mechanical_last_pointer = None
        self.mechanical_datum_no_leader = False
        self.mechanical_datum_target = None
        self.mechanical_datum_attachment = None
        self.mechanical_datum_annotation_attachment = None
        self.mechanical_datum_cursor = None
        self.mechanical_datum_vertices.clear()
        self.mechanical_datum_adding_vertex = False
        self.mechanical_datum_auto_normal = False
        self.canvas.set_tool("选择元素")
        self._message("基准标识：选择附着位置或指定指向点；E 表面延伸，N 无引线；Esc 取消。")

    def _new_surface_indication(
        self,
        target: tuple[float, float],
        position: tuple[float, float],
        *,
        text_height: float = 3.5,
        joint: tuple[float, float] | None = None,
        auto_normal: bool = False,
    ) -> SurfaceIndication | None:
        joint = joint if joint is not None else self.surface_joint
        if joint is None:
            return None
        dx, dy = joint[0] - target[0], joint[1] - target[1]
        direction = 1.0 if position[0] >= joint[0] else -1.0
        vertices = tuple((x - target[0], y - target[1]) for x, y in self.surface_vertices)
        auto_route = False
        if (
            not vertices
            and not auto_normal
            and (self.mechanical_datum_active or self.mechanical_frame_active)
            and not (self.mechanical_datum_auto_normal or self.mechanical_frame_auto_normal)
        ):
            attachment = (
                self.mechanical_datum_attachment
                if self.mechanical_datum_active
                else self.mechanical_frame_attachment
            )
            vertex = self._direct_normal_vertex(attachment, target, joint)
            if vertex is not None:
                if math.dist(vertex, joint) <= 1e-9:
                    vertex = ((vertex[0] + target[0]) / 2, (vertex[1] + target[1]) / 2)
                vertices = ((vertex[0] - target[0], vertex[1] - target[1]),)
                auto_normal = True
                auto_route = True
        return SurfaceIndication(
            (dx, dy),
            (dx + direction * 5.0 * text_height / 3.5, dy),
            0.5,
            vertices,
            arrow_size_mm=2.5 * text_height / 3.5,
            auto_normal=auto_normal,
            auto_route=auto_route,
            route_avoid_crossing=auto_route,
        )

    def _datum_pointer_moved(self, point: QPoint) -> None:
        if self.datum_drag is not None:
            self.datum_drag_cursor = self.canvas.screen_to_local(QPointF(point))
            self.canvas.update()
            return
        if (
            self.transform_action in ("move", "copy")
            and self.transform_base is not None
            and isinstance(self.transform_subject, DatumIdentifier)
        ):
            self.transform_cursor = self.canvas.snap_annotation_point(
                self.canvas.screen_to_local(QPointF(point))
            )[0]
            self.canvas.update()
            return
        if (
            self.mixed_move_active
            and self.mixed_move_base is not None
            and self.canvas.collection_session is not None
            and (
                self.mixed_view_frame is None
                or self.mixed_view_frame == self.canvas.drawing_view_frame
            )
        ):
            target = self.canvas.screen_to_local(QPointF(point))
            delta = (target[0] - self.mixed_move_base[0], target[1] - self.mixed_move_base[1])
            self.canvas.preview_collection_displacement(self.mixed_move_copy, delta)
            return
        if self.mechanical_frame_active or self.mechanical_datum_active:
            self.mechanical_last_pointer = QPoint(point)
        if (
            self.mechanical_datum_active
            and self.creation_datum_symbol_style == "circle"
            and self.mechanical_datum_target is None
        ):
            self.datum_target_preview = None
            try:
                target = self._drawing_point(self.canvas.screen_to_local(QPointF(point)))
                attachment, annotation, hit = self._pick_target(target, include_draft=True)
                if hit is not None:
                    probe = self._oriented_datum(
                        DatumIdentifier(
                            "0" * 32,
                            "A",
                            (hit[0], hit[1] + 20),
                            hit,
                            attachment=attachment,
                            annotation_attachment=annotation,
                            symbol_style="circle",
                        )
                    )
                    if probe.bar_direction is not None:
                        dx, dy = probe.bar_direction
                        self.datum_target_preview = (
                            self.canvas.local_to_screen_precise(
                                self._view_point((hit[0] - 2 * dx, hit[1] - 2 * dy))
                            ),
                            self.canvas.local_to_screen_precise(
                                self._view_point((hit[0] + 2 * dx, hit[1] + 2 * dy))
                            ),
                        )
            except ValueError:
                pass
            self.canvas.update()
            return
        if (
            self.surface_edit is not None
            or self.mechanical_frame_active
            or self.mechanical_datum_active
        ):
            try:
                self._drawing_point(self.canvas.screen_to_local(QPointF(point)))
            except ValueError:
                return
        if self.surface_edit is not None:
            cursor = self.canvas.screen_to_local(QPointF(point))
            self.surface_edit_cursor = self._constrain_surface_edit_mouse(cursor)
            self.canvas.update()
        elif self.mechanical_frame_active and self.mechanical_frame_target is not None:
            self.mechanical_frame_cursor = self._constrain_frame_mouse(
                self.canvas.screen_to_local(QPointF(point))
            )
            self.canvas.update()
        elif self.mechanical_datum_active and (
            self.mechanical_datum_target is not None or self.mechanical_datum_no_leader
        ):
            self.mechanical_datum_cursor = self._constrain_datum_mouse(
                self.canvas.screen_to_local(QPointF(point))
            )
            self.canvas.update()
        elif self.datum_grip is not None:
            self.datum_grip_cursor = self.canvas.screen_to_local(QPointF(point))
            self.canvas.update()
        elif self.frame_grip is not None:
            self.frame_grip_cursor = self.canvas.screen_to_local(QPointF(point))
            self.canvas.update()

    @property
    def datum_transform_preview(self) -> DatumIdentifier | None:
        if self.datum_drag is not None and self.datum_drag_cursor is not None:
            datum, _, base, frame = self.datum_drag
            if (
                frame != self.canvas.drawing_view_frame
                or self._single_selected_datum() != datum
                or (
                    self.source_subject is not None
                    and self.source_subject("datum", datum.datum_id) != datum
                )
            ):
                return None
            delta = (
                self.datum_drag_cursor[0] - base[0],
                self.datum_drag_cursor[1] - base[1],
            )
            try:
                dx, dy = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
                return _translated_datum(datum, dx, dy)
            except ValueError:
                return None
        datum = self.transform_subject
        if (
            not isinstance(datum, DatumIdentifier)
            or self.transform_action not in ("move", "copy")
            or self.transform_base is None
            or self.transform_cursor is None
            or self.transform_view_frame != self.canvas.drawing_view_frame
            or self._selected_transform_subject() != datum
            or (
                self.source_subject is not None
                and self.source_subject("datum", datum.datum_id) != datum
            )
        ):
            return None
        delta = (
            self.transform_cursor[0] - self.transform_base[0],
            self.transform_cursor[1] - self.transform_base[1],
        )
        try:
            if self.transform_arrow_base:
                return self._datum_from_arrow_target(datum, self.transform_cursor)
            dx, dy = project_coplanar_vector(
                delta, self.canvas.drawing_view_frame, WorkPlaneFrame.xy()
            )
            return _translated_datum(datum, dx, dy)
        except ValueError:
            return None

    def use_datum_arrow_as_transform_base(self) -> None:
        """Start a toolbar transform at the selected datum's arrow tip."""
        datum = self.transform_subject
        if (
            self.transform_action not in ("move", "copy")
            or self.transform_base is not None
            or not isinstance(datum, DatumIdentifier)
            or not datum.leader_visible
            or datum.surface_indication is not None
        ):
            return
        try:
            point = self._view_point(datum.target_mm)
        except ValueError:
            return
        self.transform_arrow_base = True
        self.transform_base = point
        self.transform_cursor = point
        self._message("已使用基准箭头作为基点；指定箭头的新目标点，Esc 取消。")
        self.canvas.update()

    def _datum_from_arrow_target(
        self, datum: DatumIdentifier, point: tuple[float, float]
    ) -> DatumIdentifier:
        drawing_point = self._drawing_point(point)
        attachment, annotation, target = self._pick_target(drawing_point)
        if target is None or (
            attachment is None
            and annotation is None
            and (datum.attachment is not None or datum.annotation_attachment is not None)
        ):
            raise ValueError("请选择唯一的几何位置；Esc 取消。")
        dx, dy = target[0] - datum.target_mm[0], target[1] - datum.target_mm[1]
        old_normal = self._attachment_normal(datum.attachment, datum.target_mm)
        new_normal = self._attachment_normal(attachment, target)
        preserve_normal = (
            datum.leader_auto_normal
            and old_normal is not None
            and new_normal is not None
            and math.dist(old_normal, new_normal) < 1e-8
        )
        if datum.leader_auto_normal and not preserve_normal:
            raise ValueError("新目标法向不同，请使用箭头夹点重新指定附着位置。")
        candidate = datum if preserve_normal else self._datum_with_grip(datum, -2, target)
        return self._oriented_datum(
            replace(
                candidate,
                position_mm=(datum.position_mm[0] + dx, datum.position_mm[1] + dy),
                target_mm=target,
                attachment=attachment,
                annotation_attachment=annotation,
            )
        )

    def _constrain_surface_edit_mouse(self, point: tuple[float, float]) -> tuple[float, float]:
        point, snapped = self.canvas.snap_annotation_point(point)
        point = self._drawing_point(point)
        item = self.surface_edit
        if item is None or snapped or not self.canvas.orthogonal_enabled:
            return point
        target = item.target_mm if isinstance(item, DatumIdentifier) else item.leader_target_mm
        if target is None:
            return point
        local_point, local_target = self._view_point(point), self._view_point(target)
        return self._drawing_point(
            (local_point[0], local_target[1])
            if abs(local_point[0] - local_target[0]) >= abs(local_point[1] - local_target[1])
            else (local_target[0], local_point[1])
        )

    def _constrain_frame_mouse(self, point: tuple[float, float]) -> tuple[float, float]:
        point, snapped = self.canvas.snap_annotation_point(point)
        point = self._drawing_point(point)
        if (
            (self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled)
            and self.surface_vertex_pending
            and not self.surface_vertices
            and self.mechanical_frame_target is not None
        ):
            target = self.mechanical_frame_target
            normal = self._attachment_normal(self.mechanical_frame_attachment, target)
            if normal is not None:
                distance = (point[0] - target[0]) * normal[0] + (point[1] - target[1]) * normal[1]
                return (target[0] + distance * normal[0], target[1] + distance * normal[1])
        if (
            (self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled)
            and self.mechanical_frame_adding_vertex
            and not self.mechanical_frame_vertices
            and self.surface_joint is None
            and self.mechanical_frame_target is not None
        ):
            target = self.mechanical_frame_target
            normal = self._attachment_normal(self.mechanical_frame_attachment, target)
            if normal is not None:
                distance = (point[0] - target[0]) * normal[0] + (point[1] - target[1]) * normal[1]
                return (target[0] + distance * normal[0], target[1] + distance * normal[1])
        base = (
            self.surface_vertices[-1]
            if self.surface_joint_pending and self.surface_vertices
            else self.surface_joint
            if self.surface_joint is not None and not self.mechanical_frame_vertices
            else self.mechanical_frame_vertices[-1]
            if self.mechanical_frame_vertices
            else self.mechanical_frame_target
        )
        symbol_axis = self.mechanical_leader_orthogonal and bool(
            self.mechanical_frame_vertices
            or self.surface_vertices
            or self.surface_joint is not None
        )
        if snapped or not (self.canvas.orthogonal_enabled or symbol_axis) or base is None:
            return point
        local_point, local_base = self._view_point(point), self._view_point(base)
        return self._drawing_point(
            (local_point[0], local_base[1])
            if abs(local_point[0] - local_base[0]) >= abs(local_point[1] - local_base[1])
            else (local_base[0], local_point[1])
        )

    def _constrain_datum_mouse(self, point: tuple[float, float]) -> tuple[float, float]:
        point, snapped = self.canvas.snap_annotation_point(point)
        point = self._drawing_point(point)
        if self.mechanical_datum_target is None:
            return point
        if (self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled) and (
            (self.surface_vertex_pending and not self.surface_vertices)
            or (
                not self.mechanical_datum_vertices
                and self.surface_joint is None
                and not self.surface_vertices
                and (self.mechanical_datum_adding_vertex or self.canvas.orthogonal_enabled)
            )
        ):
            normal = self._datum_attachment_normal()
            if normal is not None:
                target = self.mechanical_datum_target
                distance = (point[0] - target[0]) * normal[0] + (point[1] - target[1]) * normal[1]
                return (target[0] + distance * normal[0], target[1] + distance * normal[1])
        symbol_axis = self.mechanical_leader_orthogonal and bool(
            self.mechanical_datum_vertices
            or self.surface_vertices
            or self.surface_joint is not None
        )
        if snapped or not (self.canvas.orthogonal_enabled or symbol_axis):
            return point
        base = (
            self.surface_vertices[-1]
            if self.surface_joint_pending and self.surface_vertices
            else self.surface_joint
            if self.surface_joint is not None and not self.mechanical_datum_vertices
            else self.mechanical_datum_vertices[-1]
            if self.mechanical_datum_vertices
            else self.mechanical_datum_target
        )
        local_point, local_base = self._view_point(point), self._view_point(base)
        return self._drawing_point(
            (local_point[0], local_base[1])
            if abs(local_point[0] - local_base[0]) >= abs(local_point[1] - local_base[1])
            else (local_base[0], local_point[1])
        )

    def _datum_attachment_normal(self) -> tuple[float, float] | None:
        return self._attachment_normal(
            self.mechanical_datum_attachment, self.mechanical_datum_target
        )

    def _attachment_normal(
        self, attachment: DatumAttachment | None, target: tuple[float, float] | None
    ) -> tuple[float, float] | None:
        provider = self.canvas.associative_sketches_provider
        if attachment is None or provider is None or target is None:
            return None
        for sketch in provider():
            if sketch.sketch_id == attachment.sketch_id:
                return resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
        return None

    def _direct_normal_vertex(
        self,
        attachment: DatumAttachment | None,
        target: tuple[float, float] | None,
        position: tuple[float, float],
    ) -> tuple[float, float] | None:
        if not self.mechanical_leader_orthogonal or attachment is None or target is None:
            return None
        normal = self._attachment_normal(attachment, target)
        if normal is None:
            return None
        distance = (position[0] - target[0]) * normal[0] + (position[1] - target[1]) * normal[1]
        if abs(distance) <= 1e-9:
            return None
        candidates: list[tuple[float, tuple[float, float]]] = []
        for axis in (0, 1):
            if abs(normal[axis]) <= 1e-12:
                continue
            length = (position[axis] - target[axis]) / normal[axis]
            if length * distance <= 1e-9:
                continue
            vertex = (target[0] + length * normal[0], target[1] + length * normal[1])
            if math.dist(vertex, position) <= 1e-9:
                vertex = ((vertex[0] + target[0]) / 2, (vertex[1] + target[1]) / 2)
            candidates.append((abs(length) + math.dist(vertex, position), vertex))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def _direct_frame_normal_vertices(
        self, frame: FeatureControlFrame
    ) -> tuple[tuple[float, float], ...] | None:
        target = frame.leader_target_mm
        if target is None:
            return None
        style = self._annotation_text_style(frame) or TextStyle()
        bounds = layout_frame(frame, self.manager, style).bounds
        angle = math.radians(frame.rotation_deg)
        cosine, sine = math.cos(angle), math.sin(angle)

        def local(point: tuple[float, float]) -> tuple[float, float]:
            dx, dy = point[0] - frame.position_mm[0], point[1] - frame.position_mm[1]
            return (cosine * dx + sine * dy, sine * dx - cosine * dy)

        center = bounds.center()
        center_world = (
            frame.position_mm[0] + cosine * center.x() + sine * center.y(),
            frame.position_mm[1] + sine * center.x() - cosine * center.y(),
        )
        vertex = self._direct_normal_vertex(frame.leader_attachment, target, center_world)
        if vertex is None:
            return None
        vertex_local = local(vertex)
        if not bounds.contains(QPointF(*vertex_local)):
            return (vertex,)
        target_local = local(target)
        if bounds.contains(QPointF(*target_local)):
            return None
        delta = (vertex_local[0] - target_local[0], vertex_local[1] - target_local[1])
        entry = 0.0
        for coordinate, step, low, high in zip(
            target_local,
            delta,
            (bounds.left(), bounds.top()),
            (bounds.right(), bounds.bottom()),
            strict=True,
        ):
            if abs(step) <= 1e-12:
                if not low <= coordinate <= high:
                    return (vertex,)
                continue
            entry = max(entry, min((low - coordinate) / step, (high - coordinate) / step))
        if entry <= 1e-9:
            return None
        elbow = (
            target[0] + (vertex[0] - target[0]) * entry / 2,
            target[1] + (vertex[1] - target[1]) * entry / 2,
        )
        for corner in ((center_world[0], elbow[1]), (elbow[0], center_world[1])):
            if math.dist(corner, elbow) <= 1e-9:
                continue
            if not bounds.contains(QPointF(*local(corner))):
                return (corner, elbow)
        return (elbow,)

    def _direct_datum_normal_vertices(
        self, datum: DatumIdentifier
    ) -> tuple[tuple[float, float], ...] | None:
        style = self._annotation_text_style(datum) or TextStyle()
        width, height = datum.box_size_mm or datum_box_dimensions(datum.label, style)
        left, right = datum.position_mm[0], datum.position_mm[0] + width
        bottom, top = datum.position_mm[1] - height, datum.position_mm[1]
        center = ((left + right) / 2, (bottom + top) / 2)
        vertex = self._direct_normal_vertex(datum.attachment, datum.target_mm, center)
        if vertex is None:
            return None
        if not (left <= vertex[0] <= right and bottom <= vertex[1] <= top):
            return (vertex,)
        target = datum.target_mm
        if left <= target[0] <= right and bottom <= target[1] <= top:
            return None
        delta = (vertex[0] - target[0], vertex[1] - target[1])
        entry = 0.0
        for coordinate, step, low, high in zip(
            target, delta, (left, bottom), (right, top), strict=True
        ):
            if abs(step) <= 1e-12:
                if not low <= coordinate <= high:
                    return (vertex,)
                continue
            entry = max(entry, min((low - coordinate) / step, (high - coordinate) / step))
        if entry <= 1e-9:
            return None
        elbow = (target[0] + delta[0] * entry / 2, target[1] + delta[1] * entry / 2)
        if elbow[1] < bottom or elbow[1] > top:
            corner = (center[0], elbow[1])
        else:
            corner = (elbow[0], center[1])
        return (elbow,) if math.dist(corner, elbow) <= 1e-9 else (corner, elbow)

    def _surface_vertex_is_normal(
        self,
        attachment: DatumAttachment | None,
        target: tuple[float, float],
        point: tuple[float, float],
    ) -> bool:
        if self.surface_vertices or not (
            self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled
        ):
            return False
        normal = self._attachment_normal(attachment, target)
        if normal is None:
            return False
        dx, dy = point[0] - target[0], point[1] - target[1]
        length = math.hypot(dx, dy)
        return length > 1e-9 and abs(dx * normal[1] - dy * normal[0]) <= 1e-8 * max(length, 1)

    def _next_datum_label(self) -> str:
        used = {datum.label.casefold() for datum in self.datums}
        return next(
            (chr(value) for value in range(65, 91) if chr(value).casefold() not in used), ""
        )

    @property
    def mechanical_frame_preview_vertices(self) -> tuple[tuple[float, float], ...]:
        if self.mechanical_frame_vertices:
            return tuple(self.mechanical_frame_vertices)
        if (
            not self.mechanical_frame_active
            or self.mechanical_frame_target is None
            or self.mechanical_frame_cursor is None
            or self.mechanical_frame_adding_vertex
            or self.surface_joint_pending
            or self.surface_joint is not None
            or self.mechanical_frame_attachment is None
        ):
            return ()
        preview = FeatureControlFrame(
            "0" * 32,
            (ToleranceRow("straightness", 0, 2),),
            self.mechanical_frame_cursor,
            leader_target_mm=self.mechanical_frame_target,
            leader_attachment=self.mechanical_frame_attachment,
            leader_arrow_style="closed_filled",
        )
        vertices = self._direct_frame_normal_vertices(preview)
        return tuple(reversed(vertices)) if vertices is not None else ()

    @property
    def mechanical_datum_preview(self) -> DatumIdentifier | None:
        if (
            not self.mechanical_datum_active
            or (self.mechanical_datum_target is None and not self.mechanical_datum_no_leader)
            or self.mechanical_datum_cursor is None
        ):
            return None
        datum = DatumIdentifier(
            "0" * 32,
            self._next_datum_label() or "?",
            self.mechanical_datum_cursor,
            self.mechanical_datum_target or self.mechanical_datum_cursor,
            self.canvas.active_layer_name,
            self.mechanical_datum_attachment,
            leader_offsets=tuple(
                (
                    point[0] - self.mechanical_datum_cursor[0],
                    point[1] - self.mechanical_datum_cursor[1],
                )
                for point in reversed(self.mechanical_datum_vertices)
            ),
            leader_auto_normal=self.mechanical_datum_auto_normal,
            leader_visible=not self.mechanical_datum_no_leader,
            layout_mode="shared",
            annotation_attachment=self.mechanical_datum_annotation_attachment,
        )
        if self.creation_datum_symbol_style == "circle":
            try:
                return self._oriented_datum(replace(datum, symbol_style="circle"))
            except ValueError:
                return None
        if not self.mechanical_datum_vertices and self.surface_joint is None:
            vertices = self._direct_datum_normal_vertices(datum)
            if vertices is not None:
                style = self._annotation_text_style(datum) or TextStyle()
                size = datum_box_dimensions(datum.label, style)
                point = self.mechanical_datum_cursor
                offsets = tuple((vertex[0] - point[0], vertex[1] - point[1]) for vertex in vertices)
                try:
                    offsets = reroute_leader_around_box(
                        point,
                        offsets,
                        vertices[-1],
                        datum.target_mm,
                        (point[0], point[1], point[0] + size[0], point[1] - size[1]),
                        orthogonal_box_side=True,
                    )
                except ValueError:
                    return None
                datum = replace(
                    datum,
                    leader_offsets=offsets,
                    leader_auto_normal=True,
                    leader_auto_route=True,
                    route_avoid_crossing=True,
                    route_track_target=True,
                    route_algorithm_version=4,
                    box_size_mm=size,
                    spline_normal_enabled=(
                        self.mechanical_datum_attachment is not None
                        and self.mechanical_datum_attachment.curve_kind == "spline"
                    ),
                )
        try:
            indication = self._new_surface_indication(
                self.mechanical_datum_target or self.mechanical_datum_cursor,
                self.mechanical_datum_cursor,
                auto_normal=self.surface_auto_normal,
            )
            if indication is not None:
                return cast("DatumIdentifier", self._preserve_surface_normal(datum, indication))
        except ValueError:
            return None
        return datum

    def _mechanical_datum_point(
        self,
        point: tuple[float, float],
        *,
        normal_at_box: bool = False,
        surface_normal_at_box: bool = False,
    ) -> None:
        if self.mechanical_datum_no_leader and self.mechanical_datum_target is None:
            self.mechanical_datum_target = point
        if self.mechanical_datum_target is None:
            if self.surface_pick_active:
                geometry, target = self._pick_surface_extension(point)
                annotation = None
                if geometry is None:
                    return
                self.surface_pick_active = False
            else:
                geometry, annotation, target = self._pick_target(
                    point, include_draft=self.creation_datum_symbol_style == "circle"
                )
            if target is None:
                return
            (
                self.mechanical_datum_attachment,
                self.mechanical_datum_annotation_attachment,
                self.mechanical_datum_target,
            ) = geometry, annotation, target
            self._message(
                "基准标识：指定标识框位置；V 添加顶点，F 表面指示；Shift+F 切换引线正交；Esc 取消。"
            )
            return
        if self.surface_joint_pending:
            if self.surface_vertex_pending:
                if len(self.surface_vertices) >= 64:
                    self._message("表面引线顶点最多 64 个。")
                    return
                previous = (
                    self.surface_vertices[-1]
                    if self.surface_vertices
                    else self.mechanical_datum_target
                )
                if math.dist(point, previous) <= 1e-9:
                    self._message("表面引线相邻顶点不能重合。")
                    return
                if not self.surface_vertices:
                    self.surface_auto_normal = self._surface_vertex_is_normal(
                        self.mechanical_datum_attachment, self.mechanical_datum_target, point
                    )
                self.surface_vertices.append(point)
                self.surface_vertex_pending = False
                self._message("基准标识：指定参考线位置，或输入 V 添加表面引线顶点。")
                return
            if (
                self.mechanical_leader_orthogonal
                and self.mechanical_datum_attachment is not None
                and not self.surface_vertices
                and not self.mechanical_datum_auto_normal
                and self._direct_normal_vertex(
                    self.mechanical_datum_attachment, self.mechanical_datum_target, point
                )
                is None
            ):
                self._message("无法确定表面引线法向或侧别；请重新指定位置，或按 Shift+F 关闭约束。")
                return
            previous = (
                self.surface_vertices[-1] if self.surface_vertices else self.mechanical_datum_target
            )
            if math.dist(point, previous) <= 1e-9:
                self._message("表面指示参考线位置不能与指向点重合。")
                return
            self.surface_joint = point
            self.surface_joint_pending = False
            self._message("基准标识：指定标识框位置；Esc 取消。")
            return
        if self.mechanical_datum_adding_vertex:
            if len(self.mechanical_datum_vertices) >= 64:
                self._message("引线顶点最多 64 个。")
                return
            previous = (
                self.mechanical_datum_vertices[-1]
                if self.mechanical_datum_vertices
                else self.mechanical_datum_target
                if self.surface_joint is None
                else None
            )
            if previous is not None and math.dist(point, previous) <= 1e-9:
                self._message("引线相邻顶点不能重合，请重新指定顶点。")
                return
            spline_normal_missing = False
            if (
                not self.mechanical_datum_vertices
                and (self.mechanical_leader_orthogonal or self.canvas.orthogonal_enabled)
                and self.surface_joint is None
            ):
                normal = self._datum_attachment_normal()
                if normal is not None:
                    dx = point[0] - self.mechanical_datum_target[0]
                    dy = point[1] - self.mechanical_datum_target[1]
                    self.mechanical_datum_auto_normal = math.hypot(dx, dy) > 1e-9 and abs(
                        dx * normal[1] - dy * normal[0]
                    ) <= 1e-8 * max(math.hypot(dx, dy), 1)
                elif (
                    self.mechanical_datum_attachment is not None
                    and self.mechanical_datum_attachment.curve_kind == "spline"
                ):
                    spline_normal_missing = True
            self.mechanical_datum_vertices.append(point)
            self.mechanical_datum_adding_vertex = False
            self._message(
                "样条该处无法确定法向；请指定标识框位置，或输入 V 添加顶点。"
                if spline_normal_missing
                else "基准标识：指定标识框位置，V 添加顶点，Enter 使用最后顶点；Esc 取消。"
            )
            return
        if (
            self.mechanical_leader_orthogonal
            and self.mechanical_datum_attachment is not None
            and not self.mechanical_datum_vertices
            and self.surface_joint is None
            and self._attachment_normal(
                self.mechanical_datum_attachment, self.mechanical_datum_target
            )
            is None
        ):
            self._message("无法确定引线法向或侧别；请移动基准框，或按 Shift+F 关闭约束。")
            return
        used = {datum.label.casefold() for datum in self.datums}
        default = self._next_datum_label()
        label, accepted = QInputDialog.getText(
            self.parent, "基准标识", _DATUM_NAME_PROMPT, text=default
        )
        if not accepted:
            self.cancel()
            return
        try:
            datum = DatumIdentifier(
                uuid4().hex,
                label,
                point,
                self.mechanical_datum_target,
                self.canvas.active_layer_name,
                self.mechanical_datum_attachment,
                leader_offsets=tuple(
                    (vertex[0] - point[0], vertex[1] - point[1])
                    for vertex in reversed(self.mechanical_datum_vertices)
                ),
                leader_auto_normal=self.mechanical_datum_auto_normal,
                spline_normal_enabled=(
                    self.mechanical_datum_auto_normal
                    and self.mechanical_datum_attachment is not None
                    and self.mechanical_datum_attachment.curve_kind == "spline"
                ),
                leader_visible=not self.mechanical_datum_no_leader,
                layout_mode="shared",
                annotation_attachment=self.mechanical_datum_annotation_attachment,
            )
            if (
                not self.mechanical_datum_vertices
                and self.surface_joint is None
                and not self.mechanical_datum_no_leader
                and self.creation_datum_symbol_style != "circle"
            ):
                vertices = self._direct_datum_normal_vertices(datum)
                if (
                    vertices is None
                    and self.mechanical_datum_attachment is not None
                    and self.mechanical_leader_orthogonal
                ):
                    raise ValueError("基准框与法向引线重叠；请移动基准框，或按 Shift+F 关闭约束。")
                if vertices is not None:
                    style = self._annotation_text_style(datum) or TextStyle()
                    size = datum_box_dimensions(datum.label, style)
                    offsets = tuple(
                        (vertex[0] - point[0], vertex[1] - point[1]) for vertex in vertices
                    )
                    offsets = reroute_leader_around_box(
                        point,
                        offsets,
                        vertices[-1],
                        datum.target_mm,
                        (point[0], point[1], point[0] + size[0], point[1] - size[1]),
                        orthogonal_box_side=True,
                    )
                    datum = replace(
                        datum,
                        leader_offsets=offsets,
                        leader_auto_normal=True,
                        leader_auto_route=True,
                        route_avoid_crossing=True,
                        route_track_target=True,
                        route_algorithm_version=4,
                        box_size_mm=size,
                        spline_normal_enabled=(
                            self.mechanical_datum_attachment is not None
                            and self.mechanical_datum_attachment.curve_kind == "spline"
                        ),
                    )
            if normal_at_box:
                style = self._annotation_text_style(datum) or TextStyle()
                width, height = datum.box_size_mm or datum_box_dimensions(datum.label, style)
                origin = (point[0] - width / 2, point[1] + height / 2)
                datum = replace(
                    datum,
                    position_mm=origin,
                    leader_offsets=((point[0] - origin[0], point[1] - origin[1]),),
                )
                target_local = (datum.target_mm[0] - origin[0], datum.target_mm[1] - origin[1])
                path = datum_leader_path((0, 0, width, -height), target_local, datum.leader_offsets)
                if not path:
                    raise ValueError("基准框与引线指向点重叠，请重新指定标识框位置。")
                datum = replace(datum, leader_offsets=(path[0],))
            indication = self._new_surface_indication(
                self.mechanical_datum_target, point, auto_normal=self.surface_auto_normal
            )
            if indication is not None:
                if surface_normal_at_box and indication.auto_normal:
                    datum = replace(
                        datum,
                        leader_auto_normal=False,
                        leader_auto_route=False,
                        route_avoid_crossing=False,
                        route_track_target=False,
                        route_algorithm_version=1,
                        leader_offsets=(),
                    )
                datum = cast("DatumIdentifier", self._preserve_surface_normal(datum, indication))
            if label.casefold() in used:
                raise ValueError("基准名称已存在。")
            if self.creation_datum_symbol_style == "circle":
                datum = self._oriented_datum(replace(datum, symbol_style="circle"))
                self.circular_datum_screen_geometry(datum)
        except ValueError as exc:
            self._message(str(exc))
            return
        if not self._annotation_layer_editable(datum.layer_name):
            return
        if self._commit({"add_datums": [datum.to_mapping()]}):
            self.mechanical_datum_active = False
            self.mechanical_datum_no_leader = False
            self.mechanical_datum_target = None
            self.mechanical_datum_attachment = None
            self.mechanical_datum_annotation_attachment = None
            self.mechanical_datum_cursor = None
            self.mechanical_datum_vertices.clear()
            self.mechanical_datum_adding_vertex = False
            self.mechanical_datum_auto_normal = False
            self.surface_joint = None
            self.surface_joint_pending = False
            self.surface_vertex_pending = False
            self.surface_vertices.clear()
            self.surface_auto_normal = False
            self._message("基准标识已放置。")

    def relayout_recorded_datum(
        self, datum: DatumIdentifier, styles: TextStyleTable | None = None
    ) -> DatumIdentifier:
        if datum.box_size_mm is None:
            return datum
        if datum.text_style_id is None:
            style = TextStyle()
        else:
            table = styles or (self.canvas.text_tools.styles if self.canvas.text_tools else None)
            if table is None:
                raise ValueError("当前图纸的文字样式不可用。")
            style = table.get(datum.text_style_id)
        size = datum_box_dimensions(datum.label, style)
        if size == datum.box_size_mm:
            return datum
        offsets = datum.leader_offsets
        if datum.route_algorithm_version >= 3:
            normal = (datum.position_mm[0] + offsets[-1][0], datum.position_mm[1] + offsets[-1][1])
            x, y = datum.position_mm
            offsets = reroute_leader_around_box(
                datum.position_mm,
                offsets,
                normal,
                datum.target_mm,
                (x, y, x + size[0], y - size[1]),
                orthogonal_box_side=datum.route_algorithm_version >= 4,
            )
        return replace(datum, box_size_mm=size, leader_offsets=offsets)

    def edit_datum_arrow_style(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再修改基准主引线箭头样式。")
            return
        datum = self._single_selected_datum()
        if datum is None or self.canvas.selected_entity_ids or self.canvas.selected_constraint_ids:
            self._message("请先单独选择一个基准标识。")
            return
        if self.canvas.selected_raster_ids or (
            self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids
        ):
            self._message("请先单独选择一个基准标识。")
            return
        labels = ("实心", "空心", "无")
        styles = ("filled", "open", "none")
        selected, accepted = QInputDialog.getItem(
            self.parent,
            "基准主引线箭头样式",
            "箭头样式：",
            labels,
            styles.index(datum.arrow_style),
            False,
        )
        if accepted and selected in labels:
            if not self._annotation_edit_is_current("datum", datum.datum_id, datum):
                return
            self._commit(
                {
                    "update_datums": [
                        replace(datum, arrow_style=styles[labels.index(selected)]).to_mapping()
                    ]
                }
            )

    def edit_datum_symbol_style(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再修改基准标识样式。")
            return
        datum = self._single_selected_datum()
        if datum is None or self.canvas.selected_entity_ids or self.canvas.selected_constraint_ids:
            self._message("请先单独选择一个基准标识。")
            return
        if self.canvas.selected_raster_ids or (
            self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids
        ):
            self._message("请先单独选择一个基准标识。")
            return
        labels, styles = ("矩形", "圆圈"), ("rectangle", "circle")
        selected, accepted = QInputDialog.getItem(
            self.parent,
            "基准标识样式",
            "标识样式：",
            labels,
            styles.index(datum.symbol_style),
            False,
        )
        if not accepted or selected not in labels:
            return
        if not self._annotation_edit_is_current("datum", datum.datum_id, datum):
            return
        chosen_style = styles[labels.index(selected)]
        if chosen_style == "circle" and (
            not datum.leader_visible or datum.surface_indication is not None
        ):
            self._message("圆圈基准需要普通引线；请先移除表面指示。")
            return
        candidate = self._oriented_datum(replace(datum, symbol_style=chosen_style))
        if candidate.symbol_style == "circle":
            try:
                projected = self.display_datum(candidate)
                if projected is None:
                    raise ValueError("基准不在当前工作平面。")
                self.circular_datum_screen_geometry(projected)
            except ValueError as exc:
                self._message(str(exc))
                return
        self._commit({"update_datums": [candidate.to_mapping()]})

    def edit_datum_text_style(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再修改基准文字样式。")
            return
        datum = (
            next((item for item in self.datums if item.datum_id == self.selected_id), None)
            if self.selected_kind == "datum"
            else None
        )
        if datum is None or len(self.selected_ids) != 1:
            self._message("请先选择一个基准标识。")
            return
        if self.canvas.text_tools is None:
            self._message("当前图纸的文字样式不可用。")
            return
        styles = self.canvas.text_tools.styles.styles
        labels = ["默认（不引用样式）", *(f"{style.name} ({style.style_id})" for style in styles)]
        identities: list[str | None] = [None, *(style.style_id for style in styles)]
        current = identities.index(datum.text_style_id) if datum.text_style_id in identities else 0
        selected, accepted = QInputDialog.getItem(
            self.parent, "基准文字样式", "文字样式：", labels, current, False
        )
        if accepted and selected in labels:
            style_id = identities[labels.index(selected)]
            try:
                updated = self.relayout_recorded_datum(replace(datum, text_style_id=style_id))
            except (KeyError, ValueError) as exc:
                self._message(str(exc))
                return
            self._commit({"update_datums": [updated.to_mapping()]})

    def edit_surface_extension(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再编辑表面延伸线。")
            return
        if (
            self.selected_id is None
            or self.selected_ids != {self.selected_id}
            or self.canvas.selected_entity_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
        ):
            self._message("请先单独选择一个带表面延伸线的标注。")
            return
        item: DatumIdentifier | FeatureControlFrame | None
        if self.selected_kind == "datum":
            item = next(
                (datum for datum in self.datums if datum.datum_id == self.selected_id), None
            )
        elif self.selected_kind == "frame":
            item = next(
                (frame for frame in self.frames if frame.frame_id == self.selected_id), None
            )
        else:
            item = None
        attachment = (
            item.attachment
            if isinstance(item, DatumIdentifier)
            else item.leader_attachment
            if item is not None
            else None
        )
        if item is None or attachment is None or attachment.surface_extension is None:
            self._message("所选标注没有表面延伸线。")
            return
        layer = self.canvas.layer_table.get(item.layer_name)
        if not layer.displayed or layer.locked:
            self._message("标注图层不可编辑，请先显示并解锁。")
            return
        revision = self.source_revision() if self.source_revision is not None else None
        dialog = SurfaceExtensionDialog(attachment.surface_extension, self.parent)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        if (
            revision is not None
            and self.source_revision is not None
            and revision != self.source_revision()
        ):
            self._message("图纸已变化，请重新选择并编辑表面延伸线。")
            return
        updated = replace(attachment, surface_extension=dialog.value())
        if isinstance(item, DatumIdentifier):
            committed = self._commit(
                {"update_datums": [replace(item, attachment=updated).to_mapping()]}
            )
        else:
            committed = self._commit(
                {"update_frames": [replace(item, leader_attachment=updated).to_mapping()]}
            )
        if committed:
            self._message("表面延伸线设置已更新。")

    @staticmethod
    def _drop_datum_geometry_attachment(datum: DatumIdentifier) -> DatumIdentifier:
        return replace(
            datum,
            attachment=None,
            leader_auto_normal=False,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
            spline_normal_enabled=False,
            surface_indication=(
                replace(
                    datum.surface_indication,
                    auto_normal=False,
                    auto_route=False,
                    route_avoid_crossing=False,
                )
                if datum.surface_indication is not None
                else None
            ),
        )

    @staticmethod
    def _drop_frame_geometry_attachment(frame: FeatureControlFrame) -> FeatureControlFrame:
        return replace(
            frame,
            leader_attachment=None,
            leader_auto_normal=False,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
            surface_indication=(
                replace(
                    frame.surface_indication,
                    auto_normal=False,
                    auto_route=False,
                    route_avoid_crossing=False,
                )
                if frame.surface_indication is not None
                else None
            ),
        )

    def _selected_surface_annotation(self) -> DatumIdentifier | FeatureControlFrame | None:
        if (
            self.selected_id is None
            or self.selected_ids != {self.selected_id}
            or self.canvas.selected_entity_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
        ):
            return None
        if self.selected_kind == "datum":
            item = next(
                (datum for datum in self.datums if datum.datum_id == self.selected_id), None
            )
            return item if item is not None and item.leader_visible else None
        if self.selected_kind == "frame":
            frame = next((item for item in self.frames if item.frame_id == self.selected_id), None)
            return frame if frame is not None and frame.leader_target_mm is not None else None
        return None

    def begin_surface_indication_edit(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再编辑表面指示。")
            return
        item = self._selected_surface_annotation()
        if item is None:
            self._message("请先单独选择有引线的基准或公差框。")
            return
        layer = self.canvas.layer_table.get(item.layer_name)
        if not layer.displayed or layer.locked:
            self._message("标注图层不可编辑，请先显示并解锁。")
            return
        self.surface_edit = item
        self.surface_edit_cursor = None
        self.surface_edit_revision = (
            self.source_revision() if self.source_revision is not None else None
        )
        self.canvas.set_tool("选择元素")
        self._message("指定表面指示参考线位置；Esc 取消。")

    @staticmethod
    def _preserve_surface_normal(
        item: DatumIdentifier | FeatureControlFrame, indication: SurfaceIndication
    ) -> DatumIdentifier | FeatureControlFrame:
        previous = item.surface_indication
        if previous is not None and previous.auto_normal:
            indication = replace(
                indication,
                leader_offsets_mm=previous.leader_offsets_mm,
                auto_normal=True,
                auto_route=False,
                route_avoid_crossing=False,
            )
        elif item.leader_auto_normal and indication.auto_normal:
            item = replace(
                item,
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
        elif item.leader_auto_normal:
            vertex = item.leader_offsets[-1]
            target = item.target_mm if isinstance(item, DatumIdentifier) else item.leader_target_mm
            if target is None:
                raise ValueError("missing leader target")
            offset = (
                item.position_mm[0] + vertex[0] - target[0],
                item.position_mm[1] + vertex[1] - target[1],
            )
            indication = replace(indication, leader_offsets_mm=(offset,), auto_normal=True)
            item = replace(
                item,
                leader_offsets=item.leader_offsets[:-1],
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
        return replace(item, surface_indication=indication)

    @property
    def surface_edit_preview(self) -> DatumIdentifier | FeatureControlFrame | None:
        item, cursor = self.surface_edit, self.surface_edit_cursor
        if item is None or cursor is None:
            return None
        target = item.target_mm if isinstance(item, DatumIdentifier) else item.leader_target_mm
        if target is None or math.dist(cursor, target) <= 1e-9:
            return None
        style = self._annotation_text_style(item) or TextStyle()
        indication = self._new_surface_indication(
            target, item.position_mm, text_height=style.height_mm, joint=cursor
        )
        if indication is None:
            return None
        try:
            updated = self._preserve_surface_normal(item, indication)
        except ValueError:
            return None
        if isinstance(updated, DatumIdentifier):
            return updated
        frame = updated
        anchor = self._frame_leader_anchor(frame)
        return (
            None
            if anchor is None
            else replace(
                frame,
                leader_anchor_offset=(
                    anchor[0] - frame.position_mm[0],
                    anchor[1] - frame.position_mm[1],
                ),
            )
        )

    def _finish_surface_indication_edit(self, point: tuple[float, float]) -> None:
        item = self.surface_edit
        if item is None:
            return
        if (
            self.source_revision is not None
            and self.surface_edit_revision is not None
            and self.source_revision() != self.surface_edit_revision
        ) or item not in (*self.datums, *self.frames):
            self.cancel()
            self._message("图纸已变化，请重新选择标注。")
            return
        target = item.target_mm if isinstance(item, DatumIdentifier) else item.leader_target_mm
        if target is None or math.dist(point, target) <= 1e-9:
            self._message("表面指示参考线位置不能与指向点重合。")
            return
        self.surface_joint = point
        style = self._annotation_text_style(item) or TextStyle()
        indication = self._new_surface_indication(
            target, item.position_mm, text_height=style.height_mm
        )
        if indication is None:
            return
        try:
            updated = self._preserve_surface_normal(item, indication)
        except ValueError:
            self._message("参考线位置与保留的法向顶点重合，请选择其他位置。")
            return
        if isinstance(updated, DatumIdentifier):
            committed = self._commit({"update_datums": [updated.to_mapping()]})
        else:
            frame = updated
            anchor = self._frame_leader_anchor(frame)
            if anchor is None:
                self._message("公差框与引线指向点重叠，请重新指定位置。")
                return
            frame = replace(
                frame,
                leader_anchor_offset=(
                    anchor[0] - frame.position_mm[0],
                    anchor[1] - frame.position_mm[1],
                ),
            )
            committed = self._commit({"update_frames": [frame.to_mapping()]})
        if committed:
            self.surface_edit = None
            self.surface_edit_revision = None
            self.surface_edit_cursor = None
            self.surface_joint = None
            self._message("表面指示已更新。")

    def remove_surface_indication(self) -> None:
        if self.pending:
            self._message("请先完成当前操作，再切换边线指示。")
            return
        item = self._selected_surface_annotation()
        if item is None or item.surface_indication is None:
            self._message("请先单独选择带表面指示的标注。")
            return
        surface = item.surface_indication
        lost_datum_normal = False
        if surface.auto_normal and len(item.leader_offsets) + len(surface.leader_offsets_mm) > 64:
            self._message("切换后引线顶点将超过 64 个，请先减少顶点。")
            return
        if isinstance(item, DatumIdentifier):
            datum = item
            if surface.auto_normal:
                transferred = tuple(
                    (
                        item.target_mm[0] + x - item.position_mm[0],
                        item.target_mm[1] + y - item.position_mm[1],
                    )
                    for x, y in reversed(surface.leader_offsets_mm)
                )
                attached = item.attachment is not None
                lost_datum_normal = not attached
                datum = replace(
                    item,
                    surface_indication=None,
                    leader_offsets=(*item.leader_offsets, *transferred),
                    leader_auto_normal=attached,
                    leader_auto_route=False,
                    route_avoid_crossing=False,
                    route_track_target=False,
                    route_algorithm_version=1,
                    spline_normal_enabled=attached
                    and item.attachment is not None
                    and item.attachment.curve_kind == "spline",
                )
            else:
                datum = replace(item, surface_indication=None)
            committed = self._commit({"update_datums": [datum.to_mapping()]})
        else:
            frame = replace(item, surface_indication=None)
            if surface.auto_normal and item.leader_target_mm is not None:
                transferred = tuple(
                    (
                        item.leader_target_mm[0] + x - item.position_mm[0],
                        item.leader_target_mm[1] + y - item.position_mm[1],
                    )
                    for x, y in reversed(surface.leader_offsets_mm)
                )
                frame = replace(
                    frame,
                    leader_offsets=(*frame.leader_offsets, *transferred),
                    leader_auto_normal=frame.leader_attachment is not None,
                    leader_auto_route=False,
                    route_avoid_crossing=False,
                    route_track_target=False,
                    route_algorithm_version=1,
                )
            anchor = self._frame_leader_anchor(frame)
            if anchor is None:
                self._message("公差框与引线指向点重叠，无法切换。")
                return
            frame = replace(
                frame,
                leader_anchor_offset=(
                    anchor[0] - frame.position_mm[0],
                    anchor[1] - frame.position_mm[1],
                ),
            )
            committed = self._commit({"update_frames": [frame.to_mapping()]})
        if committed:
            self._message(
                "已切换为边线指示；附着目标缺失，法向约束已解除。"
                if lost_datum_normal
                else "已切换为边线指示。"
            )

    def _message(self, value: str) -> None:
        self.canvas.message = value
        self.parent.status_label.setText(value)

    def _annotation_text_style(
        self, annotation: FeatureControlFrame | DatumIdentifier
    ) -> TextStyle | None:
        if annotation.text_style_id is None:
            return TextStyle()
        if self.canvas.text_tools is None:
            return None
        return next(
            (
                item
                for item in self.canvas.text_tools.styles.styles
                if item.style_id == annotation.text_style_id
            ),
            None,
        )

    def _layout(self, frame: FeatureControlFrame) -> FrameLayout:
        style = self._annotation_text_style(frame) or TextStyle()
        key = (frame, style)
        if key not in self._cache:
            self._cache[key] = layout_frame(frame, self.manager, style)
        return self._cache[key]

    def _frame_font_warning(self, frame: FeatureControlFrame) -> str:
        style = self._annotation_text_style(frame)
        return frame_font_warning(frame, self.manager, style, layout=self._layout(frame))

    def _transform(self, frame: FeatureControlFrame) -> QTransform:
        position = self.canvas.local_to_screen_precise(frame.position_mm)
        transform = QTransform()
        transform.translate(position.x(), position.y())
        transform.rotate(-frame.rotation_deg)
        transform.scale(self.canvas.view_scale, self.canvas.view_scale)
        return transform

    def screen_bounds(self, frame: FeatureControlFrame) -> QRectF:
        return self._transform(frame).mapRect(self._layout(frame).bounds)

    def surface_indication_screen_geometry(
        self, target: tuple[float, float], indication: SurfaceIndication
    ) -> tuple[tuple[QPointF, QPointF], tuple[QPointF, ...], QPointF]:
        reference, leader, landing = surface_indication_geometry(target, indication)
        return (
            (
                self.canvas.local_to_screen_precise(reference[0]),
                self.canvas.local_to_screen_precise(reference[1]),
            ),
            tuple(self.canvas.local_to_screen_precise(point) for point in leader),
            self.canvas.local_to_screen_precise(landing),
        )

    def _surface_screen_arrow(
        self, leader: tuple[QPointF, ...], indication: SurfaceIndication
    ) -> QPolygonF:
        start = (leader[-2].x(), leader[-2].y())
        end = (leader[-1].x(), leader[-1].y())
        size = (indication.arrow_size_mm or 2.5) * self.canvas.view_scale
        triangle = datum_triangle(start, end, min(size, math.dist(start, end)))
        return QPolygonF([QPointF(*point) for point in triangle])

    def _surface_indication_path(
        self, target: tuple[float, float], indication: SurfaceIndication | None
    ) -> QPainterPath:
        path = QPainterPath()
        if indication is None:
            return path
        reference, leader, _ = self.surface_indication_screen_geometry(target, indication)
        path.moveTo(reference[0])
        path.lineTo(reference[1])
        path.moveTo(leader[0])
        for point in leader[1:]:
            path.lineTo(point)
        triangle = self._surface_screen_arrow(leader, indication)
        if triangle:
            path.addPolygon(triangle)
            path.closeSubpath()
        return path

    def _surface_arrow_contains(
        self, target: tuple[float, float], indication: SurfaceIndication | None, point: QPointF
    ) -> bool:
        if indication is None:
            return False
        _, leader, _ = self.surface_indication_screen_geometry(target, indication)
        return self._surface_screen_arrow(leader, indication).containsPoint(
            point, Qt.FillRule.OddEvenFill
        )

    def _draw_surface_indication(
        self, painter: QPainter, target: tuple[float, float], indication: SurfaceIndication
    ) -> None:
        reference, leader, _ = self.surface_indication_screen_geometry(target, indication)
        painter.drawLine(reference[0], reference[1])
        painter.drawPolyline(QPolygonF(leader))
        triangle = self._surface_screen_arrow(leader, indication)
        if triangle:
            painter.setBrush(painter.pen().color())
            painter.drawPolygon(triangle)

    def surface_screen_path(
        self,
        attachment: DatumAttachment | None,
        *,
        source_sketches: tuple[Sketch, ...] | None = None,
        target_frame: WorkPlaneFrame | None = None,
        delta: tuple[float, float] = (0, 0),
    ) -> tuple[QPointF, ...]:
        if attachment is None or attachment.surface_extension is None:
            return ()
        provider = self.canvas.associative_sketches_provider
        if source_sketches is None:
            if provider is None:
                return ()
            sketches = provider()
        else:
            sketches = source_sketches
        sketch = next((item for item in sketches if item.sketch_id == attachment.sketch_id), None)
        if sketch is None:
            return ()
        entity = next(
            (item for item in sketch.entities if item.entity_id == attachment.reference.entity_id),
            None,
        )
        if not isinstance(entity, LineEntity | ArcEntity):
            return ()
        spec = attachment.surface_extension
        try:
            geometry = surface_extension_geometry(
                entity, spec.side, spec.distance_mm, spec.offset_mm, spec.overshoot_mm
            )
        except ValueError:
            return ()
        local = [geometry.start_mm, geometry.end_mm]
        if geometry.center_mm is not None:
            cx, cy = geometry.center_mm
            angle = math.atan2(geometry.start_mm[1] - cy, geometry.start_mm[0] - cx)
            radius = math.dist(geometry.start_mm, geometry.center_mm)
            steps = max(1, math.ceil(abs(geometry.sweep_angle_deg) / 3))
            local = [
                (
                    cx
                    + radius * math.cos(angle + math.radians(geometry.sweep_angle_deg) * i / steps),
                    cy
                    + radius * math.sin(angle + math.radians(geometry.sweep_angle_deg) * i / steps),
                )
                for i in range(steps + 1)
            ]
        destination = target_frame or self.canvas.drawing_view_frame
        try:
            project_coplanar_vector((0, 0), sketch.frame, destination)
        except ValueError:
            return ()
        world_points = (sketch.frame.local_to_world(point) for point in local)
        return tuple(
            self.canvas.local_to_screen_precise((point[0] + delta[0], point[1] + delta[1]))
            for point in (destination.world_to_local(world) for world in world_points)
        )

    def _frame_leader_anchor(self, frame: FeatureControlFrame) -> tuple[float, float] | None:
        result = legacy_frame_leader_layout(frame, self.manager, bounds=self._layout(frame).bounds)
        return result[0] if result is not None else None

    def legacy_frame_export_anchors(
        self, frames: tuple[FeatureControlFrame, ...]
    ) -> dict[str, tuple[float, float]]:
        """Snapshot visible legacy anchors without changing the drawing."""
        anchors: dict[str, tuple[float, float]] = {}
        for frame in frames:
            if frame.leader_target_mm is None or frame.leader_anchor_offset is not None:
                continue
            anchor = self._frame_leader_anchor(frame)
            if anchor is None:
                raise ValueError(f"公差框 {frame.frame_id[:8]} 的引线无法计算框侧锚点。")
            anchors[frame.frame_id] = (
                anchor[0] - frame.position_mm[0],
                anchor[1] - frame.position_mm[1],
            )
        return anchors

    def legacy_frame_export_font_notices(
        self, frames: tuple[FeatureControlFrame, ...], anchors: Mapping[str, tuple[float, float]]
    ) -> tuple[str, ...]:
        """Report font substitutions and missing glyphs used by exported anchors."""
        notices: list[str] = []
        for frame in frames:
            if frame.frame_id not in anchors:
                continue
            warning = self._frame_font_warning(frame)
            if warning:
                notices.append(f"公差框 {frame.frame_id[:8]} 的导出锚点：{warning}")
        return tuple(notices)

    def legacy_frame_export_bounds(
        self, frames: tuple[FeatureControlFrame, ...], anchors: Mapping[str, tuple[float, float]]
    ) -> dict[str, tuple[float, float, float, float]]:
        """Capture the exact font-dependent rectangles used for legacy anchors."""
        bounds: dict[str, tuple[float, float, float, float]] = {}
        for frame in frames:
            if frame.frame_id in anchors:
                rect = self._layout(frame).bounds
                bounds[frame.frame_id] = (rect.left(), rect.top(), rect.right(), rect.bottom())
        return bounds

    def graphic_frame_export_widths(
        self, frames: tuple[FeatureControlFrame, ...]
    ) -> dict[str, tuple[tuple[float, ...], ...]]:
        """Snapshot each painted frame cell width for graphic DXF conversion."""
        return {
            frame.frame_id: tuple(
                tuple(cell.bounds.width() for cell in row.cells) for row in self._layout(frame).rows
            )
            for frame in frames
        }

    def graphic_frame_export_font_notices(
        self, frames: tuple[FeatureControlFrame, ...]
    ) -> tuple[str, ...]:
        """Report substitutions already visible in frozen graphic text."""
        notices: list[str] = []
        for frame in frames:
            warning = self._frame_font_warning(frame)
            if warning:
                notices.append(f"公差框 {frame.frame_id[:8]} 的图形文字：{warning}")
        return tuple(notices)

    def graphic_frame_export_glyphs(
        self, frames: tuple[FeatureControlFrame, ...]
    ) -> dict[str, FrameGlyphs]:
        """Freeze shaped text geometry in canvas-local millimetres on the GUI thread."""
        result: dict[str, FrameGlyphs] = {}
        for frame in frames:
            layout = self._layout(frame)
            glyphs: list[GlyphContours] = []
            for row in layout.rows:
                for cell in row.cells:
                    if cell.text is None:
                        continue
                    x = cell.bounds.left() + 0.8 * layout.scale
                    if cell.diameter:
                        x += 3.3 * layout.scale
                    glyphs.extend(
                        _capture_text_glyphs(
                            cell.text,
                            x - cell.text.bounds.left(),
                            cell.bounds.center().y() - cell.text.bounds.center().y(),
                        )
                    )
                    x += cell.text.bounds.width()
                    if cell.modifier_text is not None:
                        x += 0.6 * layout.scale
                        factor = cell.modifier_scale
                        glyphs.extend(
                            _capture_text_glyphs(
                                cell.modifier_text,
                                x
                                + 1.45 * layout.scale
                                - cell.modifier_text.bounds.center().x() * factor,
                                cell.bounds.center().y()
                                - cell.modifier_text.bounds.center().y() * factor,
                                factor,
                            )
                        )
            result[frame.frame_id] = tuple(glyphs)
        return result

    def graphic_datum_export_snapshots(
        self, datums: tuple[DatumIdentifier, ...]
    ) -> dict[str, DatumGraphicSnapshot]:
        """Freeze the same datum geometry and glyphs currently painted on the canvas."""
        result: dict[str, DatumGraphicSnapshot] = {}
        for datum in datums:
            label = self._datum_label_layout(datum)
            style = self._annotation_text_style(datum) or TextStyle()
            padding = style.height_mm / 3.5
            width, height = self._datum_box_size(datum, label)
            fit = 1.0
            if (
                datum.layout_mode == "shared"
                and label.bounds.width() > 0
                and label.bounds.height() > 0
            ):
                fit = min(
                    1.0,
                    max(0.0, width - 1.6 * padding) / label.bounds.width(),
                    max(0.0, height - 0.8 * padding) / label.bounds.height(),
                )
            if fit <= 0:
                raise ValueError("基准文字无法放入标注框")
            glyphs = _capture_text_glyphs(
                label,
                width / 2 - label.bounds.center().x() * fit,
                height / 2 - label.bounds.center().y() * fit,
                fit,
            )
            target = datum.target_mm
            if datum.surface_indication is not None:
                _, _, target = surface_indication_geometry(target, datum.surface_indication)
            relative_target = (target[0] - datum.position_mm[0], target[1] - datum.position_mm[1])
            leader = (
                datum_leader_path((0, 0, width, -height), relative_target, datum.leader_offsets)
                if datum.leader_visible
                else ()
            )
            if datum.symbol_style == "circle":
                radius = width / 2
                _, leader, _ = circular_datum_geometry(
                    (radius, -radius),
                    relative_target,
                    radius,
                    radius * 1.6,
                    bar_direction=datum.bar_direction,
                )
            arrow: tuple[tuple[float, float], ...] = ()
            if leader and datum.arrow_style != "none" and datum.symbol_style != "circle":
                arrow_size = (
                    datum.surface_indication.arrow_size_mm if datum.surface_indication else None
                ) or (2.5 * padding if datum.layout_mode == "shared" else 2.5)
                arrow = datum_triangle(
                    leader[-2], leader[-1], min(arrow_size, math.dist(*leader[-2:]))
                )
                if datum.layout_mode == "legacy" and arrow:
                    arrow = (arrow[0], arrow[2], arrow[1])
            result[datum.datum_id] = DatumGraphicSnapshot(
                datum,
                width,
                height,
                leader,
                arrow,
                glyphs,
            )
        return result

    def legacy_datum_export_snapshots(
        self, datums: tuple[DatumIdentifier, ...]
    ) -> dict[str, DatumNativeSnapshot]:
        """Freeze old datum box dimensions without using viewport coordinates."""
        result: dict[str, DatumNativeSnapshot] = {}
        for datum in datums:
            if datum.layout_mode == "legacy":
                width, height = self._datum_box_size(datum, self._datum_label_layout(datum))
                result[datum.datum_id] = DatumNativeSnapshot(datum, width, height)
        return result

    def graphic_datum_export_font_notices(
        self, datums: tuple[DatumIdentifier, ...]
    ) -> tuple[str, ...]:
        """Report substitutions in the datum glyphs captured for graphic export."""
        notices: list[str] = []
        for datum in datums:
            warning = self._datum_font_warning(datum)
            if warning:
                notices.append(f"基准 {datum.datum_id[:8]} 的图形文字：{warning}")
        return tuple(notices)

    def legacy_datum_export_font_notices(
        self, datums: tuple[DatumIdentifier, ...]
    ) -> tuple[str, ...]:
        """Report substitutions used to measure native legacy datum boxes."""
        notices: list[str] = []
        for datum in datums:
            if datum.layout_mode == "legacy":
                warning = self._datum_font_warning(datum)
                if warning:
                    notices.append(f"基准 {datum.datum_id[:8]} 的导出框：{warning}")
        return tuple(notices)

    def legacy_frame_export_skipped_vertices(
        self, frames: tuple[FeatureControlFrame, ...], anchors: Mapping[str, tuple[float, float]]
    ) -> dict[str, int]:
        """Count initial vertices clipped inside each visible legacy frame."""
        skipped: dict[str, int] = {}
        for frame in frames:
            if frame.frame_id in anchors:
                result = legacy_frame_leader_layout(
                    frame, self.manager, bounds=self._layout(frame).bounds
                )
                if result is not None and result[1]:
                    skipped[frame.frame_id] = result[1]
        return skipped

    def frame_screen_leader(
        self, frame: FeatureControlFrame, *, bounds: QRectF | None = None
    ) -> tuple[QPointF, ...]:
        if frame.leader_target_mm is None:
            return ()
        target = frame.leader_target_mm
        if frame.surface_indication is not None:
            _, _, target = surface_indication_geometry(target, frame.surface_indication)
        if frame.leader_anchor_offset is not None:
            anchor = (
                frame.position_mm[0] + frame.leader_anchor_offset[0],
                frame.position_mm[1] + frame.leader_anchor_offset[1],
            )
            world = (
                anchor,
                *(
                    (frame.position_mm[0] + x, frame.position_mm[1] + y)
                    for x, y in frame.leader_offsets
                ),
                target,
            )
            return tuple(self.canvas.local_to_screen_precise(point) for point in world)
        transform = self._transform(frame)
        inverse, valid = transform.inverted()
        if not valid:
            return ()
        screen_target = inverse.map(self.canvas.local_to_screen_precise(target))
        vertices = tuple(
            inverse.map(
                self.canvas.local_to_screen_precise(
                    (frame.position_mm[0] + x, frame.position_mm[1] + y)
                )
            )
            for x, y in frame.leader_offsets
        )
        rect = bounds if bounds is not None else self._layout(frame).bounds
        points = datum_leader_path(
            (rect.left(), rect.top(), rect.right(), rect.bottom()),
            (screen_target.x(), screen_target.y()),
            tuple((point.x(), point.y()) for point in vertices),
        )
        return tuple(transform.map(QPointF(*point)) for point in points)

    def visible_extent_points(self) -> tuple[tuple[float, float], ...]:
        """Return visible annotation extents in drawing coordinates for zoom-to-fit."""
        screen: list[QPointF] = []

        def rectangle(rect: QRectF) -> None:
            screen.extend((rect.topLeft(), rect.bottomRight()))

        def polygon(points: QPolygonF) -> None:
            screen.extend(points.at(index) for index in range(points.size()))

        def surface(target: tuple[float, float], indication: SurfaceIndication | None) -> None:
            path = self._surface_indication_path(target, indication)
            if not path.isEmpty():
                rectangle(path.boundingRect())

        for source in self.frames:
            frame = self.display_frame(source)
            if frame is None or not self.canvas.layer_table.get(frame.layer_name).displayed:
                continue
            rectangle(self.screen_bounds(frame))
            leader = self.frame_screen_leader(frame)
            screen.extend(leader)
            polygon(self._frame_screen_arrow(frame, leader))
            screen.extend(self.surface_screen_path(frame.leader_attachment))
            if frame.leader_target_mm is not None:
                surface(frame.leader_target_mm, frame.surface_indication)
        for source in self.datums:
            datum = self.display_datum(source)
            if datum is None or not self.canvas.layer_table.get(datum.layer_name).displayed:
                continue
            rect = self.datum_screen_bounds(datum)
            rectangle(rect)
            leader, arrow = self.datum_screen_path(datum, rect)
            screen.extend(leader)
            polygon(arrow)
            screen.extend(self.surface_screen_path(datum.attachment))
            surface(datum.target_mm, datum.surface_indication)
        for source in self.reference_dimensions:
            dimension = self.display_reference(source)
            if dimension is None or not self.canvas.layer_table.get(dimension.layer_name).displayed:
                continue
            layout = self.reference_layout(source)
            assert layout is not None
            rectangle(layout.label)
            for start, end in layout.lines:
                screen.extend((start, end))
            for arrow in layout.arrows:
                screen.extend(arrow)
        return tuple(self.canvas.screen_to_local(point) for point in screen)

    def reference_bounds(self, dimension: DetachedDimension) -> QRectF:
        layout = self.reference_layout(dimension)
        return layout.label if layout else QRectF()

    def reference_layout(self, source: DetachedDimension) -> ReferenceDimensionLayout | None:
        displayed = self.display_reference(source)
        if displayed is None:
            return None
        return layout_reference_dimension(
            displayed,
            self.canvas,
            ordinate_bent=source.angle_deg != 0
            if source.kind in ("ordinate_x", "ordinate_y")
            else None,
        )

    def display_reference(self, dimension: DetachedDimension) -> DetachedDimension | None:
        """Project a saved reference dimension onto the current drawing plane."""
        try:
            return project_reference_dimension(
                dimension, WorkPlaneFrame.xy(), self.canvas.drawing_view_frame
            )
        except ValueError:
            return None

    def display_frame(self, frame: FeatureControlFrame) -> FeatureControlFrame | None:
        try:
            projected = project_annotation(
                frame, WorkPlaneFrame.xy(), self.canvas.drawing_view_frame
            )
            return cast("FeatureControlFrame", projected)
        except ValueError:
            return None

    def display_datum(self, datum: DatumIdentifier) -> DatumIdentifier | None:
        try:
            projected = project_annotation(
                self._oriented_datum(datum), WorkPlaneFrame.xy(), self.canvas.drawing_view_frame
            )
            return cast("DatumIdentifier", projected)
        except ValueError:
            return None

    def _oriented_datum(self, datum: DatumIdentifier) -> DatumIdentifier:
        if datum.symbol_style != "circle":
            return datum
        provider = self.canvas.associative_sketches_provider
        direction = resolve_datum_bar_direction(
            datum,
            {sketch.sketch_id: sketch for sketch in provider()} if provider is not None else {},
            {frame.frame_id: frame for frame in self.frames},
        )
        if direction is None and datum.attachment is None and datum.annotation_attachment is None:
            # Draft geometry has no replayable attachment until it is submitted.
            # Capture its tangent without persisting a reference to an absent sketch.
            sources = self.parent.dimension_sources()
            attachment, _ = self._pick_attachment(datum.target_mm, sketches=sources)
            if attachment is not None:
                direction = resolve_datum_bar_direction(
                    replace(datum, attachment=attachment),
                    {sketch.sketch_id: sketch for sketch in sources},
                )
        return replace(datum, bar_direction=direction)

    def _drawing_point(self, point: tuple[float, float]) -> tuple[float, float]:
        try:
            project_coplanar_vector((0, 0), self.canvas.drawing_view_frame, WorkPlaneFrame.xy())
        except ValueError as exc:
            raise ValueError("当前工作平面与图纸不共面，无法放置或编辑标注。") from exc
        return WorkPlaneFrame.xy().world_to_local(
            self.canvas.drawing_view_frame.local_to_world(point)
        )

    def _view_point(self, point: tuple[float, float]) -> tuple[float, float]:
        project_coplanar_vector((0, 0), WorkPlaneFrame.xy(), self.canvas.drawing_view_frame)
        return self.canvas.drawing_view_frame.world_to_local(
            WorkPlaneFrame.xy().local_to_world(point)
        )

    def _frame_screen_arrow(
        self, frame: FeatureControlFrame, points: tuple[QPointF, ...]
    ) -> QPolygonF:
        if len(points) < 2:
            return QPolygonF()
        start = (points[-2].x(), points[-2].y())
        end = (points[-1].x(), points[-1].y())
        indication = frame.surface_indication
        size = (indication.arrow_size_mm if indication else None) or 2.5
        arrow_geometry = (
            frame_leader_arrow if frame.leader_arrow_style == "closed_filled" else datum_triangle
        )
        triangle = arrow_geometry(
            start, end, min(size * self.canvas.view_scale, math.dist(start, end))
        )
        return QPolygonF([QPointF(*point) for point in triangle])

    def _unresolved_datum_labels(self, frame: FeatureControlFrame) -> tuple[str, ...]:
        known = {datum.datum_id: datum.label for datum in self.datums}
        return tuple(
            dict.fromkeys(
                ref.label
                for row in frame.rows
                for ref in row.datums
                if ref.datum_id is None or known.get(ref.datum_id) != ref.label
            )
        )

    def _frame_attachment_lost(self, frame: FeatureControlFrame) -> bool:
        annotation = frame.leader_annotation_attachment
        if annotation is not None:
            if annotation.kind == "frame":
                return not any(item.frame_id == annotation.object_id for item in self.frames)
            if annotation.kind == "reference_dimension":
                return not any(
                    item.dimension_id == annotation.object_id for item in self.reference_dimensions
                )
            provider = self.canvas.associative_sketches_provider
            if provider is None:
                return False
            return not any(
                sketch.sketch_id == annotation.sketch_id
                and any(
                    item.constraint_id == annotation.object_id
                    and (
                        item.position_mm is not None
                        or (annotation.anchor == "text" and item.text_position_mm is not None)
                    )
                    for item in sketch.constraints
                )
                for sketch in provider()
            )
        attachment = frame.leader_attachment
        provider = self.canvas.associative_sketches_provider
        if attachment is None or provider is None:
            return False
        sketch = next((item for item in provider() if item.sketch_id == attachment.sketch_id), None)
        if sketch is None:
            return True
        return (
            resolve_attachment_local(attachment, {item.entity_id: item for item in sketch.entities})
            is None
        )

    def _datum_label_layout(self, datum: DatumIdentifier) -> TextLayout:
        return layout_text(
            DrawingText("00000000000000000000000000000000", datum.label, (0, 0)),
            self._annotation_text_style(datum) or TextStyle(),
            self.manager,
        )

    def _datum_font_warning(self, datum: DatumIdentifier) -> str:
        style = self._annotation_text_style(datum)
        if style is None:
            return f"文字样式 {datum.text_style_id} 不可用，使用默认样式显示。"
        replacement = self.manager.substitution(style)
        missing = self._datum_label_layout(datum).missing_glyphs
        message = (
            f"字体 {style.font_family or style.font_file} 不可用，使用 {replacement} 显示。"
            if replacement
            else ""
        )
        return message + (f"缺少字符：{missing}。" if missing else "")

    def _datum_box_size(self, datum: DatumIdentifier, label: TextLayout) -> tuple[float, float]:
        style = self._annotation_text_style(datum) or TextStyle()
        return datum_box_size(datum, label, style)

    def datum_screen_bounds(
        self, datum: DatumIdentifier, label: TextLayout | None = None
    ) -> QRectF:
        label = label if label is not None else self._datum_label_layout(datum)
        origin = self.canvas.local_to_screen_precise(datum.position_mm)
        width, height = self._datum_box_size(datum, label)
        scale = self.canvas.view_scale
        return QRectF(
            origin.x(),
            origin.y(),
            width * scale,
            height * scale,
        )

    def datum_screen_leader(
        self, datum: DatumIdentifier, rect: QRectF | None = None
    ) -> tuple[tuple[QPointF, QPointF] | None, QPolygonF]:
        points, triangle = self.datum_screen_path(datum, rect)
        return ((points[0], points[-1]) if points else None), triangle

    def circular_datum_screen_geometry(
        self, datum: DatumIdentifier
    ) -> tuple[tuple[QPointF, QPointF], tuple[QPointF, QPointF]]:
        rect = self.datum_screen_bounds(datum)
        scale = self.canvas.view_scale
        radius = rect.width() / (2 * scale)
        center = (datum.position_mm[0] + radius, datum.position_mm[1] - radius)
        _, connector, bar = circular_datum_geometry(
            center, datum.target_mm, radius, radius * 1.6, bar_direction=datum.bar_direction
        )
        return (
            (
                self.canvas.local_to_screen_precise(connector[0]),
                self.canvas.local_to_screen_precise(connector[1]),
            ),
            (
                self.canvas.local_to_screen_precise(bar[0]),
                self.canvas.local_to_screen_precise(bar[1]),
            ),
        )

    def datum_screen_path(
        self, datum: DatumIdentifier, rect: QRectF | None = None, *, style: TextStyle | None = None
    ) -> tuple[tuple[QPointF, ...], QPolygonF]:
        if not datum.leader_visible:
            return (), QPolygonF()
        if datum.symbol_style == "circle":
            try:
                connector, _ = self.circular_datum_screen_geometry(datum)
            except ValueError:
                return (), QPolygonF()
            return connector, QPolygonF()
        target_world = datum.target_mm
        if datum.surface_indication is not None:
            _, _, target_world = surface_indication_geometry(target_world, datum.surface_indication)
        if datum.layout_mode == "shared":
            style = style or self._annotation_text_style(datum) or TextStyle()
            width, height = datum.box_size_mm or datum_box_dimensions(datum.label, style)
            target = (
                target_world[0] - datum.position_mm[0],
                target_world[1] - datum.position_mm[1],
            )
            world_path = datum_leader_path((0, 0, width, -height), target, datum.leader_offsets)
            if not world_path:
                return (), QPolygonF()
            triangle = datum_triangle(
                world_path[-2],
                world_path[-1],
                min(
                    (datum.surface_indication.arrow_size_mm if datum.surface_indication else None)
                    or 2.5 * style.height_mm / 3.5,
                    math.dist(*world_path[-2:]),
                ),
            )

            def to_screen(point: tuple[float, float]) -> QPointF:
                return self.canvas.local_to_screen_precise(
                    (datum.position_mm[0] + point[0], datum.position_mm[1] + point[1])
                )

            return tuple(to_screen(point) for point in world_path), QPolygonF(
                [to_screen(point) for point in triangle] if datum.arrow_style != "none" else []
            )
        rect = rect if rect is not None else self.datum_screen_bounds(datum)
        target = self.canvas.local_to_screen_precise(target_world)
        vertices = tuple(
            self.canvas.local_to_screen_precise(
                (datum.position_mm[0] + x, datum.position_mm[1] + y)
            )
            for x, y in datum.leader_offsets
        )
        path = datum_leader_path(
            (rect.left(), rect.top(), rect.right(), rect.bottom()),
            (target.x(), target.y()),
            tuple((point.x(), point.y()) for point in vertices),
        )
        if not path:
            return (), QPolygonF()
        triangle = datum_triangle(
            path[-2],
            path[-1],
            min(
                (
                    (datum.surface_indication.arrow_size_mm if datum.surface_indication else None)
                    or 2.5
                )
                * self.canvas.view_scale,
                math.dist(*path[-2:]),
            ),
        )
        return tuple(QPointF(*point) for point in path), QPolygonF(
            [QPointF(*point) for point in triangle] if datum.arrow_style != "none" else []
        )

    def select_box(self, first: QPointF, second: QPointF, modifiers: Qt.KeyboardModifier) -> bool:
        """Apply window/crossing selection to visible, unlocked annotation geometry."""
        selection = QRectF(first, second).normalized()
        crossing = second.x() < first.x()
        hits: list[tuple[str, str]] = []

        def accepts(path: QPainterPath, filled: list[QPainterPath]) -> bool:
            if not crossing:
                return selection.contains(path.boundingRect())
            stroke = QPainterPathStroker()
            stroke.setWidth(5)
            return stroke.createStroke(path).intersects(selection) or any(
                shape.intersects(selection) for shape in filled
            )

        def add_arrow(
            path: QPainterPath, filled: list[QPainterPath], arrow: QPolygonF, *, solid: bool = True
        ) -> None:
            if arrow:
                shape = QPainterPath()
                shape.addPolygon(arrow)
                shape.closeSubpath()
                path.addPath(shape)
                if solid:
                    filled.append(shape)

        def add_surface(
            path: QPainterPath,
            filled: list[QPainterPath],
            target: tuple[float, float],
            indication: SurfaceIndication | None,
        ) -> None:
            path.addPath(self._surface_indication_path(target, indication))
            if indication is not None:
                _, leader, _ = self.surface_indication_screen_geometry(target, indication)
                arrow = self._surface_screen_arrow(leader, indication)
                if arrow:
                    shape = QPainterPath()
                    shape.addPolygon(arrow)
                    shape.closeSubpath()
                    filled.append(shape)

        for source in self.frames:
            frame = self.display_frame(source)
            if frame is None:
                continue
            layer = self.canvas.layer_table.get(frame.layer_name)
            path = QPainterPath()
            path.addRect(self._layout(frame).bounds)
            path = self._transform(frame).map(path)
            filled = [QPainterPath(path)]
            points = self.frame_screen_leader(frame)
            if points:
                path.moveTo(points[0])
                for point in points[1:]:
                    path.lineTo(point)
            add_arrow(path, filled, self._frame_screen_arrow(frame, points))
            extension = self.surface_screen_path(frame.leader_attachment)
            if extension:
                path.moveTo(extension[0])
                for point in extension[1:]:
                    path.lineTo(point)
            if frame.leader_target_mm is not None:
                add_surface(path, filled, frame.leader_target_mm, frame.surface_indication)
            if layer.displayed and not layer.locked and accepts(path, filled):
                hits.append((frame.frame_id, "frame"))
        for source in self.datums:
            datum = self.display_datum(source)
            if datum is None:
                continue
            layer = self.canvas.layer_table.get(datum.layer_name)
            if not layer.displayed or layer.locked:
                continue
            path = QPainterPath()
            rect = self.datum_screen_bounds(datum)
            if datum.symbol_style == "circle":
                path.addEllipse(rect)
                try:
                    _, bar = self.circular_datum_screen_geometry(datum)
                    path.moveTo(bar[0])
                    path.lineTo(bar[1])
                except ValueError:
                    pass
            else:
                path.addRect(rect)
            filled = [QPainterPath(path)]
            points, triangle = self.datum_screen_path(datum, rect)
            if points:
                path.moveTo(points[0])
                for point in points[1:]:
                    path.lineTo(point)
            add_arrow(path, filled, triangle, solid=datum.arrow_style == "filled")
            extension = self.surface_screen_path(datum.attachment)
            if extension:
                path.moveTo(extension[0])
                for point in extension[1:]:
                    path.lineTo(point)
            add_surface(path, filled, datum.target_mm, datum.surface_indication)
            if accepts(path, filled):
                hits.append((datum.datum_id, "datum"))
        for source in self.reference_dimensions:
            dimension = self.display_reference(source)
            if dimension is None:
                continue
            layer = self.canvas.layer_table.get(dimension.layer_name)
            if not layer.displayed or layer.locked:
                continue
            layout = self.reference_layout(source)
            assert layout is not None
            path = QPainterPath()
            if layout.label_polygon is None:
                path.addRect(layout.label)
            else:
                path.addPolygon(layout.label_polygon)
            filled = [QPainterPath(path)]
            for start, end in layout.lines:
                path.moveTo(start)
                path.lineTo(end)
            for arrow in layout.arrows:
                add_arrow(path, filled, QPolygonF(arrow))
            if accepts(path, filled):
                hits.append((dimension.dimension_id, "reference"))

        counts: dict[str, int] = {}
        for identity in (item.frame_id for item in self.frames):
            counts[identity] = counts.get(identity, 0) + 1
        for identity in (item.datum_id for item in self.datums):
            counts[identity] = counts.get(identity, 0) + 1
        for identity in (item.dimension_id for item in self.reference_dimensions):
            counts[identity] = counts.get(identity, 0) + 1
        selected = {identity for identity, _ in hits if counts[identity] == 1}
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected_ids = self.selection_original - selected
        elif modifiers & Qt.KeyboardModifier.ControlModifier or self.canvas.transform_selecting:
            self.selected_ids = self.selection_original | selected
        else:
            self.selected_ids = selected
        self._restore_selected_kind()
        return any(counts[identity] != 1 for identity, _ in hits)

    def restore_box_selection(self) -> None:
        self.selected_ids = set(self.selection_original)
        self._restore_selected_kind()

    def restore_collection_selection(self, identities: set[str]) -> None:
        """Restore a validated annotation selection from a collection checkpoint."""
        self.selected_ids = set(identities)
        self._restore_selected_kind()

    def _restore_selected_kind(self) -> None:
        self.selected_id = next(iter(sorted(self.selected_ids)), None)
        if self.selected_id is not None:
            if any(frame.frame_id == self.selected_id for frame in self.frames):
                self.selected_kind = "frame"
            elif any(datum.datum_id == self.selected_id for datum in self.datums):
                self.selected_kind = "datum"
            else:
                self.selected_kind = "reference"

    def draw_clipboard_preview(
        self,
        painter: QPainter,
        item: DetachedDimension | FeatureControlFrame | DatumIdentifier,
        source_layers: SketchLayerTable,
        styles: TextStyleTable,
        *,
        ordinate_bent: bool | None = None,
    ) -> None:
        """Draw a clipboard annotation without installing it in the document."""
        try:
            layer = self.canvas.layer_table.get(item.layer_name)
        except KeyError:
            layer = source_layers.get(item.layer_name)
        if not layer.displayed:
            return
        painter.save()
        painter.setPen(self.canvas.text_color(layer))
        if isinstance(item, DetachedDimension):
            layout_reference_dimension(item, self.canvas, ordinate_bent=ordinate_bent).draw(painter)
        elif isinstance(item, FeatureControlFrame):
            style = (
                styles.get(item.text_style_id) if item.text_style_id is not None else TextStyle()
            )
            layout = layout_frame(item, self.manager, style)
            painter.save()
            painter.setWorldTransform(self._transform(item))
            layout.draw(painter)
            painter.restore()
            if item.leader_target_mm is not None and item.surface_indication is not None:
                self._draw_surface_indication(
                    painter, item.leader_target_mm, item.surface_indication
                )
            points = self.frame_screen_leader(item, bounds=layout.bounds)
            if len(points) >= 2:
                painter.drawPolyline(QPolygonF(points))
                triangle = self._frame_screen_arrow(item, points)
                if triangle:
                    painter.setBrush(painter.pen().color())
                    painter.drawPolygon(triangle)
        else:
            style = (
                styles.get(item.text_style_id) if item.text_style_id is not None else TextStyle()
            )
            label = layout_text(
                DrawingText("00000000000000000000000000000000", item.label, (0, 0)),
                style,
                self.manager,
            )
            width, height = datum_box_size(item, label, style)
            origin = self.canvas.local_to_screen_precise(item.position_mm)
            scale = self.canvas.view_scale
            rect = QRectF(origin.x(), origin.y(), width * scale, height * scale)
            if item.surface_indication is not None:
                self._draw_surface_indication(painter, item.target_mm, item.surface_indication)
            points, triangle = self.datum_screen_path(item, rect, style=style)
            if len(points) >= 2:
                painter.drawPolyline(QPolygonF(points))
            if triangle:
                painter.setBrush(
                    painter.pen().color() if item.arrow_style == "filled" else Qt.BrushStyle.NoBrush
                )
                painter.drawPolygon(triangle)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if item.symbol_style == "circle":
                painter.drawEllipse(rect)
                try:
                    _, bar = self.circular_datum_screen_geometry(item)
                    painter.drawLine(bar[0], bar[1])
                except ValueError:
                    pass
            else:
                painter.drawRect(rect)
            painter.translate(rect.center())
            painter.scale(scale, scale)
            if (
                item.layout_mode == "shared"
                and label.bounds.width() > 0
                and label.bounds.height() > 0
            ):
                padding = style.height_mm / 3.5
                fit = min(
                    1.0,
                    max(0.0, rect.width() / scale - 1.6 * padding) / label.bounds.width(),
                    max(0.0, rect.height() / scale - 0.8 * padding) / label.bounds.height(),
                )
                painter.scale(fit, fit)
            painter.translate(-label.bounds.center())
            label.draw(painter)
        painter.restore()

    def draw(
        self,
        painter: QPainter,
        effective_frames: frozenset[str] = frozenset(),
        effective_datums: frozenset[str] = frozenset(),
        effective_references: frozenset[str] = frozenset(),
    ) -> None:
        surface_preview = self.surface_edit_preview
        if (
            self.mechanical_datum_active
            and self.mechanical_datum_target is None
            and self.datum_target_preview is not None
        ):
            painter.save()
            pen = QPen(
                self.canvas.text_color(self.canvas.layer_table.get(self.canvas.active_layer_name))
            )
            pen.setWidthF(0.5 * self.canvas.view_scale)
            painter.setPen(pen)
            painter.drawLine(*self.datum_target_preview)
            painter.restore()
        for source in self.reference_dimensions:
            dimension = self.display_reference(source)
            if dimension is None:
                continue
            layer = self.canvas.layer_table.get(dimension.layer_name)
            if not layer.displayed:
                continue
            painter.save()
            painter.setPen(self.canvas.text_color(layer))
            layout = self.reference_layout(source)
            assert layout is not None
            layout.draw(painter)
            if (
                dimension.dimension_id in self.selected_ids
                or dimension.dimension_id in effective_references
            ):
                painter.setPen(QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine))
                painter.drawRect(layout.label)
            painter.restore()
        if self.mechanical_frame_target is not None and self.mechanical_frame_cursor is not None:
            painter.save()
            painter.setPen(QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine))
            target = self.mechanical_frame_target
            indication = self._new_surface_indication(
                target, self.mechanical_frame_cursor, auto_normal=self.surface_auto_normal
            )
            with suppress(ValueError):
                if indication is not None:
                    projected_indication = project_surface(
                        indication, WorkPlaneFrame.xy(), self.canvas.drawing_view_frame
                    )
                    assert projected_indication is not None
                    self._draw_surface_indication(
                        painter, self._view_point(target), projected_indication
                    )
                    _, _, target = surface_indication_geometry(target, indication)
                path = (
                    target,
                    *self.mechanical_frame_preview_vertices,
                    self.mechanical_frame_cursor,
                )
                painter.drawPolyline(
                    QPolygonF(
                        [
                            QPointF(self.canvas.local_to_screen(self._view_point(point)))
                            for point in path
                        ]
                    )
                )
            painter.restore()
        for frame in self.frames:
            if isinstance(surface_preview, FeatureControlFrame) and frame == self.surface_edit:
                frame = surface_preview
            if (
                self.frame_grip is not None
                and frame == self.frame_grip[0]
                and self.frame_grip_cursor is not None
                and (
                    self.grip_view_frame is None
                    or self.grip_view_frame == self.canvas.drawing_view_frame
                )
            ):
                with suppress(ValueError):
                    frame = self._frame_with_grip(
                        frame, self.frame_grip[1], self._drawing_point(self.frame_grip_cursor)
                    )
            frame = self.display_frame(frame)
            if frame is None:
                continue
            layer = self.canvas.layer_table.get(frame.layer_name)
            if not layer.displayed:
                continue
            painter.save()
            painter.setWorldTransform(self._transform(frame))
            painter.setPen(self.canvas.text_color(layer))
            self._layout(frame).draw(painter)
            if frame.frame_id in self.selected_ids or frame.frame_id in effective_frames:
                pen = QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawRect(self._layout(frame).bounds)
            painter.restore()
            if frame.frame_id in self.selected_ids:
                painter.save()
                painter.setPen(QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine))
                for _, world in self._frame_grips(frame):
                    grip = self.canvas.local_to_screen(world)
                    painter.drawRect(QRectF(grip.x() - 3, grip.y() - 3, 6, 6))
                painter.restore()
            points = self.frame_screen_leader(frame)
            if frame.leader_target_mm is not None and frame.surface_indication is not None:
                painter.save()
                painter.setPen(self.canvas.text_color(layer))
                self._draw_surface_indication(
                    painter, frame.leader_target_mm, frame.surface_indication
                )
                painter.restore()
            extension = self.surface_screen_path(frame.leader_attachment)
            if len(extension) >= 2:
                painter.save()
                painter.setPen(self.canvas.text_color(layer))
                painter.drawPolyline(QPolygonF(extension))
                painter.restore()
            if len(points) >= 2:
                painter.save()
                painter.setPen(self.canvas.text_color(layer))
                painter.drawPolyline(QPolygonF(points))
                triangle = self._frame_screen_arrow(frame, points)
                if triangle:
                    painter.setBrush(painter.pen().color())
                    painter.drawPolygon(triangle)
                painter.restore()
            if self._unresolved_datum_labels(frame):
                painter.save()
                painter.setPen(QColor("#c46a00"))
                painter.drawText(self.screen_bounds(frame).topRight() + QPointF(4, 0), "基准未关联")
                painter.restore()
            if self._frame_attachment_lost(frame):
                painter.save()
                painter.setPen(QColor("#c46a00"))
                painter.drawText(
                    self.screen_bounds(frame).bottomRight() + QPointF(4, 12), "引线失关联"
                )
                painter.restore()
        preview = self.mechanical_datum_preview
        transform_preview = self.datum_transform_preview
        copy_preview = transform_preview if self.transform_action == "copy" else None
        for datum in (
            *self.datums,
            *((preview,) if preview is not None else ()),
            *((copy_preview,) if copy_preview is not None else ()),
        ):
            is_preview = datum is preview or datum is copy_preview
            if (
                (self.transform_action == "move" or self.datum_drag is not None)
                and transform_preview is not None
                and datum.datum_id == transform_preview.datum_id
            ):
                datum = transform_preview
                is_preview = True
            if isinstance(surface_preview, DatumIdentifier) and datum == self.surface_edit:
                datum = surface_preview
            if (
                self.datum_grip is not None
                and datum == self.datum_grip[0]
                and self.datum_grip_cursor is not None
                and (
                    self.grip_view_frame is None
                    or self.grip_view_frame == self.canvas.drawing_view_frame
                )
            ):
                with suppress(ValueError):
                    datum = self._datum_with_grip(
                        datum, self.datum_grip[1], self._drawing_point(self.datum_grip_cursor)
                    )
            projected = self.display_datum(datum)
            if projected is None:
                continue
            datum = projected
            layer = self.canvas.layer_table.get(datum.layer_name)
            if not layer.displayed:
                continue
            painter.save()
            origin = self.canvas.local_to_screen(datum.position_mm)
            painter.setPen(self.canvas.text_color(layer))
            if is_preview:
                painter.setPen(QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine))
            unresolved = (
                (datum.attachment is not None or datum.annotation_attachment is not None)
                and self.attachment_resolved is not None
                and not self.attachment_resolved(datum.datum_id)
            )
            if unresolved:
                painter.setPen(QPen(QColor("#c46a00"), 1, Qt.PenStyle.DashLine))
            scale = self.canvas.view_scale
            label = self._datum_label_layout(datum)
            rect = self.datum_screen_bounds(datum, label)
            points, triangle = self.datum_screen_path(datum, rect)
            if datum.surface_indication is not None:
                painter.save()
                self._draw_surface_indication(painter, datum.target_mm, datum.surface_indication)
                painter.restore()
            extension = self.surface_screen_path(datum.attachment)
            if len(extension) >= 2:
                painter.drawPolyline(QPolygonF(extension))
            if len(points) >= 2:
                painter.drawPolyline(QPolygonF(points))
            if triangle:
                painter.setBrush(
                    painter.pen().color()
                    if datum.arrow_style == "filled"
                    else Qt.BrushStyle.NoBrush
                )
                painter.drawPolygon(triangle)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if unresolved:
                painter.drawText(origin.x() + 5, origin.y() - 5, "失关联")
            if datum.symbol_style == "circle":
                painter.drawEllipse(rect)
                try:
                    _, bar = self.circular_datum_screen_geometry(datum)
                    painter.save()
                    pen = QPen(painter.pen())
                    pen.setWidthF(0.5 * scale)
                    painter.setPen(pen)
                    painter.drawLine(bar[0], bar[1])
                    painter.restore()
                except ValueError:
                    pass
            else:
                painter.drawRect(rect)
            if not is_preview and (
                datum.datum_id in self.selected_ids or datum.datum_id in effective_datums
            ):
                painter.save()
                painter.setPen(QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine))
                painter.drawRect(rect.adjusted(-2, -2, 2, 2))
                if datum.datum_id in self.selected_ids:
                    for _, world in self._datum_grips(datum):
                        grip = self.canvas.local_to_screen(world)
                        painter.drawRect(QRectF(grip.x() - 3, grip.y() - 3, 6, 6))
                painter.restore()
            painter.translate(rect.center())
            painter.scale(scale, scale)
            if (
                datum.layout_mode == "shared"
                and label.bounds.width() > 0
                and label.bounds.height() > 0
            ):
                style = self._annotation_text_style(datum) or TextStyle()
                padding = style.height_mm / 3.5
                fit = min(
                    1.0,
                    max(0.0, rect.width() / scale - 1.6 * padding) / label.bounds.width(),
                    max(0.0, rect.height() / scale - 0.8 * padding) / label.bounds.height(),
                )
                painter.scale(fit, fit)
            painter.translate(-label.bounds.center())
            label.draw(painter)
            painter.restore()

    def _pick_target(
        self,
        point: tuple[float, float],
        *,
        exclude_frame: str | None = None,
        include_draft: bool = False,
    ) -> tuple[DatumAttachment | None, AnnotationAttachment | None, tuple[float, float] | None]:
        try:
            view_point = self._view_point(point)
        except ValueError:
            self._message("当前工作平面与图纸不共面，无法拾取标注。")
            return None, None, None
        candidates: list[tuple[AnnotationAttachment, tuple[float, float]]] = []
        radius = 7.0 / self.canvas.view_scale
        for frame in self.frames:
            layer = self.canvas.layer_table.get(frame.layer_name)
            if frame.frame_id == exclude_frame or not layer.displayed or layer.locked:
                continue
            theta = math.radians(frame.rotation_deg)
            cosine, sine = math.cos(theta), math.sin(theta)
            dx, dy = point[0] - frame.position_mm[0], point[1] - frame.position_mm[1]
            x, y = cosine * dx + sine * dy, sine * dx - cosine * dy
            rect = self._layout(frame).bounds
            if not rect.adjusted(-radius, -radius, radius, radius).contains(QPointF(x, y)):
                continue
            x = min(rect.right(), max(rect.left(), x))
            y = min(rect.bottom(), max(rect.top(), y))
            distances = (
                abs(x - rect.left()),
                abs(x - rect.right()),
                abs(y - rect.top()),
                abs(y - rect.bottom()),
            )
            edge = min(range(4), key=lambda index: distances[index])
            if edge == 0:
                x = rect.left()
            elif edge == 1:
                x = rect.right()
            elif edge == 2:
                y = rect.top()
            else:
                y = rect.bottom()
            offset = (x, -y)
            world = (
                frame.position_mm[0] + cosine * offset[0] - sine * offset[1],
                frame.position_mm[1] + sine * offset[0] + cosine * offset[1],
            )
            candidates.append((AnnotationAttachment("frame", frame.frame_id, offset), world))
        screen = self.canvas.local_to_screen_precise(view_point)
        for source in self.reference_dimensions:
            dimension = self.display_reference(source)
            if dimension is None:
                continue
            layer = self.canvas.layer_table.get(dimension.layer_name)
            if (
                layer.displayed
                and not layer.locked
                and (layout := self.reference_layout(source)) is not None
                and layout.hit(screen)
            ):
                offset = (
                    point[0] - source.location_mm[0],
                    point[1] - source.location_mm[1],
                )
                candidates.append(
                    (
                        AnnotationAttachment("reference_dimension", dimension.dimension_id, offset),
                        point,
                    )
                )
        sketch_hit = self.parent.dimensions.annotation_dimension_at(view_point)
        if sketch_hit is not None:
            sketch, dimension, part = sketch_hit
            anchor = (
                dimension.text_position_mm
                if part == "text" and dimension.text_position_mm is not None
                else dimension.position_mm
            )
            if anchor is None:
                self._message("该尺寸没有固定标注位置，请先放置或移动尺寸后再附着。")
                return None, None, None
            if (
                abs(abs(sketch.frame.normal[2]) - 1.0) > 1e-9
                or abs(sketch.frame.origin_mm[2]) > 1e-7
            ):
                self._message("只支持附着到当前 XY 平面的尺寸。")
                return None, None, None
            dx, dy = point[0] - sketch.frame.origin_mm[0], point[1] - sketch.frame.origin_mm[1]
            local = (
                dx * sketch.frame.u_axis[0] + dy * sketch.frame.u_axis[1],
                dx * sketch.frame.v_axis[0] + dy * sketch.frame.v_axis[1],
            )
            offset = (local[0] - anchor[0], local[1] - anchor[1])
            candidates.append(
                (
                    AnnotationAttachment(
                        "sketch_dimension",
                        dimension.constraint_id,
                        offset,
                        sketch.sketch_id,
                        anchor="text" if part == "text" else "position",
                    ),
                    point,
                )
            )
        if candidates:
            if len(candidates) == 1:
                return None, candidates[0][0], candidates[0][1]
            self._message("附着目标不唯一，请选择其他位置。")
            return None, None, None
        geometry, hit = self._pick_attachment(point)
        if geometry is None and include_draft:
            _, hit = self._pick_attachment(point, sketches=self.parent.dimension_sources())
        return geometry, None, hit

    def _pick_attachment(
        self, point: tuple[float, float], *, sketches: tuple[Sketch, ...] | None = None
    ) -> tuple[DatumAttachment | None, tuple[float, float]]:
        if sketches is None:
            provider = self.canvas.associative_sketches_provider
            if provider is None:
                return None, point
            sketches = provider()
        candidates: list[tuple[DatumAttachment, tuple[float, float]]] = []
        radius = 7.0 / self.canvas.view_scale
        for sketch in sketches:
            frame = sketch.frame
            if abs(abs(frame.normal[2]) - 1.0) > 1e-9 or abs(frame.origin_mm[2]) > 1e-7:
                continue
            for entity in sketch.entities:
                if not self.canvas.layer_table.get(entity.layer_name).displayed:
                    continue
                for reference, local in self.canvas.entity_point_references(entity):
                    world = (
                        frame.origin_mm[0]
                        + local[0] * frame.u_axis[0]
                        + local[1] * frame.v_axis[0],
                        frame.origin_mm[1]
                        + local[0] * frame.u_axis[1]
                        + local[1] * frame.v_axis[1],
                    )
                    if math.dist(point, world) <= radius:
                        candidates.append((DatumAttachment(sketch.sketch_id, reference), world))
        if candidates:
            return candidates[0] if len(candidates) == 1 else (None, point)
        for sketch in sketches:
            frame = sketch.frame
            if abs(abs(frame.normal[2]) - 1.0) > 1e-9 or abs(frame.origin_mm[2]) > 1e-7:
                continue
            delta = (point[0] - frame.origin_mm[0], point[1] - frame.origin_mm[1])
            local = (
                delta[0] * frame.u_axis[0] + delta[1] * frame.u_axis[1],
                delta[0] * frame.v_axis[0] + delta[1] * frame.v_axis[1],
            )
            for entity in sketch.entities:
                if not self.canvas.layer_table.get(entity.layer_name).displayed:
                    continue
                if isinstance(entity, EllipseEntity):
                    for parameter, hit in _ellipse_hits(entity, local, radius):
                        world = (
                            frame.origin_mm[0]
                            + hit[0] * frame.u_axis[0]
                            + hit[1] * frame.v_axis[0],
                            frame.origin_mm[1]
                            + hit[0] * frame.u_axis[1]
                            + hit[1] * frame.v_axis[1],
                        )
                        candidates.append(
                            (
                                DatumAttachment(
                                    sketch.sketch_id,
                                    SketchGeometryReference(entity.entity_id, "geometry"),
                                    parameter,
                                    curve_kind="ellipse",
                                ),
                                world,
                            )
                        )
                    continue
                if isinstance(entity, SplineEntity):
                    for parameter, hit in _spline_hits(entity, local, radius):
                        world = (
                            frame.origin_mm[0]
                            + hit[0] * frame.u_axis[0]
                            + hit[1] * frame.v_axis[0],
                            frame.origin_mm[1]
                            + hit[0] * frame.u_axis[1]
                            + hit[1] * frame.v_axis[1],
                        )
                        candidates.append(
                            (
                                DatumAttachment(
                                    sketch.sketch_id,
                                    SketchGeometryReference(entity.entity_id, "geometry"),
                                    parameter,
                                    curve_kind="spline",
                                    control_count=len(entity.control_points_mm),
                                ),
                                world,
                            )
                        )
                    continue
                if isinstance(entity, PolylineEntity):
                    count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                    shapes = tuple(
                        (segment, SketchGeometryReference(entity.entity_id, "segment", index))
                        for index, segment in enumerate(
                            polyline_curve_segments(
                                entity.points_mm,
                                entity.bulges or (0.0,) * count,
                                entity.closed,
                                entity.entity_id,
                            )
                        )
                    )
                elif isinstance(entity, RectangleEntity):
                    x1, y1 = entity.first_corner_mm
                    x2, y2 = entity.opposite_corner_mm
                    corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                    shapes = tuple(
                        (
                            LineEntity(entity.entity_id, corners[index], corners[(index + 1) % 4]),
                            SketchGeometryReference(entity.entity_id, "segment", index),
                        )
                        for index in range(4)
                    )
                elif isinstance(entity, LineEntity | CircleEntity | ArcEntity):
                    shapes = ((entity, SketchGeometryReference(entity.entity_id, "geometry")),)
                else:
                    continue
                for shape, reference in shapes:
                    if isinstance(shape, LineEntity):
                        dx, dy = (
                            shape.end_mm[0] - shape.start_mm[0],
                            shape.end_mm[1] - shape.start_mm[1],
                        )
                        length2 = dx * dx + dy * dy
                        if length2 < 1e-18:
                            continue
                        parameter = max(
                            0.0,
                            min(
                                1.0,
                                (
                                    (local[0] - shape.start_mm[0]) * dx
                                    + (local[1] - shape.start_mm[1]) * dy
                                )
                                / length2,
                            ),
                        )
                        hit = (
                            shape.start_mm[0] + parameter * dx,
                            shape.start_mm[1] + parameter * dy,
                        )
                    else:
                        dx, dy = local[0] - shape.center_mm[0], local[1] - shape.center_mm[1]
                        if math.hypot(dx, dy) < 1e-12:
                            continue
                        angle = math.degrees(math.atan2(dy, dx)) % 360
                        if isinstance(shape, CircleEntity):
                            parameter = angle / 360
                        else:
                            delta_angle = (
                                (angle - shape.start_angle_deg) % 360
                                if shape.sweep_angle_deg > 0
                                else (shape.start_angle_deg - angle) % 360
                            )
                            if delta_angle > abs(shape.sweep_angle_deg) + 1e-9:
                                continue
                            parameter = min(1.0, delta_angle / abs(shape.sweep_angle_deg))
                        hit = (
                            shape.center_mm[0] + shape.radius_mm * math.cos(math.radians(angle)),
                            shape.center_mm[1] + shape.radius_mm * math.sin(math.radians(angle)),
                        )
                    if math.dist(local, hit) <= radius:
                        world = (
                            frame.origin_mm[0]
                            + hit[0] * frame.u_axis[0]
                            + hit[1] * frame.v_axis[0],
                            frame.origin_mm[1]
                            + hit[0] * frame.u_axis[1]
                            + hit[1] * frame.v_axis[1],
                        )
                        candidates.append(
                            (
                                DatumAttachment(
                                    sketch.sketch_id,
                                    reference,
                                    parameter,
                                    (
                                        len(entity.points_mm)
                                        if entity.closed
                                        else len(entity.points_mm) - 1
                                    )
                                    if isinstance(entity, PolylineEntity)
                                    else 4
                                    if isinstance(entity, RectangleEntity)
                                    else None,
                                    "rectangle" if isinstance(entity, RectangleEntity) else None,
                                ),
                                world,
                            )
                        )

        return candidates[0] if len(candidates) == 1 else (None, point)

    def _pick_surface_extension(
        self, point: tuple[float, float], *, original: DatumAttachment | None = None
    ) -> tuple[DatumAttachment | None, tuple[float, float]]:
        provider = self.canvas.associative_sketches_provider
        if provider is None:
            self._message("当前图纸无法拾取表面延伸。")
            return None, point
        styles = self.canvas.drawing_dimension_styles
        gap = styles.current.extline_offset if styles is not None else 0.0
        overshoot = styles.current.extline_extension if styles is not None else 0.0
        if original is not None and original.surface_extension is not None:
            gap = original.surface_extension.offset_mm
            overshoot = original.surface_extension.overshoot_mm
        radius = 7.0 / self.canvas.view_scale
        candidates: list[tuple[DatumAttachment, tuple[float, float]]] = []
        for sketch in provider():
            if original is not None and sketch.sketch_id != original.sketch_id:
                continue
            frame = sketch.frame
            if abs(abs(frame.normal[2]) - 1) > 1e-9 or abs(frame.origin_mm[2]) > 1e-7:
                continue
            delta = (point[0] - frame.origin_mm[0], point[1] - frame.origin_mm[1])
            local = (
                delta[0] * frame.u_axis[0] + delta[1] * frame.u_axis[1],
                delta[0] * frame.v_axis[0] + delta[1] * frame.v_axis[1],
            )
            for entity in sketch.entities:
                if original is not None and entity.entity_id != original.reference.entity_id:
                    continue
                layer = self.canvas.layer_table.get(entity.layer_name)
                if (
                    not layer.displayed
                    or layer.locked
                    or not isinstance(entity, LineEntity | ArcEntity)
                ):
                    continue
                side: Literal["start", "end"]
                if isinstance(entity, LineEntity):
                    dx, dy = (
                        entity.end_mm[0] - entity.start_mm[0],
                        entity.end_mm[1] - entity.start_mm[1],
                    )
                    length = math.hypot(dx, dy)
                    projection = (
                        (local[0] - entity.start_mm[0]) * dx + (local[1] - entity.start_mm[1]) * dy
                    ) / length
                    if 0 <= projection <= length:
                        continue
                    side = "start" if projection < 0 else "end"
                    distance = -projection if projection < 0 else projection - length
                else:
                    dx, dy = local[0] - entity.center_mm[0], local[1] - entity.center_mm[1]
                    if math.hypot(dx, dy) < 1e-12:
                        continue
                    angle = math.degrees(math.atan2(dy, dx))
                    sign = math.copysign(1.0, entity.sweep_angle_deg)
                    relative = ((angle - entity.start_angle_deg) * sign) % 360
                    if relative <= abs(entity.sweep_angle_deg):
                        continue
                    before = 360 - relative
                    after = relative - abs(entity.sweep_angle_deg)
                    if math.isclose(before, after, abs_tol=1e-9):
                        continue
                    side = "start" if before < after else "end"
                    distance = math.radians(min(before, after)) * entity.radius_mm
                try:
                    spec = SurfaceExtensionSpec(side, distance, gap, overshoot)
                    geometry = surface_extension_geometry(entity, side, distance, gap, overshoot)
                except ValueError:
                    continue
                if math.dist(local, geometry.target_mm) > radius:
                    continue
                world = frame.local_to_world(geometry.target_mm)
                candidates.append(
                    (
                        DatumAttachment(
                            sketch.sketch_id,
                            SketchGeometryReference(entity.entity_id, "geometry"),
                            0 if side == "start" else 1,
                            surface_extension=spec,
                        ),
                        (world[0], world[1]),
                    )
                )
        if len(candidates) != 1:
            self._message("表面延伸目标不唯一或不可用，请靠近直线或圆弧的延长部分。")
            return None, point
        return candidates[0]

    def _copy_mixed_to_clipboard(self) -> bool:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再复制标注和图元。")
            return False
        text_ids: set[str] = (
            self.canvas.text_tools.selected_ids if self.canvas.text_tools is not None else set()
        )
        texts = (
            tuple(item for item in self.canvas.text_tools.texts if item.text_id in text_ids)
            if self.canvas.text_tools is not None
            else ()
        )
        rasters = tuple(
            item
            for item in self.canvas.drawing_rasters
            if item.image_id in self.canvas.selected_raster_ids
        )
        if len(rasters) > 1000:
            self._message("一次混合复制最多支持 1000 张图片。")
            return False
        if len(texts) != len(text_ids) or len(rasters) != len(self.canvas.selected_raster_ids):
            self._message("所选文字或图片已变化，请重新选择。")
            return False
        provider = self.canvas.associative_sketches_provider
        if provider is None:
            self._message("当前图纸无法复制几何。")
            return False
        selected = set(self.canvas.selected_entity_ids)
        source_sketches = provider()
        source_entities: list[SketchEntity] = []
        owners: dict[str, str] = {}
        for sketch in source_sketches:
            for entity in sketch.entities:
                if entity.entity_id not in selected:
                    continue
                if sketch.frame != WorkPlaneFrame.xy() or entity.entity_id in owners:
                    self._message("所选图元的工作平面或身份不唯一，不能混合复制。")
                    return False
                owners[entity.entity_id] = sketch.sketch_id
                source_entities.append(entity)
        if set(owners) != selected:
            self._message("所选图元已变化，请重新选择。")
            return False
        constraint_counts = Counter(
            item.constraint_id
            for sketch in source_sketches
            for item in sketch.constraints
            if item.constraint_id in self.canvas.selected_constraint_ids
        )
        if any(count != 1 for count in constraint_counts.values()):
            self._message("所选尺寸或约束身份不唯一，不能混合复制。")
            return False
        related = tuple(
            item
            for sketch in source_sketches
            for item in sketch.constraints
            if any(owners.get(ref.entity_id) == sketch.sketch_id for ref in item.references)
        )
        if len({item.constraint_id for item in related}) != len(related):
            self._message("所选尺寸或约束身份不唯一，不能混合复制。")
            return False
        if not self.canvas.selected_constraint_ids.issubset(
            {item.constraint_id for item in related}
        ):
            self._message("所选尺寸或约束须与其全部关联图元一起复制。")
            return False
        if any(not all(ref.entity_id in selected for ref in item.references) for item in related):
            self._message("关联尺寸或约束的全部图元必须同时选中。")
            return False
        names = {item.style_name.casefold() for item in related if item.style_name is not None}
        source_styles = self.canvas.drawing_dimension_styles
        copied_styles: DimensionStyleTable | None = None
        copied_text_styles: TextStyleTable | None = None
        font_ids: set[str] = set()
        if names:
            if source_styles is None:
                self._message("所选尺寸引用的标注样式不可用。")
                return False
            selected_styles = tuple(
                style for style in source_styles.styles if style.name.casefold() in names
            )
            if {style.name.casefold() for style in selected_styles} != names:
                self._message("所选尺寸引用了不存在的标注样式。")
                return False
            copied_styles = DimensionStyleTable(selected_styles, selected_styles[0].name)
            font_ids.update(style.text_style_id for style in selected_styles if style.text_style_id)
        tangencies = (
            self.canvas.associative_tangencies_provider()
            if self.canvas.associative_tangencies_provider
            else ()
        )
        arrays = (
            self.canvas.associative_arrays_provider()
            if self.canvas.associative_arrays_provider
            else ()
        )
        if any(
            relation.first.entity_id in selected or relation.second.entity_id in selected
            for relation in tangencies
        ) or any(
            any(ref.entity_id in selected for ref in array.sources)
            or any(member.target.entity_id in selected for member in array.members)
            or any(
                member.replacement is not None and member.replacement.source.entity_id in selected
                for member in array.members
            )
            or any(
                output.target.entity_id in selected or output.source.entity_id in selected
                for output in array.extra_outputs
            )
            for array in arrays
        ):
            self._message("所选图元包含对象相切或阵列关联；请分别复制，避免丢失关联。")
            return False
        frames = tuple(item for item in self.frames if item.frame_id in self.selected_ids)
        datums = tuple(item for item in self.datums if item.datum_id in self.selected_ids)
        font_ids.update(frame.text_style_id for frame in frames if frame.text_style_id)
        font_ids.update(datum.text_style_id for datum in datums if datum.text_style_id)
        font_ids.update(item.style_id for item in texts)
        if font_ids:
            if self.canvas.text_tools is None:
                self._message("所选标注引用的文字样式不可用。")
                return False
            selected_text_styles = tuple(
                style
                for style in self.canvas.text_tools.styles.styles
                if style.style_id in font_ids
            )
            if {style.style_id for style in selected_text_styles} != font_ids:
                self._message("所选标注引用了不存在的文字样式。")
                return False
            copied_text_styles = TextStyleTable(
                selected_text_styles, selected_text_styles[0].style_id
            )
        references = tuple(
            item for item in self.reference_dimensions if item.dimension_id in self.selected_ids
        )
        if len(frames) + len(datums) + len(references) != len(self.selected_ids):
            self._message("标注选择已变化，请重新选择。")
            return False
        used_layers = (
            {"0"}
            | {
                item.layer_name.casefold()
                for item in (*source_entities, *frames, *datums, *references, *texts, *rasters)
            }
            | {item.layer_name.casefold() for item in related if item.layer_name is not None}
        )
        layers = SketchLayerTable(
            tuple(
                layer
                for layer in self.canvas.layer_table.layers
                if layer.name.casefold() in used_layers
            )
        )
        sketch = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            tuple(source_entities),
            constraints=related,
            layers=layers,
        )
        anchor = (
            datums[0].position_mm
            if datums
            else frames[0].position_mm
            if frames
            else references[0].location_mm
        )
        record = {
            "sketch": sketch.to_state_mapping(),
            "owners": owners,
            "frames": [item.to_mapping() for item in frames],
            "datums": [item.to_mapping() for item in datums],
            "references": [item.to_mapping() for item in references],
            "texts": [item.to_mapping() for item in texts],
            "rasters": [item.to_mapping(version=2) for item in rasters],
            "anchor": list(anchor),
            "styles": copied_styles.to_mapping() if copied_styles is not None else None,
            "text_styles": copied_text_styles.to_mapping()
            if copied_text_styles is not None
            else None,
        }
        payload = json.dumps(
            {
                "format": "mycad-tolerance-annotation",
                "version": 1,
                "source": self._clipboard_source,
                "kind": "mixed",
                "object": record,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) > MAX_MIXED_CLIPBOARD_BYTES:
            self._message("混合剪贴板数据过大。")
            return False
        mime = QMimeData()
        mime.setData(TOLERANCE_CLIPBOARD_MIME, payload)
        QApplication.clipboard().setMimeData(mime)
        self._message("图元与标注已复制；Ctrl+V 粘贴。")
        self.canvas.changed.emit()
        return True

    def copy_frame_to_clipboard(self) -> bool:
        selected: FeatureControlFrame | DatumIdentifier | DetachedDimension | None
        if self.selected_kind == "frame":
            selected = next(
                (item for item in self.frames if item.frame_id == self.selected_id), None
            )
        elif self.selected_kind == "datum":
            selected = next(
                (item for item in self.datums if item.datum_id == self.selected_id), None
            )
        else:
            selected = next(
                (
                    item
                    for item in self.reference_dimensions
                    if item.dimension_id == self.selected_id
                ),
                None,
            )
        if selected is None or self.pending:
            return False
        if (
            len(self.selected_ids) > 1
            or self.canvas.selected_entity_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
            or isinstance(selected, (FeatureControlFrame, DatumIdentifier))
            and selected.text_style_id is not None
        ):
            return self._copy_mixed_to_clipboard()
        payload = json.dumps(
            {
                "format": "mycad-tolerance-annotation",
                "version": 1,
                "source": self._clipboard_source,
                "kind": self.selected_kind,
                "object": selected.to_mapping(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) > 200_000:
            self._message("标注数据过大，无法复制。")
            return False
        mime = QMimeData()
        mime.setData(TOLERANCE_CLIPBOARD_MIME, payload)
        QApplication.clipboard().setMimeData(mime)
        self._message("标注已复制；Ctrl+V 粘贴。")
        self.canvas.changed.emit()
        return True

    def begin_frame_paste(self) -> bool:
        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        if mime is None or not mime.hasFormat(TOLERANCE_CLIPBOARD_MIME):
            return False
        if (
            self.pending
            or not self.canvas.select_committed_entities
            or self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
        ):
            self._message("请先完成当前操作，再粘贴标注。")
            return True
        try:
            raw = bytes(mime.data(TOLERANCE_CLIPBOARD_MIME).data())
            if not raw or len(raw) > MAX_MIXED_CLIPBOARD_BYTES:
                raise ValueError("剪贴板数据无效或过大。")
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("剪贴板格式无效。")
            record = cast("dict[str, object]", value)
            if (
                set(record) != {"format", "version", "source", "kind", "object"}
                or record["format"] != "mycad-tolerance-annotation"
                or type(record["version"]) is not int
                or record["version"] != 1
                or not isinstance(record["source"], str)
                or record["kind"] not in ("frame", "datum", "reference", "mixed")
            ):
                raise ValueError("剪贴板格式无效。")
            preserve = record["source"] == self._clipboard_source
            missing_layer = False
            lost_links = False
            if record["kind"] == "mixed":
                raw_mixed = record["object"]
                if not isinstance(raw_mixed, dict):
                    raise ValueError("混合剪贴板格式无效。")
                mixed = cast("dict[str, object]", raw_mixed)
                if set(mixed) not in (
                    {
                        "sketch",
                        "owners",
                        "frames",
                        "datums",
                        "references",
                        "anchor",
                        "styles",
                    },
                    {
                        "sketch",
                        "owners",
                        "frames",
                        "datums",
                        "references",
                        "anchor",
                        "styles",
                        "text_styles",
                    },
                    {
                        "sketch",
                        "owners",
                        "frames",
                        "datums",
                        "references",
                        "anchor",
                        "styles",
                        "text_styles",
                        "texts",
                        "rasters",
                    },
                ):
                    raise ValueError("混合剪贴板格式无效。")
                sketch = Sketch.from_mapping(mixed["sketch"])
                raw_owners = mixed["owners"]
                if not isinstance(raw_owners, dict) or any(
                    not isinstance(k, str) or not isinstance(v, str)
                    for k, v in cast("dict[object, object]", raw_owners).items()
                ):
                    raise ValueError("图元来源无效。")
                owners = cast("dict[str, str]", raw_owners)
                if (
                    set(owners) != {entity.entity_id for entity in sketch.entities}
                    or any(
                        ref.entity_id not in owners
                        for item in sketch.constraints
                        for ref in item.references
                    )
                    or sketch.frame != WorkPlaneFrame.xy()
                ):
                    raise ValueError("混合剪贴板图元或关联无效。")
                source_styles = (
                    DimensionStyleTable.from_mapping(mixed["styles"])
                    if mixed["styles"] is not None
                    else None
                )
                source_text_styles = (
                    TextStyleTable.from_mapping(mixed["text_styles"])
                    if mixed.get("text_styles") is not None
                    else None
                )
                if source_styles is not None:
                    for style in source_styles.styles:
                        if style.text_style_id is not None:
                            if source_text_styles is None:
                                raise ValueError("混合剪贴板缺少文字样式。")
                            source_text_styles.get(style.text_style_id)
                if any(item.style_name is not None for item in sketch.constraints):
                    if source_styles is None:
                        raise ValueError("混合剪贴板缺少标注样式。")
                    for item in sketch.constraints:
                        if item.style_name is not None:
                            source_styles.get(item.style_name)
                lists = (mixed["frames"], mixed["datums"], mixed["references"])
                if not all(isinstance(items, list) for items in lists):
                    raise ValueError("混合标注数据无效。")
                frames = tuple(
                    FeatureControlFrame.from_mapping(item)
                    for item in cast("list[object]", mixed["frames"])
                )
                for frame in frames:
                    if frame.text_style_id is not None:
                        if source_text_styles is None:
                            raise ValueError("混合剪贴板缺少公差框文字样式。")
                        source_text_styles.get(frame.text_style_id)
                datums = tuple(
                    DatumIdentifier.from_mapping(item)
                    for item in cast("list[object]", mixed["datums"])
                )
                for datum in datums:
                    if datum.text_style_id is not None:
                        if source_text_styles is None:
                            raise ValueError("混合剪贴板缺少基准文字样式。")
                        source_text_styles.get(datum.text_style_id)
                references = tuple(
                    DetachedDimension.from_mapping(item)
                    for item in cast("list[object]", mixed["references"])
                )
                raw_texts, raw_rasters = mixed.get("texts", []), mixed.get("rasters", [])
                if not isinstance(raw_texts, list) or not isinstance(raw_rasters, list):
                    raise ValueError("混合剪贴板文字或图片数据无效。")
                if len(cast("list[object]", raw_rasters)) > 1000:
                    raise ValueError("混合剪贴板图片超过 1000 张。")
                texts = tuple(
                    DrawingText.from_mapping(item) for item in cast("list[object]", raw_texts)
                )
                rasters = tuple(
                    DrawingRaster.from_mapping(item) for item in cast("list[object]", raw_rasters)
                )
                if len({item.text_id for item in texts}) != len(texts) or len(
                    {item.image_id for item in rasters}
                ) != len(rasters):
                    raise ValueError("混合剪贴板文字或图片身份重复。")
                for item in texts:
                    if source_text_styles is None:
                        raise ValueError("混合剪贴板缺少文字样式。")
                    source_text_styles.get(item.style_id)
                if not frames and not datums and not references:
                    raise ValueError("混合剪贴板没有标注。")
                all_ids = (
                    [item.frame_id for item in frames]
                    + [item.datum_id for item in datums]
                    + [item.dimension_id for item in references]
                )
                if len(set(all_ids)) != len(all_ids):
                    raise ValueError("混合剪贴板标注身份重复。")
                lost_external = False
                if preserve:
                    copied_datum_ids = {item.datum_id for item in datums}
                    current_datums = {item.datum_id: item for item in self.datums}
                    current_frames = {item.frame_id: item for item in self.frames}
                    copied_frame_ids = {item.frame_id for item in frames}
                    copied_reference_ids = {item.dimension_id for item in references}
                    copied_dimensions = {
                        (owners[item.references[0].entity_id], item.constraint_id)
                        for item in sketch.constraints
                        if item.references and item.references[0].entity_id in owners
                    }

                    def internal(reference: AnnotationAttachment) -> bool:
                        if reference.kind == "frame":
                            return reference.object_id in copied_frame_ids
                        if reference.kind == "reference_dimension":
                            return reference.object_id in copied_reference_ids
                        return (reference.sketch_id, reference.object_id) in copied_dimensions

                    rebound_frames: list[FeatureControlFrame] = []
                    for frame in frames:
                        annotation = frame.leader_annotation_attachment
                        if annotation is not None and not internal(annotation):
                            current_frame = current_frames.get(frame.frame_id)
                            if (
                                current_frame is None
                                or current_frame.leader_annotation_attachment != annotation
                                or self._frame_attachment_lost(current_frame)
                            ):
                                frame = replace(frame, leader_annotation_attachment=None)
                                lost_external = True
                            else:
                                frame = replace(
                                    frame, leader_target_mm=current_frame.leader_target_mm
                                )
                        attachment = frame.leader_attachment
                        if (
                            attachment is not None
                            and owners.get(attachment.reference.entity_id) != attachment.sketch_id
                        ):
                            current_frame = current_frames.get(frame.frame_id)
                            if (
                                current_frame is None
                                or current_frame.leader_attachment != attachment
                                or self._frame_attachment_lost(current_frame)
                            ):
                                frame = self._drop_frame_geometry_attachment(frame)
                                lost_external = True
                            else:
                                frame = replace(
                                    frame, leader_target_mm=current_frame.leader_target_mm
                                )
                        rebound_rows: list[ToleranceRow] = []
                        for row in frame.rows:
                            rebound_refs: list[DatumReference] = []
                            for ref in row.datums:
                                if (
                                    ref.datum_id is not None
                                    and ref.datum_id not in copied_datum_ids
                                ):
                                    current = current_datums.get(ref.datum_id)
                                    if current is None:
                                        ref = replace(ref, datum_id=None)
                                        lost_external = True
                                    else:
                                        ref = replace(ref, label=current.label)
                                rebound_refs.append(ref)
                            rebound_rows.append(replace(row, datums=tuple(rebound_refs)))
                        rebound_frames.append(replace(frame, rows=tuple(rebound_rows)))
                    frames = tuple(rebound_frames)
                    rebound_datums: list[DatumIdentifier] = []
                    for datum in datums:
                        annotation = datum.annotation_attachment
                        if annotation is not None and not internal(annotation):
                            current = current_datums.get(datum.datum_id)
                            if (
                                current is None
                                or current.annotation_attachment != annotation
                                or self.attachment_resolved is None
                                or not self.attachment_resolved(datum.datum_id)
                            ):
                                datum = replace(datum, annotation_attachment=None)
                                lost_external = True
                            else:
                                datum = replace(datum, target_mm=current.target_mm)
                        attachment = datum.attachment
                        if (
                            attachment is not None
                            and owners.get(attachment.reference.entity_id) != attachment.sketch_id
                        ):
                            current = current_datums.get(datum.datum_id)
                            if (
                                current is None
                                or current.attachment != attachment
                                or self.attachment_resolved is None
                                or not self.attachment_resolved(datum.datum_id)
                            ):
                                datum = self._drop_datum_geometry_attachment(datum)
                                lost_external = True
                            else:
                                datum = replace(datum, target_mm=current.target_mm)
                        rebound_datums.append(datum)
                    datums = tuple(rebound_datums)
                anchor_raw = mixed["anchor"]
                if (
                    not isinstance(anchor_raw, list)
                    or len(cast("list[object]", anchor_raw)) != 2
                    or any(
                        isinstance(x, bool)
                        or not isinstance(x, int | float)
                        or not math.isfinite(x)
                        for x in cast("list[object]", anchor_raw)
                    )
                ):
                    raise ValueError("混合剪贴板基点无效。")
                anchor_values = cast("list[float]", anchor_raw)
                if self.source_revision is None:
                    raise ValueError("无法确认目标图纸状态。")
                target_revision = self.source_revision()
                labels: dict[str, str] = {}
                used = {item.label.casefold() for item in self.datums}
                for datum in datums:
                    label, accepted = QInputDialog.getText(
                        self.parent,
                        "粘贴基准",
                        f"基准 {datum.label} 的新名称（请输入本图中唯一的标识）：",
                        text=next(
                            (
                                chr(value)
                                for value in range(65, 91)
                                if chr(value).casefold() not in used
                            ),
                            "",
                        ),
                    )
                    if not accepted:
                        self._message("已取消混合粘贴。")
                        return True
                    if not label or label.casefold() in used:
                        raise ValueError("基准名称为空或重复。")
                    replace(datum, label=label)
                    labels[datum.datum_id] = label
                    used.add(label.casefold())
                if self.commit_mixed is None:
                    raise ValueError("当前图纸无法提交混合粘贴。")
                self.clipboard_mixed = MixedTolerancePaste(
                    sketch,
                    owners,
                    frames,
                    datums,
                    references,
                    texts,
                    rasters,
                    labels,
                    source_styles,
                    source_text_styles,
                    preserve,
                    (float(anchor_values[0]), float(anchor_values[1])),
                    target_revision,
                )
                self.canvas.set_tool("选择元素")
                self._message(
                    "点击放置混合图元与标注；Esc 取消。"
                    + (" 外部关联将解除。" if not preserve or lost_external else "")
                )
                return True
            if record["kind"] == "frame":
                frame = FeatureControlFrame.from_mapping(record["object"])
                if frame.text_style_id is not None:
                    raise ValueError("剪贴板缺少公差框文字样式定义。")
                known = {datum.datum_id: datum.label for datum in self.datums}
                rows = tuple(
                    replace(
                        row,
                        datums=tuple(
                            ref
                            if preserve
                            and (ref.datum_id is None or known.get(ref.datum_id) == ref.label)
                            else replace(ref, datum_id=None)
                            for ref in row.datums
                        ),
                    )
                    for row in frame.rows
                )
                lost_links = any(
                    before.datum_id is not None and after.datum_id is None
                    for original, copied in zip(frame.rows, rows, strict=True)
                    for before, after in zip(original.datums, copied.datums, strict=True)
                )
                if preserve and frame.leader_attachment is not None:
                    current_frame = next(
                        (item for item in self.frames if item.frame_id == frame.frame_id), None
                    )
                    if (
                        current_frame is None
                        or current_frame.leader_attachment != frame.leader_attachment
                        or self._frame_attachment_lost(current_frame)
                    ):
                        frame = self._drop_frame_geometry_attachment(frame)
                        lost_links = True
                    else:
                        frame = replace(frame, leader_target_mm=current_frame.leader_target_mm)
                if not preserve and frame.leader_attachment is not None:
                    frame = self._drop_frame_geometry_attachment(frame)
                    lost_links = True
                if frame.leader_annotation_attachment is not None:
                    current_frame = next(
                        (item for item in self.frames if item.frame_id == frame.frame_id), None
                    )
                    if (
                        not preserve
                        or current_frame is None
                        or current_frame.leader_annotation_attachment
                        != frame.leader_annotation_attachment
                        or self._frame_attachment_lost(current_frame)
                    ):
                        frame = replace(frame, leader_annotation_attachment=None)
                        lost_links = True
                    else:
                        frame = replace(frame, leader_target_mm=current_frame.leader_target_mm)
                try:
                    self.canvas.layer_table.get(frame.layer_name)
                except KeyError:
                    frame = replace(frame, layer_name=self.canvas.active_layer_name)
                    missing_layer = True
                self.clipboard_frame = replace(frame, frame_id=uuid4().hex, rows=rows)
            elif record["kind"] == "datum":
                datum = DatumIdentifier.from_mapping(record["object"])
                if datum.text_style_id is not None:
                    raise ValueError("剪贴板缺少基准文字样式定义。")
                label, accepted = QInputDialog.getText(
                    self.parent, "粘贴基准", _DATUM_NAME_PROMPT, text=self._next_datum_label()
                )
                if not accepted:
                    self._message("已取消粘贴基准。")
                    return True
                if any(item.label.casefold() == label.casefold() for item in self.datums):
                    raise ValueError("基准名称已存在。")
                if datum.attachment is not None:
                    current = next(
                        (item for item in self.datums if item.datum_id == datum.datum_id), None
                    )
                    if (
                        not preserve
                        or current is None
                        or current.attachment != datum.attachment
                        or self.attachment_resolved is None
                        or not self.attachment_resolved(datum.datum_id)
                    ):
                        datum = self._drop_datum_geometry_attachment(datum)
                        lost_links = True
                    else:
                        datum = replace(datum, target_mm=current.target_mm)
                if datum.annotation_attachment is not None:
                    current = next(
                        (item for item in self.datums if item.datum_id == datum.datum_id), None
                    )
                    if (
                        not preserve
                        or current is None
                        or current.annotation_attachment != datum.annotation_attachment
                        or self.attachment_resolved is None
                        or not self.attachment_resolved(datum.datum_id)
                    ):
                        datum = replace(datum, annotation_attachment=None)
                        lost_links = True
                    else:
                        datum = replace(datum, target_mm=current.target_mm)
                try:
                    self.canvas.layer_table.get(datum.layer_name)
                except KeyError:
                    datum = replace(datum, layer_name=self.canvas.active_layer_name)
                    missing_layer = True
                self.clipboard_datum = replace(datum, datum_id=uuid4().hex, label=label)
            else:
                dimension = DetachedDimension.from_mapping(record["object"])
                try:
                    self.canvas.layer_table.get(dimension.layer_name)
                except KeyError:
                    dimension = replace(dimension, layer_name=self.canvas.active_layer_name)
                    missing_layer = True
                self.clipboard_reference = replace(dimension, dimension_id=uuid4().hex)
            self.canvas.set_tool("选择元素")
            self._message(
                "点击放置复制的标注；Esc 取消。"
                + (" 原图层不存在，将使用当前图层。" if missing_layer else "")
                + (" 部分关联需重新建立。" if lost_links else "")
            )
            return True
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
            self._message(f"标注剪贴板数据无效：{exc}")
            return True

    def _place_mixed(self, point: tuple[float, float]) -> None:
        if self.clipboard_mixed is None:
            return
        mixed = self.clipboard_mixed
        if self.source_revision is None or self.source_revision() != mixed.target_revision:
            self.clipboard_mixed = None
            self.mixed_copy_command = False
            self.mixed_copy_base = None
            self.mixed_view_frame = None
            self._message("图纸已变化，请重新开始混合粘贴。")
            return
        base = self.mixed_copy_base if self.mixed_copy_command else mixed.anchor
        if base is None:
            self.mixed_copy_base = point
            self.mixed_view_frame = self.canvas.drawing_view_frame
            self._message("指定混合复制的目标点；Esc 取消。")
            return
        if (
            self.mixed_copy_command
            and self.mixed_view_frame is not None
            and self.mixed_view_frame != self.canvas.drawing_view_frame
        ):
            self.cancel()
            self._message("工作平面已改变，请重新开始混合复制。")
            return
        try:
            if self.mixed_copy_command:
                delta = project_coplanar_vector(
                    (point[0] - base[0], point[1] - base[1]),
                    self.canvas.drawing_view_frame,
                    WorkPlaneFrame.xy(),
                )
            else:
                drawing_point = self._drawing_point(point)
                delta = (drawing_point[0] - base[0], drawing_point[1] - base[1])
            entities, constraints = (
                instantiate_drawing_clipboard(mixed.sketch, delta, styles=mixed.styles)
                if mixed.sketch.entities
                else ((), ())
            )
            sketch_id = uuid4().hex
            mapping = {
                (mixed.owners[old.entity_id], old.entity_id): new.entity_id
                for old, new in zip(mixed.sketch.entities, entities, strict=True)
            }
            references = tuple(
                replace(
                    item,
                    dimension_id=uuid4().hex,
                    first_mm=(item.first_mm[0] + delta[0], item.first_mm[1] + delta[1]),
                    second_mm=(item.second_mm[0] + delta[0], item.second_mm[1] + delta[1]),
                    vertex_mm=(item.vertex_mm[0] + delta[0], item.vertex_mm[1] + delta[1])
                    if item.vertex_mm is not None
                    else None,
                    location_mm=(
                        item.location_mm[0] + delta[0],
                        item.location_mm[1] + delta[1],
                    ),
                )
                for item in mixed.references
            )
            texts = tuple(
                replace(move_text(item, delta), text_id=uuid4().hex) for item in mixed.texts
            )
            rasters = tuple(
                replace(
                    item,
                    image_id=uuid4().hex,
                    origin_mm=(item.origin_mm[0] + delta[0], item.origin_mm[1] + delta[1]),
                )
                for item in mixed.rasters
            )
            reference_mapping = {
                old.dimension_id: new.dimension_id
                for old, new in zip(mixed.references, references, strict=True)
            }
            dimension_mapping = {
                (mixed.owners[old.references[0].entity_id], old.constraint_id): new.constraint_id
                for old, new in zip(mixed.sketch.constraints, constraints, strict=True)
                if old.references and old.references[0].entity_id in mixed.owners
            }
            frames, datums = copy_geometric_annotations(
                mixed.frames,
                mixed.datums,
                mapping,
                sketch_id,
                delta,
                mixed.labels,
                preserve_external=mixed.preserve_external,
                reference_mapping=reference_mapping,
                dimension_mapping=dimension_mapping,
            )
            datums = tuple(
                self.relayout_recorded_datum(datum, mixed.text_styles) for datum in datums
            )
            if mixed.styles is not None:
                constraints = tuple(
                    replace(clone, style_name=original.style_name)
                    for original, clone in zip(mixed.sketch.constraints, constraints, strict=True)
                )
            sketch = Sketch(
                sketch_id,
                WorkPlaneFrame.xy(),
                entities,
                constraints=constraints,
                layers=mixed.sketch.layers,
            )
            used_layers = {
                item.layer_name.casefold()
                for item in (
                    *mixed.sketch.entities,
                    *frames,
                    *datums,
                    *references,
                    *texts,
                    *rasters,
                )
            } | {
                item.layer_name.casefold()
                for item in mixed.sketch.constraints
                if item.layer_name is not None
            }
            target_layers = {
                layer.name.casefold(): layer for layer in self.canvas.layer_table.layers
            }
            source_layers = {layer.name.casefold(): layer for layer in sketch.layers.layers}
            for item in rasters:
                layer = target_layers.get(item.layer_name.casefold())
                if layer is not None and (layer.locked or not layer.displayed):
                    raise ValueError("目标图片图层已锁定或隐藏，不能粘贴。")
            for key in used_layers:
                layer = target_layers.get(key) or source_layers.get(key)
                if layer is not None and (layer.locked or not layer.displayed):
                    raise ValueError("目标图层已锁定或隐藏，不能粘贴。")
            conflicts = sorted(
                layer.name
                for layer in mixed.sketch.layers.layers
                if layer.name.casefold() in used_layers
                and layer.name.casefold() in target_layers
                and layer != target_layers[layer.name.casefold()]
            )
            destination_styles = self.canvas.drawing_dimension_styles
            imported_styles = None
            imported_text_styles = mixed.text_styles if mixed.styles is None else None
            if mixed.styles is not None:
                if destination_styles is None:
                    raise ValueError("目标图纸的标注样式不可用。")
                source_styles = mixed.styles
                if mixed.text_styles is not None:
                    if self.canvas.text_tools is None:
                        raise ValueError("目标图纸的文字样式不可用。")
                    target_text_styles = self.canvas.text_tools.styles
                    font_ids = tuple(
                        style.text_style_id
                        for style in source_styles.styles
                        if style.text_style_id is not None
                    )
                    font_ids += tuple(
                        frame.text_style_id for frame in frames if frame.text_style_id is not None
                    )
                    font_ids += tuple(
                        datum.text_style_id for datum in datums if datum.text_style_id is not None
                    )
                    font_ids += tuple(item.style_id for item in texts)
                    merged_fonts, font_map = reconcile_text_style_ids(
                        font_ids, mixed.text_styles, target_text_styles
                    )
                    source_styles = replace(
                        source_styles,
                        styles=tuple(
                            replace(style, text_style_id=font_map[style.text_style_id])
                            if style.text_style_id is not None
                            else style
                            for style in source_styles.styles
                        ),
                    )
                    frames = tuple(
                        replace(frame, text_style_id=font_map[frame.text_style_id])
                        if frame.text_style_id is not None
                        else frame
                        for frame in frames
                    )
                    datums = tuple(
                        replace(datum, text_style_id=font_map[datum.text_style_id])
                        if datum.text_style_id is not None
                        else datum
                        for datum in datums
                    )
                    texts = tuple(replace(item, style_id=font_map[item.style_id]) for item in texts)
                    if merged_fonts != target_text_styles:
                        imported_text_styles = merged_fonts
                merged, sketch = reconcile_clipboard_styles(
                    sketch, source_styles, destination_styles
                )
                if merged != destination_styles:
                    imported_styles = merged
            if self.commit_mixed is not None and self.commit_mixed(
                sketch,
                frames,
                datums,
                references,
                texts,
                rasters,
                imported_styles,
                imported_text_styles,
                mixed.preserve_external,
            ):
                self.clipboard_mixed = None
                self.mixed_copy_command = False
                self.mixed_copy_base = None
                self.mixed_view_frame = None
                self._message(
                    "图元与标注已复制。"
                    + (f" 同名图层采用目标属性：{', '.join(conflicts)}。" if conflicts else "")
                )
        except (KeyError, TypeError, ValueError) as exc:
            self._message(f"混合粘贴失败：{exc}")
        return

    def _place_mixed_move(self, point: tuple[float, float]) -> None:
        if self.mixed_move_base is None:
            self.mixed_move_base = point
            self.mixed_view_frame = self.canvas.drawing_view_frame
            self._message(
                "指定混合复制的目标点；Esc 取消。"
                if self.mixed_move_copy
                else "指定混合移动的目标点；Esc 取消。"
            )
            return
        if (
            self.mixed_view_frame is not None
            and self.mixed_view_frame != self.canvas.drawing_view_frame
        ):
            self.cancel()
            self._message("工作平面已改变，请重新开始混合移动或复制。")
            return
        delta = (point[0] - self.mixed_move_base[0], point[1] - self.mixed_move_base[1])
        if self.canvas.collection_session is not None:
            self.canvas.begin_collection_preview_commit(self.mixed_move_copy, delta)
        try:
            commit = self.commit_collection_copy if self.mixed_move_copy else self.commit_move
            if commit is None:
                raise ValueError("当前图纸不支持混合移动。")
            if commit(
                self.mixed_move_entities,
                self.mixed_move_frames,
                self.mixed_move_datums,
                self.mixed_move_references,
                self.mixed_move_texts,
                self.mixed_move_rasters,
                delta,
                self.mixed_move_revision,
            ):
                self.mixed_move_active = False
                self.mixed_move_base = None
                self.mixed_view_frame = None
                self._message(
                    "图元与标注已复制。" if self.mixed_move_copy else "图元与标注已移动。"
                )
                self.mixed_move_copy = False
        except ValueError as exc:
            self._message(f"混合移动失败：{exc}")
        finally:
            self.canvas.end_collection_preview_commit()

    @staticmethod
    def _surface_grips(
        target: tuple[float, float], indication: SurfaceIndication | None
    ) -> tuple[tuple[int, tuple[float, float]], ...]:
        if indication is None:
            return ()
        reference, _, landing = surface_indication_geometry(target, indication)
        return (
            (-3, reference[0]),
            (-4, reference[1]),
            (-5, landing),
            *(
                (-6 - index, (target[0] + x, target[1] + y))
                for index, (x, y) in enumerate(indication.leader_offsets_mm)
            ),
        )

    @staticmethod
    def _surface_with_grip(
        target: tuple[float, float],
        indication: SurfaceIndication,
        index: int,
        point: tuple[float, float],
    ) -> SurfaceIndication:
        offset = (point[0] - target[0], point[1] - target[1])
        if index == -3:
            return replace(
                indication,
                reference_start_offset_mm=offset,
                auto_route=False,
                route_avoid_crossing=False,
            )
        if index == -4:
            return replace(
                indication,
                reference_end_offset_mm=offset,
                auto_route=False,
                route_avoid_crossing=False,
            )
        if index == -5:
            x, y = indication.reference_start_offset_mm
            dx = indication.reference_end_offset_mm[0] - x
            dy = indication.reference_end_offset_mm[1] - y
            ratio = max(
                0.0, min(1.0, ((offset[0] - x) * dx + (offset[1] - y) * dy) / (dx * dx + dy * dy))
            )
            return replace(
                indication, landing_ratio=ratio, auto_route=False, route_avoid_crossing=False
            )
        points = list(indication.leader_offsets_mm)
        points[-6 - index] = offset
        return replace(
            indication,
            leader_offsets_mm=tuple(points),
            auto_normal=indication.auto_normal and index != -6,
            auto_route=False,
            route_avoid_crossing=False,
        )

    @staticmethod
    def _datum_grips(datum: DatumIdentifier) -> tuple[tuple[int, tuple[float, float]], ...]:
        if not datum.leader_visible:
            return ((-1, datum.position_mm),)
        return (
            (-1, datum.position_mm),
            (-2, datum.target_mm),
            *GeometricToleranceTools._surface_grips(datum.target_mm, datum.surface_indication),
            *(
                (index, (datum.position_mm[0] + x, datum.position_mm[1] + y))
                for index, (x, y) in enumerate(datum.leader_offsets)
            ),
        )

    @staticmethod
    def _frame_grips(frame: FeatureControlFrame) -> tuple[tuple[int, tuple[float, float]], ...]:
        if frame.leader_target_mm is None:
            return ((-1, frame.position_mm),)
        return (
            (-1, frame.position_mm),
            (-2, frame.leader_target_mm),
            *GeometricToleranceTools._surface_grips(
                frame.leader_target_mm, frame.surface_indication
            ),
            *(
                (index, (frame.position_mm[0] + x, frame.position_mm[1] + y))
                for index, (x, y) in enumerate(frame.leader_offsets)
            ),
        )

    @staticmethod
    def _frame_with_grip(
        frame: FeatureControlFrame, index: int, point: tuple[float, float]
    ) -> FeatureControlFrame:
        if index == -1:
            offsets = frame.leader_offsets
            if frame.leader_auto_route:
                offsets = _relocate_automatic_leader(frame, point)
            elif frame.leader_auto_normal:
                dx, dy = frame.position_mm[0] - point[0], frame.position_mm[1] - point[1]
                offsets = tuple((x + dx, y + dy) for x, y in offsets)
            return replace(
                frame,
                position_mm=point,
                leader_offsets=offsets,
                leader_anchor_offset=None,
            )
        if index == -2:
            return replace(
                frame,
                leader_target_mm=point,
                leader_anchor_offset=None,
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
        if (
            index <= -3
            and frame.surface_indication is not None
            and frame.leader_target_mm is not None
        ):
            return replace(
                frame,
                surface_indication=GeometricToleranceTools._surface_with_grip(
                    frame.leader_target_mm, frame.surface_indication, index, point
                ),
                leader_anchor_offset=None,
            )
        offsets = list(frame.leader_offsets)
        offsets[index] = (point[0] - frame.position_mm[0], point[1] - frame.position_mm[1])
        return replace(
            frame,
            leader_offsets=tuple(offsets),
            leader_anchor_offset=None,
            leader_auto_normal=frame.leader_auto_normal and index != len(offsets) - 1,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
        )

    @staticmethod
    def _leader_vertex_overlaps_neighbor(
        item: FeatureControlFrame | DatumIdentifier, index: int, point: tuple[float, float]
    ) -> bool:
        if index < 0:
            return False
        target = item.leader_target_mm if isinstance(item, FeatureControlFrame) else item.target_mm
        if target is None:
            return False
        if item.surface_indication is not None:
            _, _, target = surface_indication_geometry(target, item.surface_indication)
        vertices = tuple(
            (item.position_mm[0] + x, item.position_mm[1] + y) for x, y in item.leader_offsets
        )
        neighbors = ([vertices[index - 1]] if index > 0 else []) + [
            vertices[index + 1] if index + 1 < len(vertices) else target
        ]
        return any(math.dist(point, neighbor) <= 1e-9 for neighbor in neighbors)

    @staticmethod
    def _leader_target_overlaps_vertex(item: FeatureControlFrame | DatumIdentifier) -> bool:
        if not item.leader_offsets:
            return False
        target = item.leader_target_mm if isinstance(item, FeatureControlFrame) else item.target_mm
        if target is None:
            return False
        if item.surface_indication is not None:
            _, _, target = surface_indication_geometry(target, item.surface_indication)
        offset = item.leader_offsets[-1]
        vertex = (item.position_mm[0] + offset[0], item.position_mm[1] + offset[1])
        return math.dist(target, vertex) <= 1e-9

    def _annotation_layer_editable(self, layer_name: str) -> bool:
        layer = self.canvas.layer_table.get(layer_name)
        if (
            layer.locked
            or not layer.displayed
            or (
                self.source_layer_editable is not None
                and not self.source_layer_editable(layer_name)
            )
        ):
            self._message("标注图层已锁定、冻结或隐藏，不能执行当前操作。")
            return False
        return True

    def _place_frame_grip(self, point: tuple[float, float]) -> None:
        if self.frame_grip is None:
            return
        if (
            self.grip_view_frame is not None
            and self.grip_view_frame != self.canvas.drawing_view_frame
        ):
            self.cancel()
            self._message("工作平面已改变，请重新选择标注夹点。")
            return
        original, index = self.frame_grip
        try:
            point = self._drawing_point(point)
        except ValueError as exc:
            self._message(str(exc))
            return
        if original not in self.frames or (
            self.source_subject is not None
            and self.source_subject("frame", original.frame_id) != original
        ):
            self.cancel()
            self._message("公差框已改变，请重新选择夹点。")
            return
        if not self._annotation_layer_editable(original.layer_name):
            return
        if self._leader_vertex_overlaps_neighbor(original, index, point):
            self._message("引线相邻顶点不能重合，请重新指定位置。")
            return
        try:
            candidate = self._frame_with_grip(original, index, point)
        except ValueError as exc:
            self._message(str(exc))
            return
        if index == -2:
            previous = original.leader_attachment
            attachment, target = (
                self._pick_surface_extension(point, original=previous)
                if previous is not None and previous.surface_extension is not None
                else (None, point)
            )
            annotation = None
            if attachment is None:
                attachment, annotation, target = self._pick_target(
                    point, exclude_frame=original.frame_id
                )
            if target is None:
                return
            if (
                attachment is None
                and annotation is None
                and (
                    original.leader_attachment is not None
                    or original.leader_annotation_attachment is not None
                )
            ):
                self._message("请选择唯一的几何位置；Esc 取消。")
                return
            candidate = replace(
                candidate,
                leader_target_mm=target,
                leader_attachment=attachment,
                leader_annotation_attachment=annotation,
            )
            if self._leader_target_overlaps_vertex(candidate):
                self._message("引线相邻顶点不能重合，请重新指定位置。")
                return
        if candidate.leader_target_mm is not None:
            anchor = self._frame_leader_anchor(candidate)
            if anchor is None:
                self._message("公差框与引线指向点重叠，请重新指定位置。")
                return
            candidate = replace(
                candidate,
                leader_anchor_offset=(
                    anchor[0] - candidate.position_mm[0],
                    anchor[1] - candidate.position_mm[1],
                ),
            )
        if self._commit({"update_frames": [candidate.to_mapping()]}):
            self.frame_grip = None
            self.frame_grip_cursor = None
            self.grip_view_frame = None
            self._message("公差框夹点已调整。")

    @staticmethod
    def _datum_with_grip(
        datum: DatumIdentifier, index: int, point: tuple[float, float]
    ) -> DatumIdentifier:
        if index == -1:
            if datum.leader_auto_normal:
                dx = datum.position_mm[0] - point[0]
                dy = datum.position_mm[1] - point[1]
                offsets = (
                    _relocate_automatic_leader(datum, point)
                    if datum.leader_auto_route
                    else tuple((x + dx, y + dy) for x, y in datum.leader_offsets)
                )
                return replace(datum, position_mm=point, leader_offsets=offsets)
            return replace(
                datum,
                position_mm=point,
                target_mm=point if not datum.leader_visible else datum.target_mm,
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
            )
        if index == -2:
            return replace(
                datum,
                target_mm=point,
                leader_auto_normal=False,
                leader_auto_route=False,
                route_avoid_crossing=False,
                route_track_target=False,
                route_algorithm_version=1,
                spline_normal_enabled=False,
            )
        if index <= -3 and datum.surface_indication is not None:
            return replace(
                datum,
                surface_indication=GeometricToleranceTools._surface_with_grip(
                    datum.target_mm, datum.surface_indication, index, point
                ),
            )
        offsets = list(datum.leader_offsets)
        offsets[index] = (point[0] - datum.position_mm[0], point[1] - datum.position_mm[1])
        keep_normal = datum.leader_auto_normal and index != len(offsets) - 1
        return replace(
            datum,
            leader_offsets=tuple(offsets),
            leader_auto_normal=keep_normal,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
            spline_normal_enabled=datum.spline_normal_enabled and keep_normal,
        )

    def _place_datum_grip(self, point: tuple[float, float]) -> None:
        if self.datum_grip is None:
            return
        if (
            self.grip_view_frame is not None
            and self.grip_view_frame != self.canvas.drawing_view_frame
        ):
            self.cancel()
            self._message("工作平面已改变，请重新选择标注夹点。")
            return
        original, index = self.datum_grip
        try:
            point = self._drawing_point(point)
        except ValueError as exc:
            self._message(str(exc))
            return
        if original not in self.datums or (
            self.source_subject is not None
            and self.source_subject("datum", original.datum_id) != original
        ):
            self.cancel()
            self._message("基准已改变，请重新选择夹点。")
            return
        if not self._annotation_layer_editable(original.layer_name):
            return
        if self._leader_vertex_overlaps_neighbor(original, index, point):
            self._message("引线相邻顶点不能重合，请重新指定位置。")
            return
        try:
            candidate = self._datum_with_grip(original, index, point)
        except ValueError as exc:
            self._message(str(exc))
            return
        if index == -2:
            previous = original.attachment
            attachment, target = (
                self._pick_surface_extension(point, original=previous)
                if previous is not None and previous.surface_extension is not None
                else (None, point)
            )
            annotation = None
            if attachment is None:
                attachment, annotation, target = self._pick_target(point)
            if target is None:
                return
            if (
                attachment is None
                and annotation is None
                and (original.attachment is not None or original.annotation_attachment is not None)
            ):
                self._message("请选择唯一的几何位置；Esc 取消。")
                return
            if attachment is not None or annotation is not None:
                candidate = replace(
                    candidate,
                    target_mm=target,
                    attachment=attachment,
                    annotation_attachment=annotation,
                )
            if self._leader_target_overlaps_vertex(candidate):
                self._message("引线相邻顶点不能重合，请重新指定位置。")
                return
        if self._commit({"update_datums": [candidate.to_mapping()]}):
            self.datum_grip = None
            self.datum_grip_cursor = None
            self.grip_view_frame = None
            self._message("基准引线顶点已调整。")

    def datum_mouse_release(self, event: QMouseEvent) -> bool:
        """Move a selected datum when its box was dragged, using MOVE semantics."""
        if event.button() != Qt.MouseButton.LeftButton or self.datum_drag is None:
            return False
        datum, start_screen, start, view_frame = self.datum_drag
        self.datum_drag = None
        self.datum_drag_cursor = None
        if (
            math.hypot(
                event.position().x() - start_screen.x(), event.position().y() - start_screen.y()
            )
            <= 4
        ):
            return False
        self.transform_subject = datum
        self.transform_action = "move"
        self.transform_arrow_base = False
        self.transform_base = start
        self.transform_view_frame = view_frame
        self._transform_point(self.canvas.screen_to_local(event.position()))
        self.transform_action = ""
        self.transform_base = None
        self.transform_cursor = None
        self.transform_view_frame = None
        self.transform_subject = None
        return True

    def mouse_press(self, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        self.datum_drag = None
        self.datum_drag_cursor = None
        if (
            self.surface_edit is not None
            or self.mechanical_frame_active
            or self.mechanical_datum_active
        ):
            try:
                self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
        if self.surface_edit is not None:
            point = self._constrain_surface_edit_mouse(
                self.canvas.screen_to_local(event.position())
            )
            self._finish_surface_indication_edit(point)
            return True
        if self.datum_grip is not None:
            self._place_datum_grip(self.canvas.screen_to_local(event.position()))
            return True
        if self.frame_grip is not None:
            self._place_frame_grip(self.canvas.screen_to_local(event.position()))
            return True
        if self.mechanical_frame_active:
            self._mechanical_frame_point(
                self._constrain_frame_mouse(self.canvas.screen_to_local(event.position()))
            )
            return True
        if self.mechanical_datum_active:
            self._mechanical_datum_point(
                self._constrain_datum_mouse(self.canvas.screen_to_local(event.position()))
            )
            return True
        if self.mixed_move_active:
            self._place_mixed_move(self.canvas.screen_to_local(event.position()))
            return True
        if self.transform_action:
            point = self.canvas.screen_to_local(event.position())
            datum = self.transform_subject
            if self.transform_base is None and isinstance(datum, DatumIdentifier):
                target = self._view_point(datum.target_mm)
                projected = self.display_datum(datum)
                arrow_hit = False
                if projected is not None and datum.surface_indication is None:
                    _, arrow = self.datum_screen_path(projected)
                    if arrow:
                        path = QPainterPath()
                        path.addPolygon(arrow)
                        path.closeSubpath()
                        stroke = QPainterPathStroker()
                        stroke.setWidth(6)
                        arrow_hit = path.contains(event.position()) or stroke.createStroke(
                            path
                        ).contains(event.position())
                self.transform_arrow_base = datum.leader_visible and (
                    arrow_hit or math.dist(point, target) * self.canvas.view_scale <= 7.0
                )
                if self.transform_arrow_base:
                    point = target
                else:
                    point = self.canvas.snap_annotation_point(point)[0]
            else:
                point = self.canvas.snap_annotation_point(point)[0]
            self._transform_point(point)
            return True
        if self.clipboard_mixed is not None:
            self._place_mixed(self.canvas.screen_to_local(event.position()))
            return True
        if self.clipboard_frame is not None:
            if not self._annotation_layer_editable(self.clipboard_frame.layer_name):
                return True
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            dx = point[0] - self.clipboard_frame.position_mm[0]
            dy = point[1] - self.clipboard_frame.position_mm[1]
            frame = translate_frame(
                self.clipboard_frame,
                (dx, dy),
            )
            if (
                self.clipboard_frame.leader_attachment is not None
                or self.clipboard_frame.leader_annotation_attachment is not None
            ):
                try:
                    offsets = _moved_leader_offsets(self.clipboard_frame, point)
                except ValueError as exc:
                    self._message(str(exc))
                    return True
                frame = replace(
                    frame,
                    leader_target_mm=self.clipboard_frame.leader_target_mm,
                    leader_offsets=offsets,
                )
            if self._commit({"add_frames": [frame.to_mapping()]}):
                self.clipboard_frame = None
                self._message("公差框已粘贴。")
            return True
        if self.clipboard_datum is not None:
            datum = self.clipboard_datum
            if not self._annotation_layer_editable(datum.layer_name):
                return True
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            dx, dy = point[0] - datum.position_mm[0], point[1] - datum.position_mm[1]
            target = (
                datum.target_mm
                if datum.attachment is not None or datum.annotation_attachment is not None
                else (datum.target_mm[0] + dx, datum.target_mm[1] + dy)
            )
            try:
                offsets = _moved_leader_offsets(datum, point)
            except ValueError as exc:
                self._message(str(exc))
                return True
            try:
                placed = self.relayout_recorded_datum(
                    replace(datum, position_mm=point, target_mm=target, leader_offsets=offsets)
                )
            except (KeyError, ValueError) as exc:
                self._message(str(exc))
                return True
            if self._commit({"add_datums": [placed.to_mapping()]}):
                self.clipboard_datum = None
                self._message("基准已粘贴。")
            return True
        if self.clipboard_reference is not None:
            dimension = self.clipboard_reference
            if not self._annotation_layer_editable(dimension.layer_name):
                return True
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            dx, dy = point[0] - dimension.location_mm[0], point[1] - dimension.location_mm[1]
            moved = replace(
                dimension,
                location_mm=point,
                first_mm=(dimension.first_mm[0] + dx, dimension.first_mm[1] + dy),
                second_mm=(dimension.second_mm[0] + dx, dimension.second_mm[1] + dy),
                vertex_mm=(dimension.vertex_mm[0] + dx, dimension.vertex_mm[1] + dy)
                if dimension.vertex_mm is not None
                else None,
            )
            if self._commit_reference({"add": [moved.to_mapping()]}):
                self.clipboard_reference = None
                self._message("参考尺寸已粘贴。")
            return True
        if self.pending_reattach:
            datum = self._single_selected_datum()
            if (
                datum is None
                or datum != self.pending_reattach_target
                or (
                    self.pending_reattach_revision is not None
                    and (
                        self.source_revision is None
                        or self.source_revision() != self.pending_reattach_revision
                    )
                )
            ):
                self._end_reattach()
                self._message("图纸或选择已变化，请重新开始基准重关联。")
                return True
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            attachment, annotation, point = self._pick_target(point)
            if point is None:
                return True
            if attachment is None and annotation is None:
                self._message("请选择唯一的已有几何或标注位置；Esc 取消。")
            elif self._commit(
                {
                    "update_datums": [
                        replace(
                            datum,
                            attachment=attachment,
                            annotation_attachment=annotation,
                            target_mm=point,
                        ).to_mapping()
                    ]
                }
            ):
                self._end_reattach()
                self._message("基准已重新关联。")
            return True
        if self.pending_datum_label:
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            if self.pending_datum_position is None:
                self.pending_datum_position = point
                self._message("基准标识：点击指定指向点。")
            else:
                attachment, annotation, point = self._pick_target(point)
                if point is None:
                    return True
                datum = DatumIdentifier(
                    uuid4().hex,
                    self.pending_datum_label,
                    self.pending_datum_position,
                    point,
                    self.canvas.active_layer_name,
                    attachment,
                    layout_mode="shared",
                    annotation_attachment=annotation,
                    symbol_style=self.creation_datum_symbol_style,
                )
                datum = self._oriented_datum(datum)
                if not self._annotation_layer_editable(datum.layer_name):
                    return True
                if self._commit({"add_datums": [datum.to_mapping()]}):
                    self.pending_datum_label = ""
                    self.pending_datum_position = None
                    self._message(
                        "基准标识已放置并附着几何。"
                        if attachment is not None
                        else "基准标识已放置；指向点未附着几何。"
                    )
            return True
        if self.pending_rows:
            try:
                point = self._drawing_point(self.canvas.screen_to_local(event.position()))
            except ValueError as exc:
                self._message(str(exc))
                return True
            frame = FeatureControlFrame(
                uuid4().hex,
                self.pending_rows,
                point,
                rotation_deg=self.pending_rotation,
                layer_name=self.pending_layer,
                text_style_id=self.pending_text_style_id,
                leader_arrow_style="closed_filled",
            )
            if not self._annotation_layer_editable(frame.layer_name):
                return True
            if self._commit({"add_frames": [frame.to_mapping()]}):
                self.pending_rows = ()
                self._message("形位公差已放置。")
            return True
        if self.canvas.tool != "选择元素":
            return False
        if len(self.selected_ids) == 1 and self.selected_kind == "frame":
            selected_frame = next(
                (frame for frame in self.frames if frame.frame_id == self.selected_id), None
            )
            if selected_frame is not None:
                layer = self.canvas.layer_table.get(selected_frame.layer_name)
                projected_frame = self.display_frame(selected_frame)
                if layer.displayed and not layer.locked and projected_frame is not None:
                    for index, world in self._frame_grips(projected_frame):
                        grip = self.canvas.local_to_screen(world)
                        if (
                            math.hypot(
                                event.position().x() - grip.x(), event.position().y() - grip.y()
                            )
                            <= 6
                        ):
                            self.frame_grip = (selected_frame, index)
                            self.frame_grip_cursor = None
                            self.grip_view_frame = self.canvas.drawing_view_frame
                            self._message("指定公差框夹点新位置；Esc 取消。")
                            return True
        selected_datum = (
            self._single_selected_datum() if self.canvas.active_transform is None else None
        )
        if selected_datum is not None:
            layer = self.canvas.layer_table.get(selected_datum.layer_name)
            projected_datum = self.display_datum(selected_datum)
            if layer.displayed and not layer.locked and projected_datum is not None:
                for index, world in self._datum_grips(projected_datum):
                    grip = self.canvas.local_to_screen(world)
                    if (
                        math.hypot(event.position().x() - grip.x(), event.position().y() - grip.y())
                        <= 6
                    ):
                        self.datum_grip = (selected_datum, index)
                        self.datum_grip_cursor = None
                        self.grip_view_frame = self.canvas.drawing_view_frame
                        self._message("指定基准引线顶点新位置；Esc 取消。")
                        return True
                if (
                    event.modifiers() == Qt.KeyboardModifier.NoModifier
                    and not self.canvas.selected_entity_ids
                    and not self.canvas.selected_constraint_ids
                    and not self.canvas.selected_raster_ids
                    and (self.canvas.text_tools is None or not self.canvas.text_tools.selected_ids)
                    and self.datum_screen_bounds(projected_datum).contains(event.position())
                ):
                    self.datum_drag = (
                        selected_datum,
                        QPointF(event.position()),
                        self.canvas.screen_to_local(event.position()),
                        self.canvas.drawing_view_frame,
                    )
        self.selection_before_press = set(self.selected_ids)
        for source in reversed(self.reference_dimensions):
            dimension = self.display_reference(source)
            if dimension is None:
                continue
            layer = self.canvas.layer_table.get(dimension.layer_name)
            if (
                layer.displayed
                and not layer.locked
                and (layout := self.reference_layout(source)) is not None
                and layout.hit(event.position())
            ):
                selected = self._select(
                    dimension.dimension_id,
                    "reference",
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                )
                if selected:
                    self._message("独立参考尺寸：不关联几何。双击编辑公差。")
                return True
        for source in reversed(self.frames):
            frame = self.display_frame(source)
            if frame is None:
                continue
            layer = self.canvas.layer_table.get(frame.layer_name)
            if layer.displayed and not layer.locked:
                inverse, valid = self._transform(frame).inverted()
                points = self.frame_screen_leader(frame)
                extension = self.surface_screen_path(frame.leader_attachment)
                indication_path = (
                    self._surface_indication_path(frame.leader_target_mm, frame.surface_indication)
                    if frame.leader_target_mm is not None
                    else QPainterPath()
                )
                stroke = QPainterPathStroker()
                stroke.setWidth(10)
                arrow = self._frame_screen_arrow(frame, points)
                arrow_path = QPainterPath()
                if arrow:
                    arrow_path.addPolygon(arrow)
                    arrow_path.closeSubpath()
                if valid and (
                    self._layout(frame).bounds.contains(inverse.map(event.position()))
                    or any(
                        _near_segment(event.position(), a, b, 5.0)
                        for a, b in zip(points, points[1:], strict=False)
                    )
                    or arrow_path.contains(event.position())
                    or stroke.createStroke(arrow_path).contains(event.position())
                    or (
                        frame.leader_target_mm is not None
                        and self._surface_arrow_contains(
                            frame.leader_target_mm, frame.surface_indication, event.position()
                        )
                    )
                    or stroke.createStroke(indication_path).contains(event.position())
                    or any(
                        _near_segment(event.position(), a, b, 5.0)
                        for a, b in zip(extension, extension[1:], strict=False)
                    )
                ):
                    selected = self._select(
                        frame.frame_id,
                        "frame",
                        additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                    )
                    if not selected:
                        return True
                    return True
        for source in reversed(self.datums):
            datum = self.display_datum(source)
            if datum is None:
                continue
            layer = self.canvas.layer_table.get(datum.layer_name)
            rect = self.datum_screen_bounds(datum)
            if not layer.displayed or layer.locked:
                continue
            points, polygon = self.datum_screen_path(datum, rect)
            circular_bar: tuple[QPointF, QPointF] | None = None
            if datum.symbol_style == "circle":
                with suppress(ValueError):
                    _, circular_bar = self.circular_datum_screen_geometry(datum)
            extension = self.surface_screen_path(datum.attachment)
            indication_path = self._surface_indication_path(
                datum.target_mm, datum.surface_indication
            )
            stroke = QPainterPathStroker()
            stroke.setWidth(10)
            arrow_path = QPainterPath()
            if polygon:
                arrow_path.addPolygon(polygon)
                arrow_path.closeSubpath()
            if (
                rect.adjusted(-5, -5, 5, 5).contains(event.position())
                or any(
                    _near_segment(event.position(), a, b, 5.0)
                    for a, b in zip(points, points[1:], strict=False)
                )
                or (
                    circular_bar is not None and _near_segment(event.position(), *circular_bar, 5.0)
                )
                or (datum.arrow_style == "filled" and arrow_path.contains(event.position()))
                or stroke.createStroke(arrow_path).contains(event.position())
                or self._surface_arrow_contains(
                    datum.target_mm, datum.surface_indication, event.position()
                )
                or stroke.createStroke(indication_path).contains(event.position())
                or any(
                    _near_segment(event.position(), a, b, 5.0)
                    for a, b in zip(extension, extension[1:], strict=False)
                )
            ):
                selected = self._select(
                    datum.datum_id,
                    "datum",
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                )
                if (
                    selected
                    and event.modifiers() == Qt.KeyboardModifier.NoModifier
                    and self.canvas.active_transform is None
                    and rect.contains(event.position())
                ):
                    self.datum_drag = (
                        source,
                        QPointF(event.position()),
                        self.canvas.screen_to_local(event.position()),
                        self.canvas.drawing_view_frame,
                    )
                return True
        if (
            self.selected_id is not None
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.selected_id = None
            self.selected_ids.clear()
            self.canvas.update()
        return False

    def _select(self, identity: str, kind: str, *, additive: bool = False) -> bool:
        matches = (
            sum(item.frame_id == identity for item in self.frames)
            + sum(item.datum_id == identity for item in self.datums)
            + sum(item.dimension_id == identity for item in self.reference_dimensions)
        )
        if matches != 1:
            self.selected_id = None
            self.selected_ids.clear()
            self._message("标注身份重复，无法安全选择；请先修复重复身份。")
            self.canvas.update()
            return False
        if not additive:
            self.canvas.selected_entity_ids.clear()
            self.canvas.selected_constraint_ids.clear()
            self.canvas.selected_raster_ids.clear()
            self.canvas.selected_block_instance_ids.clear()
            self.canvas.clear_selected_tangent_segments()
            if self.canvas.text_tools is not None:
                self.canvas.text_tools.selected_ids.clear()
            self.selected_ids.clear()
        if additive and identity in self.selected_ids:
            self.selected_ids.remove(identity)
            self.selected_id = next(iter(self.selected_ids), None)
            if self.selected_id is not None:
                self.selected_kind = (
                    "frame"
                    if any(item.frame_id == self.selected_id for item in self.frames)
                    else "datum"
                    if any(item.datum_id == self.selected_id for item in self.datums)
                    else "reference"
                )
        else:
            self.selected_ids.add(identity)
            self.selected_id, self.selected_kind = identity, kind
        if kind == "datum":
            datum = next((item for item in self.datums if item.datum_id == identity), None)
            warnings: list[str] = []
            if (
                datum is not None
                and (datum.attachment is not None or datum.annotation_attachment is not None)
                and self.attachment_resolved is not None
                and not self.attachment_resolved(identity)
            ):
                warnings.append("基准已失关联；输入 REATTACH 选择新的几何位置。")
            if datum is not None:
                font_warning = self._datum_font_warning(datum)
                if font_warning:
                    warnings.append(font_warning)
            if warnings:
                self._message(" ".join(warnings))
        elif kind == "frame":
            frame = next((item for item in self.frames if item.frame_id == identity), None)
            if frame is not None:
                warnings = []
                if self._frame_attachment_lost(frame):
                    warnings.append(
                        "公差框引线已失关联；拖动目标夹点重新关联，或输入 DETACHFRAME 解除附着。"
                    )
                unresolved = self._unresolved_datum_labels(frame)
                if unresolved:
                    warnings.append(
                        f"基准 {', '.join(unresolved)} 未关联；双击公差框可查看或关联本图基准。"
                    )
                font_warning = self._frame_font_warning(frame)
                if font_warning:
                    warnings.append(font_warning)
                if warnings:
                    self._message(" ".join(warnings))
        self.canvas.changed.emit()
        self.canvas.update()
        return True

    def double_click(self, event: QMouseEvent) -> bool:
        if not self.mouse_press(event) or self.selected_id is None:
            return False
        if self.selected_kind == "reference":
            dimension = next(
                (
                    item
                    for item in self.reference_dimensions
                    if item.dimension_id == self.selected_id
                ),
                None,
            )
            if dimension is None:
                return False
            dialog = DimensionToleranceDialog(
                dimension.tolerance, dimension.tolerance, self.parent, nominal=dimension.nominal
            )
            dialog.inherit.setEnabled(False)
            if dialog.exec() == int(QDialog.DialogCode.Accepted):
                if not self._annotation_edit_is_current(
                    "reference", dimension.dimension_id, dimension
                ):
                    return True
                tolerance = dialog.selected_value()
                if tolerance is not None:
                    self._commit_reference(
                        {"update": [replace(dimension, tolerance=tolerance).to_mapping()]}
                    )
            return True
        if self.selected_kind == "datum":
            datum = next((item for item in self.datums if item.datum_id == self.selected_id), None)
            if datum is None:
                return False
            label, accepted = QInputDialog.getText(
                self.parent, "基准标识", _DATUM_NAME_PROMPT, text=datum.label
            )
            if accepted:
                if not self._annotation_edit_is_current("datum", datum.datum_id, datum):
                    return True
                try:
                    updated = self.relayout_recorded_datum(replace(datum, label=label))
                    self._commit({"update_datums": [updated.to_mapping()]})
                except ValueError as exc:
                    self._message(str(exc))
            return True
        frame = next((item for item in self.frames if item.frame_id == self.selected_id), None)
        if frame is None:
            return False
        dialog = GeometricToleranceDialog(
            frame.rows,
            self.datums,
            self.parent,
            rotation_deg=frame.rotation_deg,
            layer_names=tuple(layer.name for layer in self.canvas.layer_table.layers),
            layer_name=frame.layer_name,
            text_styles=self.canvas.text_tools.styles if self.canvas.text_tools else None,
            text_style_id=frame.text_style_id,
            font_manager=self.manager,
        )
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            if not self._annotation_edit_is_current("frame", frame.frame_id, frame):
                return True
            updated = replace(
                frame,
                rows=dialog.values(),
                rotation_deg=dialog.rotation.precise_value(),
                layer_name=dialog.layer.currentText(),
                text_style_id=cast("str | None", dialog.text_style.currentData()),
            )
            if not self._annotation_layer_editable(updated.layer_name):
                return True
            if updated.leader_target_mm is not None:
                anchor = self._frame_leader_anchor(updated)
                if anchor is None:
                    self._message("公差框与引线指向点重叠，无法更新。")
                    return True
                updated = replace(
                    updated,
                    leader_anchor_offset=(
                        anchor[0] - updated.position_mm[0],
                        anchor[1] - updated.position_mm[1],
                    ),
                )
            self._commit({"update_frames": [updated.to_mapping()]})
        return True

    def delete_selected(self) -> bool:
        if self.selected_id is None:
            return False
        selected = self.selected_ids | {self.selected_id}
        for kind, identity, item in (
            *(("frame", frame.frame_id, frame) for frame in self.frames),
            *(("datum", datum.datum_id, datum) for datum in self.datums),
            *(
                ("reference", reference.dimension_id, reference)
                for reference in self.reference_dimensions
            ),
        ):
            if identity not in selected:
                continue
            if self.source_subject is not None and self.source_subject(kind, identity) != item:
                self._message("标注已改变，请重新选择后删除。")
                return True
            if not self._annotation_layer_editable(item.layer_name):
                return True
        text_tools = self.canvas.text_tools
        if text_tools is not None:
            texts = tuple(
                item for item in text_tools.texts if item.text_id in text_tools.selected_ids
            )
            if len(texts) != len(text_tools.selected_ids):
                self._message("文字选择已改变，请重新选择后删除。")
                return True
            for text in texts:
                if self.source_text is not None and self.source_text(text.text_id) != text:
                    self._message("文字已改变，请重新选择后删除。")
                    return True
                if not self._annotation_layer_editable(text.layer_name):
                    return True
        rasters = tuple(
            item
            for item in self.canvas.drawing_rasters
            if item.image_id in self.canvas.selected_raster_ids
        )
        if len(rasters) != len(self.canvas.selected_raster_ids):
            self._message("图片选择已改变，请重新选择后删除。")
            return True
        for raster in rasters:
            if self.source_raster is not None and self.source_raster(raster.image_id) != raster:
                self._message("图片已改变，请重新选择后删除。")
                return True
            if not self._annotation_layer_editable(raster.layer_name):
                return True
        if self.canvas.selected_entity_ids or self.canvas.selected_constraint_ids:
            if self.commit_geometry_delete is None:
                self._message("当前图纸不支持混合删除。")
                return True
            return self.commit_geometry_delete()
        text_ids = (
            tuple(sorted(self.canvas.text_tools.selected_ids))
            if self.canvas.text_tools is not None
            else ()
        )
        raster_ids = tuple(sorted(self.canvas.selected_raster_ids))
        if len(self.selected_ids) > 1 or text_ids or raster_ids:
            frame_ids = [
                item.frame_id for item in self.frames if item.frame_id in self.selected_ids
            ]
            datum_ids = [
                item.datum_id for item in self.datums if item.datum_id in self.selected_ids
            ]
            reference_ids = [
                item.dimension_id
                for item in self.reference_dimensions
                if item.dimension_id in self.selected_ids
            ]
            if len(frame_ids) + len(datum_ids) + len(reference_ids) != len(self.selected_ids):
                self._message("混合选择暂不支持删除，请分别选择对象。")
                return True
            if reference_ids or text_ids or raster_ids:
                if self.commit_delete is None:
                    self._message("当前图纸不支持混合删除标注。")
                    return True
                try:
                    return self.commit_delete(
                        tuple(frame_ids),
                        tuple(datum_ids),
                        tuple(reference_ids),
                        text_ids,
                        raster_ids,
                    )
                except ValueError as exc:
                    self._message(str(exc))
                    return False
            return self._commit({"remove_frames": frame_ids, "remove_datums": datum_ids})
        identity = self.selected_id
        if self.selected_kind == "reference":
            return self._commit_reference({"remove": [identity]})
        return self._commit(
            {"remove_datums" if self.selected_kind == "datum" else "remove_frames": [identity]}
        )

    def cancel(self) -> bool:
        if not self.pending:
            return False
        if self.mixed_move_active:
            self.canvas.clear_collection_transform_preview()
        self.pending_rows = ()
        self.mechanical_frame_active = False
        self.mechanical_last_pointer = None
        self.surface_pick_active = False
        self.surface_joint_pending = False
        self.surface_joint = None
        self.surface_vertex_pending = False
        self.surface_vertices.clear()
        self.surface_auto_normal = False
        self.surface_edit = None
        self.surface_edit_revision = None
        self.surface_edit_cursor = None
        self.mechanical_frame_target = None
        self.mechanical_frame_attachment = None
        self.mechanical_frame_annotation_attachment = None
        self.mechanical_frame_cursor = None
        self.mechanical_frame_vertices.clear()
        self.mechanical_frame_adding_vertex = False
        self.mechanical_frame_auto_normal = False
        self.pending_datum_label = ""
        self.datum_grip = None
        self.datum_grip_cursor = None
        self.datum_drag = None
        self.datum_drag_cursor = None
        self.frame_grip = None
        self.frame_grip_cursor = None
        self.grip_view_frame = None
        self.mechanical_datum_active = False
        self.mechanical_datum_no_leader = False
        self.mechanical_datum_target = None
        self.mechanical_datum_attachment = None
        self.mechanical_datum_annotation_attachment = None
        self.mechanical_datum_cursor = None
        self.mechanical_datum_vertices.clear()
        self.mechanical_datum_adding_vertex = False
        self.mechanical_datum_auto_normal = False
        self._end_reattach()
        self.clipboard_frame = None
        self.clipboard_datum = None
        self.clipboard_reference = None
        self.clipboard_mixed = None
        self.mixed_copy_command = False
        self.mixed_copy_base = None
        self.mixed_view_frame = None
        self.mixed_move_active = False
        self.mixed_move_copy = False
        self.mixed_move_base = None
        self.pending_datum_position = None
        self.transform_action = ""
        self.transform_arrow_base = False
        self.transform_base = None
        self.transform_cursor = None
        self.transform_view_frame = None
        self.transform_subject = None
        self._message("形位公差放置已取消。")
        self.canvas.update()
        return True

    def _commit_reference(self, params: dict[str, object]) -> bool:
        if self.execute is None:
            self._message("当前图纸不支持独立参考尺寸。")
            return False
        try:
            return self.execute("drawing.reference_dimensions.batch", params)
        except ValueError as exc:
            self._message(str(exc))
            return False

    def _commit(self, params: dict[str, object]) -> bool:
        if self.execute is None:
            self._message("当前图纸不支持形位公差操作。")
            return False
        try:
            return self.execute("drawing.tolerance.batch", params)
        except ValueError as exc:
            self._message(str(exc))
            return False

    def _single_selected_datum(self) -> DatumIdentifier | None:
        if (
            self.selected_kind != "datum"
            or self.selected_id is None
            or self.selected_ids != {self.selected_id}
            or self.canvas.selected_entity_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
        ):
            return None
        return next((datum for datum in self.datums if datum.datum_id == self.selected_id), None)

    def _end_reattach(self) -> None:
        self.pending_reattach = False
        self.pending_reattach_target = None
        self.pending_reattach_revision = None

    def begin_reattach(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再重新关联基准。")
            return
        datum = self._single_selected_datum()
        if datum is None:
            self._message("请选择一个基准标识，再重新关联。")
            return
        self.pending_reattach_target = datum
        self.pending_reattach_revision = (
            self.source_revision() if self.source_revision is not None else None
        )
        self.pending_reattach = True
        self._message("请选择唯一的已有几何位置重新关联；Esc 取消。")

    def detach_selected_datum(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再解除基准附着。")
            return
        datum = self._single_selected_datum()
        if datum is None:
            self._message("请选择一个基准标识，再解除附着。")
            return
        if datum.attachment is None and datum.annotation_attachment is None:
            self._message("所选基准没有附着目标。")
        elif self._commit(
            {
                "update_datums": [
                    replace(
                        self._drop_datum_geometry_attachment(datum), annotation_attachment=None
                    ).to_mapping()
                ]
            }
        ):
            self._message("基准附着已解除，指向位置已保留；可撤销恢复。")

    def detach_selected_frame(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再解除公差框附着。")
            return
        frame = self._selected_surface_annotation()
        if not isinstance(frame, FeatureControlFrame):
            self._message("请单独选择一个有引线的公差框。")
            return
        if frame.leader_attachment is None and frame.leader_annotation_attachment is None:
            self._message("所选公差框没有附着目标。")
            return
        detached = replace(
            self._drop_frame_geometry_attachment(frame), leader_annotation_attachment=None
        )
        if self._commit({"update_frames": [detached.to_mapping()]}):
            self._message("公差框附着已解除，指向位置已保留；可撤销恢复。")

    def repair_annotation_ids(self) -> None:
        from mycad.core.geometric_tolerance_identity import repair_annotation_identities

        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再修复标注身份。")
            return
        frames, references = repair_annotation_identities(
            self.frames, self.datums, self.reference_dimensions
        )
        if not frames["remove_frames"] and not references["remove"]:
            self._message("没有需要修复的标注身份。")
            return
        if self.commit_identity_repair is None:
            self._message("当前图纸不支持修复标注身份。")
            return
        try:
            committed = self.commit_identity_repair()
        except ValueError as exc:
            self._message(str(exc))
            return
        if committed:
            self.selected_id = None
            self.selected_ids.clear()
            self._message("标注身份已修复；可撤销恢复。")

    def upgrade_curve_identities(self) -> None:
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成当前操作，再升级曲线点身份。")
            return
        if not self.canvas.selected_entity_ids:
            self._message("请先选择需要升级的多段线或样条。")
            return
        if (
            self.selected_id is not None
            or self.selected_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
        ):
            self._message("请仅选择需要升级的多段线或样条，取消其他对象的选择。")
            return
        if self.commit_curve_identity_upgrade is None:
            self._message("当前图纸不支持升级曲线点身份。")
            return
        try:
            committed = self.commit_curve_identity_upgrade()
        except ValueError as exc:
            self._message(str(exc))
            return
        if committed:
            self._message("曲线点身份已升级；可撤销。复杂变形仍须检查附着。")

    def handle_command(self, text: str) -> bool:
        if self.surface_edit is not None:
            target = (
                self.surface_edit.target_mm
                if isinstance(self.surface_edit, DatumIdentifier)
                else self.surface_edit.leader_target_mm
            )
            try:
                base = self._view_point(target) if target is not None else None
                self._finish_surface_indication_edit(
                    self._drawing_point(parse_coordinate(text, base))
                )
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.frame_grip is not None:
            original, index = self.frame_grip
            base = next(point for key, point in self._frame_grips(original) if key == index)
            try:
                self._place_frame_grip(parse_coordinate(text, self._view_point(base)))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.mechanical_frame_active:
            if (
                not text.strip()
                and not self.surface_joint_pending
                and not self.mechanical_frame_adding_vertex
            ):
                if not self.mechanical_frame_vertices:
                    self._message("形位公差：请先指定引线顶点或公差框位置。")
                    return True
                if self.mechanical_frame_auto_normal and len(self.mechanical_frame_vertices) == 1:
                    if self.surface_joint is not None:
                        self._mechanical_frame_point(
                            self.mechanical_frame_vertices[0], surface_normal_at_box=True
                        )
                        return True
                    self._mechanical_frame_point(
                        self.mechanical_frame_vertices[0], normal_at_box=True
                    )
                    return True
                point = self.mechanical_frame_vertices.pop()
                try:
                    self._mechanical_frame_point(point)
                finally:
                    if self.mechanical_frame_active:
                        self.mechanical_frame_vertices.append(point)
                return True
            if text.strip().upper() == "V" and self.surface_joint_pending:
                self.surface_vertex_pending = True
                self._message("形位公差：指定表面引线顶点；Esc 取消。")
                return True
            if text.strip().upper() == "F" and self.mechanical_frame_target is not None:
                self.surface_joint_pending = True
                self._message(
                    "形位公差：指定表面指示参考线位置，或输入 V 添加表面引线顶点；Esc 取消。"
                )
                return True
            if text.strip().upper() == "E" and self.mechanical_frame_target is None:
                self.surface_pick_active = True
                self._message("形位公差：指定直线或圆弧延长部分上的指向点；Esc 取消。")
                return True
            if text.strip().upper() == "V" and self.mechanical_frame_target is not None:
                self.mechanical_frame_adding_vertex = True
                self._message("形位公差：指定引线顶点；Esc 取消。")
                return True
            try:
                base = (
                    self.surface_vertices[-1]
                    if self.surface_joint_pending and self.surface_vertices
                    else self.mechanical_frame_vertices[-1]
                    if self.mechanical_frame_vertices
                    else self.mechanical_frame_target
                )
                view_base = self._view_point(base) if base is not None else None
                self._mechanical_frame_point(self._drawing_point(parse_coordinate(text, view_base)))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.datum_grip is not None:
            original, index = self.datum_grip
            base = next(point for key, point in self._datum_grips(original) if key == index)
            try:
                self._place_datum_grip(parse_coordinate(text, self._view_point(base)))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.mechanical_datum_active:
            if self.creation_datum_symbol_style == "circle" and text.strip().upper() in ("N", "F"):
                self._message(
                    "圆圈基准使用普通引线；如需无引线或表面指示，请将新建默认样式设为矩形。"
                )
                return True
            if (
                not text.strip()
                and not self.surface_joint_pending
                and not self.mechanical_datum_adding_vertex
            ):
                if not self.mechanical_datum_vertices:
                    self._message("基准标识：请先指定引线顶点或标识框位置。")
                    return True
                if self.mechanical_datum_auto_normal and len(self.mechanical_datum_vertices) == 1:
                    if self.surface_joint is not None:
                        self._mechanical_datum_point(
                            self.mechanical_datum_vertices[0], surface_normal_at_box=True
                        )
                        return True
                    self._mechanical_datum_point(
                        self.mechanical_datum_vertices[0], normal_at_box=True
                    )
                    return True
                point = self.mechanical_datum_vertices.pop()
                try:
                    self._mechanical_datum_point(point)
                finally:
                    if self.mechanical_datum_active:
                        self.mechanical_datum_vertices.append(point)
                return True
            if text.strip().upper() == "V" and self.surface_joint_pending:
                self.surface_vertex_pending = True
                self._message("基准标识：指定表面引线顶点；Esc 取消。")
                return True
            if (
                text.strip().upper() == "F"
                and self.mechanical_datum_target is not None
                and not self.mechanical_datum_no_leader
            ):
                self.surface_joint_pending = True
                self._message(
                    "基准标识：指定表面指示参考线位置，或输入 V 添加表面引线顶点；Esc 取消。"
                )
                return True
            if text.strip().upper() == "E" and self.mechanical_datum_target is None:
                self.surface_pick_active = True
                self._message("基准标识：指定直线或圆弧延长部分上的指向点；Esc 取消。")
                return True
            if text.strip().upper() == "N" and self.mechanical_datum_target is None:
                self.mechanical_datum_no_leader = True
                self._message("无引线基准：指定标识框位置；Esc 取消。")
                return True
            if text.strip().upper() == "V" and self.mechanical_datum_target is not None:
                self.mechanical_datum_adding_vertex = True
                self._message("基准标识：指定引线顶点；Esc 取消。")
                return True
            try:
                base = (
                    self.surface_vertices[-1]
                    if self.surface_joint_pending and self.surface_vertices
                    else self.mechanical_datum_vertices[-1]
                    if self.mechanical_datum_vertices
                    else self.mechanical_datum_target
                )
                view_base = self._view_point(base) if base is not None else None
                self._mechanical_datum_point(self._drawing_point(parse_coordinate(text, view_base)))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.mixed_move_active:
            try:
                self._place_mixed_move(parse_coordinate(text, self.mixed_move_base))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if self.clipboard_mixed is not None and self.mixed_copy_command:
            try:
                self._place_mixed(parse_coordinate(text, self.mixed_copy_base))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if (
            self.clipboard_frame is not None
            or self.clipboard_datum is not None
            or self.clipboard_reference is not None
            or self.clipboard_mixed is not None
        ):
            self._message("点击放置复制的标注；Esc 取消。")
            return True
        if self.pending_reattach:
            self._message("请选择唯一的已有几何位置；Esc 取消。")
            return True
        if self.transform_action:
            try:
                self._transform_point(parse_coordinate(text, self.transform_base))
            except ValueError as exc:
                self._message(str(exc))
            return True
        if text.strip().upper() == "REATTACH":
            self.begin_reattach()
            return True
        if text.strip().upper() == "DATUMARROW":
            self.edit_datum_arrow_style()
            return True
        if text.strip().upper() == "DATUMSYMBOL":
            self.edit_datum_symbol_style()
            return True
        if text.strip().upper() == "DATUMSTYLE":
            self.edit_datum_text_style()
            return True
        if text.strip().upper() == "SURFACEEXTEDIT":
            self.edit_surface_extension()
            return True
        if text.strip().upper() == "SURFACEINDICATION":
            self.begin_surface_indication_edit()
            return True
        if text.strip().upper() == "EDGESYMBOL":
            self.remove_surface_indication()
            return True
        if text.strip().upper() == "DETACHDATUM":
            self.detach_selected_datum()
            return True
        if text.strip().upper() == "DETACHFRAME":
            self.detach_selected_frame()
            return True
        if text.strip().upper() == "REPAIRANNOTATIONIDS":
            self.repair_annotation_ids()
            return True
        if text.strip().upper() == "CURVEIDUPGRADE":
            self.upgrade_curve_identities()
            return True
        if text.strip().upper() in ("MOVE", "M", "COPY", "CO", "CP") and self.selected_id:
            copy_group = False
            if (
                self.canvas.ensure_group_operation is not None
                and not self.canvas.ensure_group_operation(None)
            ):
                self._message(self.canvas.message)
                return True
            if (
                text.strip().upper() in ("COPY", "CO", "CP")
                and self.canvas.collection_session is not None
            ):
                from mycad.core.exceptions import ValidationError

                try:
                    groups = self.canvas.collection_session.snapshot.groups
                except ValidationError as exc:
                    self._message(str(exc))
                    return True
                if any(
                    group.selectable
                    and any(
                        member.kind in {"tolerance", "datum", "reference_dimension"}
                        and member.object_id in self.selected_ids
                        for member in group.members
                    )
                    for group in groups
                ):
                    copy_group = True
            if (
                copy_group
                or len(self.selected_ids) > 1
                or self.canvas.selected_entity_ids
                or self.canvas.selected_constraint_ids
                or self.canvas.selected_raster_ids
                or (self.canvas.text_tools is not None and self.canvas.text_tools.selected_ids)
                or (
                    self.canvas.collection_session is not None
                    and text.strip().upper() in ("MOVE", "M")
                )
            ):
                if text.strip().upper() in ("COPY", "CO", "CP") and not copy_group:
                    if (
                        self._copy_mixed_to_clipboard()
                        and self.begin_frame_paste()
                        and self.clipboard_mixed is not None
                    ):
                        self.mixed_copy_command = True
                        self.mixed_copy_base = None
                        self._message("指定混合复制的基点，再指定目标点；Esc 取消。")
                else:
                    if (
                        self.commit_collection_copy if copy_group else self.commit_move
                    ) is None or self.source_revision is None:
                        self._message("当前图纸不支持混合移动。")
                    elif not self.canvas.selected_constraint_ids.issubset(
                        {
                            item.constraint_id
                            for item in self.canvas.dimension_constraints()
                            if item.references
                            and all(
                                ref.entity_id in self.canvas.selected_entity_ids
                                for ref in item.references
                            )
                        }
                    ):
                        self._message("所选尺寸或约束须与其全部关联图元一起移动。")
                    else:
                        self.mixed_move_entities = tuple(sorted(self.canvas.selected_entity_ids))
                        self.mixed_move_frames = tuple(
                            item.frame_id
                            for item in self.frames
                            if item.frame_id in self.selected_ids
                        )
                        self.mixed_move_datums = tuple(
                            item.datum_id
                            for item in self.datums
                            if item.datum_id in self.selected_ids
                        )
                        self.mixed_move_references = tuple(
                            item.dimension_id
                            for item in self.reference_dimensions
                            if item.dimension_id in self.selected_ids
                        )
                        self.mixed_move_texts = (
                            tuple(sorted(self.canvas.text_tools.selected_ids))
                            if self.canvas.text_tools is not None
                            else ()
                        )
                        self.mixed_move_rasters = tuple(sorted(self.canvas.selected_raster_ids))
                        self.mixed_move_revision = self.source_revision()
                        self.mixed_move_base = None
                        self.mixed_move_active = True
                        self.mixed_move_copy = copy_group
                        self._message(
                            "指定混合复制的基点，再指定目标点；Esc 取消。"
                            if copy_group
                            else "指定混合移动的基点，再指定目标点；Esc 取消。"
                        )
                return True
            self.transform_subject = self._selected_transform_subject()
            if self.transform_subject is None:
                self._message("所选标注已不存在，请重新选择。")
                return True
            self.transform_action = (
                "copy" if text.strip().upper() in ("COPY", "CO", "CP") else "move"
            )
            self.transform_base = None
            self.transform_arrow_base = False
            self.transform_cursor = None
            self.transform_view_frame = self.canvas.drawing_view_frame
            self._message(
                "指定基点（可选择基准箭头端点），再指定目标点；Esc 取消。"
                if isinstance(self.transform_subject, DatumIdentifier)
                else "指定基点，再指定目标点；Esc 取消。"
            )
            return True
        if text.strip().upper() == "TOLERANCE":
            self.begin_frame()
            return True
        if text.strip().upper() == "AMFCFRAME":
            self.begin_mechanical_frame()
            return True
        if text.strip().upper() == "DATUMLABEL":
            self.begin_mechanical_datum()
            return True
        if text.strip().upper() == "AMDATUMID":
            self.begin_mechanical_datum()
            return True
        return False

    def _selected_transform_subject(
        self,
    ) -> FeatureControlFrame | DatumIdentifier | DetachedDimension | None:
        if self.selected_kind == "frame":
            return next((item for item in self.frames if item.frame_id == self.selected_id), None)
        if self.selected_kind == "datum":
            return next((item for item in self.datums if item.datum_id == self.selected_id), None)
        if self.selected_kind == "reference":
            return next(
                (
                    item
                    for item in self.reference_dimensions
                    if item.dimension_id == self.selected_id
                ),
                None,
            )
        return None

    def _annotation_edit_is_current(
        self,
        kind: str,
        identity: str,
        original: FeatureControlFrame | DatumIdentifier | DetachedDimension,
    ) -> bool:
        if (
            self.selected_kind != kind
            or self.selected_id != identity
            or self._selected_transform_subject() != original
            or (self.source_subject is not None and self.source_subject(kind, identity) != original)
        ):
            self._message("标注或选择已改变，请重新打开编辑器。")
            return False
        return self._annotation_layer_editable(original.layer_name)

    def _transform_subject_is_current(self) -> bool:
        if (
            self.transform_view_frame is not None
            and self.transform_view_frame != self.canvas.drawing_view_frame
        ):
            self.transform_action = ""
            self.transform_base = None
            self.transform_view_frame = None
            self.transform_subject = None
            self._message("工作平面已改变，请重新开始移动或复制。")
            return False
        if (
            self.transform_subject is None
            or self._selected_transform_subject() != self.transform_subject
            or (
                self.source_subject is not None
                and (
                    self.selected_id is None
                    or self.source_subject(self.selected_kind, self.selected_id)
                    != self.transform_subject
                )
            )
        ):
            self.transform_action = ""
            self.transform_base = None
            self.transform_view_frame = None
            self.transform_subject = None
            self._message("标注或选择已改变，请重新开始移动或复制。")
            return False
        return True

    def _transform_point(self, point: tuple[float, float]) -> None:
        if not self._transform_subject_is_current():
            return
        if self.transform_base is None:
            self.transform_base = point
            self.transform_cursor = point
            self.canvas.update()
            self._message(
                "指定箭头的新目标点；靠近图形边线可精确附着，Esc 取消。"
                if self.transform_arrow_base
                else "指定目标点；Esc 取消。"
            )
            return
        dx, dy = point[0] - self.transform_base[0], point[1] - self.transform_base[1]
        try:
            dx, dy = project_coplanar_vector(
                (dx, dy), self.canvas.drawing_view_frame, WorkPlaneFrame.xy()
            )
        except ValueError as exc:
            self._message(str(exc))
            return
        identity, action = self.selected_id, self.transform_action
        params: dict[str, object]
        if self.selected_kind == "reference":
            dimension = next(
                (item for item in self.reference_dimensions if item.dimension_id == identity), None
            )
            if dimension is None:
                self.cancel()
                return
            if not self._annotation_layer_editable(dimension.layer_name):
                return
            changed = replace(
                dimension,
                dimension_id=uuid4().hex if action == "copy" else dimension.dimension_id,
                first_mm=(dimension.first_mm[0] + dx, dimension.first_mm[1] + dy),
                second_mm=(dimension.second_mm[0] + dx, dimension.second_mm[1] + dy),
                vertex_mm=(dimension.vertex_mm[0] + dx, dimension.vertex_mm[1] + dy)
                if dimension.vertex_mm is not None
                else None,
                location_mm=(dimension.location_mm[0] + dx, dimension.location_mm[1] + dy),
            )
            if self._commit_reference(
                {"add" if action == "copy" else "update": [changed.to_mapping()]}
            ):
                self.transform_action = ""
                self.transform_base = None
                self.transform_view_frame = None
                self.transform_subject = None
                self.selected_id = changed.dimension_id
                self.selected_ids = {changed.dimension_id}
                self.canvas.update()
                self._message(
                    "独立参考尺寸已复制。" if action == "copy" else "独立参考尺寸已移动。"
                )
            return
        if self.selected_kind == "frame":
            item = next((frame for frame in self.frames if frame.frame_id == identity), None)
            if item is None:
                self.cancel()
                return
            if not self._annotation_layer_editable(item.layer_name):
                return
            try:
                offsets = _moved_leader_offsets(
                    item, (item.position_mm[0] + dx, item.position_mm[1] + dy)
                )
            except ValueError as exc:
                self._message(str(exc))
                return
            changed = replace(
                translate_frame(item, (dx, dy)),
                frame_id=uuid4().hex if action == "copy" else item.frame_id,
                leader_target_mm=item.leader_target_mm
                if item.leader_attachment is not None
                or item.leader_annotation_attachment is not None
                else (
                    None
                    if item.leader_target_mm is None
                    else (item.leader_target_mm[0] + dx, item.leader_target_mm[1] + dy)
                ),
                leader_offsets=offsets,
            )
            params = {"add_frames" if action == "copy" else "update_frames": [changed.to_mapping()]}
            selected = changed.frame_id
        else:
            datum = next((item for item in self.datums if item.datum_id == identity), None)
            if datum is None:
                self.cancel()
                return
            if not self._annotation_layer_editable(datum.layer_name):
                return
            try:
                candidate_datum = (
                    self._datum_from_arrow_target(datum, point)
                    if self.transform_arrow_base
                    else _translated_datum(datum, dx, dy)
                )
            except ValueError as exc:
                self._message(str(exc))
                return
            label = datum.label
            if action == "copy":
                label, accepted = QInputDialog.getText(
                    self.parent, "复制基准", _DATUM_NAME_PROMPT, text=self._next_datum_label()
                )
                if not accepted:
                    self.cancel()
                    return
                if not self._transform_subject_is_current() or not self._annotation_layer_editable(
                    datum.layer_name
                ):
                    return
            try:
                changed_datum = replace(
                    candidate_datum,
                    datum_id=uuid4().hex if action == "copy" else datum.datum_id,
                    label=label,
                )
                if action == "copy":
                    changed_datum = self.relayout_recorded_datum(changed_datum)
            except (KeyError, ValueError) as exc:
                self._message(str(exc))
                return
            params = {
                "add_datums" if action == "copy" else "update_datums": [changed_datum.to_mapping()]
            }
            selected = changed_datum.datum_id
        if self._commit(params):
            self.transform_action = ""
            self.transform_arrow_base = False
            self.transform_base = None
            self.transform_cursor = None
            self.transform_view_frame = None
            self.transform_subject = None
            self.selected_id = selected
            self.selected_ids = {selected}
            self.canvas.update()
            self._message("标注已复制。" if action == "copy" else "标注已移动。")
