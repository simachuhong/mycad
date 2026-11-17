# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive 2D sketch draft editor; it does not write the document."""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from functools import partial
from typing import cast, override
from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QCursor,
    QEnterEvent,
    QFont,
    QFontMetricsF,
    QHideEvent,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QShortcut,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from mycad.core.angular_dimension import angular_sector
from mycad.core.arc_tangent_snap import tangent_endpoints_to_circle, tangent_endpoints_to_line
from mycad.core.associative_array import (
    ArrayBasePoint,
    ArrayEntityRef,
    ArrayMember,
    AssociativeRectArray,
    array_counts_from_grip,
    array_spacing_from_grip,
    array_spacing_grip,
    erase_drawing_entities,
    move_associative_array_with_offsets,
    propagate_array_changes,
    resize_array,
    resolve_array_base_point,
    update_array_spacing,
    validate_array_cross_changes,
)
from mycad.core.circle_fillet import circle_fillet_notrim
from mycad.core.circle_ttr import TangentSource, circle_ttr
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    DraftConnectedEndpoint,
    DraftTangentPair,
    RectangleTransformEvidence,
    arc_tangent_endpoint,
    closed_polyline_rotation_index,
    closed_polyline_vertex_rotation_index,
    curve_endpoint_at_fillet,
    draft_tangent_reference,
    map_transformed_rectangle_segments,
    project_coplanar_entity,
    project_tangent_entity,
    rebind_retained_local_tangencies,
    tangent_endpoints_satisfied,
    tangent_entity_curve,
    unique_containing_polyline_arc,
    unique_extended_polyline_segment,
    unique_retained_tangent_fragment,
    unique_retained_tangent_polyline_arc,
    unique_unchanged_polyline_segment,
    validate_tangency_component,
)
from mycad.core.curve_corner import curve_corner
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.document import METADATA_KEYS
from mycad.core.drawing_quick_measure import (
    CurvePairMeasurement,
    LinePairMeasurement,
    QuickRadiusMeasurement,
    measure_circular_curves,
    measure_line_arc,
    measure_line_circle,
    measure_line_pair,
)
from mycad.core.drawing_quick_regions import CircularBoundary, LinearRegion, SampledMeasuredRegion
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.fillet_curves import tangent_on_curves, trim_arc_at_contact
from mycad.core.line_chamfer import (
    line_chamfer,
    polyline_chamfer,
    polyline_chamfer_between,
    polyline_chamfer_close,
    rectangle_chamfer,
)
from mycad.core.line_circle_fillet import line_circle_fillet_notrim, line_circle_fillet_trim
from mycad.core.line_fillet import line_corner, line_fillet, lines_parallel
from mycad.core.line_tangent import common_tangent_line, tangent_line_to_point
from mycad.core.polyline_curves import bulge_arc, polyline_curve_segments, polyline_sampled_points
from mycad.core.polyline_fillet import (
    chamfer_joined_paths,
    polyline_circular_fillet,
    polyline_fillet_notrim,
    polyline_fillet_trimmed_segments,
    polyline_line_fillet,
    polyline_polyline_fillet,
    polyline_segment_fillet,
)
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
    SketchSupportFace,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_edit import (
    NoTrimIntersection,
    break_entity_at_point,
    circular_array_entities,
    copy_entities,
    copy_scaled_entities,
    extend_curve_at,
    fence_intersections,
    linear_array_entities,
    mirror_entities,
    move_entities,
    move_sketch_handle,
    offset_entities,
    rectangular_array_displacement,
    rectangular_array_entities,
    rotate_entities,
    scale_entities,
    split_entity_at,
    trim_curve_at,
)
from mycad.core.sketch_layers import (
    DEFAULT_DIM_LAYER,
    SKETCH_LINETYPES,
    STANDARD_LINEWEIGHTS_MM,
    SketchLayer,
    SketchLayerTable,
    SketchLinetype,
    merge_layer_tables,
)
from mycad.core.sketch_projection import (
    SpatialBoundary,
    edit_curve_with_spatial_boundaries,
    plane_projection,
    projected_boundary_in_box,
)
from mycad.core.sketch_references import resolve_point_reference
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.dimension_colors import indexed_color
from mycad.ui.dimension_text import dimension_text
from mycad.ui.dimension_tools import DimensionTools
from mycad.ui.drawing2d_command_bar import Drawing2DCommandBar, parse_coordinate
from mycad.ui.drawing_clipboard import (
    DRAWING_CLIPBOARD_MIME,
    DRAWING_MIXED_CLIPBOARD_MIME,
    DRAWING_RASTER_GROUP_MIME,
    DRAWING_RASTER_MIME,
    decode_drawing_clipboard_data,
    decode_mixed_clipboard_data,
    decode_raster_group,
    encode_drawing_clipboard,
    encode_mixed_clipboard,
    encode_raster_group,
    instantiate_drawing_clipboard,
    raster_from_clipboard_image,
    reconcile_clipboard_styles,
)
from mycad.ui.drawing_offset import signed_offset_distance, through_offset_distance
from mycad.ui.layer_panel import DrawingLayerPanel
from mycad.ui.quick_select import QuickSelectDialog
from mycad.ui.sketch_dynamic_input import SketchDynamicInput
from mycad.ui.sketch_navigation import SketchNavigator
from mycad.ui.sketch_selection import entity_in_selection_box
from mycad.ui.workspace_console import DrawingMessageLabel, MessageLabel, drawing_message

_SNAP_RADIUS_PX = 12.0
_DOCUMENT_METADATA_LABELS = {
    "part_no": "编号",
    "revision": "修订",
    "material": "材料",
    "source": "来源",
    "part_name": "名称",
    "notes": "备注",
}
_SNAP_PRIORITY = {
    "端点": 0,
    "交点": 1,
    "垂足": 2,
    "切点": 3,
    "圆心": 4,
    "中点": 5,
    "中心": 6,
}


@dataclass(frozen=True)
class DimensionLayout:
    lines: tuple[tuple[QPointF, QPointF], ...]
    arrows: tuple[tuple[QPointF, QPointF], ...]
    label: QPointF
    extension_indices: tuple[int, ...] = ()
    extension_roles: tuple[int, ...] = ()
    arrow_roles: tuple[int, ...] = ()
    leader_indices: tuple[int, ...] = ()


def _rebind_draft_polyline_segment(
    original: PolylineEntity, updated: PolylineEntity, index: int | None
) -> int:
    """Match a directed segment exactly when a draft polyline changes topology."""
    if index is None:
        raise ValueError("相切段索引无效。")
    old_count = len(original.points_mm) if original.closed else len(original.points_mm) - 1
    new_count = len(updated.points_mm) if updated.closed else len(updated.points_mm) - 1
    if index >= old_count:
        raise ValueError("相切段索引无效。")
    rotated = closed_polyline_rotation_index(original, updated, index)
    if rotated is not None:
        return rotated
    vertex_index = closed_polyline_vertex_rotation_index(original, updated, index)
    if (
        (vertex_index is None or vertex_index == index)
        and original.closed == updated.closed
        and old_count == new_count
        and bool(original.bulges and original.bulges[index])
        == bool(updated.bulges and updated.bulges[index])
    ):
        return index
    matched = unique_unchanged_polyline_segment(original, updated, index)
    if matched is None:
        matched = unique_extended_polyline_segment(original, updated, index)
    if matched is None:
        matched = unique_containing_polyline_arc(original, updated, index)
    if matched is None:
        raise ValueError("无法唯一重绑定相切段。")
    return matched


def _rebind_draft_polyline_vertex(
    original: PolylineEntity, updated: PolylineEntity, index: int | None
) -> int:
    """Keep a uniquely unchanged vertex when a draft path changes topology."""
    if index is None or index >= len(original.points_mm):
        raise ValueError("多段线顶点索引无效。")
    rotated = closed_polyline_vertex_rotation_index(original, updated, index)
    if rotated is not None:
        return rotated
    if original.closed == updated.closed and len(original.points_mm) == len(updated.points_mm):
        return index
    point = original.points_mm[index]
    matches = [i for i, candidate in enumerate(updated.points_mm) if candidate == point]
    if original.points_mm.count(point) != 1 or len(matches) != 1:
        raise ValueError("无法唯一重绑定多段线顶点。")
    return matches[0]


def rebind_pending_saved_sources(
    previous: tuple[Sketch, ...],
    updated: tuple[Sketch, ...],
    pairs: tuple[DraftTangentPair, ...],
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
    *,
    previous_draft: Sketch | None = None,
    updated_draft: Sketch | None = None,
) -> tuple[DraftTangentPair, ...]:
    """Resolve unchanged saved polyline segments before mixed candidate validation."""
    result: list[DraftTangentPair] = []
    for source, draft in pairs:
        reference = draft_tangent_reference(source)
        old = [
            entity
            for sketch in previous
            for entity in sketch.entities
            if entity.entity_id == reference.entity_id
        ]
        new = [
            entity
            for sketch in updated
            for entity in sketch.entities
            if entity.entity_id == reference.entity_id
        ]
        evidence = next(
            (
                item
                for item in rectangle_transforms
                if item.reference.entity_id == reference.entity_id
            ),
            None,
        )
        if evidence is not None:
            if (
                len(old) != 1
                or len(new) != 1
                or not isinstance(old[0], RectangleEntity)
                or reference.index is None
                or reference.index >= 4
            ):
                raise ValueError("待提交矩形相切来源无效。")
            mapping = map_transformed_rectangle_segments(old[0], new[0], evidence.apply)
            index, reversed_direction = mapping[reference.index]
            reference = replace(reference, index=index)
            if isinstance(source, DraftConnectedEndpoint):
                endpoint = source.endpoint
                if reversed_direction:
                    endpoint = "end" if endpoint == "start" else "start"
                source = replace(source, reference=reference, endpoint=endpoint)
            else:
                source = reference
            result.append((source, draft))
            continue
        if (
            len(old) == len(new) == 1
            and isinstance(old[0], PolylineEntity)
            and isinstance(new[0], PolylineEntity)
        ):
            if (
                old[0] != new[0]
                and reference.index is not None
                and previous_draft is not None
                and updated_draft is not None
                and previous_draft.frame == updated_draft.frame
            ):
                target = draft_tangent_reference(draft)
                previous_targets = [
                    e for e in previous_draft.entities if e.entity_id == target.entity_id
                ]
                updated_targets = [
                    e for e in updated_draft.entities if e.entity_id == target.entity_id
                ]
                owners = [sketch for sketch in previous if old[0] in sketch.entities]
                revised_owners = [sketch for sketch in updated if new[0] in sketch.entities]
                if (
                    len(previous_targets)
                    == len(updated_targets)
                    == len(owners)
                    == len(revised_owners)
                    == 1
                    and owners[0].frame == revised_owners[0].frame
                ):
                    other = tangent_entity_curve(previous_targets[0], target.index)
                    if other == tangent_entity_curve(updated_targets[0], target.index):
                        projected = project_tangent_entity(
                            other, previous_draft.frame, owners[0].frame
                        )
                        old_ids = {entity.entity_id for entity in owners[0].entities}
                        candidates = tuple(
                            entity
                            for entity in revised_owners[0].entities
                            if isinstance(entity, PolylineEntity)
                            and (
                                entity.entity_id == old[0].entity_id
                                or entity.entity_id not in old_ids
                            )
                        )
                        retained = unique_retained_tangent_fragment(
                            old[0], candidates, reference.index, projected
                        )
                        if retained is not None:
                            reference = replace(reference, entity_id=retained[0], index=retained[1])
                            source = (
                                replace(source, reference=reference)
                                if isinstance(source, DraftConnectedEndpoint)
                                else reference
                            )
                            result.append((source, draft))
                            continue
            try:
                index = _rebind_draft_polyline_segment(old[0], new[0], reference.index)
            except ValueError:
                if previous_draft is None or updated_draft is None or reference.index is None:
                    continue
                target = draft_tangent_reference(draft)
                previous_targets = [
                    e for e in previous_draft.entities if e.entity_id == target.entity_id
                ]
                updated_targets = [
                    e for e in updated_draft.entities if e.entity_id == target.entity_id
                ]
                owners = [
                    sketch
                    for sketch in previous
                    if any(e.entity_id == reference.entity_id for e in sketch.entities)
                ]
                revised_owners = [
                    sketch
                    for sketch in updated
                    if any(e.entity_id == reference.entity_id for e in sketch.entities)
                ]
                if (
                    len(previous_targets) != 1
                    or len(updated_targets) != 1
                    or len(owners) != 1
                    or len(revised_owners) != 1
                    or previous_draft.frame != updated_draft.frame
                    or owners[0].frame != revised_owners[0].frame
                ):
                    continue
                other = tangent_entity_curve(previous_targets[0], target.index)
                if other != tangent_entity_curve(updated_targets[0], target.index):
                    continue
                projected = project_tangent_entity(other, previous_draft.frame, owners[0].frame)
                index = unique_retained_tangent_polyline_arc(
                    old[0], new[0], reference.index, projected
                )
                if index is None:
                    continue
            reference = replace(reference, index=index)
            source = (
                replace(source, reference=reference)
                if isinstance(source, DraftConnectedEndpoint)
                else reference
            )
        result.append((source, draft))
    return tuple(result)


@dataclass(frozen=True)
class MixedMoveState:
    transaction_id: str
    source_revision: int
    original_draft: Sketch
    original_saved: tuple[Sketch, ...]
    current_saved: tuple[Sketch, ...]
    base_background: tuple[tuple[SketchEntity, SketchLayer], ...]
    overlay_background: tuple[tuple[SketchEntity, SketchLayer], ...]
    original_cross_tangencies: tuple[DraftTangentPair, ...] = ()
    original_associative_arrays: tuple[AssociativeRectArray, ...] = ()
    step_rectangle_transforms: tuple[RectangleTransformEvidence, ...] = ()


@dataclass(frozen=True)
class SavedHandlePreview:
    original: tuple[Sketch, ...]
    solved: tuple[Sketch, ...]
    anchors: tuple[CrossSketchRef, ...]
    overlay: tuple[tuple[SketchEntity, SketchLayer], ...]
    mixed_state: MixedMoveState | None = None
    mixed_draft: Sketch | None = None
    mixed_before: MixedMoveState | None = None
    draft_before: Sketch | None = None
    pairs_before: tuple[DraftTangentPair, ...] = ()
    history_before: int = 0


@dataclass
class _SavedHandleDrag:
    token: str
    reference: SketchGeometryReference
    origin: Point2D
    target: Point2D
    revision: int
    inflight: Point2D | None = None
    preview_point: Point2D | None = None
    preview: SavedHandlePreview | None = None
    released: bool = False
    committing: bool = False
    expected_line: LineEntity | None = None


@dataclass
class _ArraySpacingDrag:
    token: str
    array: AssociativeRectArray
    axis: str
    anchor: Point2D
    origin: Point2D
    target: Point2D
    revision: int
    selected: frozenset[str]
    frame: WorkPlaneFrame
    sketches: tuple[Sketch, ...]
    arrays: tuple[AssociativeRectArray, ...]
    relations: tuple[CrossSketchTangency, ...]
    draft: _DraftState
    document_layers: SketchLayerTable | None
    spacing: float | None = None
    displacement: Point2D | None = None
    preview: tuple[tuple[SketchEntity, SketchLayer], ...] = ()
    preview_constraints: tuple[SketchConstraint, ...] = ()
    resized: AssociativeRectArray | None = None
    grip_offset: Point2D = (0.0, 0.0)
    member_cache: dict[tuple[ArrayEntityRef, int, int], ArrayMember] | None = None
    hidden_ids: frozenset[str] = frozenset()
    committing: bool = False


@dataclass(frozen=True)
class _DraftState:
    entities: tuple[SketchEntity, ...]
    constraints: tuple[SketchConstraint, ...]
    selected_ids: frozenset[str]
    layers: SketchLayerTable
    active_layer_name: str
    line_points: tuple[Point2D, ...] = ()
    history_position: int = 0
    mixed_move: MixedMoveState | None = None
    pending_cross_tangencies: tuple[DraftTangentPair, ...] = ()
    last_polar_entity_id: str | None = None
    pending_associative_arrays: tuple[AssociativeRectArray, ...] = ()


def _cross(first: Point2D, second: Point2D) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _distance(first: Point2D, second: Point2D) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _distance_to_segment(point: Point2D, start: Point2D, end: Point2D) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-20:
        return _distance(point, start)
    ratio = min(
        1.0,
        max(0.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator),
    )
    return _distance(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def _arc_sweep(start_angle: float, end_angle: float, direction: str) -> float:
    if direction == "顺时针":
        return -((start_angle - end_angle) % 360.0)
    return (end_angle - start_angle) % 360.0


def _angle_on_arc(angle: float, start_angle: float, sweep_angle: float) -> bool:
    if abs(sweep_angle) >= 360.0:
        return True
    offset = (angle - start_angle) % 360.0 if sweep_angle > 0.0 else (start_angle - angle) % 360.0
    return offset <= abs(sweep_angle) + 1e-9


def _distance_to_arc(point: Point2D, arc: ArcEntity) -> float:
    dx, dy = point[0] - arc.center_mm[0], point[1] - arc.center_mm[1]
    angle = math.degrees(math.atan2(dy, dx))
    if _angle_on_arc(angle, arc.start_angle_deg, arc.sweep_angle_deg):
        return abs(math.hypot(dx, dy) - arc.radius_mm)
    endpoints = (
        (
            arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(value)),
            arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(value)),
        )
        for value in (arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg)
    )
    return min(_distance(point, endpoint) for endpoint in endpoints)


def _whole_fillet_source_pairs(
    segments: tuple[LineEntity | ArcEntity, ...], arcs: tuple[ArcEntity, ...], *, closed: bool
) -> tuple[tuple[int, int] | None, ...]:
    """Find uniquely adjacent tangent sources using conservative finite-curve bounds."""
    max_radius = max((arc.radius_mm for arc in arcs), default=0.0)
    bounds: list[tuple[float, float, float, float]] = []
    for segment in segments:
        if isinstance(segment, LineEntity):
            x0, y0 = segment.start_mm
            x1, y1 = segment.end_mm
            extent = math.dist(segment.start_mm, segment.end_mm)
        else:
            x, y = segment.center_mm
            x0, x1 = x - segment.radius_mm, x + segment.radius_mm
            y0, y1 = y - segment.radius_mm, y + segment.radius_mm
            extent = segment.radius_mm
        magnitude = max(1.0, abs(x0), abs(x1), abs(y0), abs(y1))
        tolerance = max(1e-8, extent * 1e-9, max_radius * 1e-9, math.ulp(magnitude) * 16)
        bounds.append(
            (
                min(x0, x1) - tolerance,
                max(x0, x1) + tolerance,
                min(y0, y1) - tolerance,
                max(y0, y1) + tolerance,
            )
        )
    starts = sorted((bound[0], index) for index, bound in enumerate(bounds))
    ends = sorted((bound[1], index) for index, bound in enumerate(bounds))
    start_values = [value for value, _index in starts]
    end_values = [value for value, _index in ends]
    start_indices = [index for _value, index in starts]
    end_indices = [index for _value, index in ends]

    def candidates(point: Point2D) -> set[int]:
        x, y = point
        left = set(start_indices[: bisect_right(start_values, x)])
        right = set(end_indices[bisect_left(end_values, x) :])
        return {index for index in left & right if bounds[index][2] <= y <= bounds[index][3]}

    result: list[tuple[int, int] | None] = []
    count = len(segments)
    for arc in arcs:
        endpoints = tuple(
            (
                arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(angle)),
                arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(angle)),
            )
            for angle in (arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg)
        )
        first_candidates, second_candidates = candidates(endpoints[0]), candidates(endpoints[1])
        possible: set[tuple[int, int]] = set()
        for left, right in (
            (first_candidates, second_candidates),
            (second_candidates, first_candidates),
        ):
            for first_index in left:
                if not closed and first_index + 1 >= count:
                    continue
                second_index = (first_index + 1) % count
                if second_index in right:
                    possible.add((first_index, second_index))
        matches: list[tuple[int, int]] = []
        for first_index, second_index in sorted(possible):
            first, second = segments[first_index], segments[second_index]
            if not tangent_on_curves(first, arc) or not tangent_on_curves(second, arc):
                continue
            try:
                if arc_tangent_endpoint(arc, first) != arc_tangent_endpoint(arc, second):
                    matches.append((first_index, second_index))
            except ValueError:
                continue
        result.append(matches[0] if len(matches) == 1 else None)
    return tuple(result)


def _segment_circle_intersections(
    start: Point2D,
    end: Point2D,
    center: Point2D,
    radius: float,
) -> tuple[Point2D, ...]:
    delta = (end[0] - start[0], end[1] - start[1])
    relative = (start[0] - center[0], start[1] - center[1])
    a = delta[0] * delta[0] + delta[1] * delta[1]
    if a <= 1e-12:
        return ()
    b = 2.0 * (relative[0] * delta[0] + relative[1] * delta[1])
    c = relative[0] * relative[0] + relative[1] * relative[1] - radius * radius
    discriminant = b * b - 4.0 * a * c
    if discriminant < -1e-12:
        return ()
    root = math.sqrt(max(0.0, discriminant))
    parameters = (
        (-b / (2.0 * a),)
        if root <= 1e-12
        else (
            (-b - root) / (2.0 * a),
            (-b + root) / (2.0 * a),
        )
    )
    return tuple(
        (start[0] + delta[0] * parameter, start[1] + delta[1] * parameter)
        for parameter in parameters
        if -1e-12 <= parameter <= 1.0 + 1e-12
    )


def _circle_circle_intersections(
    first_center: Point2D,
    first_radius: float,
    second_center: Point2D,
    second_radius: float,
) -> tuple[Point2D, ...]:
    delta = (second_center[0] - first_center[0], second_center[1] - first_center[1])
    distance = math.hypot(*delta)
    if (
        distance <= 1e-12
        or distance > first_radius + second_radius + 1e-12
        or distance < abs(first_radius - second_radius) - 1e-12
    ):
        return ()
    along = (first_radius**2 - second_radius**2 + distance**2) / (2.0 * distance)
    height_squared = max(0.0, first_radius**2 - along**2)
    base = (
        first_center[0] + along * delta[0] / distance,
        first_center[1] + along * delta[1] / distance,
    )
    height = math.sqrt(height_squared)
    if height <= 1e-12:
        return (base,)
    perpendicular = (-delta[1] * height / distance, delta[0] * height / distance)
    return (
        (base[0] + perpendicular[0], base[1] + perpendicular[1]),
        (base[0] - perpendicular[0], base[1] - perpendicular[1]),
    )


class SketchLayerManagerDialog(QDialog):
    """Edit a draft sketch's layer table before the single Bus submission."""

    def __init__(
        self,
        layers: SketchLayerTable,
        *,
        used_names: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("草图图层")
        self.layer_table = layers
        self.used_names = used_names
        self._color_rgb = layers.layers[0].color_rgb
        root = QVBoxLayout(self)
        controls = QGridLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(tuple(layer.name for layer in layers.layers))
        self.name_label = QLabel()
        self.color_button = QPushButton()
        self.linetype_combo = QComboBox()
        self.linetype_combo.addItems(SKETCH_LINETYPES)
        self.lineweight_combo = QComboBox()
        for value in STANDARD_LINEWEIGHTS_MM:
            self.lineweight_combo.addItem(f"{value:g} mm", value)
        self.visible_check = QCheckBox("可见")
        self.visible_check.setChecked(True)
        self.locked_check = QCheckBox("锁定")
        self.color_button.clicked.connect(self._choose_color)
        self.layer_combo.currentTextChanged.connect(self._load_layer)
        controls.addWidget(QLabel("图层"), 0, 0)
        controls.addWidget(self.layer_combo, 0, 1, 1, 2)
        controls.addWidget(QLabel("名称"), 1, 0)
        controls.addWidget(self.name_label, 1, 1, 1, 2)
        controls.addWidget(QLabel("颜色"), 2, 0)
        controls.addWidget(self.color_button, 2, 1, 1, 2)
        controls.addWidget(QLabel("线型"), 3, 0)
        controls.addWidget(self.linetype_combo, 3, 1, 1, 2)
        controls.addWidget(QLabel("线宽"), 4, 0)
        controls.addWidget(self.lineweight_combo, 4, 1, 1, 2)
        controls.addWidget(self.visible_check, 5, 1)
        controls.addWidget(self.locked_check, 5, 2)
        root.addLayout(controls)

        actions = QHBoxLayout()
        self.add_button = QPushButton("新建图层")
        self.remove_button = QPushButton("删除图层")
        self.apply_button = QPushButton("应用属性")
        self.close_button = QPushButton("完成")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        self.status_label = QLabel()
        root.addWidget(self.status_label)
        self.add_button.clicked.connect(self._prompt_add_layer)
        self.remove_button.clicked.connect(self._remove_layer)
        self.apply_button.clicked.connect(self._apply_layer_properties)
        self.close_button.clicked.connect(self.accept)
        self._load_layer(self.layer_combo.currentText())

    @property
    def current_layer_name(self) -> str:
        """Return the selected draft layer name."""
        return self.layer_combo.currentText()

    def add_layer(self, name: str) -> bool:
        """Add one named layer, returning False with an explanation on invalid input."""
        try:
            self.layer_table = self.layer_table.add(SketchLayer(name))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self.layer_combo.addItem(name)
        self.layer_combo.setCurrentText(name)
        self.status_label.setText(f"已创建图层 {name}。")
        return True

    def set_color_rgb(self, color_rgb: tuple[int, int, int]) -> None:
        """Set the current layer color from a palette or test harness."""
        self._color_rgb = color_rgb
        self._sync_color_button()

    @override
    def accept(self) -> None:
        if not self._apply_layer_properties():
            return
        super().accept()

    def _prompt_add_layer(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建图层", "图层名称")
        if accepted:
            self.add_layer(name)

    def _remove_layer(self) -> None:
        name = self.layer_combo.currentText()
        try:
            self.layer_table = self.layer_table.remove(name, used_names=self.used_names)
        except (KeyError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        blocker = QSignalBlocker(self.layer_combo)
        self.layer_combo.clear()
        self.layer_combo.addItems(
            tuple(layer.name for layer in self.layer_table.layers if not layer.frozen)
        )
        self.layer_combo.setCurrentText("0")
        del blocker
        self._load_layer(self.layer_combo.currentText())
        self.status_label.setText(f"已删除图层 {name}。")

    def _choose_color(self) -> None:
        initial = QColor(*self._color_rgb)
        color = QColorDialog.getColor(initial, self, "选择图层颜色")
        if color.isValid():
            self.set_color_rgb((color.red(), color.green(), color.blue()))

    def _sync_color_button(self) -> None:
        red, green, blue = self._color_rgb
        self.color_button.setText(f"#{red:02X}{green:02X}{blue:02X}")
        self.color_button.setStyleSheet(
            f"background-color: rgb({red}, {green}, {blue}); color: white;"
        )

    def _load_layer(self, name: str) -> None:
        if not name:
            return
        layer = self.layer_table.get(name)
        self.name_label.setText(layer.name)
        self._color_rgb = layer.color_rgb
        self._sync_color_button()
        self.linetype_combo.setCurrentText(layer.linetype)
        weight_index = self.lineweight_combo.findData(layer.lineweight_mm)
        self.lineweight_combo.setCurrentIndex(weight_index)
        self.visible_check.setChecked(layer.visible)
        self.locked_check.setChecked(layer.locked)

    def _apply_layer_properties(self) -> bool:
        name = self.layer_combo.currentText()
        if not name:
            self.status_label.setText("至少需要一个有效图层。")
            return False
        lineweight = self.lineweight_combo.currentData()
        if not isinstance(lineweight, int | float) or isinstance(lineweight, bool):
            self.status_label.setText("请选择有效线宽。")
            return False
        try:
            layer = SketchLayer(
                name,
                self._color_rgb,
                cast("SketchLinetype", self.linetype_combo.currentText()),
                float(lineweight),
                self.visible_check.isChecked(),
                self.locked_check.isChecked(),
            )
            self.layer_table = self.layer_table.replace(layer)
        except (KeyError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText(f"已更新图层 {name} 的属性。")
        return True


class _CursorDimensionEntry(QLineEdit):
    next_requested = Signal()
    accept_requested = Signal()
    cancel_requested = Signal()

    @override
    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = cast("QKeyEvent", event)
            if key.key() == Qt.Key.Key_Tab:
                self.next_requested.emit()
                return True
        return super().event(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_requested.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class SketchCanvas(QWidget):
    """Grid canvas with local coordinates, cursor preview, pan/zoom and snaps."""

    changed = Signal()
    property_vertex_picked = Signal(str, int)
    point_accepted = Signal(object)
    history_recorded = Signal()
    deleting = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    cursor_changed = Signal(float, float, str)
    pointer_moved = Signal(QPoint)
    pointer_left = Signal()
    committed_move_requested = Signal(object, object)
    committed_mixed_copy_requested = Signal(object, object)
    committed_mixed_copy_array_requested = Signal(object, object, int)
    saved_mixed_copy_undo_requested = Signal(str, int, int)
    committed_mirror_copy_requested = Signal(object, object, object)
    committed_rotation_requested = Signal(object, object, object)
    committed_rotation_copy_requested = Signal(object, object, object)
    committed_scale_requested = Signal(object, object, object)
    committed_scale_copy_requested = Signal(object, object, object)
    committed_mirror_requested = Signal(object, object, object)
    committed_delete_requested = Signal(object)
    committed_dimension_delete_requested = Signal(object)
    committed_line_edit_requested = Signal(object, object, object)
    saved_line_edit_undo_requested = Signal(str, int, int)
    committed_drag_trim_requested = Signal(object, object, object, object, object)
    saved_handle_preview_requested = Signal(object, object, object, object)
    saved_handle_commit_requested = Signal(object, object, object)
    saved_handle_cancelled = Signal()
    array_spacing_commit_requested = Signal(object, object, object, object, object)
    array_count_commit_requested = Signal(object, object, object, object)
    array_move_commit_requested = Signal(object, object, object, object)
    source_revision_invalidated = Signal()
    visible_snap_entities_changed = Signal()
    copy_mode_changed = Signal(int)
    offset_default_distance_changed = Signal(float)
    offset_gap_type_changed = Signal(int)
    corner_trim_changed = Signal(bool)
    chamfer_method_changed = Signal(bool)
    line_edge_mode_changed = Signal(bool)
    line_standard_mode_changed = Signal(bool)
    line_projection_mode_changed = Signal(int)
    rotation_reference_mode_changed = Signal(bool)
    mirror_keep_source_mode_changed = Signal(bool)
    object_tangency_selection_ready = Signal()
    object_tangency_options_requested = Signal()

    @property
    def message(self) -> str:
        return self._message

    @message.setter
    def message(self, text: str) -> None:
        self._message = drawing_message(text) if self.select_committed_entities else text

    def __init__(
        self, parent: QWidget | None = None, *, select_committed_entities: bool = False
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 60)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.entities: list[SketchEntity] = []
        self.background_entities: tuple[tuple[SketchEntity, SketchLayer], ...] = ()
        self.spatial_boundaries: tuple[SpatialBoundary, ...] = ()
        self._spatial_paths_cache: tuple[tuple[str, tuple[Point2D, ...]], ...] | None = None
        self._spatial_boundary_unsupported = False
        self._spatial_target_frame = WorkPlaneFrame.xy()
        self.mixed_move: MixedMoveState | None = None
        self._invalid_mixed_transactions: set[str] = set()
        self.select_committed_entities = select_committed_entities
        self.active_property_vertex: tuple[str, int] | None = None
        self.crosshair_style = "short"
        self._drawing_dark_theme = False
        self.constraint_markers_visible = True
        self._crosshair_position: QPoint | None = None
        if select_committed_entities:
            self.setCursor(Qt.CursorShape.BlankCursor)
        self.layer_table = SketchLayerTable()
        self.active_layer_name = "0"
        self.document_layer_table: SketchLayerTable | None = None
        self.drawing_dimension_styles: DimensionStyleTable | None = None
        self.preserve_document_layers = False
        self._undo_history: list[_DraftState] = []
        self._redo_history: list[_DraftState] = []
        self.history_position = 0
        self._next_history_position = 0
        self.constraints: list[SketchConstraint] = []
        self.dimension_preview: Sketch | None = None
        self.dimension_linked_previews: tuple[Sketch, ...] = ()
        self.dimension_linked_sources: tuple[Sketch, ...] = ()
        self.dimension_error_entity_ids: frozenset[str] = frozenset()
        self.dimension_error_constraint_ids: frozenset[str] = frozenset()
        self.dimension_candidate: SketchConstraint | None = None
        self.dimension_references: tuple[SketchGeometryReference, ...] = ()
        self.background_constraints: tuple[SketchConstraint, ...] = ()
        self.background_dimension_basis: dict[str, tuple[Point2D, Point2D, float]] = {}
        self.background_entity_basis: dict[str, tuple[Point2D, Point2D, float]] = {}
        self._snap_candidates_cache: tuple[tuple[Point2D, str], ...] | None = None
        self._snapping_enabled = True
        self._object_tracking_enabled = False
        self._object_tracking_use_polar = False
        self._object_tracking_shift_to_acquire = False
        self._object_tracking_points: list[Point2D] = []
        self._object_tracking_paths: tuple[tuple[Point2D, Point2D], ...] = ()
        self._object_tracking_vector: tuple[Point2D, Point2D] | None = None
        self._object_tracking_hover_point: Point2D | None = None
        self._object_tracking_history_position: int | None = None
        self._object_tracking_source_revision: int | None = None
        self._grid_snapping_enabled = False
        self._polar_snap_enabled = False
        self._polar_snap_spacing = 0.0
        self.grid_visible = True
        self._orthogonal_enabled = False
        self._polar_tracking_enabled = False
        self._polar_angle_increment_deg = 90.0
        self._polar_relative = False
        self._last_polar_entity_id: str | None = None
        self._polar_additional_angles: tuple[float, ...] = ()
        self._polar_tracking_direction: Point2D | None = None
        self._auto_inference_enabled = True
        self.tool = "直线"
        self.continuous_lines = False
        self.ucs_plane = "XY"
        self.construction = False
        self.closed_polyline = False
        self.polygon_sides = 6
        self.polygon_circumscribed = False
        self.arc_direction = "逆时针"
        self.chamfer_first_distance = 0.0
        self.chamfer_second_distance = 0.0
        self.chamfer_distance_first = 0.0
        self.chamfer_angle_length = 0.0
        self.chamfer_angle: float | None = None
        self.chamfer_last_angle = 45.0
        self.persist_chamfer_values: Callable[[tuple[float, float, float, float]], None] | None = (
            None
        )
        self._corner_trim = True
        self.chamfer_polyline_pending = False
        self._chamfer_first: (
            tuple[LineEntity | PolylineEntity | RectangleEntity, Point2D] | None
        ) = None
        self._chamfer_segment: int | None = None
        self.circle_fillet_radius = 1.0
        self.persist_fillet_radius: Callable[[float], None] | None = None
        self.circle_fillet_trim_pending = False
        self.circle_fillet_polyline_pending = False
        self.circle_fillet_multiple = False
        self._fillet_candidate_pending = False
        self._fillet_pending_cross_candidate: tuple[DraftTangentPair, ...] = ()
        self._fillet_undo_floor = 0
        self.circle_fillet_radius_pending = False
        self._fillet_radius_anchor: Point2D | None = None
        self._circle_fillet_first: (
            tuple[CircleEntity | ArcEntity | LineEntity | PolylineEntity | RectangleEntity, Point2D]
            | None
        ) = None
        self._circle_fillet_segment: int | None = None
        self._fillet_source_revision: int | None = None
        self._corner_drag_points: list[Point2D] = []
        self._corner_drag_shift = False
        self._corner_drag_revision: int | None = None
        self._clipboard_paste: Sketch | None = None
        self._clipboard_styles: DimensionStyleTable | None = None
        self._clipboard_raster: DrawingRaster | None = None
        self._clipboard_rasters: tuple[DrawingRaster, ...] = ()
        self._clipboard_mixed_images: tuple[DrawingRaster, ...] = ()
        self._clipboard_mixed_revision: int | None = None
        self.drawing_rasters: tuple[DrawingRaster, ...] = ()
        self._raster_image_cache: dict[str, QImage] = {}
        self.commit_clipboard_raster: Callable[[DrawingRaster], None] | None = None
        self.commit_mixed_clipboard: (
            Callable[[Sketch, tuple[DrawingRaster, ...], DimensionStyleTable | None], None] | None
        ) = None
        self.commit_mixed_draft_transform: (
            Callable[[tuple[SketchEntity, ...], tuple[DrawingRaster, ...], str], str | None] | None
        ) = None
        self.commit_raster_edit: Callable[[str, DrawingRaster], None] | None = None
        self.commit_raster_batch: Callable[[str, tuple[DrawingRaster, ...]], None] | None = None
        self.selected_raster_ids: set[str] = set()
        self._selection_original_raster_ids: frozenset[str] = frozenset()
        self._raster_transform_preview: DrawingRaster | None = None
        self._raster_transform_previews: tuple[DrawingRaster, ...] = ()
        self._clipboard_anchor: Point2D = (0.0, 0.0)
        self._suppress_clipboard_context = False
        self.import_clipboard_layers: (
            Callable[[SketchLayerTable, DimensionStyleTable | None], Callable[[bool], None]] | None
        ) = None
        self.pending_cross_tangencies: list[DraftTangentPair] = []
        self._pending_tangency_removal_notices: dict[int, int] = {}
        self.pending_associative_arrays: list[AssociativeRectArray] = []
        self.arc_mode_prompt_active = False
        self.arc_creation_mode = "center"
        self.arc_ttr_active = False
        self._arc_ttr_sources: list[
            tuple[
                LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
                SketchGeometryReference,
                Point2D,
            ]
        ] = []
        self._arc_ttr_revision: int | None = None
        self.arc_ttr_last_radius: float | None = None
        self.circle_ttr_active = False
        self.circle_ttr_last_radius: float | None = None
        self._circle_ttr_sources: list[tuple[TangentSource, Point2D]] = []
        self.line_tangent_active = False
        self._line_tangent_require_two = False
        self._line_tangent_awaiting = False
        self._line_tangent_sources: list[tuple[CircleEntity | ArcEntity, Point2D]] = []
        self._line_tangent_revision: int | None = None
        self._line_tangent_anchor: Point2D | None = None
        self._circle_ttr_revision: int | None = None
        self._scale = 5.0
        self._pan = QPointF(0.0, 0.0)
        self._previous_views: list[tuple[float, float, float]] = []
        self._pan_start_view: tuple[float, float, float] | None = None
        self._first: Point2D | None = None
        self._points: list[Point2D] = []
        self._polyline_bulges: list[float] = []
        self.polyline_arc_mode = False
        self._polyline_arc_middle: Point2D | None = None
        self._polyline_arc_second_pending = False
        self.polyline_arc_stage = ""
        self._polyline_arc_radius: float | None = None
        self._polyline_arc_angle: float | None = None
        self._polyline_arc_center: Point2D | None = None
        self._cursor: Point2D | None = None
        self._area_preview_points: tuple[Point2D, ...] = ()
        self._area_preview_cursor: Point2D | None = None
        self._area_preview_subtract = False
        self.quick_measure_preview: (
            LinePairMeasurement | QuickRadiusMeasurement | CurvePairMeasurement | None
        ) = None
        self.quick_measure_regions: tuple[LinearRegion | SampledMeasuredRegion, ...] = ()
        self._zoom_window_first: Point2D | None = None
        self._zoom_window_cursor: QPointF | None = None
        self._last_placement_raw: Point2D | None = None
        self._last_pointer_shift = False
        self.dynamic_point_resolver: Callable[[Point2D, Point2D], Point2D] | None = None
        self.dynamic_key_handler: Callable[[QKeyEvent], bool] | None = None
        self.dynamic_click_guard: Callable[[], bool] | None = None
        self.dynamic_submit_handler: Callable[[], bool] | None = None
        self._snap_kind = ""
        self._hovered_line_edit_entity_id: str | None = None
        self._break_at_point_target: str | None = None
        self._line_edit_boundary_ids: frozenset[str] | None = None
        self._line_edit_boundary_sources: tuple[SketchEntity, ...] = ()
        self._line_edit_spatial_sources: tuple[SpatialBoundary, ...] = ()
        self._line_edit_selection_spatial: tuple[SpatialBoundary, ...] = ()
        self._line_edit_boundary_revision: int | None = None
        self._line_edit_selecting_boundaries = False
        self._line_edit_boundary_invalidated = False
        self._line_edit_selection_revision: int | None = None
        self._line_edit_selection_history = 0
        self._line_edit_preview_original: SketchEntity | None = None
        self._line_edit_preview_result: tuple[SketchEntity, ...] = ()
        self.selected_entity_ids: set[str] = set()
        self.selected_segment_indices: dict[str, int] = {}
        self._selected_segment_sources: dict[str, SketchEntity] = {}
        self.selected_constraint_ids: set[str] = set()
        self._hovered_entity_id: str | None = None
        self._selection_anchor: QPointF | None = None
        self._selection_corner = QPointF()
        self._selection_waiting_click = False
        self._selection_original: frozenset[str] = frozenset()
        self._selection_original_constraints: frozenset[str] = frozenset()
        self._selection_modifiers = Qt.KeyboardModifier.NoModifier
        self._panning = False
        self._last_mouse = QPoint()
        self._drag_solver: (
            Callable[
                [
                    tuple[SketchEntity, ...],
                    tuple[SketchConstraint, ...],
                    SketchGeometryReference,
                    Point2D,
                ],
                SketchConstraintSolveResult,
            ]
            | None
        ) = None
        self._drag_reference: SketchGeometryReference | None = None
        self._drag_entity_id: str | None = None
        self._drag_origin: Point2D | None = None
        self._drag_original_entities: tuple[SketchEntity, ...] | None = None
        self._drag_original_constraints: tuple[SketchConstraint, ...] | None = None
        self._drag_original_selection: frozenset[str] | None = None
        self._drag_last_entities: tuple[SketchEntity, ...] | None = None
        self._drag_last_constraints: tuple[SketchConstraint, ...] | None = None
        self._drag_branch_warning = ""
        self._saved_handle_drag: _SavedHandleDrag | None = None
        self._array_spacing_drag: _ArraySpacingDrag | None = None
        self.mixed_handle_drag_enabled = False
        self._copy_array_awaiting_count = False
        self._copy_array_count: int | None = None
        self._copy_array_fit = False
        self._copy_array_ids: frozenset[str] = frozenset()
        self._copy_array_sources: tuple[SketchEntity, ...] = ()
        self._copy_array_image_sources: tuple[DrawingRaster, ...] = ()
        self._copy_array_history = 0
        self._copy_array_preview_point: Point2D | None = None
        self._copy_array_candidate: tuple[SketchEntity, ...] = ()
        self._mirror_ask_erase = False
        self._mirror_previous_keep_source: bool | None = None
        self._mirror_axis_end: Point2D | None = None
        self._mirror_candidate: tuple[SketchEntity, ...] = ()
        self._mirror_selected_sources: tuple[SketchEntity, ...] = ()
        self._mirror_selected_ids: frozenset[str] = frozenset()
        self._mirror_history_position = 0
        self._offset_distance: float | None = None
        self._offset_through = False
        self._offset_distance_anchor: Point2D | None = None
        self.offset_erase_source = False
        self.offset_erase_pending = False
        self.offset_layer_current = False
        self.offset_layer_pending = False
        self.offset_default_distance = -1.0
        self.offset_gap_type = 0
        self._offset_multiple = False
        self._offset_undo_positions: list[int] = []
        self._offset_pending_result_id: str | None = None
        self._offset_target: SketchEntity | None = None
        self._offset_signed_distance: float | None = None
        self._transform_operation: str | None = None
        self._transform_base: Point2D | None = None
        self._transform_selecting = False
        self._transform_reference_mode = False
        self._transform_reference: Point2D | None = None
        self._transform_reference_end: Point2D | None = None
        self._transform_reference_angle: float | None = None
        self._rotation_target_points_active = False
        self._rotation_target_first: Point2D | None = None
        self._rotation_copy = False
        self._scale_copy = False
        self._scale_reference_active = False
        self._scale_reference_length: float | None = None
        self._scale_reference_first: Point2D | None = None
        self._scale_target_points_active = False
        self._scale_target_first: Point2D | None = None
        self.rotation_default_angle = 0.0
        self.scale_default_factor = 1.0
        self._reference_previous_mode: bool | None = None
        self._transform_keep_source = True
        self._transform_angle_text = ""
        self._transform_preview: tuple[SketchEntity, ...] = ()
        self._transform_source_revision: int | None = None
        self._copy_placements: list[tuple[Point2D, int, int]] = []
        self._mixed_copy_placements: list[tuple[Point2D, str, int]] = []
        self._mixed_draft_copy_ids: set[str] = set()
        self._mixed_copy_pending_point: Point2D | None = None
        self._mixed_copy_started = False
        self.copy_mode = 0
        self._copy_repeat = True
        self._trim_drag_start: Point2D | None = None
        self._trim_fence_active = False
        self._line_crossing_active = False
        self._line_crossing_original_ids: set[str] = set()
        self._line_edit_erasing = False
        self._line_erase_history = 0
        self._line_erase_revision: int | None = None
        self.line_edit_extend_boundaries = False
        self.line_edit_standard_mode = False
        self.line_edit_projection_mode = 1
        self._trim_fence_points: list[Point2D] = []
        self._trim_fence_seen: set[str] = set()
        self._line_edit_undo_actions: list[tuple[str, int, str, int]] = []
        self._trim_drag_last: Point2D | None = None
        self._trim_drag_original_entities: tuple[SketchEntity, ...] | None = None
        self._trim_drag_original_constraints: tuple[SketchConstraint, ...] | None = None
        self._trim_drag_original_selection: frozenset[str] | None = None
        self._trim_drag_candidate_entities: tuple[SketchEntity, ...] | None = None
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error: str | None = None
        self._trim_drag_moved = False
        self._trim_drag_saved_target = False
        self._trim_drag_blocked = False
        self._trim_drag_original_background: tuple[tuple[SketchEntity, SketchLayer], ...] | None = (
            None
        )
        self._trim_drag_saved_events: list[tuple[str, tuple[SketchEntity, ...]]] = []
        self.source_revision_provider: Callable[[], int] | None = None
        self.associative_arrays_provider: Callable[[], tuple[AssociativeRectArray, ...]] | None = (
            None
        )
        self.associative_sketches_provider: Callable[[], tuple[Sketch, ...]] | None = None
        self.draft_sketches_provider: Callable[[], tuple[Sketch, ...]] | None = None
        self.associative_tangencies_provider: (
            Callable[[], tuple[CrossSketchTangency, ...]] | None
        ) = None
        self.source_context_revision: int | None = None
        self._object_tangency_selection_revision: int | None = None
        self._trim_drag_source_revision: int | None = None
        self._trim_drag_spatial_snapshot: tuple[SpatialBoundary, ...] | None = None
        self._trim_drag_spatial_frame: WorkPlaneFrame | None = None
        self._trim_drag_spatial_unsupported = False
        self.message = "选择绘图工具；单击画布放置几何。"
        self.point_accepted.connect(self._clear_tracking_after_point)

    @property
    def chamfer_trim(self) -> bool:
        return self._corner_trim

    @chamfer_trim.setter
    def chamfer_trim(self, value: bool) -> None:
        self.set_corner_trim(value)

    @property
    def circle_fillet_trim(self) -> bool:
        return self._corner_trim

    @circle_fillet_trim.setter
    def circle_fillet_trim(self, value: bool) -> None:
        self.set_corner_trim(value)

    def set_corner_trim(self, value: bool, *, notify: bool = True) -> None:
        if self._corner_trim != value:
            self._corner_trim = value
            if notify:
                self.corner_trim_changed.emit(value)

    def set_chamfer_method(self, angle_method: bool, *, notify: bool = True) -> None:
        changed = (self.chamfer_angle is not None) != angle_method
        self.chamfer_angle = self.chamfer_last_angle if angle_method else None
        self.chamfer_first_distance = (
            self.chamfer_angle_length if angle_method else self.chamfer_distance_first
        )
        if changed and notify:
            self.chamfer_method_changed.emit(angle_method)

    def local_to_screen(self, point: Point2D) -> QPoint:
        """Convert a local millimetre point to canvas pixels for UI automation."""
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        return QPoint(
            round(center_x + point[0] * self._scale),
            round(center_y - point[1] * self._scale),
        )

    def screen_to_local(self, point: QPointF) -> Point2D:
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        return ((point.x() - center_x) / self._scale, (center_y - point.y()) / self._scale)

    def _preview_screen_point(self, point: Point2D) -> QPointF:
        """Clamp off-screen preview coordinates before passing them to Qt."""
        x = self.width() / 2 + self._pan.x() + point[0] * self._scale
        y = self.height() / 2 + self._pan.y() - point[1] * self._scale
        return QPointF(max(-1e6, min(1e6, x)), max(-1e6, min(1e6, y)))

    def _clip_area_preview(self, points: tuple[Point2D, ...]) -> tuple[Point2D, ...]:
        """Clip a preview boundary in drawing space before converting to screen points."""
        left, top = self.screen_to_local(QPointF(-20, -20))
        right, bottom = self.screen_to_local(QPointF(self.width() + 20, self.height() + 20))
        vertices = list(points)
        for axis, bound, lower in (
            (0, left, True),
            (0, right, False),
            (1, bottom, True),
            (1, top, False),
        ):
            if not vertices:
                break
            clipped: list[Point2D] = []

            def inside(
                point: Point2D, *, axis: int = axis, bound: float = bound, lower: bool = lower
            ) -> bool:
                return point[axis] >= bound if lower else point[axis] <= bound

            def intersection(
                a: Point2D, b: Point2D, *, axis: int = axis, bound: float = bound
            ) -> Point2D:
                other = 1 - axis
                if max(abs(a[axis]), abs(b[axis]), abs(a[other]), abs(b[other])) > 1e12:
                    with localcontext() as context:
                        context.prec = 340
                        da, db, edge = (
                            Decimal(str(a[axis])),
                            Decimal(str(b[axis])),
                            Decimal(str(bound)),
                        )
                        fraction = (edge - da) / (db - da)
                        value = float(
                            Decimal(str(a[other])) * (1 - fraction)
                            + Decimal(str(b[other])) * fraction
                        )
                else:
                    fraction = (bound - a[axis]) / (b[axis] - a[axis])
                    value = a[other] * (1 - fraction) + b[other] * fraction
                return (bound, value) if axis == 0 else (value, bound)

            previous = vertices[-1]
            for current in vertices:
                if inside(current) != inside(previous):
                    clipped.append(intersection(previous, current))
                if inside(current):
                    clipped.append(current)
                previous = current
            vertices = clipped
        return tuple(vertices)

    def pan_view_between(self, start: Point2D, end: Point2D) -> bool:
        """Pan the view by a displacement expressed in drawing coordinates."""
        x = self._pan.x() + (end[0] - start[0]) * self._scale
        y = self._pan.y() + (start[1] - end[1]) * self._scale
        if not math.isfinite(x) or not math.isfinite(y) or max(abs(x), abs(y)) > 1e9:
            return False
        previous = self._view_state()
        self._pan = QPointF(x, y)
        self._remember_changed_view(previous)
        self.update()
        return True

    def zoom_view_factor(self, factor: float) -> None:
        """Zoom around the centre of the drawing canvas."""
        old_scale = self._scale
        previous = self._view_state()
        self._scale = min(60.0, max(1e-6, old_scale * factor))
        self._pan *= self._scale / old_scale
        self._remember_changed_view(previous)
        self.update()

    def zoom_view_window(self, first: Point2D, second: Point2D) -> bool:
        """Fit a nondegenerate drawing rectangle to the current canvas."""
        width = abs(second[0] - first[0])
        height = abs(second[1] - first[1])
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            return False
        scale = min(self.width() / width, self.height() / height, 60.0)
        center_x = first[0] / 2 + second[0] / 2
        center_y = first[1] / 2 + second[1] / 2
        x, y = -center_x * scale, center_y * scale
        if scale < 1e-6 or not all(math.isfinite(value) for value in (scale, x, y)):
            return False
        if max(abs(x), abs(y)) > 1e9:
            return False
        previous = self._view_state()
        self._scale = scale
        self._pan = QPointF(x, y)
        self._remember_changed_view(previous)
        self.update()
        return True

    def _view_state(self) -> tuple[float, float, float]:
        return self._scale, self._pan.x(), self._pan.y()

    def _remember_changed_view(self, previous: tuple[float, float, float]) -> None:
        if previous != self._view_state():
            self._previous_views.append(previous)
            del self._previous_views[:-10]

    def restore_previous_view(self) -> bool:
        """Restore the preceding view without changing document history."""
        if not self._previous_views:
            return False
        self._scale, x, y = self._previous_views.pop()
        self._pan = QPointF(x, y)
        self.update()
        return True

    @property
    def has_pending_geometry(self) -> bool:
        if self.tool == "直线" and self.continuous_lines and len(self._points) >= 2:
            return False  # The next segment is only a rubber band, not unfinished geometry.
        return self._first is not None or bool(self._points)

    @property
    def can_close_chain(self) -> bool:
        return self.tool in {"直线", "多段线"} and len(self._points) >= 3

    def end_line_chain(self) -> None:
        self._first = None
        self._points.clear()
        self._snap_kind = ""
        self.message = "连续直线已结束；已完成线段保留。指定新起点继续绘图。"
        self.changed.emit()
        self.update()

    def close_chain(self) -> None:
        if not self.can_close_chain:
            self.message = "闭合至少需要三个不同的点。"
            self.changed.emit()
            return
        if self.tool == "多段线":
            self.finish_polyline(close=True)
        else:
            self._accept_point(self._points[0], exact_point=True)

    def fit_view(self) -> None:
        previous = self._view_state()
        points: list[Point2D] = []
        for entity in (*self.entities, *(e for e, _layer in self.background_entities)):
            layer = (
                self._layer(entity)
                if entity in self.entities
                else next(
                    layer
                    for e, layer in self.background_entities
                    if e.entity_id == entity.entity_id
                )
            )
            if layer.frozen:
                continue
            if isinstance(entity, CircleEntity | ArcEntity):
                x, y = entity.center_mm
                radius = entity.radius_mm
                points.extend(((x - radius, y - radius), (x + radius, y + radius)))
            else:
                points.extend(point for _reference, point in self._entity_handles(entity))
        dimension_entities = self.dimension_entities()
        for constraint in self.dimension_constraints():
            if constraint.kind not in DIMENSION_KINDS or self.annotation_layer(constraint).frozen:
                continue
            layout = self.dimension_layout(constraint, dimension_entities)
            if layout is not None:
                points.append(self.screen_to_local(layout.label))
                points.extend(
                    self.screen_to_local(point) for line in layout.lines for point in line
                )
        if not points:
            self._scale = 5.0
            self._pan = QPointF()
        else:
            left = min(point[0] for point in points)
            right = max(point[0] for point in points)
            bottom = min(point[1] for point in points)
            top = max(point[1] for point in points)
            self._scale = min(
                60.0,
                max(
                    1e-6,
                    min(
                        max(1, self.width() - 80) / max(1.0, right - left),
                        max(1, self.height() - 80) / max(1.0, top - bottom),
                    ),
                ),
            )
            self._pan = QPointF(-(left + right) * self._scale / 2, (bottom + top) * self._scale / 2)
        self._remember_changed_view(previous)
        self.update()

    def copy_view_from(self, other: SketchCanvas) -> None:
        self._scale = other._scale
        self._pan = QPointF(other._pan)
        self._previous_views = list(other._previous_views)
        self.update()

    def set_source_context_revision(self, revision: int) -> None:
        if self.source_context_revision != revision:
            self._clear_line_edit_preview()
            self._hovered_line_edit_entity_id = None
        self.source_context_revision = revision

    def spatial_boundary_paths(self) -> tuple[tuple[str, tuple[Point2D, ...]], ...]:
        """Return display-only projections, preserving the source entities and frames."""
        if self._spatial_paths_cache is not None:
            return self._spatial_paths_cache
        paths: list[tuple[str, tuple[Point2D, ...]]] = []
        for source in self.spatial_boundaries:
            entity = source.entity
            if isinstance(entity, LineEntity):
                points = (entity.start_mm, entity.end_mm)
            elif isinstance(entity, PolylineEntity):
                points = polyline_sampled_points(entity)
            elif isinstance(entity, RectangleEntity):
                first, opposite = entity.first_corner_mm, entity.opposite_corner_mm
                points = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]), first)
            else:
                start = entity.start_angle_deg if isinstance(entity, ArcEntity) else 0.0
                sweep = entity.sweep_angle_deg if isinstance(entity, ArcEntity) else 360.0
                points = tuple(
                    (
                        entity.center_mm[0]
                        + entity.radius_mm * math.cos(math.radians(start + sweep * index / 64)),
                        entity.center_mm[1]
                        + entity.radius_mm * math.sin(math.radians(start + sweep * index / 64)),
                    )
                    for index in range(65)
                )
            projection = plane_projection(
                source.frame, self._spatial_target_frame, self._spatial_target_frame.normal
            )
            paths.append((entity.entity_id, tuple(projection.map_point(point) for point in points)))
        self._spatial_paths_cache = tuple(paths)
        return self._spatial_paths_cache

    def _hit_spatial_boundary_at(self, point: Point2D) -> str | None:
        candidates = sorted(
            (
                min(
                    _distance_to_segment(point, first, second)
                    for first, second in zip(path, path[1:], strict=False)
                ),
                identity,
            )
            for identity, path in self.spatial_boundary_paths()
        )
        if not candidates or candidates[0][0] > _SNAP_RADIUS_PX / self._scale:
            return None
        if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-9:
            return None
        return candidates[0][1]

    def set_background_sketches(self, sketches: tuple[Sketch, ...], frame: WorkPlaneFrame) -> None:
        """Project coplanar sources into the active drawing plane."""
        previous_visible = self.visible_snap_entities()
        background: list[tuple[SketchEntity, SketchLayer]] = []
        constraints: list[SketchConstraint] = []
        dimension_basis: dict[str, tuple[Point2D, Point2D, float]] = {}
        entity_basis: dict[str, tuple[Point2D, Point2D, float]] = {}
        spatial: list[SpatialBoundary] = []
        unsupported = False
        for sketch in sketches:
            source = sketch.frame
            delta = tuple(a - b for a, b in zip(source.origin_mm, frame.origin_mm, strict=True))
            cross = (
                source.normal[1] * frame.normal[2] - source.normal[2] * frame.normal[1],
                source.normal[2] * frame.normal[0] - source.normal[0] * frame.normal[2],
                source.normal[0] * frame.normal[1] - source.normal[1] * frame.normal[0],
            )
            coplanar = (
                math.hypot(*cross) <= 1e-9
                and abs(sum(a * b for a, b in zip(delta, frame.normal, strict=True))) <= 1e-7
            )
            aligned = source.u_axis == frame.u_axis and source.v_axis == frame.v_axis
            if not self.select_committed_entities and not aligned:
                coplanar = False
            if not coplanar:
                if self.select_committed_entities:
                    table = (
                        merge_layer_tables(sketch.layers, self.document_layer_table)
                        if self.document_layer_table is not None
                        else sketch.layers
                    )
                    for entity in sketch.entities:
                        if not table.get(entity.layer_name).displayed or entity.construction:
                            continue
                        if isinstance(
                            entity,
                            LineEntity
                            | CircleEntity
                            | ArcEntity
                            | PolylineEntity
                            | RectangleEntity,
                        ):
                            spatial.append(SpatialBoundary(sketch.sketch_id, source, entity))
                        elif isinstance(entity, SplineEntity):
                            unsupported = True
                continue
            shift = (
                sum(a * b for a, b in zip(delta, frame.u_axis, strict=True)),
                sum(a * b for a, b in zip(delta, frame.v_axis, strict=True)),
            )
            if not sketch.entities:
                continue
            entities = (
                move_entities(
                    sketch.entities,
                    tuple(entity.entity_id for entity in sketch.entities),
                    shift,
                    preserve_rectangle_order=True,
                )
                if aligned
                else tuple(
                    project_coplanar_entity(entity, source, frame) for entity in sketch.entities
                )
            )
            table = (
                merge_layer_tables(sketch.layers, self.document_layer_table)
                if self.document_layer_table is not None
                else sketch.layers
            )
            background.extend((entity, table.get(entity.layer_name)) for entity in entities)
            if not aligned:
                u = (
                    sum(a * b for a, b in zip(source.u_axis, frame.u_axis, strict=True)),
                    sum(a * b for a, b in zip(source.u_axis, frame.v_axis, strict=True)),
                )
                v = (
                    sum(a * b for a, b in zip(source.v_axis, frame.u_axis, strict=True)),
                    sum(a * b for a, b in zip(source.v_axis, frame.v_axis, strict=True)),
                )
                orientation = sum(a * b for a, b in zip(source.normal, frame.normal, strict=True))
                entity_basis.update((e.entity_id, (u, v, orientation)) for e in sketch.entities)
                dimension_basis.update(
                    (c.constraint_id, (u, v, orientation))
                    for c in sketch.constraints
                    if c.kind in DIMENSION_KINDS
                )
            constraints.extend(
                replace(
                    c,
                    position_mm=None
                    if c.position_mm is None
                    else (c.position_mm[0] + shift[0], c.position_mm[1] + shift[1])
                    if aligned
                    else frame.world_to_local(source.local_to_world(c.position_mm)),
                    text_position_mm=None
                    if c.text_position_mm is None
                    else (c.text_position_mm[0] + shift[0], c.text_position_mm[1] + shift[1])
                    if aligned
                    else frame.world_to_local(source.local_to_world(c.text_position_mm)),
                )
                for c in sketch.constraints
                if aligned or c.kind in DIMENSION_KINDS
            )
        if self.spatial_boundaries != tuple(spatial) or self._spatial_target_frame != frame:
            self._clear_line_edit_preview()
            self._spatial_paths_cache = None
        self.spatial_boundaries = tuple(spatial)
        self._spatial_boundary_unsupported = unsupported
        self._spatial_target_frame = frame
        self.background_constraints = tuple(constraints)
        self.background_dimension_basis = dimension_basis
        self.background_entity_basis = entity_basis
        projected = tuple(background)
        mixed = self.mixed_move
        if mixed is not None:
            if (
                projected == mixed.base_background
                and mixed.transaction_id not in self._invalid_mixed_transactions
            ):
                projected = mixed.overlay_background
            else:
                self._invalid_mixed_transactions.add(mixed.transaction_id)
                self.message = "来源或工作平面已变化；暂存变换不能提交，请撤销或取消。"
        if self.background_entities != projected:
            self._cancel_selection_box()
            self._clear_line_edit_preview()
            self._hovered_line_edit_entity_id = None
        self.background_entities = projected
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        self._snap_candidates_cache = None
        if previous_visible != self.visible_snap_entities():
            self.visible_snap_entities_changed.emit()
        self.update()

    def visible_snap_entities(self) -> tuple[SketchEntity, ...]:
        return (
            *self._visible_entities(),
            *(entity for entity, layer in self.background_entities if layer.displayed),
        )

    def set_layer_table(
        self, layers: SketchLayerTable, active_layer_name: str, *, record_history: bool = False
    ) -> None:
        """Replace the draft layer table and current drawing layer."""
        previous_layers = self.layer_table
        self._cancel_active_edit_gesture()
        self._fillet_candidate_pending = False
        self._fillet_pending_cross_candidate = ()
        layers.get(active_layer_name)
        if record_history and layers != self.layer_table:
            self._record_undo()
        self.layer_table = layers
        self.active_layer_name = active_layer_name
        visible_layers = {layer.name.casefold() for layer in layers.layers if layer.displayed}
        self.selected_raster_ids.intersection_update(
            image.image_id
            for image in self.drawing_rasters
            if image.layer_name.casefold() in visible_layers
        )
        self._snap_candidates_cache = None
        if previous_layers != layers:
            self.visible_snap_entities_changed.emit()
        self.update()

    def dimension_entities(self) -> dict[str, SketchEntity]:
        entities = {
            e.entity_id: e for e in (*self.entities, *(e for e, _layer in self.background_entities))
        }
        if self.dimension_preview is not None:
            entities.update((e.entity_id, e) for e in self.dimension_preview.entities)
        if self._array_spacing_drag is not None:
            entities.update((e.entity_id, e) for e, _layer in self._array_spacing_drag.preview)
        return entities

    def dimension_constraints(self) -> tuple[SketchConstraint, ...]:
        retained = (
            {
                c.constraint_id
                for sketch in self.mixed_move.current_saved
                for c in sketch.constraints
            }
            if self.mixed_move is not None and self.mixed_move_is_valid
            else None
        )
        constraints = {
            c.constraint_id: c
            for c in self.background_constraints
            if retained is None or c.constraint_id in retained
        }
        constraints.update((c.constraint_id, c) for c in self.constraints)
        if self.dimension_preview is not None:
            constraints.update((c.constraint_id, c) for c in self.dimension_preview.constraints)
        if self._array_spacing_drag is not None:
            constraints.update(
                (c.constraint_id, c) for c in self._array_spacing_drag.preview_constraints
            )
        return tuple(constraints.values())

    def annotation_layer(self, constraint: SketchConstraint) -> SketchLayer:
        entities = self.dimension_entities()
        first = entities.get(constraint.references[0].entity_id)
        name = constraint.layer_name or (first.layer_name if first is not None else "0")
        if self.document_layer_table is not None:
            return self.document_layer_table.get(name)
        if constraint in self.background_constraints:
            for entity, layer in self.background_entities:
                if (
                    first is not None
                    and entity.entity_id == first.entity_id
                    and constraint.layer_name is None
                ):
                    return layer
        try:
            return self.layer_table.get(name)
        except KeyError:
            return DEFAULT_DIM_LAYER if name.casefold() == "dim" else SketchLayer(name)

    def visible_dimensions(self) -> tuple[SketchConstraint, ...]:
        return tuple(
            c
            for c in self.dimension_constraints()
            if c.kind in DIMENSION_KINDS and self.annotation_layer(c).displayed
        )

    def set_drag_solver(
        self,
        solver: Callable[
            [
                tuple[SketchEntity, ...],
                tuple[SketchConstraint, ...],
                SketchGeometryReference,
                Point2D,
            ],
            SketchConstraintSolveResult,
        ],
    ) -> None:
        """Install the optional solver used to preview constrained handle drags."""
        self._drag_solver = solver

    def _layer(self, entity: SketchEntity) -> SketchLayer:
        return self.layer_table.get(entity.layer_name)

    def _visible_entities(self) -> tuple[SketchEntity, ...]:
        return tuple(entity for entity in self.entities if self._layer(entity).displayed)

    def selectable_entities(self) -> tuple[SketchEntity, ...]:
        """Include committed drawing geometry while keeping part references separate."""
        return (
            *self._visible_entities(),
            *(
                entity
                for entity, layer in self.background_entities
                if self.select_committed_entities and layer.displayed
            ),
        )

    def _selected_committed_entities(self) -> bool:
        return self.select_committed_entities and any(
            entity.entity_id in self.selected_entity_ids
            for entity, _layer in self.background_entities
        )

    def _merge_hidden_entities(
        self,
        original: tuple[SketchEntity, ...],
        updated_visible: tuple[SketchEntity, ...],
    ) -> tuple[SketchEntity, ...]:
        """Reinsert hidden geometry at its nearest surviving visible successor."""
        updated_ids = {entity.entity_id for entity in updated_visible}
        hidden_before: dict[str, list[SketchEntity]] = {}
        trailing_hidden: list[SketchEntity] = []
        for index, entity in enumerate(original):
            if self._layer(entity).displayed:
                continue
            successor = next(
                (
                    candidate.entity_id
                    for candidate in original[index + 1 :]
                    if self._layer(candidate).displayed and candidate.entity_id in updated_ids
                ),
                None,
            )
            if successor is None:
                trailing_hidden.append(entity)
            else:
                hidden_before.setdefault(successor, []).append(entity)
        merged: list[SketchEntity] = []
        for entity in updated_visible:
            merged.extend(hidden_before.pop(entity.entity_id, ()))
            merged.append(entity)
        for remaining in hidden_before.values():
            merged.extend(remaining)
        merged.extend(trailing_hidden)
        return tuple(merged)

    def _edit_draft_with_boundaries(
        self,
        original: tuple[SketchEntity, ...],
        mode: str,
        point: Point2D,
        target_id: str,
        *,
        allow_endpoint_intersections: bool = False,
    ) -> tuple[SketchEntity, ...]:
        result = self._edit_visible_geometry(
            original,
            mode,
            point,
            target_id,
            allow_endpoint_intersections=allow_endpoint_intersections,
        )
        boundary_ids = {
            entity.entity_id
            for entity, layer in self.background_entities
            if self.select_committed_entities and layer.displayed
        }
        draft_result = tuple(entity for entity in result if entity.entity_id not in boundary_ids)
        return self._merge_hidden_entities(original, draft_result)

    def set_line_edit_edge_mode(self, extend: bool) -> None:
        changed = self.line_edit_extend_boundaries != extend
        self.line_edit_extend_boundaries = extend
        self._clear_line_edit_preview()
        if changed:
            self.line_edge_mode_changed.emit(extend)
        self.changed.emit()
        self.update()

    def set_line_edit_standard_mode(self, standard: bool) -> None:
        changed = self.line_edit_standard_mode != standard
        self.line_edit_standard_mode = standard
        if changed:
            self.line_standard_mode_changed.emit(standard)
        self.changed.emit()

    def set_line_edit_projection_mode(self, mode: int) -> None:
        if mode not in (0, 1, 2):
            raise ValueError("投影模式必须为 0、1 或 2。")
        changed = self.line_edit_projection_mode != mode
        self.line_edit_projection_mode = mode
        self._clear_line_edit_preview()
        if changed:
            self.line_projection_mode_changed.emit(mode)
        self.changed.emit()
        self.update()

    def set_line_edit_boundaries(self, identities: frozenset[str] | None) -> None:
        """Restrict line-edit boundaries, or use all visible entities when None."""
        if identities is not None:
            available = [entity.entity_id for entity in self.selectable_entities()]
            available.extend(source.entity.entity_id for source in self.spatial_boundaries)
            if any(available.count(identity) != 1 for identity in identities):
                raise ValueError("边界对象不存在或身份不唯一。")
        self._line_edit_boundary_ids = identities
        self._line_edit_boundary_invalidated = False
        self._line_edit_boundary_revision = (
            self.source_revision_provider()
            if identities is not None and self.source_revision_provider is not None
            else None
        )
        self._line_edit_boundary_sources = tuple(
            entity
            for entity in self.selectable_entities()
            if identities is not None and entity.entity_id in identities
        )
        self._line_edit_spatial_sources = tuple(
            source
            for source in self.spatial_boundaries
            if identities is not None and source.entity.entity_id in identities
        )
        self._clear_line_edit_preview()
        self.update()

    def acknowledge_line_edit_revision(self, previous: int, current: int) -> None:
        """Retain unchanged explicit boundaries after this editor's successful commit."""
        if (
            self._line_edit_boundary_ids is None
            or self._line_edit_boundary_revision != previous
            or current != previous + 1
            or self.source_revision_provider is None
            or self.source_revision_provider() != current
        ):
            return
        available = self.selectable_entities()
        if all(source in available for source in self._line_edit_boundary_sources) and all(
            source in self.spatial_boundaries for source in self._line_edit_spatial_sources
        ):
            self._line_edit_boundary_revision = current

    @property
    def selecting_line_edit_boundaries(self) -> bool:
        return self._line_edit_selecting_boundaries

    def begin_line_edit_boundary_selection(self) -> None:
        if self.tool not in {"修剪", "延伸"}:
            return
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            self._line_edit_boundary_invalidated = True
            self.source_revision_invalidated.emit()
            self.message = "边界来源已变化；请重新选择边界。"
            self.changed.emit()
            return
        self._cancel_active_edit_gesture()
        self.set_line_edit_boundaries(None)
        self.selected_entity_ids.clear()
        self._line_edit_selecting_boundaries = True
        self._line_edit_selection_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self._line_edit_selection_history = self.history_position
        self._line_edit_selection_spatial = self.spatial_boundaries
        self.message = "选择边界；Enter / 右键确认，直接确认使用全部边界，Esc 取消。"
        self.changed.emit()
        self.update()

    def _finish_line_edit_boundary_selection(self) -> None:
        if (
            self.history_position != self._line_edit_selection_history
            or (self.spatial_boundaries != self._line_edit_selection_spatial)
            or (
                self._line_edit_selection_revision is not None
                and self.source_revision_provider is not None
                and self.source_revision_provider() != self._line_edit_selection_revision
            )
        ):
            self._line_edit_selecting_boundaries = False
            self._line_edit_boundary_invalidated = True
            self.selected_entity_ids.clear()
            self.message = "边界来源已变化；请重新选择边界。"
            self.changed.emit()
            self.update()
            return
        identities = frozenset(self.selected_entity_ids)
        try:
            self.set_line_edit_boundaries(identities or None)
        except ValueError as exc:
            self.selected_entity_ids.clear()
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return
        self._line_edit_selecting_boundaries = False
        self.selected_entity_ids.clear()
        self.message = "边界已设置；选择修剪或延伸目标。"
        self.changed.emit()
        self.update()

    def _edit_visible_geometry(
        self,
        original: tuple[SketchEntity, ...],
        mode: str,
        point: Point2D,
        target_id: str,
        *,
        allow_endpoint_intersections: bool = False,
    ) -> tuple[SketchEntity, ...]:
        if mode in {"修剪", "延伸"} and self._line_edit_boundary_invalidated:
            raise ValueError("边界来源已变化；请重新选择边界。")
        visible = tuple(entity for entity in original if self._layer(entity).displayed)
        boundaries = tuple(
            entity
            for entity, layer in self.background_entities
            if self.select_committed_entities and layer.displayed
        )
        identities = [entity.entity_id for entity in original]
        if self.select_committed_entities:
            identities.extend(entity.entity_id for entity, _layer in self.background_entities)
        if len(identities) != len(set(identities)):
            raise ValueError("图元身份不唯一；无法安全确定边界，草稿未修改。")
        combined = (*visible, *boundaries)
        boundary_ids = self._line_edit_boundary_ids if mode in {"修剪", "延伸"} else None
        scoped = (
            combined
            if boundary_ids is None
            else tuple(
                entity
                for entity in combined
                if entity.entity_id == target_id or entity.entity_id in boundary_ids
            )
        )
        if boundary_ids is not None and (
            not boundary_ids.issubset(
                entity.entity_id
                for entity in (
                    *combined,
                    *(source.entity for source in self.spatial_boundaries),
                )
            )
            or any(source not in combined for source in self._line_edit_boundary_sources)
            or any(
                source not in self.spatial_boundaries for source in self._line_edit_spatial_sources
            )
            or (
                self._line_edit_boundary_revision is not None
                and self.source_revision_provider is not None
                and self.source_revision_provider() != self._line_edit_boundary_revision
            )
        ):
            raise ValueError("边界对象已变化；请重新选择。")
        tolerance = _SNAP_RADIUS_PX / self._scale
        spatial = tuple(
            source
            for source in self.spatial_boundaries
            if boundary_ids is None or source.entity.entity_id in boundary_ids
        )
        if mode in {"修剪", "延伸"} and boundary_ids is None and self._spatial_boundary_unsupported:
            raise ValueError("异面样条边界尚不支持，草图未修改。")
        if mode == "修剪":
            try:
                if spatial:
                    result = edit_curve_with_spatial_boundaries(
                        scoped,
                        target_id,
                        point,
                        self._spatial_target_frame,
                        spatial,
                        None
                        if self.line_edit_projection_mode == 0
                        else self._spatial_target_frame.normal,
                        operation="trim",
                        hit_tolerance_mm=tolerance,
                        allow_endpoint_intersections=allow_endpoint_intersections,
                        extend_boundaries=self.line_edit_extend_boundaries,
                    )
                else:
                    result = trim_curve_at(
                        scoped,
                        point,
                        hit_tolerance_mm=tolerance,
                        target_entity_id=target_id,
                        allow_endpoint_intersections=allow_endpoint_intersections,
                        extend_boundaries=self.line_edit_extend_boundaries,
                    )
            except NoTrimIntersection:
                if not self.select_committed_entities or self.line_edit_standard_mode:
                    raise
                target = next(entity for entity in scoped if entity.entity_id == target_id)
                if isinstance(target, PolylineEntity) and not target.closed:
                    result = trim_curve_at(
                        scoped,
                        point,
                        hit_tolerance_mm=tolerance,
                        target_entity_id=target_id,
                        remove_unintersected_polyline_segment=True,
                    )
                else:
                    result = tuple(entity for entity in scoped if entity.entity_id != target_id)
        elif mode == "延伸":
            if spatial:
                result = edit_curve_with_spatial_boundaries(
                    scoped,
                    target_id,
                    point,
                    self._spatial_target_frame,
                    spatial,
                    None
                    if self.line_edit_projection_mode == 0
                    else self._spatial_target_frame.normal,
                    operation="extend",
                    hit_tolerance_mm=tolerance,
                    extend_boundaries=self.line_edit_extend_boundaries,
                )
            else:
                result = extend_curve_at(
                    scoped,
                    point,
                    hit_tolerance_mm=tolerance,
                    target_entity_id=target_id,
                    extend_boundaries=self.line_edit_extend_boundaries,
                )
        else:
            result = split_entity_at(
                scoped, point, hit_tolerance_mm=tolerance, target_entity_id=target_id
            )
        if boundary_ids is None:
            return result
        target_index = next(
            index for index, entity in enumerate(scoped) if entity.entity_id == target_id
        )
        suffix_length = len(scoped) - target_index - 1
        replacements = result[target_index : len(result) - suffix_length if suffix_length else None]
        expanded: list[SketchEntity] = []
        for entity in combined:
            if entity.entity_id == target_id:
                expanded.extend(replacements)
            else:
                expanded.append(entity)
        return tuple(expanded)

    def _current_layer_can_draw(self) -> bool:
        layer = self.layer_table.get(self.active_layer_name)
        return layer.displayed and not layer.locked

    def set_tool(self, tool: str) -> bool:
        if self._array_spacing_drag is not None and self._array_spacing_drag.committing:
            self.message = "阵列修改正在提交；完成后可撤销。"
            self.changed.emit()
            return False
        if self.has_pending_geometry:
            self.message = "当前图元未完成；先完成图元或按 Esc 清除。"
            self.changed.emit()
            self.update()
            return False
        preselected = tuple(self.selected_entity_ids) if tool == "单点打断" else ()
        self._object_tangency_selection_revision = None
        self._break_at_point_target = preselected[0] if len(preselected) == 1 else None
        self._last_placement_raw = None
        self.clear_object_tracking()
        self._cancel_active_edit_gesture()
        self._line_edit_undo_actions.clear()
        self._fillet_candidate_pending = False
        self._fillet_pending_cross_candidate = ()
        self.set_line_edit_boundaries(None)
        if tool != "选择元素":
            self.selected_entity_ids.clear()
            self.selected_constraint_ids.clear()
            self.selected_raster_ids.clear()
            self.clear_selected_tangent_segments()
        self.tool = tool
        self.arc_mode_prompt_active = tool == "圆弧"
        if tool == "圆弧":
            self.arc_creation_mode = "three_point" if self.select_committed_entities else "center"
        if tool in {"二维圆角", "二维倒角"}:
            self._fillet_undo_floor = len(self._undo_history)
            self.circle_fillet_multiple = False
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()
        self._hovered_entity_id = None
        self._first = None
        self._points.clear()
        self._polyline_bulges.clear()
        self.polyline_arc_mode = False
        self._polyline_arc_middle = None
        self._polyline_arc_second_pending = False
        self.polyline_arc_stage = ""
        self._polyline_arc_radius = None
        self._polyline_arc_angle = None
        self._polyline_arc_center = None
        chamfer_settings = (
            f"距离 {self.chamfer_first_distance:g}、角度 {self.chamfer_angle:g}°，命令栏 A 设置"
            if self.chamfer_angle is not None
            else f"距离 {self.chamfer_first_distance:g}/{self.chamfer_second_distance:g}，命令栏 D 设置"
        )
        self.message = (
            "单点打断：指定打断点。"
            if tool == "单点打断" and self._break_at_point_target
            else "单点打断：选择直线、圆弧或开放多段线。"
            if tool == "单点打断"
            else f"二维倒角：选择边或拖过两边；{chamfer_settings}，P 整体、M 连续。"
            if tool == "二维倒角"
            else f"二维圆角：选择对象或拖过两边；半径 {self.circle_fillet_radius:g}，R 设置、P 整体、M 连续（圆不修剪）。"
            if tool == "二维圆角"
            else "修剪：单击删除曲线段，或按住左键拖过多个区段；Shift+单击临时延伸，Esc 取消。"
            if tool == "修剪"
            else "延伸：选择端点延至最近有效交点；Shift+单击临时修剪。"
            if tool == "延伸"
            else "分割：单击目标直线、矩形边或多段线路径，靠近交点区段；选中区间的首段保留原身份。"
            if tool == "分割"
            else "选择：点选或在空白处拖拽/两次单击框选；左→右全包含，右→左包含或相交；Ctrl 加选，Shift 减选；Delete 删除所选对象。"
            if tool == "选择元素"
            else (
                "圆弧：指定起点、经过点和终点；输入 C 圆心模式或 T 两对象与半径。"
                if self.arc_creation_mode == "three_point"
                else "圆弧：指定圆心、起点和终点。"
            )
            if tool == "圆弧"
            else f"{tool}：单击画布按提示放置点。"
        )
        if self.select_committed_entities and tool in {"修剪", "延伸"}:
            self.message += " 命令栏 C 可指定边界。"
        if self.isVisible() and tool in {"修剪", "延伸", "分割"}:
            position = self.mapFromGlobal(QCursor.pos())
            if self.rect().contains(position):
                self._cursor = self.screen_to_local(QPointF(position))
                self._hovered_line_edit_entity_id = (
                    self._extend_target_at(self._cursor)
                    if tool == "延伸"
                    else self._trim_target_at(self._cursor, lines_only=tool == "分割")
                )
                self._refresh_line_edit_preview(None if tool == "分割" else tool)
        if tool in {"修剪", "延伸"} and self.line_edit_standard_mode:
            self.begin_line_edit_boundary_selection()
        self.update()
        self.changed.emit()
        return True

    def replace_draft_entities(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        select_new: bool = False,
        new_relations: tuple[SketchConstraint, ...] = (),
        preserve_unchanged_polyline_references: bool = False,
        new_layer_table: SketchLayerTable | None = None,
        remove_dependent_constraints: bool = False,
        remove_constraint_ids: frozenset[str] = frozenset(),
        allow_satisfied_tangency: bool = False,
    ) -> bool:
        """Replace draft geometry and keep selection identities valid."""
        removed_ids = {entity.entity_id for entity in self.entities} - {
            entity.entity_id for entity in entities
        }
        removed_constraints = {
            constraint.constraint_id
            for constraint in self.constraints
            if remove_dependent_constraints
            and (
                constraint.constraint_id in self.selected_constraint_ids
                or constraint.constraint_id in remove_constraint_ids
                or any(ref.entity_id in removed_ids for ref in constraint.references)
            )
        }
        if tuple(self.entities) == entities and not removed_constraints:
            return False
        try:
            rebound = (
                self._rebind_unchanged_user_polyline_references(entities)
                if preserve_unchanged_polyline_references
                else None
            )
            if rebound is None:
                self._reject_user_constraint_reference_edits(
                    entities,
                    proven_rebound_ids=frozenset(removed_constraints),
                    allow_satisfied_tangency=allow_satisfied_tangency,
                )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return False
        original_entities = tuple(self.entities)
        original_by_id = {entity.entity_id: entity for entity in original_entities}
        metadata_only = (
            len(original_by_id) == len(original_entities) == len(entities)
            and all(
                (before := original_by_id.get(entity.entity_id)) is not None
                and type(before) is type(entity)
                and replace(entity, layer_name=before.layer_name, construction=before.construction)
                == before
                for entity in entities
            )
            and len({entity.entity_id for entity in entities}) == len(entities)
        )
        self._record_undo()
        if removed_constraints:
            self.constraints = [
                constraint
                for constraint in self.constraints
                if constraint.constraint_id not in removed_constraints
            ]
            self.selected_constraint_ids.difference_update(removed_constraints)
        if new_layer_table is not None:
            self.layer_table = new_layer_table
        if self.tool == "二维倒角":
            self._line_edit_undo_actions.append(("draft", self.history_position, "", 0))
        previous_ids = {entity.entity_id for entity in original_entities}
        self.entities = list(entities)
        if rebound is not None:
            self.constraints = list(rebound)
        if metadata_only:
            removed_relations = 0
        else:
            self._prune_pending_cross_tangencies(original_entities=original_entities)
            removed_relations = self._preserve_satisfied_relations(
                entities, original_entities=original_entities
            )
        self.constraints.extend(new_relations)
        if removed_relations:
            self.message = f"几何已变更；移除了 {removed_relations} 条失效或需重新确认的自动关系。"
        available_ids = {entity.entity_id for entity in self.entities}
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        if select_new:
            self.selected_entity_ids.update(available_ids - previous_ids)
        self._snap_candidates_cache = None
        self.changed.emit()
        self.update()
        return True

    def replace_draft_entities_atomically(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        remove_dependent_constraints: bool = False,
        remove_constraint_ids: frozenset[str] = frozenset(),
        preserve_pending_tangencies: bool = False,
        allow_satisfied_tangency: bool = False,
    ) -> bool:
        """Restore draft and local history if a linked document update cannot finish."""
        state = self._draft_state()
        undo, redo = list(self._undo_history), list(self._redo_history)
        next_position = self._next_history_position
        line_actions = list(self._line_edit_undo_actions)
        selected_constraints = set(self.selected_constraint_ids)
        applied = False
        try:
            applied = self.replace_draft_entities(
                entities,
                remove_dependent_constraints=remove_dependent_constraints,
                remove_constraint_ids=remove_constraint_ids,
                allow_satisfied_tangency=allow_satisfied_tangency,
            )
            if applied and preserve_pending_tangencies:
                applied = tuple(self.pending_cross_tangencies) == state.pending_cross_tangencies
        finally:
            if not applied:
                self._undo_history, self._redo_history = undo, redo
                self._next_history_position = next_position
                self._line_edit_undo_actions = line_actions
                self._restore_draft_state(state)
                self.selected_constraint_ids = selected_constraints
                self.changed.emit()
                self.update()
        return applied

    def apply_mixed_move_atomically(
        self,
        state: MixedMoveState,
        entities: tuple[SketchEntity, ...],
        *,
        constraints: tuple[SketchConstraint, ...] | None = None,
        pending_arrays: tuple[AssociativeRectArray, ...] | None = None,
        pending_pairs: tuple[DraftTangentPair, ...] | None = None,
    ) -> None:
        """Apply a staged move or restore the draft and its history on failure."""
        before = self._draft_state()
        undo, redo = list(self._undo_history), list(self._redo_history)
        position = self._next_history_position
        notices = dict(self._pending_tangency_removal_notices)
        actions = list(self._line_edit_undo_actions)
        try:
            self.apply_mixed_move(
                state,
                entities,
                constraints=constraints,
                pending_arrays=pending_arrays,
                pending_pairs=pending_pairs,
            )
            if pending_pairs is not None and tuple(self.pending_cross_tangencies) != pending_pairs:
                raise ValueError("无法保留暂存相切关系。")
        except Exception:
            self._undo_history, self._redo_history = undo, redo
            self._next_history_position = position
            self._pending_tangency_removal_notices = notices
            self._line_edit_undo_actions = actions
            self._restore_draft_state(before)
            self.changed.emit()
            self.update()
            raise

    def apply_mixed_move(
        self,
        state: MixedMoveState,
        entities: tuple[SketchEntity, ...],
        *,
        erase: bool = False,
        constraints: tuple[SketchConstraint, ...] | None = None,
        pending_arrays: tuple[AssociativeRectArray, ...] | None = None,
        pending_pairs: tuple[DraftTangentPair, ...] | None = None,
    ) -> None:
        """Record one validated provisional move across draft and committed geometry."""
        original = tuple(self.entities)
        previous_saved = (
            self.mixed_move.current_saved if self.mixed_move is not None else state.original_saved
        )
        if not erase and constraints is None:
            self._reject_user_constraint_reference_edits(entities)
        self._record_undo()
        if pending_pairs is not None:
            removed = max(0, len(self.pending_cross_tangencies) - len(pending_pairs))
            if removed:
                position = self.history_position
                self._pending_tangency_removal_notices[position] = (
                    self._pending_tangency_removal_notices.get(position, 0) + removed
                )
            self.pending_cross_tangencies = list(pending_pairs)
        if pending_arrays is not None:
            self.pending_associative_arrays = list(pending_arrays)
        if self.tool in {"修剪", "延伸", "二维倒角"}:
            self._line_edit_undo_actions.append(("draft", self.history_position, "", 0))
        self.entities = list(entities)
        if erase:
            available = {entity.entity_id for entity in entities}
            self.constraints = [
                constraint
                for constraint in self.constraints
                if all(ref.entity_id in available for ref in constraint.references)
            ]
        else:
            self._preserve_satisfied_relations(entities, original_entities=original)
        if constraints is not None:
            self.constraints = list(constraints)
        self.selected_entity_ids.intersection_update(
            {entity.entity_id for entity in entities}
            | {entity.entity_id for entity, _ in state.overlay_background}
        )
        self.mixed_move = state
        self.background_entities = state.overlay_background
        if self._transform_operation == "offset" and self._offset_pending_result_id is not None:
            result = next(
                (
                    entity
                    for entity in entities
                    if entity.entity_id == self._offset_pending_result_id
                ),
                None,
            )
            self._offset_pending_result_id = None
            if result is not None:
                self._offset_undo_positions.append(self.history_position)
                if self._offset_multiple:
                    self._offset_target = result
                    self.selected_entity_ids = {result.entity_id}
        self._prune_pending_cross_tangencies(
            original_entities=original,
            original_sources=tuple(
                entity
                for sketch in previous_saved
                if pending_pairs is None
                for entity in sketch.entities
            ),
        )
        self._snap_candidates_cache = None
        self.message = "混合变换已暂存；完成草图时统一提交，可撤销。"
        self.finish_fillet_candidate(success=True)
        self.changed.emit()
        self.update()

    def mixed_move_timeline(self) -> tuple[tuple[tuple[Sketch, ...], Sketch], ...]:
        """Return retained provisional states in the order they must be replayed."""
        result: list[tuple[tuple[Sketch, ...], Sketch]] = []
        for saved, draft, _pending in self.mixed_move_timeline_with_tangencies():
            item = (saved, draft)
            if not result or result[-1] != item:
                result.append(item)
        return tuple(result)

    def mixed_move_timeline_with_tangencies(
        self,
    ) -> tuple[tuple[tuple[Sketch, ...], Sketch, tuple[DraftTangentPair, ...]], ...]:
        """Include inferred cross-sketch pairs at each retained draft state."""
        return tuple(
            (saved, draft, pairs)
            for saved, draft, pairs, _arrays in self.mixed_move_timeline_with_arrays()
        )

    def mixed_move_timeline_with_arrays(
        self,
    ) -> tuple[
        tuple[
            tuple[Sketch, ...],
            Sketch,
            tuple[DraftTangentPair, ...],
            tuple[AssociativeRectArray, ...],
        ],
        ...,
    ]:
        """Retain array additions at the draft history step that created them."""
        return tuple(
            (saved, draft, pairs, arrays)
            for saved, draft, pairs, arrays, _transforms in self.mixed_move_timeline_with_transforms()
        )

    def mixed_move_timeline_with_transforms(
        self,
    ) -> tuple[
        tuple[
            tuple[Sketch, ...],
            Sketch,
            tuple[DraftTangentPair, ...],
            tuple[AssociativeRectArray, ...],
            tuple[RectangleTransformEvidence, ...],
        ],
        ...,
    ]:
        """Retain each operation's transform proof alongside its draft state."""
        mixed = self.mixed_move
        if mixed is None:
            return ()
        states = (*self._undo_history, self._draft_state())
        result: list[
            tuple[
                tuple[Sketch, ...],
                Sketch,
                tuple[DraftTangentPair, ...],
                tuple[AssociativeRectArray, ...],
                tuple[RectangleTransformEvidence, ...],
            ]
        ] = []
        previous_sketches = (*mixed.original_saved, mixed.original_draft)
        previous_pending: MixedMoveState | None = None
        for state in states:
            pending = state.mixed_move
            if pending is None or pending.transaction_id != mixed.transaction_id:
                continue
            draft = replace(
                mixed.original_draft,
                entities=state.entities,
                constraints=state.constraints,
                layers=state.layers,
            )
            old_entities = {
                (sketch.sketch_id, entity.entity_id): entity
                for sketch in previous_sketches
                for entity in sketch.entities
            }
            new_entities = {
                (sketch.sketch_id, entity.entity_id): entity
                for sketch in (*pending.current_saved, draft)
                for entity in sketch.entities
            }
            transforms = tuple(
                evidence
                for evidence in pending.step_rectangle_transforms
                if old_entities.get((evidence.reference.sketch_id, evidence.reference.entity_id))
                != new_entities.get((evidence.reference.sketch_id, evidence.reference.entity_id))
                or pending is not previous_pending
            )
            item = (
                pending.current_saved,
                draft,
                state.pending_cross_tangencies,
                state.pending_associative_arrays,
                transforms,
            )
            if not result or result[-1][:4] != item[:4]:
                result.append(item)
                previous_sketches = (*pending.current_saved, draft)
            previous_pending = pending
        return tuple(result)

    @property
    def mixed_move_is_valid(self) -> bool:
        return self.mixed_move is None or (
            self.mixed_move.transaction_id not in self._invalid_mixed_transactions
        )

    @property
    def selected_raster_id(self) -> str | None:
        """Compatibility view of the currently selected pictures."""
        return next(iter(sorted(self.selected_raster_ids)), None)

    @selected_raster_id.setter
    def selected_raster_id(self, value: str | None) -> None:
        self.selected_raster_ids = {value} if value is not None else set()

    def delete_selected(self) -> bool:
        """Erase draft selection and its dependent relations as one undo step."""
        if self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先完成当前操作，或按 Esc 取消预览，再删除所选对象。"
            self.changed.emit()
            return False
        if self.selected_raster_id is not None and (
            self.selected_entity_ids or self.selected_constraint_ids
        ):
            saved_constraint_ids = {
                constraint.constraint_id for constraint in self.background_constraints
            }
            if (
                self.selected_constraint_ids
                and self.selected_constraint_ids <= saved_constraint_ids
                and not any(
                    entity.entity_id in self.selected_entity_ids for entity in self.entities
                )
            ):
                self.committed_dimension_delete_requested.emit(
                    tuple(sorted(self.selected_constraint_ids))
                )
                return True
            if any(entity.entity_id in self.selected_entity_ids for entity in self.entities) or (
                not self.selected_entity_ids and self.selected_constraint_ids
            ):
                if self._selected_committed_entities():
                    selected_constraints = tuple(
                        constraint
                        for constraint in self.dimension_constraints()
                        if constraint.constraint_id in self.selected_constraint_ids
                    )
                    if len(selected_constraints) != len(self.selected_constraint_ids):
                        self.message = "所选标注已变化，请重新选择。"
                        self.changed.emit()
                        return False
                    self.committed_delete_requested.emit(tuple(self.selected_entity_ids))
                    return True
                error = self.transform_selection_error("delete")
                if error:
                    self.message = error
                    self.changed.emit()
                    return False
                local_constraint_ids = {constraint.constraint_id for constraint in self.constraints}
                if self.selected_constraint_ids - local_constraint_ids:
                    self.message = "请分别删除图片和已提交的标注。"
                    self.changed.emit()
                    return False
                affected_constraints = (
                    constraint
                    for constraint in self.constraints
                    if constraint.constraint_id in self.selected_constraint_ids
                    or any(
                        ref.entity_id in self.selected_entity_ids for ref in constraint.references
                    )
                )
                if any(
                    self.annotation_layer(constraint).locked
                    or not self.annotation_layer(constraint).displayed
                    for constraint in affected_constraints
                ):
                    self.message = "选择包含已锁定或隐藏图层的约束；对象未修改。"
                    self.changed.emit()
                    return False
                images = tuple(
                    image
                    for image in self.drawing_rasters
                    if image.image_id in self.selected_raster_ids
                )
                if (
                    len(images) != len(self.selected_raster_ids)
                    or self.commit_mixed_draft_transform is None
                ):
                    self.message = "所选图片已变化或无法编辑，请重新选择。"
                    self.changed.emit()
                    return False
                candidate = tuple(
                    entity
                    for entity in self.entities
                    if entity.entity_id not in self.selected_entity_ids
                )
                if not self.commit_mixed_draft_transform(candidate, images, "remove"):
                    return False
                self.selected_entity_ids.clear()
                self.selected_raster_ids.clear()
                self.message = "已删除所选图片和图元或标注；可撤销。"
                self.changed.emit()
                self.update()
                return True
            if self.selected_constraint_ids:
                self.message = "暂不能同时删除图片和标注，请分别选择。"
                self.changed.emit()
                return False
            if any(
                entity.entity_id in self.selected_entity_ids
                and (layer.locked or not layer.displayed)
                for entity, layer in self.background_entities
            ):
                self.message = "选择包含已锁定或隐藏图层；对象未修改。"
                self.changed.emit()
                return False
            error = self.transform_selection_error("delete_mixed")
            if error:
                self.message = error
                self.changed.emit()
                return False
            self.committed_delete_requested.emit(tuple(self.selected_entity_ids))
            return True
        if len(self.selected_raster_ids) > 1:
            if self.commit_raster_batch is None:
                self.message = "当前图纸无法批量删除图片。"
                self.changed.emit()
                return False
            images = tuple(
                item for item in self.drawing_rasters if item.image_id in self.selected_raster_ids
            )
            if len(images) != len(self.selected_raster_ids):
                self.message = "所选图片已变化，请重新选择。"
                self.changed.emit()
                return False
            try:
                self.commit_raster_batch("remove", images)
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
                return False
            self.selected_raster_ids.clear()
            self.message = "已删除所选图片。"
            self.changed.emit()
            self.update()
            return True
        if self.selected_raster_id is not None and self.commit_raster_edit is not None:
            image = next(
                (item for item in self.drawing_rasters if item.image_id == self.selected_raster_id),
                None,
            )
            if image is not None:
                try:
                    self.commit_raster_edit("remove", image)
                except ValueError as exc:
                    self.message = str(exc)
                    self.changed.emit()
                    return False
                self.selected_raster_id = None
                self.message = "已删除图片。"
                self.changed.emit()
                self.update()
                return True
        saved_constraints = {
            constraint.constraint_id
            for constraint in self.background_constraints
            if constraint.constraint_id in self.selected_constraint_ids
        }
        if saved_constraints or (
            self._selected_committed_entities() and self.selected_constraint_ids
        ):
            self.committed_dimension_delete_requested.emit(
                tuple(sorted(self.selected_constraint_ids))
            )
            return True
        if self._selected_committed_entities() and not self.selected_constraint_ids:
            selected = [
                entity.entity_id
                for entity in (*self.entities, *(item for item, _ in self.background_entities))
                if entity.entity_id in self.selected_entity_ids
            ]
            if len(selected) != len(set(selected)):
                self.message = "选择的图元身份不唯一；请先解决重复身份，图元未修改。"
                self.changed.emit()
                return False
            error = self.transform_selection_error("delete_mixed")
            if error:
                self.message = error
                self.changed.emit()
                return False
            if any(
                (layer.locked or not layer.displayed)
                and entity.entity_id in self.selected_entity_ids
                for entity, layer in self.background_entities
            ):
                self.message = "选择包含已锁定或隐藏图层；图元未修改。"
                self.changed.emit()
                return False
            self.committed_delete_requested.emit(tuple(self.selected_entity_ids))
            return True
        error = self.transform_selection_error("delete") if self.selected_entity_ids else ""
        if error:
            self.message = error
            self.changed.emit()
            return False
        entity_ids = {
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        }
        constraints = [
            constraint
            for constraint in self.constraints
            if constraint.constraint_id in self.selected_constraint_ids
            or any(ref.entity_id in entity_ids for ref in constraint.references)
        ]
        if any(
            self.annotation_layer(constraint).locked
            or not self.annotation_layer(constraint).displayed
            for constraint in constraints
        ):
            self.message = "选择包含已锁定或隐藏图层的约束；草图未修改。"
            self.changed.emit()
            return False
        if not entity_ids and not constraints:
            return False
        updated_draft: Sketch | None = None
        updated_pending: tuple[AssociativeRectArray, ...] | None = None
        if entity_ids and self.pending_associative_arrays:
            member_ids = {
                member.target.entity_id
                for array in self.pending_associative_arrays
                for member in array.members
                if member.erased_index is None
            }
            member_ids.update(
                output.target.entity_id
                for array in self.pending_associative_arrays
                for output in array.extra_outputs
            )
            if any(
                draft_tangent_reference(target).entity_id in entity_ids & member_ids
                and draft_tangent_reference(source).entity_id not in entity_ids
                for source, target in self.pending_cross_tangencies
            ):
                self.message = "阵列成员仍有对象相切关系；图元未修改。"
                self.changed.emit()
                return False
            if self.draft_sketches_provider is None:
                self.message = "无法校验草稿阵列；图元未修改。"
                self.changed.emit()
                return False
            try:
                states = self.draft_sketches_provider()
                proposed, arrays = erase_drawing_entities(
                    states,
                    tuple(self.pending_associative_arrays),
                    tuple(ArrayEntityRef(states[0].sketch_id, identity) for identity in entity_ids),
                )
                updated_draft = proposed[0]
                pending_ids = {array.array_id for array in self.pending_associative_arrays}
                updated_pending = tuple(array for array in arrays if array.array_id in pending_ids)
            except (IndexError, KeyError, ValueError) as exc:
                self.message = f"删除失败：{exc}"
                self.changed.emit()
                return False
        self.deleting.emit()
        self._record_undo()
        self.entities = (
            list(updated_draft.entities)
            if updated_draft is not None
            else [entity for entity in self.entities if entity.entity_id not in entity_ids]
        )
        if updated_pending is not None:
            self.pending_associative_arrays = list(updated_pending)
        self._prune_pending_cross_tangencies()
        removed_constraints = {constraint.constraint_id for constraint in constraints}
        self.constraints = [
            constraint
            for constraint in self.constraints
            if constraint.constraint_id not in removed_constraints
        ]
        self.selected_entity_ids.difference_update(entity_ids)
        self.selected_constraint_ids.difference_update(removed_constraints)
        self._snap_candidates_cache = None
        self._snap_kind = ""
        self._hovered_entity_id = None
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()
        self.message = (
            f"已删除 {len(entity_ids)} 个图元及 {len(constraints)} 条约束；Ctrl+Z 可撤销。"
        )
        self.changed.emit()
        self.update()
        return True

    def validate_draft_constraint_edits(
        self, entities: tuple[SketchEntity, ...], *, removed_constraint_ids: frozenset[str]
    ) -> None:
        """Validate a linked edit while accounting for constraints it deletes."""
        self._reject_user_constraint_reference_edits(
            entities, proven_rebound_ids=removed_constraint_ids
        )

    def selected_draft_constraints_exist(self) -> bool:
        """Whether copying the selected draft geometry omits a local relation."""
        return any(
            ref.entity_id in self.selected_entity_ids
            for constraint in self.constraints
            for ref in constraint.references
        )

    def selected_user_tangencies_transformable(self) -> bool:
        """Allow transforms when all affected user tangencies move together."""
        affected = tuple(
            constraint
            for constraint in self.constraints
            if constraint.source == "user"
            and any(ref.entity_id in self.selected_entity_ids for ref in constraint.references)
        )
        return bool(affected) and all(
            constraint.kind == "tangent"
            and all(ref.entity_id in self.selected_entity_ids for ref in constraint.references)
            for constraint in affected
        )

    def selected_pending_copy_omissions(self) -> tuple[bool, bool]:
        """Identify pending relations that independent copies will not inherit."""
        tangent = any(
            draft_tangent_reference(endpoint).entity_id in self.selected_entity_ids
            for pair in self.pending_cross_tangencies
            for endpoint in pair
        )
        array = any(
            ref.entity_id in self.selected_entity_ids
            for item in self.pending_associative_arrays
            for ref in (
                *item.sources,
                *(member.source for member in item.members),
                *(member.target for member in item.members),
                *(member.replacement.source for member in item.members if member.replacement),
                *(output.source for output in item.extra_outputs),
                *(output.target for output in item.extra_outputs),
                *(output.anchor_source for output in item.extra_outputs),
            )
        )
        return tangent, array

    def draft_copy_preserves_sources(self, candidate: tuple[SketchEntity, ...]) -> bool:
        """Prove that a proposed copy keeps every existing draft entity unchanged."""
        original = {entity.entity_id: entity for entity in self.entities}
        updated = {entity.entity_id: entity for entity in candidate}
        return (
            len(original) == len(self.entities)
            and len(updated) == len(candidate)
            and len(candidate) > len(self.entities)
            and all(updated.get(identity) == entity for identity, entity in original.items())
        )

    def draft_copy_omission_notice(self) -> str:
        tangent, array = self.selected_pending_copy_omissions()
        labels = [
            label
            for present, label in (
                (self.selected_draft_constraints_exist() or tangent, "约束关系"),
                (array, "阵列关联"),
            )
            if present
        ]
        return f"副本未继承原对象的{'和'.join(labels)}。" if labels else ""

    def _reject_user_constraint_reference_edits(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
        allow_satisfied_tangency: bool = False,
        proven_rebound_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Keep direct draft edits from silently breaking confirmed relations."""
        baseline = original_entities if original_entities is not None else tuple(self.entities)
        current_by_id = {entity.entity_id: entity for entity in baseline}
        updated_by_id = {entity.entity_id: entity for entity in entities}
        changed_ids = {
            entity_id
            for entity_id in current_by_id.keys() | updated_by_id.keys()
            if current_by_id.get(entity_id) != updated_by_id.get(entity_id)
            and not (
                (before := current_by_id.get(entity_id)) is not None
                and (after := updated_by_id.get(entity_id)) is not None
                and type(before) is type(after)
                and replace(after, layer_name=before.layer_name, construction=before.construction)
                == before
            )
        }
        for constraint in self.constraints:
            if constraint.source != "user":
                continue
            if constraint.constraint_id in proven_rebound_ids:
                continue
            if any(reference.entity_id in changed_ids for reference in constraint.references):
                if allow_satisfied_tangency and constraint.kind == "tangent":
                    try:
                        for ref in constraint.references:
                            if ref.index is None or ref.entity_id not in changed_ids:
                                continue
                            before, after = (
                                current_by_id[ref.entity_id],
                                updated_by_id[ref.entity_id],
                            )
                            if not isinstance(before, PolylineEntity) or not isinstance(
                                after, PolylineEntity
                            ):
                                raise ValueError("无法确认相切段身份。")
                            matched = unique_unchanged_polyline_segment(before, after, ref.index)
                            if matched is None:
                                matched = unique_extended_polyline_segment(before, after, ref.index)
                            if matched is None:
                                matched = unique_containing_polyline_arc(before, after, ref.index)
                            if matched is None and (
                                unique_extended_polyline_segment(after, before, ref.index)
                                == ref.index
                                and unique_extended_polyline_segment(after, after, ref.index)
                                == ref.index
                                or unique_containing_polyline_arc(after, before, ref.index)
                                == ref.index
                                and unique_containing_polyline_arc(after, after, ref.index)
                                == ref.index
                            ):
                                matched = ref.index
                            if matched != ref.index:
                                raise ValueError("无法确认相切段身份。")
                        first, second = (
                            tangent_entity_curve(updated_by_id[ref.entity_id], ref.index)
                            for ref in constraint.references
                        )
                        if tangent_on_curves(first, second) and tangent_endpoints_satisfied(
                            first, second, constraint.first_endpoint, constraint.second_endpoint
                        ):
                            continue
                    except (KeyError, ValueError):
                        pass
                raise ValueError(
                    "本次编辑会改变用户约束引用的图元；请先处理相关约束再改几何。草稿未变。"
                )

    def _line_edit_user_constraints(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        trim: bool,
        original_entities: tuple[SketchEntity, ...] | None = None,
        allow_split_lines: bool = False,
        allow_split_arcs: bool = False,
    ) -> tuple[SketchConstraint, ...]:
        """Check draft edits and stage only proven local tangency rebindings."""
        original = original_entities if original_entities is not None else tuple(self.entities)
        tangencies = tuple(
            constraint
            for constraint in self.constraints
            if constraint.kind == "tangent" and constraint.source == "user"
        )
        rebound = tangencies
        if trim and tangencies:
            baseline = Sketch(
                uuid4().hex,
                self._spatial_target_frame,
                original,
                constraints=tangencies,
                layers=self.layer_table,
            )
            rebound = rebind_retained_local_tangencies(
                baseline,
                replace(baseline, entities=entities),
                allow_fragment_rebind=True,
                allow_split_lines=allow_split_lines,
                allow_split_arcs=allow_split_arcs,
            )
        changed = frozenset(
            old.constraint_id for old, new in zip(tangencies, rebound, strict=True) if old != new
        )
        self._reject_user_constraint_reference_edits(
            entities,
            original_entities=original,
            allow_satisfied_tangency=True,
            proven_rebound_ids=changed,
        )
        rebound_by_id = {constraint.constraint_id: constraint for constraint in rebound}
        return tuple(rebound_by_id.get(item.constraint_id, item) for item in self.constraints)

    def _rebind_unchanged_user_polyline_references(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
        constraints: tuple[SketchConstraint, ...] | None = None,
        include_inferred: bool = False,
    ) -> tuple[SketchConstraint, ...]:
        """Retain user references only when the referenced polyline part is unchanged."""
        original = {
            entity.entity_id: entity
            for entity in (original_entities if original_entities is not None else self.entities)
        }
        updated = {entity.entity_id: entity for entity in entities}
        rebound: list[SketchConstraint] = []
        for constraint in constraints if constraints is not None else self.constraints:
            if constraint.source != "user" and not (
                include_inferred and constraint.kind in ("coincident", "tangent")
            ):
                if include_inferred and any(
                    original.get(ref.entity_id) != updated.get(ref.entity_id)
                    for ref in constraint.references
                ):
                    raise ValueError("不支持重绑定该自动约束；草稿未变。")
                rebound.append(constraint)
                continue
            refs: list[SketchGeometryReference] = []
            for ref in constraint.references:
                before, after = original.get(ref.entity_id), updated.get(ref.entity_id)
                if before == after:
                    refs.append(ref)
                    continue
                if not isinstance(before, PolylineEntity) or not isinstance(after, PolylineEntity):
                    raise ValueError("用户约束引用的图元已改变；草稿未变。")
                if (
                    before.layer_name != after.layer_name
                    or before.construction != after.construction
                    or before.closed != after.closed
                ):
                    raise ValueError("用户约束引用的多段线属性已改变；草稿未变。")
                if ref.kind == "vertex" and ref.index is not None:
                    if ref.index >= len(before.points_mm):
                        raise ValueError("用户约束顶点索引无效；草稿未变。")
                    point = before.points_mm[ref.index]
                    matches = [i for i, value in enumerate(after.points_mm) if value == point]
                    if before.points_mm.count(point) != 1 or len(matches) != 1:
                        raise ValueError("用户约束顶点已改变或不唯一；草稿未变。")
                    refs.append(replace(ref, index=matches[0]))
                elif ref.kind == "segment" and ref.index is not None:
                    index = unique_unchanged_polyline_segment(before, after, ref.index)
                    if index is None:
                        raise ValueError("用户约束线段已改变或不唯一；草稿未变。")
                    refs.append(replace(ref, index=index))
                elif ref.kind in ("start", "end") and not before.closed:
                    index = 0 if ref.kind == "start" else -1
                    if before.points_mm[index] != after.points_mm[index]:
                        raise ValueError("用户约束端点已改变；草稿未变。")
                    refs.append(ref)
                else:
                    raise ValueError("用户约束引用的多段线已改变；草稿未变。")
            rebound.append(replace(constraint, references=tuple(refs)))
        return tuple(rebound)

    @property
    def view_scale(self) -> float:
        return self._scale

    @property
    def is_panning(self) -> bool:
        return self._panning

    @property
    def can_undo(self) -> bool:
        return (
            bool(self._undo_history)
            and not self.has_pending_geometry
            and not self.has_active_edit_gesture
        )

    @property
    def can_redo(self) -> bool:
        return (
            bool(self._redo_history)
            and (not self.has_pending_geometry or (self.tool == "直线" and self.continuous_lines))
            and not self.has_active_edit_gesture
        )

    @property
    def has_active_edit_gesture(self) -> bool:
        """Whether a pointer edit is displaying an unconfirmed draft preview."""
        return (
            self.tool == "对象相切选择"
            or self._transform_operation is not None
            or self._line_edit_selecting_boundaries
            or self._circle_fillet_first is not None
            or self._chamfer_first is not None
            or bool(self._corner_drag_points)
            or self._clipboard_paste is not None
            or self._clipboard_raster is not None
            or bool(self._clipboard_rasters)
            or self.chamfer_polyline_pending
            or self.circle_fillet_polyline_pending
            or self.circle_ttr_active
            or self.arc_ttr_active
            or self.line_tangent_active
            or self._trim_fence_active
            or self._line_edit_erasing
            or self._trim_drag_start is not None
            or self._drag_reference is not None
            or self._saved_handle_drag is not None
            or self._array_spacing_drag is not None
            or self._selection_anchor is not None
        )

    def _cancel_active_edit_gesture(self) -> bool:
        cancelled_paste = self.clipboard_paste_active
        self._clipboard_paste = None
        self._clipboard_raster = None
        self._clipboard_rasters = ()
        self._clipboard_mixed_images = ()
        self._clipboard_mixed_revision = None
        cancelled_corner_drag = bool(self._corner_drag_points)
        self._corner_drag_points.clear()
        cancelled_selection = self._cancel_selection_box()
        cancelled_boundaries = self._line_edit_selecting_boundaries
        cancelled_fence = self._trim_fence_active
        self._trim_fence_active = False
        self._line_crossing_active = False
        cancelled_erase = self._line_edit_erasing
        self._line_edit_erasing = False
        self._line_edit_selecting_boundaries = False
        return (
            self.cancel_transform()
            or self._cancel_circle_fillet()
            or self._cancel_circle_ttr()
            or self._cancel_arc_ttr()
            or self._cancel_line_tangent()
            or self._cancel_trim_drag()
            or self._cancel_handle_drag()
            or self.cancel_saved_handle_drag()
            or self.cancel_array_spacing_drag()
            or cancelled_selection
            or cancelled_boundaries
            or cancelled_fence
            or cancelled_erase
            or cancelled_corner_drag
            or cancelled_paste
        )

    def _cancel_circle_fillet(self) -> bool:
        if (
            self._circle_fillet_first is None
            and self._chamfer_first is None
            and not self.chamfer_polyline_pending
            and not self.circle_fillet_radius_pending
            and self._fillet_radius_anchor is None
            and not self.circle_fillet_trim_pending
            and not self.circle_fillet_polyline_pending
        ):
            return False
        self._circle_fillet_first = None
        self._chamfer_first = None
        self._chamfer_segment = None
        self.chamfer_polyline_pending = False
        self._circle_fillet_segment = None
        self._fillet_source_revision = None
        self.circle_fillet_radius_pending = False
        self._fillet_radius_anchor = None
        self.circle_fillet_trim_pending = False
        self.circle_fillet_polyline_pending = False
        self.selected_entity_ids.clear()
        self.message = "已取消圆角选取；草稿未变。"
        self.changed.emit()
        self.update()
        return True

    def _complete_fillet_command(self) -> None:
        """Return to selection after one result unless Multiple was requested."""
        self.selected_entity_ids.clear()
        if self.circle_fillet_multiple:
            self.message += " 可继续选择或拖过两条边；Enter / Esc 结束。"
        else:
            self.tool = "选择元素"

    def _finish_corner_drag(self, point: Point2D) -> None:
        points = (*self._corner_drag_points, point)
        self._corner_drag_points.clear()
        if (
            self._corner_drag_revision is not None
            and self.source_revision_provider is not None
            and self._corner_drag_revision != self.source_revision_provider()
        ):
            self.message = "文档在拖动期间已变化；请重新选取。"
            self.changed.emit()
            self.update()
            return
        if max(_distance(points[0], item) for item in points) * self._scale <= 4:
            pick = self._chamfer_pick if self.tool == "二维倒角" else self._circle_fillet_pick
            pick(points[0], temporary_zero=self._corner_drag_shift)
            return
        hits: list[tuple[SketchEntity, Point2D, int | None]] = []
        seen: set[tuple[str, int | None]] = set()
        try:
            for start, end in zip(points, points[1:], strict=False):
                segment_hits: list[tuple[SketchEntity, Point2D, int | None]] = []
                for entity in self.selectable_entities():
                    supported = (
                        isinstance(entity, LineEntity | PolylineEntity | RectangleEntity)
                        if self.tool == "二维倒角"
                        else isinstance(
                            entity,
                            LineEntity
                            | PolylineEntity
                            | RectangleEntity
                            | CircleEntity
                            | ArcEntity,
                        )
                    )
                    if not supported:
                        continue
                    for hit in fence_intersections(start, end, entity):
                        path = (
                            self._chamfer_rectangle_path(entity)
                            if isinstance(entity, RectangleEntity)
                            else entity
                        )
                        index = (
                            self._fillet_polyline_segment_at(path, hit)
                            if isinstance(path, PolylineEntity)
                            else None
                        )
                        segment_hits.append((entity, hit, index))
                segment_hits.sort(key=lambda item: _distance(start, item[1]))
                for entity, hit, index in segment_hits:
                    key = (entity.entity_id, index)
                    if key not in seen:
                        if any(_distance(hit, previous[1]) * self._scale < 1 for previous in hits):
                            raise ValueError("轨迹穿过重合或交叉位置，请避开交点重新拖动。")
                        seen.add(key)
                        hits.append((entity, hit, index))
            if len(hits) != 2:
                raise ValueError("拖动轨迹应穿过两条边；请重新拖动或逐条选择。")
            if any(self._hit_entity_at(hit) != entity.entity_id for entity, hit, _index in hits):
                raise ValueError("轨迹上的对象无法唯一选择，请调整轨迹。")
            pick = self._chamfer_pick if self.tool == "二维倒角" else self._circle_fillet_pick
            pick(hits[0][1], temporary_zero=self._corner_drag_shift)
            if self._chamfer_first is not None or self._circle_fillet_first is not None:
                pick(hits[1][1], temporary_zero=self._corner_drag_shift)
                if not self._fillet_candidate_pending and (
                    self._chamfer_first is not None or self._circle_fillet_first is not None
                ):
                    message = self.message
                    self._cancel_circle_fillet()
                    self.message = f"{message} 请调整参数后重新拖动。"
                    self.changed.emit()
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
        self.update()

    def _unchanged_corner_message(self, *, temporary_zero: bool = False) -> str:
        if temporary_zero:
            return "按住 Shift 临时使用零值；所选边已相交，图形未变化。"
        if self.tool == "二维圆角" and self.circle_fillet_radius == 0:
            return "圆角半径为 0，所选边已相交，无需更改；重新执行圆角并输入 R 设置非零半径。"
        if (
            self.tool == "二维倒角"
            and self.chamfer_first_distance == 0
            and (
                self.chamfer_angle == 0
                or (self.chamfer_angle is None and self.chamfer_second_distance == 0)
            )
        ):
            return "倒角距离为 0，所选边已相交；重新执行倒角并在命令栏输入 D 设置非零距离。"
        return "所选对象已满足角点要求，图形未变化。"

    def finish_fillet_candidate(self, *, success: bool) -> None:
        """Finish a saved-source fillet only after its candidate has completed."""
        if not self._fillet_candidate_pending:
            return
        self._fillet_candidate_pending = False
        if success and self.tool in {"二维圆角", "二维倒角"}:
            self.pending_cross_tangencies.extend(self._fillet_pending_cross_candidate)
            self.circle_fillet_polyline_pending = False
            self._complete_fillet_command()
        self._fillet_pending_cross_candidate = ()

    def begin_arc_center(self) -> bool:
        """Use a center, start point and end direction for the new arc."""
        if self.tool != "圆弧" or self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先完成或取消当前操作。"
            self.changed.emit()
            return False
        self.arc_creation_mode = "center"
        self.arc_mode_prompt_active = False
        self.message = "圆弧：指定圆心、起点和终点。"
        self.changed.emit()
        self.update()
        return True

    def begin_arc_three_point(self) -> bool:
        """Use three circumference points to determine the new arc."""
        if self.tool != "圆弧" or self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先完成或取消当前操作。"
            self.changed.emit()
            return False
        self.arc_creation_mode = "three_point"
        self.arc_mode_prompt_active = False
        self.message = "三点圆弧：指定起点、第二点和终点。"
        self.changed.emit()
        self.update()
        return True

    def _three_point_arc(
        self, start: Point2D, middle: Point2D, end: Point2D, identity: str
    ) -> ArcEntity:
        ux, uy = middle[0] - start[0], middle[1] - start[1]
        vx, vy = end[0] - start[0], end[1] - start[1]
        scale = max(abs(ux), abs(uy), abs(vx), abs(vy))
        if not math.isfinite(scale) or scale <= 1e-12:
            raise ValueError("三点圆弧需要三个不同的有限点。")
        ux, uy, vx, vy = ux / scale, uy / scale, vx / scale, vy / scale
        determinant = 2 * (ux * vy - uy * vx)
        if abs(determinant) <= 1e-12:
            raise ValueError("三点不能共线，请重新指定终点。")
        u2, v2 = ux * ux + uy * uy, vx * vx + vy * vy
        center = (
            start[0] + scale * (u2 * vy - v2 * uy) / determinant,
            start[1] + scale * (ux * v2 - vx * u2) / determinant,
        )
        radius = math.dist(center, start)
        if not all(math.isfinite(value) for value in (*center, radius)) or radius <= 0:
            raise ValueError("三点圆弧超出可用数值范围。")
        angles = tuple(
            math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
            for point in (start, middle, end)
        )
        first, through, last = angles
        ccw = (last - first) % 360
        middle_ccw = (through - first) % 360
        sweep = ccw if middle_ccw <= ccw else ccw - 360
        return ArcEntity(
            identity, center, radius, first, sweep, self.construction, self.active_layer_name
        )

    def begin_arc_ttr(self) -> bool:
        """Select two tangent objects, then enter a radius for a new arc."""
        if self.tool != "圆弧" or self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先启动圆弧命令并完成或取消当前操作。"
            self.changed.emit()
            return False
        self.arc_mode_prompt_active = False
        self.arc_ttr_active = True
        self._arc_ttr_sources.clear()
        self._arc_ttr_revision = (
            self.source_revision_provider() if self.source_revision_provider else None
        )
        self.selected_entity_ids.clear()
        self.message = "相切圆弧：请选择第一个对象。"
        self.changed.emit()
        self.update()
        return True

    @property
    def arc_ttr_radius_pending(self) -> bool:
        return self.arc_ttr_active and len(self._arc_ttr_sources) == 2

    def _cancel_arc_ttr(self) -> bool:
        if not self.arc_ttr_active:
            return False
        self.arc_ttr_active = False
        self._snap_kind = ""
        self._arc_ttr_sources.clear()
        self._arc_ttr_revision = None
        self.selected_entity_ids.clear()
        self.message = "已取消相切圆弧；图形未修改。"
        self.changed.emit()
        self.update()
        return True

    def _pick_arc_ttr_source(self, point: Point2D) -> None:
        if self.arc_ttr_radius_pending:
            self.message = "相切圆弧：请输入半径。"
        else:
            identity = self._hit_entity_at(point)
            entity = next(
                (item for item in self.selectable_entities() if item.entity_id == identity), None
            )
            try:
                if not isinstance(
                    entity, LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
                ):
                    raise ValueError("请选择直线、圆、圆弧或多段线的线段。")
                if isinstance(entity, PolylineEntity | RectangleEntity):
                    path = (
                        self._chamfer_rectangle_path(entity)
                        if isinstance(entity, RectangleEntity)
                        else entity
                    )
                    index = self._fillet_polyline_segment_at(path, point)
                    reference = SketchGeometryReference(entity.entity_id, "segment", index)
                else:
                    reference = SketchGeometryReference(entity.entity_id, "geometry")
                if any(ref == reference for _source, ref, _pick in self._arc_ttr_sources):
                    raise ValueError("请选择两个不同的对象或线段。")
                self._arc_ttr_sources.append((entity, reference, point))
                self._snap_kind = ""
                self.selected_entity_ids.add(entity.entity_id)
                self.message = (
                    (
                        f"相切圆弧：输入半径或按 Enter 使用 {self.arc_ttr_last_radius:g}。"
                        if self.arc_ttr_last_radius is not None
                        else "相切圆弧：请输入大于零的半径。"
                    )
                    if self.arc_ttr_radius_pending
                    else "相切圆弧：请选择第二个对象。"
                )
            except ValueError as exc:
                self.message = str(exc)
        self.changed.emit()
        self.update()

    def finish_arc_ttr(self, radius: float) -> bool:
        if not self.arc_ttr_radius_pending:
            self.message = "请先选择两个相切对象。"
            self.changed.emit()
            return False
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或已锁定，无法创建圆弧。"
            self.changed.emit()
            return False
        if (
            self._arc_ttr_revision is not None
            and self.source_revision_provider is not None
            and self.source_revision_provider() != self._arc_ttr_revision
        ) or any(
            source not in self.selectable_entities()
            for source, _ref, _point in self._arc_ttr_sources
        ):
            self.message = "来源已变化；请按 Esc 后重新选择对象。"
            self.changed.emit()
            return False
        (source_a, ref_a, pick_a), (source_b, ref_b, pick_b) = self._arc_ttr_sources
        try:
            if not math.isfinite(radius) or radius <= 0:
                raise ValueError("半径必须是大于零的有限数值。")
            available = (*self.entities, *(entity for entity, _layer in self.background_entities))
            if any(
                sum(entity.entity_id == source.entity_id for entity in available) != 1
                for source in (source_a, source_b)
            ):
                raise ValueError("来源图元身份不唯一；请重新选择。")
            first = replace(tangent_entity_curve(source_a, ref_a.index), entity_id=uuid4().hex)
            second = replace(tangent_entity_curve(source_b, ref_b.index), entity_id=uuid4().hex)
            if isinstance(first, LineEntity) and isinstance(second, LineEntity):
                _, _, arc = line_fillet(
                    first,
                    second,
                    pick_a,
                    pick_b,
                    radius,
                    uuid4().hex,
                    layer_name=self.active_layer_name,
                )
                if not math.isclose(arc.radius_mm, radius, rel_tol=1e-9, abs_tol=1e-8):
                    raise ValueError("指定半径不能与这两条平行线相切。")
            elif isinstance(first, CircleEntity | ArcEntity) and isinstance(
                second, CircleEntity | ArcEntity
            ):
                arc = circle_fillet_notrim(
                    first,
                    second,
                    pick_a,
                    pick_b,
                    radius,
                    uuid4().hex,
                    layer_name=self.active_layer_name,
                )
            else:
                line = first if isinstance(first, LineEntity) else second
                curve = second if isinstance(first, LineEntity) else first
                assert isinstance(line, LineEntity) and isinstance(curve, CircleEntity | ArcEntity)
                line_pick, curve_pick = (
                    (pick_a, pick_b) if isinstance(first, LineEntity) else (pick_b, pick_a)
                )
                arc = line_circle_fillet_notrim(
                    line,
                    curve,
                    line_pick,
                    curve_pick,
                    radius,
                    uuid4().hex,
                    layer_name=self.active_layer_name,
                )
            arc = replace(arc, construction=self.construction)
            if not tangent_on_curves(first, arc) or not tangent_on_curves(second, arc):
                raise ValueError("相切点不在来源对象的有效范围内。")
            relations, pending = self._fillet_indexed_relations(
                arc, ((source_a, ref_a), (source_b, ref_b))
            )
            if not self.replace_draft_entities((*self.entities, arc), new_relations=relations):
                return False
            self.pending_cross_tangencies.extend(pending)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        self.arc_ttr_active = False
        self._arc_ttr_sources.clear()
        self._arc_ttr_revision = None
        self.arc_ttr_last_radius = radius
        self.selected_entity_ids.clear()
        self.message = "相切圆弧已创建；来源对象保留。"
        self.changed.emit()
        self.update()
        return True

    def begin_circle_ttr(self) -> bool:
        """Start selecting the two tangent sources for a radius-defined circle."""
        if self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先完成或取消当前操作。"
            self.changed.emit()
            return False
        self.circle_ttr_active = True
        self._circle_ttr_sources.clear()
        self._circle_ttr_revision = (
            self.source_revision_provider() if self.source_revision_provider else None
        )
        self.selected_entity_ids.clear()
        self.message = "圆 TTR：请选择第一个切线对象。"
        self.changed.emit()
        return True

    def begin_line_tangent_pick(self, *, require_two: bool = False) -> bool:
        """Request one source for a deferred common tangent line."""
        if self.tool != "直线":
            self.message = "请先启动直线命令。"
            self.changed.emit()
            return False
        if not self.line_tangent_active:
            if (
                self.source_revision_provider is not None
                and self.source_context_revision is not None
                and self.source_revision_provider() != self.source_context_revision
            ):
                self.message = "来源已变化；请刷新后重新选择对象。"
                self.source_revision_invalidated.emit()
                self.changed.emit()
                return False
            if self.has_active_edit_gesture:
                self.message = "请先完成或取消当前操作。"
                self.changed.emit()
                return False
            self.line_tangent_active = True
            self._line_tangent_require_two = require_two
            self._line_tangent_sources.clear()
            self._line_tangent_anchor = self._first
            self._line_tangent_revision = (
                self.source_revision_provider() if self.source_revision_provider else None
            )
            self.selected_entity_ids.clear()
        self._line_tangent_awaiting = True
        self.message = f"切点直线：请选择第{len(self._line_tangent_sources) + 1}个圆或圆弧。"
        self.changed.emit()
        self.update()
        return True

    @property
    def line_tangent_awaiting_pick(self) -> bool:
        return self.line_tangent_active and self._line_tangent_awaiting

    def _line_tangent_target_at(self, point: Point2D) -> CircleEntity | ArcEntity | None:
        """Pick a distinct circular target for a deferred tangent line."""
        if self._last_pointer_shift:
            return None
        identity = self._hit_entity_at(point)
        target = next(
            (entity for entity in self.selectable_entities() if entity.entity_id == identity), None
        )
        if isinstance(target, CircleEntity | ArcEntity) and all(
            source.entity_id != target.entity_id for source, _pick in self._line_tangent_sources
        ):
            return target
        return None

    @property
    def previewed_tangent_line(self) -> LineEntity | None:
        """Return the current tangent candidate without mutating draft geometry."""
        if not self.line_tangent_active or self._cursor is None:
            return None
        if (
            self._line_tangent_revision is not None
            and self.source_revision_provider is not None
            and self.source_revision_provider() != self._line_tangent_revision
        ) or any(
            source not in self.selectable_entities() for source, _ in self._line_tangent_sources
        ):
            return None
        identity = "00000000000000000000000000000000"
        try:
            if not self._line_tangent_awaiting:
                source, pick = self._line_tangent_sources[0]
                target = self._line_tangent_target_at(self._cursor)
                if target is not None:
                    return common_tangent_line(
                        source,
                        target,
                        pick,
                        self._cursor,
                        identity,
                        construction=self.construction,
                        layer_name=self.active_layer_name,
                    )
                if self._line_tangent_require_two:
                    return None
                return tangent_line_to_point(
                    source,
                    self._cursor,
                    pick,
                    identity,
                    from_curve=True,
                    construction=self.construction,
                    layer_name=self.active_layer_name,
                )
            picked_id = self._hit_entity_at(self._cursor)
            picked = next(
                (item for item in self.selectable_entities() if item.entity_id == picked_id), None
            )
            if not isinstance(picked, CircleEntity | ArcEntity):
                return None
            if self._line_tangent_anchor is not None:
                return tangent_line_to_point(
                    picked,
                    self._line_tangent_anchor,
                    self._cursor,
                    identity,
                    construction=self.construction,
                    layer_name=self.active_layer_name,
                )
            if self._line_tangent_sources:
                first, pick = self._line_tangent_sources[0]
                return common_tangent_line(
                    first,
                    picked,
                    pick,
                    self._cursor,
                    identity,
                    construction=self.construction,
                    layer_name=self.active_layer_name,
                )
        except ValueError:
            return None
        return None

    def _cancel_line_tangent(self) -> bool:
        if not self.line_tangent_active:
            return False
        self.line_tangent_active = False
        self._line_tangent_require_two = False
        self._line_tangent_awaiting = False
        self._line_tangent_sources.clear()
        self._line_tangent_revision = None
        self._line_tangent_anchor = None
        self._snap_kind = ""
        self.selected_entity_ids.clear()
        self.message = "已取消切点直线；草稿未变。"
        self.changed.emit()
        self.update()
        return True

    def _pick_line_tangent_source(self, point: Point2D) -> None:
        if not self._line_tangent_awaiting:
            first, first_pick = self._line_tangent_sources[0]
            try:
                target = self._line_tangent_target_at(point)
                if target is None and self._line_tangent_require_two:
                    self.message = "切点直线：请选择另一个圆或圆弧。"
                    self.changed.emit()
                    return
                if target is not None:
                    line = common_tangent_line(
                        first,
                        target,
                        first_pick,
                        point,
                        uuid4().hex,
                        construction=self.construction,
                        layer_name=self.active_layer_name,
                    )
                    self._finish_line_tangent(line, (first, target))
                else:
                    line = tangent_line_to_point(
                        first,
                        point,
                        first_pick,
                        uuid4().hex,
                        from_curve=True,
                        construction=self.construction,
                        layer_name=self.active_layer_name,
                    )
                    self._finish_line_tangent(line, (first,))
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
            return
        identity = self._hit_entity_at(point)
        entity = next(
            (item for item in self.selectable_entities() if item.entity_id == identity), None
        )
        if not isinstance(entity, CircleEntity | ArcEntity):
            self.message = "切点直线：请选择圆或圆弧。"
            self.changed.emit()
            return
        if any(source.entity_id == entity.entity_id for source, _ in self._line_tangent_sources):
            self.message = "切点直线：请选择两个不同对象。"
            self.changed.emit()
            return
        if self._line_tangent_anchor is not None:
            try:
                line = tangent_line_to_point(
                    entity,
                    self._line_tangent_anchor,
                    point,
                    uuid4().hex,
                    construction=self.construction,
                    layer_name=self.active_layer_name,
                )
                self._finish_line_tangent(line, (entity,))
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
            return
        if not self._line_tangent_sources:
            self._line_tangent_sources.append((entity, point))
            self._line_tangent_awaiting = False
            self.selected_entity_ids.add(entity.entity_id)
            self.message = (
                "切点直线：请选择第二个圆或圆弧。"
                if self._line_tangent_require_two
                else "切点直线：捕捉第二个圆或圆弧，或指定普通终点。"
            )
            self.changed.emit()
            self.update()
            return
        first, first_pick = self._line_tangent_sources[0]
        sources = (first, entity)
        try:
            line = common_tangent_line(
                first,
                entity,
                first_pick,
                point,
                uuid4().hex,
                construction=self.construction,
                layer_name=self.active_layer_name,
            )
            self._finish_line_tangent(line, sources)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()

    def _finish_line_tangent(
        self, line: LineEntity, sources: tuple[CircleEntity | ArcEntity, ...]
    ) -> None:
        if not self._current_layer_can_draw():
            raise ValueError("当前图层隐藏或已锁定，无法创建直线。")
        if (
            self._line_tangent_revision is not None
            and self.source_revision_provider is not None
            and self.source_revision_provider() != self._line_tangent_revision
        ) or any(source not in self.selectable_entities() for source in sources):
            raise ValueError("来源已变化；请按 Esc 后重新选择对象。")
        available = (*self.entities, *(item for item, _ in self.background_entities))
        if any(
            sum(item.entity_id == source.entity_id for item in available) != 1 for source in sources
        ):
            raise ValueError("来源图元身份不唯一；请重新选择。")
        relations = self._fillet_tangent_relations(line, sources)
        pending = self._fillet_cross_pairs(line, sources)
        relation_keys = {(item.kind, frozenset(item.references)) for item in relations}
        relations = (
            *relations,
            *(
                item
                for item in self._inferred_constraints_for_entity(line)
                if (item.kind, frozenset(item.references)) not in relation_keys
            ),
        )
        if not self.replace_draft_entities((*self.entities, line), new_relations=relations):
            return
        self._last_polar_entity_id = line.entity_id
        self.pending_cross_tangencies.extend(pending)
        self.line_tangent_active = False
        self._line_tangent_require_two = False
        self._line_tangent_awaiting = False
        self._line_tangent_sources.clear()
        self._line_tangent_revision = None
        prior_anchor = self._line_tangent_anchor
        self._line_tangent_anchor = None
        self._snap_kind = ""
        self.selected_entity_ids.clear()
        if self.continuous_lines:
            self._points = (
                [*self._points, line.end_mm]
                if prior_anchor is not None and self._points
                else [line.start_mm, line.end_mm]
            )
            self._first = line.end_mm
            self.message = "切点直线已创建；指定下一点或按 Enter 结束。"
        else:
            self._first = None
            self._points.clear()
            self.message = "切点直线已创建。"
        self.point_accepted.emit(line.end_mm)
        self.changed.emit()
        self.update()

    def _cancel_circle_ttr(self) -> bool:
        if not self.circle_ttr_active:
            return False
        self.circle_ttr_active = False
        self._snap_kind = ""
        self._circle_ttr_sources.clear()
        self._circle_ttr_revision = None
        self.selected_entity_ids.clear()
        self.message = "已取消 TTR 圆；草稿未变。"
        self.changed.emit()
        self.update()
        return True

    @property
    def circle_ttr_radius_pending(self) -> bool:
        return self.circle_ttr_active and len(self._circle_ttr_sources) == 2

    def _pick_circle_ttr_source(self, point: Point2D) -> None:
        if self.circle_ttr_radius_pending:
            self.message = "圆 TTR：请输入半径。"
        else:
            identity = self._hit_entity_at(point)
            entity = next(
                (item for item in self.selectable_entities() if item.entity_id == identity), None
            )
            if not isinstance(entity, LineEntity | CircleEntity | ArcEntity):
                self.message = "圆 TTR：请选择直线、圆或圆弧。"
            elif any(item.entity_id == entity.entity_id for item, _ in self._circle_ttr_sources):
                self.message = "圆 TTR：请选择两个不同对象。"
            else:
                self._circle_ttr_sources.append((entity, point))
                self._snap_kind = ""
                self.selected_entity_ids.add(entity.entity_id)
                self.message = (
                    (
                        f"圆 TTR：输入半径或按 Enter 使用 {self.circle_ttr_last_radius:g}。"
                        if self.circle_ttr_last_radius is not None
                        else "圆 TTR：请输入大于零的半径。"
                    )
                    if self.circle_ttr_radius_pending
                    else "圆 TTR：请选择第二个切线对象。"
                )
        self.changed.emit()
        self.update()

    def finish_circle_ttr(self, radius: float) -> bool:
        """Validate and append the TTR circle as one undoable draft operation."""
        if not self.circle_ttr_radius_pending:
            self.message = "圆 TTR：请先选择两个对象。"
            return False
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或已锁定，无法创建圆。"
            return False
        if (
            self._circle_ttr_revision is not None
            and self.source_revision_provider is not None
            and self.source_revision_provider() != self._circle_ttr_revision
        ) or any(
            entity not in self.selectable_entities() for entity, _ in self._circle_ttr_sources
        ):
            self.message = "来源已变化；请按 Esc 后重新选择对象。"
            return False
        (first, first_pick), (second, second_pick) = self._circle_ttr_sources
        try:
            available = (*self.entities, *(entity for entity, _layer in self.background_entities))
            if any(
                sum(item.entity_id == source.entity_id for item in available) != 1
                for source in (first, second)
            ):
                raise ValueError("来源图元身份不唯一；请重新选择。")
            circle = circle_ttr(
                first,
                second,
                first_pick,
                second_pick,
                radius,
                uuid4().hex,
                construction=self.construction,
                layer_name=self.active_layer_name,
            )
        except ValueError as exc:
            self.message = str(exc)
            return False
        try:
            relations = self._fillet_tangent_relations(circle, (first, second))
            pending = self._fillet_cross_pairs(circle, (first, second))
        except ValueError as exc:
            self.message = str(exc)
            return False
        if not self.replace_draft_entities((*self.entities, circle), new_relations=relations):
            return False
        self.pending_cross_tangencies.extend(pending)
        self.circle_ttr_active = False
        self.circle_ttr_last_radius = radius
        self._circle_ttr_sources.clear()
        self._circle_ttr_revision = None
        self.selected_entity_ids.clear()
        self.message = "TTR 圆已创建；" + (
            "对象相切将在完成绘图时建立。"
            if pending
            else "已建立对象相切约束。"
            if relations
            else "未建立相切约束。"
        )
        self.changed.emit()
        self.update()
        return True

    def undo_fillet(self) -> bool:
        """Undo only edits made since this fillet command was activated."""
        if self.tool == "二维倒角":
            return self.undo_line_edit_action()
        if (
            not self.has_active_edit_gesture
            and self._line_edit_undo_actions
            and self._line_edit_undo_actions[-1][0] == "saved"
            and self._line_edit_undo_actions[-1][1] == self.history_position
        ):
            return self.undo_line_edit_action()
        if self.has_active_edit_gesture or len(self._undo_history) <= self._fillet_undo_floor:
            self.message = "没有可撤销的圆角；请先完成或取消当前选取。"
            self.changed.emit()
            return False
        result = self.undo_last_operation()
        self.message = "已撤销上一个圆角。" if result else "没有可撤销的圆角。"
        self.changed.emit()
        return result

    def sync_chamfer_values(self, values: tuple[float, float, float, float]) -> None:
        """Restore drawing-owned values while preserving the selected input method."""
        first, second, length, angle = values
        self.chamfer_distance_first = first
        self.chamfer_second_distance = second
        self.chamfer_angle_length = length
        self.chamfer_last_angle = angle
        self.chamfer_first_distance = length if self.chamfer_angle is not None else first
        if self.chamfer_angle is not None:
            self.chamfer_angle = angle

    def set_chamfer_values(self, values: tuple[float, float, float, float]) -> None:
        current = (
            self.chamfer_distance_first,
            self.chamfer_second_distance,
            self.chamfer_angle_length,
            self.chamfer_last_angle,
        )
        if values != current and self.persist_chamfer_values is not None:
            revision = self.source_revision_provider() if self.source_revision_provider else None
            self.persist_chamfer_values(values)
            if revision is not None and self.source_revision_provider is not None:
                self.acknowledge_fillet_setting_revision(revision, self.source_revision_provider())
        self.sync_chamfer_values(values)

    def set_circle_fillet_radius(self, radius: float) -> None:
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("圆角半径必须是非负的有限数值。")
        if radius != self.circle_fillet_radius and self.persist_fillet_radius is not None:
            revision = self.source_revision_provider() if self.source_revision_provider else None
            self.persist_fillet_radius(radius)
            if revision is not None and self.source_revision_provider is not None:
                self.acknowledge_fillet_setting_revision(revision, self.source_revision_provider())
        self.circle_fillet_radius = radius
        self._fillet_radius_anchor = None
        target = "第二个对象" if self._circle_fillet_first is not None else "第一个对象"
        action = (
            f"选择{target}" if self._circle_fillet_first is not None else "选择第一个对象或拖过两边"
        )
        self.message = f"二维圆角（圆不修剪，R={radius:g}）：{action}；M 连续。"
        self.changed.emit()

    def acknowledge_fillet_setting_revision(self, previous: int, current: int) -> None:
        """Retain geometry-only selections and draft history after a settings-only write."""
        if current != previous + 1:
            return
        if self._fillet_source_revision == previous:
            self._fillet_source_revision = current
        if self.source_context_revision == previous:
            self.source_context_revision = current
        self._line_edit_undo_actions = [
            (
                kind,
                position,
                identity,
                current if kind == "saved" and revision == previous else revision,
            )
            for kind, position, identity, revision in self._line_edit_undo_actions
        ]
        mixed = self.mixed_move
        if mixed is None or mixed.source_revision != previous or not self.mixed_move_is_valid:
            return
        self.mixed_move = replace(mixed, source_revision=current)

        def rebase(state: _DraftState) -> _DraftState:
            old = state.mixed_move
            if (
                old is not None
                and old.transaction_id == mixed.transaction_id
                and old.source_revision == previous
            ):
                return replace(state, mixed_move=replace(old, source_revision=current))
            return state

        self._undo_history = [rebase(state) for state in self._undo_history]
        self._redo_history = [rebase(state) for state in self._redo_history]

    @property
    def circle_fillet_radius_measuring(self) -> bool:
        return self._fillet_radius_anchor is not None

    def begin_circle_fillet_radius(self) -> None:
        self._fillet_radius_anchor = None
        self.circle_fillet_radius_pending = True

    def set_circle_fillet_radius_point(self, point: Point2D) -> None:
        if self.tool != "二维圆角" or not self.circle_fillet_radius_pending:
            raise ValueError("圆角半径量距已结束。")
        if not all(math.isfinite(value) for value in point):
            raise ValueError("量距点坐标必须有限。")
        if self._fillet_radius_anchor is None:
            self._fillet_radius_anchor = point
            self.message = "二维圆角：指定量距第二点；Esc 取消。"
            self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        distance = math.dist(self._fillet_radius_anchor, point)
        if not math.isfinite(distance):
            raise ValueError("圆角半径超出可用范围。")
        self.circle_fillet_radius_pending = False
        try:
            self.set_circle_fillet_radius(distance)
        except ValueError:
            self.circle_fillet_radius_pending = True
            raise
        self.point_accepted.emit(point)
        self.update()

    def _apply_chamfer_polyline(
        self,
        entity: PolylineEntity,
        *,
        corners: tuple[int, ...] | None = None,
        reverse: bool = False,
        temporary_zero: bool = False,
    ) -> None:
        layer = self.layer_table.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("多段线所在图层隐藏或已锁定。")
        first = 0.0 if temporary_zero else self.chamfer_first_distance
        second = 0.0 if temporary_zero else self.chamfer_second_distance
        trim = temporary_zero or self.chamfer_trim
        revised, edges = polyline_chamfer(
            entity,
            first,
            second,
            tuple(uuid4().hex for _ in entity.points_mm),
            angle_deg=None if temporary_zero else self.chamfer_angle,
            trim=trim,
            corner_indices=corners,
            reverse=reverse,
        )
        if (
            revised == entity
            and not edges
            and (
                first != 0
                or (not temporary_zero and self.chamfer_angle is None and second != 0)
                or (not temporary_zero and self.chamfer_angle not in (None, 0))
            )
        ):
            raise ValueError("没有可倒角的直线角点。")
        if not trim:
            if not edges:
                raise ValueError("没有可倒角的直线角点。")
            if self.replace_draft_entities((*self.entities, *edges)):
                self.chamfer_polyline_pending = False
                self._chamfer_first = None
                self._chamfer_segment = None
                self._fillet_source_revision = None
                self.message = "已创建多段线倒角线；可撤销。"
                self._complete_fillet_command()
        else:
            self.chamfer_polyline_pending = False
            self._apply_fillet_replacements((entity,), (revised,), None, tangent_sources=())

    @staticmethod
    def _chamfer_rectangle_path(entity: RectangleEntity) -> PolylineEntity:
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        return PolylineEntity(
            entity.entity_id,
            ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
            closed=True,
            construction=entity.construction,
            layer_name=entity.layer_name,
        )

    def _apply_chamfer_rectangle(
        self,
        entity: RectangleEntity,
        *,
        corners: tuple[int, ...] | None = None,
        reverse: bool = False,
        temporary_zero: bool = False,
    ) -> None:
        layer = self.layer_table.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("矩形所在图层隐藏或已锁定。")
        trim = temporary_zero or self.chamfer_trim
        revised, edges = rectangle_chamfer(
            entity,
            0.0 if temporary_zero else self.chamfer_first_distance,
            0.0 if temporary_zero else self.chamfer_second_distance,
            uuid4().hex,
            tuple(uuid4().hex for _ in range(4)),
            angle_deg=None if temporary_zero else self.chamfer_angle,
            trim=trim,
            corner_indices=corners,
            reverse=reverse,
        )
        if trim:
            if len(revised.points_mm) == 4:
                if temporary_zero or (
                    self.chamfer_first_distance == 0
                    and (
                        self.chamfer_angle == 0
                        or (self.chamfer_angle is None and self.chamfer_second_distance == 0)
                    )
                ):
                    self.chamfer_polyline_pending = False
                    self._chamfer_first = None
                    self.message = self._unchanged_corner_message(temporary_zero=temporary_zero)
                    self._complete_fillet_command()
                    return
                raise ValueError("矩形没有可倒角的角点。")
            self.chamfer_polyline_pending = False
            self._apply_fillet_replacements((entity,), (revised,), None, tangent_sources=())
        elif edges and self.replace_draft_entities((*self.entities, *edges)):
            self.chamfer_polyline_pending = False
            self._chamfer_first = None
            self._chamfer_segment = None
            self.message = "已创建矩形倒角线；源对象保持不变。"
            self._complete_fillet_command()
        elif not edges:
            raise ValueError("矩形没有可倒角的角点。")

    def _chamfer_pick(self, point: Point2D, *, temporary_zero: bool = False) -> None:
        identity = self._hit_entity_at(point)
        entity = next(
            (item for item in self.selectable_entities() if item.entity_id == identity), None
        )
        try:
            if self.chamfer_polyline_pending:
                if isinstance(entity, RectangleEntity):
                    self._apply_chamfer_rectangle(entity, temporary_zero=temporary_zero)
                elif isinstance(entity, PolylineEntity):
                    self._apply_chamfer_polyline(entity, temporary_zero=temporary_zero)
                else:
                    raise ValueError("请选择多段线或矩形。")
            elif not isinstance(entity, LineEntity | PolylineEntity | RectangleEntity):
                raise ValueError("请选择直线或多段线段。")
            elif self._chamfer_first is None:
                self._chamfer_first = (entity, point)
                self._chamfer_segment = (
                    self._fillet_polyline_segment_at(
                        self._chamfer_rectangle_path(entity)
                        if isinstance(entity, RectangleEntity)
                        else entity,
                        point,
                    )
                    if isinstance(entity, PolylineEntity | RectangleEntity)
                    else None
                )
                self._fillet_source_revision = (
                    self.source_revision_provider() if self.source_revision_provider else None
                )
                self.selected_entity_ids = {entity.entity_id}
                self.message = "二维倒角：选择第二条直线或相邻多段线段；Shift 临时交角。"
            else:
                first, first_pick = self._chamfer_first
                if first not in self.selectable_entities() or (
                    self._fillet_source_revision is not None
                    and self.source_revision_provider is not None
                    and self.source_revision_provider() != self._fillet_source_revision
                ):
                    raise ValueError("文档或第一条直线已变化，请重新选择。")
                if isinstance(first, RectangleEntity) and entity == first:
                    if self._chamfer_segment is None:
                        raise ValueError("请选择同一矩形的相邻边。")
                    first_index = self._chamfer_segment
                    second_index = self._fillet_polyline_segment_at(
                        self._chamfer_rectangle_path(first), point
                    )
                    if second_index == (first_index + 1) % 4:
                        corner, reverse = second_index, False
                    elif first_index == (second_index + 1) % 4:
                        corner, reverse = first_index, True
                    else:
                        raise ValueError("请选择同一矩形的相邻边。")
                    self._apply_chamfer_rectangle(
                        first, corners=(corner,), reverse=reverse, temporary_zero=temporary_zero
                    )
                elif isinstance(first, PolylineEntity) and entity == first:
                    if not isinstance(entity, PolylineEntity) or self._chamfer_segment is None:
                        raise ValueError("请选择同一多段线的相邻直线段。")
                    first_index = self._chamfer_segment
                    second_index = self._fillet_polyline_segment_at(entity, point)
                    count = len(entity.points_mm)
                    segment_count = count if entity.closed else count - 1
                    closes = not entity.closed and {first_index, second_index} == {
                        0,
                        segment_count - 1,
                    }
                    if closes and segment_count <= 3:
                        start_pick, end_pick = (
                            (first_pick, point) if first_index == 0 else (point, first_pick)
                        )

                        def ratio(p: Point2D, a: Point2D, b: Point2D) -> float:
                            dx, dy = b[0] - a[0], b[1] - a[1]
                            return min(
                                1.0,
                                max(
                                    0.0,
                                    ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy),
                                ),
                            )

                        start_ratio = ratio(start_pick, entity.points_mm[0], entity.points_mm[1])
                        end_ratio = ratio(end_pick, entity.points_mm[-2], entity.points_mm[-1])
                        closes = start_ratio + (1 - end_ratio) < 0.95
                    if closes:
                        layer = self.layer_table.get(first.layer_name)
                        if layer.locked or not layer.displayed:
                            raise ValueError("多段线所在图层隐藏或已锁定。")
                        trim = temporary_zero or self.chamfer_trim
                        revised, edge = polyline_chamfer_close(
                            first,
                            first_index,
                            second_index,
                            first_pick,
                            point,
                            0.0 if temporary_zero else self.chamfer_first_distance,
                            0.0 if temporary_zero else self.chamfer_second_distance,
                            uuid4().hex,
                            angle_deg=None if temporary_zero else self.chamfer_angle,
                            trim=trim,
                        )
                        if trim:
                            self._apply_fillet_replacements(
                                (first,), (revised,), None, tangent_sources=()
                            )
                        elif edge is not None and self.replace_draft_entities(
                            (*self.entities, edge)
                        ):
                            self._chamfer_first = None
                            self._chamfer_segment = None
                            self._fillet_source_revision = None
                            self.message = "已创建倒角线；源对象保持不变。"
                            self._complete_fillet_command()
                        self.changed.emit()
                        self.update()
                        return
                    if second_index == first_index + 1 or (
                        entity.closed and first_index == count - 1 and second_index == 0
                    ):
                        corner, reverse = second_index, False
                    elif first_index == second_index + 1 or (
                        entity.closed and second_index == count - 1 and first_index == 0
                    ):
                        corner, reverse = first_index, True
                    elif (not entity.closed and abs(first_index - second_index) == 2) or (
                        entity.closed
                        and (
                            (first_index + 2) % count == second_index
                            or (second_index + 2) % count == first_index
                        )
                    ):
                        layer = self.layer_table.get(first.layer_name)
                        if layer.locked or not layer.displayed:
                            raise ValueError("多段线所在图层隐藏或已锁定。")
                        trim = temporary_zero or self.chamfer_trim
                        revised, edge = polyline_chamfer_between(
                            first,
                            first_index,
                            second_index,
                            first_pick,
                            point,
                            0.0 if temporary_zero else self.chamfer_first_distance,
                            0.0 if temporary_zero else self.chamfer_second_distance,
                            uuid4().hex,
                            angle_deg=None if temporary_zero else self.chamfer_angle,
                            trim=trim,
                        )
                        if trim:
                            self._apply_fillet_replacements(
                                (first,), (revised,), None, tangent_sources=()
                            )
                        elif edge is not None and self.replace_draft_entities(
                            (*self.entities, edge)
                        ):
                            self._chamfer_first = None
                            self._chamfer_segment = None
                            self._fillet_source_revision = None
                            self.message = "已创建倒角线；源对象保持不变。"
                            self._complete_fillet_command()
                        self.changed.emit()
                        self.update()
                        return
                    else:
                        raise ValueError("请选择相邻直线段或间隔一段的直线段。")
                    self._apply_chamfer_polyline(
                        first, corners=(corner,), reverse=reverse, temporary_zero=temporary_zero
                    )
                elif isinstance(first, PolylineEntity | RectangleEntity) or isinstance(
                    entity, PolylineEntity | RectangleEntity
                ):
                    layer_name = (
                        first.layer_name
                        if first.layer_name.casefold() == entity.layer_name.casefold()
                        else self.active_layer_name
                    )
                    layer = self.layer_table.get(layer_name)
                    if layer.locked or not layer.displayed:
                        raise ValueError("倒角目标图层隐藏或已锁定。")
                    first_path = (
                        self._chamfer_rectangle_path(first)
                        if isinstance(first, RectangleEntity)
                        else first
                    )
                    second_path = (
                        self._chamfer_rectangle_path(entity)
                        if isinstance(entity, RectangleEntity)
                        else entity
                    )
                    second_index = (
                        self._fillet_polyline_segment_at(second_path, point)
                        if isinstance(second_path, PolylineEntity)
                        else None
                    )
                    trim = temporary_zero or self.chamfer_trim
                    joined, edge = chamfer_joined_paths(
                        first_path,
                        self._chamfer_segment,
                        second_path,
                        second_index,
                        first_pick,
                        point,
                        0.0 if temporary_zero else self.chamfer_first_distance,
                        0.0 if temporary_zero else self.chamfer_second_distance,
                        uuid4().hex,
                        angle_deg=None if temporary_zero else self.chamfer_angle,
                        trim=trim,
                        layer_name=layer_name,
                    )
                    if trim:
                        assert joined is not None
                        polyline = (
                            first if isinstance(first, PolylineEntity | RectangleEntity) else entity
                        )
                        other = entity if polyline is first else first
                        assert isinstance(polyline, PolylineEntity | RectangleEntity)
                        if isinstance(polyline, RectangleEntity):
                            joined = replace(joined, entity_id=uuid4().hex)
                        self._apply_joined_polyline_fillet(polyline, other, joined)
                    else:
                        assert edge is not None
                        if self.replace_draft_entities((*self.entities, edge)):
                            self._chamfer_first = None
                            self._chamfer_segment = None
                            self._fillet_source_revision = None
                            self.message = "已创建倒角线；源对象保持不变。"
                            self._complete_fillet_command()
                else:
                    assert isinstance(first, LineEntity) and isinstance(entity, LineEntity)
                    layer_name = (
                        first.layer_name
                        if first.layer_name.casefold() == entity.layer_name.casefold()
                        else self.active_layer_name
                    )
                    layer = self.layer_table.get(layer_name)
                    if layer.locked or not layer.displayed:
                        raise ValueError("倒角目标图层隐藏或已锁定。")
                    a, b, edge = line_chamfer(
                        first,
                        entity,
                        first_pick,
                        point,
                        0.0 if temporary_zero else self.chamfer_first_distance,
                        0.0 if temporary_zero else self.chamfer_second_distance,
                        uuid4().hex,
                        angle_deg=None if temporary_zero else self.chamfer_angle,
                        trim=True if temporary_zero else self.chamfer_trim,
                        layer_name=layer_name,
                    )
                    self._apply_fillet_replacements(
                        (first, entity), (a, b), edge, tangent_sources=()
                    )
        except ValueError as exc:
            self.message = str(exc)
        self.changed.emit()
        self.update()

    def _rectangle_fillet_pick(
        self, entity: SketchEntity | None, point: Point2D, *, temporary_zero: bool
    ) -> None:
        try:
            if self._circle_fillet_first is not None:
                first, first_pick = self._circle_fillet_first
                if (
                    self._fillet_source_revision is not None
                    and self.source_revision_provider is not None
                    and self.source_revision_provider() != self._fillet_source_revision
                ):
                    raise ValueError("文档已变化；请按 Esc 后重新选择对象。")
                if first not in self.selectable_entities():
                    raise ValueError("第一个对象已失效，请按 Esc 后重新选择。")
                if (isinstance(first, RectangleEntity) and isinstance(entity, LineEntity)) or (
                    isinstance(first, LineEntity) and isinstance(entity, RectangleEntity)
                ):
                    if isinstance(first, RectangleEntity) and isinstance(entity, LineEntity):
                        rectangle, line = first, entity
                        rectangle_pick, line_pick = first_pick, point
                        index = self._circle_fillet_segment
                    else:
                        assert isinstance(entity, RectangleEntity)
                        assert isinstance(first, LineEntity)
                        rectangle, line = entity, first
                        rectangle_pick, line_pick = point, first_pick
                        index = self._fillet_polyline_segment_at(
                            self._chamfer_rectangle_path(rectangle), point
                        )
                    if index is None:
                        raise ValueError("矩形边已失效；请重新选择。")
                    path = self._chamfer_rectangle_path(rectangle)
                    radius = 0.0 if temporary_zero else self.circle_fillet_radius
                    if temporary_zero or self.circle_fillet_trim:
                        joined = polyline_line_fillet(
                            path, index, line, rectangle_pick, line_pick, radius
                        )
                        self._apply_joined_polyline_fillet(
                            rectangle, line, replace(joined, entity_id=uuid4().hex)
                        )
                    else:
                        self._finish_external_polyline_notrim(
                            rectangle, index, rectangle_pick, line, None, line_pick, radius
                        )
                    self.changed.emit()
                    self.update()
                    return
                if (
                    isinstance(first, RectangleEntity)
                    and isinstance(entity, CircleEntity | ArcEntity)
                ) or (
                    isinstance(first, CircleEntity | ArcEntity)
                    and isinstance(entity, RectangleEntity)
                ):
                    if isinstance(first, RectangleEntity) and isinstance(
                        entity, CircleEntity | ArcEntity
                    ):
                        rectangle, circular = first, entity
                        rectangle_pick, circular_pick = first_pick, point
                        index = self._circle_fillet_segment
                    else:
                        assert isinstance(entity, RectangleEntity)
                        assert isinstance(first, CircleEntity | ArcEntity)
                        rectangle, circular = entity, first
                        rectangle_pick, circular_pick = point, first_pick
                        index = self._fillet_polyline_segment_at(
                            self._chamfer_rectangle_path(rectangle), point
                        )
                    if index is None:
                        raise ValueError("矩形边已失效；请重新选择。")
                    path = self._chamfer_rectangle_path(rectangle)
                    radius = 0.0 if temporary_zero else self.circle_fillet_radius
                    layer_name = (
                        rectangle.layer_name
                        if rectangle.layer_name.casefold() == circular.layer_name.casefold()
                        else self.active_layer_name
                    )
                    layer = self.layer_table.get(layer_name)
                    if radius > 0 and (layer.locked or not layer.displayed):
                        raise ValueError("圆角目标图层隐藏或已锁定。")
                    if temporary_zero or self.circle_fillet_trim:
                        result, target, arc, result_index = polyline_circular_fillet(
                            path,
                            index,
                            circular,
                            rectangle_pick,
                            circular_pick,
                            radius,
                            layer_name=layer_name,
                        )
                        result = replace(result, entity_id=uuid4().hex)
                        rectangle_sources: tuple[
                            LineEntity | ArcEntity | PolylineEntity | RectangleEntity, ...
                        ] = (rectangle,)
                        rectangle_results: tuple[LineEntity | ArcEntity | PolylineEntity, ...] = (
                            result,
                        )
                        if isinstance(circular, ArcEntity):
                            assert isinstance(target, ArcEntity)
                            rectangle_sources += (circular,)
                            rectangle_results += (target,)
                        self._apply_fillet_replacements(
                            rectangle_sources,
                            rectangle_results,
                            arc,
                            tangent_sources=(),
                            indexed_sources=(
                                (
                                    result,
                                    SketchGeometryReference(
                                        result.entity_id, "segment", result_index
                                    ),
                                ),
                                (
                                    target,
                                    SketchGeometryReference(target.entity_id, "geometry"),
                                ),
                            ),
                        )
                    else:
                        self._finish_external_polyline_notrim(
                            rectangle, index, rectangle_pick, circular, None, circular_pick, radius
                        )
                    self.changed.emit()
                    self.update()
                    return
                if (
                    isinstance(first, PolylineEntity | RectangleEntity)
                    and isinstance(entity, PolylineEntity | RectangleEntity)
                    and first.entity_id != entity.entity_id
                ):
                    first_path = (
                        self._chamfer_rectangle_path(first)
                        if isinstance(first, RectangleEntity)
                        else first
                    )
                    second_path = (
                        self._chamfer_rectangle_path(entity)
                        if isinstance(entity, RectangleEntity)
                        else entity
                    )
                    first_index = self._circle_fillet_segment
                    second_index = self._fillet_polyline_segment_at(second_path, point)
                    if first_index is None:
                        raise ValueError("第一个路径段已失效；请重新选择。")
                    radius = 0.0 if temporary_zero else self.circle_fillet_radius
                    if temporary_zero or self.circle_fillet_trim:
                        joined = polyline_polyline_fillet(
                            first_path,
                            first_index,
                            second_path,
                            second_index,
                            first_pick,
                            point,
                            radius,
                        )
                        if isinstance(first, RectangleEntity):
                            joined = replace(joined, entity_id=uuid4().hex)
                        self._apply_joined_polyline_fillet(first, entity, joined)
                    else:
                        self._finish_external_polyline_notrim(
                            first,
                            first_index,
                            first_pick,
                            entity,
                            second_index,
                            point,
                            radius,
                        )
                    self.changed.emit()
                    self.update()
                    return
            if not isinstance(entity, RectangleEntity):
                raise ValueError("请选择同一矩形的另一条边。")
            path = self._chamfer_rectangle_path(entity)
            segment_index = self._fillet_polyline_segment_at(path, point)
            if self._circle_fillet_first is None:
                self._fillet_candidate_pending = False
                self._fillet_pending_cross_candidate = ()
                self._circle_fillet_first = (entity, point)
                self._circle_fillet_segment = segment_index
                self._fillet_source_revision = (
                    self.source_revision_provider() if self.source_revision_provider else None
                )
                self.selected_entity_ids = {entity.entity_id}
                self.message = "二维圆角：请选择矩形的另一条边；Esc 取消。"
            else:
                first, first_pick = self._circle_fillet_first
                if first != entity or self._circle_fillet_segment is None:
                    raise ValueError("请选择同一矩形的另一条边。")
                if (
                    self._fillet_source_revision is not None
                    and self.source_revision_provider is not None
                    and self.source_revision_provider() != self._fillet_source_revision
                ):
                    raise ValueError("文档已变化；请按 Esc 后重新选择对象。")
                trim = temporary_zero or self.circle_fillet_trim
                result, arc = polyline_segment_fillet(
                    path,
                    self._circle_fillet_segment,
                    segment_index,
                    0.0 if temporary_zero else self.circle_fillet_radius,
                    trim=trim,
                    first_pick=first_pick,
                    second_pick=point,
                )
                if trim and result != path:
                    self._apply_fillet_replacements(
                        (entity,),
                        (replace(result, entity_id=uuid4().hex),),
                        None,
                        tangent_sources=(),
                    )
                elif trim:
                    self._circle_fillet_first = None
                    self._circle_fillet_segment = None
                    self._fillet_source_revision = None
                    self.message = self._unchanged_corner_message(temporary_zero=temporary_zero)
                    self._complete_fillet_command()
                elif arc is not None:
                    layer = self._layer(entity)
                    if layer.locked or not layer.displayed:
                        raise ValueError("圆角目标图层隐藏或已锁定。")
                    relations, pending = self._fillet_indexed_relations(
                        arc,
                        (
                            (
                                entity,
                                SketchGeometryReference(
                                    entity.entity_id, "segment", self._circle_fillet_segment
                                ),
                            ),
                            (
                                entity,
                                SketchGeometryReference(entity.entity_id, "segment", segment_index),
                            ),
                        ),
                    )
                    if self.replace_draft_entities((*self.entities, arc), new_relations=relations):
                        self.pending_cross_tangencies.extend(pending)
                        self._circle_fillet_first = None
                        self._circle_fillet_segment = None
                        self._fillet_source_revision = None
                        self.message = "圆角已创建；原矩形保留。"
                        self._complete_fillet_command()
        except ValueError as exc:
            self.message = str(exc)

    def fillet_open_polyline_ends(self) -> bool:
        """Apply the Polyline option after a first open-polyline segment was picked."""
        selected = self._circle_fillet_first
        if selected is None or not isinstance(selected[0], PolylineEntity):
            return False
        source = selected[0]
        try:
            if source.closed:
                raise ValueError("该多段线已闭合；请选择开放多段线。")
            if source not in self.selectable_entities() or (
                self._fillet_source_revision is not None
                and self.source_revision_provider is not None
                and self.source_revision_provider() != self._fillet_source_revision
            ):
                raise ValueError("多段线来源已变化；请按 Esc 后重新选择。")
            count = len(source.points_mm) - 1
            if count < 2:
                raise ValueError("开放多段线至少需要两段才能闭合。")
            result, arc = polyline_segment_fillet(
                source,
                0,
                count - 1,
                self.circle_fillet_radius,
                trim=self.circle_fillet_trim,
                first_pick=source.points_mm[0],
                second_pick=source.points_mm[-1],
            )
            if self.circle_fillet_trim:
                if result == source:
                    raise ValueError("所选多段线圆角无需更改。")
                self._apply_fillet_replacements((source,), (result,), None, tangent_sources=())
            elif arc is not None:
                layer = self._layer(source)
                if layer.locked or not layer.displayed:
                    raise ValueError("圆角目标图层隐藏或已锁定。")
                relations, pending = self._fillet_indexed_relations(
                    arc,
                    tuple(
                        (source, SketchGeometryReference(source.entity_id, "segment", index))
                        for index in (0, count - 1)
                    ),
                )
                if self.replace_draft_entities((*self.entities, arc), new_relations=relations):
                    self.pending_cross_tangencies.extend(pending)
                    self._circle_fillet_first = None
                    self._circle_fillet_segment = None
                    self._fillet_source_revision = None
                    self.selected_entity_ids.clear()
                    self.message = "圆角已创建；原多段线保留。"
                    self._complete_fillet_command()
        except ValueError as exc:
            self.message = str(exc)
        self.changed.emit()
        self.update()
        return True

    def _circle_fillet_pick(self, point: Point2D, *, temporary_zero: bool = False) -> None:
        if self.circle_fillet_trim_pending:
            self.message = "请先在命令栏选择修剪或不修剪。"
        elif self.circle_fillet_radius_pending:
            try:
                measured, _kind = self._placement_point(
                    point, temporarily_disable_snapping=temporary_zero
                )
                self.set_circle_fillet_radius_point(measured)
            except ValueError as exc:
                self.message = str(exc)
        else:
            identity = self._hit_entity_at(point)
            entity = next(
                (item for item in self.selectable_entities() if item.entity_id == identity), None
            )
            if self.circle_fillet_polyline_pending:
                if not isinstance(entity, PolylineEntity | RectangleEntity):
                    self.message = "请选择多段线或矩形；Esc 取消。"
                elif temporary_zero or self.circle_fillet_trim:
                    try:
                        path = (
                            self._chamfer_rectangle_path(entity)
                            if isinstance(entity, RectangleEntity)
                            else entity
                        )
                        vertices, bulges = polyline_fillet_trimmed_segments(
                            path, 0.0 if temporary_zero else self.circle_fillet_radius
                        )
                        if isinstance(entity, RectangleEntity) and not any(bulges):
                            rounded = entity
                        else:
                            rounded = replace(
                                path,
                                entity_id=uuid4().hex
                                if isinstance(entity, RectangleEntity)
                                else path.entity_id,
                                points_mm=vertices,
                                bulges=bulges,
                            )
                        if rounded == entity:
                            self.message = self._unchanged_corner_message(
                                temporary_zero=temporary_zero
                            )
                            self.circle_fillet_polyline_pending = False
                            self._complete_fillet_command()
                        else:
                            assert isinstance(rounded, PolylineEntity)
                            self._apply_fillet_replacements(
                                (entity,), (rounded,), None, tangent_sources=()
                            )
                    except ValueError as exc:
                        self.message = str(exc)
                else:
                    try:
                        if self.circle_fillet_radius == 0:
                            raise ValueError("零半径多段线圆角需要修剪模式。")
                        layer = self._layer(entity)
                        if layer.locked or not layer.displayed:
                            raise ValueError("圆角目标图层隐藏或已锁定。")
                        arcs = polyline_fillet_notrim(
                            self._chamfer_rectangle_path(entity)
                            if isinstance(entity, RectangleEntity)
                            else entity,
                            self.circle_fillet_radius,
                            layer_name=entity.layer_name,
                        )
                        all_relations: list[SketchConstraint] = []
                        all_pending: list[DraftTangentPair] = []
                        unbound_arcs = 0
                        if isinstance(entity, RectangleEntity):
                            path = self._chamfer_rectangle_path(entity)
                            segments = polyline_curve_segments(
                                path.points_mm, (0.0,) * 4, True, path.entity_id
                            )
                            for arc in arcs:
                                indices = [
                                    index
                                    for index, segment in enumerate(segments)
                                    if tangent_on_curves(segment, arc)
                                ]
                                if len(indices) != 2:
                                    raise ValueError("无法唯一确定矩形圆角的两条来源边。")
                                relations, pending = self._fillet_indexed_relations(
                                    arc,
                                    tuple(
                                        (
                                            entity,
                                            SketchGeometryReference(
                                                entity.entity_id, "segment", index
                                            ),
                                        )
                                        for index in indices
                                    ),
                                )
                                all_relations.extend(relations)
                                all_pending.extend(pending)
                        elif self._auto_inference_enabled:
                            segment_count = (
                                len(entity.points_mm)
                                if entity.closed
                                else len(entity.points_mm) - 1
                            )
                            segments = polyline_curve_segments(
                                entity.points_mm,
                                entity.bulges or (0.0,) * segment_count,
                                entity.closed,
                                entity.entity_id,
                                construction=entity.construction,
                                layer_name=entity.layer_name,
                            )
                            source_pairs = _whole_fillet_source_pairs(
                                segments, arcs, closed=entity.closed
                            )
                            for arc, pair in zip(arcs, source_pairs, strict=True):
                                if pair is None:
                                    unbound_arcs += 1
                                    continue
                                relations, pending = self._fillet_indexed_relations(
                                    arc,
                                    tuple(
                                        (
                                            entity,
                                            SketchGeometryReference(
                                                entity.entity_id, "segment", index
                                            ),
                                        )
                                        for index in pair
                                    ),
                                )
                                all_relations.extend(relations)
                                all_pending.extend(pending)
                    except ValueError as exc:
                        self.message = str(exc)
                    else:
                        if self.replace_draft_entities(
                            (*self.entities, *arcs), new_relations=tuple(all_relations)
                        ):
                            self.pending_cross_tangencies.extend(all_pending)
                            self.circle_fillet_polyline_pending = False
                            self.message = (
                                f"多段线圆角已创建；原对象保留，{unbound_arcs} 个圆角来源不唯一或不在原段上，未自动建立相切。"
                                if unbound_arcs
                                else "多段线圆角已创建；原对象保留。"
                            )
                            self._complete_fillet_command()
            elif isinstance(entity, RectangleEntity) or (
                self._circle_fillet_first is not None
                and isinstance(self._circle_fillet_first[0], RectangleEntity)
            ):
                self._rectangle_fillet_pick(entity, point, temporary_zero=temporary_zero)
            elif isinstance(entity, PolylineEntity) or (
                self._circle_fillet_first is not None
                and isinstance(self._circle_fillet_first[0], PolylineEntity)
            ):
                try:
                    if not isinstance(
                        entity, PolylineEntity | LineEntity | CircleEntity | ArcEntity
                    ):
                        raise ValueError("请选择直线、圆、圆弧或多段线段。")
                    segment_index = (
                        self._fillet_polyline_segment_at(entity, point)
                        if isinstance(entity, PolylineEntity)
                        else None
                    )
                    if self._circle_fillet_first is None:
                        assert isinstance(entity, PolylineEntity) and segment_index is not None
                        self._fillet_candidate_pending = False
                        self._fillet_pending_cross_candidate = ()
                        self._circle_fillet_first = (entity, point)
                        self._circle_fillet_segment = segment_index
                        self._fillet_source_revision = (
                            self.source_revision_provider()
                            if self.source_revision_provider
                            else None
                        )
                        self.selected_entity_ids = {entity.entity_id}
                        self.message = "二维圆角：请选择第二个对象或多段线段；Esc 取消。"
                    else:
                        first, first_pick = self._circle_fillet_first
                        if (
                            self._fillet_source_revision is not None
                            and self.source_revision_provider is not None
                            and self.source_revision_provider() != self._fillet_source_revision
                        ):
                            raise ValueError("文档已变化；请按 Esc 后重新选择对象。")
                        use_trim = temporary_zero or self.circle_fillet_trim
                        radius = 0.0 if temporary_zero else self.circle_fillet_radius
                        if not (
                            isinstance(first, PolylineEntity)
                            and isinstance(entity, PolylineEntity)
                            and first.entity_id == entity.entity_id
                        ):
                            if first not in self.selectable_entities():
                                raise ValueError("第一个对象已失效，请按 Esc 后重新选择。")
                            if use_trim:
                                if isinstance(first, PolylineEntity) and isinstance(
                                    entity, PolylineEntity
                                ):
                                    if self._circle_fillet_segment is None or segment_index is None:
                                        raise ValueError("多段线段已失效；请重新选择。")
                                    joined = polyline_polyline_fillet(
                                        first,
                                        self._circle_fillet_segment,
                                        entity,
                                        segment_index,
                                        first_pick,
                                        point,
                                        radius,
                                    )
                                    self._apply_joined_polyline_fillet(first, entity, joined)
                                    self.changed.emit()
                                    self.update()
                                    return
                                if isinstance(first, PolylineEntity) and isinstance(
                                    entity, LineEntity
                                ):
                                    polyline, selected_index, poly_pick = (
                                        first,
                                        self._circle_fillet_segment,
                                        first_pick,
                                    )
                                    line, line_pick = entity, point
                                elif isinstance(first, LineEntity) and isinstance(
                                    entity, PolylineEntity
                                ):
                                    polyline, selected_index, poly_pick = (
                                        entity,
                                        segment_index,
                                        point,
                                    )
                                    line, line_pick = first, first_pick
                                elif (
                                    isinstance(first, PolylineEntity)
                                    and isinstance(entity, CircleEntity | ArcEntity)
                                ) or (
                                    isinstance(first, CircleEntity | ArcEntity)
                                    and isinstance(entity, PolylineEntity)
                                ):
                                    if isinstance(first, PolylineEntity):
                                        polyline, selected_index, poly_pick = (
                                            first,
                                            self._circle_fillet_segment,
                                            first_pick,
                                        )
                                        circular, circular_pick = entity, point
                                    else:
                                        polyline, selected_index, poly_pick = (
                                            entity,
                                            segment_index,
                                            point,
                                        )
                                        circular, circular_pick = first, first_pick
                                    assert isinstance(polyline, PolylineEntity)
                                    assert isinstance(circular, CircleEntity | ArcEntity)
                                    if selected_index is None:
                                        raise ValueError("多段线段已失效；请重新选择。")
                                    layer_name = (
                                        polyline.layer_name
                                        if polyline.layer_name.casefold()
                                        == circular.layer_name.casefold()
                                        else self.active_layer_name
                                    )
                                    if radius > 0:
                                        layer = self.layer_table.get(layer_name)
                                        if layer.locked or not layer.displayed:
                                            raise ValueError("圆角目标图层隐藏或已锁定。")
                                    result, target, fillet, result_index = polyline_circular_fillet(
                                        polyline,
                                        selected_index,
                                        circular,
                                        poly_pick,
                                        circular_pick,
                                        radius,
                                        layer_name=layer_name,
                                    )
                                    sources: tuple[LineEntity | ArcEntity | PolylineEntity, ...] = (
                                        polyline,
                                    )
                                    results: tuple[LineEntity | ArcEntity | PolylineEntity, ...] = (
                                        result,
                                    )
                                    if isinstance(circular, ArcEntity):
                                        assert isinstance(target, ArcEntity)
                                        sources += (circular,)
                                        results += (target,)
                                    self._apply_fillet_replacements(
                                        sources,
                                        results,
                                        fillet,
                                        tangent_sources=(),
                                        indexed_sources=(
                                            (
                                                result,
                                                SketchGeometryReference(
                                                    result.entity_id, "segment", result_index
                                                ),
                                            ),
                                            (
                                                target,
                                                SketchGeometryReference(
                                                    target.entity_id, "geometry"
                                                ),
                                            ),
                                        ),
                                    )
                                    self.changed.emit()
                                    self.update()
                                    return
                                else:
                                    raise ValueError("此多段线与曲线的修剪圆角尚不支持。")
                                if selected_index is None:
                                    raise ValueError("多段线段已失效；请重新选择。")
                                joined = polyline_line_fillet(
                                    polyline, selected_index, line, poly_pick, line_pick, radius
                                )
                                self._apply_joined_polyline_fillet(polyline, line, joined)
                                self.changed.emit()
                                self.update()
                                return
                            if isinstance(first, RectangleEntity):
                                raise ValueError("矩形来源已变化；请重新选择。")
                            self._finish_external_polyline_notrim(
                                first,
                                self._circle_fillet_segment,
                                first_pick,
                                entity,
                                segment_index,
                                point,
                                radius,
                            )
                            self.changed.emit()
                            self.update()
                            return
                        if first != entity:
                            raise ValueError("多段线来源已变化；请重新选择。")
                        if self._circle_fillet_segment is None or segment_index is None:
                            raise ValueError("原多段线段已失效；请重新选择。")
                        result, new_arc = polyline_segment_fillet(
                            first,
                            self._circle_fillet_segment,
                            segment_index,
                            radius,
                            trim=use_trim,
                            first_pick=first_pick,
                            second_pick=point,
                        )
                        if use_trim:
                            if result == first:
                                self._circle_fillet_first = None
                                self._circle_fillet_segment = None
                                self.selected_entity_ids.clear()
                                self.message = (
                                    "所选多段线段已形成角点。"
                                    if radius == 0
                                    else "所选多段线圆角无需更改。"
                                )
                                self._complete_fillet_command()
                            else:
                                self._apply_fillet_replacements(
                                    (first,), (result,), None, tangent_sources=()
                                )
                        elif new_arc is not None:
                            layer = self._layer(first)
                            if layer.locked or not layer.displayed:
                                raise ValueError("圆角目标图层隐藏或已锁定。")
                            relations, pending = self._fillet_indexed_relations(
                                new_arc,
                                (
                                    (
                                        first,
                                        SketchGeometryReference(
                                            first.entity_id, "segment", self._circle_fillet_segment
                                        ),
                                    ),
                                    (
                                        first,
                                        SketchGeometryReference(
                                            first.entity_id, "segment", segment_index
                                        ),
                                    ),
                                ),
                            )
                            if self.replace_draft_entities(
                                (*self.entities, new_arc), new_relations=relations
                            ):
                                self.pending_cross_tangencies.extend(pending)
                                self._circle_fillet_first = None
                                self._circle_fillet_segment = None
                                self.selected_entity_ids.clear()
                                self.message = "圆角已创建；原多段线保留。"
                                self._complete_fillet_command()
                except ValueError as exc:
                    self.message = str(exc)
            elif not isinstance(entity, CircleEntity | ArcEntity | LineEntity):
                self.message = "请点选直线、圆或圆弧；圆保持不修剪。"
            elif self._circle_fillet_first is None:
                if not self._current_layer_can_draw() and self._layer(entity).locked:
                    self.message = "当前图层隐藏或已锁定，无法创建圆角。"
                else:
                    self._fillet_candidate_pending = False
                    self._fillet_pending_cross_candidate = ()
                    self._circle_fillet_first = (entity, point)
                    self._circle_fillet_segment = None
                    self._fillet_source_revision = (
                        self.source_revision_provider() if self.source_revision_provider else None
                    )
                    self.selected_entity_ids = {entity.entity_id}
                    self.message = "二维圆角：请选择第二条直线、圆或圆弧；Esc 取消。"
            else:
                first, first_pick = self._circle_fillet_first
                try:
                    if not isinstance(first, CircleEntity | ArcEntity | LineEntity):
                        raise ValueError("请选择同一多段线的另一条直线段。")
                    if first not in self.selectable_entities():
                        raise ValueError("第一个对象已失效，请按 Esc 后重新选择。")
                    if (
                        self._fillet_source_revision is not None
                        and self.source_revision_provider is not None
                        and self.source_revision_provider() != self._fillet_source_revision
                    ):
                        raise ValueError("文档已变化；请按 Esc 后重新选择对象。")
                    zero_line_corner = (
                        isinstance(first, LineEntity)
                        and isinstance(entity, LineEntity)
                        and (temporary_zero or self.circle_fillet_radius == 0)
                        and not lines_parallel(first, entity)
                    )
                    zero_curve_corner = (temporary_zero or self.circle_fillet_radius == 0) and not (
                        isinstance(first, LineEntity) and isinstance(entity, LineEntity)
                    )
                    fillet_layer = (
                        first.layer_name
                        if first.layer_name.casefold() == entity.layer_name.casefold()
                        else self.active_layer_name
                    )
                    if not zero_line_corner and not zero_curve_corner:
                        layer = self.layer_table.get(fillet_layer)
                        if layer.locked or not layer.displayed:
                            raise ValueError("圆角目标图层隐藏或已锁定。")
                    if isinstance(first, LineEntity) and isinstance(entity, LineEntity):
                        if zero_line_corner:
                            if not temporary_zero and not self.circle_fillet_trim:
                                raise ValueError("零半径角点需要修剪模式。")
                            a, b = line_corner(first, entity, first_pick, point)
                            self._apply_fillet_replacements(
                                (first, entity), (a, b), None, tangent_sources=()
                            )
                            self.changed.emit()
                            self.update()
                            return
                        if not self.circle_fillet_trim:
                            _, _, arc = line_fillet(
                                first,
                                entity,
                                first_pick,
                                point,
                                self.circle_fillet_radius,
                                uuid4().hex,
                                layer_name=fillet_layer,
                            )
                            self._finish_notrim_fillet(arc, first, entity)
                            return
                        self._apply_line_fillet(first, entity, first_pick, point, fillet_layer)
                        self.changed.emit()
                        self.update()
                        return
                    if zero_curve_corner:
                        if not temporary_zero and not self.circle_fillet_trim:
                            raise ValueError("零半径角点需要修剪模式。")
                        first_result, second_result = curve_corner(first, entity, first_pick, point)
                        sources = tuple(
                            item
                            for item in (first, entity)
                            if isinstance(item, LineEntity | ArcEntity)
                        )
                        results = tuple(
                            item
                            for item in (first_result, second_result)
                            if isinstance(item, LineEntity | ArcEntity)
                        )
                        self._apply_fillet_replacements(sources, results, None, tangent_sources=())
                        self.changed.emit()
                        self.update()
                        return
                    if isinstance(first, CircleEntity | ArcEntity) and isinstance(
                        entity, CircleEntity | ArcEntity
                    ):
                        arc = circle_fillet_notrim(
                            first,
                            entity,
                            first_pick,
                            point,
                            self.circle_fillet_radius,
                            uuid4().hex,
                            layer_name=fillet_layer,
                            extend_arcs=self.circle_fillet_trim,
                        )
                        sources = tuple(
                            item for item in (first, entity) if isinstance(item, ArcEntity)
                        )
                        if sources and self.circle_fillet_trim:
                            points = tuple(
                                (
                                    arc.center_mm[0]
                                    + arc.radius_mm * math.cos(math.radians(angle)),
                                    arc.center_mm[1]
                                    + arc.radius_mm * math.sin(math.radians(angle)),
                                )
                                for angle in (
                                    arc.start_angle_deg,
                                    arc.start_angle_deg + arc.sweep_angle_deg,
                                )
                            )
                            first_result = (
                                trim_arc_at_contact(first, points[0], first_pick)
                                if isinstance(first, ArcEntity)
                                else first
                            )
                            second_result = (
                                trim_arc_at_contact(entity, points[1], point)
                                if isinstance(entity, ArcEntity)
                                else entity
                            )
                            results = tuple(
                                item
                                for item in (first_result, second_result)
                                if isinstance(item, ArcEntity)
                            )
                            self._apply_fillet_replacements(
                                sources, results, arc, tangent_sources=(first_result, second_result)
                            )
                            self.changed.emit()
                            self.update()
                            return
                    else:
                        line = first if isinstance(first, LineEntity) else entity
                        circle = entity if isinstance(first, LineEntity) else first
                        if not isinstance(line, LineEntity) or not isinstance(
                            circle, CircleEntity | ArcEntity
                        ):
                            raise ValueError("请选择直线、圆或圆弧。")
                        line_pick, circle_pick = (
                            (first_pick, point)
                            if isinstance(first, LineEntity)
                            else (point, first_pick)
                        )
                        if not self.circle_fillet_trim:
                            arc = line_circle_fillet_notrim(
                                line,
                                circle,
                                line_pick,
                                circle_pick,
                                self.circle_fillet_radius,
                                uuid4().hex,
                                layer_name=fillet_layer,
                            )
                            self._finish_notrim_fillet(arc, first, entity)
                            return
                        line_result, arc = line_circle_fillet_trim(
                            line,
                            circle,
                            line_pick,
                            circle_pick,
                            self.circle_fillet_radius,
                            uuid4().hex,
                            layer_name=fillet_layer,
                        )
                        if isinstance(circle, ArcEntity):
                            angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
                            contact = (
                                arc.center_mm[0] + arc.radius_mm * math.cos(angle),
                                arc.center_mm[1] + arc.radius_mm * math.sin(angle),
                            )
                            arc_result = trim_arc_at_contact(circle, contact, circle_pick)
                            self._apply_fillet_replacements(
                                (line, circle),
                                (line_result, arc_result),
                                arc,
                                tangent_sources=(line_result, arc_result),
                            )
                            self.changed.emit()
                            self.update()
                            return
                        self._apply_fillet_replacements(
                            (line,), (line_result,), arc, tangent_sources=(line_result, circle)
                        )
                        self.changed.emit()
                        self.update()
                        return
                except ValueError as exc:
                    self.message = str(exc)
                else:
                    try:
                        self._finish_notrim_fillet(arc, first, entity)
                    except ValueError as exc:
                        self.message = str(exc)
        self.changed.emit()
        self.update()

    def _apply_joined_polyline_fillet(
        self,
        polyline: PolylineEntity | RectangleEntity,
        line: LineEntity | PolylineEntity | RectangleEntity,
        joined: PolylineEntity,
    ) -> None:
        """Atomically replace a polyline and consume its joined source."""
        sources = (polyline, line)
        affected = {item.entity_id for item in sources}
        all_entities = (*self.entities, *(item for item, _ in self.background_entities))
        for source in sources:
            if sum(item.entity_id == source.entity_id for item in all_entities) != 1:
                raise ValueError("目标身份不唯一；原图元未修改。")
            layer = next(
                (
                    layer
                    for item, layer in self.background_entities
                    if item.entity_id == source.entity_id
                ),
                None,
            )
            layer = self._layer(source) if layer is None else layer
            if layer.locked or not layer.displayed:
                raise ValueError("目标图层隐藏或已锁定；原图元未修改。")
        if any(
            draft_tangent_reference(endpoint).entity_id in affected
            for pair in self.pending_cross_tangencies
            for endpoint in pair
        ):
            raise ValueError("对象参与暂存对象相切；请先处理关系。")
        replacements: dict[str, tuple[SketchEntity, ...]] = {
            polyline.entity_id: (joined,),
            line.entity_id: (),
        }
        candidate = tuple(
            replacement
            for item in self.entities
            for replacement in replacements.get(item.entity_id, (item,))
        )
        self._reject_user_constraint_reference_edits(candidate)
        background = tuple(
            (replacement, layer)
            for item, layer in self.background_entities
            for replacement in replacements.get(item.entity_id, (item,))
        )
        saved = {
            item.entity_id for item, _ in self.background_entities if item.entity_id in affected
        }
        if saved:
            if self.source_revision_provider is None:
                raise ValueError("缺少文档版本；已保存对象无法安全修改。")
            if any(
                ref.entity_id in saved
                for constraint in self.background_constraints
                for ref in constraint.references
            ):
                raise ValueError("已保存图元有关联约束；请先处理约束。")
            previous_constraints = tuple(self.constraints)
            try:
                self._preserve_satisfied_relations(
                    candidate, original_entities=tuple(self.entities)
                )
                constraints = tuple(self.constraints)
            finally:
                self.constraints = list(previous_constraints)
            events = tuple((identity, replacements[identity]) for identity in sorted(saved))
            revision = self.source_revision_provider()
            self._chamfer_first = None
            self._chamfer_segment = None
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self._fillet_candidate_pending = True
            self._fillet_pending_cross_candidate = ()
            self.message = (
                "正在校验多段线倒角连接。"
                if self.tool == "二维倒角"
                else "正在校验多段线圆角连接。"
            )
            self.committed_drag_trim_requested.emit(
                events, candidate, constraints, background, revision
            )
        elif self.replace_draft_entities(candidate):
            self._chamfer_first = None
            self._chamfer_segment = None
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self.selected_entity_ids.clear()
            self.message = "已连接所选对象；可撤销。"
            self._complete_fillet_command()

    def _finish_external_polyline_notrim(
        self,
        first: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
        first_index: int | None,
        first_pick: Point2D,
        second: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
        second_index: int | None,
        second_pick: Point2D,
        radius: float,
    ) -> None:
        """Create an untrimmed fillet while retaining indexed source references."""

        def curve_and_ref(
            source: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
            index: int | None,
        ) -> tuple[LineEntity | CircleEntity | ArcEntity, SketchGeometryReference]:
            if isinstance(source, RectangleEntity):
                if index is None or not 0 <= index < 4:
                    raise ValueError("请选择有效的矩形边。")
                path = self._chamfer_rectangle_path(source)
                segment = polyline_curve_segments(path.points_mm, (0.0,) * 4, True, path.entity_id)[
                    index
                ]
                assert isinstance(segment, LineEntity)
                return segment, SketchGeometryReference(source.entity_id, "segment", index)
            if not isinstance(source, PolylineEntity):
                return source, SketchGeometryReference(source.entity_id, "geometry")
            if index is None:
                raise ValueError("多段线段已失效；请重新选择。")
            count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
            segments = polyline_curve_segments(
                source.points_mm,
                source.bulges or (0.0,) * count,
                source.closed,
                source.entity_id,
                construction=source.construction,
                layer_name=source.layer_name,
            )
            if not 0 <= index < count:
                raise ValueError("请选择有效的多段线段。")
            return segments[index], SketchGeometryReference(source.entity_id, "segment", index)

        first_curve, first_ref = curve_and_ref(first, first_index)
        second_curve, second_ref = curve_and_ref(second, second_index)
        layer_name = (
            first.layer_name
            if first.layer_name.casefold() == second.layer_name.casefold()
            else self.active_layer_name
        )
        layer = self.layer_table.get(layer_name)
        if layer.locked or not layer.displayed:
            raise ValueError("圆角目标图层隐藏或已锁定。")
        if isinstance(first_curve, LineEntity) and isinstance(second_curve, LineEntity):
            _, _, arc = line_fillet(
                first_curve,
                second_curve,
                first_pick,
                second_pick,
                radius,
                uuid4().hex,
                layer_name=layer_name,
            )
        elif isinstance(first_curve, CircleEntity | ArcEntity) and isinstance(
            second_curve, CircleEntity | ArcEntity
        ):
            arc = circle_fillet_notrim(
                first_curve,
                second_curve,
                first_pick,
                second_pick,
                radius,
                uuid4().hex,
                layer_name=layer_name,
            )
        else:
            line, circular, line_pick, circular_pick = (
                (first_curve, second_curve, first_pick, second_pick)
                if isinstance(first_curve, LineEntity)
                else (second_curve, first_curve, second_pick, first_pick)
            )
            if not isinstance(line, LineEntity) or not isinstance(
                circular, CircleEntity | ArcEntity
            ):
                raise ValueError("多段线圆角需要直线段与受支持曲线。")
            arc = line_circle_fillet_notrim(
                line,
                circular,
                line_pick,
                circular_pick,
                radius,
                uuid4().hex,
                layer_name=layer_name,
            )
        if not tangent_on_curves(first_curve, arc) or not tangent_on_curves(second_curve, arc):
            raise ValueError("不修剪模式要求切点位于原图元上。")
        relations, pending = self._fillet_indexed_relations(
            arc, ((first, first_ref), (second, second_ref))
        )
        if self.replace_draft_entities((*self.entities, arc), new_relations=relations):
            self.pending_cross_tangencies.extend(pending)
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self.selected_entity_ids.clear()
            self.message = "圆角已创建；原对象保留。"
            self._complete_fillet_command()

    def _fillet_indexed_relations(
        self,
        arc: ArcEntity,
        sources: tuple[
            tuple[
                LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
                SketchGeometryReference,
            ],
            ...,
        ],
        *,
        draft_replacements: frozenset[str] = frozenset(),
    ) -> tuple[tuple[SketchConstraint, ...], tuple[DraftTangentPair, ...]]:
        draft_ids = {item.entity_id for item in self.entities} | draft_replacements
        relations: list[SketchConstraint] = []
        pending: list[DraftTangentPair] = []
        if self._auto_inference_enabled:
            for source, ref in sources:
                if source.entity_id in draft_ids:
                    source_curve = tangent_entity_curve(source, ref.index)
                    relations.append(
                        SketchConstraint(
                            uuid4().hex,
                            "tangent",
                            (ref, SketchGeometryReference(arc.entity_id, "geometry")),
                            source="inferred",
                            first_endpoint=curve_endpoint_at_fillet(source_curve, arc),
                            second_endpoint=arc_tangent_endpoint(arc, source_curve),
                        )
                    )
                    if isinstance(source, PolylineEntity | RectangleEntity):
                        assert ref.index is not None
                        points = (
                            source.points_mm
                            if isinstance(source, PolylineEntity)
                            else self._chamfer_rectangle_path(source).points_mm
                        )
                        vertices = (ref.index, (ref.index + 1) % len(points))
                        source_points = tuple(
                            (
                                SketchGeometryReference(source.entity_id, "vertex", index),
                                points[index],
                            )
                            for index in vertices
                        )
                    else:
                        source_points = tuple(
                            item
                            for item in self._stable_point_references(source)
                            if item[0].kind in ("start", "end")
                        )
                    for source_ref, source_point in source_points:
                        for arc_ref, arc_point in self._stable_point_references(arc):
                            if (
                                arc_ref.kind in ("start", "end")
                                and _distance(source_point, arc_point) <= 1e-8
                            ):
                                relations.append(
                                    SketchConstraint(
                                        uuid4().hex,
                                        "coincident",
                                        (source_ref, arc_ref),
                                        source="inferred",
                                    )
                                )
                else:
                    source_curve = tangent_entity_curve(source, ref.index)
                    endpoint = arc_tangent_endpoint(arc, source_curve)
                    source_endpoint = curve_endpoint_at_fillet(source_curve, arc)
                    pending.append(
                        (
                            DraftConnectedEndpoint(ref, source_endpoint)
                            if source_endpoint is not None
                            else ref,
                            DraftConnectedEndpoint(
                                SketchGeometryReference(arc.entity_id, "geometry"), endpoint
                            ),
                        )
                    )
        return tuple(relations), tuple(pending)

    def _finish_notrim_fillet(
        self,
        arc: ArcEntity,
        first: LineEntity | CircleEntity | ArcEntity,
        second: LineEntity | CircleEntity | ArcEntity,
    ) -> None:
        if not tangent_on_curves(first, arc) or not tangent_on_curves(second, arc):
            raise ValueError("不修剪模式要求切点位于原图元上。")
        relations = self._fillet_tangent_relations(arc, (first, second))
        pending = self._fillet_cross_pairs(arc, (first, second))
        if self.replace_draft_entities((*self.entities, arc), new_relations=relations):
            self.pending_cross_tangencies.extend(pending)
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self.selected_entity_ids.clear()
            self.message = "二维圆角已创建；" + (
                "对象相切将在完成绘图时建立。"
                if pending
                else "已建立对象相切约束。"
                if relations
                else "未建立相切约束。"
            )
            self._complete_fillet_command()
            self.changed.emit()
            self.update()

    def _fillet_cross_pairs(
        self,
        arc: LineEntity | CircleEntity | ArcEntity,
        sources: tuple[LineEntity | CircleEntity | ArcEntity, ...],
    ) -> tuple[DraftTangentPair, ...]:
        if not self._auto_inference_enabled:
            return ()
        draft_ids = {entity.entity_id for entity in self.entities}
        return tuple(
            (
                DraftConnectedEndpoint(
                    SketchGeometryReference(source.entity_id, "geometry"), source_endpoint
                )
                if isinstance(arc, ArcEntity)
                and (source_endpoint := curve_endpoint_at_fillet(source, arc)) is not None
                else source.entity_id,
                DraftConnectedEndpoint(
                    SketchGeometryReference(arc.entity_id, "geometry"),
                    arc_tangent_endpoint(arc, source),
                )
                if isinstance(arc, ArcEntity)
                else arc.entity_id,
            )
            for source in sources
            if source.entity_id not in draft_ids
        )

    def _prune_pending_cross_tangencies(
        self,
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
        original_sources: tuple[SketchEntity, ...] = (),
    ) -> None:
        """Drop inferred draft relations whose finite geometry no longer touches."""
        original_by_id = {entity.entity_id: entity for entity in original_entities or ()}
        previous_count = len(self.pending_cross_tangencies)
        retained: list[DraftTangentPair] = []
        for source, draft in self.pending_cross_tangencies:
            source_ref, draft_ref = draft_tangent_reference(source), draft_tangent_reference(draft)
            targets = [
                entity for entity in self.entities if entity.entity_id == draft_ref.entity_id
            ]
            try:
                previous_sources = tuple(
                    entity
                    for entity in original_sources
                    if entity.entity_id == source_ref.entity_id
                )
                mixed = self.mixed_move
                current_sources: tuple[SketchEntity, ...] = (
                    tuple(
                        entity
                        for sketch in mixed.current_saved
                        for entity in sketch.entities
                        if entity.entity_id == source_ref.entity_id
                    )
                    if mixed is not None
                    else ()
                )
                if len(previous_sources) == 1 and len(current_sources) == 1:
                    previous_source, current_source = previous_sources[0], current_sources[0]
                    if isinstance(previous_source, PolylineEntity) and isinstance(
                        current_source, PolylineEntity
                    ):
                        index = _rebind_draft_polyline_segment(
                            previous_source, current_source, source_ref.index
                        )
                        source_ref = replace(source_ref, index=index)
                        if isinstance(source, DraftConnectedEndpoint):
                            source = replace(source, reference=source_ref)
                        else:
                            source = source_ref
                sources = self._pending_source_curves(source_ref)
                if len(sources) > 1 or len(targets) > 1:
                    retained.append((source, draft))
                    continue
                if len(sources) != 1 or len(targets) != 1:
                    continue
                original_target = original_by_id.get(draft_ref.entity_id)
                if isinstance(original_target, PolylineEntity) and isinstance(
                    targets[0], PolylineEntity
                ):
                    candidates = tuple(
                        entity
                        for entity in self.entities
                        if isinstance(entity, PolylineEntity)
                        and (
                            entity.entity_id == original_target.entity_id
                            or entity.entity_id not in original_by_id
                        )
                    )
                    fragment = (
                        unique_retained_tangent_fragment(
                            original_target, candidates, draft_ref.index, sources[0]
                        )
                        if draft_ref.index is not None
                        else None
                    )
                    if fragment is not None:
                        draft_ref = replace(draft_ref, entity_id=fragment[0], index=fragment[1])
                        targets = [
                            entity for entity in candidates if entity.entity_id == fragment[0]
                        ]
                    else:
                        try:
                            index = _rebind_draft_polyline_segment(
                                original_target, targets[0], draft_ref.index
                            )
                        except ValueError:
                            if draft_ref.index is None:
                                raise
                            index = unique_retained_tangent_polyline_arc(
                                original_target, targets[0], draft_ref.index, sources[0]
                            )
                            if index is None:
                                raise
                        draft_ref = replace(draft_ref, index=index)
                    if isinstance(draft, DraftConnectedEndpoint):
                        draft = replace(draft, reference=draft_ref)
                    else:
                        draft = draft_ref
                source_curve = sources[0]
                target_curve = tangent_entity_curve(targets[0], draft_ref.index)
                source_endpoint = (
                    source.endpoint if isinstance(source, DraftConnectedEndpoint) else None
                )
                draft_endpoint = (
                    draft.endpoint if isinstance(draft, DraftConnectedEndpoint) else None
                )
                if tangent_on_curves(source_curve, target_curve) and tangent_endpoints_satisfied(
                    source_curve, target_curve, source_endpoint, draft_endpoint
                ):
                    retained.append((source, draft))
            except (ValueError, IndexError):
                continue
        self.pending_cross_tangencies = retained
        removed = previous_count - len(retained)
        if removed:
            position = self.history_position
            self._pending_tangency_removal_notices[position] = (
                self._pending_tangency_removal_notices.get(position, 0) + removed
            )

    @property
    def pending_tangency_removal_notice(self) -> str:
        count = self._pending_tangency_removal_notices.get(self.history_position, 0)
        return f"已移除 {count} 条失效的暂存相切关系；可撤销。" if count else ""

    def _pending_source_curves(
        self, reference: SketchGeometryReference
    ) -> tuple[LineEntity | CircleEntity | ArcEntity, ...]:
        """Resolve saved sources in the draft frame, including non-background sketches."""
        mixed = self.mixed_move
        if mixed is not None:
            return tuple(
                project_tangent_entity(
                    tangent_entity_curve(entity, reference.index),
                    sketch.frame,
                    mixed.original_draft.frame,
                )
                for sketch in mixed.current_saved
                for entity in sketch.entities
                if entity.entity_id == reference.entity_id
            )
        return tuple(
            tangent_entity_curve(entity, reference.index)
            for entity, _layer in self.background_entities
            if entity.entity_id == reference.entity_id
        )

    def remove_pending_cross_tangency(self, pair: DraftTangentPair) -> bool:
        """Remove one staged relation as an undoable draft operation."""
        if pair not in self.pending_cross_tangencies:
            return False
        self._record_undo()
        self.pending_cross_tangencies.remove(pair)
        self.message = "暂存相切关系已移除，可撤销。"
        self.changed.emit()
        self.update()
        return True

    def _apply_line_fillet(
        self,
        first: LineEntity,
        second: LineEntity,
        first_pick: Point2D,
        second_pick: Point2D,
        layer_name: str,
    ) -> None:
        first_result, second_result, arc = line_fillet(
            first,
            second,
            first_pick,
            second_pick,
            self.circle_fillet_radius,
            uuid4().hex,
            layer_name=layer_name,
        )
        self._apply_fillet_replacements(
            (first, second),
            (first_result, second_result),
            arc,
            tangent_sources=(first_result, second_result),
        )

    def _fillet_tangent_relations(
        self,
        arc: LineEntity | CircleEntity | ArcEntity,
        sources: tuple[LineEntity | CircleEntity | ArcEntity, ...],
    ) -> tuple[SketchConstraint, ...]:
        if not self._auto_inference_enabled:
            return ()
        draft_ids = {entity.entity_id for entity in self.entities}
        if not all(tangent_on_curves(source, arc) for source in sources):
            raise ValueError("相切几何校验失败；原图元未修改。")
        sources = tuple(source for source in sources if source.entity_id in draft_ids)
        tangent_relations = tuple(
            SketchConstraint(
                uuid4().hex,
                "tangent",
                (
                    SketchGeometryReference(source.entity_id, "geometry"),
                    SketchGeometryReference(arc.entity_id, "geometry"),
                ),
                source="inferred",
                first_endpoint=curve_endpoint_at_fillet(source, arc)
                if isinstance(arc, ArcEntity)
                else None,
                second_endpoint=arc_tangent_endpoint(arc, source)
                if isinstance(arc, ArcEntity)
                else None,
            )
            for source in sources
        )
        arc_endpoints = tuple(
            (reference, point)
            for reference, point in self._stable_point_references(arc)
            if reference.kind in ("start", "end")
        )
        coincident: list[SketchConstraint] = []
        for source in sources:
            if isinstance(source, CircleEntity):
                continue
            for source_ref, source_point in self._stable_point_references(source):
                if source_ref.kind not in ("start", "end"):
                    continue
                for arc_ref, arc_point in arc_endpoints:
                    if _distance(source_point, arc_point) <= 1e-8:
                        coincident.append(
                            SketchConstraint(
                                uuid4().hex, "coincident", (source_ref, arc_ref), source="inferred"
                            )
                        )
        return (*tangent_relations, *coincident)

    def _apply_fillet_replacements(
        self,
        sources: tuple[LineEntity | ArcEntity | PolylineEntity | RectangleEntity, ...],
        results: tuple[LineEntity | ArcEntity | PolylineEntity, ...],
        arc: ArcEntity | LineEntity | None,
        *,
        tangent_sources: tuple[LineEntity | CircleEntity | ArcEntity, ...],
        indexed_sources: tuple[
            tuple[LineEntity | CircleEntity | ArcEntity | PolylineEntity, SketchGeometryReference],
            ...,
        ]
        | None = None,
    ) -> None:
        all_entities = (*self.entities, *(entity for entity, _layer in self.background_entities))
        for source in sources:
            if sum(entity.entity_id == source.entity_id for entity in all_entities) != 1:
                raise ValueError("目标身份不唯一；原图元未修改。")
            layer = next(
                (
                    layer
                    for entity, layer in self.background_entities
                    if entity.entity_id == source.entity_id
                ),
                None,
            )
            if (layer if layer is not None else self._layer(source)).locked:
                raise ValueError("目标图层已锁定；原图元未修改。")
        if arc is None and all(
            source == result for source, result in zip(sources, results, strict=True)
        ):
            self._chamfer_first = None
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self.selected_entity_ids.clear()
            self.message = self._unchanged_corner_message()
            self._complete_fillet_command()
            return
        replacements = {
            source.entity_id: result for source, result in zip(sources, results, strict=True)
        }
        draft = tuple(replacements.get(entity.entity_id, entity) for entity in self.entities)
        candidate = (*draft, arc) if arc is not None else draft
        background = tuple(
            (replacements.get(entity.entity_id, entity), layer)
            for entity, layer in self.background_entities
        )
        saved_ids = {
            entity.entity_id
            for entity, _layer in self.background_entities
            if entity.entity_id in replacements
        }
        preserve_user_refs = not saved_ids and all(
            isinstance(source, PolylineEntity)
            and isinstance(result, PolylineEntity)
            and source.entity_id == result.entity_id
            for source, result in zip(sources, results, strict=True)
        )
        if preserve_user_refs:
            self._rebind_unchanged_user_polyline_references(candidate)
        else:
            self._reject_user_constraint_reference_edits(candidate)
        if isinstance(arc, ArcEntity) and indexed_sources is not None:
            draft_ids = {entity.entity_id for entity in self.entities}
            relations, pending = self._fillet_indexed_relations(
                arc,
                indexed_sources,
                draft_replacements=frozenset(
                    result.entity_id
                    for source, result in zip(sources, results, strict=True)
                    if source.entity_id in draft_ids
                ),
            )
        else:
            relations = (
                self._fillet_tangent_relations(arc, tangent_sources)
                if isinstance(arc, ArcEntity)
                else ()
            )
            pending = (
                self._fillet_cross_pairs(arc, tangent_sources) if isinstance(arc, ArcEntity) else ()
            )
        if saved_ids:
            if self.source_revision_provider is None:
                raise ValueError("缺少文档版本；已保存对象无法安全修改。")
            changed_saved_ids = {
                entity.entity_id
                for entity, _layer in self.background_entities
                if entity.entity_id in saved_ids and replacements[entity.entity_id] != entity
            }
            affected_constraints = tuple(
                constraint
                for constraint in self.background_constraints
                if any(ref.entity_id in changed_saved_ids for ref in constraint.references)
            )
            if affected_constraints:
                self._rebind_unchanged_user_polyline_references(
                    tuple(entity for entity, _layer in background),
                    original_entities=tuple(entity for entity, _layer in self.background_entities),
                    constraints=affected_constraints,
                    include_inferred=True,
                )
            old_constraints = tuple(self.constraints)
            try:
                self._preserve_satisfied_relations(
                    candidate, original_entities=tuple(self.entities)
                )
                constraints = (*self.constraints, *relations)
            finally:
                self.constraints = list(old_constraints)
            events = tuple((identity, (replacements[identity],)) for identity in sorted(saved_ids))
            revision = self.source_revision_provider()
            self._chamfer_first = None
            self._circle_fillet_first = None
            self._circle_fillet_segment = None
            self._fillet_source_revision = None
            self.message = "正在校验倒角修改。" if self.tool == "二维倒角" else "正在校验圆角修改。"
            self._fillet_candidate_pending = True
            self._fillet_pending_cross_candidate = pending
            self.committed_drag_trim_requested.emit(
                events, candidate, constraints, background, revision
            )
        else:
            if self.replace_draft_entities(
                candidate,
                new_relations=relations,
                preserve_unchanged_polyline_references=preserve_user_refs,
            ):
                self.pending_cross_tangencies.extend(pending)
                self._chamfer_first = None
                self._circle_fillet_first = None
                self._circle_fillet_segment = None
                self._fillet_source_revision = None
                self.selected_entity_ids.clear()
                self.circle_fillet_polyline_pending = False
                self.message = (
                    "已修剪或延伸对象至交点；可撤销。"
                    if arc is None
                    else "已创建倒角；可撤销。"
                    if isinstance(arc, LineEntity)
                    else "已修剪对象并创建圆角；可撤销。"
                )
                self._complete_fillet_command()

    def _record_undo(self) -> None:
        self._undo_history.append(self._draft_state())
        self._advance_history()

    def _advance_history(self) -> None:
        self._next_history_position += 1
        self.history_position = self._next_history_position
        self._redo_history.clear()
        self.history_recorded.emit()

    def _draft_state(self) -> _DraftState:
        return _DraftState(
            tuple(self.entities),
            tuple(self.constraints),
            frozenset(self.selected_entity_ids),
            self.layer_table,
            self.active_layer_name,
            tuple(self._points) if self.tool == "直线" and self.continuous_lines else (),
            self.history_position,
            self.mixed_move,
            tuple(self.pending_cross_tangencies),
            self._last_polar_entity_id,
            tuple(self.pending_associative_arrays),
        )

    def rebind_restored_source(self, previous_revision: int, revision: int) -> None:
        """Rebind retained history only after the Bus restored its exact source.

        A save keeps this canvas detached from intermediate document changes;
        invalid transactions stay invalid, including entries in the redo branch.
        """

        def rebind(mixed: MixedMoveState | None) -> MixedMoveState | None:
            if mixed is not None and mixed.source_revision == previous_revision:
                return replace(mixed, source_revision=revision)
            return mixed

        self.mixed_move = rebind(self.mixed_move)
        self._undo_history = [
            replace(state, mixed_move=rebind(state.mixed_move)) for state in self._undo_history
        ]
        self._redo_history = [
            replace(state, mixed_move=rebind(state.mixed_move)) for state in self._redo_history
        ]
        self.set_source_context_revision(revision)

    def rebase_mixed_layers(self, saved: tuple[Sketch, ...], layers: SketchLayerTable) -> bool:
        """Carry a layer-only document change into a retained mixed-edit timeline."""
        current = {sketch.sketch_id: sketch for sketch in saved}
        active = self.mixed_move
        if active is None or not self.mixed_move_is_valid:
            return False
        for old in active.original_saved:
            new = current.get(old.sketch_id)
            if new is None or replace(old, layers=new.layers) != new:
                return False

        def rebase(mixed: MixedMoveState | None) -> MixedMoveState | None:
            if mixed is None:
                return None
            original = tuple(current.get(sketch.sketch_id) for sketch in mixed.original_saved)
            if any(sketch is None for sketch in original) or any(
                replace(old, layers=new.layers) != new
                for old, new in zip(mixed.original_saved, original, strict=True)
                if new is not None
            ):
                return mixed
            tables = {sketch.sketch_id: sketch.layers for sketch in saved}
            return replace(
                mixed,
                original_draft=replace(mixed.original_draft, layers=layers),
                original_saved=tuple(
                    replace(sketch, layers=tables[sketch.sketch_id])
                    for sketch in mixed.original_saved
                ),
                current_saved=tuple(
                    replace(sketch, layers=tables[sketch.sketch_id])
                    for sketch in mixed.current_saved
                ),
            )

        self.mixed_move = rebase(self.mixed_move)
        self._undo_history = [
            replace(state, layers=layers, mixed_move=rebase(state.mixed_move))
            for state in self._undo_history
        ]
        self._redo_history = [
            replace(state, layers=layers, mixed_move=rebase(state.mixed_move))
            for state in self._redo_history
        ]
        return True

    def _restore_draft_state(self, state: _DraftState) -> None:
        previous_mixed = self.mixed_move
        self.mixed_move = state.mixed_move
        if (
            state.mixed_move is not None
            and state.mixed_move.transaction_id not in self._invalid_mixed_transactions
        ):
            self.background_entities = state.mixed_move.overlay_background
        elif (
            state.mixed_move is None
            and previous_mixed is not None
            and previous_mixed.transaction_id not in self._invalid_mixed_transactions
        ):
            self.background_entities = previous_mixed.base_background
        self.history_position = state.history_position
        self._last_polar_entity_id = state.last_polar_entity_id
        if self.tool == "直线" and self.continuous_lines:
            self._points = list(state.line_points)
            self._first = self._points[-1] if self._points else None
        self.entities = list(state.entities)
        self.constraints = list(state.constraints)
        self.pending_cross_tangencies = list(state.pending_cross_tangencies)
        self.pending_associative_arrays = list(state.pending_associative_arrays)
        self.selected_entity_ids = set(state.selected_ids)
        self.layer_table = (
            (self.document_layer_table or state.layers)
            if self.preserve_document_layers
            else state.layers
        )
        if self.document_layer_table is not None:
            self.document_layer_table = self.layer_table
        self.active_layer_name = state.active_layer_name
        try:
            active = self.layer_table.get(self.active_layer_name)
            if active.frozen:
                self.active_layer_name = "0"
        except KeyError:
            self.active_layer_name = "0"
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        self._snap_candidates_cache = None
        self._snap_kind = ""
        self._hovered_entity_id = None
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()

    def _hit_entity_at(self, point: Point2D) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[float, str]] = []
        for entity in self.selectable_entities():
            if isinstance(entity, PointEntity):
                distance = _distance(point, entity.position_mm)
            elif isinstance(entity, SplineEntity):
                points = entity.sampled_points()
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(points, points[1:], strict=False)
                )
            elif isinstance(entity, LineEntity):
                distance = _distance_to_segment(point, entity.start_mm, entity.end_mm)
            elif isinstance(entity, PolylineEntity):
                if entity.bulges:
                    segments = polyline_curve_segments(
                        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                    )
                    distance = min(
                        _distance_to_arc(point, segment)
                        if isinstance(segment, ArcEntity)
                        else _distance_to_segment(point, segment.start_mm, segment.end_mm)
                        for segment in segments
                    )
                else:
                    points = polyline_sampled_points(entity)
                    distance = min(
                        _distance_to_segment(point, start, end)
                        for start, end in zip(points, points[1:], strict=False)
                    )
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
                )
            elif isinstance(entity, CircleEntity):
                distance = abs(_distance(point, entity.center_mm) - entity.radius_mm)
            else:
                distance = _distance_to_arc(point, entity)
            if distance <= tolerance:
                candidates.append((distance, entity.entity_id))
        candidates.sort()
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][0] - candidates[0][0]) * self._scale <= 1.0:
            return None
        return candidates[0][1]

    def measurement_entity_at(self, point: Point2D) -> SketchEntity | None:
        """Return an unambiguous visible entity at a point without selecting it."""
        identity = self._hit_entity_at(point)
        if identity is None:
            return None
        return next(
            (item for item in self.selectable_entities() if item.entity_id == identity), None
        )

    def update_quick_measure(self, point: Point2D | None) -> None:
        """Preview a nearby circular curve or the distance between nearby curves."""
        self.quick_measure_preview = None
        if point is not None:
            circular: list[tuple[float, str, CircleEntity | ArcEntity]] = []
            nearby_curves: list[tuple[float, str, LineEntity | CircleEntity | ArcEntity]] = []
            for entity in self.visible_snap_entities():
                curves: tuple[CircleEntity | ArcEntity, ...]
                if isinstance(entity, CircleEntity | ArcEntity):
                    curves = (entity,)
                elif isinstance(entity, PolylineEntity):
                    count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                    curves = tuple(
                        segment
                        for segment in polyline_curve_segments(
                            entity.points_mm,
                            entity.bulges or (0.0,) * count,
                            entity.closed,
                            entity.entity_id,
                        )
                        if isinstance(segment, ArcEntity)
                    )
                else:
                    continue
                for curve in curves:
                    distance = (
                        abs(_distance(point, curve.center_mm) - curve.radius_mm)
                        if isinstance(curve, CircleEntity)
                        else _distance_to_arc(point, curve)
                    )
                    if distance * self.view_scale <= _SNAP_RADIUS_PX:
                        circular.append((distance, entity.entity_id, curve))
                    if distance * self.view_scale <= 100:
                        nearby_curves.append((distance, entity.entity_id, curve))
            circular.sort(key=lambda item: (item[0], item[1]))
            if circular:
                if len(circular) == 1 or (circular[1][0] - circular[0][0]) * self.view_scale > 1:
                    curve = circular[0][2]
                    self.quick_measure_preview = QuickRadiusMeasurement(
                        curve.center_mm, point, curve.radius_mm
                    )
                self.update()
                return
            lines = self.quick_measure_linework()
            candidates: list[tuple[float, str, LineEntity | CircleEntity | ArcEntity]] = sorted(
                [
                    (
                        _distance_to_segment(point, entity.start_mm, entity.end_mm),
                        entity.entity_id,
                        entity,
                    )
                    for entity in lines
                ]
                + nearby_curves,
                key=lambda item: (item[0], item[1]),
            )
            if len(candidates) >= 2 and candidates[1][0] * self.view_scale <= 100:
                with suppress(ValueError):
                    first, second = candidates[0][2], candidates[1][2]
                    if isinstance(first, LineEntity) and isinstance(second, LineEntity):
                        self.quick_measure_preview = measure_line_pair(first, second, near=point)
                    elif isinstance(first, CircleEntity | ArcEntity) and isinstance(
                        second, CircleEntity | ArcEntity
                    ):
                        self.quick_measure_preview = measure_circular_curves(
                            first, second, near=point
                        )
                    elif isinstance(first, LineEntity) and isinstance(second, CircleEntity):
                        self.quick_measure_preview = measure_line_circle(first, second, near=point)
                    elif isinstance(first, CircleEntity) and isinstance(second, LineEntity):
                        self.quick_measure_preview = measure_line_circle(second, first, near=point)
                    elif isinstance(first, LineEntity) and isinstance(second, ArcEntity):
                        self.quick_measure_preview = measure_line_arc(first, second, near=point)
                    elif isinstance(first, ArcEntity) and isinstance(second, LineEntity):
                        self.quick_measure_preview = measure_line_arc(second, first, near=point)
        self.update()

    def quick_measure_linework(self) -> tuple[LineEntity, ...]:
        """Return visible finite line segments in the current canvas frame."""
        lines: list[LineEntity] = []
        for entity in self.visible_snap_entities():
            if isinstance(entity, LineEntity):
                lines.append(entity)
            elif isinstance(entity, PolylineEntity):
                count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                lines.extend(
                    segment
                    for segment in polyline_curve_segments(
                        entity.points_mm,
                        entity.bulges or (0.0,) * count,
                        entity.closed,
                        entity.entity_id,
                    )
                    if isinstance(segment, LineEntity)
                )
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                lines.extend(
                    LineEntity(entity.entity_id, start, end)
                    for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
                )
        return tuple(lines)

    def measurement_curve_at(
        self, point: Point2D
    ) -> tuple[SketchEntity, LineEntity | ArcEntity | CircleEntity, int | None] | None:
        """Resolve a picked curve, retaining the parent identity for polyline segments."""
        entity = self.measurement_entity_at(point)
        if isinstance(entity, PolylineEntity):
            index = self._fillet_polyline_segment_at(entity, point)
            count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
            segments = polyline_curve_segments(
                entity.points_mm, entity.bulges or (0.0,) * count, entity.closed, entity.entity_id
            )
            return entity, segments[index], index
        if isinstance(entity, LineEntity | ArcEntity | CircleEntity):
            return entity, entity, None
        return None

    def _fillet_polyline_segment_at(self, entity: PolylineEntity, point: Point2D) -> int:
        count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        segments = polyline_curve_segments(
            entity.points_mm,
            entity.bulges or (0.0,) * count,
            entity.closed,
            entity.entity_id,
        )
        candidates = sorted(
            (
                _distance_to_arc(point, segment)
                if isinstance(segment, ArcEntity)
                else _distance_to_segment(point, segment.start_mm, segment.end_mm),
                index,
            )
            for index, segment in enumerate(segments)
        )
        if not candidates or candidates[0][0] * self._scale > _SNAP_RADIUS_PX:
            raise ValueError("请点选多段线段。")
        if len(candidates) > 1 and (candidates[1][0] - candidates[0][0]) * self._scale <= 1.0:
            raise ValueError("多段线段选择不明确，请远离顶点重新选取。")
        return candidates[0][1]

    def clear_selected_tangent_segments(self) -> None:
        """Discard edge picks when the selection is replaced by another workflow."""
        self.selected_segment_indices.clear()
        self._selected_segment_sources.clear()

    def selected_tangent_segments(self) -> dict[str, int]:
        """Return picked segments only while their source geometry remains unchanged."""
        current = {entity.entity_id: entity for entity in self.selectable_entities()}
        return {
            identity: index
            for identity, index in self.selected_segment_indices.items()
            if identity in self.selected_entity_ids
            and current.get(identity) == self._selected_segment_sources.get(identity)
        }

    def _select_at(self, point: Point2D, *, additive: bool, subtractive: bool = False) -> None:
        identity = self._hit_entity_at(point)
        if not additive and not subtractive:
            self.selected_entity_ids.clear()
            self.selected_constraint_ids.clear()
            self.selected_segment_indices.clear()
            self._selected_segment_sources.clear()
        if identity is not None:
            if subtractive:
                self.selected_entity_ids.discard(identity)
            elif additive and identity in self.selected_entity_ids:
                self.selected_entity_ids.remove(identity)
            else:
                self.selected_entity_ids.add(identity)
            self.selected_segment_indices.pop(identity, None)
            self._selected_segment_sources.pop(identity, None)
            if identity in self.selected_entity_ids:
                entity = next(
                    (item for item in self.selectable_entities() if item.entity_id == identity),
                    None,
                )
                if isinstance(entity, PolylineEntity | RectangleEntity):
                    with suppress(ValueError):
                        path = (
                            self._chamfer_rectangle_path(entity)
                            if isinstance(entity, RectangleEntity)
                            else entity
                        )
                        self.selected_segment_indices[identity] = self._fillet_polyline_segment_at(
                            path, point
                        )
                        self._selected_segment_sources[identity] = entity
            self.message = f"已选择 {len(self.selected_entity_ids)} 个草图元素。"
        else:
            self.message = "未命中唯一草图元素；请靠近目标或缩放视图后重试。"
        self.changed.emit()
        self.update()

    def begin_object_tangency_selection(self) -> bool:
        """Start picking two visible drawing objects, retaining a valid preselection."""
        revision = self.source_revision_provider() if self.source_revision_provider else None
        if (
            revision is not None
            and self.source_context_revision is not None
            and revision != self.source_context_revision
        ):
            self.source_revision_invalidated.emit()
            self.message = "文档已变化；请重新选择对象。"
            self.changed.emit()
            return False
        available = {entity.entity_id: entity for entity in self.selectable_entities()}
        eligible = tuple(
            entity
            for entity in available.values()
            if isinstance(
                entity, LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
            )
        )
        if len(eligible) < 2:
            self.message = "图纸中至少需要两个可见的曲线对象。"
            self.changed.emit()
            return False
        selected: set[str] = self.selected_entity_ids & {entity.entity_id for entity in eligible}
        if len(selected) != 1:
            selected.clear()
        segments = {
            identity: index
            for identity, index in self.selected_tangent_segments().items()
            if identity in selected
        }
        if selected:
            selected_id = next(iter(selected))
            selected_entity = available[selected_id]
            if self._layer(selected_entity).locked or (
                isinstance(selected_entity, PolylineEntity | RectangleEntity)
                and selected_id not in segments
            ):
                selected.clear()
                segments.clear()
        sources = {
            identity: entity
            for identity, entity in self._selected_segment_sources.items()
            if identity in segments
        }
        if not self.set_tool("对象相切选择"):
            return False
        self._object_tangency_selection_revision = revision
        self.selected_entity_ids = selected
        self.selected_segment_indices = segments
        self._selected_segment_sources = sources
        self.message = (
            "对象相切：请选择第二个对象；Enter 查看选项，Esc 取消。"
            if selected
            else "对象相切：请选择第一个对象；Enter 查看选项，Esc 取消。"
        )
        self.changed.emit()
        self.update()
        return True

    def _pick_object_tangency(self, point: Point2D) -> None:
        if (
            self._object_tangency_selection_revision is not None
            and self.source_revision_provider is not None
            and self.source_revision_provider() != self._object_tangency_selection_revision
        ):
            self.set_tool("选择元素")
            self.selected_entity_ids.clear()
            self.clear_selected_tangent_segments()
            self.source_revision_invalidated.emit()
            self.message = "文档已变化；请重新选择对象。"
            self.changed.emit()
            self.update()
            return
        available = {entity.entity_id: entity for entity in self.selectable_entities()}
        if any(
            identity not in available or self._layer(available[identity]).locked
            for identity in self.selected_entity_ids
        ):
            self.selected_entity_ids.clear()
            self.clear_selected_tangent_segments()
            self.message = "已选对象不可见或所在图层已锁定；请重新选择。"
            self.changed.emit()
            self.update()
            return
        identity = self._hit_entity_at(point)
        entity = available.get(identity) if identity is not None else None
        if not isinstance(
            entity, LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
        ):
            self.message = "请选择唯一的直线、圆、圆弧或多段线边。"
        elif identity in self.selected_entity_ids:
            self.message = "请选择另一个对象。"
        elif self._layer(entity).locked:
            self.message = "对象所在图层已锁定；请选择可编辑对象。"
        else:
            self._select_at(point, additive=True)
            if (
                isinstance(entity, PolylineEntity | RectangleEntity)
                and identity not in self.selected_tangent_segments()
            ):
                self.selected_entity_ids.discard(entity.entity_id)
                self.message = "无法唯一确定所选边，请靠近边的中部重试。"
            elif len(self.selected_entity_ids) == 2:
                self.set_tool("选择元素")
                self.object_tangency_selection_ready.emit()
                return
            else:
                self.message = "对象相切：请选择第二个对象；Enter 查看选项，Esc 取消。"
        self.changed.emit()
        self.update()

    def _begin_selection_box(self, event: QMouseEvent) -> None:
        self._selection_anchor = event.position()
        self._selection_corner = event.position()
        self._selection_waiting_click = False
        self._selection_original = frozenset(self.selected_entity_ids)
        self._selection_original_constraints = frozenset(self.selected_constraint_ids)
        self._selection_original_raster_ids = frozenset(self.selected_raster_ids)
        self._selection_modifiers = event.modifiers()
        self._hovered_entity_id = None
        self._snap_kind = ""
        self.message = "指定选框对角点：左→右仅选完全包含，右→左选包含或相交；Esc 取消。"
        self.changed.emit()
        self.update()

    def _cancel_selection_box(self) -> bool:
        if self._selection_anchor is None:
            return False
        self.selected_entity_ids = set(self._selection_original)
        self.selected_constraint_ids = set(self._selection_original_constraints)
        self.selected_raster_ids = set(self._selection_original_raster_ids)
        self._selection_anchor = None
        self._selection_waiting_click = False
        self.message = "已取消框选。"
        self.changed.emit()
        self.update()
        return True

    def _finish_selection_box(self, position: QPointF) -> None:
        anchor = self._selection_anchor
        if anchor is None:
            return
        self.selected_segment_indices.clear()
        self._selected_segment_sources.clear()
        crossing = position.x() < anchor.x()
        first, second = self.screen_to_local(anchor), self.screen_to_local(position)
        identities = {
            entity.entity_id
            for entity in self.selectable_entities()
            if entity_in_selection_box(entity, first, second, crossing=crossing)
        }
        if self._line_edit_selecting_boundaries:
            identities.update(
                source.entity.entity_id
                for source in self.spatial_boundaries
                if projected_boundary_in_box(
                    source, self._spatial_target_frame, first, second, crossing=crossing
                )
            )
        dimension_ids: set[str] = set()
        if (
            self.select_committed_entities
            and self.tool == "选择元素"
            and (not self._transform_selecting or self._transform_operation == "erase")
            and not self._line_edit_selecting_boundaries
            and not self._line_edit_erasing
        ):
            selection = QRectF(anchor, position).normalized()
            entities = self.dimension_entities()
            label_rectangles = self.dimension_label_rectangles()
            for constraint in self.dimension_constraints():
                layer = self.annotation_layer(constraint)
                if constraint.kind not in DIMENSION_KINDS or not layer.displayed or layer.locked:
                    continue
                layout = self.dimension_layout(constraint, entities)
                label_rect = label_rectangles.get(constraint.constraint_id)
                if label_rect is None:
                    continue
                path = QPainterPath()
                path.addRect(label_rect)
                if layout is not None:
                    for start, end in layout.lines:
                        path.moveTo(start)
                        path.lineTo(end)
                    for start, end in self.dimension_arrow_segments(
                        layout, constraint.scale, constraint
                    ):
                        path.moveTo(start)
                        path.lineTo(end)
                stroker = QPainterPathStroker()
                stroker.setWidth(5)
                hit = (
                    selection.contains(path.boundingRect())
                    if not crossing
                    else (
                        path.intersects(selection)
                        or stroker.createStroke(path).intersects(selection)
                        or selection.contains(label_rect.center())
                    )
                )
                if hit:
                    dimension_ids.add(constraint.constraint_id)
            if self._selection_modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.selected_constraint_ids = (
                    set(self._selection_original_constraints) - dimension_ids
                )
            elif (
                self._selection_modifiers & Qt.KeyboardModifier.ControlModifier
                or self._transform_selecting
            ):
                self.selected_constraint_ids = (
                    set(self._selection_original_constraints) | dimension_ids
                )
            else:
                self.selected_constraint_ids = dimension_ids
        image_hits: list[str] = []
        if (
            self.select_committed_entities
            and self.tool == "选择元素"
            and not self._line_edit_selecting_boundaries
            and not self._line_edit_erasing
        ):
            selection = QRectF(anchor, position).normalized()
            for image in self.drawing_rasters:
                layer = self.layer_table.get(image.layer_name)
                if not layer.displayed or layer.locked:
                    continue
                angle = math.radians(image.angle_deg)
                ux, uy = math.cos(angle) * image.width_mm, math.sin(angle) * image.width_mm
                sign = -1 if image.mirrored else 1
                vx, vy = (
                    -math.sin(angle) * image.height_mm * sign,
                    math.cos(angle) * image.height_mm * sign,
                )
                x, y = image.origin_mm
                corners = ((x, y), (x + ux, y + uy), (x + ux + vx, y + uy + vy), (x + vx, y + vy))
                path = QPainterPath()
                path.moveTo(self.local_to_screen(corners[0]))
                for corner in corners[1:]:
                    path.lineTo(self.local_to_screen(corner))
                path.closeSubpath()
                if selection.contains(path.boundingRect()) or (
                    crossing and path.intersects(selection)
                ):
                    image_hits.append(image.image_id)
        additive = (
            bool(
                self._selection_modifiers
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            )
            or self._transform_selecting
        )
        if (
            self._transform_selecting
            and self._transform_operation
            not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
            and (
                (image_hits and (identities or self._selection_original))
                or (self._selection_original_raster_ids and identities)
            )
        ):
            self.selected_entity_ids = set(self._selection_original)
            self.selected_constraint_ids = set(self._selection_original_constraints)
            self.selected_raster_ids = set(self._selection_original_raster_ids)
            self._selection_anchor = None
            self._selection_waiting_click = False
            self.message = "暂不能同时变换图片和其他对象，请分别选择。"
            self.changed.emit()
            self.update()
            return
        if self._selection_modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected_raster_ids = set(self._selection_original_raster_ids) - set(image_hits)
        elif additive:
            self.selected_raster_ids = set(self._selection_original_raster_ids) | set(image_hits)
        else:
            self.selected_raster_ids = set(image_hits)
        if self._selection_modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected_entity_ids = set(self._selection_original) - identities
        elif (
            self._selection_modifiers & Qt.KeyboardModifier.ControlModifier
            or self._transform_selecting
            or self._line_edit_selecting_boundaries
        ):
            self.selected_entity_ids = set(self._selection_original) | identities
        else:
            self.selected_entity_ids = identities
        self._selection_anchor = None
        self._selection_waiting_click = False
        mode = "交叉选择" if crossing else "窗口选择"
        self.message = f"{mode} · 已选择 {len(self.selected_entity_ids)} 个草图元素。"
        if self.selected_raster_ids:
            self.message += f" 已选择 {len(self.selected_raster_ids)} 张图片。"
        if self.selected_constraint_ids:
            self.message += f" 已选择 {len(self.selected_constraint_ids)} 个标注。"
        if self._transform_selecting:
            self.message += " Enter / 右键结束选择，然后指定基点。"
        self.changed.emit()
        self.update()

    @staticmethod
    def _entity_handles(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        if isinstance(entity, PointEntity):
            return ((SketchGeometryReference(entity.entity_id, "vertex", 0), entity.position_mm),)
        if isinstance(entity, SplineEntity):
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(entity.control_points_mm)
            )
        if isinstance(entity, LineEntity):
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.start_mm),
                (SketchGeometryReference(entity.entity_id, "end"), entity.end_mm),
            )
        if isinstance(entity, PolylineEntity):
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(entity.points_mm)
            )
        if isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            corners = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(corners)
            )
        if isinstance(entity, CircleEntity):
            return ((SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),)
        start = math.radians(entity.start_angle_deg)
        end = math.radians(entity.start_angle_deg + entity.sweep_angle_deg)
        return (
            (SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),
            (
                SketchGeometryReference(entity.entity_id, "start"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(start),
                    entity.center_mm[1] + entity.radius_mm * math.sin(start),
                ),
            ),
            (
                SketchGeometryReference(entity.entity_id, "end"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(end),
                    entity.center_mm[1] + entity.radius_mm * math.sin(end),
                ),
            ),
        )

    @staticmethod
    def entity_point_references(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        """Return stable point references and positions for canvas picking."""
        return SketchCanvas._entity_handles(entity)

    def associative_spacing_grips(self) -> tuple[tuple[AssociativeRectArray, str, Point2D], ...]:
        """Resolve unambiguous saved-array grips in the current drawing plane."""
        provider, frame = self.associative_arrays_provider, self._spatial_target_frame
        if (
            provider is None
            or not self.select_committed_entities
            or self.tool != "选择元素"
            or self.has_active_edit_gesture
            or self.pending_cross_tangencies
            or self.pending_associative_arrays
            or self.mixed_move is not None
            or len(self.selected_entity_ids) != 1
            or (
                self.source_revision_provider is not None
                and self.source_context_revision != self.source_revision_provider()
            )
        ):
            return ()
        identity = next(iter(self.selected_entity_ids))
        if any(entity.entity_id == identity for entity in self.entities):
            return ()
        selected = [
            (entity, layer)
            for entity, layer in self.background_entities
            if entity.entity_id == identity
        ]
        if len(selected) != 1 or not selected[0][1].displayed or selected[0][1].locked:
            return ()
        arrays = tuple(
            array
            for array in provider()
            if any(source.entity_id == identity for source in array.sources)
            or any(member.target.entity_id == identity for member in array.members)
            or any(output.target.entity_id == identity for output in array.extra_outputs)
        )
        if len(arrays) != 1:
            return ()
        array = arrays[0]
        if any(entity.entity_id == array.sources[0].entity_id for entity in self.entities):
            return ()
        displacement = tuple(
            a - b for a, b in zip(array.frame.origin_mm, frame.origin_mm, strict=True)
        )
        if (
            array.frame.u_axis != frame.u_axis
            or array.frame.v_axis != frame.v_axis
            or abs(sum(a * b for a, b in zip(displacement, frame.normal, strict=True))) > 1e-7
        ):
            return ()
        sources = [
            (entity, layer)
            for entity, layer in self.background_entities
            if entity.entity_id == array.sources[0].entity_id
        ]
        if len(sources) != 1 or not sources[0][1].displayed or sources[0][1].locked:
            return ()
        handles = self._entity_handles(sources[0][0])
        if not handles:
            return ()
        anchor = handles[0][1]
        if array.base_point is not None:
            if self.associative_sketches_provider is None:
                return ()
            try:
                base = resolve_array_base_point(array, self.associative_sketches_provider())
                if base is None:
                    return ()
                anchor = frame.world_to_local(array.frame.local_to_world(base))
            except ValueError:
                return ()
        return tuple(
            (array, axis, array_spacing_grip(array, anchor, axis))
            for axis, count in (("row", array.rows), ("column", array.columns))
            if count > 1
        )

    @property
    def array_spacing_drag_active(self) -> bool:
        return self._array_spacing_drag is not None

    @property
    def array_spacing_preview(self) -> tuple[tuple[SketchEntity, SketchLayer], ...]:
        state = self._array_spacing_drag
        return state.preview if state is not None else ()

    def associative_count_grips(self) -> tuple[tuple[AssociativeRectArray, Point2D], ...]:
        """Return the offset corner grip for the unique selected saved array."""
        grips = self.associative_spacing_grips()
        if not grips:
            return ()
        array, axis, point = grips[0]
        step = array_spacing_grip(array, (0, 0), axis)
        anchor = (point[0] - step[0], point[1] - step[1])
        corner = rectangular_array_displacement(
            array.rows - 1,
            array.columns - 1,
            array.row_spacing,
            array.column_spacing,
            array.angle_deg,
        )
        return (
            (
                array,
                (
                    anchor[0] + corner[0] + 14 / self._scale,
                    anchor[1] + corner[1] - 14 / self._scale,
                ),
            ),
        )

    def associative_base_grips(self) -> tuple[tuple[AssociativeRectArray, Point2D], ...]:
        """Resolve the base grip of an unambiguous saved associative array."""
        grips = self.associative_spacing_grips()
        if not grips:
            return ()
        array, axis, point = grips[0]
        step = array_spacing_grip(array, (0, 0), axis)
        return ((array, (point[0] - step[0], point[1] - step[1])),)

    def _begin_array_spacing_drag(self, point: Point2D) -> bool:
        candidates = sorted(
            [
                (_distance(point, position), array, axis, position)
                for array, axis, position in self.associative_spacing_grips()
            ]
            + [
                (_distance(point, position), array, "count", position)
                for array, position in self.associative_count_grips()
            ]
            + [
                (_distance(point, position), array, "move", position)
                for array, position in self.associative_base_grips()
            ],
            key=lambda item: item[0],
        )
        if not candidates or candidates[0][0] * self._scale > 8:
            return False
        if len(candidates) > 1 and (candidates[1][0] - candidates[0][0]) * self._scale <= 1:
            return False
        sketches_provider, arrays_provider, relations_provider, revision_provider = (
            self.associative_sketches_provider,
            self.associative_arrays_provider,
            self.associative_tangencies_provider,
            self.source_revision_provider,
        )
        if (
            sketches_provider is None
            or arrays_provider is None
            or relations_provider is None
            or revision_provider is None
        ):
            return False
        _, array, axis, position = candidates[0]
        grip_offset = (14 / self._scale, -14 / self._scale) if axis == "count" else (0.0, 0.0)
        offset = (
            rectangular_array_displacement(
                array.rows - 1,
                array.columns - 1,
                array.row_spacing,
                array.column_spacing,
                array.angle_deg,
            )
            if axis == "count"
            else (0.0, 0.0)
            if axis == "move"
            else array_spacing_grip(array, (0, 0), axis)
        )
        anchor = (
            position[0] - offset[0] - grip_offset[0],
            position[1] - offset[1] - grip_offset[1],
        )
        self._array_spacing_drag = _ArraySpacingDrag(
            uuid4().hex,
            array,
            axis,
            anchor,
            position,
            position,
            revision_provider(),
            frozenset(self.selected_entity_ids),
            self._spatial_target_frame,
            sketches_provider(),
            arrays_provider(),
            relations_provider(),
            self._draft_state(),
            self.document_layer_table,
            grip_offset=grip_offset,
            member_cache={
                (member.source, member.row, member.column): member for member in array.members
            },
        )
        self.message = {
            "count": "拖动阵列数量夹点；Esc 取消。",
            "move": "拖动阵列基点以移动阵列；Esc 取消。",
        }.get(axis, "拖动阵列间距夹点；Esc 取消。")
        self.changed.emit()
        self.update()
        return True

    def _array_spacing_drag_current(self, state: _ArraySpacingDrag) -> bool:
        return (
            self.source_revision_provider is not None
            and self.source_revision_provider() == state.revision
            and self.associative_arrays_provider is not None
            and self.associative_arrays_provider() == state.arrays
            and self.associative_sketches_provider is not None
            and self.associative_sketches_provider() == state.sketches
            and self.associative_tangencies_provider is not None
            and self.associative_tangencies_provider() == state.relations
            and self._draft_state() == state.draft
            and self.document_layer_table == state.document_layers
            and frozenset(self.selected_entity_ids) == state.selected
            and self._spatial_target_frame == state.frame
            and not self.pending_cross_tangencies
            and not self.pending_associative_arrays
            and self.mixed_move is None
        )

    def _preview_array_spacing_drag(self, point: Point2D) -> None:
        state = self._array_spacing_drag
        if state is None or state.committing:
            return
        if not self._array_spacing_drag_current(state):
            self.cancel_array_spacing_drag("文档或选择已变化；阵列夹点拖动已取消。")
            return
        state.target = point
        state.resized = None
        state.displacement = None
        resized: AssociativeRectArray | None = None
        spacing: float | None = None
        try:
            if state.axis == "move":
                delta = (point[0] - state.origin[0], point[1] - state.origin[1])
                updated, _arrays = move_associative_array_with_offsets(
                    state.sketches, state.arrays, state.array.array_id, delta
                )
                try:
                    for relation in state.relations:
                        validate_tangency_component(
                            updated, state.relations, relation.first.sketch_id
                        )
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"对象相切校验失败：{exc}") from exc
            elif state.axis == "count":
                target = (point[0] - state.grip_offset[0], point[1] - state.grip_offset[1])
                rows, columns, row_spacing, column_spacing = array_counts_from_grip(
                    state.array, state.anchor, target
                )
                if (rows, columns) == (state.array.rows, state.array.columns):
                    state.resized = state.array
                    state.preview = ()
                    state.hidden_ids = frozenset()
                    self.message = "阵列数量未变化。"
                    self.changed.emit()
                    self.update()
                    return
                targets = {member.target.sketch_id for member in state.array.members}
                if len(targets) != 1 or state.member_cache is None:
                    raise ValueError("数量夹点要求副本位于同一草图。")
                target_sketch = next(iter(targets))
                members: list[ArrayMember] = []
                for row in range(rows):
                    for column in range(columns):
                        if not (row or column):
                            continue
                        for source in state.array.sources:
                            key = (source, row, column)
                            if key not in state.member_cache:
                                state.member_cache[key] = ArrayMember(
                                    source, ArrayEntityRef(target_sketch, uuid4().hex), row, column
                                )
                            members.append(state.member_cache[key])
                resized = replace(
                    state.array,
                    rows=rows,
                    columns=columns,
                    row_spacing=row_spacing,
                    column_spacing=column_spacing,
                    members=tuple(members),
                    extra_outputs=tuple(
                        output
                        for output in state.array.extra_outputs
                        if output.row < rows and output.column < columns
                    ),
                )
                updated = resize_array(state.sketches, state.arrays, resized)
            else:
                spacing = array_spacing_from_grip(state.array, state.anchor, state.axis, point)
                old_spacing = (
                    state.array.row_spacing if state.axis == "row" else state.array.column_spacing
                )
                if math.isclose(spacing, old_spacing, rel_tol=1e-12, abs_tol=1e-10):
                    state.spacing = old_spacing
                    state.preview = ()
                    state.hidden_ids = frozenset()
                    self.message = "阵列间距未变化。"
                    self.changed.emit()
                    self.update()
                    return
                rows = spacing if state.axis == "row" else state.array.row_spacing
                columns = spacing if state.axis == "column" else state.array.column_spacing
                updated, _array = update_array_spacing(
                    state.sketches, state.arrays, state.array.array_id, rows, columns
                )
            before = {sketch.sketch_id: sketch for sketch in state.sketches}
            validate_array_cross_changes(
                before,
                {sketch.sketch_id: sketch for sketch in updated},
                state.arrays,
                state.relations,
            )
            background = {entity.entity_id: layer for entity, layer in self.background_entities}
            if len(background) != len(self.background_entities):
                raise ValueError("图元身份不唯一，无法预览阵列。")
            old_entities = {
                (sketch.sketch_id, entity.entity_id): entity
                for sketch in state.sketches
                for entity in sketch.entities
            }
            changed_refs = {
                (sketch.sketch_id, entity.entity_id)
                for sketch in updated
                for entity in sketch.entities
                if old_entities.get((sketch.sketch_id, entity.entity_id)) != entity
            }
            new_refs = {
                (sketch.sketch_id, entity.entity_id)
                for sketch in updated
                for entity in sketch.entities
            }
            removed_refs = set(old_entities) - new_refs
            changed_refs.update(removed_refs)
            for _sketch_id, identity in removed_refs:
                layer = background.get(identity)
                if layer is None or not layer.displayed or layer.locked:
                    raise ValueError("待移除的阵列副本隐藏或已锁定。")
            for array in state.arrays:
                if not (
                    state.axis == "count" and array.array_id == state.array.array_id
                ) and not any(
                    (member.target.sketch_id, member.target.entity_id) in changed_refs
                    for member in array.members
                ):
                    continue
                for source in array.sources:
                    layer = background.get(source.entity_id)
                    if layer is None or not layer.displayed or layer.locked:
                        raise ValueError("关联阵列源对象隐藏或已锁定。")
            preview: list[tuple[SketchEntity, SketchLayer]] = []
            preview_constraints: list[SketchConstraint] = []
            for sketch in updated:
                original = before[sketch.sketch_id]
                old = {entity.entity_id: entity for entity in original.entities}
                changed = tuple(
                    entity for entity in sketch.entities if old.get(entity.entity_id) != entity
                )
                if not changed:
                    continue
                if (
                    sketch.frame.u_axis != state.frame.u_axis
                    or sketch.frame.v_axis != state.frame.v_axis
                ):
                    raise ValueError("关联阵列预览包含不可见的工作平面。")
                delta = tuple(
                    a - b
                    for a, b in zip(sketch.frame.origin_mm, state.frame.origin_mm, strict=True)
                )
                shift = (
                    sum(a * b for a, b in zip(delta, state.frame.u_axis, strict=True)),
                    sum(a * b for a, b in zip(delta, state.frame.v_axis, strict=True)),
                )
                original_constraints = {item.constraint_id: item for item in original.constraints}
                for constraint in sketch.constraints:
                    if constraint == original_constraints.get(constraint.constraint_id):
                        continue

                    def project(
                        position: Point2D | None, offset: Point2D = shift
                    ) -> Point2D | None:
                        return (
                            None
                            if position is None
                            else (position[0] + offset[0], position[1] + offset[1])
                        )

                    preview_constraints.append(
                        replace(
                            constraint,
                            position_mm=project(constraint.position_mm),
                            text_position_mm=project(constraint.text_position_mm),
                        )
                    )
                projected = move_entities(
                    changed,
                    tuple(entity.entity_id for entity in changed),
                    shift,
                    preserve_rectangle_order=True,
                )
                for entity in projected:
                    layer = background.get(entity.entity_id)
                    if layer is None and state.axis == "count":
                        layer = (self.document_layer_table or sketch.layers).get(entity.layer_name)
                    if layer is None or not layer.displayed or layer.locked:
                        raise ValueError("关联阵列预览包含隐藏或锁定对象。")
                    preview.append((entity, layer))
        except (KeyError, ValueError) as exc:
            state.spacing = None
            state.displacement = None
            state.resized = None
            state.preview = ()
            state.preview_constraints = ()
            state.hidden_ids = frozenset()
            self.message = str(exc).replace("跨草图相切", "对象相切")
        else:
            if state.axis == "move":
                state.displacement = (point[0] - state.origin[0], point[1] - state.origin[1])
                self.message = "阵列移动预览；释放确认，Esc 取消。"
            elif state.axis == "count":
                assert resized is not None
                state.resized = resized
                self.message = (
                    f"阵列数量预览：{resized.rows} 行 × {resized.columns} 列；释放确认，Esc 取消。"
                )
            else:
                assert spacing is not None
                state.spacing = spacing
                self.message = f"阵列间距预览：{spacing:.8g}；释放确认，Esc 取消。"
            state.preview = tuple(preview)
            state.preview_constraints = tuple(preview_constraints)
            state.hidden_ids = frozenset(identity for _sketch_id, identity in changed_refs)
        self.changed.emit()
        self.update()

    def cancel_array_spacing_drag(self, message: str = "已取消阵列夹点拖动。") -> bool:
        state = self._array_spacing_drag
        if state is None:
            return False
        if state.committing:
            self.message = "阵列修改正在提交；完成后可撤销。"
        else:
            self._array_spacing_drag = None
            self.message = message
        self.changed.emit()
        self.update()
        return True

    def finish_array_spacing_commit(self, token: str, error: str | None) -> None:
        state = self._array_spacing_drag
        if state is None or state.token != token:
            return
        self._array_spacing_drag = None
        self.message = (
            f"阵列修改失败：{error}"
            if error
            else "已修改阵列数量；可撤销。"
            if state.axis == "count"
            else "已移动阵列；可撤销。"
            if state.axis == "move"
            else "已修改阵列间距；可撤销。"
        )
        self.changed.emit()
        self.update()

    def array_spacing_commit_is_current(self, token: str, revision: int) -> bool:
        state = self._array_spacing_drag
        return (
            state is not None
            and state.token == token
            and state.committing
            and state.revision == revision
            and self._array_spacing_drag_current(state)
        )

    def control_point_at(
        self, point: Point2D
    ) -> tuple[SketchEntity, SketchGeometryReference, Point2D] | None:
        """Resolve an unambiguous editable handle at a local position."""
        committed = tuple(
            entity
            for entity, layer in self.background_entities
            if self.select_committed_entities
            and layer.displayed
            and not layer.locked
            and entity.entity_id in self.selected_entity_ids
        )
        candidates = [
            (entity, reference, handle, _distance(point, handle))
            for entity in (
                *(item for item in self._visible_entities() if not self._layer(item).locked),
                *committed,
            )
            for reference, handle in self._entity_handles(entity)
            if _distance(point, handle) * self._scale <= 10.0
        ]
        candidates.sort(key=lambda item: item[3])
        if not candidates:
            return None
        ambiguous = [
            item for item in candidates if (item[3] - candidates[0][3]) * self._scale <= 1.0
        ]
        if len(ambiguous) > 1:
            if any(_distance(item[2], ambiguous[0][2]) > 1e-7 for item in ambiguous[1:]):
                return None
            entities = {item[0].entity_id: item[0] for item in candidates}

            def canonical(ref: SketchGeometryReference) -> SketchGeometryReference:
                owner = entities.get(ref.entity_id)
                if isinstance(owner, PolylineEntity) and ref.kind in ("start", "end"):
                    index = 0 if ref.kind == "start" else len(owner.points_mm) - 1
                    return SketchGeometryReference(ref.entity_id, "vertex", index)
                return ref

            connected = {canonical(ambiguous[0][1])}
            relations = (*self.constraints, *self.background_constraints)
            while True:
                expanded = set(connected)
                for constraint in relations:
                    if constraint.kind == "coincident" and constraint.driving:
                        references = {canonical(ref) for ref in constraint.references}
                        if references & connected:
                            expanded.update(references)
                if expanded == connected:
                    break
                connected = expanded
            if any(canonical(item[1]) not in connected for item in ambiguous):
                return None
        entity, reference, handle, _distance_mm = candidates[0]
        return entity, reference, handle

    def _begin_handle_drag(
        self, entity: SketchEntity, reference: SketchGeometryReference, origin: Point2D
    ) -> None:
        if not any(candidate is entity for candidate in self.entities):
            self._begin_saved_handle_drag(entity, reference, origin)
            return
        connected = {
            draft_tangent_reference(target).entity_id
            for _source, target in self.pending_cross_tangencies
        }
        while True:
            expanded = connected | {
                ref.entity_id
                for constraint in self.constraints
                if constraint.driving
                and any(item.entity_id in connected for item in constraint.references)
                for ref in constraint.references
            }
            if expanded == connected:
                break
            connected = expanded
        if self.mixed_handle_drag_enabled and reference.entity_id in connected:
            self._begin_mixed_draft_handle_drag(entity, reference, origin)
            return
        if self._layer(entity).locked:
            self.message = "目标图元所在图层已锁定；无法拖动。"
            self.changed.emit()
            return
        self._drag_reference = reference
        self._drag_entity_id = entity.entity_id
        self._drag_origin = origin
        self._drag_original_entities = tuple(self.entities)
        self._drag_original_constraints = tuple(self.constraints)
        self._drag_original_selection = frozenset(self.selected_entity_ids)
        self._drag_last_entities = tuple(self.entities)
        self._drag_last_constraints = tuple(self.constraints)
        self._drag_branch_warning = ""
        self.selected_entity_ids = {entity.entity_id}
        self.message = "正在拖动草图控制点；约束冲突时不会替换上一个有效预览。"
        self.changed.emit()
        self.update()

    def edit_handle_coordinate(
        self,
        entity: SketchEntity,
        reference: SketchGeometryReference,
        origin: Point2D,
        target: Point2D,
        *,
        expected_line: LineEntity | None = None,
    ) -> None:
        """Apply a numeric coordinate through the same solver and transaction as a grip."""
        if target == origin:
            self.message = "控制点未移动；草图保持原样。"
            self.changed.emit()
            return
        self._begin_handle_drag(entity, reference, origin)
        saved = self._saved_handle_drag
        if saved is not None:
            saved.expected_line = expected_line
            saved.target = target
            saved.released = True
            self._request_saved_handle_preview()
            return
        original = self._drag_original_entities
        constraints = self._drag_original_constraints
        if original is None or constraints is None or self._drag_reference != reference:
            return
        solved = self._solve_handle_drag(original, constraints, reference, target)
        if solved is None:
            error = self.message
            self._cancel_handle_drag()
            self.message = error
            self.changed.emit()
            return
        if expected_line is not None and not self._matches_expected_line(solved[0], expected_line):
            self._cancel_handle_drag()
            self.message = "约束不允许保持起点和方向修改长度；图形未修改。"
            self.changed.emit()
            return
        self._drag_last_entities, self._drag_last_constraints = solved
        self._finish_handle_drag()

    @staticmethod
    def _matches_expected_line(entities: Iterable[SketchEntity], expected: LineEntity) -> bool:
        matches = [entity for entity in entities if entity.entity_id == expected.entity_id]
        if len(matches) != 1 or not isinstance(matches[0], LineEntity):
            return False
        actual = matches[0]
        return (
            math.dist(actual.start_mm, expected.start_mm) <= 1e-7
            and math.dist(actual.end_mm, expected.end_mm) <= 1e-7
        )

    @property
    def saved_handle_preview(self) -> tuple[tuple[SketchEntity, SketchLayer], ...]:
        state = self._saved_handle_drag
        return () if state is None or state.preview is None else state.preview.overlay

    @property
    def saved_handle_drag_active(self) -> bool:
        return self._saved_handle_drag is not None

    def _begin_saved_handle_drag(
        self, entity: SketchEntity, reference: SketchGeometryReference, origin: Point2D
    ) -> None:
        layers = [
            layer for item, layer in self.background_entities if item.entity_id == entity.entity_id
        ]
        if len(layers) != 1 or any(item.entity_id == entity.entity_id for item in self.entities):
            self.message = "图元身份不唯一，无法拖动已保存控制点。"
        elif layers[0].locked or not layers[0].displayed:
            self.message = "目标图元所在图层已锁定或隐藏。"
        elif (
            self.mixed_move is not None or self.pending_cross_tangencies
        ) and not self.mixed_handle_drag_enabled:
            self.message = "请先完成或取消当前混合草图，再拖动已保存图元。"
        elif self.source_revision_provider is None:
            self.message = "无法确认文档版本，已取消拖动。"
        elif (
            self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            self.message = "文档已变化，请重新选择图元。"
            self.source_revision_invalidated.emit()
        else:
            revision = self.source_revision_provider()
            self._saved_handle_drag = _SavedHandleDrag(
                uuid4().hex, reference, origin, origin, revision
            )
            self.message = "拖动已保存控制点；Esc 取消。"
        self.changed.emit()
        self.update()

    def _begin_mixed_draft_handle_drag(
        self, entity: SketchEntity, reference: SketchGeometryReference, origin: Point2D
    ) -> None:
        if self._layer(entity).locked or not self._layer(entity).displayed:
            self.message = "目标图元所在图层已锁定或隐藏。"
        elif sum(item.entity_id == entity.entity_id for item in self.entities) != 1 or any(
            item.entity_id == entity.entity_id for item, _layer in self.background_entities
        ):
            self.message = "图元身份不唯一，无法拖动控制点。"
        elif self.source_revision_provider is None:
            self.message = "无法确认文档版本，已取消拖动。"
        elif (
            self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            self.message = "文档已变化，请重新选择图元。"
            self.source_revision_invalidated.emit()
        else:
            self._saved_handle_drag = _SavedHandleDrag(
                uuid4().hex, reference, origin, origin, self.source_revision_provider()
            )
            self.selected_entity_ids = {entity.entity_id}
            self.message = "拖动草稿控制点并预览相切关联；Esc 取消。"
        self.changed.emit()
        self.update()

    def _request_saved_handle_preview(self) -> None:
        state = self._saved_handle_drag
        if state is None or state.inflight is not None or state.committing:
            return
        if state.preview_point == state.target and state.preview is not None:
            if state.released:
                state.committing = True
                self.saved_handle_commit_requested.emit(state.token, state.preview, state.revision)
            return
        state.inflight = state.target
        self.saved_handle_preview_requested.emit(
            state.token, state.reference, state.target, state.revision
        )

    def complete_saved_handle_preview(
        self, token: str, point: Point2D, preview: SavedHandlePreview | None, error: str | None
    ) -> None:
        state = self._saved_handle_drag
        if state is None or state.token != token or state.inflight != point:
            return
        state.inflight = None
        if (
            self.source_revision_provider is None
            or self.source_revision_provider() != state.revision
        ):
            self.cancel_saved_handle_drag("文档已变化；拖动未提交。")
            self.source_revision_invalidated.emit()
            return
        if state.target != point:
            self._request_saved_handle_preview()
            return
        if preview is None:
            self.message = error or "拖动位置无法满足约束。"
            if state.released:
                self.cancel_saved_handle_drag(self.message)
            else:
                self.changed.emit()
                self.update()
            return
        if state.expected_line is not None and not self._matches_expected_line(
            (entity for entity, _layer in preview.overlay), state.expected_line
        ):
            self.cancel_saved_handle_drag("约束不允许保持起点和方向修改长度；图形未修改。")
            return
        state.preview = preview
        state.preview_point = point
        self.message = "关联草图拖动预览；松开鼠标提交，Esc 取消。"
        self.changed.emit()
        self.update()
        if state.released:
            self._request_saved_handle_preview()

    def saved_handle_commit_is_current(self, token: str, revision: int) -> bool:
        state = self._saved_handle_drag
        return (
            state is not None
            and state.token == token
            and state.revision == revision
            and state.committing
            and self.source_revision_provider is not None
            and self.source_revision_provider() == revision
        )

    def finish_saved_handle_commit(self, token: str, error: str | None) -> None:
        state = self._saved_handle_drag
        if state is None or state.token != token:
            return
        self._saved_handle_drag = None
        self.message = f"拖动失败：{error}" if error else "已更新控制点和相切关联；可撤销。"
        self.changed.emit()
        self.update()

    def cancel_saved_handle_drag(self, message: str = "已取消控制点拖动。") -> bool:
        if self._saved_handle_drag is None:
            return False
        if self._saved_handle_drag.committing:
            self.message = "控制点修改正在提交；完成后可撤销。"
            self.changed.emit()
            return True
        self._saved_handle_drag = None
        self.message = message
        self.saved_handle_cancelled.emit()
        self.changed.emit()
        self.update()
        return True

    @property
    def transform_preview_entities(self) -> tuple[SketchEntity, ...]:
        return self._transform_preview

    @property
    def active_transform(self) -> str | None:
        return self._transform_operation

    @property
    def transform_selecting(self) -> bool:
        return self._transform_operation is not None and self._transform_selecting

    def begin_interactive_offset(self) -> None:
        """Start the independent 2D distance, object and side interaction."""
        if not self.set_tool("选择元素"):
            return
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            self.source_revision_invalidated.emit()
            self.message = "文档已变化；请重新开始偏移。"
            self.changed.emit()
            return
        self.selected_entity_ids.clear()
        self._transform_operation = "offset"
        self._transform_source_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self._copy_array_awaiting_count = False
        self._copy_array_count = None
        self._copy_array_fit = False
        self._copy_array_ids = frozenset()
        self._copy_array_sources = ()
        self._copy_array_image_sources = ()
        self._copy_array_preview_point = None
        self._copy_array_candidate = ()
        self._mirror_ask_erase = False
        self._mirror_axis_end = None
        self._mirror_candidate = ()
        self._mirror_selected_sources = ()
        self._mirror_selected_ids = frozenset()
        self._offset_distance = None
        self._offset_through = False
        self._offset_distance_anchor = None
        self.offset_erase_source = False
        self.offset_erase_pending = False
        self.offset_layer_pending = False
        self._offset_multiple = False
        self._offset_undo_positions.clear()
        self._offset_pending_result_id = None
        self._offset_target = None
        self._offset_signed_distance = None
        self._transform_preview = ()
        default = (
            "通过点" if self.offset_default_distance < 0 else f"{self.offset_default_distance:g}"
        )
        self.message = f"偏移：输入距离、两点量距或 T；Enter 使用 {default}；Esc 取消。"
        self.changed.emit()
        self.update()

    def set_interactive_offset_distance(self, distance: float) -> None:
        """Set a finite positive offset distance for the active operation."""
        if self._transform_operation != "offset" or not self._transform_revision_current():
            raise ValueError("偏移命令已结束。")
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError("偏移距离必须是大于零的有限数值。")
        self._offset_distance = distance
        self.set_offset_default_distance(distance)
        self._offset_through = False
        self._offset_distance_anchor = None
        self._offset_target = None
        self._offset_signed_distance = None
        self._transform_preview = ()
        self.message = "偏移：选择对象，Enter / 右键结束。"
        self.changed.emit()
        self.update()

    def set_interactive_offset_layer(self, current: bool) -> None:
        """Select the destination layer for subsequent offset copies."""
        if self._transform_operation != "offset" or not self._transform_revision_current():
            raise ValueError("偏移命令已结束。")
        self.offset_layer_current = current
        self.offset_layer_pending = False
        self._offset_signed_distance = None
        self._transform_preview = ()
        self.message = "偏移目标层：当前层。" if current else "偏移目标层：源对象层。"
        self.changed.emit()
        self.update()

    def set_interactive_offset_multiple(self) -> None:
        if self._transform_operation != "offset" or self._offset_target is None:
            raise ValueError("请先选择要连续偏移的对象。")
        if not self._transform_revision_current():
            raise ValueError("偏移命令已结束。")
        self._offset_multiple = True
        self.message = "连续偏移：指定偏移侧或通过点；Enter 结束。"
        self.changed.emit()

    def begin_rectangular_array_preview(
        self,
        rows: int,
        columns: int,
        row_spacing: float,
        column_spacing: float,
        angle_deg: float = 0,
    ) -> None:
        """Create a reversible visual candidate without changing the draft."""
        if self.has_pending_geometry or (
            self.has_active_edit_gesture
            and self._transform_operation != "rectangular_array_preview"
        ):
            raise ValueError("请先完成或取消当前操作。")
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
            and self._selected_committed_entities()
        ):
            self.source_revision_invalidated.emit()
            raise ValueError("文档已变化；请重新选择图元。")
        error = self.transform_selection_error("rectangular_array")
        if error:
            raise ValueError(error)
        background = (
            tuple(entity for entity, _ in self.background_entities)
            if self.select_committed_entities
            else ()
        )
        source = (*self.entities, *background)
        selected = tuple(
            entity.entity_id for entity in source if entity.entity_id in self.selected_entity_ids
        )
        if len(selected) != len(set(selected)) or set(selected) != self.selected_entity_ids:
            raise ValueError("选择的图元身份不唯一或已变化。")
        result = rectangular_array_entities(
            source,
            selected,
            rows=rows,
            columns=columns,
            row_spacing=row_spacing,
            column_spacing=column_spacing,
            angle_deg=angle_deg,
        )
        self._transform_operation = "rectangular_array_preview"
        self._transform_source_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self._transform_preview = result[len(source) :]
        self.message = (
            "矩形阵列预览：R 行、C 列、CO 数量、S 间距、AN 角度、B 基点、AS 关联；Enter / X 确认。"
        )
        self.changed.emit()
        self.update()

    def rectangular_array_unit_point(self, screen: QPointF, *, disable_snapping: bool) -> Point2D:
        """Resolve a unit-cell corner with the canvas's normal object/grid snaps."""
        point, _kind = self._placement_point(
            self.screen_to_local(screen), temporarily_disable_snapping=disable_snapping
        )
        return point

    def begin_polar_array_preview(self, count: int, center: Point2D, angle_deg: float) -> None:
        """Preview independent polar-array copies before the user confirms."""
        if self.has_pending_geometry or (
            self.has_active_edit_gesture and self._transform_operation != "polar_array_preview"
        ):
            raise ValueError("请先完成或取消当前操作。")
        if self.selected_raster_ids or self.selected_constraint_ids:
            raise ValueError("环形阵列目前只支持二维图元，请取消图片或尺寸选择。")
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
            and self._selected_committed_entities()
        ):
            self.source_revision_invalidated.emit()
            raise ValueError("文档已变化；请重新选择图元。")
        error = self.transform_selection_error("circular_array")
        if error:
            raise ValueError(error)
        background = (
            tuple(entity for entity, _ in self.background_entities)
            if self.select_committed_entities
            else ()
        )
        source = (*self.entities, *background)
        selected = tuple(
            entity.entity_id for entity in source if entity.entity_id in self.selected_entity_ids
        )
        if (
            not selected
            or len(selected) != len(set(selected))
            or set(selected) != self.selected_entity_ids
        ):
            raise ValueError("选择的图元身份不唯一或已变化。")
        if (count - 1) * len(selected) > 10000:
            raise ValueError("环形阵列生成的图元超过 10000 个。")
        result = circular_array_entities(
            source, selected, count=count, center_mm=center, total_angle_deg=angle_deg
        )
        self._transform_operation = "polar_array_preview"
        self._transform_source_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self._transform_preview = result[len(source) :]
        self.message = "环形阵列预览：I 数量、A 角度；Enter 确认独立副本，Esc 取消。"
        self.changed.emit()
        self.update()

    def commit_polar_array_preview(self) -> bool:
        if (
            self._transform_operation != "polar_array_preview"
            or not self._transform_revision_current()
        ):
            return False
        candidate = self._transform_preview
        self.cancel_transform()
        if not self.replace_draft_entities((*self.entities, *candidate), select_new=True):
            return False
        self.message = "已生成环形阵列独立副本；可撤销。"
        self.changed.emit()
        return True

    def commit_rectangular_array_preview(self) -> bool:
        if (
            self._transform_operation != "rectangular_array_preview"
            or not self._transform_revision_current()
        ):
            return False
        candidate = self._transform_preview
        self.cancel_transform()
        if not self.replace_draft_entities((*self.entities, *candidate), select_new=True):
            return False
        self.message = "已生成矩形阵列；行列数包含原始位置。"
        self.changed.emit()
        return True

    def undo_interactive_offset(self) -> bool:
        if not self._transform_revision_current():
            return False
        if (
            not self._offset_undo_positions
            or self._offset_undo_positions[-1] != self.history_position
        ):
            self.message = "当前偏移命令没有可撤销的操作，或草稿历史已变化。"
            self.changed.emit()
            return False
        if not self._undo_history or self.has_pending_geometry:
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self._offset_undo_positions.pop()
        self._offset_target = None
        self._offset_multiple = False
        self._offset_signed_distance = None
        self._transform_preview = ()
        self.selected_entity_ids.clear()
        self.message = "已撤销当前偏移；选择对象继续。"
        self.changed.emit()
        self.update()
        return True

    @property
    def interactive_offset_needs_distance(self) -> bool:
        return (
            self._transform_operation == "offset"
            and self._offset_distance is None
            and not self._offset_through
        )

    def set_interactive_offset_through(self, *, update_default: bool = True) -> None:
        """Select a source and then a point through which its offset will pass."""
        if self._transform_operation != "offset" or not self._transform_revision_current():
            raise ValueError("偏移命令已结束。")
        self._offset_through = True
        if update_default:
            self.set_offset_default_distance(-1.0)
        self._offset_distance = None
        self._offset_distance_anchor = None
        self._offset_target = None
        self._offset_signed_distance = None
        self._transform_preview = ()
        self.message = "通过点偏移：选择对象；Enter / 右键结束。"
        self.changed.emit()
        self.update()

    def set_offset_default_distance(self, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("OFFSETDIST 必须为有限数值。")
        if value != self.offset_default_distance:
            self.offset_default_distance = value
            self.offset_default_distance_changed.emit(value)

    def set_offset_gap_type(self, value: int) -> None:
        if value not in (0, 1, 2):
            raise ValueError("OFFSETGAPTYPE 必须为 0、1 或 2。")
        if value != self.offset_gap_type:
            self.offset_gap_type = value
            if self._transform_operation == "offset":
                self._offset_signed_distance = None
                self._transform_preview = ()
                self.update()
            self.offset_gap_type_changed.emit(value)

    def use_interactive_offset_default(self) -> None:
        if self._offset_distance_anchor is not None:
            raise ValueError("偏移：请指定量距第二点。")
        if self.offset_default_distance < 0:
            self.set_interactive_offset_through(update_default=False)
        else:
            self.set_interactive_offset_distance(self.offset_default_distance)

    def set_interactive_offset_distance_point(self, point: Point2D) -> None:
        """Set a positive offset distance by measuring between two points."""
        if not self.interactive_offset_needs_distance or not self._transform_revision_current():
            raise ValueError("偏移量距已结束。")
        if not all(math.isfinite(value) for value in point):
            raise ValueError("量距点坐标必须有限。")
        if self._offset_distance_anchor is None:
            self._offset_distance_anchor = point
            self.message = "偏移：指定量距第二点；Esc 取消。"
            self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        distance = math.dist(self._offset_distance_anchor, point)
        self.set_interactive_offset_distance(distance)
        self.point_accepted.emit(point)

    def _interactive_offset_point(self, point: Point2D, *, commit: bool) -> None:
        if not self._transform_revision_current():
            return
        if self.offset_erase_pending or self.offset_layer_pending:
            self.message = "请先在命令栏完成偏移选项。"
            self.changed.emit()
            return
        if self._offset_distance is None and not self._offset_through:
            if commit:
                try:
                    self.set_interactive_offset_distance_point(point)
                except ValueError as exc:
                    self.message = str(exc)
                    self.changed.emit()
            return
        if self._offset_target is None:
            if not commit:
                return
            identity = self._hit_entity_at(point)
            matches = [
                entity for entity in self.selectable_entities() if entity.entity_id == identity
            ]
            all_ids = [entity.entity_id for entity in self.entities]
            if self.select_committed_entities:
                all_ids.extend(entity.entity_id for entity, _layer in self.background_entities)
            if identity is None or len(matches) != 1 or all_ids.count(identity) != 1:
                self.message = "请选择唯一的可见对象。"
            else:
                self.selected_entity_ids = {identity}
                error = self.transform_selection_error("offset")
                if error:
                    self.message = error
                    self.selected_entity_ids.clear()
                elif isinstance(matches[0], PointEntity | SplineEntity):
                    self.selected_entity_ids.clear()
                    self.message = "点和样条暂不支持偏移；请选择其他对象。"
                else:
                    self._offset_target = matches[0]
                    self.message = (
                        "偏移：指定通过点；Esc 取消。"
                        if self._offset_through
                        else "偏移：指定对象的偏移侧；Esc 取消。"
                    )
            self.changed.emit()
            self.update()
            return
        identity = self._offset_target.entity_id
        current = [entity for entity in self.selectable_entities() if entity.entity_id == identity]
        all_ids = [entity.entity_id for entity in self.entities]
        if self.select_committed_entities:
            all_ids.extend(entity.entity_id for entity, _layer in self.background_entities)
        error = self.transform_selection_error("offset")
        if (
            len(current) != 1
            or current[0] != self._offset_target
            or all_ids.count(identity) != 1
            or self.selected_entity_ids != {identity}
            or error
        ):
            self._offset_target = None
            self._offset_signed_distance = None
            self._transform_preview = ()
            self.selected_entity_ids.clear()
            self.message = error or "偏移对象已变化；请重新选择。"
            self.changed.emit()
            self.update()
            return
        try:
            target_layer = (
                self.active_layer_name
                if self.offset_layer_current
                else self._offset_target.layer_name
            )
            destination = self.layer_table.get(target_layer)
            if destination.locked or not destination.displayed:
                raise ValueError("偏移目标图层已锁定或隐藏。")
            if self._offset_through:
                signed = through_offset_distance(
                    self._offset_target, point, gap_type=self.offset_gap_type
                )
            else:
                assert self._offset_distance is not None
                signed = signed_offset_distance(self._offset_target, point, self._offset_distance)
            if signed != self._offset_signed_distance or not self._transform_preview:
                source = (self._offset_target,)
                result = offset_entities(
                    source, (self._offset_target.entity_id,), signed, gap_type=self.offset_gap_type
                )[1:]
                self._transform_preview = tuple(
                    replace(entity, layer_name=target_layer) for entity in result
                )
                self._offset_signed_distance = signed
        except ValueError as exc:
            self._transform_preview = ()
            self._offset_signed_distance = None
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return
        if commit:
            candidate = self._transform_preview
            is_saved = any(entity.entity_id == identity for entity, _ in self.background_entities)
            if self.offset_erase_source and is_saved:
                if self.source_revision_provider is None:
                    self.message = "缺少文档版本；无法安全删除已保存对象。"
                    self.changed.emit()
                    return
                if any(
                    ref.entity_id == identity
                    for constraint in self.background_constraints
                    for ref in constraint.references
                ):
                    self.message = "已保存对象有关联约束；请先处理约束。"
                    self.changed.emit()
                    return
                draft = (*self.entities, *candidate)
                background = tuple(
                    (entity, layer)
                    for entity, layer in self.background_entities
                    if entity.entity_id != identity
                )
                self._offset_target = None
                self._offset_pending_result_id = candidate[0].entity_id
                self._offset_signed_distance = None
                self._transform_preview = ()
                self.message = "正在校验偏移与删除源对象。"
                self.point_accepted.emit(point)
                self.committed_drag_trim_requested.emit(
                    ((identity, ()),),
                    draft,
                    tuple(self.constraints),
                    background,
                    self.source_revision_provider(),
                )
            elif self.replace_draft_entities(
                (
                    *(
                        entity
                        for entity in self.entities
                        if not self.offset_erase_source or entity.entity_id != identity
                    ),
                    *candidate,
                )
            ):
                self._offset_undo_positions.append(self.history_position)
                self._offset_target = candidate[0] if self._offset_multiple else None
                self._offset_signed_distance = None
                self._transform_preview = ()
                self.selected_entity_ids = (
                    {candidate[0].entity_id} if self._offset_multiple else set()
                )
                self.message = (
                    "已偏移；继续指定偏移侧或通过点。"
                    if self._offset_multiple
                    else "已偏移；选择下一个对象，Enter / 右键结束。"
                )
                self.point_accepted.emit(point)
        self.changed.emit()
        self.update()

    def begin_transform(
        self,
        operation: str,
        *,
        reference_rotation: bool = False,
        keep_source: bool = True,
        ask_mirror_erase: bool = False,
    ) -> None:
        if (
            operation not in {"move", "copy", "rotate", "mirror", "erase", "scale"}
            or self.has_pending_geometry
        ):
            return
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            self.cancel_transform()
            self.source_revision_invalidated.emit()
            self.message = "文档已变化；请重新选择图元并开始操作。"
            self.changed.emit()
            return
        if not self.set_tool("选择元素"):
            return
        if (
            self.selected_raster_id is not None
            and (self.selected_entity_ids or self.selected_constraint_ids)
            and (
                operation not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
                or (self.selected_constraint_ids and operation != "erase")
            )
        ):
            self.message = "暂不能同时变换图片和其他对象，请分别选择。"
            self.changed.emit()
            return
        if (
            self.selected_raster_ids
            and any(entity.entity_id in self.selected_entity_ids for entity in self.entities)
            and (
                operation not in {"move", "scale", "rotate", "mirror", "erase", "copy"}
                or (
                    self._selected_committed_entities()
                    and operation not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
                )
            )
        ):
            self.message = "暂不能同时变换图片、草稿和已提交图元，请分开操作。"
            self.changed.emit()
            return
        error = self.transform_selection_error(operation)
        if error:
            self.message = error
            self.changed.emit()
            return
        self._transform_operation = operation
        self._reference_previous_mode = None
        self._transform_source_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self._transform_reference_mode = reference_rotation
        self._transform_reference = None
        self._transform_reference_end = None
        self._transform_reference_angle = None
        self._rotation_target_points_active = False
        self._rotation_target_first = None
        self._rotation_copy = False
        self._scale_copy = False
        self._scale_reference_active = False
        self._scale_reference_length = None
        self._scale_reference_first = None
        self._scale_target_points_active = False
        self._scale_target_first = None
        self._transform_keep_source = True if ask_mirror_erase else keep_source
        self._mirror_ask_erase = operation == "mirror" and ask_mirror_erase
        self._mirror_previous_keep_source = keep_source if self._mirror_ask_erase else None
        if self._mirror_ask_erase:
            self.mirror_keep_source_mode_changed.emit(True)
        self._mirror_axis_end = None
        self._mirror_candidate = ()
        self._mirror_selected_sources = ()
        self._copy_repeat = self.copy_mode == 0
        self._transform_angle_text = ""
        self._transform_selecting = not bool(self.selected_entity_ids or self.selected_raster_id)
        self._transform_base = None
        self._transform_preview = ()
        self._copy_placements.clear()
        self._mixed_copy_placements.clear()
        self._mixed_draft_copy_ids.clear()
        self._mixed_copy_pending_point = None
        self._mixed_copy_started = False
        self.message = (
            (
                "选择要删除的图元，Enter / 右键确认。"
                if operation == "erase"
                else "选择要变换的图元，Enter / 右键结束选择。"
            )
            if self._transform_selecting
            else self._transform_point_hint()
        )
        self.changed.emit()
        self.setFocus()

    def configure_active_transform(self, *, reference_rotation: bool, keep_source: bool) -> None:
        """Refresh the current preview when its visible options change."""
        if self._transform_operation == "rotate":
            if reference_rotation == self._transform_reference_mode:
                return
            self._transform_reference_mode = reference_rotation
            self._transform_reference = None
            self._transform_reference_end = None
            self._transform_reference_angle = None
            self._rotation_target_points_active = False
            self._rotation_target_first = None
            self._transform_angle_text = ""
        elif self._transform_operation == "mirror":
            if self._mirror_ask_erase:
                return
            if keep_source == self._transform_keep_source:
                return
            self._transform_keep_source = keep_source
        else:
            return
        self._transform_preview = ()
        self.message = self._transform_point_hint()
        if not self._transform_selecting and self._cursor is not None:
            self._transform_point(self._cursor, commit=False)
        self.changed.emit()
        self.update()

    def _transform_revision_current(self) -> bool:
        if (
            self._transform_source_revision is None
            or self.source_revision_provider is None
            or self.source_revision_provider() == self._transform_source_revision
        ):
            return True
        self.cancel_transform()
        self.source_revision_invalidated.emit()
        self.message = "文档已变化；操作已取消，请重新选择图元。"
        self.changed.emit()
        self.update()
        return False

    def cancel_transform(self) -> bool:
        if self._transform_operation is None:
            return False
        self._transform_operation = None
        self._raster_transform_preview = None
        self._raster_transform_previews = ()
        previous_reference_mode = self._reference_previous_mode
        previous_mirror_mode = self._mirror_previous_keep_source
        self._reference_previous_mode = None
        self._mirror_previous_keep_source = None
        self._copy_array_awaiting_count = False
        self._copy_array_count = None
        self._copy_array_fit = False
        self._copy_array_ids = frozenset()
        self._copy_array_sources = ()
        self._copy_array_preview_point = None
        self._copy_array_candidate = ()
        self._mirror_ask_erase = False
        self._mirror_axis_end = None
        self._mirror_candidate = ()
        self._mirror_selected_sources = ()
        self._mirror_selected_ids = frozenset()
        self._offset_distance = None
        self._offset_through = False
        self._offset_distance_anchor = None
        self.offset_erase_source = False
        self.offset_erase_pending = False
        self.offset_layer_pending = False
        self._offset_multiple = False
        self._offset_undo_positions.clear()
        self._offset_pending_result_id = None
        self._offset_target = None
        self._offset_signed_distance = None
        self._transform_source_revision = None
        self._transform_base = None
        self._transform_preview = ()
        self._transform_selecting = False
        self._transform_reference = None
        self._transform_reference_end = None
        self._transform_reference_angle = None
        self._rotation_target_points_active = False
        self._rotation_target_first = None
        self._rotation_copy = False
        self._scale_copy = False
        self._scale_reference_active = False
        self._scale_reference_length = None
        self._scale_reference_first = None
        self._scale_target_points_active = False
        self._scale_target_first = None
        self._transform_angle_text = ""
        self._copy_placements.clear()
        self._mixed_copy_placements.clear()
        self._mixed_draft_copy_ids.clear()
        self._mixed_copy_pending_point = None
        self._mixed_copy_started = False
        if previous_reference_mode is not None:
            self.rotation_reference_mode_changed.emit(previous_reference_mode)
        if previous_mirror_mode is not None:
            self.mirror_keep_source_mode_changed.emit(previous_mirror_mode)
        self.message = "已结束变换；已完成的修改保留。"
        self.changed.emit()
        self.update()
        return True

    def set_copy_mode(self, mode: int) -> None:
        """Set independent 2D copy behavior: 0 repeats, 1 places once."""
        if mode not in (0, 1):
            raise ValueError("COPYMODE 必须为 0 或 1。")
        if self.copy_mode != mode:
            self.copy_mode = mode
            self.copy_mode_changed.emit(mode)
        if self.copy_options_available:
            self._copy_repeat = mode == 0

    @property
    def copy_options_available(self) -> bool:
        """Whether COPY is waiting for its base point after selection."""
        return (
            self._transform_operation == "copy"
            and not self._transform_selecting
            and self._transform_base is None
        )

    def use_multiple_copy_for_command(self) -> None:
        """Enable repetition for the current COPY without changing its preference."""
        if not self.copy_options_available:
            raise ValueError("请先选择对象，再设置当前复制模式。")
        self._copy_repeat = True

    def use_single_copy_for_command(self) -> None:
        """Use a single placement without changing the COPYMODE preference."""
        if not self.copy_options_available:
            raise ValueError("请先选择对象，再设置当前复制模式。")
        self._copy_repeat = False

    @property
    def copy_array_available(self) -> bool:
        return (
            self._transform_operation == "copy"
            and not self._transform_selecting
            and self._transform_base is not None
        )

    @property
    def copy_array_needs_count(self) -> bool:
        return self.copy_array_available and self._copy_array_awaiting_count

    @property
    def copy_array_waiting_point(self) -> bool:
        return self.copy_array_available and self._copy_array_count is not None

    def begin_copy_array(self) -> bool:
        if not self.copy_array_available or not self._transform_revision_current():
            return False
        error = self.transform_selection_error("linear_array")
        if error:
            self.message = error
            self.changed.emit()
            return False
        self._copy_array_ids = frozenset(self.selected_entity_ids)
        self._copy_array_sources = tuple(
            entity
            for entity in self.selectable_entities()
            if entity.entity_id in self._copy_array_ids
        )
        self._copy_array_image_sources = tuple(
            image for image in self.drawing_rasters if image.image_id in self.selected_raster_ids
        )
        if len(self._copy_array_image_sources) != len(self.selected_raster_ids):
            self.message = "选择的图片已变化，请重新选择。"
            self.changed.emit()
            return False
        if len(self._copy_array_sources) != len(self._copy_array_ids):
            self.message = "选择的图元已变化或身份不唯一。"
            self.changed.emit()
            return False
        self._copy_array_history = self.history_position
        self._copy_array_awaiting_count = True
        self._copy_array_count = None
        self._copy_array_fit = False
        self._copy_array_preview_point = None
        self._copy_array_candidate = ()
        self._transform_preview = ()
        self.message = "复制阵列：输入总数量（包含原对象，2–1000）。"
        self.changed.emit()
        self.update()
        return True

    def set_copy_array_count(self, count: int) -> None:
        if not self.copy_array_needs_count or not self._transform_revision_current():
            raise ValueError("复制阵列已失效。")
        if isinstance(count, bool) or count < 2 or count > 1000:
            raise ValueError("复制阵列数量必须为 2 到 1000 的整数。")
        if self.selected_raster_ids and len(self.selected_raster_ids) * (count - 1) > 1000:
            raise ValueError("复制阵列最多生成 1000 张图片。")
        if self.selected_raster_ids and len(self.selected_entity_ids) * (count - 1) > 10000:
            raise ValueError("复制阵列最多生成 10000 个图元。")
        self._copy_array_count = count
        self._copy_array_awaiting_count = False
        self.message = "复制阵列：指定步距点，或输入 F 按总位移适合。"
        self.changed.emit()
        self.update()

    def set_copy_array_fit(self) -> None:
        if not self.copy_array_waiting_point:
            raise ValueError("请先输入复制阵列数量。")
        if not self._transform_revision_current():
            raise ValueError("复制阵列来源已变化；请重新开始。")
        self._copy_array_fit = True
        self._copy_array_preview_point = None
        self._copy_array_candidate = ()
        self._transform_preview = ()
        self.message = "复制阵列适合：指定最后副本的位置。"
        self.changed.emit()
        self.update()

    def transform_selection_error(self, operation: str) -> str:
        """Explain why the selection cannot be transformed without changing geometry."""
        if self._selected_committed_entities() and operation not in {
            "move",
            "copy",
            "rotate",
            "scale",
            "mirror",
            "delete_mixed",
            "offset",
            "linear_array",
            "rectangular_array",
            "circular_array",
        }:
            return "选择包含已提交图元；几何修改请通过历史编辑，当前选择已保留。"
        if operation in {
            "move",
            "copy",
            "rotate",
            "scale",
            "mirror",
            "offset",
            "linear_array",
            "rectangular_array",
            "circular_array",
        } and any(
            layer.locked and entity.entity_id in self.selected_entity_ids
            for entity, layer in self.background_entities
        ):
            return "选择包含已锁定图层；草稿未修改。"
        if operation in {
            "scale",
            "offset",
            "linear_array",
            "rectangular_array",
            "circular_array",
        } and any(
            not layer.displayed and entity.entity_id in self.selected_entity_ids
            for entity, layer in self.background_entities
        ):
            return "选择包含隐藏图层；草稿未修改。"
        if any(
            self._layer(entity).locked
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        ):
            return "选择包含已锁定图层；草稿未修改。"
        if any(
            not self._layer(entity).displayed
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        ):
            return "选择包含隐藏图层；草稿未修改。"
        if (
            operation == "move"
            and not self.selected_user_tangencies_transformable()
            and any(
                constraint.source == "user"
                and any(
                    reference.entity_id in self.selected_entity_ids
                    for reference in constraint.references
                )
                for constraint in self.constraints
            )
        ):
            return "本次移动会改变用户约束引用的图元；请先处理相关约束再改几何。草稿未变。"
        return ""

    def copy_to_clipboard(self) -> bool:
        """Copy selected drawing entities and their wholly internal relations."""
        if (
            not self.select_committed_entities
            or self.has_pending_geometry
            or self.has_active_edit_gesture
        ):
            self.message = "请先完成当前操作，再复制二维图元。"
            self.changed.emit()
            return False
        if self.selected_raster_id is not None and not (
            self.selected_entity_ids or self.selected_constraint_ids
        ):
            if len(self.selected_raster_ids) > 1:
                if self.selected_entity_ids or self.selected_constraint_ids:
                    self.message = "暂不能同时复制图片和其他对象，请分别选择。"
                    self.changed.emit()
                    return False
                images = tuple(
                    item
                    for item in self.drawing_rasters
                    if item.image_id in self.selected_raster_ids
                )
                try:
                    if len(images) != len(self.selected_raster_ids):
                        raise ValueError("所选图片已变化，请重新选择。")
                    data = encode_raster_group(images)
                except ValueError as exc:
                    self.message = str(exc)
                    self.changed.emit()
                    return False
                mime = QMimeData()
                mime.setData(DRAWING_RASTER_GROUP_MIME, QByteArray(data))
                QApplication.clipboard().setMimeData(mime)
                self.message = f"已复制 {len(images)} 张图片；Ctrl+V 粘贴。"
                self.changed.emit()
                return True
            if self.selected_entity_ids or self.selected_constraint_ids:
                self.message = "暂不能同时复制图片和其他对象，请分别选择。"
                self.changed.emit()
                return False
            image = next(
                (item for item in self.drawing_rasters if item.image_id == self.selected_raster_id),
                None,
            )
            if image is not None:
                mime = QMimeData()
                mime.setImageData(QImage.fromData(image.png_bytes))
                mime.setData(
                    DRAWING_RASTER_MIME,
                    QByteArray(
                        json.dumps(
                            [image.width_mm, image.height_mm, image.angle_deg, image.mirrored]
                        ).encode("utf-8")
                    ),
                )
                QApplication.clipboard().setMimeData(mime)
                self.message = "已复制图片。"
                self.changed.emit()
                return True
        entities = tuple(
            entity
            for entity in self.selectable_entities()
            if entity.entity_id in self.selected_entity_ids
        )
        identities = {entity.entity_id for entity in entities}
        if identities != self.selected_entity_ids or len(identities) != len(entities):
            self.message = "选择的图元已变化或身份不唯一；请重新选择。"
            self.changed.emit()
            return False
        all_constraints = self.dimension_constraints()
        constraints = tuple(
            c for c in all_constraints if all(ref.entity_id in identities for ref in c.references)
        )
        if self.selected_constraint_ids - {c.constraint_id for c in constraints}:
            self.message = "复制标注时请同时选择其引用的图元。"
            self.changed.emit()
            return False
        if any(
            ref.entity_id in self.background_entity_basis
            for constraint in constraints
            for ref in constraint.references
        ):
            self.message = "旋转工作平面的关联标注暂不能复制；请先切换至其原工作平面。"
            self.changed.emit()
            return False
        try:
            sketch = Sketch(
                uuid4().hex, WorkPlaneFrame.xy(), entities, constraints, self.layer_table
            )
            images = tuple(
                image
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
            if len(images) != len(self.selected_raster_ids):
                raise ValueError("所选图片已变化，请重新选择。")
            data = (
                encode_mixed_clipboard(sketch, images, self.drawing_dimension_styles)
                if images
                else encode_drawing_clipboard(sketch, self.drawing_dimension_styles)
            )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        mime = QMimeData()
        mime.setData(
            DRAWING_MIXED_CLIPBOARD_MIME if images else DRAWING_CLIPBOARD_MIME, QByteArray(data)
        )
        QApplication.clipboard().setMimeData(mime)
        self.message = f"已复制 {len(entities)} 个二维图元"
        if images:
            self.message += f"和 {len(images)} 张图片"
        self.message += "；Ctrl+V 粘贴。"
        omitted_local = any(
            any(ref.entity_id in identities for ref in constraint.references)
            and not all(ref.entity_id in identities for ref in constraint.references)
            for constraint in all_constraints
        )
        saved_tangencies = (
            self.associative_tangencies_provider() if self.associative_tangencies_provider else ()
        )
        omitted_tangencies = any(
            relation.first.entity_id in identities or relation.second.entity_id in identities
            for relation in saved_tangencies
        ) or any(
            draft_tangent_reference(endpoint).entity_id in identities
            for pair in self.pending_cross_tangencies
            for endpoint in pair
        )
        arrays = (
            *(self.associative_arrays_provider() if self.associative_arrays_provider else ()),
            *self.pending_associative_arrays,
        )
        omitted_arrays = any(
            any(ref.entity_id in identities for ref in array.sources)
            or any(member.target.entity_id in identities for member in array.members)
            or any(
                member.replacement is not None and member.replacement.source.entity_id in identities
                for member in array.members
            )
            or any(output.target.entity_id in identities for output in array.extra_outputs)
            or any(output.source.entity_id in identities for output in array.extra_outputs)
            for array in arrays
        )
        omitted = [
            label
            for present, label in (
                (omitted_local, "未选图元的约束"),
                (omitted_tangencies, "对象相切"),
                (omitted_arrays, "阵列关联"),
            )
            if present
        ]
        if omitted:
            self.message += f" 以下关联未复制：{'、'.join(omitted)}。"
        self.changed.emit()
        return True

    def begin_clipboard_paste(self) -> bool:
        """Begin an insertion gesture without modifying the current draft."""
        if (
            not self.select_committed_entities
            or self.has_pending_geometry
            or self.has_active_edit_gesture
        ):
            self.message = "请先完成当前操作，再粘贴二维图元。"
            self.changed.emit()
            return False
        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        try:
            if mime is not None and mime.hasFormat(DRAWING_MIXED_CLIPBOARD_MIME):
                if self.commit_mixed_clipboard is None:
                    raise ValueError("当前图纸无法粘贴图片与图元。")
                sketch, images, styles = decode_mixed_clipboard_data(
                    bytes(mime.data(DRAWING_MIXED_CLIPBOARD_MIME).data())
                )
                names = {entity.layer_name for entity in sketch.entities}
                names.update(item.layer_name for item in images)
                names.update(c.layer_name for c in sketch.constraints if c.layer_name is not None)
                for name in names:
                    try:
                        layer = self.layer_table.get(name)
                    except KeyError:
                        layer = sketch.layers.get(name)
                    if layer.locked or not layer.displayed:
                        raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
                if self.tool != "选择元素" and not self.set_tool("选择元素"):
                    return False
                self._clipboard_anchor = self._entity_handles(sketch.entities[0])[0][1]
                self._clipboard_paste = sketch
                self._clipboard_styles = styles
                self._clipboard_mixed_images = tuple(
                    replace(image, image_id=uuid4().hex) for image in images
                )
                self._clipboard_mixed_revision = (
                    self.source_revision_provider() if self.source_revision_provider else None
                )
                self.selected_raster_ids.clear()
                self.selected_entity_ids.clear()
                self.selected_constraint_ids.clear()
                self.message = "粘贴图片和图元：指定放置点；Esc 取消。"
                self.changed.emit()
                self.update()
                return True
            if mime is not None and mime.hasFormat(DRAWING_RASTER_GROUP_MIME):
                layer = self.layer_table.get(self.active_layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("当前图层隐藏或已锁定。")
                if self.commit_raster_batch is None:
                    raise ValueError("当前图纸暂不能粘贴多张图片。")
                images = decode_raster_group(bytes(mime.data(DRAWING_RASTER_GROUP_MIME).data()))
                if self.tool != "选择元素" and not self.set_tool("选择元素"):
                    return False
                self._clipboard_rasters = tuple(
                    replace(item, image_id=uuid4().hex, layer_name=layer.name) for item in images
                )
                self._clipboard_anchor = images[0].origin_mm
                self.selected_raster_ids.clear()
                self.selected_entity_ids.clear()
                self.selected_constraint_ids.clear()
                self.message = "粘贴图片：指定放置点；Esc 取消。"
                self.changed.emit()
                self.update()
                return True
            if mime is not None and not mime.hasFormat(DRAWING_CLIPBOARD_MIME) and mime.hasImage():
                layer = self.layer_table.get(self.active_layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError("当前图层隐藏或已锁定。")
                if self.commit_clipboard_raster is None:
                    raise ValueError("当前图纸暂不能粘贴图片。")
                size_data = (
                    bytes(mime.data(DRAWING_RASTER_MIME).data())
                    if mime.hasFormat(DRAWING_RASTER_MIME)
                    else None
                )
                raster = raster_from_clipboard_image(
                    QApplication.clipboard().image(), layer.name, size_data
                )
                if self.tool != "选择元素" and not self.set_tool("选择元素"):
                    return False
                self._clipboard_raster = raster
                self.selected_raster_ids.clear()
                self.selected_entity_ids.clear()
                self.selected_constraint_ids.clear()
                self.message = (
                    "粘贴图片：指定左下角；Esc 取消。"
                    if size_data is not None
                    else "粘贴图片：指定左下角，默认宽度 100 mm；Esc 取消。"
                )
                self.changed.emit()
                self.update()
                return True
            if mime is None or not mime.hasFormat(DRAWING_CLIPBOARD_MIME):
                raise ValueError("剪贴板中没有可粘贴的二维图元或图片。")
            sketch, styles = decode_drawing_clipboard_data(
                bytes(mime.data(DRAWING_CLIPBOARD_MIME).data())
            )
            names = {entity.layer_name for entity in sketch.entities}
            names.update(c.layer_name for c in sketch.constraints if c.layer_name is not None)
            for name in names:
                try:
                    layer = self.layer_table.get(name)
                except KeyError:
                    layer = sketch.layers.get(name)
                if layer.locked or not layer.displayed:
                    raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        if self.tool != "选择元素" and not self.set_tool("选择元素"):
            return False
        self._clipboard_anchor = self._entity_handles(sketch.entities[0])[0][1]
        self._clipboard_paste = sketch
        self._clipboard_styles = styles
        self.selected_raster_ids.clear()
        self.selected_entity_ids.clear()
        self.selected_constraint_ids.clear()
        self.message = "粘贴：指定放置点，Esc 取消。"
        self.changed.emit()
        self.update()
        return True

    @property
    def clipboard_paste_active(self) -> bool:
        return (
            self._clipboard_paste is not None
            or self._clipboard_raster is not None
            or bool(self._clipboard_rasters)
        )

    def _place_clipboard(self, point: Point2D) -> bool:
        if self._clipboard_mixed_images and self._clipboard_paste is not None:
            sketch, images = self._clipboard_paste, self._clipboard_mixed_images
            delta = (point[0] - self._clipboard_anchor[0], point[1] - self._clipboard_anchor[1])
            try:
                if (
                    self._clipboard_mixed_revision is not None
                    and self.source_revision_provider is not None
                    and self.source_revision_provider() != self._clipboard_mixed_revision
                ):
                    raise ValueError("图纸已变化，请取消后重新粘贴。")
                source_sketch = sketch
                styles = self.drawing_dimension_styles
                if self._clipboard_styles is not None:
                    if styles is None:
                        raise ValueError("当前图纸无法导入标注样式。")
                    styles, source_sketch = reconcile_clipboard_styles(
                        sketch, self._clipboard_styles, styles
                    )
                else:
                    styles = None
                entities, constraints = instantiate_drawing_clipboard(
                    source_sketch, delta, styles=styles
                )
                layers = self.layer_table
                names = {entity.layer_name for entity in entities}
                names.update(image.layer_name for image in images)
                names.update(c.layer_name for c in constraints if c.layer_name is not None)
                for name in names:
                    try:
                        layer = layers.get(name)
                    except KeyError:
                        layer = sketch.layers.get(name)
                        layers = layers.add(layer)
                    if layer.locked or not layer.displayed:
                        raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
                placed = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, constraints, layers)
                moved_images = tuple(
                    replace(
                        image,
                        origin_mm=(image.origin_mm[0] + delta[0], image.origin_mm[1] + delta[1]),
                    )
                    for image in images
                )
                if self.commit_mixed_clipboard is None:
                    raise ValueError("当前图纸无法粘贴图片与图元。")
                self.commit_mixed_clipboard(placed, moved_images, styles)
            except ValueError as exc:
                self.message = f"粘贴失败：{exc}"
                self.changed.emit()
                return False
            self._clipboard_paste = None
            self._clipboard_styles = None
            self._clipboard_mixed_images = ()
            self._clipboard_mixed_revision = None
            self.selected_entity_ids = {entity.entity_id for entity in entities}
            self.selected_raster_ids = {image.image_id for image in moved_images}
            detached = any(
                original.style_name is not None and copied.style_name is None
                for original, copied in zip(sketch.constraints, constraints, strict=True)
            )
            self.message = f"已粘贴 {len(entities)} 个图元和 {len(images)} 张图片；可撤销。"
            if detached:
                self.message += "剪贴板缺少完整样式，相关尺寸已解除样式关联。"
            self.changed.emit()
            self.point_accepted.emit(point)
            self.update()
            return True
        if self._clipboard_rasters:
            images = self._clipboard_rasters
            try:
                dx, dy = point[0] - self._clipboard_anchor[0], point[1] - self._clipboard_anchor[1]
                placed = tuple(
                    replace(item, origin_mm=(item.origin_mm[0] + dx, item.origin_mm[1] + dy))
                    for item in images
                )
                if self.commit_raster_batch is None:
                    raise ValueError("当前图纸暂不能粘贴多张图片。")
                self._clipboard_rasters = ()
                self.commit_raster_batch("add", placed)
            except ValueError as exc:
                self._clipboard_rasters = images
                self.message = str(exc)
                self.changed.emit()
                return False
            self.selected_raster_ids = {item.image_id for item in placed}
            self.message = f"已粘贴 {len(placed)} 张图片；可撤销。"
            self.changed.emit()
            self.point_accepted.emit(point)
            self.update()
            return True
        raster = self._clipboard_raster
        if raster is not None:
            try:
                placed = replace(raster, origin_mm=point)
                if self.commit_clipboard_raster is None:
                    raise ValueError("当前图纸暂不能粘贴图片。")
                self._clipboard_raster = None
                self.commit_clipboard_raster(placed)
            except ValueError as exc:
                self._clipboard_raster = raster
                self.message = str(exc)
                self.changed.emit()
                return False
            self.selected_raster_id = placed.image_id
            self.message = "图片已粘贴并选中；可删除或变换。"
            self.changed.emit()
            self.point_accepted.emit(point)
            self.update()
            return True
        sketch = self._clipboard_paste
        if sketch is None:
            return False
        delta = (point[0] - self._clipboard_anchor[0], point[1] - self._clipboard_anchor[1])
        finish_layer_import: Callable[[bool], None] | None = None
        try:
            source_sketch = sketch
            styles = self.drawing_dimension_styles
            if self._clipboard_styles is not None:
                if styles is None:
                    raise ValueError("当前图纸无法导入标注样式。")
                styles, source_sketch = reconcile_clipboard_styles(
                    sketch, self._clipboard_styles, styles
                )
            else:
                styles = None
            entities, constraints = instantiate_drawing_clipboard(
                source_sketch, delta, styles=styles
            )
            layers = self.layer_table
            names = {entity.layer_name for entity in entities}
            names.update(c.layer_name for c in constraints if c.layer_name is not None)
            for name in names:
                try:
                    layer = layers.get(name)
                except KeyError:
                    layer = sketch.layers.get(name)
                    layers = layers.add(layer)
                if layer.locked or not layer.displayed:
                    raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
            if self.preserve_document_layers and (
                layers != self.layer_table
                or (styles is not None and styles != self.drawing_dimension_styles)
            ):
                if self.import_clipboard_layers is None:
                    raise ValueError("当前图纸无法导入剪贴板图层。")
                finish_layer_import = self.import_clipboard_layers(layers, styles)
        except ValueError as exc:
            self.message = f"粘贴位置无效：{exc}"
            self.changed.emit()
            return False
        self._clipboard_paste = None
        self.message = "正在粘贴二维图元。"
        try:
            placed = self.replace_draft_entities(
                (*self.entities, *entities),
                select_new=True,
                new_relations=constraints,
                new_layer_table=layers,
            )
        except Exception:
            if finish_layer_import is not None:
                finish_layer_import(False)
            self._clipboard_paste = sketch
            raise
        if not placed:
            if finish_layer_import is not None:
                finish_layer_import(False)
            self._clipboard_paste = sketch
            if self.message == "正在粘贴二维图元。":
                self.message = "粘贴未完成；可重新指定放置点或按 Esc 取消。"
                self.changed.emit()
            return False
        if finish_layer_import is not None:
            finish_layer_import(True)
        self._clipboard_styles = None
        if self.message == "正在粘贴二维图元。":
            self.message = f"已粘贴 {len(entities)} 个二维图元；可撤销。"
            if any(
                original.style_name is not None and copied.style_name is None
                for original, copied in zip(sketch.constraints, constraints, strict=True)
            ):
                self.message += "剪贴板缺少完整样式，相关尺寸已解除样式关联。"
            self.changed.emit()
        self.point_accepted.emit(point)
        return True

    def copy_selected_to_draft(self, delta: Point2D) -> tuple[SketchEntity, ...]:
        """Copy selected draft and visible committed geometry into the draft."""
        background = tuple(
            entity
            for entity, _layer in self.background_entities
            if entity.entity_id in self.selected_entity_ids
        )
        original_background_ids = {entity.entity_id for entity in background}
        source = (*self.entities, *background)
        selected = tuple(
            entity.entity_id for entity in source if entity.entity_id in self.selected_entity_ids
        )
        return tuple(
            entity
            for entity in copy_entities(source, selected, delta)
            if entity.entity_id not in original_background_ids
        )

    def rotation_draft_error(self, center: Point2D, angle: float) -> str:
        """Check the selected draft geometry before dispatching a mixed rotation."""
        selected = tuple(
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        )
        if not selected:
            return ""
        try:
            candidate = rotate_entities(tuple(self.entities), selected, center, angle)
            self._reject_user_constraint_reference_edits(candidate)
        except ValueError as exc:
            return str(exc)
        return ""

    def mirror_draft_error(self, start: Point2D, end: Point2D) -> str:
        """Check selected draft geometry before dispatching a mixed mirror."""
        selected = tuple(
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        )
        if not selected:
            return ""
        try:
            candidate = mirror_entities(tuple(self.entities), selected, start, end)
            self._reject_user_constraint_reference_edits(candidate)
        except ValueError as exc:
            return str(exc)
        return ""

    def mirror_selected_to_draft(self, start: Point2D, end: Point2D) -> tuple[SketchEntity, ...]:
        """Mirror new copies of selected draft and committed entities into the draft."""
        original_ids = {entity.entity_id for entity in self.entities}
        copied = self.copy_selected_to_draft((0.0, 0.0))
        copies = tuple(
            entity.entity_id for entity in copied if entity.entity_id not in original_ids
        )
        return mirror_entities(copied, copies, start, end)

    def _finish_transform_selection(self) -> None:
        if self._selection_anchor is not None:
            self._finish_selection_box(self._selection_corner)
        if self._transform_selecting and (
            self.selected_entity_ids
            or self.selected_raster_id
            or (self._transform_operation == "erase" and self.selected_constraint_ids)
        ):
            if (
                self.selected_raster_ids
                and any(entity.entity_id in self.selected_entity_ids for entity in self.entities)
                and (
                    self._transform_operation
                    not in {"move", "scale", "rotate", "mirror", "erase", "copy"}
                    or (
                        self._selected_committed_entities()
                        and self._transform_operation
                        not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
                    )
                )
            ):
                self.message = "暂不能同时变换图片、草稿和已提交图元，请分开操作。"
                self.changed.emit()
                return
            if self._transform_operation == "erase":
                self.cancel_transform()
                self.delete_selected()
                return
            error = self.transform_selection_error(self._transform_operation or "move")
            if error:
                self.message = error
                self.changed.emit()
                return
            self._transform_selecting = False
            self.message = self._transform_point_hint()
            self.changed.emit()

    def _transform_point_hint(self) -> str:
        if self._transform_operation == "scale":
            if self._transform_base is not None and self._scale_reference_active:
                if self._scale_reference_length is None:
                    return (
                        "参考缩放：指定参考长度第二点；Esc 取消。"
                        if self._scale_reference_first is not None
                        else "参考缩放：输入原参考长度或指定第一点；Esc 取消。"
                    )
                if self._scale_target_points_active:
                    return (
                        "参考缩放：指定目标长度第二点；Esc 取消。"
                        if self._scale_target_first is not None
                        else "参考缩放：指定目标长度第一点；Esc 取消。"
                    )
                return "参考缩放：输入目标长度或指定目标点；P 两点定距，Esc 取消。"
            return (
                "缩放：指定基点；Esc 取消。"
                if self._transform_base is None
                else f"缩放：输入比例或指定比例点 <{self.scale_default_factor:g}>，"
                "C 复制，R 参考；Esc 取消。"
            )
        if self._transform_operation == "rotate":
            if self._transform_base is None:
                return "旋转：指定旋转中心；Esc 取消。"
            if (
                self._transform_reference_mode
                and self._reference_previous_mode is not None
                and self._transform_reference is not None
                and self._transform_reference_angle is None
            ):
                return "参考旋转：指定第二参考点，或输入目标角。"
            if self._transform_reference_mode and self.rotation_reference_angle is None:
                hint = "参考旋转：输入参考角或指定起始参考点。"
                return hint if self._reference_previous_mode is None else hint + "Enter 使用 0°。"
            if self._transform_reference_mode and self._rotation_target_points_active:
                return (
                    "参考旋转：指定目标方向的第二点；Esc 取消。"
                    if self._rotation_target_first is not None
                    else "参考旋转：指定目标方向的第一点；Esc 取消。"
                )
            if self._transform_reference_mode:
                hint = "参考旋转：输入目标绝对角、指定目标方向或 P 两点定向。"
                return hint if self._reference_previous_mode is None else hint + "Enter 使用 0°。"
            return (
                f"旋转：指定目标方向或输入角度 <{self.rotation_default_angle:g}°>；"
                "R 参考，C 复制，Esc 取消。"
            )
        if self._transform_operation == "mirror":
            return (
                "镜像：指定镜像轴第一点；Esc 取消。"
                if self._transform_base is None
                else "镜像：指定镜像轴第二点；两点定义无限长镜像轴，Esc 取消。"
            )
        return (
            "指定移动/复制基点；Esc 取消。"
            if self._transform_base is None
            else "指定目标点，或按 Enter 使用基点作为位移；Esc 取消。"
        )

    def _transform_copies_source(self) -> bool:
        return (
            self._transform_operation in {"copy", "offset", "rectangular_array_preview"}
            or (self._transform_operation == "mirror" and self._transform_keep_source)
            or (self._transform_operation == "rotate" and self._rotation_copy)
            or (self._transform_operation == "scale" and self._scale_copy)
        )

    def _transform_pointer_point(
        self, raw: Point2D, *, disable_snapping: bool
    ) -> tuple[Point2D, str]:
        point, kind = (
            (raw, "")
            if self._transform_operation == "offset"
            or self._transform_selecting
            or disable_snapping
            else self._snapped(raw)
        )
        base = self._transform_base
        if (
            self._transform_operation in {"move", "copy"}
            and base is not None
            and not self._transform_selecting
            and self._polar_tracking_enabled
            and not disable_snapping
            and not kind
        ):
            tracked = self._polar_tracking_point(base, point)
            if tracked is not None:
                return tracked
        if (
            self._transform_operation in {"move", "copy"}
            and base is not None
            and not self._transform_selecting
            and self._orthogonal_enabled
            and kind in {"", "栅格"}
        ):
            if abs(point[0] - base[0]) >= abs(point[1] - base[1]):
                point = (point[0], base[1])
            else:
                point = (base[0], point[1])
            kind = "正交"
        return point, kind

    def _transform_candidate(
        self, point: Point2D, *, angle_deg: float | None = None, scale_factor: float | None = None
    ) -> tuple[SketchEntity, ...]:
        base = self._transform_base
        if base is None:
            return ()
        transform_entities = (
            (*self.entities, *(entity for entity, _layer in self.background_entities))
            if self._selected_committed_entities()
            else tuple(self.entities)
        )
        selected = tuple(
            entity.entity_id
            for entity in transform_entities
            if entity.entity_id in self.selected_entity_ids
        )
        error = self.transform_selection_error(self._transform_operation or "move")
        if error:
            raise ValueError(error)
        delta = (point[0] - base[0], point[1] - base[1])
        if angle_deg is None and scale_factor is None and math.hypot(*delta) <= 1e-9:
            raise ValueError("两点重合；请指定不同的方向点。")
        if self._transform_operation == "copy" and self._copy_array_count is not None:
            sources = tuple(
                entity
                for entity in self.selectable_entities()
                if entity.entity_id in self._copy_array_ids
            )
            if (
                self.history_position != self._copy_array_history
                or frozenset(self.selected_entity_ids) != self._copy_array_ids
                or sources != self._copy_array_sources
            ):
                raise ValueError("复制阵列来源已变化；请取消后重新开始。")
            error = self.transform_selection_error("linear_array")
            if error:
                raise ValueError(error)
            if self._copy_array_preview_point == point and self._copy_array_candidate:
                return self._copy_array_candidate
            background = (
                tuple(entity for entity, _layer in self.background_entities)
                if self.select_committed_entities
                else ()
            )
            source = (*self.entities, *background)
            selected_ids = tuple(
                entity.entity_id for entity in source if entity.entity_id in self._copy_array_ids
            )
            step = (
                tuple(value / (self._copy_array_count - 1) for value in delta)
                if self._copy_array_fit
                else delta
            )
            generated = linear_array_entities(
                source, selected_ids, count=self._copy_array_count, step_mm=cast("Point2D", step)
            )
            self._copy_array_preview_point = point
            self._copy_array_candidate = (*self.entities, *generated[len(source) :])
            return self._copy_array_candidate
        if self._transform_operation == "copy":
            candidate = self.copy_selected_to_draft(delta)
            self._reject_user_constraint_reference_edits(candidate)
            return candidate
        if self._transform_operation == "mirror" and self._transform_keep_source:
            candidate = self.mirror_selected_to_draft(base, point)
            self._reject_user_constraint_reference_edits(candidate)
            return candidate
        entities = transform_entities
        if self._transform_operation == "scale":
            pending_refs_selected = False
            if not self._scale_copy and self.pending_associative_arrays:
                array_refs: set[str] = set()
                for array in self.pending_associative_arrays:
                    array_refs.update(ref.entity_id for ref in array.sources)
                    for member in array.members:
                        array_refs.add(member.target.entity_id)
                        if member.replacement is not None:
                            array_refs.add(member.replacement.source.entity_id)
                    for output in array.extra_outputs:
                        array_refs.update(
                            (
                                output.source.entity_id,
                                output.target.entity_id,
                                output.anchor_source.entity_id,
                            )
                        )
                pending_refs_selected = bool(array_refs.intersection(selected))
            factor = scale_factor if scale_factor is not None else math.hypot(*delta)
            if self._scale_copy and self._selected_committed_entities():
                source_ids = {entity.entity_id for entity in self.entities}
                copies = self.copy_selected_to_draft((0, 0))
                copied_ids = tuple(
                    entity.entity_id for entity in copies if entity.entity_id not in source_ids
                )
                candidate = scale_entities(copies, copied_ids, base, factor)
            else:
                operation = copy_scaled_entities if self._scale_copy else scale_entities
                candidate = operation(entities, selected, base, factor)
            if pending_refs_selected:
                if self.draft_sketches_provider is None:
                    raise ValueError("无法验证关联阵列，请先完成草图。")
                before = self.draft_sketches_provider()
                draft_ids = {entity.entity_id for entity in before[0].entities}
                draft_candidate = tuple(
                    entity for entity in candidate if entity.entity_id in draft_ids
                )
                saved_candidates: list[Sketch] = []
                for sketch in before[1:]:
                    ids = tuple(
                        entity.entity_id
                        for entity in sketch.entities
                        if entity.entity_id in selected
                    )
                    center = sketch.frame.world_to_local(before[0].frame.local_to_world(base))
                    changed = (
                        scale_entities(sketch.entities, ids, center, factor)
                        if ids
                        else sketch.entities
                    )
                    saved_candidates.append(replace(sketch, entities=changed))
                proposed = (replace(before[0], entities=draft_candidate), *saved_candidates)
                propagated = propagate_array_changes(
                    before, proposed, tuple(self.pending_associative_arrays)
                )
                if propagated[1:] != proposed[1:]:
                    raise ValueError("请先完成草图，再修改关联的已保存对象。")
                candidate = (
                    *propagated[0].entities,
                    *(entity for entity in candidate if entity.entity_id not in draft_ids),
                )
        elif self._transform_operation == "rotate":
            if angle_deg is None:
                angle_deg = math.degrees(math.atan2(delta[1], delta[0]))
                reference_angle = self.rotation_reference_angle
                if reference_angle is not None:
                    angle_deg -= reference_angle
            if self._rotation_copy:
                source_ids = {entity.entity_id for entity in self.entities}
                copies = self.copy_selected_to_draft((0.0, 0.0))
                copied_ids = tuple(
                    entity.entity_id for entity in copies if entity.entity_id not in source_ids
                )
                candidate = rotate_entities(copies, copied_ids, base, angle_deg)
            else:
                candidate = rotate_entities(entities, selected, base, angle_deg)
        elif self._transform_operation == "mirror":
            if self._transform_keep_source:
                source_ids = {entity.entity_id for entity in entities}
                entities = copy_entities(entities, selected, (0.0, 0.0))
                selected = tuple(
                    entity.entity_id for entity in entities if entity.entity_id not in source_ids
                )
            candidate = mirror_entities(entities, selected, base, point)
        else:
            candidate = (
                copy_entities(entities, selected, delta)
                if self._transform_operation == "copy"
                else move_entities(entities, selected, delta, preserve_rectangle_order=True)
            )
        self._reject_user_constraint_reference_edits(
            candidate,
            allow_satisfied_tangency=self.selected_user_tangencies_transformable(),
        )
        return candidate

    @property
    def scale_center(self) -> Point2D | None:
        return self._transform_base if self._transform_operation == "scale" else None

    def enable_scale_copy(self) -> bool:
        if self.scale_center is None:
            return False
        self._scale_copy = True
        self.message = "缩放复制：请输入比例或指定比例点。"
        self.changed.emit()
        return True

    def start_scale_reference(self) -> bool:
        if self.scale_center is None:
            return False
        self._scale_reference_active = True
        self._raster_transform_preview = None
        self._raster_transform_previews = ()
        self._scale_reference_length = None
        self._scale_reference_first = None
        self._scale_target_points_active = False
        self._scale_target_first = None
        self.message = "参考缩放：输入原参考长度或指定第一点。"
        self.changed.emit()
        self.update()
        return True

    @property
    def scale_reference_active(self) -> bool:
        return self.scale_center is not None and self._scale_reference_active

    @property
    def scale_target_points_active(self) -> bool:
        return self.scale_reference_active and self._scale_target_points_active

    def start_scale_target_points(self) -> bool:
        if not self.scale_reference_active or self._scale_reference_length is None:
            self.message = "请先指定参考长度。"
            self.changed.emit()
            return False
        self._scale_target_points_active = True
        self._raster_transform_preview = None
        self._raster_transform_previews = ()
        self._scale_target_first = None
        self.message = "参考缩放：指定目标长度的第一点。"
        self.changed.emit()
        self.update()
        return True

    def apply_scale_length(self, length: float) -> bool:
        if not self.scale_reference_active or not math.isfinite(length) or length <= 0:
            return False
        if self._scale_reference_length is None:
            self._scale_reference_length = length
            self._scale_reference_first = None
            self.message = "参考缩放：输入目标长度。"
            self.changed.emit()
            return True
        return self.apply_scale_factor(length / self._scale_reference_length)

    def apply_scale_factor(self, factor: float) -> bool:
        if not self._transform_revision_current() or self.scale_center is None:
            return False
        if self.selected_raster_id is not None and not self.selected_entity_ids:
            return self._apply_raster_transform(self.scale_center, factor=factor)
        try:
            candidate = self._transform_candidate(self.scale_center, scale_factor=factor)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        if not self.scale_reference_active:
            self.scale_default_factor = factor
        if self.selected_raster_ids and not self._selected_committed_entities():
            return self._commit_mixed_draft_affine(candidate, self.scale_center, scale=factor)
        if self._selected_committed_entities() and (
            not self._scale_copy or self.selected_raster_ids
        ):
            center = self.scale_center
            assert center is not None
            selected = tuple(self.selected_entity_ids)
            copy_source = self._scale_copy
            self.cancel_transform()
            if copy_source:
                self.committed_scale_copy_requested.emit(selected, center, factor)
            else:
                self.committed_scale_requested.emit(selected, center, factor)
        else:
            self._show_transform_candidate(candidate, commit=True)
        return True

    def scale_selection_about(self, center: Point2D, factor: float) -> bool:
        """Apply a property-driven scale without changing the SCALE command default."""
        self.begin_transform("scale")
        if self._transform_operation != "scale" or self._transform_selecting:
            return False
        self._transform_base = center
        previous_default = self.scale_default_factor
        try:
            applied = self.apply_scale_factor(factor)
        finally:
            self.scale_default_factor = previous_default
        if not applied:
            error = self.message
            self.cancel_transform()
            self.message = error
            self.changed.emit()
        return applied

    @property
    def rotation_center(self) -> Point2D | None:
        return self._transform_base if self._transform_operation == "rotate" else None

    @property
    def rotation_uses_reference(self) -> bool:
        return self._transform_operation == "rotate" and self._transform_reference_mode

    @property
    def rotation_reference_angle(self) -> float | None:
        if not self.rotation_uses_reference:
            return None
        if self._transform_reference_angle is not None:
            return self._transform_reference_angle
        reference, base = self._transform_reference, self._transform_base
        if reference is None or base is None or _distance(reference, base) <= 1e-9:
            return None
        return math.degrees(math.atan2(reference[1] - base[1], reference[0] - base[0]))

    def start_rotation_reference(self) -> bool:
        if not self._transform_revision_current():
            return False
        if self._transform_operation != "rotate" or self._transform_base is None:
            return False
        if self._reference_previous_mode is None:
            self._reference_previous_mode = self._transform_reference_mode
        self.configure_active_transform(reference_rotation=True, keep_source=True)
        self._transform_reference = None
        self._transform_reference_end = None
        self._transform_reference_angle = None
        self._rotation_target_points_active = False
        self._rotation_target_first = None
        self._transform_preview = ()
        self._raster_transform_preview = None
        self._raster_transform_previews = ()
        self.message = self._transform_point_hint()
        self.rotation_reference_mode_changed.emit(True)
        self.changed.emit()
        self.update()
        return True

    def enable_rotation_copy(self) -> bool:
        """Keep the selected source geometry when this rotation is committed."""
        if self.rotation_center is None or not self._transform_revision_current():
            return False
        self._rotation_copy = True
        self._transform_preview = ()
        self.message = (
            f"旋转副本：指定目标方向或输入角度 <{self.rotation_default_angle:g}°>；"
            "R 参考，Esc 取消。"
        )
        self.changed.emit()
        self.update()
        return True

    def set_rotation_reference_angle(self, angle_deg: float) -> None:
        if not self._transform_revision_current() or not self.rotation_uses_reference:
            raise ValueError("参考旋转已失效。")
        if not math.isfinite(angle_deg):
            raise ValueError("参考角必须是有限数值。")
        self._transform_reference = None
        self._transform_reference_end = None
        self._transform_reference_angle = angle_deg
        self._transform_preview = ()
        self.message = self._transform_point_hint()
        self.changed.emit()
        self.update()

    @property
    def rotation_target_points_active(self) -> bool:
        return self._rotation_target_points_active

    def start_rotation_target_points(self) -> bool:
        """Select two arbitrary points defining the absolute target angle."""
        if not self._transform_revision_current():
            return False
        if (
            self.rotation_center is None
            or self.rotation_reference_angle is None
            or (
                self._reference_previous_mode is not None
                and self._transform_reference_angle is None
            )
        ):
            self.message = "请先确定参考角，再选择目标方向的两点。"
            self.changed.emit()
            return False
        self._rotation_target_points_active = True
        self._raster_transform_preview = None
        self._raster_transform_previews = ()
        self._rotation_target_first = None
        self._transform_angle_text = ""
        self._transform_preview = ()
        self.message = self._transform_point_hint()
        self.changed.emit()
        self.update()
        return True

    def apply_rotation_target_angle(self, target_deg: float) -> bool:
        reference = self.rotation_reference_angle
        if reference is None or not math.isfinite(target_deg - reference):
            self.message = "请输入有效的参考角和目标角。"
            self.changed.emit()
            return False
        return self.apply_rotation_angle(target_deg - reference)

    def apply_rotation_angle(self, angle_deg: float) -> bool:
        """Apply an explicit relative angle about the currently picked center."""
        if not self._transform_revision_current():
            return False
        if self._transform_operation != "rotate" or self._transform_base is None:
            return False
        if self.selected_raster_id is not None and not self.selected_entity_ids:
            return self._apply_raster_transform(self._transform_base, angle=angle_deg)
        try:
            candidate = self._transform_candidate(self._transform_base, angle_deg=angle_deg)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        if not self.rotation_uses_reference:
            self.rotation_default_angle = angle_deg
        if self.selected_raster_ids and not self._selected_committed_entities():
            return self._commit_mixed_draft_affine(candidate, self._transform_base, angle=angle_deg)
        if self._selected_committed_entities() and (
            not self._rotation_copy or self.selected_raster_ids
        ):
            self._commit_saved_rotation(angle_deg)
        else:
            self._show_transform_candidate(candidate, commit=True)
        return True

    def _commit_mixed_draft_affine(
        self,
        candidate: tuple[SketchEntity, ...],
        center: Point2D,
        *,
        scale: float | None = None,
        angle: float | None = None,
    ) -> bool:
        images: list[DrawingRaster] = []
        copy_source = (scale is not None and self._scale_copy) or (
            angle is not None and self._rotation_copy
        )
        omission_notice = self.draft_copy_omission_notice() if copy_source else ""
        for image in self.drawing_rasters:
            if image.image_id not in self.selected_raster_ids:
                continue
            x, y = image.origin_mm[0] - center[0], image.origin_mm[1] - center[1]
            if scale is not None:
                images.append(
                    replace(
                        image,
                        image_id=uuid4().hex if copy_source else image.image_id,
                        origin_mm=(center[0] + x * scale, center[1] + y * scale),
                        width_mm=image.width_mm * scale,
                        height_mm=image.height_mm * scale,
                    )
                )
            elif angle is not None:
                c, sn = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                images.append(
                    replace(
                        image,
                        image_id=uuid4().hex if copy_source else image.image_id,
                        origin_mm=(center[0] + c * x - sn * y, center[1] + sn * x + c * y),
                        angle_deg=image.angle_deg + angle,
                    )
                )
        if (
            len(images) != len(self.selected_raster_ids)
            or self.commit_mixed_draft_transform is None
        ):
            self.message = "所选图片已变化或无法编辑，请重新选择。"
            self.changed.emit()
            return False
        if not self.commit_mixed_draft_transform(
            candidate, tuple(images), "add" if copy_source else "update"
        ):
            return False
        self.cancel_transform()
        self.message = "已变换图片和图元；可撤销。"
        self.message += omission_notice
        self.changed.emit()
        return True

    def _commit_saved_rotation(self, angle_deg: float) -> None:
        center = self._transform_base
        assert center is not None
        selected = tuple(self.selected_entity_ids)
        copy_source = self._rotation_copy and bool(self.selected_raster_ids)
        self.cancel_transform()
        if copy_source:
            self.committed_rotation_copy_requested.emit(selected, center, angle_deg)
        else:
            self.committed_rotation_requested.emit(selected, center, angle_deg)

    def _commit_mixed_draft_mirror(
        self,
        candidate: tuple[SketchEntity, ...],
        start: Point2D,
        end: Point2D,
        *,
        keep_source: bool,
    ) -> bool:
        omission_notice = self.draft_copy_omission_notice() if keep_source else ""
        axis = math.atan2(end[1] - start[1], end[0] - start[0])
        c, sn = math.cos(2 * axis), math.sin(2 * axis)
        images: list[DrawingRaster] = []
        for image in self.drawing_rasters:
            if image.image_id not in self.selected_raster_ids:
                continue
            x, y = image.origin_mm[0] - start[0], image.origin_mm[1] - start[1]
            images.append(
                replace(
                    image,
                    image_id=uuid4().hex if keep_source else image.image_id,
                    origin_mm=(start[0] + c * x + sn * y, start[1] + sn * x - c * y),
                    angle_deg=math.degrees(2 * axis) - image.angle_deg,
                    mirrored=not image.mirrored,
                )
            )
        if (
            len(images) != len(self.selected_raster_ids)
            or self.commit_mixed_draft_transform is None
        ):
            self.message = "所选图片已变化或无法编辑，请重新选择。"
            self.changed.emit()
            return False
        if not self.commit_mixed_draft_transform(
            candidate, tuple(images), "add" if keep_source else "update"
        ):
            return False
        self.cancel_transform()
        self.message = "已镜像图片和图元；可撤销。"
        self.message += omission_notice
        self.changed.emit()
        self.update()
        return True

    def _show_transform_candidate(
        self, candidate: tuple[SketchEntity, ...], *, commit: bool, point: Point2D | None = None
    ) -> None:
        selected = self.selected_entity_ids
        source_ids = {entity.entity_id for entity in self.entities}
        is_copy = self._transform_copies_source()
        original = {entity.entity_id: entity for entity in self.entities}
        self._transform_preview = tuple(
            entity
            for entity in candidate
            if (
                entity.entity_id not in source_ids
                if is_copy
                else entity.entity_id in selected
                or (
                    self._transform_operation == "scale"
                    and entity.entity_id in original
                    and original[entity.entity_id] != entity
                )
            )
        )
        if commit:
            if (
                self._transform_operation == "copy"
                and self.select_committed_entities
                and self._copy_repeat
            ):
                original_selection = set(selected)
                previous_position = self.history_position
                if self.replace_draft_entities(candidate):
                    assert point is not None
                    self._copy_placements.append((point, previous_position, self.history_position))
                    self.selected_entity_ids = original_selection
                    self._transform_preview = ()
                    self.message = "已复制；指定下一个目标点，U 撤销，Enter / 右键结束。"
                self.changed.emit()
                self.update()
                return
            label = {
                "move": "移动",
                "copy": "复制",
                "rotate": "旋转",
                "mirror": "镜像",
                "scale": "缩放",
            }[self._transform_operation or "move"]
            preserve_tangency = self.selected_user_tangencies_transformable()
            self.cancel_transform()
            self.message = f"已{label}所选图元；可撤销。"
            if (
                self.replace_draft_entities(
                    candidate, select_new=is_copy, allow_satisfied_tangency=preserve_tangency
                )
                and is_copy
            ):
                self.selected_entity_ids = {
                    entity.entity_id for entity in candidate if entity.entity_id not in source_ids
                }
            self.changed.emit()
        else:
            self.message = self._transform_point_hint()
            self.changed.emit()
        self.update()

    @property
    def awaiting_mirror_erase(self) -> bool:
        return self._transform_operation == "mirror" and self._mirror_axis_end is not None

    def confirm_mirror_erase(self, erase: bool) -> bool:
        """Complete a pending mirror only while its selection is still current."""
        if not self.awaiting_mirror_erase or not self._transform_revision_current():
            return False
        point = self._mirror_axis_end
        assert point is not None
        if self.selected_raster_id is not None and not self.selected_entity_ids:
            return self._apply_raster_transform(point, keep_source=not erase)
        selected = self.selected_entity_ids
        sources = tuple(
            entity for entity in self.selectable_entities() if entity.entity_id in selected
        )
        if (
            self.history_position != self._mirror_history_position
            or frozenset(selected) != self._mirror_selected_ids
            or sources != self._mirror_selected_sources
        ):
            self.cancel_transform()
            self.message = "镜像对象已变化；请重新开始。"
            self.changed.emit()
            return False
        error = self.transform_selection_error("mirror")
        if error:
            self._transform_preview = ()
            self.message = error
            self.changed.emit()
            self.update()
            return False
        self._transform_keep_source = not erase
        try:
            candidate = self._transform_candidate(point) if erase else self._mirror_candidate
        except ValueError as exc:
            self._transform_preview = ()
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return False
        if erase and self._selected_committed_entities():
            start = self._transform_base
            assert start is not None
            identities = tuple(selected)
            self.cancel_transform()
            self.committed_mirror_requested.emit(identities, start, point)
            return True
        if not erase and self.selected_raster_ids and self._selected_committed_entities():
            start = self._transform_base
            assert start is not None
            identities = tuple(selected)
            self.cancel_transform()
            self.committed_mirror_copy_requested.emit(identities, start, point)
            return True
        if self.selected_raster_ids and not self._selected_committed_entities():
            start = self._transform_base
            assert start is not None
            return self._commit_mixed_draft_mirror(candidate, start, point, keep_source=not erase)
        self._show_transform_candidate(candidate, commit=True, point=point)
        return True

    def apply_numeric_raster_transform(
        self,
        operation: str,
        center: Point2D,
        point: Point2D,
        *,
        angle: float,
        keep_source: bool,
    ) -> bool:
        self.begin_transform(operation)
        if self.active_transform != operation:
            return False
        self._transform_base = center
        if operation == "rotate":
            return self.apply_rotation_angle(angle)
        return self._apply_raster_transform(point, keep_source=keep_source)

    def _apply_raster_transform(
        self,
        point: Point2D,
        *,
        factor: float | None = None,
        angle: float | None = None,
        keep_source: bool = False,
        preview: bool = False,
    ) -> bool:
        sources = tuple(
            item for item in self.drawing_rasters if item.image_id in self.selected_raster_ids
        )
        base, operation = self._transform_base, self._transform_operation
        if not sources or len(sources) != len(self.selected_raster_ids) or base is None:
            return False
        if self.selected_entity_ids or self.selected_constraint_ids:
            self.message = "暂不能同时变换图片和其他对象，请分别选择。"
            self.changed.emit()
            return False
        try:
            results: list[DrawingRaster] = []
            for raster in sources:
                x, y = raster.origin_mm[0] - base[0], raster.origin_mm[1] - base[1]
                if operation == "scale":
                    scale = factor if factor is not None else math.dist(base, point)
                    if not math.isfinite(scale) or scale <= 0:
                        raise ValueError("缩放比例必须为正数。")
                    result = replace(
                        raster,
                        origin_mm=(base[0] + x * scale, base[1] + y * scale),
                        width_mm=raster.width_mm * scale,
                        height_mm=raster.height_mm * scale,
                    )
                elif operation == "rotate":
                    rotation = (
                        angle
                        if angle is not None
                        else math.degrees(math.atan2(point[1] - base[1], point[0] - base[0]))
                    )
                    rad = math.radians(rotation)
                    c, sn = math.cos(rad), math.sin(rad)
                    result = replace(
                        raster,
                        origin_mm=(base[0] + c * x - sn * y, base[1] + sn * x + c * y),
                        angle_deg=raster.angle_deg + rotation,
                    )
                elif operation == "mirror":
                    dx, dy = point[0] - base[0], point[1] - base[1]
                    if math.hypot(dx, dy) <= 1e-9:
                        raise ValueError("镜像轴两点不能重合。")
                    axis = math.atan2(dy, dx)
                    c, sn = math.cos(2 * axis), math.sin(2 * axis)
                    result = replace(
                        raster,
                        origin_mm=(base[0] + c * x + sn * y, base[1] + sn * x - c * y),
                        angle_deg=math.degrees(2 * axis) - raster.angle_deg,
                        mirrored=not raster.mirrored,
                    )
                elif operation in {"move", "copy"}:
                    result = replace(
                        raster,
                        origin_mm=(
                            raster.origin_mm[0] + point[0] - base[0],
                            raster.origin_mm[1] + point[1] - base[1],
                        ),
                    )
                else:
                    raise ValueError("图片不支持此操作。")
                results.append(result)
            if preview:
                self._raster_transform_preview = results[0]
                self._raster_transform_previews = tuple(results)
                self.update()
                return True
            copy_image = (
                keep_source
                or operation == "copy"
                or (operation == "rotate" and self._rotation_copy)
                or (operation == "scale" and self._scale_copy)
            )
            if copy_image:
                results = [replace(result, image_id=uuid4().hex) for result in results]
            if len(results) > 1:
                if self.commit_raster_batch is None:
                    raise ValueError("当前图纸暂不能批量变换图片。")
                self.commit_raster_batch("add" if copy_image else "update", tuple(results))
            elif copy_image:
                if self.commit_clipboard_raster is None:
                    raise ValueError("当前图纸暂不能复制图片。")
                self.commit_clipboard_raster(results[0])
            else:
                if self.commit_raster_edit is None:
                    raise ValueError("当前图纸暂不能修改图片。")
                self.commit_raster_edit("update", results[0])
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        self.cancel_transform()
        self.selected_raster_ids = {result.image_id for result in results}
        self.message = "已变换所选图片；可撤销。"
        self.changed.emit()
        self.update()
        return True

    def _transform_point(self, point: Point2D, *, commit: bool) -> None:
        if self._transform_operation == "rectangular_array_preview":
            return
        if self._transform_operation == "offset":
            self._interactive_offset_point(point, commit=commit)
            return
        if not self._transform_revision_current():
            return
        if self.awaiting_mirror_erase or self.copy_array_needs_count:
            return
        if self._transform_selecting:
            if commit:
                if self.selected_raster_id is not None and self._transform_operation not in {
                    "move",
                    "scale",
                    "rotate",
                    "mirror",
                    "copy",
                    "erase",
                }:
                    self.message = "暂不能同时选择图片和其他对象，请按 Enter 继续。"
                    self.changed.emit()
                    return
                self._select_at(point, additive=True)
                self.message = "继续选择图元；Enter / 右键结束选择。"
                self.changed.emit()
            return
        if self._transform_base is None:
            if commit:
                self._transform_base = point
                self.point_accepted.emit(point)
                self.message = self._transform_point_hint()
                self.changed.emit()
                self.update()
            return
        if self.scale_reference_active and self._scale_reference_length is None:
            if not commit:
                return
            if self._scale_reference_first is None:
                self._scale_reference_first = point
                self.message = "参考缩放：指定第二参考点。"
                self.point_accepted.emit(point)
            else:
                length = math.dist(self._scale_reference_first, point)
                if length <= 1e-9:
                    self.message = "参考长度必须大于零，请重新指定第二点。"
                elif self.apply_scale_length(length):
                    self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        if self.scale_target_points_active:
            first = self._scale_target_first
            if first is None:
                if commit:
                    self._scale_target_first = point
                    self.point_accepted.emit(point)
                    self.message = "参考缩放：指定目标长度的第二点。"
                    self.changed.emit()
                return
            length = math.dist(first, point)
            if length <= 1e-9:
                self._raster_transform_preview = None
                self._raster_transform_previews = ()
                self.update()
                if commit:
                    self.message = "目标长度必须大于零，请重新指定第二点。"
                    self.changed.emit()
                return
            if commit:
                if self.apply_scale_length(length):
                    self.point_accepted.emit(point)
            else:
                assert self._scale_reference_length is not None and self._transform_base is not None
                if self.selected_raster_id is not None and not self.selected_entity_ids:
                    self._apply_raster_transform(
                        self._transform_base,
                        factor=length / self._scale_reference_length,
                        preview=True,
                    )
                    return
                try:
                    candidate = self._transform_candidate(
                        self._transform_base, scale_factor=length / self._scale_reference_length
                    )
                except ValueError as exc:
                    self._transform_preview = ()
                    self.message = str(exc)
                    self.changed.emit()
                else:
                    self._show_transform_candidate(candidate, commit=False)
            return
        if (
            self._transform_operation == "rotate"
            and self._transform_reference_mode
            and self._transform_reference is None
            and self._transform_reference_angle is None
        ):
            if commit:
                if (
                    self._reference_previous_mode is None
                    and _distance(point, self._transform_base) <= 1e-9
                ):
                    self.message = "参考点不能与旋转中心重合。"
                else:
                    self._transform_reference = point
                    self.point_accepted.emit(point)
                    self.message = self._transform_point_hint()
                self.changed.emit()
                self.update()
            return
        if (
            self._transform_operation == "rotate"
            and self._transform_reference_mode
            and self._reference_previous_mode is not None
            and self._transform_reference is not None
            and self._transform_reference_angle is None
        ):
            if commit:
                first = self._transform_reference
                if _distance(point, first) <= 1e-9:
                    self.message = "参考线两点不能重合；请重新指定第二点。"
                else:
                    self._transform_reference_angle = math.degrees(
                        math.atan2(point[1] - first[1], point[0] - first[0])
                    )
                    self._transform_reference_end = point
                    self.point_accepted.emit(point)
                    self.message = self._transform_point_hint()
                self.changed.emit()
                self.update()
            return
        if self._transform_operation == "rotate" and self._rotation_target_points_active:
            first = self._rotation_target_first
            if first is None:
                if commit:
                    self._rotation_target_first = point
                    self.point_accepted.emit(point)
                    self.message = self._transform_point_hint()
                    self.changed.emit()
                    self.update()
                return
            if _distance(first, point) <= 1e-9:
                self._transform_preview = ()
                self._raster_transform_preview = None
                self._raster_transform_previews = ()
                if commit:
                    self.message = "目标方向两点不能重合；请重新指定第二点。"
                self.changed.emit()
                self.update()
                return
            target_angle = math.degrees(math.atan2(point[1] - first[1], point[0] - first[0]))
            if commit:
                if self.apply_rotation_target_angle(target_angle):
                    self.point_accepted.emit(point)
            else:
                reference = self.rotation_reference_angle
                if reference is not None:
                    if self.selected_raster_id is not None and not self.selected_entity_ids:
                        self._apply_raster_transform(
                            self._transform_base, angle=target_angle - reference, preview=True
                        )
                        return
                    try:
                        candidate = self._transform_candidate(
                            self._transform_base, angle_deg=target_angle - reference
                        )
                    except ValueError as exc:
                        self._transform_preview = ()
                        self.message = str(exc)
                        self.changed.emit()
                        self.update()
                    else:
                        self._show_transform_candidate(candidate, commit=False)
            return
        if self.selected_raster_id is not None and not self.selected_entity_ids:
            if commit and self._transform_operation == "mirror" and self._mirror_ask_erase:
                if math.dist(self._transform_base, point) <= 1e-9:
                    self.message = "镜像轴两点不能重合。"
                else:
                    self._mirror_axis_end = point
                    self.message = "删除源对象？[Y/N] <N>：Enter 保留，Esc 取消。"
                self.changed.emit()
                return
            factor = (
                math.dist(self._transform_base, point) / self._scale_reference_length
                if self.scale_reference_active and self._scale_reference_length
                else None
            )
            angle = None
            if self._transform_operation == "rotate" and self.rotation_reference_angle is not None:
                angle = (
                    math.degrees(
                        math.atan2(
                            point[1] - self._transform_base[1],
                            point[0] - self._transform_base[0],
                        )
                    )
                    - self.rotation_reference_angle
                )
            if (
                self._apply_raster_transform(
                    point,
                    factor=factor,
                    angle=angle,
                    keep_source=self._transform_operation == "mirror"
                    and self._transform_keep_source,
                    preview=not commit,
                )
                and commit
            ):
                self.point_accepted.emit(point)
            return
        reference_factor = (
            math.dist(self._transform_base, point) / self._scale_reference_length
            if self.scale_reference_active and self._scale_reference_length is not None
            else None
        )
        if (
            commit
            and self._transform_operation == "copy"
            and self.selected_raster_ids
            and self._selected_committed_entities()
        ):
            base = self._transform_base
            assert base is not None
            selected = tuple(self.selected_entity_ids)
            delta = (point[0] - base[0], point[1] - base[1])
            if math.hypot(*delta) <= 1e-9:
                self.message = "复制位移不能为零，请指定另一个点。"
                self.changed.emit()
                return
            count = self._copy_array_count
            if count is not None:
                if (
                    self._copy_array_ids != frozenset(self.selected_entity_ids)
                    or self._copy_array_history != self.history_position
                    or self._copy_array_image_sources
                    != tuple(
                        image
                        for image in self.drawing_rasters
                        if image.image_id in self.selected_raster_ids
                    )
                    or self._copy_array_sources
                    != tuple(
                        entity
                        for entity in self.selectable_entities()
                        if entity.entity_id in self._copy_array_ids
                    )
                ):
                    self.message = "复制阵列来源已变化，请重新选择。"
                    self.changed.emit()
                    return
                if self._copy_array_fit:
                    delta = (delta[0] / (count - 1), delta[1] / (count - 1))
            if self._copy_repeat:
                self._mixed_copy_pending_point = point
                self._copy_array_count = None
                self._copy_array_fit = False
            else:
                self.cancel_transform()
            if count is None:
                self.committed_mixed_copy_requested.emit(selected, delta)
            else:
                self.committed_mixed_copy_array_requested.emit(selected, delta, count)
            self.point_accepted.emit(point)
            return
        try:
            candidate = self._transform_candidate(point, scale_factor=reference_factor)
        except ValueError as exc:
            self._transform_preview = ()
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return
        if (
            self._transform_operation in {"move", "copy"}
            and self.selected_raster_ids
            and not commit
        ):
            base = self._transform_base
            assert base is not None
            dx, dy = point[0] - base[0], point[1] - base[1]
            count = self._copy_array_count if self._transform_operation == "copy" else None
            if count is not None and self._copy_array_fit:
                dx, dy = dx / (count - 1), dy / (count - 1)
            self._raster_transform_previews = tuple(
                replace(
                    image,
                    origin_mm=(image.origin_mm[0] + index * dx, image.origin_mm[1] + index * dy),
                )
                for index in range(1, count if count is not None else 2)
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
        elif self._transform_operation == "scale" and self.selected_raster_ids and not commit:
            base = self._transform_base
            assert base is not None
            factor = reference_factor if reference_factor is not None else math.dist(base, point)
            self._raster_transform_previews = tuple(
                replace(
                    image,
                    origin_mm=(
                        base[0] + (image.origin_mm[0] - base[0]) * factor,
                        base[1] + (image.origin_mm[1] - base[1]) * factor,
                    ),
                    width_mm=image.width_mm * factor,
                    height_mm=image.height_mm * factor,
                )
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
        elif self._transform_operation == "rotate" and self.selected_raster_ids and not commit:
            base = self._transform_base
            assert base is not None
            rotation = math.degrees(math.atan2(point[1] - base[1], point[0] - base[0]))
            rotation -= self.rotation_reference_angle or 0
            c, sn = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
            self._raster_transform_previews = tuple(
                replace(
                    image,
                    origin_mm=(
                        base[0]
                        + c * (image.origin_mm[0] - base[0])
                        - sn * (image.origin_mm[1] - base[1]),
                        base[1]
                        + sn * (image.origin_mm[0] - base[0])
                        + c * (image.origin_mm[1] - base[1]),
                    ),
                    angle_deg=image.angle_deg + rotation,
                )
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
        elif self._transform_operation == "mirror" and self.selected_raster_ids and not commit:
            base = self._transform_base
            assert base is not None
            axis = math.atan2(point[1] - base[1], point[0] - base[0])
            c, sn = math.cos(2 * axis), math.sin(2 * axis)
            self._raster_transform_previews = tuple(
                replace(
                    image,
                    origin_mm=(
                        base[0]
                        + c * (image.origin_mm[0] - base[0])
                        + sn * (image.origin_mm[1] - base[1]),
                        base[1]
                        + sn * (image.origin_mm[0] - base[0])
                        - c * (image.origin_mm[1] - base[1]),
                    ),
                    angle_deg=math.degrees(2 * axis) - image.angle_deg,
                    mirrored=not image.mirrored,
                )
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
        if commit and self._transform_operation == "rotate" and not self.rotation_uses_reference:
            base = self._transform_base
            assert base is not None
            self.rotation_default_angle = math.degrees(
                math.atan2(point[1] - base[1], point[0] - base[0])
            )
        if commit and self._transform_operation == "scale" and not self.scale_reference_active:
            self.scale_default_factor = math.dist(self._transform_base, point)
        if commit and self._transform_operation == "mirror" and self._mirror_ask_erase:
            self._mirror_axis_end = point
            self._mirror_candidate = candidate
            self._mirror_selected_ids = frozenset(self.selected_entity_ids)
            self._mirror_selected_sources = tuple(
                entity
                for entity in self.selectable_entities()
                if entity.entity_id in self.selected_entity_ids
            )
            self._mirror_history_position = self.history_position
            source_ids = {entity.entity_id for entity in self.entities}
            self._transform_preview = tuple(
                entity for entity in candidate if entity.entity_id not in source_ids
            )
            self.message = "删除源对象？[Y/N] <N>：Enter 保留，Esc 取消。"
            self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        if commit and self._transform_operation == "move" and self._selected_committed_entities():
            base = self._transform_base
            assert base is not None
            selected = tuple(self.selected_entity_ids)
            delta = (point[0] - base[0], point[1] - base[1])
            self.cancel_transform()
            self.committed_move_requested.emit(selected, delta)
            self.point_accepted.emit(point)
            return
        if commit and self._transform_operation == "move" and self.selected_raster_ids:
            base = self._transform_base
            assert base is not None
            dx, dy = point[0] - base[0], point[1] - base[1]
            images = tuple(
                replace(image, origin_mm=(image.origin_mm[0] + dx, image.origin_mm[1] + dy))
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
            if (
                len(images) != len(self.selected_raster_ids)
                or self.commit_mixed_draft_transform is None
            ):
                self.message = "所选图片已变化或无法编辑，请重新选择。"
                self.changed.emit()
                return
            if self.commit_mixed_draft_transform(candidate, images, "update"):
                self.cancel_transform()
                self.message = "已移动图片和图元；可撤销。"
                self.changed.emit()
                self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "copy"
            and self.selected_raster_ids
            and not self._selected_committed_entities()
        ):
            base = self._transform_base
            assert base is not None
            dx, dy = point[0] - base[0], point[1] - base[1]
            count = self._copy_array_count or 2
            if self._copy_array_count is not None and self._copy_array_fit:
                dx, dy = dx / (count - 1), dy / (count - 1)
            sources = tuple(
                image
                for image in self.drawing_rasters
                if image.image_id in self.selected_raster_ids
            )
            if (
                len(sources) != len(self.selected_raster_ids)
                or self.commit_mixed_draft_transform is None
            ):
                self.message = "所选图片已变化或无法编辑，请重新选择。"
                self.changed.emit()
                return
            images = tuple(
                replace(
                    image,
                    image_id=uuid4().hex,
                    origin_mm=(image.origin_mm[0] + i * dx, image.origin_mm[1] + i * dy),
                )
                for i in range(1, count)
                for image in sources
            )
            omission_notice = self.draft_copy_omission_notice()
            identity = self.commit_mixed_draft_transform(candidate, images, "add")
            if identity:
                if self._copy_repeat and self.source_revision_provider is not None:
                    self._mixed_copy_pending_point = point
                    self.finish_mixed_copy_commit(identity, self.source_revision_provider())
                    self._copy_array_count = None
                    self._copy_array_fit = False
                else:
                    self.cancel_transform()
                    self.message = "已复制图片和图元；可撤销。"
                    self.changed.emit()
                if omission_notice:
                    self.message += omission_notice
                    self.changed.emit()
                self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "scale"
            and self._selected_committed_entities()
            and (not self._scale_copy or self.selected_raster_ids)
        ):
            base = self._transform_base
            assert base is not None
            selected = tuple(self.selected_entity_ids)
            factor = reference_factor if reference_factor is not None else math.dist(base, point)
            copy_source = self._scale_copy
            self.cancel_transform()
            if copy_source:
                self.committed_scale_copy_requested.emit(selected, base, factor)
            else:
                self.committed_scale_requested.emit(selected, base, factor)
            self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "rotate"
            and self._selected_committed_entities()
            and (not self._rotation_copy or self.selected_raster_ids)
        ):
            base = self._transform_base
            assert base is not None
            angle = math.degrees(math.atan2(point[1] - base[1], point[0] - base[0]))
            reference_angle = self.rotation_reference_angle
            if reference_angle is not None:
                angle -= reference_angle
            self._commit_saved_rotation(angle)
            self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation in {"scale", "rotate"}
            and self.selected_raster_ids
            and not self._selected_committed_entities()
        ):
            center = self._transform_base
            assert center is not None
            if self._transform_operation == "scale":
                factor = (
                    reference_factor if reference_factor is not None else math.dist(center, point)
                )
                done = self._commit_mixed_draft_affine(candidate, center, scale=factor)
            else:
                angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
                angle -= self.rotation_reference_angle or 0
                done = self._commit_mixed_draft_affine(candidate, center, angle=angle)
            if done:
                self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "mirror"
            and not self._transform_keep_source
            and self._selected_committed_entities()
        ):
            start = self._transform_base
            assert start is not None
            selected = tuple(self.selected_entity_ids)
            self.cancel_transform()
            self.committed_mirror_requested.emit(selected, start, point)
            self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "mirror"
            and self._transform_keep_source
            and self.selected_raster_ids
            and self._selected_committed_entities()
        ):
            start = self._transform_base
            assert start is not None
            selected = tuple(self.selected_entity_ids)
            self.cancel_transform()
            self.committed_mirror_copy_requested.emit(selected, start, point)
            self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "mirror"
            and self.selected_raster_ids
            and not self._selected_committed_entities()
        ):
            start = self._transform_base
            assert start is not None
            if self._commit_mixed_draft_mirror(
                candidate, start, point, keep_source=self._transform_keep_source
            ):
                self.point_accepted.emit(point)
            return
        was_array = self._copy_array_count is not None
        self._show_transform_candidate(candidate, commit=commit, point=point)
        if commit and tuple(self.entities) == candidate:
            if was_array and self._transform_operation == "copy":
                self._copy_array_count = None
                self._copy_array_fit = False
                self._copy_array_ids = frozenset()
                self._copy_array_sources = ()
                self._copy_array_preview_point = None
                self._copy_array_candidate = ()
                self.message = "已创建复制阵列；可继续复制，U 撤销，Enter 结束。"
                self.changed.emit()
            self.point_accepted.emit(point)

    def _confirm_transform_default(self) -> None:
        if not self._transform_revision_current():
            return
        if self._transform_operation == "offset":
            self.cancel_transform()
        elif self.copy_array_needs_count:
            self.message = "复制阵列：请先输入数量。"
            self.changed.emit()
        elif self.awaiting_mirror_erase:
            self.confirm_mirror_erase(False)
        elif self._transform_selecting:
            self._finish_transform_selection()
        elif self._transform_operation == "copy" and self._transform_base is not None:
            if self.select_committed_entities and not (
                self._copy_placements or self._mixed_copy_started
            ):
                u, v = self._transform_base
                self._transform_point((2 * u, 2 * v), commit=True)
            else:
                self.cancel_transform()
                self.message = "复制已结束；已放置的副本保留。"
                self.changed.emit()
        elif self._transform_operation == "move" and self._transform_base is not None:
            u, v = self._transform_base
            self._transform_point((2 * u, 2 * v), commit=True)

    @property
    def copy_last_point(self) -> Point2D | None:
        """Last retained copy destination, or its original base point."""
        if self._transform_operation != "copy":
            return None
        if self._mixed_copy_placements:
            return self._mixed_copy_placements[-1][0]
        return self._copy_placements[-1][0] if self._copy_placements else self._transform_base

    def undo_copy_placement(self) -> bool:
        """Undo only the latest placement in the active repeated-copy gesture."""
        if not self._transform_revision_current():
            return False
        if self._transform_operation == "copy" and self._mixed_copy_placements:
            _point, identity, revision = self._mixed_copy_placements[-1]
            self.saved_mixed_copy_undo_requested.emit(identity, self.history_position, revision)
            return True
        if self._transform_operation != "copy" or not self._copy_placements:
            self.message = "没有可撤销的复制；请选择目标点。"
            self.changed.emit()
            return False
        _point, before, after = self._copy_placements[-1]
        if (
            self.history_position != after
            or not self._undo_history
            or self._undo_history[-1].history_position != before
        ):
            self.message = "草稿历史已变化，无法撤销该复制；请结束当前命令。"
            self.changed.emit()
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self._copy_placements.pop()
        self._transform_preview = ()
        self.message = "已撤销上一个副本；指定下一个目标点。"
        if self.copy_last_point is not None:
            self.point_accepted.emit(self.copy_last_point)
        self.changed.emit()
        self.update()
        return True

    def has_mixed_draft_copy(self, identity: str) -> bool:
        return identity in self._mixed_draft_copy_ids

    def finish_mixed_copy_commit(
        self, identity: str | None, revision: int, *, includes_draft: bool = False
    ) -> None:
        point = self._mixed_copy_pending_point
        self._mixed_copy_pending_point = None
        if point is None or self._transform_operation != "copy":
            return
        if identity is None:
            self.message = "复制失败；可以重新指定目标点。"
        else:
            self._mixed_copy_placements.append((point, identity, revision))
            if includes_draft:
                self._mixed_draft_copy_ids.add(identity)
            self._mixed_copy_started = True
            self._transform_source_revision = revision
            self._transform_preview = ()
            self._raster_transform_previews = ()
            self.message = "已复制；指定下一个目标点，U 撤销，Enter 结束。"
        self.changed.emit()
        self.update()

    def finish_mixed_copy_undo(self, identity: str, revision: int) -> None:
        if not self._mixed_copy_placements or self._mixed_copy_placements[-1][1] != identity:
            return
        self._mixed_copy_placements.pop()
        self._mixed_draft_copy_ids.discard(identity)
        if self._mixed_copy_placements:
            point, previous, _old_revision = self._mixed_copy_placements[-1]
            self._mixed_copy_placements[-1] = (point, previous, revision)
        self._transform_source_revision = revision
        self.message = "已撤销上一个副本；指定下一个目标点。"
        self.changed.emit()
        self.update()

    def _begin_trim_drag(self, point: Point2D) -> None:
        self._clear_line_edit_preview()
        self._trim_drag_start = point
        self._trim_drag_last = point
        self._hovered_line_edit_entity_id = self._trim_target_at(point)
        self._trim_drag_original_entities = tuple(self.entities)
        self._trim_drag_original_constraints = tuple(self.constraints)
        self._trim_drag_original_selection = frozenset(self.selected_entity_ids)
        self._trim_drag_candidate_entities = tuple(self.entities)
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error = None
        self._trim_drag_moved = False
        self._trim_drag_saved_target = False
        self._trim_drag_blocked = False
        self._trim_drag_original_background = self.background_entities
        self._trim_drag_spatial_snapshot = self.spatial_boundaries
        self._trim_drag_spatial_frame = self._spatial_target_frame
        self._trim_drag_spatial_unsupported = self._spatial_boundary_unsupported
        self._trim_drag_saved_events = []
        self._trim_drag_source_revision = (
            self.source_context_revision
            if self.source_context_revision is not None
            else self.source_revision_provider()
            if self.source_revision_provider is not None
            else None
        )

    @property
    def trim_fence_active(self) -> bool:
        return self._trim_fence_active

    @property
    def line_edit_erasing(self) -> bool:
        return self._line_edit_erasing

    def begin_line_edit_erase(self) -> None:
        if self.tool != "修剪" or self.has_active_edit_gesture:
            raise ValueError("请先完成或取消当前操作。")
        self._line_edit_erasing = True
        self._line_erase_history = self.history_position
        self._line_erase_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )
        self.selected_entity_ids.clear()
        self.selected_constraint_ids.clear()
        self._clear_line_edit_preview()
        self._hovered_line_edit_entity_id = None
        self.message = "选择要删除的对象；Enter / 右键确认，Esc 取消。"
        self.changed.emit()
        self.update()

    def _finish_line_edit_erase(self) -> None:
        self._line_edit_erasing = False
        if self.history_position != self._line_erase_history or (
            self.source_revision_provider is not None
            and self.source_revision_provider() != self._line_erase_revision
        ):
            self.selected_entity_ids.clear()
            self.message = "草稿或文档已变化；删除未执行。"
            self.changed.emit()
            return
        before = self.history_position
        if not self.selected_entity_ids and not self.selected_constraint_ids:
            self.message = "未选择删除对象；继续修剪。"
            self.changed.emit()
            return
        if self.delete_selected() and self.history_position != before:
            self._line_edit_undo_actions.append(("draft", self.history_position, "", 0))

    def begin_trim_fence(self) -> None:
        if self.tool not in {"修剪", "延伸"} or self.has_active_edit_gesture:
            raise ValueError("请先完成或取消当前操作。")
        self._trim_fence_active = True
        self._trim_fence_points.clear()
        self._trim_fence_seen.clear()
        self.message = f"{self.tool}围栏：指定第一点，再逐点绘制；Enter 完成，Esc 取消。"
        self.changed.emit()

    def begin_line_crossing(self) -> None:
        self.begin_trim_fence()
        self._line_crossing_active = True
        self.message = f"{self.tool}交叉窗口：指定第一角点，再指定对角点；Esc 取消。"
        self.changed.emit()

    def _add_trim_fence_point(self, point: Point2D) -> None:
        if self._line_crossing_active and self._trim_drag_start is not None:
            if self._finish_line_crossing(point):
                self.point_accepted.emit(point)
            return
        if self._trim_drag_start is None:
            self._begin_trim_drag(point)
            self.message = (
                f"{self.tool}交叉窗口：指定对角点；Esc 取消。"
                if self._line_crossing_active
                else f"{self.tool}围栏：指定下一点；Enter 完成，Esc 取消。"
            )
        else:
            self._update_trim_drag(point)
        self._trim_fence_points.append(point)
        self.point_accepted.emit(point)
        self.changed.emit()
        self.update()

    def _finish_trim_fence(self) -> None:
        self._trim_fence_active = False
        self._line_crossing_active = False
        if self._trim_drag_start is None:
            self.message = "围栏未指定；草图未修改。"
            self._trim_fence_points.clear()
            self.changed.emit()
        elif not self._trim_drag_moved:
            self._cancel_trim_drag()
        else:
            self._finish_trim_drag()

    def _finish_line_crossing(self, opposite: Point2D) -> bool:
        first = self._trim_drag_start
        if first is None:
            return False
        if abs(opposite[0] - first[0]) <= 1e-9 or abs(opposite[1] - first[1]) <= 1e-9:
            self.message = "交叉窗口必须有非零宽度和高度。"
            self.changed.emit()
            return False
        original = self.selectable_entities()
        self._line_crossing_original_ids = {entity.entity_id for entity in original}
        self._trim_drag_moved = True
        inside = tuple(
            entity
            for entity in original
            if entity_in_selection_box(entity, first, opposite, crossing=False)
        )
        if (opposite[0] - first[0]) * (opposite[1] - first[1]) > 0:
            corners = ((first[0], opposite[1]), opposite, (opposite[0], first[1]), first)
        else:
            corners = ((opposite[0], first[1]), opposite, (first[0], opposite[1]), first)
        self._trim_fence_points.extend(corners)
        for corner in corners:
            self._update_trim_drag(corner)
        for entity in inside:
            if entity.entity_id in self._trim_fence_seen:
                continue
            segment: SketchEntity = entity
            if isinstance(entity, PolylineEntity):
                count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                segments = polyline_curve_segments(
                    entity.points_mm,
                    entity.bulges or (0.0,) * count,
                    entity.closed,
                    entity.entity_id,
                )
                if self.tool == "延伸" and not entity.closed:
                    segment = (
                        segments[0]
                        if _distance(first, entity.points_mm[0])
                        <= _distance(first, entity.points_mm[-1])
                        else segments[-1]
                    )
                else:
                    segment = min(
                        segments,
                        key=lambda part: (
                            _distance_to_segment(first, part.start_mm, part.end_mm)
                            if isinstance(part, LineEntity)
                            else _distance_to_arc(first, part)
                        ),
                    )
            elif isinstance(entity, RectangleEntity):
                a, c = entity.first_corner_mm, entity.opposite_corner_mm
                vertices = (a, (c[0], a[1]), c, (a[0], c[1]))
                edges = tuple(
                    LineEntity(entity.entity_id, vertices[index], vertices[(index + 1) % 4])
                    for index in range(4)
                )
                segment = min(
                    edges, key=lambda edge: _distance_to_segment(first, edge.start_mm, edge.end_mm)
                )
            if isinstance(segment, LineEntity):
                dx = segment.end_mm[0] - segment.start_mm[0]
                dy = segment.end_mm[1] - segment.start_mm[1]
                ratio = (
                    (first[0] - segment.start_mm[0]) * dx + (first[1] - segment.start_mm[1]) * dy
                ) / (dx * dx + dy * dy)
                ratio = min(0.99, max(0.01, ratio))
                sample = (segment.start_mm[0] + ratio * dx, segment.start_mm[1] + ratio * dy)
            elif isinstance(segment, CircleEntity | ArcEntity):
                if isinstance(segment, CircleEntity):
                    angle = math.degrees(
                        math.atan2(first[1] - segment.center_mm[1], first[0] - segment.center_mm[0])
                    )
                else:
                    endpoints = tuple(
                        (
                            segment.center_mm[0] + segment.radius_mm * math.cos(math.radians(a)),
                            segment.center_mm[1] + segment.radius_mm * math.sin(math.radians(a)),
                        )
                        for a in (
                            segment.start_angle_deg,
                            segment.start_angle_deg + segment.sweep_angle_deg,
                        )
                    )
                    ratio = (
                        0.01
                        if _distance(first, endpoints[0]) <= _distance(first, endpoints[1])
                        else 0.99
                    )
                    angle = segment.start_angle_deg + segment.sweep_angle_deg * ratio
                sample = (
                    segment.center_mm[0] + segment.radius_mm * math.cos(math.radians(angle)),
                    segment.center_mm[1] + segment.radius_mm * math.sin(math.radians(angle)),
                )
            else:
                self._trim_drag_blocked = True
                self._trim_drag_last_error = "交叉窗口包含暂不支持的目标；本次未修改。"
                continue
            if self.tool == "延伸" and isinstance(entity, PolylineEntity) and not entity.closed:
                sample = min(
                    (entity.points_mm[0], entity.points_mm[-1]),
                    key=lambda endpoint: _distance(first, endpoint),
                )
            self._update_trim_drag(first, forced_hit=(sample, entity.entity_id))
        self._finish_trim_fence()
        return True

    def _clear_trim_drag(self) -> None:
        self._clear_line_edit_preview()
        self._trim_fence_points.clear()
        self._trim_fence_seen.clear()
        self._line_crossing_original_ids.clear()
        self._trim_drag_start = None
        self._trim_drag_last = None
        self._trim_drag_original_entities = None
        self._trim_drag_original_constraints = None
        self._trim_drag_original_selection = None
        self._trim_drag_candidate_entities = None
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error = None
        self._trim_drag_moved = False
        self._trim_drag_saved_target = False
        self._trim_drag_blocked = False
        self._trim_drag_original_background = None
        self._trim_drag_saved_events = []
        self._trim_drag_source_revision = None
        self._trim_drag_spatial_snapshot = None
        self._trim_drag_spatial_frame = None
        self._trim_drag_spatial_unsupported = False

    def _update_trim_drag(
        self, point: Point2D, *, forced_hit: tuple[Point2D, str] | None = None
    ) -> None:
        start = self._trim_drag_start
        previous = self._trim_drag_last
        candidate_entities = self._trim_drag_candidate_entities
        if start is None or previous is None or candidate_entities is None:
            return
        if _distance(point, start) * self._scale > 3.0:
            self._trim_drag_moved = True
        if not self._trim_drag_moved:
            self._trim_drag_last = point
            return

        if forced_hit is not None:
            samples: list[tuple[Point2D, str | None]] = [forced_hit]
        elif self._trim_fence_active:
            try:
                original_entities = self._trim_drag_original_entities or ()
                original_background = self._trim_drag_original_background or ()
                for original in (
                    *(entity for entity in original_entities if self._layer(entity).displayed),
                    *(
                        entity
                        for entity, layer in original_background
                        if self.select_committed_entities and layer.displayed
                    ),
                ):
                    fence_intersections(previous, point, original)
                hits = [
                    (hit, entity.entity_id)
                    for entity in self.selectable_entities()
                    if not self._line_crossing_active
                    or entity.entity_id in self._line_crossing_original_ids
                    for hit in fence_intersections(previous, point, entity)
                ]
            except ValueError as exc:
                self._trim_drag_blocked = True
                self._trim_drag_last_error = str(exc)
                self._trim_drag_last = point
                self.message = str(exc)
                self.changed.emit()
                self.update()
                return
            hits.sort(key=lambda item: _distance(previous, item[0]))
            samples = []
            for hit, identity in hits:
                if any(
                    other != identity and _distance(hit, other_hit) <= 1e-9
                    for other_hit, other in hits
                ):
                    self._trim_drag_last_error = "围栏交点包含重叠目标，无法唯一选择。"
                    self._trim_drag_blocked = True
                else:
                    samples.append((hit, identity))
        else:
            sample_count = max(1, math.ceil(_distance(previous, point) * self._scale / 6.0))
            samples = [
                (
                    (
                        previous[0] + index / sample_count * (point[0] - previous[0]),
                        previous[1] + index / sample_count * (point[1] - previous[1]),
                    ),
                    None,
                )
                for index in range(sample_count + 1)
            ]
        for sample, fence_target in samples:
            self.entities = list(candidate_entities)
            self._snap_candidates_cache = None
            target_id = fence_target if self._trim_fence_active else self._trim_target_at(sample)
            if target_id is None:
                continue
            if (
                self._trim_fence_active
                and (self.tool == "延伸" or self._line_crossing_active)
                and target_id in self._trim_fence_seen
            ):
                continue
            if self._line_crossing_active:
                self._trim_fence_seen.add(target_id)
            target = next(
                (entity for entity in candidate_entities if entity.entity_id == target_id),
                None,
            )
            picked = target or next(
                (entity for entity, _ in self.background_entities if entity.entity_id == target_id),
                None,
            )
            operation = "延伸" if self._trim_fence_active and self.tool == "延伸" else "修剪"
            edit_point = sample
            if operation == "延伸":
                self._trim_fence_seen.add(target_id)
                if isinstance(picked, LineEntity):
                    endpoints = (picked.start_mm, picked.end_mm)
                elif isinstance(picked, ArcEntity):
                    endpoints = tuple(
                        point
                        for _ref, point in self._entity_handles(picked)
                        if _ref.kind in ("start", "end")
                    )
                elif isinstance(picked, PolylineEntity) and not picked.closed:
                    endpoints = (picked.points_mm[0], picked.points_mm[-1])
                else:
                    self._trim_drag_last_error = "围栏选中的对象没有可延伸端点。"
                    self._trim_drag_blocked = True
                    continue
                if (
                    abs(_distance(sample, endpoints[0]) - _distance(sample, endpoints[1]))
                    * self._scale
                    <= 1
                ):
                    self._trim_drag_last_error = "围栏交点距离两个端点相同，无法选择延伸方向。"
                    self._trim_drag_blocked = True
                    continue
                edit_point = min(endpoints, key=lambda endpoint: _distance(sample, endpoint))
            if target is None:
                saved = next(
                    (
                        (entity, layer)
                        for entity, layer in self.background_entities
                        if entity.entity_id == target_id
                    ),
                    None,
                )
                if saved is not None:
                    self._trim_drag_saved_target = True
                    if saved[1].locked:
                        self._trim_drag_last_error = "目标图元所在图层已锁定；图元未修改。"
                        self._trim_drag_blocked = True
                        continue
                    try:
                        changed = self._edit_visible_geometry(
                            candidate_entities,
                            operation,
                            edit_point,
                            target_id,
                            allow_endpoint_intersections=True,
                        )
                        known = {
                            e.entity_id
                            for e in (
                                *candidate_entities,
                                *(e for e, _ in self.background_entities),
                            )
                        }
                        fragments = tuple(
                            replace(e, entity_id=uuid4().hex)
                            if e.entity_id == target_id
                            and type(e) is not type(saved[0])
                            and not (
                                isinstance(saved[0], CircleEntity) and isinstance(e, ArcEntity)
                            )
                            else e
                            for e in changed
                            if e.entity_id == target_id or e.entity_id not in known
                        )
                    except ValueError as exc:
                        self._trim_drag_last_error = str(exc)
                        if "没有与其他直线段的内部交点" not in str(exc):
                            self._trim_drag_blocked = True
                    else:
                        self._trim_drag_saved_events.append((target_id, fragments))
                        overlay: list[tuple[SketchEntity, SketchLayer]] = []
                        for entity, layer in self.background_entities:
                            if entity.entity_id == target_id:
                                overlay.extend((fragment, layer) for fragment in fragments)
                            else:
                                overlay.append((entity, layer))
                        self.background_entities = tuple(overlay)
                        self._trim_drag_changed_count += 1
                continue
            if self._layer(target).locked:
                self._trim_drag_last_error = "目标图元所在图层已锁定；草图未修改。"
                self._trim_drag_blocked = True
                continue
            try:
                updated = self._edit_draft_with_boundaries(
                    candidate_entities,
                    operation,
                    edit_point,
                    target_id,
                    allow_endpoint_intersections=True,
                )
            except ValueError as exc:
                self._trim_drag_last_error = str(exc)
                if "没有与其他直线段的内部交点" not in str(exc):
                    self._trim_drag_blocked = True
                continue
            if updated == candidate_entities:
                continue
            candidate_entities = updated
            self._trim_drag_candidate_entities = updated
            self._trim_drag_changed_count += 1

        self._trim_drag_candidate_entities = candidate_entities
        self._trim_drag_last = point
        self.entities = list(candidate_entities)
        self._snap_candidates_cache = None
        self.message = (
            f"{'围栏' if self._trim_fence_active else '拖动'}{self.tool}预览 · "
            f"已选 {self._trim_drag_changed_count} 个区段；"
            f"{'Enter 完成' if self._trim_fence_active else '松开保留'}，Esc 取消。"
            if self._trim_drag_changed_count
            else self._trim_drag_last_error
            or (
                f"{self.tool}围栏：指定下一点；Enter 完成，Esc 取消。"
                if self._trim_fence_active
                else "拖过要修剪的曲线区段；松开完成，Esc 取消。"
            )
        )
        self.changed.emit()
        self.update()

    def _finish_trim_drag(self) -> bool:
        action = "围栏延伸" if self.tool == "延伸" else "拖动修剪"
        start = self._trim_drag_start
        original = self._trim_drag_original_entities
        original_constraints = self._trim_drag_original_constraints
        original_selection = self._trim_drag_original_selection
        candidate = self._trim_drag_candidate_entities
        moved = self._trim_drag_moved
        changed_count = self._trim_drag_changed_count
        last_error = self._trim_drag_last_error
        if start is None or original is None or original_constraints is None or candidate is None:
            return False
        if (
            self.spatial_boundaries != self._trim_drag_spatial_snapshot
            or self._spatial_target_frame != self._trim_drag_spatial_frame
            or self._spatial_boundary_unsupported != self._trim_drag_spatial_unsupported
        ):
            self._cancel_trim_drag()
            self.message = f"异面边界已变化；{action}已取消，请重新操作。"
            self.changed.emit()
            return True
        if self.source_revision_provider is not None:
            revision = self.source_revision_provider()
            if revision != self._trim_drag_source_revision or (
                self.source_context_revision is not None
                and revision != self.source_context_revision
            ):
                self._cancel_trim_drag()
                self.source_revision_invalidated.emit()
                self.message = f"文档已变化；{action}已取消，请重新操作。"
                self.changed.emit()
                return True
        if not moved:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.selected_entity_ids = set(original_selection or ())
            self._snap_candidates_cache = None
            self._clear_trim_drag()
            self._hovered_line_edit_entity_id = None
            self._accept_point(start)
            return True
        if self._trim_drag_blocked and not self._trim_drag_saved_target:
            self._cancel_trim_drag()
            self.message = f"{action}未能安全完成；本次未修改。"
            if last_error:
                self.message += f" {last_error}"
            self.changed.emit()
            return True
        if self._trim_drag_saved_target:
            saved_events = tuple(self._trim_drag_saved_events)
            source_revision = self._trim_drag_source_revision
            original_background = self._trim_drag_original_background
            final_background = self.background_entities
            candidate_constraints = original_constraints
            blocked = self._trim_drag_blocked or not saved_events
            if not blocked:
                try:
                    candidate_constraints = self._line_edit_user_constraints(
                        candidate, trim=self.tool == "修剪", original_entities=original
                    )
                    self.constraints = list(candidate_constraints)
                    self._preserve_satisfied_relations(candidate, original_entities=original)
                    candidate_constraints = tuple(self.constraints)
                except ValueError as exc:
                    blocked = True
                    last_error = str(exc)
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.selected_entity_ids = set(original_selection or ())
            if original_background is not None:
                self.background_entities = original_background
            self._snap_candidates_cache = None
            self._clear_trim_drag()
            self._hovered_line_edit_entity_id = None
            if not blocked:
                self.message = f"正在校验{action}。"
                self.changed.emit()
                self.update()
                self.committed_drag_trim_requested.emit(
                    saved_events,
                    candidate,
                    candidate_constraints,
                    final_background,
                    source_revision,
                )
                return True
            self.message = f"{action}未能安全完成；本次未修改。"
            if last_error:
                self.message += f" {last_error}"
            self.changed.emit()
            self.update()
            return True
        if candidate != original:
            try:
                candidate_constraints = self._line_edit_user_constraints(
                    candidate, trim=self.tool == "修剪", original_entities=original
                )
            except ValueError as exc:
                self.entities = list(original)
                self.constraints = list(original_constraints)
                self.selected_entity_ids = set(original_selection or ())
                self._snap_candidates_cache = None
                self.message = str(exc)
                self._clear_trim_drag()
                self._hovered_line_edit_entity_id = None
                self.changed.emit()
                self.update()
                return True
            self._undo_history.append(
                _DraftState(
                    original,
                    original_constraints,
                    original_selection or frozenset(),
                    self.layer_table,
                    self.active_layer_name,
                    history_position=self.history_position,
                    mixed_move=self.mixed_move,
                    pending_cross_tangencies=tuple(self.pending_cross_tangencies),
                    last_polar_entity_id=self._last_polar_entity_id,
                )
            )
            self._advance_history()
            if self.tool in {"修剪", "延伸"}:
                self._line_edit_undo_actions.append(("draft", self.history_position, "", 0))
            self.entities = list(candidate)
            self._prune_pending_cross_tangencies(original_entities=original)
            self.constraints = list(candidate_constraints)
            removed_relations = self._preserve_satisfied_relations(
                candidate, original_entities=original
            )
            available = {entity.entity_id for entity in candidate}
            self.selected_entity_ids.intersection_update(available)
            self._snap_candidates_cache = None
            self.message = (
                f"围栏延伸完成；本次延伸了 {changed_count} 个对象。"
                if self.tool == "延伸"
                else f"拖动修剪完成；本次移除了 {changed_count} 个选定区段。"
            )
            if removed_relations:
                self.message += f" 已移除 {removed_relations} 条失效或需重新确认的自动关系。"
        else:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.selected_entity_ids = set(original_selection or ())
            self._snap_candidates_cache = None
            self.message = last_error or f"{action}路径没有命中可编辑对象；草图未修改。"
        self._clear_trim_drag()
        self._hovered_line_edit_entity_id = None
        self.changed.emit()
        self.update()
        return True

    def _cancel_trim_drag(self) -> bool:
        original = self._trim_drag_original_entities
        original_constraints = self._trim_drag_original_constraints
        if original is None or original_constraints is None:
            return False
        self.entities = list(original)
        self.constraints = list(original_constraints)
        self.selected_entity_ids = set(self._trim_drag_original_selection or ())
        if self._trim_drag_original_background is not None:
            self.background_entities = self._trim_drag_original_background
        self._snap_candidates_cache = None
        self._clear_trim_drag()
        self._hovered_line_edit_entity_id = None
        action = "围栏延伸" if self.tool == "延伸" else "拖动修剪"
        self.message = f"已取消{action}；草图几何保持原样。"
        self.changed.emit()
        self.update()
        return True

    def _drag_target(self, raw_point: Point2D) -> tuple[Point2D, str]:
        origin = self._drag_origin
        if origin is None or not self._snapping_enabled:
            return raw_point, ""
        candidates = tuple(
            candidate
            for candidate in self._snap_candidates()
            if _distance(candidate[0], origin) > 1e-9
        )
        nearest = min(
            candidates,
            key=lambda candidate: (
                _distance(raw_point, candidate[0]),
                _SNAP_PRIORITY.get(candidate[1], len(_SNAP_PRIORITY)),
            ),
            default=None,
        )
        if (
            nearest is not None
            and _distance(raw_point, nearest[0]) * self._scale <= _SNAP_RADIUS_PX
        ):
            return nearest
        return raw_point, ""

    def _solve_handle_drag(
        self,
        entities: tuple[SketchEntity, ...],
        constraints: tuple[SketchConstraint, ...],
        reference: SketchGeometryReference,
        point: Point2D,
    ) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]] | None:
        if self._drag_solver is None:
            if constraints:
                return None
            try:
                return self._checked_pending_drag(
                    move_sketch_handle(entities, reference, point), constraints
                )
            except ValueError as exc:
                self.message = str(exc)
                return None
        try:
            result = self._drag_solver(entities, constraints, reference, point)
        except (RuntimeError, TypeError, ValueError) as exc:
            self.message = f"约束拖动求解失败；当前几何保持原样：{exc}"
            return None
        if result.status == "success" and result.sketch is not None:
            self._drag_branch_warning = "；".join(
                f"{change.message}（{'、'.join(identity[:8] for identity in change.entity_ids)}）"
                for change in result.branch_changes
            )
            return self._checked_pending_drag(result.sketch.entities, result.sketch.constraints)
        if result.status == "unavailable" and not constraints:
            try:
                return self._checked_pending_drag(
                    move_sketch_handle(entities, reference, point), constraints
                )
            except ValueError as exc:
                self.message = str(exc)
                return None
        self.message = result.message or "草图约束无法满足拖动位置。"
        return None

    def _checked_pending_drag(
        self, entities: tuple[SketchEntity, ...], constraints: tuple[SketchConstraint, ...]
    ) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]] | None:
        original = {entity.entity_id: entity for entity in self._drag_original_entities or ()}
        changed = {
            entity.entity_id
            for entity in entities
            if entity.entity_id in original and entity != original[entity.entity_id]
        }
        if any(
            self._layer(original[identity]).locked or not self._layer(original[identity]).displayed
            for identity in changed
        ):
            self.message = "求解涉及锁定或隐藏图层；图形未修改。"
            return None
        for constraint in self._drag_original_constraints or ():
            if constraint.kind not in DIMENSION_KINDS or not any(
                reference.entity_id in changed for reference in constraint.references
            ):
                continue
            layer = self.annotation_layer(constraint)
            if layer.locked or not layer.displayed:
                self.message = "相关标注位于锁定或隐藏图层；图形未修改。"
                return None
        for source, draft in self.pending_cross_tangencies:
            source_ref, draft_ref = draft_tangent_reference(source), draft_tangent_reference(draft)
            targets = [item for item in entities if item.entity_id == draft_ref.entity_id]
            try:
                sources = self._pending_source_curves(source_ref)
                valid = len(sources) == len(targets) == 1 and tangent_on_curves(
                    sources[0],
                    tangent_entity_curve(targets[0], draft_ref.index),
                )
            except ValueError:
                valid = False
            if not valid:
                self.message = "拖动无法保持暂存的对象相切；请先完成或取消当前草图。"
                return None
        return entities, constraints

    def _clear_handle_drag(self) -> None:
        self._drag_reference = None
        self._drag_entity_id = None
        self._drag_origin = None
        self._drag_original_entities = None
        self._drag_original_constraints = None
        self._drag_original_selection = None
        self._drag_last_entities = None
        self._drag_last_constraints = None
        self._drag_branch_warning = ""

    def _cancel_handle_drag(self) -> bool:
        if self._drag_original_entities is None or self._drag_original_constraints is None:
            return False
        self.entities = list(self._drag_original_entities)
        self.constraints = list(self._drag_original_constraints)
        self.selected_entity_ids = set(self._drag_original_selection or ())
        self._snap_candidates_cache = None
        self._clear_handle_drag()
        self.message = "已取消控制点拖动；草图几何保持原样。"
        self.changed.emit()
        self.update()
        return True

    def _finish_handle_drag(self) -> bool:
        original = self._drag_original_entities
        original_constraints = self._drag_original_constraints
        current = self._drag_last_entities
        current_constraints = self._drag_last_constraints
        if (
            original is None
            or original_constraints is None
            or current is None
            or current_constraints is None
        ):
            return False
        if current != original or current_constraints != original_constraints:
            self._undo_history.append(
                _DraftState(
                    original,
                    original_constraints,
                    self._drag_original_selection or frozenset(),
                    self.layer_table,
                    self.active_layer_name,
                    history_position=self.history_position,
                    mixed_move=self.mixed_move,
                    pending_cross_tangencies=tuple(self.pending_cross_tangencies),
                    last_polar_entity_id=self._last_polar_entity_id,
                )
            )
            self._advance_history()
            self.entities = list(current)
            self._prune_pending_cross_tangencies(original_entities=original)
            self.constraints = list(current_constraints)
            self._snap_candidates_cache = None
            self.message = "草图控制点已更新；当前约束保持满足，可撤销本次拖动。"
            if self._drag_branch_warning:
                self.message += f" 分支变化：{self._drag_branch_warning}。请核对当前几何。"
        else:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            if not self.message.startswith("拖动无法保持暂存的对象相切"):
                self.message = "控制点未移动；草图保持原样。"
        self._clear_handle_drag()
        self.changed.emit()
        self.update()
        return True

    def set_arc_direction(self, direction: str) -> None:
        self.arc_direction = direction
        self.update()

    def set_construction(self, construction: bool) -> None:
        self.construction = construction

    def set_snapping_enabled(self, enabled: bool) -> None:
        self._snapping_enabled = enabled
        if not enabled:
            self.clear_object_tracking()
        self._snap_kind = ""
        self._refresh_polar_preview()
        self.message = "几何捕捉已启用。" if enabled else "几何捕捉已关闭；当前草图仍可按坐标绘制。"
        self.changed.emit()
        self.update()

    @property
    def acquired_tracking_points(self) -> tuple[Point2D, ...]:
        self._validate_object_tracking()
        return tuple(self._object_tracking_points)

    @property
    def object_tracking_paths(self) -> tuple[tuple[Point2D, Point2D], ...]:
        self._validate_object_tracking()
        return self._object_tracking_paths

    def clear_object_tracking(self) -> None:
        self._object_tracking_points.clear()
        self._object_tracking_paths = ()
        self._object_tracking_vector = None
        self._object_tracking_hover_point = None
        self._object_tracking_history_position = None
        self._object_tracking_source_revision = None
        self.update()

    def _clear_tracking_after_point(self, _point: object) -> None:
        self.clear_object_tracking()

    def set_object_tracking_enabled(self, enabled: bool) -> None:
        self._object_tracking_enabled = enabled
        if not enabled:
            self.clear_object_tracking()
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    def set_object_tracking_use_polar(self, enabled: bool) -> None:
        self._object_tracking_use_polar = enabled
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    def set_object_tracking_shift_to_acquire(self, enabled: bool) -> None:
        self._object_tracking_shift_to_acquire = enabled
        self.clear_object_tracking()
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    def _validate_object_tracking(self) -> None:
        if not self._object_tracking_points:
            return
        if self._object_tracking_history_position != self.history_position or (
            self._object_tracking_source_revision is not None
            and self.source_revision_provider is not None
            and self._object_tracking_source_revision != self.source_revision_provider()
        ):
            self.clear_object_tracking()
            return
        candidates = self._snap_candidates()
        if any(
            not any(_distance(point, candidate) <= 1e-8 for candidate, _ in candidates)
            for point in self._object_tracking_points
        ):
            self.clear_object_tracking()

    def _acquire_object_tracking(self, raw: Point2D) -> None:
        self._validate_object_tracking()
        if (
            self._object_tracking_hover_point is not None
            and _distance(raw, self._object_tracking_hover_point) > _SNAP_RADIUS_PX / self._scale
        ):
            self._object_tracking_hover_point = None
        if (
            not self._object_tracking_enabled
            or not self._snapping_enabled
            or self._last_pointer_shift != self._object_tracking_shift_to_acquire
        ):
            return
        candidates = self._snap_candidates()
        nearest = min(candidates, key=lambda item: _distance(raw, item[0]), default=None)
        if nearest is None or _distance(raw, nearest[0]) > _SNAP_RADIUS_PX / self._scale:
            return
        point = nearest[0]
        if (
            self._object_tracking_hover_point is not None
            and _distance(point, self._object_tracking_hover_point) <= 1e-8
        ):
            return
        self._object_tracking_hover_point = point
        for old in self._object_tracking_points:
            if _distance(point, old) <= 1e-8:
                self._object_tracking_points.remove(old)
                self._object_tracking_paths = ()
                self._object_tracking_vector = None
                self.update()
                return
        self._object_tracking_points.append(point)
        del self._object_tracking_points[:-2]
        self._object_tracking_history_position = self.history_position
        self._object_tracking_source_revision = (
            self.source_revision_provider() if self.source_revision_provider is not None else None
        )

    def _object_tracking_point(self, point: Point2D) -> tuple[Point2D, str] | None:
        self._object_tracking_paths = ()
        self._object_tracking_vector = None
        self._validate_object_tracking()
        if not self._object_tracking_enabled or not self._snapping_enabled:
            return None
        if self._object_tracking_use_polar:
            return self._object_tracking_polar_point(point)
        limit = _SNAP_RADIUS_PX / self._scale
        points = self._object_tracking_points
        if len(points) == 2:
            first, second = points
            intersections = ((first[0], second[1]), (second[0], first[1]))
            intersection = min(intersections, key=lambda candidate: _distance(point, candidate))
            if _distance(point, intersection) <= limit:
                self._object_tracking_paths = ((first, intersection), (second, intersection))
                return intersection, "对象追踪交点"
        paths: list[tuple[float, Point2D, Point2D]] = []
        for reference in points:
            paths.extend(
                (
                    (abs(point[0] - reference[0]), (reference[0], point[1]), reference),
                    (abs(point[1] - reference[1]), (point[0], reference[1]), reference),
                )
            )
        nearest = min(paths, key=lambda item: item[0], default=None)
        if nearest is None or nearest[0] > limit:
            return None
        _, result, reference = nearest
        dx, dy = result[0] - reference[0], result[1] - reference[1]
        distance = math.hypot(dx, dy)
        if distance > 1e-12:
            self._object_tracking_vector = (reference, (dx / distance, dy / distance))
        if self._grid_snapping_enabled and self._polar_snap_enabled and distance > 1e-12:
            spacing = self._polar_snap_spacing or self.grid_spacing_mm()
            snapped = math.floor(distance / spacing + 0.5) * spacing
            result = (
                reference[0] + snapped * dx / distance,
                reference[1] + snapped * dy / distance,
            )
        self._object_tracking_paths = ((reference, result),)
        return result, "对象追踪"

    def _object_tracking_polar_point(self, point: Point2D) -> tuple[Point2D, str] | None:
        limit = _SNAP_RADIUS_PX / self._scale
        base = self._last_polar_segment_angle() if self._polar_relative else 0.0
        increment = self._polar_angle_increment_deg
        rays: list[list[tuple[Point2D, Point2D, float]]] = []
        for reference in self._object_tracking_points:
            dx, dy = point[0] - reference[0], point[1] - reference[1]
            angle = math.degrees(math.atan2(dy, dx)) % 360
            lower = math.floor(((angle - base) % 360) / increment)
            angles = (
                base,
                (base + lower * increment) % 360,
                (base + (lower + 1) * increment) % 360,
                *self._polar_additional_angles,
            )
            candidates: list[tuple[Point2D, Point2D, float]] = []
            for candidate in angles:
                radians = math.radians(candidate)
                direction = (math.cos(radians), math.sin(radians))
                along = dx * direction[0] + dy * direction[1]
                perpendicular = abs(dx * direction[1] - dy * direction[0])
                if along >= 0 and perpendicular <= limit:
                    candidates.append((reference, direction, along))
            rays.append(candidates)
        if len(rays) == 2:
            intersections: list[tuple[float, Point2D, Point2D, Point2D]] = []
            for first, direction_a, _ in rays[0]:
                for second, direction_b, _ in rays[1]:
                    cross = _cross(direction_a, direction_b)
                    if abs(cross) <= 1e-9:
                        continue
                    delta = (second[0] - first[0], second[1] - first[1])
                    along_a = _cross(delta, direction_b) / cross
                    along_b = _cross(delta, direction_a) / cross
                    if along_a < -1e-9 or along_b < -1e-9:
                        continue
                    intersection = (
                        first[0] + along_a * direction_a[0],
                        first[1] + along_a * direction_a[1],
                    )
                    distance = _distance(point, intersection)
                    if distance <= limit:
                        intersections.append((distance, intersection, first, second))
            if intersections:
                _, result, first, second = min(intersections, key=lambda item: item[0])
                self._object_tracking_paths = ((first, result), (second, result))
                return result, "对象追踪交点"
        nearest: tuple[float, Point2D, Point2D, float] | None = None
        for candidates in rays:
            for reference, direction, along in candidates:
                projected = (
                    reference[0] + along * direction[0],
                    reference[1] + along * direction[1],
                )
                distance = _distance(point, projected)
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, reference, direction, along)
        if nearest is None:
            return None
        _, reference, direction, along = nearest
        self._object_tracking_vector = (reference, direction)
        if self._grid_snapping_enabled and self._polar_snap_enabled:
            spacing = self._polar_snap_spacing or self.grid_spacing_mm()
            along = math.floor(along / spacing + 0.5) * spacing
        result = (reference[0] + along * direction[0], reference[1] + along * direction[1])
        self._object_tracking_paths = ((reference, result),)
        return result, "对象追踪"

    def set_orthogonal_enabled(self, enabled: bool) -> None:
        """Constrain unsnapped line/polyline points to the nearest axis."""
        self._orthogonal_enabled = enabled
        if enabled:
            self._polar_tracking_enabled = False
        self._refresh_polar_preview()
        self.message = (
            "正交输入已启用；直线和折线按位移较大的方向锁轴。" if enabled else "正交输入已关闭。"
        )
        self.changed.emit()
        self.update()

    def set_polar_tracking_enabled(self, enabled: bool) -> None:
        self._polar_tracking_enabled = enabled
        if enabled:
            self._orthogonal_enabled = False
        self._refresh_polar_preview()
        self.message = "极轴追踪已启用。" if enabled else "极轴追踪已关闭。"
        self.changed.emit()
        self.update()

    @property
    def snap_preview_available(self) -> bool:
        if self.line_tangent_active:
            return False
        if self._transform_operation in {"move", "copy"}:
            return self._transform_base is not None and not self._transform_selecting
        return self._transform_operation is None and (
            self._first is not None or (self.tool == "多段线" and bool(self._points))
        )

    def set_temporary_snap_disabled(self, disabled: bool) -> None:
        self._last_pointer_shift = disabled
        if disabled:
            self._object_tracking_paths = ()
            self._object_tracking_vector = None
            if (
                self._object_tracking_shift_to_acquire
                and self._last_placement_raw is not None
                and (
                    (
                        self._transform_operation is None
                        and self.tool
                        in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
                    )
                    or (
                        self._transform_operation in {"move", "copy"}
                        and not self._transform_selecting
                    )
                )
            ):
                self._acquire_object_tracking(self._last_placement_raw)
        if self.snap_preview_available:
            self._refresh_polar_preview()

    def set_polar_angle_increment(self, degrees: float) -> None:
        if isinstance(degrees, bool) or not math.isfinite(degrees) or not 0 < degrees <= 360:
            raise ValueError("极轴角度增量必须在 0 到 360 度之间。")
        self._polar_angle_increment_deg = degrees
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    def set_polar_relative(self, enabled: bool) -> None:
        self._polar_relative = enabled
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    def copy_polar_reference_from(self, previous: SketchCanvas) -> None:
        self._last_polar_entity_id = previous._last_polar_entity_id

    @property
    def polar_additional_angles(self) -> tuple[float, ...]:
        return self._polar_additional_angles

    def set_polar_additional_angles(self, angles: tuple[float, ...]) -> None:
        if len(angles) > 10 or any(
            isinstance(angle, bool) or not math.isfinite(angle) or not 0 <= angle < 360
            for angle in angles
        ):
            raise ValueError("附加角度最多 10 个，每个须为 0 到小于 360 的有限数值。")
        self._polar_additional_angles = tuple(dict.fromkeys(angles))
        self._refresh_polar_preview()
        self.changed.emit()
        self.update()

    @property
    def object_tracking_distance_available(self) -> bool:
        self._validate_object_tracking()
        return (
            self._object_tracking_enabled
            and self._snapping_enabled
            and not self._last_pointer_shift
            and self._snap_kind == "对象追踪"
            and self._object_tracking_vector is not None
        )

    def object_tracking_distance_point(self, distance: float) -> Point2D:
        if not self.object_tracking_distance_available or self._object_tracking_vector is None:
            raise ValueError("请先将光标移近一条对象追踪方向。")
        if isinstance(distance, bool) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("对象追踪距离必须是大于零的有限数值。")
        reference, direction = self._object_tracking_vector
        point = (reference[0] + distance * direction[0], reference[1] + distance * direction[1])
        if not all(math.isfinite(coordinate) for coordinate in point):
            raise ValueError("对象追踪距离超出可用范围。")
        return point

    @property
    def _arc_point_tracking(self) -> bool:
        return (
            self.tool == "圆弧"
            and not self.arc_ttr_active
            and (self.arc_creation_mode == "three_point" or self.select_committed_entities)
        )

    @property
    def polar_distance_available(self) -> bool:
        if not self._polar_tracking_enabled or self.line_tangent_active:
            return False
        if self._transform_operation in {"move", "copy"}:
            return self._transform_base is not None and not self._transform_selecting
        return (
            self._transform_operation is None
            and (self.tool in {"直线", "多段线"} or self._arc_point_tracking)
            and self._first is not None
        )

    def polar_distance_point(self, distance: float) -> Point2D:
        if (
            not self.polar_distance_available
            or self._cursor is None
            or not self._snap_kind.startswith("极轴")
        ):
            raise ValueError("请先将光标移近极轴方向。")
        if isinstance(distance, bool) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("极轴距离必须是大于零的有限数值。")
        anchor = (
            self._transform_base
            if self._transform_operation in {"move", "copy"}
            else self._points[-1]
            if (self.tool == "多段线" or self._arc_point_tracking) and self._points
            else self._first
        )
        if anchor is None:
            raise ValueError("请先指定起点。")
        dx, dy = self._cursor[0] - anchor[0], self._cursor[1] - anchor[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            if self._polar_tracking_direction is None:
                raise ValueError("极轴方向无效，请移动光标。")
            dx, dy = self._polar_tracking_direction
        else:
            dx, dy = dx / length, dy / length
        return (anchor[0] + distance * dx, anchor[1] + distance * dy)

    def set_auto_inference_enabled(self, enabled: bool) -> None:
        """Snap near-axis straight lines and retain the inferred relation."""
        self._auto_inference_enabled = enabled
        self.message = (
            "自动关系已启用；接近水平/竖直的直线会吸附并保留关系。"
            if enabled
            else "自动关系已关闭；绘图结果不会自动吸附到水平/竖直方向。"
        )
        self.changed.emit()
        self.update()

    def set_closed_polyline(self, closed: bool) -> None:
        self.closed_polyline = closed

    @property
    def pending_point_count(self) -> int:
        return len(self._points)

    @property
    def pending_last_point(self) -> Point2D | None:
        return self._points[-1] if self._points else None

    @property
    def current_snap_kind(self) -> str:
        return self._snap_kind

    @property
    def hovered_trim_target_id(self) -> str | None:
        """Return the uniquely preselected curve identity while trim is active."""
        return self._hovered_line_edit_entity_id

    @property
    def hovered_line_edit_target_id(self) -> str | None:
        """Return the uniquely preselected entity identity for the active edit tool."""
        return self._hovered_line_edit_entity_id

    @property
    def previewed_line_edit_original(self) -> SketchEntity | None:
        """Return the unmodified entity ghosted by a valid edit preview."""
        return self._line_edit_preview_original

    @property
    def previewed_line_edit_entities(self) -> tuple[SketchEntity, ...]:
        """Return candidate edit entities without applying them to the draft."""
        return self._line_edit_preview_result

    def _trim_target_at(self, point: Point2D, *, lines_only: bool = False) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[SketchEntity, float]] = []
        for entity in self.selectable_entities():
            if isinstance(entity, PointEntity | SplineEntity):
                continue
            if isinstance(entity, LineEntity):
                distance = _distance_to_segment(point, entity.start_mm, entity.end_mm)
            elif isinstance(entity, PolylineEntity):
                if entity.bulges:
                    segments = polyline_curve_segments(
                        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                    )
                    distance = min(
                        _distance_to_arc(point, segment)
                        if isinstance(segment, ArcEntity)
                        else _distance_to_segment(point, segment.start_mm, segment.end_mm)
                        for segment in segments
                    )
                else:
                    points = polyline_sampled_points(entity)
                    distance = min(
                        _distance_to_segment(point, start, end)
                        for start, end in zip(points, points[1:], strict=False)
                    )
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
                )
            elif not lines_only:
                dx, dy = point[0] - entity.center_mm[0], point[1] - entity.center_mm[1]
                radius_distance = math.hypot(dx, dy)
                if isinstance(entity, CircleEntity):
                    distance = abs(radius_distance - entity.radius_mm)
                else:
                    angle = math.degrees(math.atan2(dy, dx))
                    if _angle_on_arc(angle, entity.start_angle_deg, entity.sweep_angle_deg):
                        distance = abs(radius_distance - entity.radius_mm)
                    else:
                        endpoints = tuple(
                            (
                                entity.center_mm[0]
                                + entity.radius_mm * math.cos(math.radians(value)),
                                entity.center_mm[1]
                                + entity.radius_mm * math.sin(math.radians(value)),
                            )
                            for value in (
                                entity.start_angle_deg,
                                entity.start_angle_deg + entity.sweep_angle_deg,
                            )
                        )
                        distance = min(_distance(point, endpoint) for endpoint in endpoints)
            else:
                continue
            if distance <= tolerance:
                candidates.append((entity, distance))
        candidates.sort(key=lambda item: item[1])
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][1] - candidates[0][1]) * self._scale <= 1.0:
            return None
        return candidates[0][0].entity_id

    def _extend_target_at(self, point: Point2D) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[LineEntity | ArcEntity | PolylineEntity, float]] = []
        for entity in self.selectable_entities():
            if isinstance(entity, LineEntity):
                endpoints = (entity.start_mm, entity.end_mm)
            elif isinstance(entity, ArcEntity):
                endpoints = tuple(
                    (
                        entity.center_mm[0] + entity.radius_mm * math.cos(math.radians(angle)),
                        entity.center_mm[1] + entity.radius_mm * math.sin(math.radians(angle)),
                    )
                    for angle in (
                        entity.start_angle_deg,
                        entity.start_angle_deg + entity.sweep_angle_deg,
                    )
                )
            elif isinstance(entity, PolylineEntity) and not entity.closed:
                endpoints = (entity.points_mm[0], entity.points_mm[-1])
            else:
                continue
            candidates.extend(
                (entity, _distance(point, endpoint))
                for endpoint in endpoints
                if _distance(point, endpoint) <= tolerance
            )
        candidates.sort(key=lambda item: item[1])
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][1] - candidates[0][1]) * self._scale <= 1.0:
            return None
        return candidates[0][0].entity_id

    def _clear_line_edit_preview(self) -> None:
        self._line_edit_preview_original = None
        self._line_edit_preview_result = ()

    def _refresh_line_edit_preview(self, mode: str | None) -> None:
        self._clear_line_edit_preview()
        if (
            self.source_revision_provider is not None
            and self.source_context_revision is not None
            and self.source_revision_provider() != self.source_context_revision
        ):
            return
        target_id = self._hovered_line_edit_entity_id
        point = self._cursor
        if mode not in {"修剪", "延伸"} or target_id is None or point is None:
            return
        visible_entities = self.selectable_entities()
        original = next(
            (entity for entity in visible_entities if entity.entity_id == target_id), None
        )
        if original is None:
            return
        saved_layer = next(
            (layer for entity, layer in self.background_entities if entity.entity_id == target_id),
            None,
        )
        if saved_layer is not None:
            if saved_layer.locked:
                return
            try:
                updated_saved = self._edit_visible_geometry(
                    tuple(self.entities), mode, point, target_id
                )
            except ValueError:
                return
            original_ids = {entity.entity_id for entity in visible_entities}
            result = tuple(
                entity
                for entity in updated_saved
                if entity.entity_id == target_id or entity.entity_id not in original_ids
            )
            if result or all(entity.entity_id != target_id for entity in updated_saved):
                self._line_edit_preview_original = original
                self._line_edit_preview_result = result
            return
        if self._layer(original).locked:
            return
        try:
            updated = self._edit_draft_with_boundaries(tuple(self.entities), mode, point, target_id)
            self._line_edit_user_constraints(updated, trim=mode == "修剪")
        except ValueError:
            return
        if updated == tuple(self.entities):
            return
        original_ids = {entity.entity_id for entity in self.entities}
        result = tuple(
            entity
            for entity in updated
            if entity.entity_id == target_id or entity.entity_id not in original_ids
        )
        if result or all(entity.entity_id != target_id for entity in updated):
            self._line_edit_preview_original = original
            self._line_edit_preview_result = result

    def _break_at_point_pick(self, point: Point2D, *, exact_point: bool) -> None:
        if self._break_at_point_target is None:
            identity = self._hit_entity_at(point)
            if identity is None:
                self.message = "请选择唯一的直线、圆弧或开放多段线。"
            else:
                self._break_at_point_target = identity
                self.message = "单点打断：指定打断点。"
            self.changed.emit()
            self.update()
            return
        identity = self._break_at_point_target
        draft = next((entity for entity in self.entities if entity.entity_id == identity), None)
        saved = (
            next(
                (
                    (entity, layer)
                    for entity, layer in self.background_entities
                    if entity.entity_id == identity
                ),
                None,
            )
            if self.select_committed_entities
            else None
        )
        target = draft if draft is not None else saved[0] if saved is not None else None
        if target is None:
            self.message = "目标已变化；请重新选择。"
            self._break_at_point_target = None
        elif (
            (layer := self._layer(target) if draft is not None else saved[1] if saved else None)
            is None
            or layer.locked
            or not layer.displayed
        ):
            self.message = "目标图元所在图层已锁定、隐藏或冻结；草图未修改。"
        else:
            updated: tuple[SketchEntity, ...] = ()
            revised_constraints: tuple[SketchConstraint, ...] = ()
            try:
                break_point = point if exact_point else self._placement_point(point)[0]
                fragments = break_entity_at_point(target, break_point)
                if draft is not None:
                    updated = tuple(
                        item
                        for entity in self.entities
                        for item in (fragments if entity.entity_id == identity else (entity,))
                    )
                    revised_constraints = self._line_edit_user_constraints(
                        updated, trim=True, allow_split_lines=True, allow_split_arcs=True
                    )
            except ValueError as exc:
                self.message = str(exc)
            else:
                self.point_accepted.emit(break_point)
                removed_relations = 0
                if draft is None:
                    self._break_at_point_target = None
                    self.set_tool("选择元素")
                    self.message = "正在校验单点打断。"
                    self.changed.emit()
                    self.update()
                    self.committed_line_edit_requested.emit("单点打断", identity, fragments)
                    return
                original = tuple(self.entities)
                self._record_undo()
                self.entities = list(updated)
                self.constraints = list(revised_constraints)
                if isinstance(target, LineEntity | ArcEntity):
                    pending: list[DraftTangentPair] = []
                    pending_removed = 0
                    for source, draft_ref_or_endpoint in self.pending_cross_tangencies:
                        draft_ref = draft_tangent_reference(draft_ref_or_endpoint)
                        if draft_ref.entity_id != identity:
                            pending.append((source, draft_ref_or_endpoint))
                            continue
                        try:
                            sources = self._pending_source_curves(draft_tangent_reference(source))
                            source_endpoint = (
                                source.endpoint
                                if isinstance(source, DraftConnectedEndpoint)
                                else None
                            )
                            draft_endpoint = (
                                draft_ref_or_endpoint.endpoint
                                if isinstance(draft_ref_or_endpoint, DraftConnectedEndpoint)
                                else None
                            )
                            matches = [
                                fragment
                                for fragment in fragments
                                if isinstance(fragment, LineEntity | ArcEntity)
                                and len(sources) == 1
                                and tangent_on_curves(sources[0], fragment)
                                and tangent_endpoints_satisfied(
                                    sources[0], fragment, source_endpoint, draft_endpoint
                                )
                            ]
                            if len(matches) != 1:
                                raise ValueError("相切片段不唯一。")
                            rebound_ref = replace(draft_ref, entity_id=matches[0].entity_id)
                            rebound = (
                                replace(draft_ref_or_endpoint, reference=rebound_ref)
                                if isinstance(draft_ref_or_endpoint, DraftConnectedEndpoint)
                                else rebound_ref
                            )
                            pending.append((source, rebound))
                        except (KeyError, ValueError, IndexError):
                            pending_removed += 1
                    self.pending_cross_tangencies = pending
                    if pending_removed:
                        position = self.history_position
                        self._pending_tangency_removal_notices[position] = (
                            self._pending_tangency_removal_notices.get(position, 0)
                            + pending_removed
                        )
                self._prune_pending_cross_tangencies(original_entities=original)
                if isinstance(target, LineEntity | ArcEntity):
                    by_id = {entity.entity_id: entity for entity in updated}
                    retained: list[SketchConstraint] = []
                    for constraint in self.constraints:
                        indices = [
                            i
                            for i, ref in enumerate(constraint.references)
                            if ref.entity_id == identity
                        ]
                        if (
                            constraint.source != "inferred"
                            or constraint.kind != "tangent"
                            or len(indices) != 1
                        ):
                            retained.append(constraint)
                            continue
                        index = indices[0]
                        try:
                            other_ref = constraint.references[1 - index]
                            other = tangent_entity_curve(
                                by_id[other_ref.entity_id], other_ref.index
                            )
                            matches: list[LineEntity | ArcEntity] = []
                            for fragment in fragments:
                                if not isinstance(fragment, LineEntity | ArcEntity):
                                    continue
                                curves = (fragment, other) if index == 0 else (other, fragment)
                                if tangent_on_curves(*curves) and tangent_endpoints_satisfied(
                                    *curves,
                                    constraint.first_endpoint,
                                    constraint.second_endpoint,
                                ):
                                    matches.append(fragment)
                            if len(matches) == 1:
                                refs = list(constraint.references)
                                refs[index] = replace(refs[index], entity_id=matches[0].entity_id)
                                retained.append(replace(constraint, references=tuple(refs)))
                            else:
                                removed_relations += 1
                        except (KeyError, ValueError, IndexError):
                            removed_relations += 1
                    self.constraints = retained
                if isinstance(target, PolylineEntity):
                    by_id = {entity.entity_id: entity for entity in updated}
                    retained_polyline: list[SketchConstraint] = []
                    polyline_fragments = tuple(
                        fragment for fragment in fragments if isinstance(fragment, PolylineEntity)
                    )
                    for constraint in self.constraints:
                        indices = [
                            i
                            for i, ref in enumerate(constraint.references)
                            if ref.entity_id == identity
                            and ref.kind == "segment"
                            and ref.index is not None
                        ]
                        if (
                            constraint.source != "inferred"
                            or constraint.kind != "tangent"
                            or len(indices) != 1
                        ):
                            retained_polyline.append(constraint)
                            continue
                        index = indices[0]
                        try:
                            ref = constraint.references[index]
                            other_ref = constraint.references[1 - index]
                            other = tangent_entity_curve(
                                by_id[other_ref.entity_id], other_ref.index
                            )
                            if ref.index is None:
                                raise ValueError("相切段索引无效。")
                            match = unique_retained_tangent_fragment(
                                target, polyline_fragments, ref.index, other
                            )
                            if match is None:
                                raise ValueError("相切片段不唯一。")
                            refs = list(constraint.references)
                            refs[index] = replace(ref, entity_id=match[0], index=match[1])
                            curve = tangent_entity_curve(by_id[match[0]], match[1])
                            curves = (curve, other) if index == 0 else (other, curve)
                            if not tangent_endpoints_satisfied(
                                *curves, constraint.first_endpoint, constraint.second_endpoint
                            ):
                                raise ValueError("相切端点无法保留。")
                            retained_polyline.append(replace(constraint, references=tuple(refs)))
                        except (KeyError, ValueError, IndexError):
                            removed_relations += 1
                    self.constraints = retained_polyline
                removed_relations += self._preserve_satisfied_relations(
                    updated, original_entities=original
                )
                self._snap_candidates_cache = None
                self._break_at_point_target = None
                self.set_tool("选择元素")
                self.message = "单点打断完成；两个片段已生成。"
                if removed_relations:
                    self.message += f" 已移除 {removed_relations} 条失效的自动关系；可撤销。"
        self.changed.emit()
        self.update()

    def add_coordinate_point(self, point: Point2D, *, exact_point: bool = False) -> None:
        """Add a point; explicit numeric input bypasses snap and inference."""
        if self.tool == "单点打断":
            self._break_at_point_pick(point, exact_point=exact_point)
            return
        if self.clipboard_paste_active:
            self._place_clipboard(point)
            return
        if self.dynamic_click_guard is not None and not self.dynamic_click_guard():
            self.message = "请先修正光标尺寸输入，或按 Esc 取消。"
            self.changed.emit()
            return
        if self.arc_ttr_active:
            self._pick_arc_ttr_source(point)
        elif self.line_tangent_active:
            if not self._line_tangent_awaiting and not exact_point:
                point, self._snap_kind = self._placement_point(point)
            self._pick_line_tangent_source(point)
        elif self._trim_fence_active:
            self._add_trim_fence_point(point)
        else:
            self._accept_point(point, exact_point=exact_point)

    def refresh_dynamic_preview(self) -> None:
        if self._last_placement_raw is None or (
            self._first is None and not (self.tool == "多段线" and self._points)
        ):
            return
        point, self._snap_kind = self._placement_point(
            self._last_placement_raw, temporarily_disable_snapping=self._last_pointer_shift
        )
        if self.dynamic_point_resolver is not None and self._first is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, point)
                if resolved != point:
                    self._snap_kind = ""
                point = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
                return
        self._cursor = point
        self.cursor_changed.emit(*point, self._snap_kind)
        self.update()

    def _refresh_polar_preview(self) -> None:
        if self._last_placement_raw is None:
            return
        if self._transform_operation in {"move", "copy"} and self._transform_base is not None:
            point, kind = self._transform_pointer_point(
                self._last_placement_raw, disable_snapping=self._last_pointer_shift
            )
            self._cursor, self._snap_kind = point, kind
            self._transform_point(point, commit=False)
            self.cursor_changed.emit(*point, kind)
            self.update()
        elif self._transform_operation is None and self.tool in {
            "直线",
            "多段线",
            "圆",
            "圆弧",
            "矩形",
            "多边形",
            "样条曲线",
        }:
            self.refresh_dynamic_preview()

    def set_polyline_arc_mode(self, enabled: bool) -> None:
        if self.tool != "多段线" or not self._points:
            self.message = "多段线：请先指定起点。"
        else:
            self.polyline_arc_mode = enabled
            self._polyline_arc_middle = None
            self._polyline_arc_second_pending = False
            self._reset_polyline_arc_option()
            self.message = (
                "多段线圆弧：指定终点；A 角度、CE 圆心、R 半径、S 第二点、L 直线、U 撤销、C 闭合。"
                if enabled
                else "多段线直线：指定下一点；A 圆弧，U 撤销，C 闭合。"
            )
        self.changed.emit()
        self.update()

    def _reset_polyline_arc_option(self) -> None:
        self.polyline_arc_stage = ""
        self._polyline_arc_radius = None
        self._polyline_arc_angle = None
        self._polyline_arc_center = None

    def begin_polyline_arc_option(self, option: str) -> None:
        self._reset_polyline_arc_option()
        self._polyline_arc_middle = None
        self._polyline_arc_second_pending = False
        self.polyline_arc_stage = option
        self.message = {
            "radius": "多段线圆弧：输入半径。",
            "angle": "多段线圆弧：输入夹角（度，正为逆时针）。",
            "center": "多段线圆弧：指定圆心。",
        }[option]
        self.changed.emit()
        self.update()

    def set_polyline_arc_number(self, value: float) -> bool:
        if not math.isfinite(value):
            self.message = "请输入有限数值。"
        elif self.polyline_arc_stage == "radius" and value > 0:
            self._polyline_arc_radius = value
            self.polyline_arc_stage = ""
            self.message = "多段线圆弧：指定终点（半径方式）。"
        elif self.polyline_arc_stage == "angle" and 1e-8 < abs(value) < 360:
            self._polyline_arc_angle = value
            self.polyline_arc_stage = ""
            self.message = "多段线圆弧：指定终点（夹角方式）。"
        else:
            self.message = "半径须大于零；夹角须非零且绝对值小于 360°。"
        self.changed.emit()
        self.update()
        return not self.polyline_arc_stage

    def begin_polyline_arc_second_point(self) -> None:
        if self.tool == "多段线" and self.polyline_arc_mode and self._points:
            self._reset_polyline_arc_option()
            self._polyline_arc_middle = None
            self._polyline_arc_second_pending = True
            self.message = "多段线圆弧：指定圆弧上的第二点。"
            self.changed.emit()
            self.update()

    def undo_polyline_segment(self) -> None:
        if self.polyline_arc_stage or any(
            item is not None
            for item in (
                self._polyline_arc_center,
                self._polyline_arc_radius,
                self._polyline_arc_angle,
            )
        ):
            self._reset_polyline_arc_option()
            self.message = "已取消当前圆弧选项。"
        elif self._polyline_arc_middle is not None:
            self._polyline_arc_middle = None
            self._polyline_arc_second_pending = True
            self.message = "已撤销圆弧第二点；请重新指定。"
        elif self._polyline_arc_second_pending:
            self._polyline_arc_second_pending = False
            self.message = "已取消第二点输入；可指定圆弧终点。"
        elif self._polyline_bulges:
            self._points.pop()
            self._polyline_bulges.pop()
            self.message = "已撤销上一段多段线；可继续绘制。"
        else:
            self.message = "没有可撤销的多段线段。"
        self.changed.emit()
        self.update()

    def _polyline_arc_bulge(self, endpoint: Point2D) -> float:
        start = self._points[-1]
        if self._polyline_arc_middle is not None:
            arc = self._three_point_arc(start, self._polyline_arc_middle, endpoint, uuid4().hex)
            return math.tan(math.radians(arc.sweep_angle_deg) / 4)
        if self._polyline_arc_center is not None:
            center = self._polyline_arc_center
            if not math.isclose(
                math.dist(start, center), math.dist(endpoint, center), rel_tol=1e-9, abs_tol=1e-8
            ):
                raise ValueError("圆弧终点不在指定的圆上。")
            first = math.atan2(start[1] - center[1], start[0] - center[0])
            last = math.atan2(endpoint[1] - center[1], endpoint[0] - center[0])
            sweep = (last - first) % (2 * math.pi)
            if sweep <= 1e-10 or sweep >= 2 * math.pi - 1e-10:
                raise ValueError("圆弧终点不能与起点方向重合。")
            return math.tan(sweep / 4)
        if self._polyline_arc_angle is not None:
            return math.tan(math.radians(self._polyline_arc_angle) / 4)
        if self._polyline_arc_radius is not None:
            chord = math.dist(start, endpoint)
            ratio = chord / (2 * self._polyline_arc_radius)
            if not math.isfinite(ratio) or ratio <= 1e-12 or ratio > 1 + 1e-10:
                raise ValueError("圆弧弦长须大于零且不超过直径。")
            return math.tan(math.asin(min(1.0, ratio)) / 2)
        if self._polyline_bulges:
            previous = self._points[-2]
            last_bulge = self._polyline_bulges[-1]
            if last_bulge:
                previous_arc = bulge_arc(previous, start, last_bulge, uuid4().hex)
                angle = math.radians(previous_arc.start_angle_deg + previous_arc.sweep_angle_deg)
                sign = 1 if previous_arc.sweep_angle_deg > 0 else -1
                tangent = (-math.sin(angle) * sign, math.cos(angle) * sign)
            else:
                length = math.dist(previous, start)
                tangent = ((start[0] - previous[0]) / length, (start[1] - previous[1]) / length)
        else:
            tangent = (1.0, 0.0)
        dx, dy = endpoint[0] - start[0], endpoint[1] - start[1]
        chord = math.hypot(dx, dy)
        if not math.isfinite(chord) or chord <= 1e-9:
            raise ValueError("圆弧段端点必须不同且坐标有限。")
        angle = math.atan2(tangent[0] * dy - tangent[1] * dx, tangent[0] * dx + tangent[1] * dy)
        bulge = math.tan(angle / 2)
        if not math.isfinite(bulge) or abs(bulge) <= 1e-12 or abs(angle) >= math.pi - 1e-10:
            raise ValueError("无法由当前切向和终点确定圆弧；请选择其他终点或使用 S。")
        bulge_arc(start, endpoint, bulge, uuid4().hex)
        return bulge

    def _polyline_arc_project_endpoint(self, point: Point2D) -> Point2D:
        if self._polyline_arc_center is None:
            return point
        center = self._polyline_arc_center
        radius = math.dist(self._points[-1], center)
        distance = math.dist(point, center)
        if distance <= 1e-9:
            raise ValueError("终点方向不能与圆心重合。")
        return (
            center[0] + (point[0] - center[0]) * radius / distance,
            center[1] + (point[1] - center[1]) * radius / distance,
        )

    def finish_polyline(self, *, close: bool = False) -> None:
        if self.tool == "样条曲线":
            self.finish_spline()
            return
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或已锁定，无法创建图元。"
            self.changed.emit()
            return
        if len(self._points) < 2:
            self.message = "多段线至少需要两个点。"
            self.changed.emit()
            return
        points = list(self._points)
        closed = close or self.closed_polyline
        if (
            self._polyline_arc_second_pending
            or (self._polyline_arc_middle is not None and not close)
            or self.polyline_arc_stage
        ):
            self.message = "请先完成圆弧段，或用 U 撤销第二点。"
            self.changed.emit()
            return
        bulges = list(self._polyline_bulges)
        if closed and points[-1] == points[0]:
            points.pop()
        try:
            if closed:
                bulges.append(
                    self._polyline_arc_bulge(points[0]) if self.polyline_arc_mode else 0.0
                )
            entity = PolylineEntity(
                uuid4().hex,
                tuple(points),
                closed=closed,
                construction=self.construction,
                layer_name=self.active_layer_name,
                bulges=tuple(bulges),
            )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        self._record_undo()
        self.entities.append(entity)
        self._last_polar_entity_id = entity.entity_id
        self.constraints.extend(self._inferred_constraints_for_entity(entity))
        self._snap_candidates_cache = None
        self._points.clear()
        self._polyline_bulges.clear()
        self.polyline_arc_mode = False
        self._polyline_arc_middle = None
        self._polyline_arc_second_pending = False
        self._reset_polyline_arc_option()
        self.message = "多段线已加入草稿。"
        self.changed.emit()
        self.update()

    def finish_spline(self) -> None:
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或锁定，无法完成样条。"
            self.changed.emit()
            return
        try:
            entity = SplineEntity(
                uuid4().hex, tuple(self._points), self.construction, self.active_layer_name
            )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        self._record_undo()
        self.entities.append(entity)
        self._points.clear()
        self._first = None
        self._snap_candidates_cache = None
        self.message = "三次 B 样条已加入草稿；选择后可拖动控制点。"
        self.changed.emit()
        self.update()

    def undo_last_operation(self) -> bool:
        if not self.can_undo:
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self.message = "已撤销上一项草稿操作。"
        self.changed.emit()
        self.update()
        return True

    def mixed_draft_history_matches(self, before: int, after: int, *, redo: bool) -> bool:
        """Check that a linked document/draft operation remains at the history tip."""
        if redo:
            return (
                self.history_position == before
                and bool(self._redo_history)
                and self._redo_history[-1].history_position == after
            )
        return (
            self.history_position == after
            and bool(self._undo_history)
            and self._undo_history[-1].history_position == before
        )

    def undo_mixed_draft_copy(self, before: int, after: int) -> bool:
        """Restore the draft half while the repeated COPY command remains active."""
        if not self.mixed_draft_history_matches(before, after, redo=False):
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self.changed.emit()
        self.update()
        return True

    def undo_line_edit_action(self) -> bool:
        """Undo only the latest draft operation recorded by this line-edit command."""
        if self.has_active_edit_gesture:
            self.message = "请先完成或取消当前围栏，再撤销。"
            self.changed.emit()
            return False
        if (
            not self._line_edit_undo_actions
            or self._line_edit_undo_actions[-1][1] != self.history_position
        ):
            self.message = "当前命令没有可撤销的草稿编辑，或草稿历史已变化。"
            self.changed.emit()
            return False
        kind, _position, identity, revision = self._line_edit_undo_actions[-1]
        if kind == "saved":
            self.saved_line_edit_undo_requested.emit(identity, self.history_position, revision)
            return True
        if not self.undo_last_operation():
            return False
        self._line_edit_undo_actions.pop()
        self.message = "已撤销当前命令的上一项编辑；可继续选择对象。"
        self.changed.emit()
        return True

    def record_saved_line_edit(self, identity: str, revision: int) -> None:
        if self.tool in {"修剪", "延伸", "二维倒角", "二维圆角"}:
            self._line_edit_undo_actions.append(
                ("saved", self.history_position, identity, revision)
            )

    def finish_saved_line_edit_undo(
        self, identity: str, previous_identity: str | None, revision: int
    ) -> None:
        if self._line_edit_undo_actions and self._line_edit_undo_actions[-1][:3] == (
            "saved",
            self.history_position,
            identity,
        ):
            self._line_edit_undo_actions.pop()
            if (
                self._line_edit_undo_actions
                and self._line_edit_undo_actions[-1][0] == "saved"
                and self._line_edit_undo_actions[-1][2] == previous_identity
            ):
                kind, position, previous, _revision = self._line_edit_undo_actions[-1]
                self._line_edit_undo_actions[-1] = (kind, position, previous, revision)
            self.message = "已撤销当前命令的上一项编辑；可继续选择对象。"
            self.changed.emit()

    def discard_redo_history(self) -> None:
        """A new document command abandons future operations on the draft branch."""
        self._redo_history.clear()
        self.changed.emit()

    def redo_last_operation(self) -> bool:
        if not self.can_redo:
            return False
        self._undo_history.append(self._draft_state())
        self._restore_draft_state(self._redo_history.pop())
        self.message = "已重做上一项草稿操作。"
        self.changed.emit()
        self.update()
        return True

    def _segments(self) -> list[tuple[Point2D, Point2D]]:
        segments: list[tuple[Point2D, Point2D]] = []
        for entity in self.visible_snap_entities():
            if isinstance(entity, LineEntity):
                segments.append((entity.start_mm, entity.end_mm))
            elif isinstance(entity, PolylineEntity):
                if entity.bulges:
                    segments.extend(
                        (segment.start_mm, segment.end_mm)
                        for segment in polyline_curve_segments(
                            entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                        )
                        if isinstance(segment, LineEntity)
                    )
                else:
                    segments.extend(zip(entity.points_mm, entity.points_mm[1:], strict=False))
                    if entity.closed:
                        segments.append((entity.points_mm[-1], entity.points_mm[0]))
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                segments.extend(zip(corners, (*corners[1:], corners[0]), strict=True))
        return segments

    def _snap_candidates(self) -> list[tuple[Point2D, str]]:
        if self._snap_candidates_cache is not None:
            return list(self._snap_candidates_cache)
        candidates: list[tuple[Point2D, str]] = []
        segments = self._segments()
        circular_curves: list[tuple[Point2D, float, float, float]] = []
        for entity in self.visible_snap_entities():
            if isinstance(entity, PointEntity):
                candidates.append((entity.position_mm, "点"))
            elif isinstance(entity, SplineEntity):
                candidates.extend(
                    ((entity.control_points_mm[0], "端点"), (entity.control_points_mm[-1], "端点"))
                )
            elif isinstance(entity, LineEntity):
                candidates.extend(
                    (
                        (entity.start_mm, "端点"),
                        (entity.end_mm, "端点"),
                        (
                            (
                                (entity.start_mm[0] + entity.end_mm[0]) / 2.0,
                                (entity.start_mm[1] + entity.end_mm[1]) / 2.0,
                            ),
                            "中点",
                        ),
                    )
                )
            elif isinstance(entity, PolylineEntity):
                candidates.extend((point, "端点") for point in entity.points_mm)
                if entity.bulges:
                    for segment in polyline_curve_segments(
                        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                    ):
                        if isinstance(segment, ArcEntity):
                            circular_curves.append(
                                (
                                    segment.center_mm,
                                    segment.radius_mm,
                                    segment.start_angle_deg,
                                    segment.sweep_angle_deg,
                                )
                            )
                            candidates.append((segment.center_mm, "圆心"))
                            angle = math.radians(
                                segment.start_angle_deg + segment.sweep_angle_deg / 2
                            )
                            candidates.append(
                                (
                                    (
                                        segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                                        segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                                    ),
                                    "中点",
                                )
                            )
            elif isinstance(entity, CircleEntity | ArcEntity):
                candidates.append((entity.center_mm, "圆心"))
                if isinstance(entity, ArcEntity):
                    circular_curves.append(
                        (
                            entity.center_mm,
                            entity.radius_mm,
                            entity.start_angle_deg,
                            entity.sweep_angle_deg,
                        )
                    )
                    for angle in (
                        entity.start_angle_deg,
                        entity.start_angle_deg + entity.sweep_angle_deg,
                    ):
                        radians = math.radians(angle)
                        candidates.append(
                            (
                                (
                                    entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                                    entity.center_mm[1] + entity.radius_mm * math.sin(radians),
                                ),
                                "端点",
                            )
                        )
                else:
                    circular_curves.append((entity.center_mm, entity.radius_mm, 0.0, 360.0))
            else:
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                candidates.extend((point, "端点") for point in corners)
                candidates.append((((x1 + x2) / 2.0, (y1 + y2) / 2.0), "中心"))
        for first_index, (start, end) in enumerate(segments):
            candidates.append((((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0), "中点"))
            vector_a = (end[0] - start[0], end[1] - start[1])
            for other_start, other_end in segments[first_index + 1 :]:
                vector_b = (
                    other_end[0] - other_start[0],
                    other_end[1] - other_start[1],
                )
                divisor = _cross(vector_a, vector_b)
                if abs(divisor) <= 1e-12:
                    continue
                delta = (other_start[0] - start[0], other_start[1] - start[1])
                first_ratio = _cross(delta, vector_b) / divisor
                second_ratio = _cross(delta, vector_a) / divisor
                if 0.0 <= first_ratio <= 1.0 and 0.0 <= second_ratio <= 1.0:
                    candidates.append(
                        (
                            (
                                start[0] + first_ratio * vector_a[0],
                                start[1] + first_ratio * vector_a[1],
                            ),
                            "交点",
                        )
                    )
        for start, end in segments:
            for center, radius, start_angle, sweep_angle in circular_curves:
                for point in _segment_circle_intersections(start, end, center, radius):
                    angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
                    if _angle_on_arc(angle, start_angle, sweep_angle):
                        candidates.append((point, "交点"))
        for index, first_curve in enumerate(circular_curves):
            for second_curve in circular_curves[index + 1 :]:
                points = _circle_circle_intersections(
                    first_curve[0], first_curve[1], second_curve[0], second_curve[1]
                )
                for point in points:
                    first_angle = math.degrees(
                        math.atan2(point[1] - first_curve[0][1], point[0] - first_curve[0][0])
                    )
                    second_angle = math.degrees(
                        math.atan2(point[1] - second_curve[0][1], point[0] - second_curve[0][0])
                    )
                    if _angle_on_arc(first_angle, first_curve[2], first_curve[3]) and _angle_on_arc(
                        second_angle, second_curve[2], second_curve[3]
                    ):
                        candidates.append((point, "交点"))
        self._snap_candidates_cache = tuple(candidates)
        return candidates

    def apply_constraint_solution(self, original: Sketch, solved: Sketch) -> bool:
        """Apply one isolated solve atomically as a locally undoable draft edit."""
        if (
            tuple(self.entities) != original.entities
            or tuple(self.constraints) != original.constraints
        ):
            return False
        self._record_undo()
        self.entities = list(solved.entities)
        self._prune_pending_cross_tangencies(original_entities=original.entities)
        self.constraints = list(solved.constraints)
        self._snap_candidates_cache = None
        self.message = "尺寸已应用到草稿；可撤销。完成草图后写入文档。"
        self.changed.emit()
        self.update()
        return True

    def configure_polygon(self, sides: int, *, circumscribed: bool) -> None:
        if not 3 <= sides <= 128:
            raise ValueError("正多边形边数须为 3–128。")
        self.polygon_sides = sides
        self.polygon_circumscribed = circumscribed
        self.update()

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        self.update()

    def grid_spacing_mm(self) -> float:
        base = 10.0 ** math.floor(math.log10(24.0 / self._scale))
        return next(step * base for step in (1, 2, 5, 10) if step * base * self._scale >= 24)

    def set_grid_snapping_enabled(self, enabled: bool) -> None:
        self._grid_snapping_enabled = enabled
        self._refresh_polar_preview()
        self.update()

    def set_polar_snap_enabled(self, enabled: bool) -> None:
        self._polar_snap_enabled = enabled
        self._refresh_polar_preview()
        self.update()

    def set_polar_snap_spacing(self, spacing: float) -> None:
        if isinstance(spacing, bool) or not math.isfinite(spacing) or spacing < 0:
            raise ValueError("极轴捕捉距离必须为非负有限数值。")
        self._polar_snap_spacing = spacing
        self._refresh_polar_preview()
        self.update()

    def _snapped(self, point: Point2D) -> tuple[Point2D, str]:
        self._object_tracking_paths = ()
        self._object_tracking_vector = None
        snap_limit = _SNAP_RADIUS_PX / self._scale
        candidates = self._snap_candidates() if self._snapping_enabled else []
        if self._snapping_enabled and self.can_close_chain:
            start = self._points[0]
            if _distance(point, start) <= snap_limit:
                return start, "闭合首点"
        anchor = self._points[-1] if self.tool == "多段线" and self._points else self._first
        if self.tool == "直线" and self._first is not None:
            anchor = self._first
        if self._snapping_enabled and anchor is not None and self.tool in {"直线", "多段线"}:
            candidates.extend(self._reference_snap_candidates(anchor))
        if (
            self._snapping_enabled
            and self._first is not None
            and (
                (self.tool == "圆" and not self.circle_ttr_active)
                or (self.tool == "圆弧" and self.arc_creation_mode == "center")
            )
        ):
            candidates.extend(self._center_tangent_snap_candidates())
        if (
            self._snapping_enabled
            and self.tool == "圆弧"
            and self.arc_creation_mode == "three_point"
            and len(self._points) == 2
        ):
            candidates.extend(
                (contact, "切点")
                for start, end in self._segments()
                for contact in tangent_endpoints_to_line(
                    self._points[0], self._points[1], start, end
                )
            )
            for curve in self._visible_circular_curves():
                for contact in tangent_endpoints_to_circle(
                    self._points[0], self._points[1], curve.center_mm, curve.radius_mm
                ):
                    angle = math.degrees(
                        math.atan2(contact[1] - curve.center_mm[1], contact[0] - curve.center_mm[0])
                    )
                    if isinstance(curve, ArcEntity) and not _angle_on_arc(
                        angle, curve.start_angle_deg, curve.sweep_angle_deg
                    ):
                        continue
                    candidates.append((contact, "切点"))
        nearest = min(
            candidates,
            key=lambda candidate: (
                _distance(point, candidate[0]),
                _SNAP_PRIORITY.get(candidate[1], len(_SNAP_PRIORITY)),
            ),
            default=None,
        )
        if nearest is not None and _distance(point, nearest[0]) <= snap_limit:
            return nearest
        if self._snapping_enabled and _distance(point, (0.0, 0.0)) <= snap_limit:
            return (0.0, 0.0), "UCS 原点"
        tracked = self._object_tracking_point(point)
        if tracked is not None:
            return tracked
        if self._grid_snapping_enabled and not self._polar_snap_enabled:
            step = self.grid_spacing_mm()
            grid_point = (round(point[0] / step) * step, round(point[1] / step) * step)
            if _distance(point, grid_point) <= snap_limit:
                return grid_point, "栅格"
        return point, ""

    def snap_measurement_point(self, point: Point2D) -> Point2D:
        """Apply current object and grid snap modes to a measured point."""
        return self._snapped(point)[0]

    def set_area_preview(
        self, points: tuple[Point2D, ...], cursor: Point2D | None = None, *, subtract: bool = False
    ) -> None:
        """Display the transient AREA boundary without adding drawing entities."""
        self._area_preview_points = points
        self._area_preview_cursor = cursor
        self._area_preview_subtract = subtract
        self.update()

    def set_zoom_window_preview(self, first: Point2D | None, cursor: QPointF | None = None) -> None:
        """Show a transient window using a drawing anchor and screen cursor."""
        self._zoom_window_first = first
        self._zoom_window_cursor = QPointF(cursor) if cursor is not None else None
        self.update()

    def update_dimension_snap_preview(self, point: Point2D, *, show_snap: bool) -> None:
        """Update the standard cursor and snap marker while picking dimension references."""
        self._cursor, self._snap_kind = self._snapped(point) if show_snap else (point, "")
        self.cursor_changed.emit(*self._cursor, self._snap_kind)
        self.update()

    def clear_dimension_snap_preview(self) -> None:
        """Remove the snap marker after a dimension pick or cancellation."""
        self._snap_kind = ""
        if self._cursor is not None:
            self.cursor_changed.emit(*self._cursor, "")
        self.update()

    def _visible_circular_curves(self) -> Iterable[CircleEntity | ArcEntity]:
        """Yield visible circular entities and arc segments in polylines."""
        for entity in self.visible_snap_entities():
            if isinstance(entity, CircleEntity | ArcEntity):
                yield entity
            elif isinstance(entity, PolylineEntity) and entity.bulges:
                for segment in polyline_curve_segments(
                    entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                ):
                    if isinstance(segment, ArcEntity):
                        yield segment

    def _center_tangent_snap_candidates(self) -> list[tuple[Point2D, str]]:
        """Find tangent contacts for a circle or arc with a specified center."""
        center = self._first
        if center is None:
            return []
        fixed_radius = (
            _distance(center, self._points[1])
            if self.tool == "圆弧" and len(self._points) >= 2
            else None
        )
        candidates: list[tuple[Point2D, str]] = []

        def append_if_compatible(point: Point2D) -> None:
            radius = _distance(center, point)
            if radius <= 1e-9:
                return
            if fixed_radius is not None and not math.isclose(
                radius, fixed_radius, rel_tol=1e-9, abs_tol=1e-8
            ):
                return
            candidates.append((point, "切点"))

        for start, end in self._segments():
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_squared = dx * dx + dy * dy
            if length_squared <= 1e-24:
                continue
            fraction = ((center[0] - start[0]) * dx + (center[1] - start[1]) * dy) / length_squared
            if 0 <= fraction <= 1:
                append_if_compatible((start[0] + fraction * dx, start[1] + fraction * dy))

        for curve in self._visible_circular_curves():
            dx, dy = center[0] - curve.center_mm[0], center[1] - curve.center_mm[1]
            length = math.hypot(dx, dy)
            if length <= 1e-12:
                continue
            for sign in (-1, 1):
                point = (
                    curve.center_mm[0] + sign * curve.radius_mm * dx / length,
                    curve.center_mm[1] + sign * curve.radius_mm * dy / length,
                )
                angle = math.degrees(
                    math.atan2(point[1] - curve.center_mm[1], point[0] - curve.center_mm[0])
                )
                if isinstance(curve, ArcEntity) and not _angle_on_arc(
                    angle, curve.start_angle_deg, curve.sweep_angle_deg
                ):
                    continue
                append_if_compatible(point)
        return candidates

    def _reference_snap_candidates(self, anchor: Point2D) -> list[tuple[Point2D, str]]:
        """Find feet and curve tangencies from the current line endpoint."""
        candidates: list[tuple[Point2D, str]] = []
        for start, end in self._segments():
            delta = (end[0] - start[0], end[1] - start[1])
            length_squared = delta[0] ** 2 + delta[1] ** 2
            if length_squared <= 1e-24:
                continue
            ratio = (
                (anchor[0] - start[0]) * delta[0] + (anchor[1] - start[1]) * delta[1]
            ) / length_squared
            if 0.0 <= ratio <= 1.0:
                candidates.append(
                    (
                        (start[0] + ratio * delta[0], start[1] + ratio * delta[1]),
                        "垂足",
                    )
                )

        for entity in self._visible_circular_curves():
            center = entity.center_mm
            radius = entity.radius_mm
            start_angle, sweep_angle = (
                (entity.start_angle_deg, entity.sweep_angle_deg)
                if isinstance(entity, ArcEntity)
                else (0.0, 360.0)
            )
            delta_x, delta_y = anchor[0] - center[0], anchor[1] - center[1]
            distance = math.hypot(delta_x, delta_y)
            if distance <= radius + 1e-12:
                continue
            center_angle = math.degrees(math.atan2(delta_y, delta_x))
            tangent_offset = math.degrees(math.acos(radius / distance))
            for angle in (center_angle + tangent_offset, center_angle - tangent_offset):
                if not _angle_on_arc(angle, start_angle, sweep_angle):
                    continue
                radians = math.radians(angle)
                candidates.append(
                    (
                        (
                            center[0] + radius * math.cos(radians),
                            center[1] + radius * math.sin(radians),
                        ),
                        "切点",
                    )
                )
        return candidates

    def _placement_point(
        self, raw_point: Point2D, *, temporarily_disable_snapping: bool = False
    ) -> tuple[Point2D, str]:
        snap_temporarily_disabled = temporarily_disable_snapping
        point, snap_kind = (
            (raw_point, "临时关闭捕捉") if snap_temporarily_disabled else self._snapped(raw_point)
        )
        if (snap_kind and not snap_temporarily_disabled) or (
            self.tool not in {"直线", "多段线"} and not self._arc_point_tracking
        ):
            return point, snap_kind
        anchor = (
            self._points[-1]
            if (self.tool == "多段线" or self._arc_point_tracking) and self._points
            else self._first
        )
        if anchor is None:
            return point, snap_kind
        if self._polar_tracking_enabled and not snap_temporarily_disabled:
            tracked = self._polar_tracking_point(anchor, point)
            if tracked is not None:
                return tracked
        if self.tool == "直线" and self._auto_inference_enabled and not snap_temporarily_disabled:
            inferred = self._near_axis_point(anchor, point)
            if inferred is not None:
                return inferred
        if self._orthogonal_enabled:
            if abs(point[0] - anchor[0]) >= abs(point[1] - anchor[1]):
                relation = "水平关系" if self.tool == "直线" else ""
                status = relation
                if snap_temporarily_disabled:
                    status = f"临时关闭捕捉 · {relation}" if relation else "临时关闭捕捉"
                return (point[0], anchor[1]), status
            relation = "竖直关系" if self.tool == "直线" else ""
            status = relation
            if snap_temporarily_disabled:
                status = f"临时关闭捕捉 · {relation}" if relation else "临时关闭捕捉"
            return (anchor[0], point[1]), status
        return point, snap_kind

    def _polar_tracking_point(self, anchor: Point2D, point: Point2D) -> tuple[Point2D, str] | None:
        dx, dy = point[0] - anchor[0], point[1] - anchor[1]
        if math.hypot(dx, dy) * self._scale < 8.0:
            return None
        angle = math.degrees(math.atan2(dy, dx)) % 360.0
        base = self._last_polar_segment_angle() if self._polar_relative else 0.0
        increment = self._polar_angle_increment_deg
        lower = math.floor(((angle - base) % 360.0) / increment)
        candidates = (
            base,
            (base + lower * increment) % 360.0,
            (base + (lower + 1) * increment) % 360.0,
            *self._polar_additional_angles,
        )
        selected = min(candidates, key=lambda candidate: abs((angle - candidate + 180) % 360 - 180))
        deviation = abs((angle - selected + 180) % 360 - 180)
        if deviation > 5.0:
            return None
        radians = math.radians(selected)
        ux, uy = math.cos(radians), math.sin(radians)
        self._polar_tracking_direction = (ux, uy)
        distance = dx * ux + dy * uy
        if self._grid_snapping_enabled and self._polar_snap_enabled:
            spacing = self._polar_snap_spacing or self.grid_spacing_mm()
            distance = math.floor(distance / spacing + 0.5) * spacing
        return (anchor[0] + distance * ux, anchor[1] + distance * uy), f"极轴 {selected:g}°"

    def _last_polar_segment_angle(self) -> float:
        if (self.tool in {"直线", "多段线"} or self._arc_point_tracking) and len(self._points) >= 2:
            start, end = self._points[-2:]
        else:
            entity = next(
                (
                    candidate
                    for candidate in (
                        *self.entities,
                        *(item for item, _ in self.background_entities),
                    )
                    if candidate.entity_id == self._last_polar_entity_id
                ),
                None,
            )
            if isinstance(entity, PolylineEntity):
                bulges = entity.bulges or (0.0,) * (
                    len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
                )
                segment = polyline_curve_segments(
                    entity.points_mm, bulges, entity.closed, entity.entity_id
                )[-1]
            elif isinstance(entity, LineEntity):
                segment = entity
            else:
                return 0.0
            if isinstance(segment, ArcEntity):
                return (
                    segment.start_angle_deg
                    + segment.sweep_angle_deg
                    + (90 if segment.sweep_angle_deg > 0 else -90)
                ) % 360.0
            start, end = segment.start_mm, segment.end_mm
        return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 360.0

    def _near_axis_point(self, anchor: Point2D, point: Point2D) -> tuple[Point2D, str] | None:
        """Return an exact axis endpoint when its angular deviation is below five degrees."""
        delta_u, delta_v = point[0] - anchor[0], point[1] - anchor[1]
        if math.hypot(delta_u, delta_v) * self._scale < 8.0:
            return None
        tangent = math.tan(math.radians(5.0))
        if abs(delta_v) <= abs(delta_u) * tangent:
            return (point[0], anchor[1]), "水平关系"
        if abs(delta_u) <= abs(delta_v) * tangent:
            return (anchor[0], point[1]), "竖直关系"
        return None

    def _line_inferred_constraints(self, line: LineEntity) -> tuple[SketchConstraint, ...]:
        if not self._auto_inference_enabled:
            return ()
        kind = (
            "horizontal"
            if abs(line.start_mm[1] - line.end_mm[1]) <= 1e-12
            else "vertical"
            if abs(line.start_mm[0] - line.end_mm[0]) <= 1e-12
            else None
        )
        if kind is None:
            return ()
        return (
            SketchConstraint(
                uuid4().hex,
                kind,
                (SketchGeometryReference(line.entity_id, "geometry"),),
                source="inferred",
            ),
        )

    @staticmethod
    def _stable_point_references(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        if isinstance(entity, PointEntity):
            return ((SketchGeometryReference(entity.entity_id, "vertex", 0), entity.position_mm),)
        if isinstance(entity, SplineEntity):
            return ()
        if isinstance(entity, LineEntity):
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.start_mm),
                (SketchGeometryReference(entity.entity_id, "end"), entity.end_mm),
            )
        if isinstance(entity, PolylineEntity):
            if entity.closed:
                return tuple(
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(entity.points_mm)
                )
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.points_mm[0]),
                *(
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(entity.points_mm[1:-1], start=1)
                ),
                (SketchGeometryReference(entity.entity_id, "end"), entity.points_mm[-1]),
            )
        if isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            corners = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(corners)
            )
        if isinstance(entity, CircleEntity):
            return ((SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),)
        start = math.radians(entity.start_angle_deg)
        end = math.radians(entity.start_angle_deg + entity.sweep_angle_deg)
        return (
            (SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),
            (
                SketchGeometryReference(entity.entity_id, "start"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(start),
                    entity.center_mm[1] + entity.radius_mm * math.sin(start),
                ),
            ),
            (
                SketchGeometryReference(entity.entity_id, "end"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(end),
                    entity.center_mm[1] + entity.radius_mm * math.sin(end),
                ),
            ),
        )

    def _inferred_constraints_for_entity(
        self, entity: SketchEntity
    ) -> tuple[SketchConstraint, ...]:
        if not self._auto_inference_enabled:
            return ()
        inferred: list[SketchConstraint] = []
        if isinstance(entity, LineEntity):
            inferred.extend(self._line_inferred_constraints(entity))
        previous_entities = tuple(
            candidate for candidate in self.entities if candidate.entity_id != entity.entity_id
        )
        existing_points = tuple(
            (reference, point)
            for candidate in previous_entities
            for reference, point in self._stable_point_references(candidate)
        )
        for new_reference, new_point in self._stable_point_references(entity):
            matches = tuple(
                reference
                for reference, point in existing_points
                if _distance(new_point, point) <= 1e-9
            )
            if len(matches) != 1:
                continue
            inferred.append(
                SketchConstraint(
                    uuid4().hex,
                    "coincident",
                    (new_reference, matches[0]),
                    source="inferred",
                )
            )
        return tuple(inferred)

    def _preserve_satisfied_relations(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
    ) -> int:
        previous_count = len(self.constraints)
        by_id = {entity.entity_id: entity for entity in entities}
        original_by_id = {
            entity.entity_id: entity
            for entity in (
                original_entities if original_entities is not None else tuple(self.entities)
            )
        }
        retained: list[SketchConstraint] = []
        for constraint in self.constraints:
            if constraint.source != "inferred":
                retained.append(constraint)
                continue
            rebound_refs: list[SketchGeometryReference] = []
            try:
                for reference in constraint.references:
                    if reference.kind == "vertex":
                        original_entity = original_by_id.get(reference.entity_id)
                        updated_entity = by_id.get(reference.entity_id)
                        if isinstance(original_entity, PolylineEntity) and isinstance(
                            updated_entity, PolylineEntity
                        ):
                            index = _rebind_draft_polyline_vertex(
                                original_entity, updated_entity, reference.index
                            )
                            reference = replace(reference, index=index)
                        elif isinstance(original_entity, PolylineEntity) != isinstance(
                            updated_entity, PolylineEntity
                        ) or isinstance(original_entity, RectangleEntity) != isinstance(
                            updated_entity, RectangleEntity
                        ):
                            raise ValueError("顶点来源类型变化。")
                    rebound_refs.append(reference)
                constraint = replace(constraint, references=tuple(rebound_refs))
            except ValueError:
                continue
            if constraint.kind in ("horizontal", "vertical"):
                entity = by_id.get(constraint.references[0].entity_id)
                if not isinstance(entity, LineEntity):
                    continue
                residual = (
                    abs(entity.start_mm[1] - entity.end_mm[1])
                    if constraint.kind == "horizontal"
                    else abs(entity.start_mm[0] - entity.end_mm[0])
                )
                satisfied = residual <= 1e-9
            elif constraint.kind == "coincident":
                first = self.point_for_reference(constraint.references[0], by_id)
                second = self.point_for_reference(constraint.references[1], by_id)
                satisfied = (
                    first is not None and second is not None and _distance(first, second) <= 1e-9
                )
            elif constraint.kind == "tangent":
                curves: list[LineEntity | CircleEntity | ArcEntity] = []
                rebound: list[SketchGeometryReference] = []
                try:
                    for reference in constraint.references:
                        entity = by_id.get(reference.entity_id)
                        original = original_by_id.get(reference.entity_id)
                        if entity is None:
                            raise ValueError("相切来源已删除。")
                        if isinstance(original, PolylineEntity) and isinstance(
                            entity, PolylineEntity
                        ):
                            index = _rebind_draft_polyline_segment(
                                original, entity, reference.index
                            )
                            reference = replace(reference, index=index)
                        rebound.append(reference)
                        curves.append(tangent_entity_curve(entity, reference.index))
                    first, second = curves
                    satisfied = tangent_on_curves(first, second) and tangent_endpoints_satisfied(
                        first, second, constraint.first_endpoint, constraint.second_endpoint
                    )
                    if satisfied:
                        constraint = replace(constraint, references=tuple(rebound))
                except (ValueError, IndexError):
                    satisfied = False
            else:
                satisfied = False
            if satisfied:
                retained.append(constraint)
        self.constraints = retained
        return previous_count - len(retained)

    @staticmethod
    def point_for_reference(
        reference: SketchGeometryReference,
        entities: dict[str, SketchEntity],
    ) -> Point2D | None:
        return resolve_point_reference(reference, entities)

    def _accept_point(
        self,
        raw_point: Point2D,
        *,
        operation_override: str | None = None,
        temporarily_disable_snapping: bool = False,
        exact_point: bool = False,
    ) -> None:
        if self.tool == "对象相切选择":
            self._pick_object_tangency(raw_point)
            return
        if self.tool == "单点打断":
            self._break_at_point_pick(raw_point, exact_point=exact_point)
            return
        if (
            self.tool in {"点", "直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
            and not self._current_layer_can_draw()
        ):
            self.message = "当前图层隐藏或已锁定，无法创建图元。"
            self.changed.emit()
            return
        if self._transform_operation is not None:
            point = raw_point if exact_point else self._snapped(raw_point)[0]
            self._transform_point(point, commit=True)
            return
        active_tool = operation_override or self.tool
        if active_tool in {"修剪", "延伸", "分割"}:
            self._clear_line_edit_preview()
        point, snap_kind = (
            (raw_point, "")
            if exact_point or active_tool in {"修剪", "延伸", "分割"}
            else self._placement_point(
                raw_point, temporarily_disable_snapping=temporarily_disable_snapping
            )
        )
        if not exact_point and self._first is not None and self.dynamic_point_resolver is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, point)
                if resolved != point:
                    snap_kind = ""
                point = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
                return
        self._snap_kind = snap_kind
        self._cursor = point
        if active_tool in {"修剪", "延伸", "分割"}:
            if (
                self.source_revision_provider is not None
                and self.source_context_revision is not None
                and self.source_revision_provider() != self.source_context_revision
            ):
                self._clear_line_edit_preview()
                self._hovered_line_edit_entity_id = None
                self.source_revision_invalidated.emit()
                self.message = "文档已变化；请重新选择图元并操作。"
                self.changed.emit()
                self.update()
                return
            target_id = (
                self._extend_target_at(point)
                if active_tool == "延伸"
                else self._trim_target_at(point, lines_only=active_tool == "分割")
            )
            self._hovered_line_edit_entity_id = target_id
            if target_id is None:
                self.message = (
                    "请点选唯一可延伸端点。"
                    if active_tool == "延伸"
                    else "请点选唯一可修剪曲线段。"
                    if active_tool == "修剪"
                    else "请点选唯一可分割直线、矩形边或多段线段。"
                )
                self.changed.emit()
                self.update()
                return
            target = next(
                (entity for entity in self.entities if entity.entity_id == target_id), None
            )
            if target is None and self.select_committed_entities:
                saved = next(
                    (
                        (entity, layer)
                        for entity, layer in self.background_entities
                        if entity.entity_id == target_id
                    ),
                    None,
                )
                if saved is None:
                    self.message = "目标图元已变化；草稿未修改。"
                elif saved[1].locked:
                    self.message = "目标图元所在图层已锁定；草稿未修改。"
                else:
                    try:
                        updated = self._edit_visible_geometry(
                            tuple(self.entities), active_tool, point, target_id
                        )
                    except ValueError as exc:
                        self.message = str(exc)
                    else:
                        original_ids = {entity.entity_id for entity in self.selectable_entities()}
                        edited = tuple(
                            replace(entity, entity_id=uuid4().hex)
                            if entity.entity_id == target_id
                            and type(entity) is not type(saved[0])
                            and not (
                                isinstance(saved[0], CircleEntity) and isinstance(entity, ArcEntity)
                            )
                            else entity
                            for entity in updated
                            if entity.entity_id == target_id or entity.entity_id not in original_ids
                        )
                        self._clear_line_edit_preview()
                        self.message = f"正在校验{active_tool}。"
                        self.changed.emit()
                        self.update()
                        self.committed_line_edit_requested.emit(active_tool, target_id, edited)
                        return
                self.changed.emit()
                self.update()
                return
            if target is not None and self._layer(target).locked:
                self.message = "目标图元所在图层已锁定；草图未修改。"
                self.changed.emit()
                self.update()
                return
            try:
                updated = self._edit_draft_with_boundaries(
                    tuple(self.entities), active_tool, point, target_id
                )
                if active_tool in {"修剪", "延伸"}:
                    revised_constraints = self._line_edit_user_constraints(
                        updated, trim=active_tool == "修剪"
                    )
                else:
                    self._reject_user_constraint_reference_edits(updated)
                    revised_constraints = tuple(self.constraints)
            except ValueError as exc:
                self.message = str(exc)
            else:
                if updated != tuple(self.entities):
                    self._record_undo()
                    if self.tool in {"修剪", "延伸"}:
                        self._line_edit_undo_actions.append(("draft", self.history_position, "", 0))
                original_entities = tuple(self.entities)
                self.entities = list(updated)
                self.constraints = list(revised_constraints)
                self._prune_pending_cross_tangencies(original_entities=original_entities)
                removed_relations = self._preserve_satisfied_relations(
                    updated, original_entities=original_entities
                )
                self._snap_candidates_cache = None
                available_ids = {entity.entity_id for entity in self.entities}
                self.selected_entity_ids.intersection_update(available_ids)
                self.message = (
                    "快速修剪：没有有效交点，已删除目标；可撤销。"
                    if active_tool == "修剪" and target_id not in available_ids
                    else "修剪完成；源图元身份保留在首个剩余曲线片段。"
                    if active_tool == "修剪"
                    else "已延伸目标曲线到最近交点；图元身份保持不变。"
                    if active_tool == "延伸"
                    else "已分割目标图元；第一段保留原身份，第二段取得新身份。"
                )
                if removed_relations:
                    self.message += f" 已移除 {removed_relations} 条失效或需重新确认的自动关系。"
            self._hovered_line_edit_entity_id = None
            self.changed.emit()
            self.update()
            return
        if self.tool == "点":
            self._record_undo()
            self.entities.append(
                PointEntity(uuid4().hex, point, self.construction, self.active_layer_name)
            )
            self._snap_candidates_cache = None
            self.point_accepted.emit(point)
            self.message = "点已创建；可撤销。"
            self.changed.emit()
            self.update()
            return
        if self.tool == "多段线":
            if self.polyline_arc_stage == "center":
                if not self._points or math.dist(self._points[-1], point) <= 1e-9:
                    self.message = "圆心不能与圆弧起点重合。"
                else:
                    self._polyline_arc_center = point
                    self.polyline_arc_stage = ""
                    self.point_accepted.emit(point)
                    self.message = "多段线圆弧：指定终点方向（圆心方式）。"
                self.changed.emit()
                self.update()
                return
            if self.polyline_arc_stage in {"radius", "angle"}:
                self.message = "请先在命令栏输入圆弧参数。"
                self.changed.emit()
                return
            if self._polyline_arc_second_pending:
                if self._points and point != self._points[-1]:
                    self._polyline_arc_middle = point
                    self._polyline_arc_second_pending = False
                    self.point_accepted.emit(point)
                    self.message = "多段线圆弧：指定终点。"
                else:
                    self.message = "圆弧第二点不能与起点重合。"
                self.changed.emit()
                self.update()
                return
            if self._polyline_arc_center is not None and self._points:
                try:
                    point = self._polyline_arc_project_endpoint(point)
                except ValueError as exc:
                    self.message = str(exc)
                    self.changed.emit()
                    return
            if len(self._points) >= 3 and point == self._points[0]:
                self.finish_polyline(close=True)
                return
            if self._points and point == self._points[-1]:
                self.message = "相邻点不能重合；请指定下一个点。"
                self.changed.emit()
                return
            if self._points:
                try:
                    bulge = self._polyline_arc_bulge(point) if self.polyline_arc_mode else 0.0
                except ValueError as exc:
                    self.message = str(exc)
                    self.changed.emit()
                    return
                self._polyline_bulges.append(bulge)
            self._points.append(point)
            self._polyline_arc_middle = None
            self._reset_polyline_arc_option()
            self.point_accepted.emit(point)
            self.message = (
                "多段线圆弧：指定终点；A 角度，CE 圆心，R 半径，S 第二点，L 直线，U 撤销，C 闭合。"
                if self.polyline_arc_mode
                else "多段线直线：指定下一点；A 圆弧，U 撤销，C 闭合，Enter 完成。"
            )
            self.changed.emit()
            self.update()
            return
        if self.tool == "样条曲线":
            if self._points and point == self._points[-1]:
                self.message = "请选择不同的下一个控制点。"
            else:
                self._points.append(point)
                self.point_accepted.emit(point)
                self.message = f"样条：已放置 {len(self._points)} 个控制点，至少四点；Enter / 右键完成，Esc 取消。"
            self.changed.emit()
            self.update()
            return
        if self._first is None:
            if self.tool == "圆弧":
                self.arc_mode_prompt_active = False
            self._first = point
            self._points = [point]
            self.point_accepted.emit(point)
            self.message = self._next_point_hint()
            self.changed.emit()
            self.update()
            return
        try:
            entity = self._make_entity(self._first, point)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        if entity is None and self.tool == "圆弧" and len(self._points) == 2:
            self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        if entity is not None:
            if self.layer_table.get(entity.layer_name).locked:
                self.message = "目标图层已锁定；草图未修改。"
                self.changed.emit()
                self.update()
                return
            self._record_undo()
            self.entities.append(entity)
            if isinstance(entity, LineEntity | PolylineEntity):
                self._last_polar_entity_id = entity.entity_id
            self.point_accepted.emit(point)
            self.constraints.extend(self._inferred_constraints_for_entity(entity))
            self._snap_candidates_cache = None
        if self.tool == "直线" and self.continuous_lines and entity is not None:
            if len(self._points) >= 3 and point == self._points[0]:
                self.end_line_chain()
                self.message = "首尾已精确闭合；可指定新起点。"
            else:
                self._points.append(point)
                self._first = point
                self.message = "直线：指定下一点；Enter 结束，C 闭合，U 退回上一段，Esc 结束。"
        else:
            self._first = None
            self._points.clear()
            self.message = f"{self.tool}已加入草稿。可继续绘制或点击完成草图。"
        self.changed.emit()
        self.update()

    def _next_point_hint(self) -> str:
        if self.tool == "圆弧":
            return (
                "三点圆弧：指定第二点。"
                if self.arc_creation_mode == "three_point"
                else "圆弧：依次指定圆心、起点、终点。"
            )
        if self.tool == "圆":
            return "圆：已指定圆心，再指定半径。"
        if self.tool == "多边形":
            return "正多边形：中心已指定；内接模式指定顶点，外切模式指定边中点。"
        return f"{self.tool}：再指定一个点。"

    def _polygon_points(self, center: Point2D, radius_point: Point2D) -> tuple[Point2D, ...]:
        radius = _distance(center, radius_point)
        if radius <= 1e-9:
            raise ValueError("正多边形半径必须大于零。")
        angle = math.atan2(radius_point[1] - center[1], radius_point[0] - center[0])
        step = math.tau / self.polygon_sides
        if self.polygon_circumscribed:
            radius /= math.cos(step / 2.0)
            angle += step / 2.0
        return tuple(
            (
                center[0] + radius * math.cos(angle + index * step),
                center[1] + radius * math.sin(angle + index * step),
            )
            for index in range(self.polygon_sides)
        )

    def _make_entity(self, first: Point2D, second: Point2D) -> SketchEntity | None:
        identity = uuid4().hex
        if self.tool == "直线":
            return LineEntity(identity, first, second, self.construction, self.active_layer_name)
        if self.tool == "多边形":
            return PolylineEntity(
                identity,
                self._polygon_points(first, second),
                True,
                self.construction,
                self.active_layer_name,
            )
        if self.tool == "矩形":
            return RectangleEntity(
                identity, first, second, self.construction, self.active_layer_name
            )
        if self.tool == "圆":
            return CircleEntity(
                identity,
                first,
                _distance(first, second),
                self.construction,
                self.active_layer_name,
            )
        if self.tool == "圆弧":
            if len(self._points) == 1:
                if _distance(self._points[0], second) <= 1e-12:
                    if self.arc_creation_mode == "three_point":
                        raise ValueError("第二点不能与起点重合。")
                    raise ValueError("圆弧起点不能与圆心重合，请重新指定起点。")
                self._points.append(second)
                self.message = (
                    "三点圆弧：第二点已指定，再指定终点。"
                    if self.arc_creation_mode == "three_point"
                    else "圆弧：起点已指定，再指定终点。"
                )
                self.changed.emit()
                self.update()
                return None
            if self.arc_creation_mode == "three_point":
                return self._three_point_arc(self._points[0], self._points[1], second, identity)
            center, start = self._points[0], self._points[1]
            radius = _distance(center, start)
            start_angle = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
            end_angle = math.degrees(math.atan2(second[1] - center[1], second[0] - center[0]))
            sweep = _arc_sweep(start_angle, end_angle, self.arc_direction)
            if abs(sweep) <= 1e-9:
                raise ValueError("圆弧终点必须与起点不同。")
            return ArcEntity(
                identity,
                center,
                radius,
                start_angle,
                sweep,
                self.construction,
                self.active_layer_name,
            )
        return None

    def set_drawing_theme(self, theme: str) -> None:
        """Update the drawing surface without changing stored layer colors."""
        dark = self.select_committed_entities and theme == "dark"
        if dark != self._drawing_dark_theme:
            self._drawing_dark_theme = dark
            self.update()

    def _drawing_color(self, color: QColor) -> QColor:
        if not self._drawing_dark_theme:
            return color
        hue, saturation, value, alpha = cast("tuple[int, int, int, int]", color.getHsv())
        if saturation < 85 and value < 120:
            return QColor(230, 237, 245, alpha)
        if value < 190:
            return QColor.fromHsv(max(0, hue), saturation, 190, alpha)
        return color

    def _draw_entity(
        self,
        painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        layer = self._layer(entity) if layer is None else layer
        if not layer.displayed:
            return
        color = (
            QColor(210, 45, 45)
            if entity.entity_id in self.dimension_error_entity_ids
            else QColor(0, 139, 139)
            if highlighted
            else QColor(128, 138, 145)
            if entity.construction
            else QColor(*layer.color_rgb)
        )
        color = self._drawing_color(color)
        line_styles = {
            "CONTINUOUS": Qt.PenStyle.SolidLine,
            "DASHED": Qt.PenStyle.DashLine,
            "DOTTED": Qt.PenStyle.DotLine,
            "DASHDOT": Qt.PenStyle.DashDotLine,
        }
        style = (
            Qt.PenStyle.SolidLine
            if highlighted
            else Qt.PenStyle.DashLine
            if entity.construction
            else line_styles[layer.linetype]
        )
        width = 3.0 if highlighted else 1.0 + min(2.0, layer.lineweight_mm * 2.0)
        painter.setPen(
            QPen(
                color,
                width,
                style,
            )
        )
        if isinstance(entity, PointEntity):
            point = self.local_to_screen(entity.position_mm)
            painter.drawLine(point.x() - 4, point.y(), point.x() + 4, point.y())
            painter.drawLine(point.x(), point.y() - 4, point.x(), point.y() + 4)
        elif isinstance(entity, SplineEntity):
            points = entity.sampled_points()
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
        elif isinstance(entity, LineEntity):
            painter.drawLine(
                self.local_to_screen(entity.start_mm), self.local_to_screen(entity.end_mm)
            )
        elif isinstance(entity, PolylineEntity):
            points = [self.local_to_screen(point) for point in polyline_sampled_points(entity)]
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(start, end)
        elif isinstance(entity, RectangleEntity):
            first = self.local_to_screen(entity.first_corner_mm)
            opposite = self.local_to_screen(entity.opposite_corner_mm)
            painter.drawRect(QRectF(QPointF(first), QPointF(opposite)).normalized())
        else:
            center = self.local_to_screen(entity.center_mm)
            radius_px = entity.radius_mm * self._scale
            bounds = QRectF(
                center.x() - radius_px, center.y() - radius_px, radius_px * 2, radius_px * 2
            )
            if isinstance(entity, CircleEntity):
                painter.drawEllipse(bounds)
            else:
                painter.drawArc(
                    bounds,
                    round(entity.start_angle_deg * 16),
                    round(entity.sweep_angle_deg * 16),
                )

    def set_drawing_rasters(self, images: tuple[DrawingRaster, ...]) -> None:
        if images != self.drawing_rasters:
            self.drawing_rasters = images
            self.selected_raster_ids.intersection_update(image.image_id for image in images)
            self._raster_image_cache.clear()
            self.update()

    @staticmethod
    def _raster_contains(raster: DrawingRaster, point: Point2D) -> bool:
        x, y = point[0] - raster.origin_mm[0], point[1] - raster.origin_mm[1]
        angle = math.radians(raster.angle_deg)
        u = math.cos(angle) * x + math.sin(angle) * y
        v = -math.sin(angle) * x + math.cos(angle) * y
        if raster.mirrored:
            v = -v
        return 0 <= u <= raster.width_mm and 0 <= v <= raster.height_mm

    def _draw_raster(
        self, painter: QPainter, raster: DrawingRaster, *, allow_missing_layer: bool = False
    ) -> None:
        try:
            if not self.layer_table.get(raster.layer_name).displayed:
                return
        except KeyError:
            if not allow_missing_layer:
                return
        image = self._raster_image_cache.get(raster.image_id)
        if image is None:
            image = QImage.fromData(raster.png_bytes)
            self._raster_image_cache[raster.image_id] = image
        if image.isNull():
            return
        origin = self.local_to_screen(raster.origin_mm)
        x_end = self.local_to_screen((raster.origin_mm[0] + raster.width_mm, raster.origin_mm[1]))
        y_end = self.local_to_screen((raster.origin_mm[0], raster.origin_mm[1] + raster.height_mm))
        width = abs(x_end.x() - origin.x())
        height = abs(y_end.y() - origin.y())
        painter.save()
        painter.translate(origin)
        painter.rotate(-raster.angle_deg)
        if raster.mirrored:
            painter.scale(1, -1)
        bounds = QRectF(0, -height, width, height)
        painter.drawImage(bounds, image)
        if raster.image_id in self.selected_raster_ids:
            painter.setPen(QPen(QColor("#00aaff"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(bounds)
        painter.restore()

    def _draw_preview(self, painter: QPainter) -> None:
        if self._cursor is None:
            return
        if self._raster_transform_previews:
            painter.save()
            painter.setOpacity(0.65)
            for raster in self._raster_transform_previews:
                self._draw_raster(painter, raster)
            painter.restore()
        if self._clipboard_rasters:
            dx, dy = (
                self._cursor[0] - self._clipboard_anchor[0],
                self._cursor[1] - self._clipboard_anchor[1],
            )
            try:
                images = tuple(
                    replace(item, origin_mm=(item.origin_mm[0] + dx, item.origin_mm[1] + dy))
                    for item in self._clipboard_rasters
                )
            except ValueError:
                return
            painter.save()
            painter.setOpacity(0.65)
            for image in images:
                self._draw_raster(painter, image)
            painter.restore()
            return
        if self._clipboard_raster is not None:
            painter.save()
            painter.setOpacity(0.65)
            self._draw_raster(painter, replace(self._clipboard_raster, origin_mm=self._cursor))
            painter.restore()
            return
        if self._clipboard_paste is not None:
            delta = (
                self._cursor[0] - self._clipboard_anchor[0],
                self._cursor[1] - self._clipboard_anchor[1],
            )
            try:
                entities, _constraints = instantiate_drawing_clipboard(self._clipboard_paste, delta)
            except ValueError:
                return
            if self._clipboard_mixed_images:
                painter.save()
                painter.setOpacity(0.65)
                for image in self._clipboard_mixed_images:
                    self._draw_raster(
                        painter,
                        replace(
                            image,
                            origin_mm=(
                                image.origin_mm[0] + delta[0],
                                image.origin_mm[1] + delta[1],
                            ),
                        ),
                        allow_missing_layer=True,
                    )
                painter.restore()
            for entity in entities:
                try:
                    layer = self.layer_table.get(entity.layer_name)
                except KeyError:
                    layer = self._clipboard_paste.layers.get(entity.layer_name)
                self._draw_entity(painter, entity, highlighted=True, layer=layer)
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(Qt.GlobalColor.darkCyan, 1.5, Qt.PenStyle.DashLine))
        if self.line_tangent_active:
            line = self.previewed_tangent_line
            if line is not None:
                painter.drawLine(
                    self.local_to_screen(line.start_mm), self.local_to_screen(line.end_mm)
                )
                if self._snap_kind == "切点":
                    painter.setPen(QPen(Qt.GlobalColor.red, 1.5))
                    for point in (line.start_mm, line.end_mm):
                        painter.drawEllipse(self.local_to_screen(point), 5.0, 5.0)
                    painter.drawText(self.local_to_screen(line.end_mm) + QPoint(8, -8), "切点")
            elif self._snap_kind == "待定切点":
                painter.setPen(QPen(Qt.GlobalColor.red, 1.5))
                point = self.local_to_screen(self._cursor)
                painter.drawEllipse(point, 5.0, 5.0)
                painter.drawText(point + QPoint(8, -8), "待定切点")
            return
        cursor = self.local_to_screen(self._cursor)
        if self._snap_kind.startswith("极轴"):
            painter.drawText(cursor + QPoint(8, -8), self._snap_kind)
        if self.tool == "多边形" and self._first is not None:
            try:
                points = self._polygon_points(self._first, self._cursor)
            except ValueError:
                points = ()
            if points:
                for start, end in zip(points, (*points[1:], points[0]), strict=True):
                    painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
                painter.drawLine(self.local_to_screen(self._first), cursor)
        if self.tool == "样条曲线" and self._points:
            control_points = (*self._points, self._cursor)
            for start, end in zip(control_points, control_points[1:], strict=False):
                painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
            if len(control_points) >= 4:
                try:
                    preview = SplineEntity("00000000000000000000000000000000", control_points)
                    self._draw_entity(painter, preview, highlighted=True)
                except ValueError:
                    pass
        if self.tool in ("直线", "矩形", "圆", "圆弧") and self._first is not None:
            first = self.local_to_screen(self._first)
            if self.tool == "直线":
                painter.drawLine(first, cursor)
            elif self.tool == "矩形":
                painter.drawRect(QRectF(QPointF(first), QPointF(cursor)).normalized())
            elif self.tool == "圆":
                radius = math.hypot(cursor.x() - first.x(), cursor.y() - first.y())
                painter.drawEllipse(QPointF(first), radius, radius)
            elif self.tool == "圆弧" and self.arc_creation_mode == "three_point":
                if len(self._points) > 1:
                    try:
                        preview = self._three_point_arc(
                            self._points[0],
                            self._points[1],
                            self._cursor,
                            "00000000000000000000000000000000",
                        )
                    except ValueError:
                        pass
                    else:
                        self._draw_entity(painter, preview, highlighted=True)
                else:
                    painter.drawLine(first, cursor)
            elif self.tool == "圆弧" and len(self._points) > 1:
                center = self.local_to_screen(self._points[0])
                start = self.local_to_screen(self._points[1])
                radius = math.hypot(start.x() - center.x(), start.y() - center.y())
                start_angle = math.degrees(
                    math.atan2(center.y() - start.y(), start.x() - center.x())
                )
                end_angle = math.degrees(
                    math.atan2(center.y() - cursor.y(), cursor.x() - center.x())
                )
                sweep = _arc_sweep(start_angle, end_angle, self.arc_direction)
                painter.drawArc(
                    QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                    round(start_angle * 16),
                    round(sweep * 16),
                )
        elif self.tool == "多段线" and self._points:
            vertices = tuple(self._points)
            bulges = tuple(self._polyline_bulges)
            if (
                self._cursor != vertices[-1]
                and not self._polyline_arc_second_pending
                and not self.polyline_arc_stage
            ):
                try:
                    endpoint = self._polyline_arc_project_endpoint(self._cursor)
                    candidate_bulge = (
                        self._polyline_arc_bulge(endpoint) if self.polyline_arc_mode else 0.0
                    )
                    vertices = (*vertices, endpoint)
                    bulges = (*bulges, candidate_bulge)
                except ValueError:
                    pass
            if len(vertices) >= 2:
                try:
                    preview = PolylineEntity(
                        "00000000000000000000000000000000", vertices, bulges=bulges
                    )
                    vertices = polyline_sampled_points(preview)
                except ValueError:
                    pass
            points = [self.local_to_screen(point) for point in vertices]
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(start, end)
        if self._snap_kind:
            painter.setPen(QPen(Qt.GlobalColor.red, 1.5))
            painter.drawEllipse(cursor, 5.0, 5.0)
            if self._snap_kind == "待定切点":
                painter.drawText(cursor + QPoint(8, -8), "待定切点")

    def constraint_anchor(
        self,
        constraint: SketchConstraint,
        entities: dict[str, SketchEntity],
    ) -> Point2D | None:
        if constraint.position_mm is not None:
            return constraint.position_mm
        reference = constraint.references[0]
        if constraint.kind == "coincident":
            first = self.point_for_reference(reference, entities)
            second = self.point_for_reference(constraint.references[1], entities)
            if first is not None and second is not None:
                return ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
        if constraint.kind == "distance":
            first = self.point_for_reference(reference, entities)
            second = self.point_for_reference(constraint.references[1], entities)
            if first is not None and second is not None:
                return ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
        if constraint.kind in ("length", "angle"):
            segment = self.line_for_reference(reference, entities)
            if segment is not None:
                return (
                    (segment[0][0] + segment[1][0]) / 2.0,
                    (segment[0][1] + segment[1][1]) / 2.0,
                )
        entity = entities.get(reference.entity_id)
        if (
            isinstance(entity, PolylineEntity)
            and reference.kind == "segment"
            and reference.index is not None
            and constraint.kind in ("radius", "diameter", "arc_length")
        ):
            from mycad.core.polyline_curves import polyline_arc_segment

            return polyline_arc_segment(entity, reference.index).center_mm
        if isinstance(entity, CircleEntity | ArcEntity) and (
            constraint.kind in ("radius", "diameter", "arc_length", "concentric")
            or reference.kind == "center"
        ):
            return entity.center_mm
        point = self.point_for_reference(reference, entities)
        if point is not None:
            return point
        segment = self.line_for_reference(reference, entities)
        if segment is not None:
            return (
                (segment[0][0] + segment[1][0]) / 2.0,
                (segment[0][1] + segment[1][1]) / 2.0,
            )
        if isinstance(entity, LineEntity):
            return (
                (entity.start_mm[0] + entity.end_mm[0]) / 2.0,
                (entity.start_mm[1] + entity.end_mm[1]) / 2.0,
            )
        if isinstance(entity, RectangleEntity):
            return (
                (entity.first_corner_mm[0] + entity.opposite_corner_mm[0]) / 2.0,
                (entity.first_corner_mm[1] + entity.opposite_corner_mm[1]) / 2.0,
            )
        return None

    @staticmethod
    def line_for_reference(
        reference: SketchGeometryReference,
        entities: dict[str, SketchEntity],
    ) -> tuple[Point2D, Point2D] | None:
        entity = entities.get(reference.entity_id)
        if isinstance(entity, LineEntity) and reference.kind == "geometry":
            return (entity.start_mm, entity.end_mm)
        if isinstance(entity, PolylineEntity) and reference.kind == "segment":
            index = reference.index
            segment_count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
            if index is not None and 0 <= index < segment_count:
                if entity.bulges and entity.bulges[index] != 0:
                    return None
                return (
                    entity.points_mm[index],
                    entity.points_mm[(index + 1) % len(entity.points_mm)],
                )
        if isinstance(entity, RectangleEntity) and reference.kind == "segment":
            index = reference.index
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            if index is not None and 0 <= index < len(corners):
                return (corners[index], corners[(index + 1) % len(corners)])
        return None

    def dimension_layout(
        self, constraint: SketchConstraint, entities: dict[str, SketchEntity]
    ) -> DimensionLayout | None:
        """Screen-space annotation only; geometry and values come from the solver."""
        from mycad.ui.dimension_layout import apply_dimension_visibility, apply_extension_visibility

        def finalize(layout: DimensionLayout | None) -> DimensionLayout | None:
            return apply_extension_visibility(
                self, constraint, apply_dimension_visibility(self, constraint, layout)
            )

        if (
            constraint.position_mm is not None
            or constraint.axis != "aligned"
            or constraint.kind == "arc_length"
        ):
            from mycad.ui.dimension_layout import placed_dimension_layout

            result = placed_dimension_layout(self, constraint, entities)
            return finalize(result)
        reference = constraint.references[0]
        offset = 26.0 * constraint.scale
        if constraint.kind in {"length", "distance"}:
            if constraint.kind == "length":
                segment = self.line_for_reference(reference, entities)
            else:
                first = self.point_for_reference(reference, entities)
                second = self.point_for_reference(constraint.references[1], entities)
                segment = (first, second) if first is not None and second is not None else None
            if segment is None:
                return None
            a, b = (QPointF(self.local_to_screen(point)) for point in segment)
            delta = b - a
            length = math.hypot(delta.x(), delta.y())
            if length < 1e-9:
                return None
            normal = QPointF(delta.y(), -delta.x()) / length
            p, q = a + normal * offset, b + normal * offset
            return finalize(
                DimensionLayout(
                    ((a, p + normal * 5), (b, q + normal * 5), (p, q)),
                    ((p, q), (q, p)),
                    (p + q) / 2,
                    (0, 1),
                ),
            )
        if constraint.kind in {"radius", "diameter"}:
            entity = entities.get(reference.entity_id)
            if (
                isinstance(entity, PolylineEntity)
                and reference.kind == "segment"
                and reference.index is not None
            ):
                from mycad.core.polyline_curves import polyline_arc_segment

                entity = polyline_arc_segment(entity, reference.index)
            if not isinstance(entity, CircleEntity | ArcEntity):
                return None
            angle = (
                math.radians(entity.start_angle_deg + entity.sweep_angle_deg / 2)
                if isinstance(entity, ArcEntity)
                else math.pi / 4
            )
            center = QPointF(self.local_to_screen(entity.center_mm))
            direction = QPointF(math.cos(angle), -math.sin(angle))
            reach = entity.radius_mm * self._scale
            rim = center + direction * reach
            label = rim + direction * offset
            opposite = center - direction * reach if constraint.kind == "diameter" else center
            arrows = (
                ((rim, opposite), (opposite, rim))
                if constraint.kind == "diameter"
                else ((rim, center),)
            )
            from mycad.ui.dimension_layout import radial_center_lines

            lines = (
                (opposite, label),
                *radial_center_lines(self, constraint, entity, center, label),
            )
            return finalize(DimensionLayout(lines, arrows, label, tuple(range(1, len(lines)))))
        if constraint.kind == "angle" and constraint.value is not None:
            first_line = self.line_for_reference(reference, entities)
            second_line = self.line_for_reference(constraint.references[1], entities)
            if first_line is None or second_line is None:
                return None
            a, b = (QPointF(self.local_to_screen(point)) for point in first_line)
            c, d = (QPointF(self.local_to_screen(point)) for point in second_line)
            u, v = b - a, d - c
            cross = u.x() * v.y() - u.y() * v.x()
            if abs(cross) < 1e-9:
                return None
            delta = c - a
            center = a + u * ((delta.x() * v.y() - delta.y() * v.x()) / cross)
            start = math.atan2(u.y(), u.x())
            basis = self.dimension_basis(constraint)
            sweep = -math.radians(constraint.value) * (basis[2] if basis else 1.0)
            radius = max(32.0, offset * 1.5)
            points = tuple(
                center
                + QPointF(math.cos(start + sweep * i / 32), math.sin(start + sweep * i / 32))
                * radius
                for i in range(33)
            )
            lines = (
                *tuple(zip(points, points[1:], strict=False)),
                (center, points[0]),
                (center, points[-1]),
            )
            return finalize(
                DimensionLayout(
                    lines,
                    ((points[0], points[1]), (points[-1], points[-2])),
                    center
                    + QPointF(math.cos(start + sweep / 2), math.sin(start + sweep / 2))
                    * (radius + 10),
                    (len(lines) - 2, len(lines) - 1),
                ),
            )
        return None

    def dimension_basis(
        self, constraint: SketchConstraint
    ) -> tuple[Point2D, Point2D, float] | None:
        """Return the owning frame's projected basis, including unsaved candidates."""
        basis = self.background_dimension_basis.get(
            constraint.constraint_id
        ) or self.background_entity_basis.get(constraint.references[0].entity_id)
        if constraint.projection_axis is None:
            return basis
        u, v, orientation = basis or ((1.0, 0.0), (0.0, 1.0), 1.0)
        x, y = constraint.projection_axis
        direction = (x * u[0] + y * v[0], x * u[1] + y * v[1])
        if constraint.axis in ("horizontal", "ordinate_x"):
            return direction, (-orientation * direction[1], orientation * direction[0]), orientation
        return (orientation * direction[1], -orientation * direction[0]), direction, orientation

    def dimension_label_font(self, constraint: SketchConstraint) -> QFont:
        """Return the same scaled font used to draw and pick a dimension."""
        font = QFont(self.font())
        style = self.dimension_style_for_constraint(constraint)
        height_ratio = 1.0 if style is None else style.text_height / 2.5
        font.setPointSizeF(max(0.02, 8.0 * constraint.scale * self.view_scale / 5.0 * height_ratio))
        return font

    def dimension_label_rect(self, constraint: SketchConstraint, center: QPointF) -> QRectF:
        """Return the screen bounds of a dimension's formatted label."""
        label = self.dimension_display_text(constraint)
        if not constraint.driving:
            label = f"({label})"
        scale = constraint.scale * self.view_scale / 5.0
        style = self.dimension_style_for_constraint(constraint)
        scale *= 1.0 if style is None else style.text_height / 2.5
        metrics = QFontMetricsF(self.dimension_label_font(constraint), self)
        width = max(24.0 * scale, metrics.horizontalAdvance(label) + 10.0 * scale)
        return QRectF(center.x() - width / 2, center.y() - 10.0 * scale, width, 18.0 * scale)

    def dimension_style_for_constraint(
        self, constraint: SketchConstraint | None
    ) -> DimensionStyle | None:
        if (
            constraint is None
            or constraint.style_name is None
            or self.drawing_dimension_styles is None
        ):
            return None
        try:
            return self.drawing_dimension_styles.get(constraint.style_name)
        except KeyError:
            return None

    def dimension_display_value(self, constraint: SketchConstraint) -> float | None:
        if constraint.kind == "angle" and constraint.position_mm is not None:
            entities = self.dimension_entities()
            first = self.line_for_reference(constraint.references[0], entities)
            second = self.line_for_reference(constraint.references[1], entities)
            if first is not None and second is not None:
                try:
                    sector = angular_sector(first, second, constraint.position_mm)
                    return math.degrees(sector.sweep)
                except ValueError:
                    pass
        return constraint.value

    def dimension_display_text(self, constraint: SketchConstraint) -> str:
        return dimension_text(replace(constraint, value=self.dimension_display_value(constraint)))

    def dimension_arrow_segments(
        self, layout: DimensionLayout, scale: float, constraint: SketchConstraint | None = None
    ) -> tuple[tuple[QPointF, QPointF], ...]:
        scale *= self.view_scale / 5.0
        style = self.dimension_style_for_constraint(constraint)
        segments: list[tuple[QPointF, QPointF]] = []
        for index, (tip, toward) in enumerate(layout.arrows):
            role = layout.arrow_roles[index] if layout.arrow_roles else index
            delta = toward - tip
            length = math.hypot(delta.x(), delta.y())
            if length < 1e-9:
                continue
            along = delta / length
            side = QPointF(-along.y(), along.x())
            arrow = (
                "open"
                if style is None
                else (style.arrow_first if role == 0 else style.arrow_second)
            )
            size = 7 * scale if style is None else style.arrow_size * 5 * scale
            if arrow == "none":
                continue
            if arrow == "tick":
                diagonal = (along + side) * (size / math.sqrt(2))
                segments.append((tip - diagonal / 2, tip + diagonal / 2))
                continue
            first = tip + along * size + side * (size * 3 / 7)
            second = tip + along * size - side * (size * 3 / 7)
            segments.extend(((tip, first), (tip, second)))
            if arrow in ("closed", "filled"):
                segments.append((first, second))
        return tuple(segments)

    def dimension_label_rectangles(self) -> dict[str, QRectF]:
        """Return the actual stacked label bounds used by the canvas."""
        entities = self.dimension_entities()
        candidate = self.dimension_candidate
        dimensions = tuple(
            c
            for c in self.dimension_constraints()
            if candidate is None or c.constraint_id != candidate.constraint_id
        )
        stack_bottoms: dict[tuple[int, int], float] = {}
        rectangles: dict[str, QRectF] = {}
        for constraint in (*dimensions, *((candidate,) if candidate is not None else ())):
            if not self.annotation_layer(constraint).displayed:
                continue
            if constraint.kind not in DIMENSION_KINDS and not self.constraint_markers_visible:
                continue
            if any(reference.entity_id not in entities for reference in constraint.references):
                continue
            anchor = self.constraint_anchor(constraint, entities)
            if anchor is None or (constraint.kind in DIMENSION_KINDS and constraint.value is None):
                continue
            layout = self.dimension_layout(constraint, entities)
            screen = layout.label if layout is not None else QPointF(self.local_to_screen(anchor))
            key = (round(screen.x() / 24.0), round(screen.y() / 18.0))
            if constraint.kind in DIMENSION_KINDS:
                rect = self.dimension_label_rect(constraint, screen)
                if layout is None:
                    rect.moveLeft(screen.x() + 7.0)
            else:
                rect = QRectF(screen.x() + 7.0, screen.y() - 10.0, 24.0, 18.0)
            previous_bottom = stack_bottoms.get(key)
            if previous_bottom is not None and rect.top() < previous_bottom:
                rect.moveTop(previous_bottom)
            stack_bottoms[key] = rect.bottom()
            rectangles[constraint.constraint_id] = rect
        return rectangles

    def _draw_dimension_lines(
        self,
        painter: QPainter,
        layout: DimensionLayout,
        scale: float,
        constraint: SketchConstraint | None = None,
        *,
        extension_pen: QPen | None = None,
        second_extension_pen: QPen | None = None,
    ) -> None:
        painter.save()
        dimension_pen = QPen(painter.pen())
        for index, (start, end) in enumerate(layout.lines):
            roles = layout.extension_roles or tuple(range(len(layout.extension_indices)))
            second = (
                second_extension_pen is not None
                and any(
                    index == item and role == 1
                    for item, role in zip(layout.extension_indices, roles, strict=True)
                )
                and (constraint is None or constraint.kind not in ("radius", "diameter"))
            )
            painter.setPen(
                second_extension_pen
                if second
                else extension_pen
                if extension_pen is not None and index in layout.extension_indices
                else dimension_pen
            )
            painter.drawLine(start, end)
        painter.setPen(dimension_pen)
        for start, end in self.dimension_arrow_segments(layout, scale, constraint):
            painter.drawLine(start, end)
        style = self.dimension_style_for_constraint(constraint)
        if style is not None:
            painter.save()
            painter.setBrush(painter.pen().color())
            size = style.arrow_size * scale * self.view_scale
            for index, (tip, toward) in enumerate(layout.arrows):
                role = layout.arrow_roles[index] if layout.arrow_roles else index
                arrow = style.arrow_first if role == 0 else style.arrow_second
                delta = toward - tip
                length = math.hypot(delta.x(), delta.y())
                if arrow != "filled" or length <= 1e-9:
                    continue
                along = delta / length
                side = QPointF(-along.y(), along.x())
                painter.drawPolygon(
                    QPolygonF(
                        (
                            tip,
                            tip + along * size + side * size * 3 / 7,
                            tip + along * size - side * size * 3 / 7,
                        )
                    )
                )
            painter.restore()
        painter.restore()

    def _draw_constraint_overlays(self, painter: QPainter) -> None:
        painter.save()
        entities = self.dimension_entities()
        glyphs = {
            "coincident": "◎",
            "horizontal": "H",
            "vertical": "V",
            "parallel": "∥",
            "perpendicular": "⊥",
            "tangent": "T",
            "concentric": "◎",
            "equal": "=",
            "fixed": "◆",
        }
        label_rectangles = self.dimension_label_rectangles()
        label_font = QFont(painter.font())
        label_font.setPointSize(8)
        painter.setFont(label_font)
        candidate = self.dimension_candidate
        dimensions = tuple(
            c
            for c in self.dimension_constraints()
            if candidate is None or c.constraint_id != candidate.constraint_id
        )
        for constraint in (*dimensions, *((candidate,) if candidate is not None else ())):
            layer = self.annotation_layer(constraint)
            if not layer.displayed:
                continue
            label_color = (
                QColor(210, 45, 45)
                if constraint.constraint_id in self.dimension_error_constraint_ids
                else QColor(0, 145, 180)
                if constraint.constraint_id in self.selected_constraint_ids
                else QColor(*layer.color_rgb)
            )
            label_color = self._drawing_color(label_color)
            dimension_pen = QPen(
                label_color,
                max(
                    2.5 if constraint.constraint_id in self.selected_constraint_ids else 1.0,
                    layer.lineweight_mm * 4,
                ),
            )
            dimension_pen.setStyle(
                {
                    "CONTINUOUS": Qt.PenStyle.SolidLine,
                    "DASHED": Qt.PenStyle.DashLine,
                    "DOTTED": Qt.PenStyle.DotLine,
                    "DASHDOT": Qt.PenStyle.DashDotLine,
                }[layer.linetype]
            )
            extension_pen = QPen(dimension_pen)
            second_extension_pen = QPen(extension_pen)
            style = self.dimension_style_for_constraint(constraint)
            highlighted = (
                constraint.constraint_id in self.dimension_error_constraint_ids
                or constraint.constraint_id in self.selected_constraint_ids
            )
            if style is not None and not highlighted:
                if style.dimension_lineweight != -1:
                    dimension_pen.setWidthF(max(1.0, style.dimension_lineweight / 100 * 4))
                if style.extension_lineweight != -1:
                    extension_pen.setWidthF(max(1.0, style.extension_lineweight / 100 * 4))
                    second_extension_pen.setWidthF(extension_pen.widthF())
                if style.dimension_color != 256:
                    dimension_pen.setColor(
                        indexed_color(style.dimension_color, dark=self._drawing_dark_theme)
                    )
                if style.extension_color != 256:
                    extension_pen.setColor(
                        indexed_color(style.extension_color, dark=self._drawing_dark_theme)
                    )
                    second_extension_pen.setColor(extension_pen.color())
                if style.text_color != 256:
                    label_color = indexed_color(style.text_color, dark=self._drawing_dark_theme)
                pen_styles = {
                    "CONTINUOUS": Qt.PenStyle.SolidLine,
                    "DASHED": Qt.PenStyle.DashLine,
                    "DOTTED": Qt.PenStyle.DotLine,
                    "DASHDOT": Qt.PenStyle.DashDotLine,
                }
                if style.dimension_linetype != "BYLAYER":
                    dimension_pen.setStyle(pen_styles[style.dimension_linetype])
                if style.extension_linetype_first != "BYLAYER":
                    extension_pen.setStyle(pen_styles[style.extension_linetype_first])
                if style.extension_linetype_second != "BYLAYER":
                    second_extension_pen.setStyle(pen_styles[style.extension_linetype_second])
            if any(reference.entity_id not in entities for reference in constraint.references):
                continue
            anchor = self.constraint_anchor(constraint, entities)
            if anchor is None:
                continue
            if constraint.kind in DIMENSION_KINDS:
                if constraint.value is None:
                    continue
                label = self.dimension_display_text(constraint)
                painter.setFont(self.dimension_label_font(constraint))
            else:
                label = glyphs.get(constraint.kind, "?")
                painter.setFont(label_font)
            layout = self.dimension_layout(constraint, entities)
            if layout is not None:
                painter.setPen(dimension_pen)
                self._draw_dimension_lines(
                    painter,
                    layout,
                    constraint.scale,
                    constraint,
                    extension_pen=extension_pen,
                    second_extension_pen=second_extension_pen,
                )
                if not constraint.driving:
                    label = f"({label})"
            if constraint.kind not in DIMENSION_KINDS and not self.constraint_markers_visible:
                continue
            rect = label_rectangles.get(constraint.constraint_id)
            if rect is None:
                continue
            painter.setPen(QPen(label_color, 1.0))
            if constraint.kind in DIMENSION_KINDS:
                painter.fillRect(
                    rect,
                    QColor(32, 40, 48, 235)
                    if self._drawing_dark_theme
                    else QColor(255, 255, 255, 235),
                )
            else:
                painter.setBrush(
                    QColor(39, 55, 58, 235)
                    if self._drawing_dark_theme
                    else QColor(240, 253, 250, 235)
                )
                painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def track_crosshair_pointer(self, position: QPoint) -> None:
        if self.select_committed_entities:
            self._crosshair_position = position
            self.update()

    def set_crosshair_style(self, style: str) -> None:
        if style not in {"short", "full"}:
            raise ValueError("无效的二维光标样式。")
        self.crosshair_style = style
        self.update()

    def set_constraint_markers_visible(self, visible: bool) -> None:
        self.constraint_markers_visible = visible
        self.update()

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        if self.select_committed_entities:
            self._crosshair_position = event.position().toPoint()
            self.update()
        super().enterEvent(event)

    @override
    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(
            self.rect(), QColor("#202830") if self._drawing_dark_theme else Qt.GlobalColor.white
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        origin = self.local_to_screen((0.0, 0.0))
        if self.grid_visible:
            painter.setPen(
                QPen(
                    QColor(92, 108, 122) if self._drawing_dark_theme else QColor(170, 180, 190),
                    2.0,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            grid_mm = self.grid_spacing_mm()
            left, top = self.screen_to_local(QPointF(0.0, 0.0))
            right, bottom = self.screen_to_local(QPointF(self.width(), self.height()))
            for column in range(math.ceil(left / grid_mm), math.floor(right / grid_mm) + 1):
                for row in range(math.ceil(bottom / grid_mm), math.floor(top / grid_mm) + 1):
                    painter.drawPoint(self.local_to_screen((column * grid_mm, row * grid_mm)))
        if not self.select_committed_entities:
            painter.setPen(QPen(Qt.GlobalColor.gray, 1.4))
            painter.drawLine(0, origin.y(), self.width(), origin.y())
            painter.drawLine(origin.x(), 0, origin.x(), self.height())
        for raster in self.drawing_rasters:
            self._draw_raster(painter, raster)
        if self.tool in {"修剪", "延伸"}:
            painter.save()
            painter.setPen(QPen(QColor(130, 110, 160), 1.0, Qt.PenStyle.DashLine))
            for identity, path in self.spatial_boundary_paths():
                painter.setPen(
                    QPen(
                        QColor(0, 120, 140)
                        if identity in self.selected_entity_ids
                        else QColor(130, 110, 160),
                        2.0 if identity in self.selected_entity_ids else 1.0,
                        Qt.PenStyle.DashLine,
                    )
                )
                for first, second in zip(path, path[1:], strict=False):
                    painter.drawLine(self.local_to_screen(first), self.local_to_screen(second))
                if all(math.dist(path[0], point) <= 1e-9 for point in path[1:]):
                    painter.drawEllipse(self.local_to_screen(path[0]), 3, 3)
            if self.spatial_boundaries:
                painter.setPen(QColor(100, 85, 130))
                label = (
                    "异面参考（虚线）：真实三维求交"
                    if self.line_edit_projection_mode == 0
                    else "异面参考（虚线）：按草图视图投影"
                )
                painter.drawText(12, 34, label)
            painter.restore()
        array_preview_ids = {entity.entity_id for entity, _layer in self.array_spacing_preview}
        if self._array_spacing_drag is not None:
            array_preview_ids.update(self._array_spacing_drag.hidden_ids)
        dimension_highlights = {
            reference.entity_id
            for constraint in self.dimension_constraints()
            if constraint.constraint_id in self.selected_constraint_ids
            for reference in constraint.references
        }
        for entity, layer in self.background_entities:
            if (
                self._line_edit_preview_original is not None
                and entity.entity_id == self._line_edit_preview_original.entity_id
            ):
                continue
            painter.save()
            if entity.entity_id in array_preview_ids:
                painter.setOpacity(0.25)
            self._draw_entity(
                painter,
                entity,
                layer=layer,
                highlighted=self.select_committed_entities
                and (
                    entity.entity_id in self.selected_entity_ids
                    or entity.entity_id in dimension_highlights
                    or entity.entity_id == self._hovered_entity_id
                ),
            )
            painter.restore()
            if (
                self.select_committed_entities
                and entity.entity_id in self.selected_entity_ids
                and layer.displayed
                and not layer.locked
            ):
                painter.save()
                painter.setPen(QPen(QColor(0, 100, 110), 1.0))
                painter.setBrush(QColor(225, 250, 250))
                for reference, handle in self._entity_handles(entity):
                    painter.setBrush(
                        QColor(255, 170, 30)
                        if reference.index is not None
                        and self.active_property_vertex == (entity.entity_id, reference.index)
                        else QColor(225, 250, 250)
                    )
                    screen = self.local_to_screen(handle)
                    painter.drawRect(QRectF(screen.x() - 4.0, screen.y() - 4.0, 8.0, 8.0))
                painter.restore()
        for entity, layer in self.saved_handle_preview:
            self._draw_entity(painter, entity, layer=layer, highlighted=True)
        for entity, layer in self.array_spacing_preview:
            self._draw_entity(painter, entity, layer=layer, highlighted=True)
        for entity in self.entities:
            if (
                self._line_edit_preview_original is not None
                and entity.entity_id == self._line_edit_preview_original.entity_id
            ):
                continue
            painter.save()
            if (
                self._transform_operation is not None
                and not self._transform_copies_source()
                and self._transform_preview
                and entity.entity_id in self.selected_entity_ids
            ):
                painter.setOpacity(0.25)
            self._draw_entity(
                painter,
                entity,
                highlighted=entity.entity_id in self.selected_entity_ids
                or entity.entity_id in dimension_highlights
                or entity.entity_id == self._hovered_entity_id,
            )
            painter.restore()
            if (
                entity.entity_id in self.selected_entity_ids
                and self._layer(entity).displayed
                and not self._layer(entity).locked
            ):
                painter.save()
                painter.setPen(QPen(QColor(0, 100, 110), 1.0))
                painter.setBrush(QColor(225, 250, 250))
                for reference, handle in self._entity_handles(entity):
                    painter.setBrush(
                        QColor(255, 170, 30)
                        if reference.index is not None
                        and self.active_property_vertex == (entity.entity_id, reference.index)
                        else QColor(225, 250, 250)
                    )
                    screen = self.local_to_screen(handle)
                    painter.drawRect(QRectF(screen.x() - 4.0, screen.y() - 4.0, 8.0, 8.0))
                painter.restore()
        for preview_entity in self._transform_preview:
            self._draw_entity(painter, preview_entity, highlighted=True)
        for _array, _axis, grip in self.associative_spacing_grips():
            screen = self.local_to_screen(grip)
            painter.setPen(QPen(QColor(10, 95, 155), 1.5))
            painter.setBrush(QColor(245, 185, 40))
            painter.drawEllipse(QRectF(screen.x() - 5, screen.y() - 5, 10, 10))
        for _array, grip in self.associative_count_grips():
            screen = self.local_to_screen(grip)
            painter.setPen(QPen(QColor(10, 95, 155), 1.5))
            painter.setBrush(QColor(245, 185, 40))
            painter.drawRect(QRectF(screen.x() - 5, screen.y() - 5, 10, 10))
        for _array, grip in self.associative_base_grips():
            screen = self.local_to_screen(grip)
            painter.setPen(QPen(QColor(10, 95, 155), 1.5))
            painter.setBrush(QColor(245, 185, 40))
            painter.drawRect(QRectF(screen.x() - 5, screen.y() - 5, 10, 10))
        if self._array_spacing_drag is not None:
            painter.setPen(QPen(QColor(10, 95, 155), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(
                self.local_to_screen(self._array_spacing_drag.anchor),
                self.local_to_screen(self._array_spacing_drag.target),
            )
        if self._transform_base is not None:
            painter.setPen(QPen(QColor(0, 120, 140), 1.2, Qt.PenStyle.DashLine))
            base_screen = self.local_to_screen(self._transform_base)
            painter.drawEllipse(base_screen, 4, 4)
            awaiting_reference_end = (
                self._reference_previous_mode is not None
                and self._transform_reference is not None
                and self._transform_reference_angle is None
            )
            if self._cursor is not None and not awaiting_reference_end:
                if self._rotation_target_points_active and self._rotation_target_first is not None:
                    target_start = self.local_to_screen(self._rotation_target_first)
                    painter.drawEllipse(target_start, 4, 4)
                    painter.drawLine(target_start, self.local_to_screen(self._cursor))
                elif not self._rotation_target_points_active:
                    painter.drawLine(base_screen, self.local_to_screen(self._cursor))
            if self._transform_reference is not None:
                if self._transform_reference_end is not None:
                    painter.drawLine(
                        self.local_to_screen(self._transform_reference),
                        self.local_to_screen(self._transform_reference_end),
                    )
                elif awaiting_reference_end and self._cursor is not None:
                    painter.drawLine(
                        self.local_to_screen(self._transform_reference),
                        self.local_to_screen(self._cursor),
                    )
                elif not awaiting_reference_end:
                    painter.drawLine(base_screen, self.local_to_screen(self._transform_reference))
        if self._line_edit_preview_original is not None:
            painter.save()
            painter.setOpacity(0.28)
            self._draw_entity(painter, self._line_edit_preview_original)
            painter.restore()
            for entity in self._line_edit_preview_result:
                self._draw_entity(painter, entity, highlighted=True)
        elif (
            self.tool in {"修剪", "延伸", "分割"} and self._hovered_line_edit_entity_id is not None
        ):
            hovered = next(
                (
                    entity
                    for entity in self.entities
                    if entity.entity_id == self._hovered_line_edit_entity_id
                ),
                None,
            )
            if hovered is not None:
                self._draw_entity(painter, hovered, highlighted=True)
        if self.dimension_references:
            entities = {e.entity_id: e for e in self.visible_snap_entities()}
            painter.save()
            painter.setPen(QPen(QColor(0, 145, 180), 2.0))
            for reference in self.dimension_references:
                point = self.point_for_reference(reference, entities)
                if point is not None:
                    screen = self.local_to_screen(point)
                    painter.drawRect(QRectF(screen.x() - 4, screen.y() - 4, 8, 8))
                else:
                    segment = self.line_for_reference(reference, entities)
                    if segment is not None:
                        painter.drawLine(
                            self.local_to_screen(segment[0]), self.local_to_screen(segment[1])
                        )
            painter.restore()
        if self._object_tracking_enabled and self._snapping_enabled:
            painter.save()
            painter.setPen(QPen(QColor(0, 145, 100), 1.2, Qt.PenStyle.DashLine))
            for start, end in self._object_tracking_paths:
                painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
            painter.setPen(QPen(QColor(0, 145, 100), 1.6))
            for point in self.acquired_tracking_points:
                position = self.local_to_screen(point)
                painter.drawLine(position.x() - 5, position.y(), position.x() + 5, position.y())
                painter.drawLine(position.x(), position.y() - 5, position.x(), position.y() + 5)
            painter.restore()
        self._draw_constraint_overlays(painter)
        for preview in (
            *self.dimension_linked_previews,
            *((self.dimension_preview,) if self.dimension_preview else ()),
        ):
            painter.save()
            painter.setOpacity(0.65)
            for entity in preview.entities:
                self._draw_entity(
                    painter,
                    entity,
                    layer=preview.layers.get(entity.layer_name),
                    highlighted=True,
                )
            painter.restore()
        if self.quick_measure_regions:
            painter.save()
            painter.setPen(QPen(QColor(20, 155, 75), 1.5))
            for region in self.quick_measure_regions:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for boundary in (region.boundary, *region.holes):
                    points = (
                        tuple(
                            (
                                boundary.center[0] + boundary.radius * math.cos(math.tau * i / 128),
                                boundary.center[1] + boundary.radius * math.sin(math.tau * i / 128),
                            )
                            for i in range(128)
                        )
                        if isinstance(boundary, CircularBoundary)
                        else polyline_sampled_points(boundary)
                        if isinstance(boundary, PolylineEntity)
                        else boundary
                    )
                    clipped = self._clip_area_preview(points)
                    if len(clipped) >= 3:
                        path.moveTo(self._preview_screen_point(clipped[0]))
                        for position in clipped[1:]:
                            path.lineTo(self._preview_screen_point(position))
                        path.closeSubpath()
                painter.fillPath(path, QColor(20, 155, 75, 45))
                painter.drawPath(path)
            painter.restore()
        if self.quick_measure_preview is not None:
            preview = self.quick_measure_preview
            painter.save()
            painter.setPen(QPen(QColor(235, 120, 20), 2.0))
            if isinstance(preview, QuickRadiusMeasurement):
                location = self._preview_screen_point(preview.cursor)
                painter.drawText(location + QPointF(6, -6), f"R {preview.radius_mm:g} mm")
            else:
                first = self._preview_screen_point(preview.first_point)
                second = self._preview_screen_point(preview.second_point)
                painter.drawLine(first, second)
                painter.drawEllipse(first, 3, 3)
                painter.drawEllipse(second, 3, 3)
                text = f"{preview.distance_mm:g} mm"
                if isinstance(preview, LinePairMeasurement):
                    text += f" · {preview.angle_deg:g}°"
                    if preview.right_angle_directions is not None:
                        first_ray, second_ray = preview.right_angle_directions
                        first_offset = QPointF(10 * first_ray[0], -10 * first_ray[1])
                        second_offset = QPointF(10 * second_ray[0], -10 * second_ray[1])
                        corner = first + first_offset + second_offset
                        painter.drawLine(first + first_offset, corner)
                        painter.drawLine(corner, first + second_offset)
                painter.drawText((first + second) / 2 + QPointF(6, -6), text)
            painter.restore()
        if self._zoom_window_first is not None and self._zoom_window_cursor is not None:
            painter.save()
            painter.setPen(QPen(QColor(35, 105, 185), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(35, 105, 185, 35))
            anchor = self._preview_screen_point(self._zoom_window_first)
            painter.drawRect(QRectF(anchor, self._zoom_window_cursor).normalized())
            painter.restore()
        area_points = self._area_preview_points
        if area_points:
            if self._area_preview_cursor is not None:
                area_points = (*area_points, self._area_preview_cursor)
            clipped_points = self._clip_area_preview(area_points)
        else:
            clipped_points = ()
        if clipped_points:
            color = QColor(205, 50, 45) if self._area_preview_subtract else QColor(20, 155, 75)
            painter.save()
            painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
            path = QPainterPath(self._preview_screen_point(clipped_points[0]))
            for point in clipped_points[1:]:
                path.lineTo(self._preview_screen_point(point))
            if len(area_points) >= 3:
                path.closeSubpath()
                fill = QColor(color)
                fill.setAlpha(45)
                painter.fillPath(path, fill)
            painter.drawPath(path)
            painter.restore()
        self._draw_preview(painter)
        if len(self._corner_drag_points) > 1:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.darkCyan, 1.5, Qt.PenStyle.DashLine))
            for first, second in zip(
                self._corner_drag_points, self._corner_drag_points[1:], strict=False
            ):
                painter.drawLine(self.local_to_screen(first), self.local_to_screen(second))
            painter.restore()
        if self._trim_fence_active and self._trim_fence_points:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.darkCyan, 1.5, Qt.PenStyle.DashLine))
            points = tuple(self._trim_fence_points)
            if self._line_crossing_active and self._cursor is not None:
                painter.drawRect(
                    QRectF(
                        self.local_to_screen(points[0]), self.local_to_screen(self._cursor)
                    ).normalized()
                )
            else:
                for first, second in zip(points, points[1:], strict=False):
                    painter.drawLine(self.local_to_screen(first), self.local_to_screen(second))
                if self._cursor is not None:
                    painter.drawLine(
                        self.local_to_screen(points[-1]), self.local_to_screen(self._cursor)
                    )
            painter.restore()
        self._draw_ucs(painter)
        if self._selection_anchor is not None:
            crossing = self._selection_corner.x() < self._selection_anchor.x()
            color = QColor(35, 155, 75) if crossing else QColor(45, 105, 210)
            painter.setPen(
                QPen(color, 1.0, Qt.PenStyle.DashLine if crossing else Qt.PenStyle.SolidLine)
            )
            color.setAlpha(35)
            painter.setBrush(color)
            painter.drawRect(QRectF(self._selection_anchor, self._selection_corner).normalized())
        if self.select_committed_entities and self._crosshair_position is not None:
            point = self._crosshair_position
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(
                QPen(QColor(225, 231, 237) if self._drawing_dark_theme else QColor(40, 40, 40), 1)
            )
            if self.crosshair_style == "full":
                painter.drawLine(0, point.y(), self.width() - 1, point.y())
                painter.drawLine(point.x(), 0, point.x(), self.height() - 1)
            else:
                painter.drawLine(point.x() - 10, point.y(), point.x() + 10, point.y())
                painter.drawLine(point.x(), point.y() - 10, point.x(), point.y() + 10)
        painter.end()

    def _draw_ucs(self, painter: QPainter) -> None:
        origin = self.local_to_screen((0.0, 0.0))
        at_origin = 30 <= origin.x() <= self.width() - 85 and 85 <= origin.y() <= self.height() - 30
        base = origin if at_origin else QPoint(35, self.height() - 35)
        labels = {"XY": ("X", "Y"), "XZ": ("X", "−Z"), "YZ": ("Y", "Z")}.get(
            self.ucs_plane, ("U", "V")
        )
        painter.save()
        painter.setBrush(
            QColor(32, 40, 48, 220) if self._drawing_dark_theme else QColor(255, 255, 255, 220)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        if not at_origin:
            painter.drawRoundedRect(QRectF(base.x() - 10, base.y() - 80, 110, 103), 4, 4)
        colors = {"X": "#b42f35", "Y": "#247443", "Z": "#2865bd", "U": "#b42f35", "V": "#247443"}
        for end, label in ((base + QPoint(55, 0), labels[0]), (base + QPoint(0, -55), labels[1])):
            painter.setPen(QPen(self._drawing_color(QColor(colors[label.removeprefix("−")])), 2.0))
            painter.drawLine(base, end)
            arrow = (
                (QPoint(-7, -4), QPoint(-7, 4))
                if end.y() == base.y()
                else (QPoint(-4, 7), QPoint(4, 7))
            )
            for delta in arrow:
                painter.drawLine(end, end + delta)
            painter.drawText(end + QPoint(5, -6), label)
        painter.setPen(QPen(self._drawing_color(QColor("#334155")), 1.0))
        painter.drawRect(base.x() - 3, base.y() - 3, 6, 6)
        painter.drawText(base + QPoint(8, 17), "O · UCS" if at_origin else "UCS · 原点屏外")
        painter.restore()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self.clipboard_paste_active:
            self._suppress_clipboard_context = True
            self._clipboard_paste = None
            self._clipboard_raster = None
            self._clipboard_rasters = ()
            self._clipboard_mixed_images = ()
            self._clipboard_mixed_revision = None
            self.message = "已取消粘贴，图形未修改。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._suppress_clipboard_context = False
        if self._array_spacing_drag is not None:
            event.accept()
            return
        if self._saved_handle_drag is not None:
            event.accept()
            return
        if self._line_edit_erasing and self._selection_anchor is None:
            if event.button() == Qt.MouseButton.RightButton:
                self._finish_line_edit_erase()
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                point = self.screen_to_local(event.position())
                if self._hit_entity_at(point) is None:
                    self._begin_selection_box(event)
                else:
                    self._select_at(point, additive=True)
                    self.message = "选择要删除的对象；Enter / 右键确认，Esc 取消。"
                    self.changed.emit()
                event.accept()
                return
        if self._trim_fence_active:
            if event.button() == Qt.MouseButton.RightButton:
                self._finish_trim_fence()
            elif event.button() == Qt.MouseButton.LeftButton:
                point = self.screen_to_local(event.position())
                self._add_trim_fence_point(point)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.dynamic_click_guard is not None
            and not self.dynamic_click_guard()
        ):
            event.accept()
            return
        if self._line_edit_selecting_boundaries and self._selection_anchor is None:
            if event.button() == Qt.MouseButton.RightButton:
                self._finish_line_edit_boundary_selection()
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                point = self.screen_to_local(event.position())
                spatial_id = self._hit_spatial_boundary_at(point)
                if spatial_id is not None and self._hit_entity_at(point) is None:
                    if spatial_id in self.selected_entity_ids:
                        self.selected_entity_ids.remove(spatial_id)
                    else:
                        self.selected_entity_ids.add(spatial_id)
                    self.message = "选择边界；Enter / 右键确认，Esc 取消。"
                    self.changed.emit()
                    self.update()
                    event.accept()
                    return
                if self._hit_entity_at(point) is None:
                    self._begin_selection_box(event)
                    event.accept()
                    return
                self._select_at(point, additive=True)
                self.message = "选择边界；Enter / 右键确认，Esc 取消。"
                self.changed.emit()
                event.accept()
                return
        if self._selection_anchor is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._finish_selection_box(event.position())
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self._cancel_selection_box()
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._cancel_selection_box()
        if self._transform_operation is not None and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            if event.button() == Qt.MouseButton.RightButton:
                self._confirm_transform_default()
            else:
                raw = self.screen_to_local(event.position())
                target = self._hit_entity_at(raw) if self._transform_selecting else None
                if (
                    self._transform_selecting
                    and self.selected_raster_id is not None
                    and target is not None
                    and self._transform_operation
                    not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
                ):
                    self.message = "暂不能同时选择图片和其他对象，请按 Enter 继续。"
                    self.changed.emit()
                    event.accept()
                    return
                if self._transform_selecting and target is None:
                    image = next(
                        (
                            item
                            for item in reversed(self.drawing_rasters)
                            if self.layer_table.get(item.layer_name).displayed
                            and not self.layer_table.get(item.layer_name).locked
                            and self._raster_contains(item, raw)
                        ),
                        None,
                    )
                    if image is not None:
                        if (self.selected_entity_ids or self.selected_constraint_ids) and (
                            self._transform_operation
                            not in {"move", "scale", "rotate", "mirror", "copy", "erase"}
                            or (
                                self.selected_constraint_ids
                                and self._transform_operation != "erase"
                            )
                        ):
                            self.message = "暂不能同时选择图片和其他对象，请按 Enter 继续。"
                            self.changed.emit()
                            event.accept()
                            return
                        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                            self.selected_raster_ids.discard(image.image_id)
                        else:
                            self.selected_raster_ids.add(image.image_id)
                        self.message = (
                            f"已选择 {len(self.selected_raster_ids)} 张图片；Enter / 右键结束选择。"
                        )
                        self.changed.emit()
                        self.update()
                        event.accept()
                        return
                    self._begin_selection_box(event)
                    event.accept()
                    return
                if (
                    self._transform_selecting
                    and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    self._select_at(raw, additive=True, subtractive=True)
                    event.accept()
                    return
                point, _kind = self._transform_pointer_point(
                    raw,
                    disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._transform_point(point, commit=True)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self.tool == "对象相切选择":
            self.keyPressEvent(
                QKeyEvent(
                    QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
                )
            )
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self.tool in {
            "直线",
            "多段线",
            "样条曲线",
            "单点打断",
        }:
            self.keyPressEvent(
                QKeyEvent(
                    QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
                )
            )
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.RightButton
            and self.tool in {"二维圆角", "二维倒角"}
            and not self.has_active_edit_gesture
        ):
            self.set_tool("选择元素")
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start_view = self._view_state()
            self._last_mouse = event.position().toPoint()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.screen_to_local(event.position())
            if self.clipboard_paste_active:
                point, _kind = self._placement_point(point)
                self._place_clipboard(point)
                event.accept()
                return
            if (
                self.tool in {"二维圆角", "二维倒角"}
                and not self.has_active_edit_gesture
                and not self.circle_fillet_radius_pending
                and not self.circle_fillet_trim_pending
                and not self._fillet_candidate_pending
            ):
                self._corner_drag_points = [point]
                self._corner_drag_shift = bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                self._corner_drag_revision = (
                    self.source_revision_provider() if self.source_revision_provider else None
                )
                event.accept()
                return
            if self.tool == "直线" and self.line_tangent_active:
                if not self._line_tangent_awaiting and self._line_tangent_target_at(point) is None:
                    point, self._snap_kind = self._placement_point(
                        point,
                        temporarily_disable_snapping=bool(
                            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        ),
                    )
                self._pick_line_tangent_source(point)
                event.accept()
                return
            if self.tool == "圆弧" and self.arc_ttr_active:
                self._pick_arc_ttr_source(point)
                event.accept()
                return
            if self.tool == "圆" and self.circle_ttr_active:
                self._pick_circle_ttr_source(point)
                event.accept()
                return
            if self.tool == "二维倒角":
                self._chamfer_pick(
                    point,
                    temporary_zero=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                event.accept()
                return
            if self.tool == "二维圆角":
                self._circle_fillet_pick(
                    point,
                    temporary_zero=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                event.accept()
                return
            if self.tool == "修剪":
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self._cursor = point
                    self._accept_point(point, operation_override="延伸")
                    event.accept()
                    return
                self._begin_trim_drag(point)
                self._cursor = point
                self.changed.emit()
                self.update()
                event.accept()
                return
            if self.tool == "延伸" and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._cursor = point
                self._accept_point(point, operation_override="修剪")
                event.accept()
                return
            if self.tool == "选择元素":
                if not event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                ):
                    if self._begin_array_spacing_drag(point):
                        event.accept()
                        return
                    handle = self.control_point_at(point)
                    if handle is not None:
                        self._begin_handle_drag(handle[0], handle[1], handle[2])
                        if (
                            isinstance(handle[0], PolylineEntity | SplineEntity)
                            and handle[1].index is not None
                        ):
                            self.property_vertex_picked.emit(handle[0].entity_id, handle[1].index)
                        event.accept()
                        return
                if self._hit_entity_at(point) is None:
                    image = next(
                        (
                            item
                            for item in reversed(self.drawing_rasters)
                            if self.layer_table.get(item.layer_name).displayed
                            and not self.layer_table.get(item.layer_name).locked
                            and self._raster_contains(item, point)
                        ),
                        None,
                    )
                    if image is not None:
                        additive = bool(
                            event.modifiers()
                            & (
                                Qt.KeyboardModifier.ControlModifier
                                | Qt.KeyboardModifier.ShiftModifier
                            )
                        )
                        if not additive:
                            self.selected_entity_ids.clear()
                            self.selected_constraint_ids.clear()
                        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                            self.selected_raster_ids.discard(image.image_id)
                        elif additive:
                            if image.image_id in self.selected_raster_ids:
                                self.selected_raster_ids.remove(image.image_id)
                            else:
                                self.selected_raster_ids.add(image.image_id)
                        else:
                            self.selected_raster_id = image.image_id
                        self.message = f"已选择 {len(self.selected_raster_ids)} 张图片。"
                        self.changed.emit()
                        self.update()
                        event.accept()
                        return
                    self._begin_selection_box(event)
                    event.accept()
                    return
                if not event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                ):
                    self.selected_raster_id = None
                self._select_at(
                    point,
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                    subtractive=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
            else:
                self._accept_point(
                    point,
                    temporarily_disable_snapping=bool(
                        event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    )
                    and self.tool
                    in {"点", "直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"},
                )
                self.pointer_moved.emit(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        self.track_crosshair_pointer(position)
        if self._corner_drag_points:
            self._corner_drag_points.append(self.screen_to_local(event.position()))
            self.update()
            event.accept()
            return
        if self._array_spacing_drag is not None:
            self._preview_array_spacing_drag(self.screen_to_local(event.position()))
            event.accept()
            return
        self._last_pointer_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._last_pointer_shift:
            self._object_tracking_paths = ()
        if self.line_tangent_active:
            self._cursor = self.screen_to_local(event.position())
            if self._line_tangent_awaiting:
                self._snap_kind = (
                    "待定切点" if self._line_tangent_target_at(self._cursor) is not None else ""
                )
            elif self._line_tangent_target_at(self._cursor) is not None:
                preview = self.previewed_tangent_line
                if preview is not None:
                    self._cursor, self._snap_kind = preview.end_mm, "切点"
                else:
                    self._snap_kind = ""
            else:
                self._cursor, self._snap_kind = self._placement_point(
                    self._cursor,
                    temporarily_disable_snapping=bool(
                        event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    ),
                )
            self.cursor_changed.emit(*self._cursor, self._snap_kind)
            self.pointer_moved.emit(position)
            self.update()
            event.accept()
            return
        if self.arc_ttr_active or self.circle_ttr_active:
            self._cursor = self.screen_to_local(event.position())
            waiting_for_radius = self.arc_ttr_radius_pending or self.circle_ttr_radius_pending
            identity = None if waiting_for_radius else self._hit_entity_at(self._cursor)
            target = next(
                (entity for entity in self.selectable_entities() if entity.entity_id == identity),
                None,
            )
            supported = (
                isinstance(
                    target, LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
                )
                if self.arc_ttr_active
                else isinstance(target, LineEntity | CircleEntity | ArcEntity)
            )
            self._snap_kind = "待定切点" if supported else ""
            self.cursor_changed.emit(*self._cursor, self._snap_kind)
            self.pointer_moved.emit(position)
            self.update()
            event.accept()
            return
        if self._selection_anchor is not None:
            self._selection_corner = event.position()
            self._cursor = self.screen_to_local(event.position())
            self._snap_kind = ""
            mode = (
                "交叉选择（包含或相交）"
                if position.x() < self._selection_anchor.x()
                else "窗口选择（完全包含）"
            )
            self.message = f"{mode} · 指定对角点，Esc 取消。"
            self.cursor_changed.emit(*self._cursor, "")
            self.changed.emit()
            self.update()
            event.accept()
            return
        if self._panning:
            delta = position - self._last_mouse
            self._pan += QPointF(delta)
            self._last_mouse = position
        if self._saved_handle_drag is not None:
            state = self._saved_handle_drag
            if not state.released:
                state.target = self.screen_to_local(event.position())
                if _distance(state.target, state.origin) * self._scale > 3:
                    self._request_saved_handle_preview()
            event.accept()
            return
        if (
            self._drag_reference is not None
            and self._drag_original_entities is not None
            and self._drag_original_constraints is not None
            and self._drag_last_entities is not None
            and self._drag_last_constraints is not None
            and self._drag_entity_id is not None
        ):
            self.entities = list(self._drag_original_entities)
            self.constraints = list(self._drag_original_constraints)
            self._snap_candidates_cache = None
            target, snap_kind = self._drag_target(self.screen_to_local(event.position()))
            updated = self._solve_handle_drag(
                self._drag_original_entities,
                self._drag_original_constraints,
                self._drag_reference,
                target,
            )
            if updated is not None:
                self._drag_last_entities, self._drag_last_constraints = updated
                self.entities = list(self._drag_last_entities)
                self.constraints = list(self._drag_last_constraints)
                self.message = (
                    f"拖动预览中 · {len(self.constraints)} 条关系已保留"
                    if self.constraints
                    else "拖动预览中 · 松开鼠标确认草稿变化"
                )
                if self._drag_branch_warning:
                    self.message += f" · 分支变化：{self._drag_branch_warning}"
            else:
                self.entities = list(self._drag_last_entities)
                self.constraints = list(self._drag_last_constraints)
                if not self.message or self.message.startswith("拖动预览中"):
                    self.message = (
                        "已有草图约束；当前拖动位置无法满足约束。"
                        if self._drag_original_constraints
                        else "当前控制点无法移动到该位置。"
                    )
            self._cursor = target
            self._snap_kind = snap_kind
            self.cursor_changed.emit(*target, snap_kind)
            self.changed.emit()
            self.update()
            event.accept()
            return
        if self._transform_operation is not None:
            raw = self.screen_to_local(event.position())
            self._last_placement_raw = raw
            if self._transform_operation in {"move", "copy"} and not self._transform_selecting:
                self._acquire_object_tracking(raw)
            point, kind = self._transform_pointer_point(
                raw, disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            self._cursor, self._snap_kind = point, kind
            self._transform_point(point, commit=False)
            self.cursor_changed.emit(*point, kind)
            self.update()
            event.accept()
            return
        if self._trim_fence_active:
            self._cursor = self.screen_to_local(event.position())
            self.cursor_changed.emit(*self._cursor, "")
            self.update()
            event.accept()
            return
        if self._line_edit_erasing:
            self._cursor = self.screen_to_local(event.position())
            self._hovered_entity_id = self._hit_entity_at(self._cursor)
            self.cursor_changed.emit(*self._cursor, "")
            self.update()
            event.accept()
            return
        if self._trim_drag_start is not None:
            self._update_trim_drag(self.screen_to_local(event.position()))
            self._cursor = self.screen_to_local(event.position())
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor)
            self._refresh_line_edit_preview(None)
            self.cursor_changed.emit(*self._cursor, "")
            self.update()
            event.accept()
            return
        raw_point = self.screen_to_local(event.position())
        self._last_placement_raw = raw_point
        if self.tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}:
            self._acquire_object_tracking(raw_point)
        self._cursor, self._snap_kind = (
            (raw_point, "")
            if self.tool in {"修剪", "延伸", "分割"}
            else self._placement_point(
                raw_point,
                temporarily_disable_snapping=bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                and self.tool
                in {"点", "直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"},
            )
        )
        if self._first is not None and self.dynamic_point_resolver is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, self._cursor)
                if resolved != self._cursor:
                    self._snap_kind = ""
                self._cursor = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
        if self.tool == "选择元素":
            self._hovered_entity_id = self._hit_entity_at(self._cursor)
        elif self.tool == "修剪":
            temporary_extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._hovered_line_edit_entity_id = (
                self._extend_target_at(self._cursor)
                if temporary_extend
                else self._trim_target_at(self._cursor)
            )
            self._refresh_line_edit_preview("延伸" if temporary_extend else "修剪")
        elif self.tool == "延伸":
            temporary_trim = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._hovered_line_edit_entity_id = (
                self._trim_target_at(self._cursor)
                if temporary_trim
                else self._extend_target_at(self._cursor)
            )
            self._refresh_line_edit_preview("修剪" if temporary_trim else "延伸")
        elif self.tool == "分割":
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor, lines_only=True)
            self._refresh_line_edit_preview(None)
        else:
            self._hovered_line_edit_entity_id = None
            self._refresh_line_edit_preview(None)
            self._hovered_entity_id = None
        self.cursor_changed.emit(*self._cursor, self._snap_kind)
        self.pointer_moved.emit(position)
        self.update()
        event.accept()

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self._crosshair_position = None
        self.update()
        self.pointer_left.emit()
        super().leaveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._corner_drag_points:
            self._finish_corner_drag(self.screen_to_local(event.position()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._array_spacing_drag is not None:
            state = self._array_spacing_drag
            if state.committing:
                event.accept()
                return
            point = self.screen_to_local(event.position())
            if _distance(point, state.origin) * self._scale <= 3:
                self.cancel_array_spacing_drag("阵列夹点未移动。")
            else:
                self._preview_array_spacing_drag(point)
                if (
                    self._array_spacing_drag is state
                    and state.axis == "move"
                    and state.displacement is not None
                ):
                    state.committing = True
                    self.array_move_commit_requested.emit(
                        state.token, state.array, state.displacement, state.revision
                    )
                elif (
                    self._array_spacing_drag is state
                    and state.axis == "count"
                    and state.resized is not None
                ):
                    if state.resized == state.array:
                        self.cancel_array_spacing_drag("阵列数量未变化。")
                    else:
                        state.committing = True
                        self.array_count_commit_requested.emit(
                            state.token, state.array, state.resized, state.revision
                        )
                elif self._array_spacing_drag is state and state.spacing is not None:
                    old = (
                        state.array.row_spacing
                        if state.axis == "row"
                        else state.array.column_spacing
                    )
                    if math.isclose(state.spacing, old, rel_tol=1e-12, abs_tol=1e-10):
                        self.cancel_array_spacing_drag("阵列间距未变化。")
                    else:
                        state.committing = True
                        row = state.spacing if state.axis == "row" else state.array.row_spacing
                        column = (
                            state.spacing if state.axis == "column" else state.array.column_spacing
                        )
                        self.array_spacing_commit_requested.emit(
                            state.token, state.array, row, column, state.revision
                        )
                elif self._array_spacing_drag is state:
                    self.cancel_array_spacing_drag(self.message)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._saved_handle_drag is not None:
            state = self._saved_handle_drag
            state.target = self.screen_to_local(event.position())
            if _distance(state.target, state.origin) * self._scale <= 3:
                self.cancel_saved_handle_drag("控制点未移动。")
            else:
                state.released = True
                self._request_saved_handle_preview()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._selection_anchor is not None:
            delta = event.position() - self._selection_anchor
            if not self._selection_waiting_click and math.hypot(delta.x(), delta.y()) > 4.0:
                self._finish_selection_box(event.position())
            else:
                self._selection_waiting_click = True
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._transform_operation in {"move", "copy"}
            and self._transform_base is not None
            and self._transform_preview
        ):
            raw = self.screen_to_local(event.position())
            point, _kind = self._transform_pointer_point(
                raw, disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            if _distance(point, self._transform_base) * self._scale > 3.0:
                self._transform_point(point, commit=True)
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            if self._pan_start_view is not None:
                self._remember_changed_view(self._pan_start_view)
                self._pan_start_view = None
            self._panning = False
            event.accept()
            return
        if self._trim_fence_active and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._finish_trim_drag():
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_reference is not None:
            self._finish_handle_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def move_selected_raster(self) -> None:
        """Move the selected picture by specifying its lower-left coordinates."""
        raster = next(
            (item for item in self.drawing_rasters if item.image_id == self.selected_raster_id),
            None,
        )
        if raster is None or self.commit_raster_edit is None:
            return
        x, accepted = QInputDialog.getDouble(
            self, "移动图片", "左下角 X（毫米）：", raster.origin_mm[0], -1e12, 1e12, 3
        )
        if not accepted:
            return
        y, accepted = QInputDialog.getDouble(
            self, "移动图片", "左下角 Y（毫米）：", raster.origin_mm[1], -1e12, 1e12, 3
        )
        if not accepted or (x, y) == raster.origin_mm:
            return
        try:
            self.commit_raster_edit("update", replace(raster, origin_mm=(x, y)))
            self.message = "已移动图片。"
        except ValueError as exc:
            self.message = str(exc)
        self.changed.emit()
        self.update()

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self._suppress_clipboard_context and event.reason() == QContextMenuEvent.Reason.Mouse:
            self._suppress_clipboard_context = False
            event.accept()
            return
        self._suppress_clipboard_context = False
        if (
            not self.select_committed_entities
            or self.tool != "选择元素"
            or self.has_active_edit_gesture
            or self.has_pending_geometry
        ):
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        selected_image = next(
            (item for item in self.drawing_rasters if item.image_id == self.selected_raster_id),
            None,
        )
        single_image = selected_image is not None and len(self.selected_raster_ids) == 1
        move_action = menu.addAction("移动图片") if single_image else None
        resize_action = menu.addAction("调整图片大小") if single_image else None
        delete_action = menu.addAction("删除\tDelete")
        delete_action.setEnabled(
            bool(
                self.selected_entity_ids or self.selected_constraint_ids or self.selected_raster_id
            )
        )
        copy_action = menu.addAction("复制\tCtrl+C")
        copy_action.setEnabled(bool(self.selected_entity_ids or self.selected_raster_id))
        paste_action = menu.addAction("粘贴\tCtrl+V")
        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        paste_action.setEnabled(
            mime is not None
            and (
                mime.hasFormat(DRAWING_CLIPBOARD_MIME)
                or mime.hasFormat(DRAWING_MIXED_CLIPBOARD_MIME)
                or mime.hasFormat(DRAWING_RASTER_GROUP_MIME)
                or mime.hasImage()
            )
        )
        action = cast("QAction | None", menu.exec(event.globalPos()))
        if move_action is not None and action is move_action:
            self.move_selected_raster()
        elif resize_action is not None and action is resize_action and selected_image is not None:
            width, accepted = QInputDialog.getDouble(
                self,
                "调整图片大小",
                "图片宽度（毫米）：",
                selected_image.width_mm,
                0.001,
                1000000.0,
                3,
            )
            if accepted and self.commit_raster_edit is not None:
                try:
                    self.commit_raster_edit(
                        "update",
                        replace(
                            selected_image,
                            width_mm=width,
                            height_mm=selected_image.height_mm * width / selected_image.width_mm,
                        ),
                    )
                    self.message = "已调整图片大小。"
                except ValueError as exc:
                    self.message = str(exc)
                self.changed.emit()
        elif action is delete_action:
            self.delete_selected()
        elif action is copy_action:
            self.copy_to_clipboard()
        elif action is paste_action:
            self.begin_clipboard_paste()
        if action is not None:
            self.setFocus()
        event.accept()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._array_spacing_drag is not None:
            event.accept()
            return
        self._cancel_selection_box()
        if self._pan_start_view is not None:
            self._remember_changed_view(self._pan_start_view)
        previous = self._view_state()
        before = self.screen_to_local(event.position())
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._scale = min(60.0, max(1e-6, self._scale * factor))
        after = self.local_to_screen(before)
        self._pan += event.position() - QPointF(after)
        self._remember_changed_view(previous)
        if self._pan_start_view is not None:
            self._pan_start_view = self._view_state()
        self.update()
        event.accept()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy) and self.select_committed_entities:
            self.copy_to_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste) and self.select_committed_entities:
            self.begin_clipboard_paste()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.clipboard_paste_active:
            self._clipboard_paste = None
            self._clipboard_raster = None
            self._clipboard_rasters = ()
            self._clipboard_mixed_images = ()
            self._clipboard_mixed_revision = None
            self.message = "已取消粘贴，图形未修改。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._corner_drag_points:
            self._corner_drag_points.clear()
            self.message = "已取消拖动选取；图形未变化。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.clear_object_tracking()
        if event.key() == Qt.Key.Key_Shift and (
            self.snap_preview_available
            or (
                self._object_tracking_enabled
                and self._object_tracking_shift_to_acquire
                and self._transform_operation is None
                and self.tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
            )
        ):
            self.set_temporary_snap_disabled(True)
            event.accept()
            return
        if self._line_edit_erasing:
            if event.key() == Qt.Key.Key_Escape:
                self._line_edit_erasing = False
                self._cancel_selection_box()
                self.selected_entity_ids.clear()
                self.message = "已取消删除选择；草图未修改。"
                self.changed.emit()
                self.update()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if self._selection_anchor is not None:
                    self._finish_selection_box(self._selection_corner)
                else:
                    self._finish_line_edit_erase()
                event.accept()
                return
        if self._trim_fence_active:
            if event.key() == Qt.Key.Key_Escape:
                self._trim_fence_active = False
                if not self._cancel_trim_drag():
                    self.message = "已取消修剪围栏；草图未修改。"
                    self.changed.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._finish_trim_fence()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self.cancel_array_spacing_drag():
            event.accept()
            return
        if self._array_spacing_drag is not None:
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.cancel_saved_handle_drag():
            event.accept()
            return
        if self._saved_handle_drag is not None:
            event.accept()
            return
        if self.dynamic_key_handler is not None and self.dynamic_key_handler(event):
            event.accept()
            return
        if self._line_edit_selecting_boundaries:
            if event.key() == Qt.Key.Key_Escape and self._cancel_selection_box():
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._line_edit_selecting_boundaries = False
                self.selected_entity_ids.clear()
                self.message = "已取消边界选择；使用全部可见边界。"
                self.changed.emit()
                self.update()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if self._selection_anchor is not None:
                    self._finish_selection_box(self._selection_corner)
                else:
                    self._finish_line_edit_boundary_selection()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self._cancel_circle_fillet():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_arc_ttr():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_circle_ttr():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_line_tangent():
            event.accept()
            return
        if self.tool == "对象相切选择" and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.set_tool("选择元素")
            self.object_tangency_options_requested.emit()
            event.accept()
            return
        if self.tool == "对象相切选择" and event.key() == Qt.Key.Key_Escape:
            self.set_tool("选择元素")
            self.selected_entity_ids.clear()
            self.clear_selected_tangent_segments()
            self.message = "已取消对象相切选择。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if self.tool == "单点打断" and event.key() in {
            Qt.Key.Key_Escape,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        }:
            self._break_at_point_target = None
            self.set_tool("选择元素")
            self.message = "单点打断已结束；图元未修改。"
            self.changed.emit()
            event.accept()
            return
        if (
            self.tool in {"二维圆角", "二维倒角"}
            and not self.has_active_edit_gesture
            and event.key()
            in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
        ):
            self.set_tool("选择元素")
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_selection_box():
            event.accept()
            return
        if (
            self._selection_anchor is not None
            and self._transform_operation is None
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._finish_selection_box(self._selection_corner)
            event.accept()
            return
        if self._transform_operation is not None:
            if (
                self.awaiting_mirror_erase
                and event.key() in (Qt.Key.Key_Y, Qt.Key.Key_N)
                and not event.modifiers()
                & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            ):
                self.confirm_mirror_erase(event.key() == Qt.Key.Key_Y)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_transform()
                event.accept()
                return
            if self._transform_operation == "copy" and event.key() == Qt.Key.Key_U:
                self.undo_copy_placement()
                event.accept()
                return
            if self._transform_operation == "scale" and self.scale_center is not None:
                modifiers = event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
                if not modifiers and event.key() in (Qt.Key.Key_C, Qt.Key.Key_R, Qt.Key.Key_P):
                    if event.key() == Qt.Key.Key_C:
                        self.enable_scale_copy()
                    elif event.key() == Qt.Key.Key_R:
                        self.start_scale_reference()
                    else:
                        self.start_scale_target_points()
                    self._transform_angle_text = ""
                    event.accept()
                    return
                if self.scale_target_points_active:
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_Backspace:
                    self._transform_angle_text = self._transform_angle_text[:-1]
                elif event.text() and all(char in "0123456789+-." for char in event.text()):
                    self._transform_angle_text += event.text()
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    try:
                        value = (
                            self.scale_default_factor
                            if not self._transform_angle_text and not self.scale_reference_active
                            else float(self._transform_angle_text)
                        )
                        if not math.isfinite(value) or value <= 0:
                            raise ValueError
                        accepted = (
                            self.apply_scale_length(value)
                            if self.scale_reference_active
                            else self.apply_scale_factor(value)
                        )
                    except ValueError:
                        accepted = False
                        self.message = "请输入有效的正数；Backspace 修改，Esc 取消。"
                        self.changed.emit()
                    if accepted:
                        self._transform_angle_text = ""
                    event.accept()
                    return
                else:
                    super().keyPressEvent(event)
                    return
                self.message = f"缩放数值：{self._transform_angle_text}；Enter 确认。"
                self.changed.emit()
                event.accept()
                return
            if self._transform_operation == "rotate" and self._transform_base is not None:
                if event.key() == Qt.Key.Key_C and not event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                ):
                    self.enable_rotation_copy()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_R and not event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                ):
                    self.start_rotation_reference()
                    event.accept()
                    return
                if (
                    self.rotation_uses_reference
                    and event.key() == Qt.Key.Key_P
                    and not event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                ):
                    self.start_rotation_target_points()
                    event.accept()
                    return
                if self._rotation_target_points_active:
                    self.message = self._transform_point_hint()
                    self.changed.emit()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_Backspace:
                    self._transform_angle_text = self._transform_angle_text[:-1]
                elif event.text() and all(char in "0123456789+-." for char in event.text()):
                    self._transform_angle_text += event.text()
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    if not self._transform_angle_text and not self.rotation_uses_reference:
                        self.apply_rotation_angle(self.rotation_default_angle)
                    if (
                        not self._transform_angle_text
                        and self.rotation_uses_reference
                        and self._reference_previous_mode is not None
                    ):
                        if self._transform_reference_angle is not None:
                            self.apply_rotation_target_angle(0.0)
                        elif self._transform_reference is None:
                            self.set_rotation_reference_angle(0.0)
                        else:
                            self.message = "参考旋转：请指定第二参考点。"
                            self.changed.emit()
                    if self._transform_angle_text:
                        try:
                            angle = float(self._transform_angle_text)
                            if not math.isfinite(angle):
                                raise ValueError("角度必须是有限数值。")
                        except ValueError:
                            self.message = "请输入有效旋转角度；Backspace 修改，Esc 取消。"
                            self.changed.emit()
                        else:
                            if self.rotation_uses_reference:
                                if self.rotation_reference_angle is None:
                                    self.set_rotation_reference_angle(angle)
                                    self._transform_angle_text = ""
                                else:
                                    self.apply_rotation_target_angle(angle)
                            else:
                                self.apply_rotation_angle(angle)
                    event.accept()
                    return
                else:
                    super().keyPressEvent(event)
                    return
                self.message = f"旋转角度：{self._transform_angle_text}°；Enter 确认。"
                self.changed.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._confirm_transform_default()
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Undo):
            if self.preserve_document_layers:
                self.undo_requested.emit()
            else:
                self.undo_last_operation()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo) or (
            event.key() == Qt.Key.Key_Y and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            if self.preserve_document_layers:
                self.redo_requested.emit()
            else:
                self.redo_last_operation()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Shift and self.tool == "修剪" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._extend_target_at(self._cursor)
            self._refresh_line_edit_preview("延伸")
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Shift and self.tool == "延伸" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor)
            self._refresh_line_edit_preview("修剪")
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_trim_drag():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_handle_drag():
            event.accept()
            return
        if self.tool in {"直线", "多段线"} and event.key() == Qt.Key.Key_C:
            self.close_chain()
            event.accept()
            return
        if self.tool == "直线" and self.continuous_lines and self._points:
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape):
                self.end_line_chain()
                event.accept()
                return
            if event.key() == Qt.Key.Key_U:
                self.undo_last_operation()
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) and self.tool in {
            "多段线",
            "样条曲线",
        }:
            self.finish_polyline()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.has_pending_geometry:
            self._first = None
            self._points.clear()
            self._polyline_bulges.clear()
            self.polyline_arc_mode = False
            self._polyline_arc_middle = None
            self._polyline_arc_second_pending = False
            self._reset_polyline_arc_option()
            self._snap_kind = ""
            self.message = "已清除未完成图元；草图草稿仍保留。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and (
            self.selected_entity_ids or self.selected_constraint_ids or self.selected_raster_id
        ):
            self.selected_raster_id = None
            self.selected_entity_ids.clear()
            self.selected_constraint_ids.clear()
            self.clear_selected_tangent_segments()
            self.message = "已清除选择。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.continuous_lines:
            self.set_tool("选择元素")
            event.accept()
            return
        super().keyPressEvent(event)

    @override
    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Shift:
            self.set_temporary_snap_disabled(False)
            if self.snap_preview_available:
                event.accept()
                return
        if event.key() == Qt.Key.Key_Shift and self.tool == "延伸" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._extend_target_at(self._cursor)
            self._refresh_line_edit_preview("延伸")
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Shift and self.tool == "修剪" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor)
            self._refresh_line_edit_preview("修剪")
            self.update()
            event.accept()
            return
        super().keyReleaseEvent(event)


class SketchEditorDialog(QDialog):
    """Non-modal drawing window; Finish returns data and Cancel leaves Bus untouched."""

    view_3d_requested = Signal()
    layer_change_requested = Signal(object)
    assign_selection_layer_requested = Signal(object, str)
    assign_selection_construction_requested = Signal(object, bool)
    document_undo_requested = Signal()
    document_redo_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        constraint_preview: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult]
        | None = None,
        constraint_update_preview: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult]
        | None = None,
        can_finish: Callable[[], bool] | None = None,
        drag_preview: Callable[
            [Sketch, SketchGeometryReference, Point2D], SketchConstraintSolveResult
        ]
        | None = None,
        attached_frame: WorkPlaneFrame | None = None,
        support_face: SketchSupportFace | None = None,
        continuous_lines: bool = False,
        select_committed_entities: bool = False,
        document_metadata: Callable[[], Mapping[str, str]] | None = None,
        measure_planar_region: Callable[
            [tuple[SketchEntity, ...], Point2D], SampledMeasuredRegion | None
        ]
        | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("草图")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1080, 720)
        self.result_sketch: Sketch | None = None
        self.result_associative_arrays: tuple[AssociativeRectArray, ...] = ()
        self._constraint_preview = constraint_preview
        self._constraint_update_preview = constraint_update_preview
        self._can_finish = can_finish
        self._drag_preview = drag_preview
        self._document_metadata = document_metadata
        self._drag_preview_sketch_id = uuid4().hex
        self._selected_plane = "所选面" if support_face is not None else "XY"
        self._attached_frame = attached_frame
        self._support_face = support_face
        self._initial_support_face = support_face
        self._context_sketches: tuple[Sketch, ...] = ()
        self._context_frame: WorkPlaneFrame | None = None
        self.layer_table = SketchLayerTable().add(DEFAULT_DIM_LAYER)
        self.dimension_layer = "DIM"
        self.document_layer_mode = False
        self.layer_history_boundaries: dict[int, int] = {}
        self.layer_history_redo: list[tuple[int, int]] = []
        self.mixed_draft_history: dict[int, tuple[int, int, str | None]] = {}
        self.active_layer_manager: DrawingLayerPanel | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.toolbar_host = QMainWindow(self)
        self.toolbar_host.setWindowFlags(Qt.WindowType.Widget)
        outer.addWidget(self.toolbar_host)
        central = QWidget()
        self.toolbar_host.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        self._suspended_toolbar_state: QByteArray | None = None
        self.drawing_toolbar = self._make_toolbar("绘图", "draftingDrawingToolbar")
        self.modify_toolbar = self._make_toolbar("修改", "draftingModifyToolbar")
        self.dimension_toolbar = self._make_toolbar("尺寸标注", "draftingDimensionToolbar")
        self._measurement_available = select_committed_entities
        self.measurement_toolbar = self._make_toolbar("测量", "draftingMeasurementToolbar")
        self.reset_toolbar_layout()
        layer_bar = QHBoxLayout()
        root.addLayout(layer_bar)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        self.tool_panel = QScrollArea()
        self.tool_panel.setWidgetResizable(True)
        self.tool_panel.setMinimumWidth(250)
        self.tool_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel.setStyleSheet(
            "QToolButton:checked { background: #dceafa; border: 1px solid #2472ba; }"
        )
        self.tool_panel.setWidget(panel)
        self.parameter_tabs = QTabWidget()
        self.parameter_dock = QDockWidget("二维功能", self.toolbar_host)
        self.parameter_dock.setObjectName("draftingParameterDock")
        self.parameter_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.parameter_dock.setWidget(self.parameter_tabs)
        self.toolbar_host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock)
        self.toolbar_host.resizeDocks([self.parameter_dock], [270], Qt.Orientation.Horizontal)
        self.navigator = SketchNavigator()
        self.navigator.selection_requested.connect(self._select_navigation)
        self.navigator.constraint_activated.connect(self._activate_navigation_constraint)
        drawing = QVBoxLayout()
        body.addLayout(drawing, 1)
        controls = QGridLayout()
        self.plane_combo = QComboBox()
        self.plane_combo.addItems(("XY", "XZ", "YZ"))
        if support_face is not None and attached_frame is not None:
            self.plane_combo.addItem("所选面")
            self.plane_combo.setCurrentText("所选面")
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(
            (
                "直线",
                "选择元素",
                "多段线",
                "圆",
                "圆弧",
                "矩形",
                "多边形",
                "样条曲线",
                "修剪",
                "延伸",
                "分割",
            )
        )
        if select_committed_entities:
            self.tool_combo.addItems(("点", "二维圆角", "二维倒角", "单点打断"))
        self.snap_check = QCheckBox("捕捉")
        self.snap_check.setChecked(True)
        self.snap_check.setToolTip(
            "吸附到 UCS 原点与既有几何；绘图时按住 Shift 临时关闭对象和栅格捕捉。"
            "候选同距离时优先级为端点、交点、垂足、切点、圆心、中点、中心。"
        )
        self.grid_visible_check = QCheckBox("网格 F7")
        self.grid_visible_check.setChecked(True)
        self.grid_visible_check.setToolTip("显示/隐藏点阵网格（F7），不改变栅格捕捉。")
        self.grid_shortcut = QShortcut(QKeySequence("F7"), self)
        self.grid_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.grid_shortcut.activated.connect(self.grid_visible_check.toggle)
        self.grid_snap_check = QCheckBox("捕捉" if select_committed_entities else "栅格捕捉")
        self.grid_snap_check.setToolTip(
            "启用所选捕捉模式；对象捕捉优先。按住 Shift 临时关闭所有捕捉。"
        )
        self.snap_type_combo = QComboBox()
        self.snap_type_combo.addItems(("矩形栅格", "极轴距离"))
        self.snap_type_combo.setToolTip("选择矩形栅格或沿极轴方向的距离捕捉。")
        self.polar_spacing_field = QDoubleSpinBox()
        self.polar_spacing_field.setRange(0.0, 1_000_000.0)
        self.polar_spacing_field.setDecimals(4)
        self.polar_spacing_field.setSuffix(" mm")
        self.polar_spacing_field.setMaximumWidth(100)
        self.polar_spacing_field.setToolTip("极轴捕捉距离；0 使用当前栅格间距。")
        self.orthogonal_check = QCheckBox("正交")
        self.orthogonal_check.setToolTip(
            "直线、多段线和二维圆弧按位移较大的方向锁定水平/竖直；捕捉到既有几何时保留捕捉点。"
        )
        self.polar_check = QCheckBox("极轴")
        self.polar_check.setToolTip(
            "直线、多段线、二维圆弧和移动/复制接近指定角度时沿极轴追踪；与正交互斥。"
        )
        self.object_tracking_check = QCheckBox("对象追踪")
        self.object_tracking_check.setToolTip("悬停对象捕捉点，按设置沿正交或极轴方向追踪。")
        self.object_tracking_angle_combo = QComboBox()
        self.object_tracking_angle_combo.addItems(("仅正交", "使用极轴角度"))
        self.object_tracking_angle_combo.setToolTip("选择对象追踪使用正交或极轴追踪角度。")
        self.object_tracking_acquisition_combo = QComboBox()
        self.object_tracking_acquisition_combo.addItems(("自动获取", "按 Shift 获取"))
        self.polar_angle_field = QDoubleSpinBox()
        self.polar_angle_field.setRange(0.01, 360.0)
        self.polar_angle_field.setDecimals(2)
        self.polar_angle_field.setValue(90.0)
        self.polar_angle_field.setSuffix("°")
        self.polar_angle_field.setMaximumWidth(84)
        self.polar_angle_field.setToolTip("极轴角度增量；不限制沿方向的距离。")
        self.polar_reference_combo = QComboBox()
        self.polar_reference_combo.addItems(("UCS角度", "相对上一段"))
        self.polar_reference_combo.setToolTip(
            "极轴增量相对 UCS 或本次编辑中最近绘制的直线/多段线末段；没有记录时按 UCS。"
        )
        self.polar_additional_button = QPushButton("附加角度…")
        self.polar_additional_button.setToolTip("设置最多 10 个独立追踪角度，以逗号分隔。")
        self.dynamic_input_check = QCheckBox("动态输入")
        self.dynamic_input_check.setToolTip(
            "为直线、矩形、圆和圆弧输入尺寸；相切圆弧可在光标旁或命令栏输入半径。"
        )
        self.drawing_status_shortcuts: list[QShortcut] = []
        if select_committed_entities:
            for key, check in (
                ("F3", self.snap_check),
                ("F8", self.orthogonal_check),
                ("F9", self.grid_snap_check),
                ("F10", self.polar_check),
                ("F11", self.object_tracking_check),
                ("F12", self.dynamic_input_check),
            ):
                check.setToolTip(f"{check.toolTip()}（{key}）")
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(check.toggle)
                self.drawing_status_shortcuts.append(shortcut)
        self.auto_relation_check = QCheckBox("自动关系")
        self.auto_relation_check.setChecked(True)
        self.auto_relation_check.setToolTip(
            "捕捉到既有端点/圆心时保存重合关系；直线接近水平或竖直时自动对齐并保存关系。"
        )
        self.construction_check = QCheckBox("构造几何")
        self.closed_check = QCheckBox("闭合多段线")
        self.polygon_sides_field = QSpinBox()
        self.polygon_sides_field.setRange(3, 128)
        self.polygon_sides_field.setValue(6)
        self.polygon_mode_combo = QComboBox()
        self.polygon_mode_combo.addItems(("内接圆", "外切圆"))
        self.polygon_mode_combo.setToolTip("内接圆：中心到顶点；外切圆：中心到边中点。")
        self.arc_center_button = QPushButton("圆心、起点、终点")
        self.arc_center_button.setToolTip("依次指定圆心、起点和终点方向。")
        self.arc_center_button.clicked.connect(self._start_center_arc)
        self.arc_three_point_button = QPushButton("三点圆弧")
        self.arc_three_point_button.setToolTip("依次指定圆弧起点、经过点和终点。")
        self.arc_three_point_button.clicked.connect(self._start_three_point_arc)
        self.arc_ttr_button = QPushButton("两对象相切 + 半径")
        self.arc_ttr_button.setToolTip("先选择两个对象或线段，再输入半径，创建圆弧并保留来源。")
        self.arc_ttr_button.clicked.connect(self._start_tangent_arc)
        self.arc_direction_combo = QComboBox()
        self.arc_direction_combo.addItems(("逆时针", "顺时针"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(
            tuple(
                layer.name
                for layer in self.layer_table.layers
                if select_committed_entities or not layer.frozen
            )
        )
        active_layer = self.layer_table.layers[0].name
        self.layer_combo.setCurrentText(active_layer)
        self.layer_manager_button = QPushButton("图层管理…")
        self.layer_manager_button.setToolTip(
            "统一管理草稿和已提交对象的显示、冻结、锁定、颜色、线型和线宽。"
        )
        self.layer_combo.setToolTip("选择当前绘图层；新画的图元会放在该层。")
        self.assign_selection_layer_button = QPushButton("选中对象移至当前层")
        self.assign_selection_layer_button.setToolTip(
            "先选中二维图元、图片或一个尺寸，再选择目标图层并点击此按钮。"
        )
        self.assign_selection_layer_button.clicked.connect(self._assign_selection_to_current_layer)
        set_button_icon(self.layer_manager_button, "layers")
        layer_bar.addWidget(QLabel("当前图层"))
        layer_bar.addWidget(self.layer_combo, 1)
        layer_bar.addWidget(self.layer_manager_button)
        if select_committed_entities:
            layer_bar.addWidget(self.assign_selection_layer_button)
        self.thaw_layer_button = QToolButton()
        self.thaw_layer_button.setText("解冻图层")
        self.thaw_layer_button.setToolTip("选择要解冻的图层，无需打开图层管理。")
        self.thaw_layer_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        thaw_menu = QMenu(self.thaw_layer_button)
        thaw_menu.aboutToShow.connect(self._populate_thaw_layers)
        self.thaw_layer_button.setMenu(thaw_menu)
        if select_committed_entities:
            layer_bar.addWidget(self.thaw_layer_button)
        self.view_3d_button = QPushButton("三维视图")
        set_button_icon(self.view_3d_button, "view-isometric")
        self.view_3d_button.setToolTip("切换到已提交模型的三维视图，保留当前二维草稿。")
        self.view_3d_button.clicked.connect(self.view_3d_requested)
        layer_bar.addWidget(self.view_3d_button)
        for check in (
            self.grid_visible_check,
            self.snap_check,
            self.grid_snap_check,
            self.orthogonal_check,
        ):
            if not select_committed_entities:
                layer_bar.addWidget(check)
        self.toolbar_menu_button = QToolButton()
        self.toolbar_menu_button.setText("工具栏与面板")
        self.toolbar_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_menu = QMenu(self.toolbar_menu_button)
        for bar in self.drafting_toolbars:
            toolbar_menu.addAction(bar.toggleViewAction())
        toolbar_menu.addSeparator()
        for dock in self.drafting_docks:
            toolbar_menu.addAction(dock.toggleViewAction())
        toolbar_menu.addSeparator()
        toolbar_menu.addAction("恢复二维布局", self.reset_toolbar_layout)
        self.toolbar_menu_button.setMenu(toolbar_menu)
        layer_bar.addWidget(self.toolbar_menu_button)
        self.tool_buttons: dict[str, QToolButton] = {}
        for tool in (
            ("选择元素",)
            + (("点",) if select_committed_entities else ())
            + (
                "直线",
                "多段线",
                "矩形",
                "多边形",
                "圆",
                "圆弧",
                "样条曲线",
                "修剪",
                "延伸",
                "分割",
            )
        ):
            button = QToolButton()
            button.setText("选择" if tool == "选择元素" else "样条" if tool == "样条曲线" else tool)
            icon_names: dict[str, str] = dict(
                zip(
                    (
                        "点",
                        "选择元素",
                        "直线",
                        "多段线",
                        "矩形",
                        "多边形",
                        "圆",
                        "圆弧",
                        "样条曲线",
                        "修剪",
                        "延伸",
                        "分割",
                    ),
                    (
                        "point",
                        "select",
                        "line",
                        "polyline",
                        "rectangle",
                        "polygon",
                        "circle",
                        "arc",
                        "spline",
                        "trim",
                        "extend",
                        "split",
                    ),
                    strict=True,
                )
            )
            set_button_icon(button, "draw-" + icon_names[tool])
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setToolTip(
                "点：指定一个位置创建点对象。"
                if tool == "点"
                else tool + "：在画布中选点；右键 / Enter 结束连线，Esc 退出当前操作。"
            )
            button.setCheckable(True)
            button.setMinimumHeight(54)
            button.clicked.connect(
                lambda _checked=False, name=tool: self.tool_combo.setCurrentText(name)
            )
            self.tool_buttons[tool] = button
            button.setMinimumWidth(44)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            toolbar = (
                self.modify_toolbar if tool in {"修剪", "延伸", "分割"} else self.drawing_toolbar
            )
            toolbar.addWidget(button)
        if select_committed_entities:
            break_button = QToolButton()
            break_button.setText("单点打断")
            set_button_icon(break_button, "draw-split")
            break_button.setIconSize(QSize(26, 26))
            break_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            break_button.setToolTip("选择直线、圆弧或开放多段线，再指定打断点；命令 BREAKATPOINT。")
            break_button.setCheckable(True)
            break_button.setMinimumSize(44, 54)
            break_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            break_button.clicked.connect(
                lambda _checked=False: self.tool_combo.setCurrentText("单点打断")
            )
            self.tool_buttons["单点打断"] = break_button
            self.modify_toolbar.addWidget(break_button)
            fillet_button = QToolButton()
            fillet_button.setText("圆角")
            set_button_icon(fillet_button, "fillet-2d")
            fillet_button.setIconSize(QSize(26, 26))
            fillet_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            fillet_button.setToolTip(
                "支持直线、圆、圆弧和多段线段；圆保持完整。启用自动关系时可建立对象相切约束。命令栏提供 R/T/P/M/U 选项。"
            )
            fillet_button.setCheckable(True)
            fillet_button.setMinimumSize(44, 54)
            fillet_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            fillet_button.clicked.connect(
                lambda _checked=False: self.tool_combo.setCurrentText("二维圆角")
            )
            self.tool_buttons["二维圆角"] = fillet_button
            self.modify_toolbar.addWidget(fillet_button)
            chamfer_button = QToolButton()
            chamfer_button.setText("倒角")
            set_button_icon(chamfer_button, "chamfer-2d")
            chamfer_button.setIconSize(QSize(26, 26))
            chamfer_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            chamfer_button.setToolTip(
                "二维倒角：选择两条边或拖动穿过两条边；命令栏 D/A 设置参数、M 连续操作。"
            )
            chamfer_button.setCheckable(True)
            chamfer_button.setMinimumSize(44, 54)
            chamfer_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            chamfer_button.clicked.connect(
                lambda _checked=False: self.tool_combo.setCurrentText("二维倒角")
            )
            self.tool_buttons["二维倒角"] = chamfer_button
            self.modify_toolbar.addWidget(chamfer_button)
        self.tool_buttons["样条曲线"].setToolTip(
            "三次 B 样条（控制点方式）：至少四个控制点；Enter / 右键完成。首尾点在曲线上，中间点控制曲线形状。"
        )
        options_group = QGroupBox("绘图设置")
        options_group.setLayout(controls)
        for row, (label, widget) in enumerate(
            (
                ("工具", self.tool_combo),
                ("工作平面", self.plane_combo),
                ("圆弧方向", self.arc_direction_combo),
                ("圆心圆弧", self.arc_center_button),
                ("三点圆弧", self.arc_three_point_button),
                ("相切圆弧", self.arc_ttr_button),
                ("多边形边数", self.polygon_sides_field),
                ("多边形模式", self.polygon_mode_combo),
            )
        ):
            controls.addWidget(QLabel(label), row, 0)
            controls.addWidget(widget, row, 1)
        first_check_row = controls.rowCount()
        for index, check in enumerate(
            (
                self.auto_relation_check,
                self.construction_check,
                self.closed_check,
            )
        ):
            controls.addWidget(check, first_check_row + index, 0, 1, 2)
        panel_layout.addWidget(options_group)
        self.parameter_tabs.addTab(self.tool_panel, "绘图")

        origin = QFormLayout()
        self.origin_fields: dict[str, QDoubleSpinBox] = {}
        for axis in ("X", "Y", "Z"):
            field = QDoubleSpinBox()
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
            field.setSuffix(" mm")
            field.setPrefix(f"{axis}₀ ")
            if attached_frame is not None and support_face is not None:
                field.setValue(attached_frame.origin_mm[("X", "Y", "Z").index(axis)])
                field.setReadOnly(True)
                field.setToolTip("原点由所选模型面定义。")
            self.origin_fields[axis] = field
            origin.addRow(axis + "₀", field)
        origin_group = QGroupBox("UCS 原点 / mm")
        origin_group.setLayout(origin)
        self.parameter_tabs.addTab(self._parameter_page(origin_group), "UCS")

        self.canvas = SketchCanvas(self, select_committed_entities=select_committed_entities)
        self.canvas.draft_sketches_provider = self.dimension_sources
        self.canvas.continuous_lines = continuous_lines
        self.canvas.set_layer_table(self.layer_table, active_layer)
        if self._drag_preview is not None:
            self.canvas.set_drag_solver(self._preview_drag)
        self.ucs_label = QLabel("UCS · XY · X→ / Y↑ · mm")
        drawing.addWidget(self.ucs_label)
        self.dimension_controls_layout = QVBoxLayout()
        drawing.addLayout(self.dimension_controls_layout)
        drawing.addWidget(self.canvas, 1)
        self.dynamic_input = SketchDynamicInput(self)
        self._drawing_cursor_position: QPoint | None = None
        self._drawing_cursor_dimensions = QLabel(self.canvas)
        self._drawing_cursor_dimensions.setObjectName("drawingCursorDimensions")
        self._drawing_cursor_dimensions.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._drawing_cursor_dimensions.setStyleSheet(
            "QLabel { background: #f3f7fb; color: #243b53; "
            "border: 1px solid #849bb1; padding: 3px; }"
        )
        self._drawing_cursor_dimensions.hide()
        self._drawing_cursor_entry = _CursorDimensionEntry(self.canvas)
        self._drawing_cursor_entry.setObjectName("drawingCursorEntry")
        self._drawing_cursor_entry.setCursor(Qt.CursorShape.IBeamCursor)
        self._drawing_cursor_entry.setMaximumWidth(140)
        self._drawing_cursor_entry.setMaxLength(32)
        self._drawing_cursor_entry.hide()
        self._drawing_cursor_entry.next_requested.connect(self._advance_cursor_entry)
        self._drawing_cursor_entry.accept_requested.connect(self._accept_cursor_entry)
        self._drawing_cursor_entry.cancel_requested.connect(self._cancel_cursor_entry)
        self._drawing_cursor_field = 0
        self._dynamic_configured_tool = ""
        self._dynamic_was_pending = False
        self.canvas.dynamic_point_resolver = self._resolve_dynamic_point
        self.canvas.dynamic_key_handler = self._start_cursor_entry
        self.canvas.dynamic_click_guard = self._guard_cursor_entry
        self.canvas.dynamic_submit_handler = self._submit_tangent_cursor_entry
        self.canvas.changed.connect(self._sync_dynamic_input)
        self.canvas.point_accepted.connect(self._clear_dynamic_locks)
        self.dynamic_input_check.toggled.connect(self._sync_dynamic_input)
        self.dynamic_input_check.toggled.connect(self.canvas.refresh_dynamic_preview)
        self.dynamic_input.changed.connect(self.canvas.refresh_dynamic_preview)
        self.dynamic_input.changed.connect(self._update_drawing_cursor_dimensions)
        self.canvas.pointer_moved.connect(self._on_drawing_pointer_moved)
        self.canvas.pointer_left.connect(self._on_drawing_pointer_left)
        drawing.addWidget(self.dynamic_input)
        self._sync_dynamic_input()
        self.drawing_command_bar = Drawing2DCommandBar(
            self.canvas,
            self._activate_command_tool,
            self._activate_command_transform,
            self,
            apply_rectangular_array=self._apply_command_rectangular_array,
            commit_rectangular_array=self._commit_command_rectangular_array,
            configure_polygon=self._configure_command_polygon,
            measure_planar_region=measure_planar_region,
        )
        self.dynamic_input.escape_requested.connect(self.drawing_command_bar.cancel)
        self.drawing_command_bar.setVisible(select_committed_entities)
        drawing.addWidget(self.drawing_command_bar)
        self.measure_buttons: dict[str, QToolButton] = {}
        if select_committed_entities:
            for label, icon, command in (
                ("快速测量", "measure", "Q"),
                ("距离", "measure-distance", "DIST"),
                ("面积", "measure-area", "AREA"),
                ("半径", "measure-radius", "R"),
                ("角度", "measure-angle", "A"),
            ):
                button = QToolButton()
                button.setText(label)
                button.setToolTip(f"{label}：启动二维只读测量。")
                set_button_icon(button, icon)
                button.setIconSize(QSize(26, 26))
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setMinimumSize(44, 54)
                button.clicked.connect(
                    lambda _checked=False, name=command: self.drawing_command_bar.start_measurement(
                        name
                    )
                )
                self.measure_buttons[label] = button
                self.measurement_toolbar.addWidget(button)
        self.drawing_status_bar = QWidget()
        self.drawing_status_bar.setObjectName("drawing2dStatusBar")
        self.tangent_capture_button = QToolButton()
        self.tangent_capture_button.setObjectName("twoObjectTangentCapture")
        self.tangent_capture_button.setText("两对象相切")
        self.tangent_capture_button.setToolTip(
            "直线：依次点选两个圆或圆弧；圆和圆弧：点选两个对象后输入半径。"
        )
        self.tangent_capture_button.clicked.connect(self._start_two_object_tangent)
        self.tracking_settings_button = QToolButton()
        self.tracking_settings_button.setText("追踪设置…")
        self.tracking_settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tracking_menu = QMenu(self.tracking_settings_button)
        tracking_settings = QWidget(tracking_menu)
        tracking_form = QFormLayout(tracking_settings)
        tracking_form.addRow("捕捉模式", self.snap_type_combo)
        tracking_form.addRow("极轴捕捉距离", self.polar_spacing_field)
        tracking_form.addRow("极轴角度增量", self.polar_angle_field)
        tracking_form.addRow("极轴角度基准", self.polar_reference_combo)
        tracking_form.addRow("对象追踪方向", self.object_tracking_angle_combo)
        tracking_form.addRow("追踪点获取", self.object_tracking_acquisition_combo)
        tracking_form.addRow(self.polar_additional_button)
        tracking_action = QWidgetAction(tracking_menu)
        tracking_action.setDefaultWidget(tracking_settings)
        tracking_menu.addAction(tracking_action)
        self.tracking_settings_button.setMenu(tracking_menu)
        status_controls = QHBoxLayout(self.drawing_status_bar)
        status_controls.setContentsMargins(0, 0, 0, 0)
        status_controls.addStretch(1)
        if select_committed_entities:
            for check in (
                self.grid_visible_check,
                self.grid_snap_check,
                self.orthogonal_check,
                self.polar_check,
                self.object_tracking_check,
                self.tracking_settings_button,
                self.snap_check,
                self.tangent_capture_button,
                self.dynamic_input_check,
            ):
                status_controls.addWidget(check)
        self.drawing_status_bar.setVisible(select_committed_entities)
        drawing.addWidget(self.drawing_status_bar)
        coordinate_group = QGroupBox("坐标输入 / mm")
        coordinate_layout = QVBoxLayout(coordinate_group)
        coordinates = QFormLayout()
        self.u_field = QDoubleSpinBox()
        self.v_field = QDoubleSpinBox()
        for field in (self.u_field, self.v_field):
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
            field.setSuffix(" mm")
        coordinates.addRow("U", self.u_field)
        coordinates.addRow("V", self.v_field)
        coordinate_layout.addLayout(coordinates)
        self.coordinate_add_button = QPushButton("按坐标点")
        self.finish_polyline_button = QPushButton("完成多段线")
        self.finish_polyline_button.setEnabled(False)
        self.undo_entity_button = QPushButton("撤销草稿操作")
        self.undo_entity_button.setEnabled(False)
        self.redo_entity_button = QPushButton("重做草稿操作")
        self.redo_entity_button.setEnabled(False)
        self.undo_entity_button.setToolTip("撤销上一项草稿操作；画布中按 Ctrl+Z。")
        self.redo_entity_button.setToolTip("重做已撤销的草稿操作；画布中按 Ctrl+Shift+Z。")
        coordinate_layout.addWidget(self.coordinate_add_button)
        panel_layout.addWidget(coordinate_group)
        self.end_chain_button = QPushButton("结束连线 ↵")
        self.close_chain_button = QPushButton("闭合 C")
        self.end_chain_button.clicked.connect(self.canvas.end_line_chain)
        self.close_chain_button.clicked.connect(self.canvas.close_chain)
        chain_controls = QHBoxLayout()
        chain_controls.addWidget(self.end_chain_button)
        chain_controls.addWidget(self.close_chain_button)
        panel_layout.addLayout(chain_controls)
        panel_layout.addWidget(self.finish_polyline_button)
        panel_layout.addStretch()

        transform_grid = QGridLayout()
        self.delta_u_field = QDoubleSpinBox()
        self.delta_v_field = QDoubleSpinBox()
        self.center_u_field = QDoubleSpinBox()
        self.center_v_field = QDoubleSpinBox()
        self.angle_field = QDoubleSpinBox()
        self.pattern_angle_field = QDoubleSpinBox()
        self.offset_distance_field = QDoubleSpinBox()
        for field in (
            self.delta_u_field,
            self.delta_v_field,
            self.center_u_field,
            self.center_v_field,
            self.angle_field,
            self.pattern_angle_field,
            self.offset_distance_field,
        ):
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
        self.delta_u_field.setPrefix("ΔU ")
        self.delta_v_field.setPrefix("ΔV ")
        self.center_u_field.setPrefix("中心 U ")
        self.center_v_field.setPrefix("中心 V ")
        self.angle_field.setSuffix("°")
        self.angle_field.setPrefix("角度 ")
        self.angle_field.setValue(90.0)
        self.pattern_angle_field.setSuffix("°")
        self.pattern_angle_field.setPrefix("环阵角 ")
        self.pattern_angle_field.setValue(360.0)
        self.offset_distance_field.setPrefix("偏移 ")
        self.offset_distance_field.setSuffix(" mm")
        self.offset_distance_field.setValue(1.0)
        self.count_field = QSpinBox()
        self.count_field.setRange(2, 1000)
        self.count_field.setValue(3)
        self.count_field.setPrefix("数量 ")
        self.array_rows_field = QSpinBox()
        self.array_rows_field.setRange(1, 1000)
        self.array_rows_field.setValue(2)
        self.array_rows_field.setPrefix("行数 ")
        self.array_columns_field = QSpinBox()
        self.array_columns_field.setRange(1, 1000)
        self.array_columns_field.setValue(3)
        self.array_columns_field.setPrefix("列数 ")
        self.rotation_reference_check = QCheckBox("参考旋转（三点）")
        self.rotation_reference_check.setToolTip("依次指定旋转中心、起始参考点和目标方向点。")
        self.mirror_keep_source_check = QCheckBox("镜像保留原对象")
        self.mirror_keep_source_check.setChecked(True)
        self.mirror_axis_combo = QComboBox()
        self.mirror_axis_combo.addItems(("水平轴", "竖直轴"))
        fields = (
            ("参考旋转", self.rotation_reference_check),
            ("镜像副本", self.mirror_keep_source_check),
            ("变换步距", self.delta_u_field),
            ("", self.delta_v_field),
            ("旋转/阵列中心", self.center_u_field),
            ("", self.center_v_field),
            ("角度", self.angle_field),
            ("环阵总角", self.pattern_angle_field),
            ("偏移距离", self.offset_distance_field),
            ("数量", self.count_field),
            ("矩阵行数", self.array_rows_field),
            ("矩阵列数", self.array_columns_field),
            ("数值镜像方向", self.mirror_axis_combo),
        )
        for row, (label, field) in enumerate(fields):
            field.setToolTip(label)
            transform_grid.addWidget(field, row, 0)
        self.transform_buttons: dict[str, QToolButton] = {}
        operations = (
            ("move", "移动"),
            ("copy", "复制"),
            ("rotate", "旋转"),
            ("scale", "缩放"),
            ("mirror", "镜像"),
            ("offset", "偏移"),
            ("linear_array", "线性阵列"),
            ("rectangular_array", "矩形阵列"),
            ("circular_array", "环形阵列"),
        )
        for operation, label in operations:
            button = QToolButton()
            button.setText(
                {"linear_array": "线阵", "rectangular_array": "矩阵", "circular_array": "环阵"}.get(
                    operation, label
                )
            )
            set_button_icon(button, "edit-" + operation)
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setMinimumHeight(54)
            button.setToolTip(
                "矩形阵列：设置行列数，ΔU 为列间距、ΔV 为行间距；创建独立副本。"
                if operation == "rectangular_array"
                else label + "：选择草稿或已保存图元，并设置下方修改参数。"
                if operation in {"offset", "linear_array", "rectangular_array", "circular_array"}
                and select_committed_entities
                else label + "：先选择草稿图元，再设置下方修改参数。"
            )
            button.setEnabled(False)
            button.clicked.connect(
                lambda _checked=False, selected_operation=operation: self._start_transform(
                    selected_operation
                )
            )
            self.transform_buttons[operation] = button
            button.setMinimumWidth(44)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.modify_toolbar.addWidget(button)
        self.interactive_offset_button = QToolButton()
        self.interactive_offset_button.setText("侧向偏移")
        self.interactive_offset_button.setToolTip("输入距离后选择对象及偏移侧，可连续操作。")
        set_button_icon(self.interactive_offset_button, "edit-offset")
        self.interactive_offset_button.setIconSize(QSize(26, 26))
        self.interactive_offset_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        self.interactive_offset_button.setMinimumHeight(54)
        self.interactive_offset_button.setVisible(select_committed_entities)
        self.interactive_offset_button.clicked.connect(self.drawing_command_bar.start_offset)
        self.modify_toolbar.addWidget(self.interactive_offset_button)
        transform_group = QGroupBox("修改参数 · 先选择元素")
        transform_group.setLayout(transform_grid)
        self.numeric_move_button = QPushButton("按 ΔU / ΔV 移动")
        self.numeric_copy_button = QPushButton("按 ΔU / ΔV 复制")
        self.numeric_move_button.clicked.connect(lambda: self._apply_transform("move"))
        self.numeric_copy_button.clicked.connect(lambda: self._apply_transform("copy"))
        transform_grid.addWidget(self.numeric_move_button, len(fields), 0)
        transform_grid.addWidget(self.numeric_copy_button, len(fields) + 1, 0)
        self.numeric_rotate_button = QPushButton("应用输入角度")
        self.numeric_rotate_button.setToolTip("已拾取中心时绕该点旋转；否则使用中心 U / V。")
        self.numeric_rotate_button.clicked.connect(self._apply_numeric_rotation)
        transform_grid.addWidget(self.numeric_rotate_button, len(fields) + 2, 0)
        self.numeric_mirror_button = QPushButton("按输入中心 / 方向镜像")
        self.numeric_mirror_button.clicked.connect(lambda: self._apply_transform("mirror"))
        transform_grid.addWidget(self.numeric_mirror_button, len(fields) + 3, 0)
        self.transform_buttons["rotate"].setToolTip(
            "旋转：选择对象 → 中心 → 鼠标指定方向或键入角度；可选三点参考旋转。"
        )
        self.transform_buttons["scale"].setToolTip(
            "缩放：选择对象、指定基点，再输入比例或指定比例点；C 复制，R 参考长度。"
        )
        self.transform_buttons["mirror"].setToolTip(
            "镜像：选择对象 → 镜像轴两点；默认保留原对象，可取消勾选以替换。"
        )
        self.transform_buttons["move"].setToolTip(
            "移动：选择对象、指定基点和目标点；鼠标预览，Esc 取消。"
        )
        self.transform_buttons["copy"].setToolTip(
            "复制：选择对象、指定基点和目标点；原对象保留，单击放置副本。"
        )
        transform_grid.addWidget(self.undo_entity_button, transform_grid.rowCount(), 0, 1, 2)
        transform_grid.addWidget(self.redo_entity_button, transform_grid.rowCount(), 0, 1, 2)
        self.modify_page = self._parameter_page(transform_group)
        self.parameter_tabs.addTab(self.modify_page, "修改")
        self.parameter_tabs.addTab(self.navigator, "图形")
        self.properties_table = QTableWidget(0, 2)
        self.properties_table.setHorizontalHeaderLabels(("特性", "值"))
        self.properties_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.properties_table.verticalHeader().setVisible(False)
        self.properties_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.properties_table.setToolTip("查看对象特性；直接输入支持的数值，按 Enter 确认。")
        self.properties_table.itemDoubleClicked.connect(self._edit_property_coordinate)
        self._property_rows: tuple[tuple[str, str], ...] = ()
        self._property_entities: tuple[SketchEntity, ...] = ()
        self._property_revision: int | None = None
        self._property_layer_choices: tuple[str, ...] = ()
        self.property_layer_combo: QComboBox | None = None
        self.property_construction_combo: QComboBox | None = None
        self.property_edit_dimension_button = QPushButton("编辑尺寸…")
        self.property_edit_dimension_button.setEnabled(False)
        self.property_edit_dimension_button.clicked.connect(self._edit_property_dimension)
        self.property_vertex_controls = QWidget()
        vertex_layout = QHBoxLayout(self.property_vertex_controls)
        vertex_layout.setContentsMargins(0, 0, 0, 0)
        self.property_vertex_label = QLabel("顶点")
        self.property_vertex_index = QSpinBox()
        self.property_vertex_index.setMinimum(1)
        self.property_vertex_coordinate = QLineEdit()
        self.property_vertex_coordinate.setToolTip("输入绝对坐标 x,y（mm），按 Enter 确认。")
        vertex_layout.addWidget(self.property_vertex_label)
        vertex_layout.addWidget(self.property_vertex_index)
        vertex_layout.addWidget(self.property_vertex_coordinate, 1)
        self._property_vertex_identity = ""
        self.property_vertex_index.valueChanged.connect(self._refresh_property_vertex)
        self.canvas.property_vertex_picked.connect(self._select_property_vertex)
        self.property_vertex_coordinate.returnPressed.connect(self._commit_property_vertex)
        self.property_vertex_controls.hide()
        properties_page = QWidget(self)
        properties_layout = QVBoxLayout(properties_page)
        properties_layout.addWidget(self.properties_table)
        self.property_feedback_label = QLabel()
        self.property_feedback_label.setObjectName("propertyEditFeedback")
        self.property_feedback_label.setWordWrap(True)
        self.property_feedback_label.setStyleSheet("color: #a13b14;")
        self.property_feedback_label.hide()
        self._property_feedback_selection: frozenset[str] = frozenset()
        self._property_feedback_name = ""
        properties_layout.addWidget(self.property_feedback_label)
        properties_layout.addWidget(self.property_vertex_controls)
        properties_layout.addWidget(self.property_edit_dimension_button)
        if select_committed_entities:
            self.parameter_tabs.addTab(properties_page, "特性")
        else:
            properties_page.hide()

        def show_command_panel(panel: str) -> None:
            if panel == "layer":
                self.open_layer_manager()
            elif panel == "properties":
                self.parameter_dock.show()
                self.parameter_tabs.setCurrentWidget(properties_page)
            elif panel == "quickselect":
                self.open_quick_select()

        self.drawing_command_bar.panel_requested.connect(show_command_panel)

        self.status_label = (
            DrawingMessageLabel(self.canvas.message)
            if select_committed_entities
            else MessageLabel(self.canvas.message)
        )
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.text_changed.connect(self._update_property_feedback)
        self.dimensions = DimensionTools(self)
        self.drawing_command_bar.bind_dimensions(self.dimensions)
        self.canvas.deleting.connect(self.dimensions.cancel)
        self.navigator.delete_requested.connect(self.canvas.delete_selected)
        self.entity_count_label = QLabel("0 个草图元素")
        self.finish_button = QPushButton("完成草图")
        self.finish_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
        self.drawing_toolbar.addSeparator()
        self.drawing_toolbar.addWidget(self.finish_button)
        self.drawing_toolbar.addWidget(self.cancel_button)
        self.toolbar_host.statusBar().addWidget(self.entity_count_label)
        self.toolbar_host.statusBar().addWidget(self.status_label, 1)

        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        for field in self.origin_fields.values():
            field.valueChanged.connect(self._sync_state)
        self.plane_combo.currentTextChanged.connect(self._change_plane)
        self.tool_combo.currentTextChanged.connect(self._change_tool)
        self.construction_check.toggled.connect(self.canvas.set_construction)
        self.snap_check.toggled.connect(self.canvas.set_snapping_enabled)
        self.grid_snap_check.toggled.connect(self.canvas.set_grid_snapping_enabled)
        self.snap_type_combo.currentIndexChanged.connect(self._set_snap_type)
        self.polar_spacing_field.valueChanged.connect(self.canvas.set_polar_snap_spacing)
        self.grid_visible_check.toggled.connect(self.canvas.set_grid_visible)
        self.polygon_sides_field.valueChanged.connect(self._update_polygon_options)
        self.polygon_mode_combo.currentTextChanged.connect(self._update_polygon_options)
        self.rotation_reference_check.toggled.connect(self._update_transform_options)
        self.canvas.rotation_reference_mode_changed.connect(
            self.rotation_reference_check.setChecked
        )
        self.mirror_keep_source_check.toggled.connect(self._update_transform_options)
        self.canvas.mirror_keep_source_mode_changed.connect(
            self.mirror_keep_source_check.setChecked
        )
        self.orthogonal_check.toggled.connect(self._set_orthogonal_mode)
        self.polar_check.toggled.connect(self._set_polar_mode)
        self.object_tracking_check.toggled.connect(self.canvas.set_object_tracking_enabled)
        self.object_tracking_angle_combo.currentIndexChanged.connect(
            self._set_object_tracking_angle_mode
        )
        self.object_tracking_acquisition_combo.currentIndexChanged.connect(
            self._set_object_tracking_acquisition_mode
        )
        self.polar_angle_field.valueChanged.connect(self.canvas.set_polar_angle_increment)
        self.polar_reference_combo.currentIndexChanged.connect(self._set_polar_reference)
        self.polar_additional_button.clicked.connect(self._edit_polar_additional_angles)
        self.auto_relation_check.toggled.connect(self.canvas.set_auto_inference_enabled)
        self.closed_check.toggled.connect(self.canvas.set_closed_polyline)
        self.arc_direction_combo.currentTextChanged.connect(self.canvas.set_arc_direction)
        self.layer_combo.currentTextChanged.connect(self._set_active_layer)
        self.layer_manager_button.clicked.connect(self.open_layer_manager)
        self.coordinate_add_button.clicked.connect(self._add_coordinate_point)
        self.finish_polyline_button.clicked.connect(lambda: self.canvas.finish_polyline())
        self.undo_entity_button.clicked.connect(self._undo_draft_operation)
        self.redo_entity_button.clicked.connect(self._redo_draft_operation)
        self.canvas.history_recorded.connect(self.layer_history_redo.clear)
        self.canvas.undo_requested.connect(self._undo_draft_operation)
        self.canvas.redo_requested.connect(self._redo_draft_operation)
        self.finish_button.clicked.connect(self.finish_sketch)
        self.cancel_button.clicked.connect(self.reject)
        self.canvas.changed.connect(self._sync_state)
        self.canvas.cursor_changed.connect(self._show_cursor)
        self._compact_toolbar_states: dict[QToolButton, tuple[int, QSize, Qt.ToolButtonStyle]] = {}
        self._compact_layout = False
        self._sync_state()

    def _set_orthogonal_mode(self, enabled: bool) -> None:
        if enabled and self.polar_check.isChecked():
            self.polar_check.setChecked(False)
        self.canvas.set_orthogonal_enabled(enabled)

    def _set_snap_type(self, index: int) -> None:
        self.canvas.set_polar_snap_enabled(index == 1)

    def _set_object_tracking_angle_mode(self, index: int) -> None:
        self.canvas.set_object_tracking_use_polar(index == 1)

    def _set_object_tracking_acquisition_mode(self, index: int) -> None:
        self.canvas.set_object_tracking_shift_to_acquire(index == 1)

    def _set_polar_reference(self, index: int) -> None:
        self.canvas.set_polar_relative(index == 1)

    def _edit_polar_additional_angles(self) -> None:
        current = ", ".join(f"{angle:g}" for angle in self.canvas.polar_additional_angles)
        text, accepted = QInputDialog.getText(
            self, "附加极轴角度", "输入最多 10 个角度，以逗号分隔；留空清除。", text=current
        )
        if not accepted:
            return
        try:
            angles = (
                tuple(float(value.strip()) for value in text.replace("，", ",").split(","))
                if text.strip()
                else ()
            )
            self.canvas.set_polar_additional_angles(angles)
        except ValueError:
            self.canvas.message = "附加角度无效：请输入最多 10 个 0 到小于 360 的有限数值。"
            self.canvas.changed.emit()
            return
        self.canvas.message = "附加极轴角度已更新。"
        self.canvas.changed.emit()

    def _set_polar_mode(self, enabled: bool) -> None:
        if enabled and self.orthogonal_check.isChecked():
            self.orthogonal_check.setChecked(False)
        self.canvas.set_polar_tracking_enabled(enabled)

    def set_compact_layout(self, compact: bool) -> None:
        """Reduce toolbar height on small logical screens while retaining tooltips."""
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        if compact:
            self.ucs_label.hide()
            for toolbar in self.drafting_toolbars:
                for action in toolbar.actions():
                    button = toolbar.widgetForAction(action)
                    if isinstance(button, QToolButton):
                        self._compact_toolbar_states[button] = (
                            button.minimumHeight(),
                            button.iconSize(),
                            button.toolButtonStyle(),
                        )
                        button.setMinimumHeight(32)
                        button.setIconSize(QSize(18, 18))
                        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        else:
            self.ucs_label.show()
            for button, (height, icon_size, style) in self._compact_toolbar_states.items():
                button.setMinimumHeight(height)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(style)
            self._compact_toolbar_states.clear()

    @staticmethod
    def _parameter_page(group: QGroupBox) -> QScrollArea:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(group)
        layout.addStretch()
        page.setWidget(content)
        return page

    @property
    def drafting_docks(self) -> tuple[QDockWidget, ...]:
        return (self.parameter_dock,)

    @property
    def drafting_toolbars(self) -> tuple[QToolBar, ...]:
        bars = (self.drawing_toolbar, self.modify_toolbar, self.dimension_toolbar)
        return (*bars, self.measurement_toolbar) if self._measurement_available else bars

    def _make_toolbar(self, title: str, name: str) -> QToolBar:
        bar = QToolBar(title, self.toolbar_host)
        bar.setObjectName(name)
        bar.setMovable(True)
        bar.setFloatable(True)
        bar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        bar.setStyleSheet(
            "QToolButton:checked { background: palette(alternate-base); border: 1px solid palette(highlight); }"
        )
        return bar

    def reset_toolbar_layout(self) -> None:
        self._suspended_toolbar_state = None
        for bar in self.drafting_toolbars:
            self.toolbar_host.removeToolBarBreak(bar)
            self.toolbar_host.removeToolBar(bar)
        for bar in (self.drawing_toolbar, self.modify_toolbar):
            self.toolbar_host.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
            bar.show()
        self.toolbar_host.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.toolbar_host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.dimension_toolbar)
        self.dimension_toolbar.show()
        if self._measurement_available:
            self.toolbar_host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.measurement_toolbar)
            self.measurement_toolbar.show()
        if hasattr(self, "parameter_dock"):
            self.parameter_dock.setFloating(False)
            self.toolbar_host.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock
            )
            self.parameter_dock.show()
            self.toolbar_host.resizeDocks([self.parameter_dock], [270], Qt.Orientation.Horizontal)

    def _navigation_scope(self) -> tuple[frozenset[str], frozenset[str]]:
        selectable = frozenset(e.entity_id for e in self.canvas.selectable_entities())
        # An independently displayed DIM annotation remains selectable even when
        # its referenced geometry's layer is off. Keep that geometry unselected.
        in_scope = {e.entity_id for e in self.canvas.entities} | {
            e.entity_id
            for e, _layer in self.canvas.background_entities
            if self.canvas.select_committed_entities
        }
        constraints = frozenset(
            c.constraint_id
            for c in self.canvas.dimension_constraints()
            if self.canvas.annotation_layer(c).displayed
            and all(ref.entity_id in in_scope for ref in c.references)
        )
        return selectable, constraints

    def _sync_navigation(self) -> None:
        selectable, constraints = self._navigation_scope()
        self.canvas.selected_constraint_ids.intersection_update(constraints)
        self.navigator.sync(
            self.dimension_sources(),
            frozenset(self.canvas.selected_entity_ids),
            frozenset(self.canvas.selected_constraint_ids),
            selectable,
            constraints,
        )

    def _navigation_busy(self) -> bool:
        return (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.dimensions.mode is not None
            or self.dimensions.candidate is not None
        )

    def _select_navigation(self, entity_ids: object, constraint_ids: object) -> None:
        if self._navigation_busy():
            self.status_label.setText("请先完成当前操作或按 Esc 退出，再选择导航对象。")
            self._sync_navigation()
            target = (
                self.dimensions.value_editor
                if self.dimensions.value_editor.isVisible()
                else self.canvas
            )
            target.window().activateWindow()
            target.setFocus()
            return
        selectable, constraints = self._navigation_scope()
        selected_constraints = set(cast("frozenset[str]", constraint_ids)) & constraints
        selected = set(cast("frozenset[str]", entity_ids)) & selectable
        self.dimensions.cancel()
        self.canvas.set_tool("选择元素")
        self.canvas.selected_entity_ids = selected
        self.canvas.selected_constraint_ids = selected_constraints
        self.canvas.clear_selected_tangent_segments()
        self.canvas.message = (
            f"图形导航：已选 {len(selected)} 个图元、{len(selected_constraints)} 个约束。"
        )
        self.canvas.changed.emit()
        self.canvas.update()

    def _activate_navigation_constraint(self, identity: str) -> None:
        if self._navigation_busy() or identity not in self._navigation_scope()[1]:
            return
        for sketch in self.dimension_sources():
            for constraint in sketch.constraints:
                if constraint.constraint_id == identity and constraint.kind in DIMENSION_KINDS:
                    self.dimensions.edit(sketch, constraint)
                    return

    def toolbar_layout_state(self) -> QByteArray:
        return (
            self._suspended_toolbar_state
            if self._suspended_toolbar_state is not None
            else self.toolbar_host.saveState()
        )

    def restore_toolbar_layout(self, state: QByteArray | None) -> None:
        if state is not None:
            if self._suspended_toolbar_state is not None:
                self._suspended_toolbar_state = state
            else:
                self.toolbar_host.restoreState(state)

    def set_toolbars_locked(self, locked: bool) -> None:
        for bar in self.drafting_toolbars:
            bar.setMovable(not locked)
            bar.setFloatable(not locked)

    @override
    def hideEvent(self, event: QHideEvent) -> None:
        if self._suspended_toolbar_state is None:
            self._suspended_toolbar_state = self.toolbar_host.saveState()
        for widget in (*self.drafting_toolbars, *self.drafting_docks):
            widget.hide()
        super().hideEvent(event)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        if self._suspended_toolbar_state is not None:
            state = self._suspended_toolbar_state
            self._suspended_toolbar_state = None
            self.toolbar_host.restoreState(state)
        super().showEvent(event)

    @property
    def draft_sketch_id(self) -> str:
        return self._drag_preview_sketch_id

    def dimension_sources(self) -> tuple[Sketch, ...]:
        draft = Sketch(
            self._drag_preview_sketch_id,
            self.current_frame(),
            tuple(self.canvas.entities),
            tuple(self.canvas.constraints),
            self.layer_table,
            self._support_face,
        )
        mixed = self.canvas.mixed_move
        if mixed is None or not self.canvas.mixed_move_is_valid:
            return (draft, *self._context_sketches)
        current = {sketch.sketch_id: sketch for sketch in mixed.current_saved}
        return (
            draft,
            *(current.get(sketch.sketch_id, sketch) for sketch in self._context_sketches),
        )

    def preview_dimension(
        self, original: Sketch, candidate: SketchConstraint
    ) -> SketchConstraintSolveResult:
        preview = (
            self._constraint_update_preview
            if any(c.constraint_id == candidate.constraint_id for c in original.constraints)
            else self._constraint_preview
        )
        if preview is None:
            return SketchConstraintSolveResult(
                "unavailable", None, None, message="尺寸求解服务不可用"
            )
        return preview(original, candidate)

    def _open_draft_dimension(self) -> None:
        self.dimensions.start("smart")

    def show_dimension_preview(self, result: SketchConstraintSolveResult) -> None:
        self.clear_dimension_preview()
        if result.status != "success":
            candidate = self.dimensions.candidate
            conflicts = set(result.conflicting_constraint_ids)
            if candidate is not None:
                conflicts.add(candidate.constraint_id)
            constraints = (
                *self.canvas.dimension_constraints(),
                *((candidate,) if candidate is not None else ()),
            )
            self.canvas.dimension_error_constraint_ids = frozenset(conflicts)
            self.canvas.dimension_error_entity_ids = frozenset(
                ref.entity_id
                for constraint in constraints
                if constraint.constraint_id in conflicts
                for ref in constraint.references
            )
        sketch = result.sketch
        frame = self.current_frame()
        if result.status == "success" and sketch is not None:
            source = sketch.frame
            delta = tuple(a - b for a, b in zip(source.origin_mm, frame.origin_mm, strict=True))
            cross = (
                source.normal[1] * frame.normal[2] - source.normal[2] * frame.normal[1],
                source.normal[2] * frame.normal[0] - source.normal[0] * frame.normal[2],
                source.normal[0] * frame.normal[1] - source.normal[1] * frame.normal[0],
            )
            if (
                math.hypot(*cross) <= 1e-9
                and abs(sum(a * b for a, b in zip(delta, frame.normal, strict=True))) <= 1e-7
            ):
                aligned = source.u_axis == frame.u_axis and source.v_axis == frame.v_axis
                shift = (
                    sum(a * b for a, b in zip(delta, frame.u_axis, strict=True)),
                    sum(a * b for a, b in zip(delta, frame.v_axis, strict=True)),
                )
                entities = (
                    move_entities(
                        sketch.entities,
                        tuple(e.entity_id for e in sketch.entities),
                        shift,
                        preserve_rectangle_order=True,
                    )
                    if aligned
                    else tuple(
                        project_coplanar_entity(entity, source, frame) for entity in sketch.entities
                    )
                )
                constraints = tuple(
                    replace(
                        c,
                        position_mm=None
                        if c.position_mm is None
                        else (c.position_mm[0] + shift[0], c.position_mm[1] + shift[1])
                        if aligned
                        else frame.world_to_local(source.local_to_world(c.position_mm)),
                        text_position_mm=None
                        if c.text_position_mm is None
                        else (c.text_position_mm[0] + shift[0], c.text_position_mm[1] + shift[1])
                        if aligned
                        else frame.world_to_local(source.local_to_world(c.text_position_mm)),
                    )
                    for c in sketch.constraints
                )
                self.canvas.dimension_preview = replace(
                    sketch,
                    frame=frame,
                    entities=entities,
                    constraints=constraints,
                    support_face=None,
                )
        self.canvas.update()

    def clear_dimension_preview(self) -> None:
        self.canvas.dimension_preview = None
        self.canvas.dimension_linked_previews = ()
        self.canvas.dimension_linked_sources = ()
        self.canvas.dimension_error_entity_ids = frozenset()
        self.canvas.dimension_error_constraint_ids = frozenset()
        self.canvas.update()

    def show_linked_dimension_previews(self, sketches: tuple[Sketch, ...]) -> None:
        """Overlay the other sketches in an isolated dimension solution."""
        primary = self.canvas.dimension_preview
        projected: list[Sketch] = []
        for sketch in sketches:
            self.show_dimension_preview(SketchConstraintSolveResult("success", sketch, None))
            if self.canvas.dimension_preview is not None:
                projected.append(self.canvas.dimension_preview)
        self.canvas.dimension_preview = primary
        self.canvas.dimension_linked_previews = tuple(projected)
        self.canvas.dimension_linked_sources = sketches
        self.canvas.update()

    def set_context_sketches(self, sketches: tuple[Sketch, ...]) -> None:
        self._context_sketches = sketches
        if self.canvas.source_revision_provider is not None:
            self.canvas.set_source_context_revision(self.canvas.source_revision_provider())
        if not self.document_layer_mode:
            self.layer_table = merge_layer_tables(
                *(s.layers for s in sketches), self.layer_table, include_dim=True
            )
            self.canvas.layer_table = self.layer_table
        self._context_frame = self.current_frame()
        self.canvas.set_background_sketches(sketches, self._context_frame)
        self._sync_state()

    def continue_workspace_from(self, previous: SketchEditorDialog) -> None:
        self.plane_combo.setCurrentText(previous.plane_combo.currentText())
        for axis, field in self.origin_fields.items():
            field.setValue(previous.origin_fields[axis].value())
        self.canvas.copy_view_from(previous.canvas)
        self.canvas.set_layer_table(previous.layer_table, previous.layer_combo.currentText())
        self._sync_state()
        self.snap_check.setChecked(previous.snap_check.isChecked())
        self.grid_snap_check.setChecked(previous.grid_snap_check.isChecked())
        self.snap_type_combo.setCurrentIndex(previous.snap_type_combo.currentIndex())
        self.polar_spacing_field.setValue(previous.polar_spacing_field.value())
        self.grid_visible_check.setChecked(previous.grid_visible_check.isChecked())
        self.polygon_sides_field.setValue(previous.polygon_sides_field.value())
        self.polygon_mode_combo.setCurrentText(previous.polygon_mode_combo.currentText())
        self.orthogonal_check.setChecked(previous.orthogonal_check.isChecked())
        self.polar_angle_field.setValue(previous.polar_angle_field.value())
        self.polar_reference_combo.setCurrentIndex(previous.polar_reference_combo.currentIndex())
        self.canvas.copy_polar_reference_from(previous.canvas)
        self.canvas.set_polar_additional_angles(previous.canvas.polar_additional_angles)
        self.polar_check.setChecked(previous.polar_check.isChecked())
        self.object_tracking_check.setChecked(previous.object_tracking_check.isChecked())
        self.object_tracking_angle_combo.setCurrentIndex(
            previous.object_tracking_angle_combo.currentIndex()
        )
        self.object_tracking_acquisition_combo.setCurrentIndex(
            previous.object_tracking_acquisition_combo.currentIndex()
        )
        self.dynamic_input_check.setChecked(previous.dynamic_input_check.isChecked())
        self.canvas.chamfer_first_distance = previous.canvas.chamfer_first_distance
        self.canvas.chamfer_second_distance = previous.canvas.chamfer_second_distance
        self.canvas.chamfer_distance_first = previous.canvas.chamfer_distance_first
        self.canvas.chamfer_angle_length = previous.canvas.chamfer_angle_length
        self.canvas.chamfer_angle = previous.canvas.chamfer_angle
        self.canvas.chamfer_last_angle = previous.canvas.chamfer_last_angle
        self.canvas.chamfer_trim = previous.canvas.chamfer_trim
        self.canvas.circle_fillet_radius = previous.canvas.circle_fillet_radius
        self.canvas.offset_layer_current = previous.canvas.offset_layer_current
        self.canvas.offset_default_distance = previous.canvas.offset_default_distance
        self.canvas.offset_gap_type = previous.canvas.offset_gap_type
        self.canvas.circle_ttr_last_radius = previous.canvas.circle_ttr_last_radius
        self.canvas.rotation_default_angle = previous.canvas.rotation_default_angle
        self.canvas.scale_default_factor = previous.canvas.scale_default_factor
        self.drawing_command_bar.continue_from(previous.drawing_command_bar)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.canvas.continuous_lines:
            # Esc exits the command, never the whole in-place editing session.
            self.canvas.keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)

    def _preview_drag(
        self,
        entities: tuple[SketchEntity, ...],
        constraints: tuple[SketchConstraint, ...],
        reference: SketchGeometryReference,
        target_mm: Point2D,
    ) -> SketchConstraintSolveResult:
        if self._drag_preview is None:
            return SketchConstraintSolveResult(
                "unavailable", None, None, message="草图约束拖动求解器不可用。"
            )
        sketch = Sketch(
            self._drag_preview_sketch_id,
            self.current_frame(),
            entities,
            constraints,
            self.layer_table,
            self._support_face,
        )
        return self._drag_preview(sketch, reference, target_mm)

    def current_frame(self) -> WorkPlaneFrame:
        if self.plane_combo.currentText() == "所选面" and self._attached_frame is not None:
            return self._attached_frame
        plane = {
            "XY": WorkPlaneFrame.xy(),
            "XZ": WorkPlaneFrame.xz(),
            "YZ": WorkPlaneFrame.yz(),
        }[self.plane_combo.currentText()]
        origin = tuple(self.origin_fields[axis].value() for axis in ("X", "Y", "Z"))
        return WorkPlaneFrame(
            cast("tuple[float, float, float]", origin),
            plane.u_axis,
            plane.v_axis,
            plane.normal,
        )

    def _set_active_layer(self, name: str) -> None:
        if not name:
            return
        layer = self.layer_table.get(name)
        if layer.frozen:
            with QSignalBlocker(self.layer_combo):
                self.layer_combo.setCurrentText(self.canvas.active_layer_name)
            self.status_label.setText("该图层已冻结；请先使用‘解冻图层’解冻。")
            return
        self.canvas.set_layer_table(self.layer_table, name)
        if self.active_layer_manager is not None:
            self.active_layer_manager.set_layers(self.layer_table, self.dimension_layer, name)
        if layer.locked or not layer.displayed:
            self.status_label.setText("当前图层隐藏或已锁定，不能放置新图元。")

    def _populate_thaw_layers(self) -> None:
        menu = self.thaw_layer_button.menu()
        menu.clear()
        for layer in self.layer_table.layers:
            if layer.frozen:
                action = menu.addAction(layer.name)
                action.triggered.connect(
                    lambda _checked=False, name=layer.name: self._thaw_layer(name)
                )
        if not menu.actions():
            menu.addAction("没有冻结图层").setEnabled(False)

    def _thaw_layer(self, name: str) -> None:
        layer = self.layer_table.get(name)
        if layer.frozen:
            self.request_layer_update(
                self.layer_table.replace(replace(layer, frozen=False)), self.dimension_layer
            )

    def _rebuild_layer_combo(self, layers: SketchLayerTable, active: str) -> None:
        with QSignalBlocker(self.layer_combo):
            self.layer_combo.clear()
            for layer in layers.layers:
                if layer.frozen and not self.canvas.select_committed_entities:
                    continue
                self.layer_combo.addItem(layer.name)
                if layer.frozen:
                    index = self.layer_combo.count() - 1
                    self.layer_combo.setItemData(
                        index, "已冻结：请使用解冻图层", Qt.ItemDataRole.ToolTipRole
                    )
                    self.layer_combo.setItemData(
                        index, QColor("gray"), Qt.ItemDataRole.ForegroundRole
                    )
            self.layer_combo.setCurrentText(active)

    def _assign_selection_to_current_layer(self) -> None:
        selected = tuple(self.canvas.selected_entity_ids)
        if (
            len(self.canvas.selected_constraint_ids) == 1
            and not selected
            and not self.canvas.selected_raster_ids
        ):
            self._assign_dimension_layer(self.layer_combo.currentText())
            return
        if (
            not selected
            and not self.canvas.selected_raster_ids
            and not self.canvas.selected_constraint_ids
        ):
            self.status_label.setText("请先选中要更改图层的对象。")
            return
        self.assign_selection_layer_requested.emit(selected, self.layer_combo.currentText())

    def _apply_layer_table(self, layers: SketchLayerTable, active_layer_name: str) -> None:
        self.layer_table = layers
        if active_layer_name not in {layer.name for layer in layers.layers}:
            active_layer_name = "0"
        self._rebuild_layer_combo(layers, active_layer_name)
        self.canvas.set_layer_table(layers, active_layer_name, record_history=True)
        self.canvas.changed.emit()

    @property
    def draft_signature(self) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]]:
        return (tuple(self.canvas.entities), tuple(self.canvas.constraints))

    def set_document_layers(self, layers: SketchLayerTable, dimension_layer: str) -> None:
        if dimension_layer != ".":
            layers.get(dimension_layer)
        changed = layers != self.layer_table or dimension_layer != self.dimension_layer
        if (
            not changed
            and self.canvas.document_layer_table == layers
            and self.canvas.preserve_document_layers == self.document_layer_mode
        ):
            self.dimensions.sync_layer_combo()
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    layers, dimension_layer, self.layer_combo.currentText()
                )
            return
        if changed:
            self.dimensions.cancel()
        self.layer_table = layers
        self.dimension_layer = dimension_layer
        self.canvas.document_layer_table = layers
        self.canvas.preserve_document_layers = self.document_layer_mode
        active = self.layer_combo.currentText() or "0"
        try:
            if layers.get(active).frozen:
                active = next((layer.name for layer in layers.layers if not layer.frozen), "0")
        except KeyError:
            active = "0"
        self._rebuild_layer_combo(layers, active)
        self.canvas.set_layer_table(layers, active)
        self.canvas.set_background_sketches(self._context_sketches, self.current_frame())
        self.dimensions.sync_layer_combo()
        if self.active_layer_manager is not None:
            self.active_layer_manager.set_layers(layers, dimension_layer, active)
        self._sync_state()

    def request_layer_update(
        self,
        layers: SketchLayerTable,
        dimension_layer: str,
        assignments: tuple[dict[str, object], ...] = (),
        *,
        migrate_draft: bool = False,
    ) -> None:
        try:
            for sketch in self.dimension_sources():
                for entity in sketch.entities:
                    layers.get(entity.layer_name)
                for constraint in sketch.constraints:
                    if constraint.layer_name is not None:
                        layers.get(constraint.layer_name)
        except KeyError as exc:
            self.status_label.setText(f"图层 {exc} 仍被图元或标注使用，不能删除。")
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.layer_combo.currentText()
                )
            return
        if (
            layers == self.layer_table
            and dimension_layer == self.dimension_layer
            and not assignments
            and not migrate_draft
        ):
            return
        if layers.get(self.layer_combo.currentText() or "0").frozen:
            self.status_label.setText("当前绘图层不能冻结，请先切换图层。")
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.layer_combo.currentText()
                )
            return
        if self._can_finish is not None and not self._can_finish():
            self.status_label.setText("工作线程忙碌，请稍后修改图层。")
            return
        params: dict[str, object] = {
            "layers": layers.to_mapping(),
            "dimension_layer": dimension_layer,
            "assignments": list(assignments),
        }
        if self.document_layer_mode:
            self.layer_change_requested.emit({"params": params, "migrate_draft": migrate_draft})
            return
        self.canvas.set_layer_table(layers, self.canvas.active_layer_name, record_history=True)
        self.set_document_layers(layers, dimension_layer)
        if migrate_draft:
            self.apply_draft_dim_migration()

    def apply_draft_dim_migration(self) -> None:
        if any(c.kind in DIMENSION_KINDS and c.layer_name is None for c in self.canvas.constraints):
            original = self.dimension_sources()[0]
            solved = replace(
                original,
                constraints=tuple(
                    replace(c, layer_name="DIM")
                    if c.kind in DIMENSION_KINDS and c.layer_name is None
                    else c
                    for c in original.constraints
                ),
            )
            self.canvas.apply_constraint_solution(original, solved)

    def migrate_legacy_dimensions(self) -> None:
        table = merge_layer_tables(self.layer_table, include_dim=True)
        assignments: tuple[dict[str, object], ...] = tuple(
            {
                "sketch_id": s.sketch_id,
                "constraint_ids": [
                    c.constraint_id
                    for c in s.constraints
                    if c.kind in DIMENSION_KINDS and c.layer_name is None
                ],
                "layer_name": "DIM",
            }
            for s in self._context_sketches
            if any(c.kind in DIMENSION_KINDS and c.layer_name is None for c in s.constraints)
        )
        self.request_layer_update(table, self.dimension_layer, assignments, migrate_draft=True)

    def open_quick_select(self) -> None:
        if (
            self._navigation_busy()
            or self.canvas.active_transform is not None
            or (self._can_finish is not None and not self._can_finish())
        ):
            self.status_label.setText("请先完成或取消当前操作，再快速选择。")
            self.drawing_command_bar.status.setText("请先完成或取消当前操作，再快速选择。")
            return

        def source_state() -> tuple[object, ...]:
            return (
                self.canvas.selectable_entities(),
                self.canvas.visible_dimensions(),
                self.canvas.drawing_rasters,
                self.canvas.layer_table,
                frozenset(self.canvas.selected_entity_ids),
                frozenset(self.canvas.selected_constraint_ids),
                frozenset(self.canvas.selected_raster_ids),
                self.canvas.tool,
                self.canvas.source_revision_provider()
                if self.canvas.source_revision_provider is not None
                else None,
            )

        original = source_state()
        dimensions = tuple(
            (constraint.constraint_id, self.canvas.annotation_layer(constraint).name)
            for constraint in self.canvas.visible_dimensions()
            if self.canvas.select_committed_entities or constraint in self.canvas.constraints
            if not self.canvas.annotation_layer(constraint).locked
        )
        images = tuple(
            (image.image_id, image.layer_name)
            for image in self.canvas.drawing_rasters
            if self.canvas.layer_table.get(image.layer_name).displayed
            and not self.canvas.layer_table.get(image.layer_name).locked
        )
        dialog = QuickSelectDialog(
            self.canvas.selectable_entities(),
            self,
            dimensions=dimensions,
            dimension_values={
                constraint.constraint_id: (value, constraint.unit)
                for constraint in self.canvas.visible_dimensions()
                if (value := self.canvas.dimension_display_value(constraint)) is not None
                and constraint.unit is not None
            },
            images=images,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        if (
            self._navigation_busy()
            or self.canvas.active_transform is not None
            or (self._can_finish is not None and not self._can_finish())
            or source_state() != original
        ):
            self.status_label.setText("当前操作已变化，请重新快速选择。")
            self.drawing_command_bar.status.setText("当前操作已变化，请重新快速选择。")
            return
        selected = frozenset(self.canvas.selected_entity_ids)
        selected_dimensions = frozenset(self.canvas.selected_constraint_ids)
        selected_images = frozenset(self.canvas.selected_raster_ids)
        matches = dialog.matching_ids(self.canvas.selectable_entities(), selected)
        dimension_matches = dialog.matching_annotations(dimensions, selected_dimensions, "尺寸标注")
        image_matches = dialog.matching_annotations(images, selected_images, "图片")
        if not self.canvas.set_tool("选择元素"):
            self.status_label.setText(self.canvas.message)
            return
        self.canvas.selected_entity_ids = set(
            selected | matches if dialog.append.isChecked() else matches
        )
        self.canvas.selected_constraint_ids = set(
            selected_dimensions | dimension_matches
            if dialog.append.isChecked()
            else dimension_matches
        )
        self.canvas.selected_raster_ids = set(
            selected_images | image_matches if dialog.append.isChecked() else image_matches
        )
        self.canvas.clear_selected_tangent_segments()
        self.canvas.message = (
            f"快速选择：已选 {len(self.canvas.selected_entity_ids)} 个图元、"
            f"{len(self.canvas.selected_constraint_ids)} 个标注、"
            f"{len(self.canvas.selected_raster_ids)} 张图片。"
        )
        self.canvas.changed.emit()
        self.canvas.update()
        self.canvas.setFocus()

    def open_layer_manager(self) -> None:
        if self.active_layer_manager is not None:
            self.active_layer_manager.show()
            self.active_layer_manager.raise_()
            return
        used = tuple(e.layer_name for s in self.dimension_sources() for e in s.entities)
        used += tuple(
            c.layer_name
            for s in self.dimension_sources()
            for c in s.constraints
            if c.layer_name is not None
        )
        panel = DrawingLayerPanel(
            self.layer_table, self.layer_combo.currentText(), self.dimension_layer, used, self
        )
        self.active_layer_manager = panel
        panel.properties_changed.connect(self.request_layer_update)
        panel.current_layer_changed.connect(self.layer_combo.setCurrentText)
        panel.migrate_requested.connect(self.migrate_legacy_dimensions)
        panel.show()

    def finish_sketch(self) -> None:
        if self.canvas.has_active_edit_gesture:
            self.status_label.setText("先松开鼠标确认当前草稿预览，或按 Esc 取消后再完成草图。")
            return
        if self._can_finish is not None and not self._can_finish():
            self.status_label.setText("应用正在执行其他命令；草图仍保留在编辑器中。")
            return
        if self.canvas.has_pending_geometry:
            self.status_label.setText("当前图元未完成；先完成图元或按 Esc 清除后再完成草图。")
            return
        if not self.canvas.entities and self.canvas.mixed_move is None:
            self.status_label.setText("草图至少需要一个有效元素。")
            return
        try:
            self.result_sketch = Sketch(
                uuid4().hex,
                self.current_frame(),
                tuple(self.canvas.entities),
                constraints=tuple(self.canvas.constraints),
                layers=self.layer_table,
                support_face=self._support_face,
            )
            arrays = tuple(
                replace(
                    array,
                    sources=tuple(
                        replace(ref, sketch_id=self.result_sketch.sketch_id)
                        if ref.sketch_id == self.draft_sketch_id
                        else ref
                        for ref in array.sources
                    ),
                    members=tuple(
                        replace(
                            member,
                            source=replace(member.source, sketch_id=self.result_sketch.sketch_id)
                            if member.source.sketch_id == self.draft_sketch_id
                            else member.source,
                            target=replace(member.target, sketch_id=self.result_sketch.sketch_id),
                            replacement=replace(
                                member.replacement,
                                source=replace(
                                    member.replacement.source,
                                    sketch_id=self.result_sketch.sketch_id,
                                )
                                if member.replacement.source.sketch_id == self.draft_sketch_id
                                else member.replacement.source,
                                anchor_source=replace(
                                    member.replacement.anchor_source,
                                    sketch_id=self.result_sketch.sketch_id,
                                )
                                if member.replacement.anchor_source is not None
                                and member.replacement.anchor_source.sketch_id
                                == self.draft_sketch_id
                                else member.replacement.anchor_source,
                            )
                            if member.replacement is not None
                            else None,
                        )
                        for member in array.members
                    ),
                    base_point=replace(
                        array.base_point,
                        source=replace(
                            array.base_point.source, sketch_id=self.result_sketch.sketch_id
                        ),
                    )
                    if array.base_point is not None
                    and array.base_point.source is not None
                    and array.base_point.source.sketch_id == self.draft_sketch_id
                    else array.base_point,
                    extra_outputs=tuple(
                        replace(
                            output,
                            source=replace(output.source, sketch_id=self.result_sketch.sketch_id)
                            if output.source.sketch_id == self.draft_sketch_id
                            else output.source,
                            target=replace(output.target, sketch_id=self.result_sketch.sketch_id)
                            if output.target.sketch_id == self.draft_sketch_id
                            else output.target,
                            anchor_source=replace(
                                output.anchor_source, sketch_id=self.result_sketch.sketch_id
                            )
                            if output.anchor_source.sketch_id == self.draft_sketch_id
                            else output.anchor_source,
                        )
                        for output in array.extra_outputs
                    ),
                )
                for array in self.canvas.pending_associative_arrays
            )
            if arrays:
                sketches = (self.result_sketch, *self.dimension_sources()[1:])
                propagate_array_changes(sketches, sketches, arrays)
            self.result_associative_arrays = arrays
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.accept()

    def _change_tool(self, tool: str) -> None:
        if hasattr(self, "dimensions"):
            self.dimensions.cancel()
        return_to_zero = (
            tool in {"点", "直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
            and self.canvas.active_layer_name.casefold() == "dim"
        )
        if return_to_zero and self.layer_table.get("0").frozen:
            self.canvas.message = "0 图层已冻结，请先解冻后开始绘图。"
        elif self.canvas.set_tool(tool):
            if tool != "选择元素":
                self.parameter_tabs.setCurrentWidget(self.tool_panel)
            if hasattr(self, "drawing_command_bar"):
                self.drawing_command_bar.remember_tool(tool)
            if return_to_zero:
                self.layer_combo.setCurrentText("0")
            self.canvas.setFocus()
            return
        blocker = QSignalBlocker(self.tool_combo)
        self.tool_combo.setCurrentText(self.canvas.tool)
        del blocker
        self.status_label.setText(self.canvas.message)

    def _activate_command_tool(self, tool: str) -> bool:
        self._change_tool(tool)
        if self.canvas.tool != tool or self.canvas.has_pending_geometry:
            return False
        with QSignalBlocker(self.tool_combo):
            self.tool_combo.setCurrentText(tool)
        return True

    def _change_plane(self, plane: str) -> None:
        if (
            self.canvas.entities
            or self.canvas.has_pending_geometry
            or self.canvas.mixed_move is not None
        ):
            blocker = QSignalBlocker(self.plane_combo)
            self.plane_combo.setCurrentText(self._selected_plane)
            del blocker
            self.status_label.setText("草图已有元素，工作平面已锁定；请取消并重新开始以更换平面。")
            return
        was_attached = self._support_face is not None
        if plane == "所选面" and self._attached_frame is not None:
            self._support_face = self._initial_support_face
            for axis, value in zip(("X", "Y", "Z"), self._attached_frame.origin_mm, strict=True):
                self.origin_fields[axis].setValue(value)
                self.origin_fields[axis].setReadOnly(True)
                self.origin_fields[axis].setToolTip("原点由所选模型面定义。")
        else:
            self._support_face = None
            for axis in ("X", "Y", "Z"):
                field = self.origin_fields[axis]
                if was_attached:
                    field.setValue(0.0)
                field.setReadOnly(False)
                field.setToolTip("")
        self._selected_plane = plane
        self.canvas.ucs_plane = plane
        self._sync_state()
        self.canvas.update()

    def _undo_draft_operation(self) -> None:
        if self.document_layer_mode:
            self.document_undo_requested.emit()
        else:
            self.canvas.undo_last_operation()

    def _redo_draft_operation(self) -> None:
        if self.document_layer_mode:
            self.document_redo_requested.emit()
        else:
            self.canvas.redo_last_operation()

    def _add_coordinate_point(self) -> None:
        self.canvas.add_coordinate_point(
            (self.u_field.value(), self.v_field.value()), exact_point=True
        )

    def _start_two_object_tangent(self) -> None:
        """Start mouse-based tangency for the active drawing tool."""
        if self.canvas.tool == "直线":
            if self.canvas.has_pending_geometry and not self.canvas.line_tangent_active:
                self.canvas.message = "请先完成或取消当前直线，再选择两个相切对象。"
                self.canvas.changed.emit()
                return
            started = self.canvas.begin_line_tangent_pick(require_two=True)
        elif self.canvas.tool == "圆":
            started = self.canvas.begin_circle_ttr()
        elif self.canvas.tool == "圆弧":
            started = self.canvas.begin_arc_ttr()
        else:
            return
        if started:
            self.canvas.setFocus()

    def _start_center_arc(self) -> None:
        if self.canvas.tool != "圆弧":
            self.tool_combo.setCurrentText("圆弧")
        if self.canvas.tool == "圆弧" and self.canvas.begin_arc_center():
            self.canvas.setFocus()

    def _start_three_point_arc(self) -> None:
        if self.canvas.tool != "圆弧":
            self.tool_combo.setCurrentText("圆弧")
        if self.canvas.tool == "圆弧" and self.canvas.begin_arc_three_point():
            self.canvas.setFocus()

    def _start_tangent_arc(self) -> None:
        if self.canvas.tool != "圆弧":
            self.tool_combo.setCurrentText("圆弧")
        if self.canvas.tool == "圆弧" and self.canvas.begin_arc_ttr():
            self.canvas.setFocus()

    def _update_transform_options(self) -> None:
        self.canvas.configure_active_transform(
            reference_rotation=self.rotation_reference_check.isChecked(),
            keep_source=self.mirror_keep_source_check.isChecked(),
        )

    def _update_polygon_options(self) -> None:
        self.canvas.configure_polygon(
            self.polygon_sides_field.value(),
            circumscribed=self.polygon_mode_combo.currentText() == "外切圆",
        )

    def _configure_command_polygon(self, sides: int, circumscribed: bool) -> None:
        self.polygon_sides_field.setValue(sides)
        self.polygon_mode_combo.setCurrentText("外切圆" if circumscribed else "内接圆")
        self._update_polygon_options()

    def _apply_numeric_rotation(self) -> None:
        if self.canvas.rotation_center is not None:
            self.canvas.apply_rotation_angle(self.angle_field.value())
        else:
            self._apply_transform("rotate")

    def _start_transform(self, operation: str) -> None:
        self.parameter_tabs.setCurrentWidget(self.modify_page)
        if operation in {"move", "copy", "rotate", "mirror", "scale"}:
            self.canvas.begin_transform(
                operation,
                reference_rotation=self.rotation_reference_check.isChecked(),
                keep_source=self.mirror_keep_source_check.isChecked(),
            )
        else:
            self._apply_transform(operation)

    def _sync_dynamic_input(self) -> None:
        pending = self.canvas.has_pending_geometry
        finished = self._dynamic_was_pending and not pending
        self._dynamic_was_pending = pending
        ended_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count == 0
        )
        if finished or ended_line:
            self.dynamic_input.clear_locks()
        if not self.dynamic_input_check.isChecked():
            self.dynamic_input.clear_locks()
            self.dynamic_input.hide()
            self._dynamic_configured_tool = ""
            self._drawing_cursor_dimensions.hide()
            self._drawing_cursor_entry.hide()
            return
        tool = (
            "line"
            if self.canvas.tool == "圆弧"
            and self.canvas.arc_creation_mode == "three_point"
            and not self.canvas.arc_ttr_active
            else ("arc_angle" if self.canvas.pending_point_count >= 2 else "circle")
            if self.canvas.tool == "圆弧"
            and self.canvas.arc_creation_mode == "center"
            and not self.canvas.arc_ttr_active
            else {"直线": "line", "矩形": "rectangle", "圆": "circle"}.get(
                self.canvas.tool, "select"
            )
        )
        if tool != self._dynamic_configured_tool:
            self.dynamic_input.configure(tool)
            self._dynamic_configured_tool = tool
        self.dynamic_input.setVisible(tool != "select")
        continuous_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count > 0
        )
        if not self.canvas.arc_ttr_radius_pending and (
            tool == "select" or not (self.canvas.has_pending_geometry or continuous_line)
        ):
            self._drawing_cursor_entry.hide()
        self._update_drawing_cursor_dimensions()

    def _start_cursor_entry(self, event: QKeyEvent) -> bool:
        text = event.text()
        tangent_radius = self.canvas.arc_ttr_radius_pending
        if (
            not self.dynamic_input_check.isChecked()
            or (
                not tangent_radius
                and self._dynamic_configured_tool
                not in {"line", "rectangle", "circle", "arc_angle"}
            )
            or self.canvas.active_transform is not None
            or self._drawing_cursor_position is None
            or not (
                tangent_radius
                or self.canvas.has_pending_geometry
                or self.canvas.pending_point_count > 0
            )
            or len(text) != 1
            or text not in "0123456789+-."
            or event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            return False
        entry = self._drawing_cursor_entry
        self._drawing_cursor_field = 0
        entry.setText(text)
        entry.setStyleSheet("")
        entry.setToolTip("")
        entry.setPlaceholderText(
            "半径"
            if tangent_radius
            else "角度"
            if self._dynamic_configured_tool == "arc_angle"
            else "尺寸"
        )
        entry.setMaximumWidth(max(1, min(140, self.canvas.width())))
        entry.adjustSize()
        position = self._drawing_cursor_position
        x = position.x() + 14
        if x + entry.width() > self.canvas.width():
            x = max(0, position.x() - entry.width() - 14)
        y = position.y() + 38
        if y + entry.height() > self.canvas.height():
            y = max(0, position.y() - entry.height() - 14)
        entry.move(x, y)
        entry.show()
        entry.raise_()
        entry.setFocus()
        entry.setCursorPosition(len(text))
        return True

    def _commit_cursor_entry(self) -> bool:
        entry = self._drawing_cursor_entry
        if entry.isHidden():
            return True
        try:
            value = float(entry.text().strip())
        except ValueError:
            value = math.nan
        angle = self._dynamic_configured_tool == "arc_angle" or (
            self._dynamic_configured_tool == "line" and self._drawing_cursor_field == 1
        )
        if not math.isfinite(value) or abs(value) > 1e9 or (not angle and round(value, 6) <= 0):
            message = "请输入有效的角度。" if angle else "请输入大于零的有效尺寸。"
            entry.setToolTip(message)
            entry.setStyleSheet("border: 1px solid #b42318;")
            self.canvas.message = message
            self.canvas.changed.emit()
            entry.setFocus()
            return False
        field = (
            self.dynamic_input.first_value
            if self._drawing_cursor_field == 0
            else self.dynamic_input.second_value
        )
        lock = (
            self.dynamic_input.first_lock
            if self._drawing_cursor_field == 0
            else self.dynamic_input.second_lock
        )
        lock.setChecked(True)
        field.setValue(value)
        entry.setStyleSheet("")
        entry.setToolTip("")
        return True

    def _guard_cursor_entry(self) -> bool:
        if self.canvas.arc_ttr_radius_pending and not self._drawing_cursor_entry.isHidden():
            self.canvas.message = "请输入半径并按 Enter，或按 Esc 取消。"
            self.canvas.changed.emit()
            self._drawing_cursor_entry.setFocus()
            return False
        return self._accept_cursor_entry()

    def _submit_tangent_cursor_entry(self) -> bool:
        if not self.canvas.arc_ttr_radius_pending or self._drawing_cursor_entry.isHidden():
            return False
        self._accept_cursor_entry()
        return True

    def _accept_cursor_entry(self) -> bool:
        if self.canvas.arc_ttr_radius_pending and not self._drawing_cursor_entry.isHidden():
            entry = self._drawing_cursor_entry
            try:
                radius = float(entry.text().strip())
            except ValueError:
                radius = math.nan
            if not math.isfinite(radius) or radius <= 0:
                self.canvas.message = "请输入大于零的有限半径。"
                self.canvas.changed.emit()
            elif self.canvas.finish_arc_ttr(radius):
                entry.hide()
                entry.setStyleSheet("")
                entry.setToolTip("")
                self.canvas.setFocus()
                return True
            entry.setToolTip(self.canvas.message)
            entry.setStyleSheet("border: 1px solid #b42318;")
            entry.setFocus()
            return False
        if not self._commit_cursor_entry():
            return False
        if not self._drawing_cursor_entry.isHidden():
            self._drawing_cursor_entry.hide()
            self.canvas.setFocus()
        return True

    def _advance_cursor_entry(self) -> None:
        if self.canvas.arc_ttr_radius_pending:
            self._accept_cursor_entry()
            return
        if not self._commit_cursor_entry():
            return
        if self._drawing_cursor_field == 0 and self._dynamic_configured_tool not in {
            "circle",
            "arc_angle",
        }:
            self._drawing_cursor_field = 1
            self._drawing_cursor_entry.clear()
            self._drawing_cursor_entry.setPlaceholderText(
                "角度" if self._dynamic_configured_tool == "line" else "高度"
            )
            self._drawing_cursor_entry.setFocus()
        else:
            self._accept_cursor_entry()

    def _cancel_cursor_entry(self) -> None:
        self._drawing_cursor_entry.hide()
        self.canvas.setFocus()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self.canvas, event)

    def _on_drawing_pointer_moved(self, position: QPoint) -> None:
        self._drawing_cursor_position = position
        self._update_drawing_cursor_dimensions()

    def _on_drawing_pointer_left(self) -> None:
        self._drawing_cursor_position = None
        self._drawing_cursor_dimensions.hide()

    def _update_drawing_cursor_dimensions(self) -> None:
        hint = self._drawing_cursor_dimensions
        position = self._drawing_cursor_position
        continuous_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count > 0
        )
        if (
            not self.dynamic_input_check.isChecked()
            or self._dynamic_configured_tool == "select"
            or not (self.canvas.has_pending_geometry or continuous_line)
            or position is None
        ):
            hint.hide()
            return
        dynamic = self.dynamic_input
        label = dynamic.first_label.text() or dynamic.circle_mode.currentText()
        first = f"{label} {dynamic.first_value.text()}"
        if dynamic.first_lock.isChecked():
            first += "（锁定）"
        parts = [first]
        if not dynamic.second_value.isHidden():
            second = f"{dynamic.second_label.text()} {dynamic.second_value.text()}"
            if dynamic.second_lock.isChecked():
                second += "（锁定）"
            parts.append(second)
        hint.setText("   ".join(parts))
        hint.setMaximumWidth(max(1, self.canvas.width()))
        hint.adjustSize()
        x = min(max(0, position.x() + 14), max(0, self.canvas.width() - hint.width()))
        y = min(max(0, position.y() + 16), max(0, self.canvas.height() - hint.height()))
        hint.move(x, y)
        hint.show()
        hint.raise_()

    def _resolve_dynamic_point(self, start: Point2D, point: Point2D) -> Point2D:
        if not self.dynamic_input_check.isChecked() or self._dynamic_configured_tool == "select":
            return point
        if self.canvas.tool == "圆弧" and self.canvas.arc_creation_mode == "three_point":
            start = self.canvas.pending_last_point or start
        self.dynamic_input.update_from_pointer(start, point)
        return self.dynamic_input.resolve(start, point)

    def _clear_dynamic_locks(self, _point: object) -> None:
        self.dynamic_input.clear_locks()

    def _activate_command_transform(self, operation: str) -> bool:
        if operation == "mirror":
            self.canvas.begin_transform(
                "mirror",
                keep_source=self.mirror_keep_source_check.isChecked(),
                ask_mirror_erase=True,
            )
            return self.canvas.active_transform == operation
        if operation == "offset":
            self.canvas.begin_interactive_offset()
            return self.canvas.active_transform == operation
        if operation == "erase" and (
            self.canvas.selected_entity_ids
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_id
        ):
            return self.canvas.delete_selected()
        if operation == "erase":
            self.canvas.begin_transform(operation)
            return self.canvas.active_transform == operation
        self._start_transform(operation)
        return self.canvas.active_transform == operation

    def _apply_command_rectangular_array(
        self, rows: int, columns: int, row_spacing: float, column_spacing: float, angle_deg: float
    ) -> tuple[bool, str]:
        try:
            self.canvas.begin_rectangular_array_preview(
                rows, columns, row_spacing, column_spacing, angle_deg
            )
        except ValueError as exc:
            return False, str(exc)
        self.array_rows_field.setValue(rows)
        self.array_columns_field.setValue(columns)
        self.delta_v_field.setValue(row_spacing)
        self.delta_u_field.setValue(column_spacing)
        return True, self.canvas.message

    def _commit_command_rectangular_array(
        self,
        associative: bool,
        rows: int,
        columns: int,
        row_spacing: float,
        column_spacing: float,
        angle_deg: float,
        base_point: Point2D | SketchGeometryReference | None,
    ) -> tuple[bool, str]:
        array: AssociativeRectArray | None = None
        if associative:
            if not self.document_layer_mode or self._support_face is not None:
                return False, "关联阵列目前只支持独立二维草稿。"
            sources = (
                *self.canvas.entities,
                *(entity for entity, _ in self.canvas.background_entities),
            )
            selected = tuple(
                entity for entity in sources if entity.entity_id in self.canvas.selected_entity_ids
            )
            if len(selected) != len(self.canvas.selected_entity_ids):
                return False, "关联阵列源图元身份不唯一或已变化。"
            sketches = self.dimension_sources()
            refs_list: list[ArrayEntityRef] = []
            for entity in selected:
                owners = [
                    sketch.sketch_id
                    for sketch in sketches
                    if any(item.entity_id == entity.entity_id for item in sketch.entities)
                ]
                if len(owners) != 1:
                    return False, "关联阵列源图元身份不唯一或已变化。"
                refs_list.append(ArrayEntityRef(owners[0], entity.entity_id))
            refs = tuple(refs_list)
            base: ArrayBasePoint | None = None
            if isinstance(base_point, SketchGeometryReference):
                key_sources = tuple(ref for ref in refs if ref.entity_id == base_point.entity_id)
                if len(key_sources) != 1:
                    return False, "阵列基点必须引用唯一的源对象。"
                base = ArrayBasePoint(source=key_sources[0], reference=base_point)
            elif base_point is not None:
                base = ArrayBasePoint(point_mm=base_point)
            expected = (rows * columns - 1) * len(refs)
            if not refs or len(self.canvas.transform_preview_entities) != expected:
                return False, "阵列预览已变化；请重新开始。"
            copies = iter(self.canvas.transform_preview_entities)
            members = tuple(
                ArrayMember(
                    ref, ArrayEntityRef(self.draft_sketch_id, next(copies).entity_id), row, column
                )
                for row in range(rows)
                for column in range(columns)
                if row or column
                for ref in refs
            )
            try:
                array = AssociativeRectArray(
                    uuid4().hex,
                    self.current_frame(),
                    rows,
                    columns,
                    row_spacing,
                    column_spacing,
                    refs,
                    members,
                    angle_deg,
                    base,
                )
                draft = Sketch(
                    self.draft_sketch_id,
                    self.current_frame(),
                    (*self.canvas.entities, *self.canvas.transform_preview_entities),
                    tuple(self.canvas.constraints),
                    self.layer_table,
                )
                states = (draft, *self.dimension_sources()[1:])
                propagate_array_changes(
                    states, states, (*self.canvas.pending_associative_arrays, array)
                )
            except ValueError as exc:
                return False, str(exc)
        success = self.canvas.commit_rectangular_array_preview()
        if success and array is not None:
            self.canvas.pending_associative_arrays.append(array)
            self.canvas.message = "已生成关联阵列；完成草图后修改源图元会更新副本。"
            self.canvas.changed.emit()
        return success, self.canvas.message

    def _apply_transform(self, operation: str) -> None:
        self.canvas.cancel_transform()
        if (
            self.canvas.source_revision_provider is not None
            and self.canvas.source_context_revision is not None
            and self.canvas.source_revision_provider() != self.canvas.source_context_revision
            and any(
                entity.entity_id in self.canvas.selected_entity_ids
                for entity, _layer in self.canvas.background_entities
            )
        ):
            self.canvas.source_revision_invalidated.emit()
            self.status_label.setText("文档已变化；请重新选择图元。")
            return
        if (
            self.canvas.selected_raster_id is not None
            and self.canvas.selected_entity_ids
            and operation in {"move", "copy", "rotate", "mirror"}
        ):
            keep_source = operation == "mirror" and self.mirror_keep_source_check.isChecked()
            self.canvas.begin_transform(operation, keep_source=keep_source)
            if self.canvas.active_transform != operation:
                return
            selected = tuple(self.canvas.selected_entity_ids)
            center = (self.center_u_field.value(), self.center_v_field.value())
            delta = (self.delta_u_field.value(), self.delta_v_field.value())
            if operation in {"move", "copy"} and math.hypot(*delta) <= 1e-9:
                self.canvas.cancel_transform()
                self.status_label.setText("请指定非零 ΔU / ΔV。")
                return
            if operation in {"move", "copy"} and any(
                entity.entity_id in self.canvas.selected_entity_ids
                for entity in self.canvas.entities
            ):
                if operation == "copy":
                    self.canvas.use_single_copy_for_command()
                self.canvas.add_coordinate_point((0, 0), exact_point=True)
                self.canvas.add_coordinate_point(delta, exact_point=True)
                return
            if operation == "rotate" and any(
                entity.entity_id in self.canvas.selected_entity_ids
                for entity in self.canvas.entities
            ):
                self.canvas.add_coordinate_point(center, exact_point=True)
                self.canvas.apply_rotation_angle(self.angle_field.value())
                return
            end = (
                (center[0] + 1.0, center[1])
                if self.mirror_axis_combo.currentText() == "水平轴"
                else (center[0], center[1] + 1.0)
            )
            if operation == "mirror" and any(
                entity.entity_id in self.canvas.selected_entity_ids
                for entity in self.canvas.entities
            ):
                self.canvas.add_coordinate_point(center, exact_point=True)
                self.canvas.add_coordinate_point(end, exact_point=True)
                return
            self.canvas.cancel_transform()
            if operation == "move":
                self.canvas.committed_move_requested.emit(selected, delta)
            elif operation == "copy":
                self.canvas.committed_mixed_copy_requested.emit(selected, delta)
            elif operation == "rotate":
                self.canvas.committed_rotation_requested.emit(
                    selected, center, self.angle_field.value()
                )
            elif keep_source:
                self.canvas.committed_mirror_copy_requested.emit(selected, center, end)
            else:
                self.canvas.committed_mirror_requested.emit(selected, center, end)
            return
        if self.canvas.selected_raster_id is not None and operation in {
            "move",
            "copy",
            "rotate",
            "mirror",
        }:
            center = (self.center_u_field.value(), self.center_v_field.value())
            if operation in {"move", "copy"}:
                point = (
                    center[0] + self.delta_u_field.value(),
                    center[1] + self.delta_v_field.value(),
                )
            else:
                point = (
                    (center[0] + 1, center[1])
                    if self.mirror_axis_combo.currentText() == "水平轴"
                    else (center[0], center[1] + 1)
                )
            self.canvas.apply_numeric_raster_transform(
                operation,
                center,
                point,
                angle=self.angle_field.value(),
                keep_source=operation == "mirror" and self.mirror_keep_source_check.isChecked(),
            )
            return
        if self.canvas.selected_raster_ids and operation in {
            "offset",
            "linear_array",
            "rectangular_array",
            "circular_array",
        }:
            self.canvas.message = "图片暂不支持此操作；请选择其他对象后重试。"
            self.canvas.changed.emit()
            return
        error = self.canvas.transform_selection_error(operation)
        if error:
            self.canvas.message = error
            self.canvas.changed.emit()
            return
        if operation in {"offset", "linear_array", "rectangular_array", "circular_array"} and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            background = tuple(entity for entity, _layer in self.canvas.background_entities)
            source = (*self.canvas.entities, *background)
            selected = tuple(
                entity.entity_id
                for entity in source
                if entity.entity_id in self.canvas.selected_entity_ids
            )
            if len(selected) != len(set(selected)):
                self.status_label.setText("选择的图元身份不唯一；操作未应用。")
                return
            if set(selected) != self.canvas.selected_entity_ids:
                self.status_label.setText("选择的图元已变化；操作未应用。")
                return
            try:
                if operation == "offset":
                    result = offset_entities(
                        source,
                        selected,
                        self.offset_distance_field.value(),
                        gap_type=self.canvas.offset_gap_type,
                    )
                elif operation == "linear_array":
                    result = linear_array_entities(
                        source,
                        selected,
                        count=self.count_field.value(),
                        step_mm=(self.delta_u_field.value(), self.delta_v_field.value()),
                    )
                elif operation == "rectangular_array":
                    result = rectangular_array_entities(
                        source,
                        selected,
                        rows=self.array_rows_field.value(),
                        columns=self.array_columns_field.value(),
                        row_spacing=self.delta_v_field.value(),
                        column_spacing=self.delta_u_field.value(),
                    )
                else:
                    result = circular_array_entities(
                        source,
                        selected,
                        count=self.count_field.value(),
                        center_mm=(self.center_u_field.value(), self.center_v_field.value()),
                        total_angle_deg=self.pattern_angle_field.value(),
                    )
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self.canvas.message = {
                "offset": "已创建所选元素的平行偏移副本。",
                "linear_array": "已生成线性阵列；数量包含原始元素。",
                "rectangular_array": "已生成矩形阵列；行列数包含原始位置。",
                "circular_array": "已生成环形阵列；完整 360° 阵列不重复首末元素。",
            }[operation]
            self.canvas.replace_draft_entities(
                (*self.canvas.entities, *result[len(source) :]), select_new=True
            )
            return
        if operation == "move" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            delta = (self.delta_u_field.value(), self.delta_v_field.value())
            if math.hypot(*delta) <= 1e-9:
                self.status_label.setText("请指定非零 ΔU / ΔV。")
                return
            self.canvas.committed_move_requested.emit(tuple(self.canvas.selected_entity_ids), delta)
            return
        if operation == "rotate" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            center = (self.center_u_field.value(), self.center_v_field.value())
            error = self.canvas.rotation_draft_error(center, self.angle_field.value())
            if error:
                self.canvas.message = error
                self.canvas.changed.emit()
                return
            self.canvas.rotation_default_angle = self.angle_field.value()
            self.canvas.committed_rotation_requested.emit(
                tuple(self.canvas.selected_entity_ids), center, self.angle_field.value()
            )
            return
        if operation == "mirror" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            start = (self.center_u_field.value(), self.center_v_field.value())
            end = (
                (start[0] + 1.0, start[1])
                if self.mirror_axis_combo.currentText() == "水平轴"
                else (start[0], start[1] + 1.0)
            )
            if self.mirror_keep_source_check.isChecked():
                try:
                    updated = self.canvas.mirror_selected_to_draft(start, end)
                except ValueError as exc:
                    self.status_label.setText(str(exc))
                    return
                self.canvas.message = "已镜像所选元素；副本获得新的草图身份。"
                self.canvas.replace_draft_entities(updated, select_new=True)
            else:
                error = self.canvas.mirror_draft_error(start, end)
                if error:
                    self.canvas.message = error
                    self.canvas.changed.emit()
                    return
                self.canvas.committed_mirror_requested.emit(
                    tuple(self.canvas.selected_entity_ids), start, end
                )
            return
        if operation == "copy" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            delta = (self.delta_u_field.value(), self.delta_v_field.value())
            if math.hypot(*delta) <= 1e-9:
                self.status_label.setText("请指定非零 ΔU / ΔV。")
                return
            try:
                updated = self.canvas.copy_selected_to_draft(delta)
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self.canvas.message = "已复制所选元素；副本获得新的草图身份。"
            self.canvas.replace_draft_entities(updated, select_new=True)
            return
        selected_ids = tuple(
            entity.entity_id
            for entity in self.canvas.entities
            if entity.entity_id in self.canvas.selected_entity_ids
        )
        if not selected_ids:
            self.status_label.setText("先切换到“选择元素”并选择要变换的草图元素。")
            return
        locked_layers = tuple(
            sorted(
                {
                    entity.layer_name
                    for entity in self.canvas.entities
                    if entity.entity_id in selected_ids
                    and self.layer_table.get(entity.layer_name).locked
                },
                key=str.casefold,
            )
        )
        if locked_layers:
            self.status_label.setText(f"选择包含已锁定图层 {locked_layers[0]}；草图未修改。")
            return
        delta = (self.delta_u_field.value(), self.delta_v_field.value())
        if operation in {"move", "copy"} and math.hypot(*delta) <= 1e-9:
            self.status_label.setText(
                "请指定非零 ΔU / ΔV，或使用工具栏按钮在画布上指定基点和目标点。"
            )
            return
        center = (self.center_u_field.value(), self.center_v_field.value())
        angle = self.angle_field.value()
        pattern_angle = self.pattern_angle_field.value()
        offset_distance = self.offset_distance_field.value()
        count = self.count_field.value()

        def transform(entities: tuple[SketchEntity, ...]) -> tuple[SketchEntity, ...]:
            if operation == "move":
                return move_entities(entities, selected_ids, delta, preserve_rectangle_order=True)
            if operation == "copy":
                return copy_entities(entities, selected_ids, delta)
            if operation == "rotate":
                return rotate_entities(entities, selected_ids, center, angle)
            if operation == "offset":
                return offset_entities(
                    entities, selected_ids, offset_distance, gap_type=self.canvas.offset_gap_type
                )
            if operation == "mirror":
                axis_end = (
                    (center[0] + 1.0, center[1])
                    if self.mirror_axis_combo.currentText() == "水平轴"
                    else (center[0], center[1] + 1.0)
                )
                mirrored_ids = selected_ids
                if self.mirror_keep_source_check.isChecked():
                    source_ids = {entity.entity_id for entity in entities}
                    entities = copy_entities(entities, selected_ids, (0.0, 0.0))
                    mirrored_ids = tuple(
                        entity.entity_id
                        for entity in entities
                        if entity.entity_id not in source_ids
                    )
                return mirror_entities(entities, mirrored_ids, center, axis_end)
            if operation == "linear_array":
                return linear_array_entities(entities, selected_ids, count=count, step_mm=delta)
            if operation == "rectangular_array":
                return rectangular_array_entities(
                    entities,
                    selected_ids,
                    rows=self.array_rows_field.value(),
                    columns=self.array_columns_field.value(),
                    row_spacing=delta[1],
                    column_spacing=delta[0],
                )
            return circular_array_entities(
                entities,
                selected_ids,
                count=count,
                center_mm=center,
                total_angle_deg=pattern_angle,
            )

        try:
            updated = transform(tuple(self.canvas.entities))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.canvas.message = {
            "move": "已移动所选元素；草图元素身份保持不变。",
            "copy": "已复制所选元素；副本获得新的草图身份。",
            "rotate": "已绕输入中心逆时针旋转所选元素。",
            "mirror": "已按选择的水平/竖直轴镜像所选元素。",
            "offset": "已创建所选元素的平行偏移副本。",
            "linear_array": "已生成线性阵列；数量包含原始元素。",
            "rectangular_array": "已生成矩形阵列；行列数包含原始位置。",
            "circular_array": "已生成环形阵列；完整 360° 阵列不重复首末元素。",
        }[operation]
        unchanged = updated == tuple(self.canvas.entities)
        applied = self.canvas.replace_draft_entities(
            updated,
            select_new=operation
            in {"copy", "offset", "linear_array", "rectangular_array", "circular_array"}
            or (operation == "mirror" and self.mirror_keep_source_check.isChecked()),
        )
        if operation == "rotate" and (applied or unchanged):
            self.canvas.rotation_default_angle = angle

    def _show_cursor(self, u: float, v: float, snap_kind: str) -> None:
        self.u_field.setValue(u)
        self.v_field.setValue(v)
        suffix = f" · 捕捉：{snap_kind}" if snap_kind else ""
        if self.canvas.tool in {"修剪", "延伸", "分割"}:
            suffix += (
                " · 目标已预选"
                if self.canvas.hovered_line_edit_target_id is not None
                else " · 移到唯一可操作曲线、线段或端点以预选"
            )
        if self.canvas.message:
            suffix += f" · {self.canvas.message}"
        self.status_label.set_transient_text(f"U {u:.4f} mm，V {v:.4f} mm{suffix}")

    def _sync_selection_properties(self) -> None:
        if self._property_feedback_selection and (
            self._property_feedback_selection != frozenset(self.canvas.selected_entity_ids)
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
        ):
            self._property_feedback_selection = frozenset()
            self.property_feedback_label.clear()
            self.property_feedback_label.hide()
        entities = tuple(
            entity
            for entity in self.canvas.selectable_entities()
            if entity.entity_id in self.canvas.selected_entity_ids
        )
        other_count = len(self.canvas.selected_raster_ids) + len(
            self.canvas.selected_constraint_ids
        )
        rows: list[tuple[str, str]] = []
        common_layer: str | None = None
        raster_layer_editable = False
        dimension_layer_editable = False
        mixed_layer_editable = False
        if not entities and not other_count and self._document_metadata is not None:
            metadata = self._document_metadata()
            rows.extend(
                (_DOCUMENT_METADATA_LABELS.get(key, key), metadata.get(key, "—"))
                for key in METADATA_KEYS
            )
        if entities or other_count:
            rows.append(("选中数量", str(len(entities) + other_count)))
        if entities and not other_count:
            names = {
                LineEntity: "直线",
                CircleEntity: "圆",
                ArcEntity: "圆弧",
                PolylineEntity: "多段线",
                RectangleEntity: "矩形",
                PointEntity: "点",
                SplineEntity: "样条曲线",
            }
            kinds = {names.get(type(entity), "二维图元") for entity in entities}
            layers = {entity.layer_name for entity in entities}
            common_layer = next(iter(layers)) if len(layers) == 1 else None
            rows.extend(
                (
                    ("对象类型", next(iter(kinds)) if len(kinds) == 1 else "多种"),
                    ("图层", common_layer if common_layer is not None else "多种"),
                )
            )
            construction_values = {entity.construction for entity in entities}
            construction = (
                next(iter(construction_values)) if len(construction_values) == 1 else None
            )
            rows.append(
                ("构造几何", "多种" if construction is None else "是" if construction else "否")
            )
            if len(layers) == 1:
                layer = self.canvas.layer_table.get(next(iter(layers)))
                color = ", ".join(str(value) for value in layer.color_rgb)
                rows.extend(
                    (
                        ("颜色（随层）", color),
                        ("线型（随层）", layer.linetype),
                        ("线宽（随层）", f"{layer.lineweight_mm:g} mm"),
                    )
                )
            if len(entities) == 1:
                entity = entities[0]
                if isinstance(entity, LineEntity):
                    rows.extend(
                        (
                            ("起点", f"{entity.start_mm[0]:g}, {entity.start_mm[1]:g}"),
                            ("终点", f"{entity.end_mm[0]:g}, {entity.end_mm[1]:g}"),
                            ("长度", f"{math.dist(entity.start_mm, entity.end_mm):g} mm"),
                        )
                    )
                elif isinstance(entity, CircleEntity | ArcEntity):
                    rows.extend(
                        (
                            ("圆心", f"{entity.center_mm[0]:g}, {entity.center_mm[1]:g}"),
                            ("半径", f"{entity.radius_mm:g} mm"),
                        )
                    )
                    if isinstance(entity, ArcEntity):
                        rows.extend(
                            (
                                ("起始角", f"{entity.start_angle_deg:g}°"),
                                ("扫掠角", f"{entity.sweep_angle_deg:g}°"),
                            )
                        )
                elif isinstance(entity, PolylineEntity):
                    rows.extend(
                        (
                            ("顶点数", str(len(entity.points_mm))),
                            ("闭合", "是" if entity.closed else "否"),
                        )
                    )
                elif isinstance(entity, RectangleEntity):
                    rows.extend(
                        (
                            (
                                "第一角点",
                                f"{entity.first_corner_mm[0]:g}, {entity.first_corner_mm[1]:g}",
                            ),
                            (
                                "对角点",
                                f"{entity.opposite_corner_mm[0]:g}, {entity.opposite_corner_mm[1]:g}",
                            ),
                            (
                                "宽度",
                                f"{abs(entity.opposite_corner_mm[0] - entity.first_corner_mm[0]):g} mm",
                            ),
                            (
                                "高度",
                                f"{abs(entity.opposite_corner_mm[1] - entity.first_corner_mm[1]):g} mm",
                            ),
                        )
                    )
                elif isinstance(entity, PointEntity):
                    rows.append(("位置", f"{entity.position_mm[0]:g}, {entity.position_mm[1]:g}"))
                else:
                    rows.append(("控制点数", str(len(entity.control_points_mm))))
        elif other_count == 1 and not entities and len(self.canvas.selected_raster_ids) == 1:
            image = next(
                (
                    item
                    for item in self.canvas.drawing_rasters
                    if item.image_id in self.canvas.selected_raster_ids
                ),
                None,
            )
            if image is not None:
                common_layer = image.layer_name
                raster_layer_editable = True
                rows.extend(
                    (
                        ("对象类型", "图片"),
                        ("图层", image.layer_name),
                        ("位置", f"{image.origin_mm[0]:g}, {image.origin_mm[1]:g}"),
                        ("宽度", f"{image.width_mm:g} mm"),
                        ("高度", f"{image.height_mm:g} mm"),
                        ("旋转角", f"{image.angle_deg:g}°"),
                        ("镜像", "是" if image.mirrored else "否"),
                    )
                )
        elif other_count == 1 and not entities and len(self.canvas.selected_constraint_ids) == 1:
            constraint = next(
                (
                    item
                    for item in self.canvas.dimension_constraints()
                    if item.constraint_id in self.canvas.selected_constraint_ids
                ),
                None,
            )
            if constraint is not None:
                common_layer = self.canvas.annotation_layer(constraint).name
                dimension_layer_editable = constraint.kind in DIMENSION_KINDS
                rows.extend(
                    (
                        ("对象类型", "尺寸标注" if constraint.kind in DIMENSION_KINDS else "约束"),
                        ("图层", common_layer),
                        ("驱动", "是" if constraint.driving else "否"),
                    )
                )
                if constraint.value is not None:
                    unit = f" {constraint.unit}" if constraint.unit else ""
                    value = self.canvas.dimension_display_value(constraint)
                    if value is not None:
                        rows.append(("约束值", f"{value:g}{unit}"))
        elif other_count:
            rows.append(
                (
                    "对象类型",
                    "图片"
                    if not entities and not self.canvas.selected_constraint_ids
                    else "混合选择",
                )
            )
            if self.canvas.selected_raster_ids and not self.canvas.selected_constraint_ids:
                images = tuple(
                    image
                    for image in self.canvas.drawing_rasters
                    if image.image_id in self.canvas.selected_raster_ids
                )
                if len(images) == len(self.canvas.selected_raster_ids):
                    selected_layers = {item.layer_name for item in (*entities, *images)}
                    common_layer = (
                        next(iter(selected_layers)) if len(selected_layers) == 1 else None
                    )
                    rows.append(("图层", common_layer if common_layer is not None else "多种"))
                    mixed_layer_editable = True
        updated = tuple(rows)
        self.property_edit_dimension_button.setEnabled(dimension_layer_editable)
        vertex_entity = (
            entities[0]
            if len(entities) == 1
            and not other_count
            and isinstance(entities[0], PolylineEntity | SplineEntity)
            else None
        )
        self.property_vertex_controls.setVisible(vertex_entity is not None)
        if vertex_entity is not None:
            refresh_vertex = (
                self._property_vertex_identity != vertex_entity.entity_id
                or self._property_entities != entities
            )
            with QSignalBlocker(self.property_vertex_index):
                self.property_vertex_index.setMaximum(
                    len(self.canvas.entity_point_references(vertex_entity))
                )
                if self._property_vertex_identity != vertex_entity.entity_id:
                    self.property_vertex_index.setValue(1)
            self._property_vertex_identity = vertex_entity.entity_id
            self.property_vertex_label.setText(
                "顶点" if isinstance(vertex_entity, PolylineEntity) else "控制点"
            )
            if refresh_vertex:
                self._refresh_property_vertex()
        else:
            self._property_vertex_identity = ""
            self.canvas.active_property_vertex = None
            self.canvas.update()
        layer_choices = (
            tuple(
                layer.name
                for layer in self.canvas.layer_table.layers
                if layer.displayed and not layer.locked
            )
            if (
                entities
                and not other_count
                or raster_layer_editable
                or dimension_layer_editable
                or mixed_layer_editable
            )
            and self.canvas.select_committed_entities
            else ()
        )
        revision = (
            self.canvas.source_revision_provider()
            if self.canvas.source_revision_provider is not None
            else None
        )
        if (
            updated == self._property_rows
            and layer_choices == self._property_layer_choices
            and entities == self._property_entities
            and revision == self._property_revision
        ):
            return
        self._property_rows = updated
        self._property_entities = entities
        self._property_revision = revision
        self._property_layer_choices = layer_choices
        self.property_layer_combo = None
        self.property_construction_combo = None
        self.properties_table.setRowCount(0)
        self.properties_table.setRowCount(len(updated))
        for row, (name, value) in enumerate(updated):
            self.properties_table.setItem(row, 0, QTableWidgetItem(name))
            value_item = QTableWidgetItem(value)
            if (
                len(entities) == 1
                and not other_count
                and self._property_coordinate_index(entities[0], name) is not None
            ):
                value_item.setToolTip("双击输入新的绝对坐标（x,y，单位 mm）。")
            elif (
                len(entities) == 1
                and not other_count
                and isinstance(entities[0], CircleEntity | ArcEntity)
                and name == "半径"
            ):
                value_item.setToolTip("双击输入新的半径（单位 mm）。")
            elif (
                len(entities) == 1
                and not other_count
                and isinstance(entities[0], LineEntity)
                and name == "长度"
            ):
                value_item.setToolTip("双击输入新的长度，以起点为基准保持方向（单位 mm）。")
            self.properties_table.setItem(row, 1, value_item)
            entity = entities[0] if len(entities) == 1 and not other_count else None
            coordinate_index = self._property_coordinate_index(entity, name) if entity else None
            if entity is not None and coordinate_index is not None:
                _reference, point = self.canvas.entity_point_references(entity)[coordinate_index]
                coordinate_field = QLineEdit(f"{point[0]!r},{point[1]!r}")
                coordinate_field.setToolTip("输入绝对坐标 x,y（mm），按 Enter 确认。")
                revision = (
                    self.canvas.source_revision_provider()
                    if self.canvas.source_revision_provider is not None
                    else None
                )
                coordinate_field.returnPressed.connect(
                    partial(
                        self._commit_property_coordinate,
                        coordinate_field,
                        entity,
                        coordinate_index,
                        name,
                        revision,
                    )
                )
                self.properties_table.setCellWidget(row, 1, coordinate_field)
            elif (
                entity is not None
                and isinstance(entity, CircleEntity | ArcEntity)
                and name == "半径"
            ):
                radius_field = QLineEdit(repr(entity.radius_mm))
                radius_field.setToolTip("输入半径（mm），按 Enter 确认。")
                revision = (
                    self.canvas.source_revision_provider()
                    if self.canvas.source_revision_provider is not None
                    else None
                )
                radius_field.returnPressed.connect(
                    partial(self._commit_property_radius, radius_field, entity, revision)
                )
                self.properties_table.setCellWidget(row, 1, radius_field)
            elif (
                name == "长度"
                and len(entities) == 1
                and not other_count
                and isinstance(entities[0], LineEntity)
            ):
                line = entities[0]
                length_field = QLineEdit(repr(math.dist(line.start_mm, line.end_mm)))
                length_field.setObjectName("propertyLineLength")
                length_field.setToolTip("输入长度（mm），按 Enter 确认；保持起点与方向。")
                revision = (
                    self.canvas.source_revision_provider()
                    if self.canvas.source_revision_provider is not None
                    else None
                )
                length_field.returnPressed.connect(
                    partial(self._commit_property_length, length_field, line, revision)
                )
                self.properties_table.setCellWidget(row, 1, length_field)
            elif name == "图层" and layer_choices:
                combo = QComboBox()
                if common_layer is None or common_layer not in layer_choices:
                    combo.addItem(value, None)
                for layer_name in layer_choices:
                    combo.addItem(layer_name, layer_name)
                combo.setCurrentText(value)
                combo.setToolTip("更改选中对象的图层，不改变当前绘图层。")
                combo.activated.connect(partial(self._assign_property_layer, combo, common_layer))
                self.properties_table.setCellWidget(row, 1, combo)
                self.property_layer_combo = combo
            elif (
                name == "构造几何"
                and entities
                and not other_count
                and self.canvas.select_committed_entities
            ):
                combo = QComboBox()
                if value == "多种":
                    combo.addItem("多种", None)
                combo.addItem("否", False)
                combo.addItem("是", True)
                combo.setCurrentText(value)
                combo.setToolTip("将选中图元设置为构造几何或普通几何。")
                combo.activated.connect(partial(self._assign_property_construction, combo, value))
                self.properties_table.setCellWidget(row, 1, combo)
                self.property_construction_combo = combo

    def refresh_document_properties(self) -> None:
        """Refresh the empty-selection view after document metadata changes."""
        self._sync_selection_properties()

    def _assign_property_construction(self, combo: QComboBox, old: str, index: int) -> None:
        value: object = combo.itemData(index)
        with QSignalBlocker(combo):
            combo.setCurrentText(old)
        if not isinstance(value, bool) or (old != "多种" and value == (old == "是")):
            return
        if self._navigation_busy() or self.canvas.active_transform is not None:
            self.status_label.setText("请先完成或取消当前操作，再更改构造几何。")
            return
        self.assign_selection_construction_requested.emit(
            tuple(sorted(self.canvas.selected_entity_ids)), value
        )

    @staticmethod
    def _property_coordinate_index(entity: SketchEntity, label: str) -> int | None:
        if isinstance(entity, LineEntity):
            return {"起点": 0, "终点": 1}.get(label)
        if isinstance(entity, CircleEntity | ArcEntity):
            return 0 if label == "圆心" else None
        if isinstance(entity, RectangleEntity):
            return {"第一角点": 0, "对角点": 2}.get(label)
        if isinstance(entity, PointEntity):
            return 0 if label == "位置" else None
        return None

    def _edit_property_coordinate(self, item: QTableWidgetItem) -> None:
        if (
            item.column() != 1
            or self._navigation_busy()
            or self.canvas.active_transform is not None
        ):
            return
        if (
            len(self.canvas.selected_entity_ids) != 1
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or (self._can_finish is not None and not self._can_finish())
        ):
            return
        identity = next(iter(self.canvas.selected_entity_ids))
        entities = [e for e in self.canvas.selectable_entities() if e.entity_id == identity]
        if len(entities) != 1:
            return
        entity = entities[0]
        label_item = self.properties_table.item(item.row(), 0)
        if label_item is None:
            return
        label = label_item.text()
        if isinstance(entity, CircleEntity | ArcEntity) and label == "半径":
            self._edit_property_radius(entity)
            return
        index = self._property_coordinate_index(entity, label)
        if index is None:
            return
        self._edit_property_handle(entity, index, label)

    def _edit_property_radius(
        self,
        entity: CircleEntity | ArcEntity,
        *,
        input_value: str | None = None,
        input_revision: int | None = None,
    ) -> None:
        layer = self.canvas.layer_table.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            self.status_label.setText("目标图元所在图层已锁定或隐藏。")
            return
        revision = (
            input_revision
            if input_value is not None
            else (
                self.canvas.source_revision_provider()
                if self.canvas.source_revision_provider is not None
                else None
            )
        )
        value, accepted = (
            (input_value, True)
            if input_value is not None
            else QInputDialog.getText(
                self, "编辑半径", "半径（单位 mm）：", text=repr(entity.radius_mm)
            )
        )
        if not accepted:
            return
        if (
            self._navigation_busy()
            or self.canvas.active_transform is not None
            or self.canvas.selected_entity_ids != {entity.entity_id}
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or entity not in self.canvas.selectable_entities()
            or (self._can_finish is not None and not self._can_finish())
            or (
                revision is not None
                and self.canvas.source_revision_provider is not None
                and self.canvas.source_revision_provider() != revision
            )
        ):
            self.status_label.setText("选择或图纸已变化；半径未修改。")
            return
        try:
            radius = float(value)
            factor = radius / entity.radius_mm
            if not math.isfinite(radius) or radius <= 1e-9 or not math.isfinite(factor):
                raise ValueError
        except (OverflowError, ValueError):
            self.status_label.setText("请输入大于零的有限半径。")
            return
        if radius == entity.radius_mm:
            self.status_label.setText("半径未改变。")
            return
        if entity in self.canvas.entities and (
            self.canvas.pending_cross_tangencies or self.canvas.pending_associative_arrays
        ):
            self.status_label.setText("请先完成或撤销当前暂存关联编辑，再修改半径。")
            return
        if entity in self.canvas.entities and self.canvas.constraints:
            original = self.dimension_sources()[0]
            candidate = SketchConstraint(
                uuid4().hex,
                "radius",
                (SketchGeometryReference(entity.entity_id, "geometry"),),
                radius,
                "mm",
            )
            result = self.preview_dimension(original, candidate)
            if result.status != "success" or result.sketch is None:
                self.status_label.setText(result.message or "约束冲突；半径未修改。")
                return
            if result.branch_changes:
                self.status_label.setText("修改会切换几何约束分支，请使用尺寸编辑确认。")
                return
            solved = replace(
                result.sketch,
                constraints=tuple(
                    item
                    for item in result.sketch.constraints
                    if item.constraint_id != candidate.constraint_id
                ),
            )
            previous = {item.entity_id: item for item in original.entities}
            if any(
                previous.get(item.entity_id) != item
                and (
                    self.layer_table.get(item.layer_name).locked
                    or not self.layer_table.get(item.layer_name).displayed
                )
                for item in solved.entities
            ):
                self.status_label.setText("求解涉及锁定或隐藏图层；半径未修改。")
                return
            if not self.canvas.apply_constraint_solution(original, solved):
                self.status_label.setText("草图已变化；半径未修改。")
                return
            self.status_label.setText(self.canvas.message)
            return
        saved = entity not in self.canvas.entities
        applied = self.canvas.scale_selection_about(entity.center_mm, factor)
        if not saved or not applied:
            self.status_label.setText(self.canvas.message)

    def _refresh_property_vertex(self) -> None:
        entity = next(
            (
                item
                for item in self.canvas.selectable_entities()
                if item.entity_id == self._property_vertex_identity
            ),
            None,
        )
        if not isinstance(entity, PolylineEntity | SplineEntity):
            return
        index = self.property_vertex_index.value() - 1
        references = self.canvas.entity_point_references(entity)
        if 0 <= index < len(references):
            _reference, point = references[index]
            self.property_vertex_coordinate.setText(f"{point[0]!r},{point[1]!r}")
            self.canvas.active_property_vertex = (entity.entity_id, index)
            self.canvas.update()

    def _select_property_vertex(self, identity: str, index: int) -> None:
        if identity == self._property_vertex_identity:
            self.property_vertex_index.setValue(index + 1)
            self._refresh_property_vertex()

    def _commit_property_vertex(self) -> None:
        entity = next(
            (
                item
                for item in self.canvas.selectable_entities()
                if item.entity_id == self._property_vertex_identity
            ),
            None,
        )
        if not isinstance(entity, PolylineEntity | SplineEntity):
            return
        index = self.property_vertex_index.value() - 1
        revision = self._property_revision
        label = f"{self.property_vertex_label.text()} {index + 1}"
        self._commit_property_coordinate(
            self.property_vertex_coordinate, entity, index, label, revision
        )

    def _edit_property_handle(
        self,
        entity: SketchEntity,
        index: int,
        label: str,
        *,
        input_value: str | None = None,
        input_revision: int | None = None,
    ) -> None:
        identity = entity.entity_id
        layer = self.canvas.layer_table.get(entity.layer_name)
        if layer.locked or not layer.displayed:
            self.status_label.setText("目标图元所在图层已锁定或隐藏。")
            return
        reference, origin = self.canvas.entity_point_references(entity)[index]
        revision = (
            input_revision
            if input_value is not None
            else (
                self.canvas.source_revision_provider()
                if self.canvas.source_revision_provider is not None
                else None
            )
        )
        value, accepted = (
            (input_value, True)
            if input_value is not None
            else QInputDialog.getText(
                self,
                "编辑坐标",
                f"{label}（绝对坐标 x,y，单位 mm）",
                text=f"{origin[0]!r},{origin[1]!r}",
            )
        )
        if not accepted:
            return
        if (
            self._navigation_busy()
            or self.canvas.active_transform is not None
            or self.canvas.selected_entity_ids != {identity}
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or entity not in self.canvas.selectable_entities()
            or (self._can_finish is not None and not self._can_finish())
            or (
                revision is not None
                and self.canvas.source_revision_provider is not None
                and self.canvas.source_revision_provider() != revision
            )
        ):
            self.status_label.setText("选择或图纸已变化；坐标未修改。")
            return
        try:
            point = parse_coordinate(value, None)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.canvas.edit_handle_coordinate(entity, reference, origin, point)
        self.status_label.setText(self.canvas.message)

    def _commit_property_coordinate(
        self, field: QLineEdit, entity: SketchEntity, index: int, label: str, revision: int | None
    ) -> None:
        self._begin_property_feedback(entity.entity_id, label)
        self._edit_property_handle(
            entity, index, label, input_value=field.text(), input_revision=revision
        )

    def _commit_property_radius(
        self, field: QLineEdit, entity: CircleEntity | ArcEntity, revision: int | None
    ) -> None:
        self._begin_property_feedback(entity.entity_id, "半径")
        self._edit_property_radius(entity, input_value=field.text(), input_revision=revision)

    def _begin_property_feedback(self, identity: str, name: str) -> None:
        self._property_feedback_selection = frozenset({identity})
        self._property_feedback_name = name
        self.property_feedback_label.clear()
        self.property_feedback_label.hide()
        self.status_label.setText("")

    def _update_property_feedback(self, text: str) -> None:
        if (
            self._property_feedback_selection == frozenset(self.canvas.selected_entity_ids)
            and self._property_feedback_selection
        ):
            self.property_feedback_label.setText(text)
            self.property_feedback_label.setVisible(bool(text))
            if "未修改" in text:
                self._restore_property_field()

    def _restore_property_field(self) -> None:
        entities = [
            entity
            for entity in self.canvas.selectable_entities()
            if entity.entity_id in self._property_feedback_selection
        ]
        if len(entities) != 1:
            return
        entity = entities[0]
        name = self._property_feedback_name
        if name.startswith(("顶点 ", "控制点 ")):
            self._refresh_property_vertex()
            return
        if name == "长度" and isinstance(entity, LineEntity):
            value = repr(math.dist(entity.start_mm, entity.end_mm))
        elif name == "半径" and isinstance(entity, CircleEntity | ArcEntity):
            value = repr(entity.radius_mm)
        else:
            index = self._property_coordinate_index(entity, name)
            if index is None:
                return
            _reference, point = self.canvas.entity_point_references(entity)[index]
            value = f"{point[0]!r},{point[1]!r}"
        for row in range(self.properties_table.rowCount()):
            label = self.properties_table.item(row, 0)
            if label is not None and label.text() == name:
                field = self.properties_table.cellWidget(row, 1)
                if isinstance(field, QLineEdit):
                    field.setText(value)
                return

    def _commit_property_length(
        self, field: QLineEdit, line: LineEntity, revision: int | None
    ) -> None:
        self._begin_property_feedback(line.entity_id, "长度")
        if (
            self._navigation_busy()
            or self.canvas.active_transform is not None
            or self.canvas.selected_entity_ids != {line.entity_id}
            or self.canvas.selected_constraint_ids
            or self.canvas.selected_raster_ids
            or line not in self.canvas.selectable_entities()
            or (self._can_finish is not None and not self._can_finish())
            or (
                revision is not None
                and self.canvas.source_revision_provider is not None
                and self.canvas.source_revision_provider() != revision
            )
        ):
            self.status_label.setText("选择或图纸已变化；长度未修改。")
            return
        layer = self.canvas.layer_table.get(line.layer_name)
        if layer.locked or not layer.displayed:
            self.status_label.setText("目标图元所在图层已锁定或隐藏。")
            return
        try:
            length = float(field.text())
            original_length = math.dist(line.start_mm, line.end_mm)
            if not math.isfinite(length) or length <= 1e-9 or original_length <= 1e-9:
                raise ValueError
            ratio = length / original_length
            point = (
                (
                    line.start_mm[0] + (line.end_mm[0] - line.start_mm[0]) * ratio,
                    line.start_mm[1] + (line.end_mm[1] - line.start_mm[1]) * ratio,
                )
                if length != original_length
                else line.end_mm
            )
            if not all(math.isfinite(coordinate) for coordinate in point):
                raise ValueError
        except ValueError:
            self.status_label.setText("请输入大于零的有限长度。")
            return
        reference, origin = self.canvas.entity_point_references(line)[1]
        self.canvas.edit_handle_coordinate(
            line, reference, origin, point, expected_line=replace(line, end_mm=point)
        )
        self.status_label.setText(self.canvas.message)

    def _edit_property_dimension(self) -> None:
        if (
            len(self.canvas.selected_constraint_ids) != 1
            or self.canvas.selected_entity_ids
            or self.canvas.selected_raster_ids
        ):
            self.status_label.setText("请先只选择一个尺寸。")
            return
        identity = next(iter(self.canvas.selected_constraint_ids))
        matches = tuple(
            (sketch, constraint)
            for sketch in self.dimension_sources()
            for constraint in sketch.constraints
            if constraint.constraint_id == identity and constraint.kind in DIMENSION_KINDS
        )
        if len(matches) != 1:
            self.status_label.setText("尺寸来源不存在或不唯一，请重新选择。")
            return
        self.dimensions.edit(*matches[0])

    def _assign_dimension_layer(self, target: str) -> None:
        if self._can_finish is not None and not self._can_finish():
            self.status_label.setText("工作线程忙碌，请稍后修改图层。")
            return
        constraint = next(
            (
                item
                for item in self.canvas.dimension_constraints()
                if item.constraint_id in self.canvas.selected_constraint_ids
                and item.kind in DIMENSION_KINDS
            ),
            None,
        )
        if constraint is None:
            self.status_label.setText("所选尺寸已变化，请重新选择。")
            return
        if (
            self.canvas.mixed_move
            or self.canvas.pending_cross_tangencies
            or self.canvas.pending_associative_arrays
        ):
            self.status_label.setText("请先完成或撤销当前暂存关联编辑，再更改图层。")
            return
        try:
            source_layer = self.canvas.annotation_layer(constraint)
            target_layer = self.canvas.layer_table.get(target)
            if (
                source_layer.locked
                or not source_layer.displayed
                or target_layer.locked
                or not target_layer.displayed
            ):
                raise ValueError("来源或目标图层已锁定、隐藏或冻结。")
            if (
                constraint.layer_name is not None
                and constraint.layer_name.casefold() == target_layer.name.casefold()
            ):
                self.status_label.setText("所选尺寸已经位于当前图层。")
                return
            if (
                self.canvas.source_revision_provider is not None
                and self.canvas.source_context_revision is not None
                and self.canvas.source_revision_provider() != self.canvas.source_context_revision
            ):
                raise ValueError("图纸已变化，请重新选择尺寸。")
            sources = self.dimension_sources()
            matching = tuple(
                sketch
                for sketch in sources
                if any(
                    item.constraint_id == constraint.constraint_id for item in sketch.constraints
                )
            )
            if len(matching) != 1:
                raise ValueError("尺寸来源不存在或不唯一，请重新选择。")
            original = matching[0]
            if original.sketch_id != sources[0].sketch_id:
                self.request_layer_update(
                    self.layer_table,
                    self.dimension_layer,
                    (
                        {
                            "sketch_id": original.sketch_id,
                            "constraint_ids": [constraint.constraint_id],
                            "layer_name": target,
                        },
                    ),
                )
                return
            updated = replace(
                original,
                constraints=tuple(
                    replace(item, layer_name=target)
                    if item.constraint_id == constraint.constraint_id
                    else item
                    for item in original.constraints
                ),
            )
            if not self.canvas.apply_constraint_solution(original, updated):
                raise ValueError("草稿已变化，请重新选择尺寸。")
            self.status_label.setText(f"已将尺寸移至图层 {target}；可撤销。")
        except (KeyError, ValueError) as exc:
            self.status_label.setText(str(exc))

    def _assign_property_layer(self, combo: QComboBox, old: str | None, index: int) -> None:
        target = combo.itemData(index)
        with QSignalBlocker(combo):
            combo.setCurrentText(old if old is not None else "多种")
        if not isinstance(target, str) or target == old:
            return
        if (
            len(self.canvas.selected_constraint_ids) == 1
            and not self.canvas.selected_entity_ids
            and not self.canvas.selected_raster_ids
        ):
            self._assign_dimension_layer(target)
            return
        if (
            self.canvas.selected_raster_ids
            and not self.canvas.selected_entity_ids
            and not self.canvas.selected_constraint_ids
        ):
            images = tuple(
                item
                for item in self.canvas.drawing_rasters
                if item.image_id in self.canvas.selected_raster_ids
            )
            if len(images) != len(self.canvas.selected_raster_ids):
                self.status_label.setText("所选图片已变化，请重新选择。")
                return
            try:
                for image in images:
                    layer = self.canvas.layer_table.get(image.layer_name)
                    if layer.locked or not layer.displayed:
                        raise ValueError("图片所在图层已锁定或隐藏。")
                updated_images = tuple(replace(image, layer_name=target) for image in images)
                if len(updated_images) == 1 and self.canvas.commit_raster_edit is not None:
                    self.canvas.commit_raster_edit("update", updated_images[0])
                elif self.canvas.commit_raster_batch is not None:
                    self.canvas.commit_raster_batch("update", updated_images)
                else:
                    raise ValueError("图片更新服务不可用。")
            except (KeyError, ValueError) as exc:
                self.status_label.setText(str(exc))
            return
        if self.canvas.selected_constraint_ids:
            self.status_label.setText("请仅选择二维图元后更改图层。")
            return
        selected = tuple(self.canvas.selected_entity_ids)
        if selected:
            self.assign_selection_layer_requested.emit(selected, target)

    def _sync_state(self) -> None:
        self.tangent_capture_button.setEnabled(self.canvas.tool in {"直线", "圆", "圆弧"})
        if (
            self.layer_table != self.canvas.layer_table
            or self.layer_combo.currentText() != self.canvas.active_layer_name
        ):
            self.layer_table = self.canvas.layer_table
            self._rebuild_layer_combo(self.layer_table, self.canvas.active_layer_name)
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.canvas.active_layer_name
                )
        for name, button in self.tool_buttons.items():
            button.setChecked(self.canvas.tool == name)
        with QSignalBlocker(self.tool_combo):
            self.tool_combo.setCurrentText(self.canvas.tool)
        plane = self.plane_combo.currentText()
        for field in self.origin_fields.values():
            field.setReadOnly(self._support_face is not None or self.canvas.mixed_move is not None)
        horizontal, vertical = {"XY": ("X", "Y"), "XZ": ("X", "−Z"), "YZ": ("Y", "Z")}.get(
            plane, ("U", "V")
        )
        self.canvas.ucs_plane = plane
        origin = ", ".join(f"{self.origin_fields[axis].value():g}" for axis in ("X", "Y", "Z"))
        self.ucs_label.setText(f"UCS · {plane} · {horizontal}→ / {vertical}↑ · 原点 ({origin}) mm")
        self.close_chain_button.setEnabled(self.canvas.can_close_chain)
        self.end_chain_button.setEnabled(
            self.canvas.tool == "直线" and self.canvas.pending_point_count > 0
        )
        selected_count = len(self.canvas.selected_entity_ids)
        suffix = f" · 已选 {selected_count}" if selected_count else ""
        if self._context_frame != self.current_frame():
            self._context_frame = self.current_frame()
            self.canvas.set_background_sketches(self._context_sketches, self._context_frame)
        background_count = sum(
            layer.displayed for _entity, layer in self.canvas.background_entities
        )
        if background_count:
            label = "已提交图元" if self.canvas.select_committed_entities else "已提交参照"
            suffix += f" · {label} {background_count}"
        self.entity_count_label.setText(f"{len(self.canvas.entities)} 个草图元素{suffix}")
        self.finish_button.setEnabled(
            (bool(self.canvas.entities) or self.canvas.mixed_move is not None)
            and not self.canvas.has_pending_geometry
            and not self.canvas.has_active_edit_gesture
        )
        self.finish_polyline_button.setEnabled(
            (self.canvas.tool == "多段线" and self.canvas.pending_point_count >= 2)
            or (self.canvas.tool == "样条曲线" and self.canvas.pending_point_count >= 4)
        )
        self.finish_polyline_button.setText(
            "完成样条" if self.canvas.tool == "样条曲线" else "完成多段线"
        )
        self.undo_entity_button.setEnabled(
            self.canvas.can_undo or bool(self.layer_history_boundaries)
        )
        self.redo_entity_button.setEnabled(self.canvas.can_redo or bool(self.layer_history_redo))
        for operation, button in self.transform_buttons.items():
            button.setEnabled(
                not self.canvas.has_pending_geometry
                and not self.canvas.has_active_edit_gesture
                and (
                    operation in {"move", "copy", "rotate", "scale", "mirror"}
                    or (self.canvas.tool == "选择元素" and bool(selected_count))
                )
            )
        message = self.canvas.message
        notice = self.canvas.pending_tangency_removal_notice
        if notice:
            message = f"{message} {notice}" if message else notice
        if message:
            self.status_label.setText(message)
        self._sync_navigation()
        self._sync_selection_properties()
